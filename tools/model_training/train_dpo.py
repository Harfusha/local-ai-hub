"""Direct Preference Optimization (DPO) trainer for anti-hallucination alignment.

Implements native DPO log-ratio loss (Rafailov et al., 2023) using PEFT LoRA adapter
toggling (with model.disable_adapter() as the reference model). Trains on
chosen vs rejected response pairs to suppress hallucinated symbols and fictitious quotes.
"""

from __future__ import annotations

import json
import logging
# import math
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


def compute_sequence_logps(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """Compute per-example log probability sum over target tokens (ignoring label -100)."""
    # Shift so that tokens < n predict n
    shift_logits = logits[..., :-1, :].contiguous()
    shift_labels = labels[..., 1:].contiguous()
    
    loss_fct = torch.nn.CrossEntropyLoss(reduction="none", ignore_index=-100)
    # loss is -log P
    token_losses = loss_fct(
        shift_logits.view(-1, shift_logits.size(-1)),
        shift_labels.view(-1),
    ).view(shift_labels.size())

    # Sum log probabilities for non-masked tokens
    mask = (shift_labels != -100).float()
    logps = -(token_losses * mask).sum(dim=-1)
    return logps


def dpo_loss(
    policy_chosen_logps: torch.Tensor,
    policy_rejected_logps: torch.Tensor,
    reference_chosen_logps: torch.Tensor,
    reference_rejected_logps: torch.Tensor,
    beta: float = 0.1,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Compute exact DPO loss, chosen rewards, and rejected rewards."""
    pi_logratios = policy_chosen_logps - policy_rejected_logps
    ref_logratios = reference_chosen_logps - reference_rejected_logps

    logits = pi_logratios - ref_logratios
    losses = -F.logsigmoid(beta * logits)

    chosen_rewards = beta * (policy_chosen_logps - reference_chosen_logps).detach()
    rejected_rewards = beta * (policy_rejected_logps - reference_rejected_logps).detach()

    return losses.mean(), chosen_rewards.mean(), rejected_rewards.mean()


def load_dpo_dataset(jsonl_path: str | Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Load DPO preference pairs (prompt, chosen, rejected)."""
    pairs: list[dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if limit and idx >= limit:
                break
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if "prompt" in item and "chosen" in item and "rejected" in item:
                pairs.append(item)
    return pairs


def encode_dpo_pair(
    tokenizer: Any,
    prompt: str,
    chosen: str,
    rejected: str,
    max_length: int = 4096,
) -> tuple[tuple[torch.Tensor, torch.Tensor], tuple[torch.Tensor, torch.Tensor]]:
    """Encode chosen and rejected chat completions with target masking."""
    prompt_msgs = [{"role": "system", "content": "You are a precise code analysis assistant."}, {"role": "user", "content": prompt}]
    prefix_ids = tokenizer.apply_chat_template(prompt_msgs, tokenize=True, add_generation_prompt=True)
    
    # Chosen
    chosen_full = tokenizer.apply_chat_template(prompt_msgs + [{"role": "assistant", "content": chosen}], tokenize=True)
    chosen_labels = [-100] * len(prefix_ids) + chosen_full[len(prefix_ids):]
    
    # Rejected
    rejected_full = tokenizer.apply_chat_template(prompt_msgs + [{"role": "assistant", "content": rejected}], tokenize=True)
    rejected_labels = [-100] * len(prefix_ids) + rejected_full[len(prefix_ids):]

    # Truncate
    c_ids = torch.tensor(chosen_full[:max_length], dtype=torch.long)
    c_lbl = torch.tensor(chosen_labels[:max_length], dtype=torch.long)
    r_ids = torch.tensor(rejected_full[:max_length], dtype=torch.long)
    r_lbl = torch.tensor(rejected_labels[:max_length], dtype=torch.long)

    return (c_ids, c_lbl), (r_ids, r_lbl)


def run_dpo_training(
    model: Any,
    tokenizer: Any,
    dpo_data_path: str | Path,
    output_dir: str | Path,
    beta: float = 0.1,
    learning_rate: float = 5e-6,
    epochs: int = 1,
    max_steps: int | None = None,
    device: str = "cuda",
) -> dict[str, Any]:
    """Train LoRA adapter with DPO loss on preference pairs."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    dataset = load_dpo_dataset(dpo_data_path)
    if not dataset:
        raise ValueError(f"No DPO pairs found in {dpo_data_path}")

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=learning_rate,
        weight_decay=0.01,
    )

    model.train()
    total_loss = 0.0
    step = 0
    t0 = time.perf_counter()

    for epoch in range(epochs):
        for item in dataset:
            if max_steps and step >= max_steps:
                break

            (c_ids, c_lbl), (r_ids, r_lbl) = encode_dpo_pair(
                tokenizer, item["prompt"], item["chosen"], item["rejected"]
            )

            c_ids = c_ids.unsqueeze(0).to(device)
            c_lbl = c_lbl.unsqueeze(0).to(device)
            r_ids = r_ids.unsqueeze(0).to(device)
            r_lbl = r_lbl.unsqueeze(0).to(device)

            # 1. Reference forward passes with LoRA disabled
            with torch.no_grad():
                with model.disable_adapter():
                    ref_c_logits = model(c_ids).logits
                    ref_c_logps = compute_sequence_logps(ref_c_logits, c_lbl)
                    ref_r_logits = model(r_ids).logits
                    ref_r_logps = compute_sequence_logps(ref_r_logits, r_lbl)

            # 2. Policy forward passes with active LoRA
            pi_c_logits = model(c_ids).logits
            pi_c_logps = compute_sequence_logps(pi_c_logits, c_lbl)
            pi_r_logits = model(r_ids).logits
            pi_r_logps = compute_sequence_logps(pi_r_logits, r_lbl)

            # 3. Loss & backward
            loss, c_rew, r_rew = dpo_loss(
                pi_c_logps, pi_r_logps, ref_c_logps, ref_r_logps, beta=beta
            )

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            step += 1

    elapsed = time.perf_counter() - t0
    avg_loss = total_loss / max(1, step)

    # Save aligned adapter
    adapter_save_dir = output_path / "dpo_adapter"
    model.save_pretrained(str(adapter_save_dir))
    tokenizer.save_pretrained(str(adapter_save_dir))

    summary = {
        "status": "completed",
        "dpo_steps": step,
        "epochs": epochs,
        "average_loss": avg_loss,
        "elapsed_seconds": elapsed,
        "adapter_dir": str(adapter_save_dir),
    }
    with open(output_path / "dpo_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary
