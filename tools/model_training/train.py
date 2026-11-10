from __future__ import annotations

import hashlib
import json
import random
import subprocess
import time
import gc
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .manifest import load_run_manifest, validate_dataset_pair
from .runtime import resolve_runtime


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_ids(value: Any) -> list[int]:
    if isinstance(value, dict):
        value = value["input_ids"]
    elif hasattr(value, "input_ids"):
        value = value.input_ids
    if hasattr(value, "tolist"):
        value = value.tolist()
    if len(value) and isinstance(value[0], list):
        value = value[0]
    return [int(item) for item in value]


def _encode_example(tokenizer: Any, row: dict[str, Any], max_length: int) -> tuple[list[int], list[int]]:
    messages = row["messages"]
    prefix = _input_ids(tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True))
    full = _input_ids(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False))
    if full[: len(prefix)] != prefix:
        raise ValueError(f"chat template prefix mismatch in dataset row {row['id']}")
    answer = full[len(prefix) :]
    if not answer:
        raise ValueError(f"empty assistant target in dataset row {row['id']}")
    if len(answer) > max_length:
        raise ValueError(f"assistant target exceeds max_length in dataset row {row['id']}")
    prefix = prefix[-(max_length - len(answer)) :] if len(prefix) + len(answer) > max_length else prefix
    input_ids = prefix + answer
    labels = [-100] * len(prefix) + answer
    return input_ids, labels


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def train_from_manifest(manifest_path: Path | str, *, allow_model_download: bool = False) -> dict[str, Any]:
    config = load_run_manifest(manifest_path)
    dataset_summary = validate_dataset_pair(config["train_file"], config["evaluation_file"])
    training = config.get("training", {})
    runtime = resolve_runtime(device=str(training.get("device", "cuda")))
    quantization = str(training.get("quantization", "none"))
    if quantization not in {"none", "4bit"}:
        raise ValueError("training.quantization must be none or 4bit")
    if quantization == "4bit" and runtime["device"] != "cuda":
        raise ValueError("4bit QLoRA requires CUDA")
    output_dir = Path(config["output_dir"])
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("training needs torch, transformers, peft, and accelerate") from exc

    base_model = str(config["base_model"])
    is_local = Path(base_model).exists()
    if not is_local and not allow_model_download:
        raise ValueError("base model is not a local path; pass --allow-model-download to fetch it")
    local_files_only = not allow_model_download
    dtype_name = runtime["precision"]
    attention = str(training.get("attention", runtime["attention"]))
    if attention not in {"sdpa", "eager"}:
        raise ValueError("training.attention must be sdpa or eager")
    tokenizer = AutoTokenizer.from_pretrained(
        base_model, local_files_only=local_files_only, revision=config.get("revision"), trust_remote_code=False
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    load_options: dict[str, Any] = {}
    if quantization == "4bit":
        try:
            from peft import prepare_model_for_kbit_training
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError("4bit QLoRA needs bitsandbytes and current transformers/peft") from exc
        load_options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=runtime["dtype"],
        )
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        local_files_only=local_files_only,
        revision=config.get("revision"),
        trust_remote_code=False,
        dtype=runtime["dtype"],
        device_map={"": 0 if runtime["device"] == "cuda" else "cpu"},
        attn_implementation=attention,
        use_safetensors=True,
        **load_options,
    )
    model.config.use_cache = False
    checkpointing = bool(training.get("gradient_checkpointing", True))
    if quantization == "4bit":
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=checkpointing)
    if checkpointing:
        if quantization != "4bit":
            model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
            model.enable_input_require_grads()
    lora = config.get("lora", {})
    lora_config = LoraConfig(
        r=int(lora.get("r", 8)),
        lora_alpha=int(lora.get("alpha", 16)),
        lora_dropout=float(lora.get("dropout", 0.05)),
        target_modules=lora.get("target_modules", ["q_proj", "k_proj", "v_proj", "o_proj"]),
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.train()
    train_rows = [json.loads(line) for line in Path(config["train_file"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    encoded = [
        _encode_example(tokenizer, row, int(training.get("max_length", 2048)))
        for row in train_rows
    ]
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not trainable:
        raise RuntimeError("LoRA produced no trainable parameters")
    try:
        optimizer = torch.optim.AdamW(
            trainable,
            lr=float(training.get("learning_rate", 2e-4)),
            fused=bool(runtime["fused_optimizer"]),
        )
        optimizer_fused = bool(runtime["fused_optimizer"])
    except (TypeError, RuntimeError):
        optimizer = torch.optim.AdamW(trainable, lr=float(training.get("learning_rate", 2e-4)))
        optimizer_fused = False
    scaler = torch.amp.GradScaler("cuda", enabled=runtime["device"] == "cuda" and dtype_name == "fp16")
    batch_size = int(training.get("batch_size", 1))
    accumulation = int(training.get("gradient_accumulation_steps", 4))
    epochs = int(training.get("epochs", 3))
    max_length = int(training.get("max_length", 2048))
    if not (1 <= batch_size <= 32 and 1 <= accumulation <= 128 and 1 <= epochs <= 20 and 16 <= max_length <= 32768):
        raise ValueError("training batch/accumulation/epoch/max_length is outside safe bounds")
    seed = int(training.get("seed", 20261110))
    random.seed(seed)
    torch.manual_seed(seed)
    if runtime["device"] == "cuda":
        torch.cuda.manual_seed_all(seed)
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.set_float32_matmul_precision("high")
    pad_id = int(tokenizer.pad_token_id)
    run_started = time.time()
    epoch_metrics: list[dict[str, Any]] = []
    for epoch in range(epochs):
        indices = list(range(len(encoded)))
        random.Random(seed + epoch).shuffle(indices)
        loss_total = 0.0
        loss_count = 0
        optimizer.zero_grad(set_to_none=True)
        pending = 0
        for batch_start in range(0, len(indices), batch_size):
            batch = [encoded[index] for index in indices[batch_start : batch_start + batch_size]]
            width = max(len(input_ids) for input_ids, _ in batch)
            input_tensor = torch.full((len(batch), width), pad_id, dtype=torch.long)
            labels_tensor = torch.full((len(batch), width), -100, dtype=torch.long)
            attention = torch.zeros((len(batch), width), dtype=torch.long)
            for index, (input_ids, labels) in enumerate(batch):
                input_tensor[index, : len(input_ids)] = torch.tensor(input_ids, dtype=torch.long)
                labels_tensor[index, : len(labels)] = torch.tensor(labels, dtype=torch.long)
                attention[index, : len(input_ids)] = 1
            if runtime["device"] == "cuda":
                input_tensor = input_tensor.pin_memory().to("cuda", non_blocking=True)
                labels_tensor = labels_tensor.pin_memory().to("cuda", non_blocking=True)
                attention = attention.pin_memory().to("cuda", non_blocking=True)
            else:
                input_tensor, labels_tensor, attention = input_tensor, labels_tensor, attention
            amp_context = (
                torch.autocast("cuda", dtype=runtime["dtype"])
                if runtime["device"] == "cuda"
                else nullcontext()
            )
            with amp_context:
                result = model(input_ids=input_tensor, attention_mask=attention, labels=labels_tensor)
            scaler.scale(result.loss).backward()
            loss_total += float(result.loss.detach().float().cpu())
            loss_count += 1
            pending += 1
            is_last_batch = batch_start + batch_size >= len(indices)
            if pending >= accumulation or is_last_batch:
                scaler.unscale_(optimizer)
                for parameter in trainable:
                    if parameter.grad is not None:
                        parameter.grad.div_(pending)
                torch.nn.utils.clip_grad_norm_(trainable, float(training.get("max_grad_norm", 1.0)))
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                pending = 0
        summary = {"epoch": epoch + 1, "mean_loss": round(loss_total / max(1, loss_count), 6)}
        epoch_metrics.append(summary)
        model.save_pretrained(output_dir, safe_serialization=True)
        print(json.dumps(summary), flush=True)

    tokenizer.save_pretrained(output_dir)
    try:
        gpu = torch.cuda.get_device_name(0) if runtime["device"] == "cuda" else None
    except Exception:
        gpu = None
    record = {
        "schema": "local-ai-hub-finetune-run-v1",
        "name": config["name"],
        "task_type": config["task_type"],
        "base_model": base_model,
        "base_revision": config.get("revision"),
        "resolved_model_revision": getattr(model.config, "_commit_hash", None),
        "adapter_path": str(output_dir.resolve()),
        "run_manifest_sha256": _file_sha256(Path(config["_manifest_path"])),
        "train_file": str(Path(config["train_file"]).resolve()),
        "train_sha256": _file_sha256(Path(config["train_file"])),
        "evaluation_sha256": _file_sha256(Path(config["evaluation_file"])),
        "dataset": dataset_summary,
        "runtime": {key: value for key, value in runtime.items() if key != "dtype"},
        "quantization": quantization,
        "gpu": gpu,
        "torch": torch.__version__,
        "transformers": __import__("transformers").__version__,
        "peft": __import__("peft").__version__,
        "optimizer_fused": optimizer_fused,
        "seed": seed,
        "training": {key: value for key, value in training.items()},
        "lora": {key: value for key, value in lora.items()},
        "epochs": epoch_metrics,
        "elapsed_seconds": round(time.time() - run_started, 2),
        "repository_revision": _git_revision(),
    }
    (output_dir / "training_run.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    del model, tokenizer, optimizer, train_rows, encoded
    gc.collect()
    if runtime["device"] == "cuda":
        torch.cuda.empty_cache()
    return record
