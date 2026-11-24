from __future__ import annotations

import json
import logging
import math
import random
import time
import argparse
import os
import gc
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset
from sentence_transformers import CrossEncoder

from tools.model_training.train_reranker import RerankerTrainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_MODEL_PATH = str(Path.home() / ".cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
DATASET_PATH = Path("state/retrieval_triplets.jsonl")
OUTPUT_DIR = Path("state/experiments/model-training/runs/reranker/run_bge_reranker_v2_m3")


class TripletDataset(Dataset):
    def __init__(self, triplets: list[dict[str, Any]]) -> None:
        self.triplets = triplets

    def __len__(self) -> int:
        return len(self.triplets)

    def __getitem__(self, idx: int) -> dict[str, str]:
        item = self.triplets[idx]
        return {
            "query": item["query"],
            "positive": item["positive"],
            "negative": item["negative"],
        }


def collate_triplets(batch: list[dict[str, str]]) -> dict[str, list[str]]:
    return {
        "query": [x["query"] for x in batch],
        "positive": [x["positive"] for x in batch],
        "negative": [x["negative"] for x in batch],
    }


def measure_triplet_lengths(
    tokenizer: Any,
    triplets: list[dict[str, Any]],
    *,
    max_length: int,
    batch_size: int = 512,
) -> list[int]:
    """Measure exact truncated pair lengths once for low-padding batches."""
    lengths: list[int] = []
    for start in range(0, len(triplets), batch_size):
        batch = triplets[start : start + batch_size]
        queries = [item["query"] for item in batch]
        positive = tokenizer(
            queries, [item["positive"] for item in batch], truncation=True,
            max_length=max_length, padding=False, return_attention_mask=False,
        )["input_ids"]
        negative = tokenizer(
            queries, [item["negative"] for item in batch], truncation=True,
            max_length=max_length, padding=False, return_attention_mask=False,
        )["input_ids"]
        lengths.extend(max(len(pos), len(neg)) for pos, neg in zip(positive, negative))
    return lengths


def evaluate_reranker(
    model: CrossEncoder,
    eval_triplets: list[dict[str, Any]],
    eval_sample_size: int = 1000,
    margin: float = 0.5,
) -> dict[str, Any]:
    sample = eval_triplets[:eval_sample_size]
    trainer = RerankerTrainer(margin=margin)

    # Score function for evaluate_batch
    pairs_pos = [(x["query"], x["positive"]) for x in sample]
    pairs_neg = [(x["query"], x["negative"]) for x in sample]

    model.transformers_model.eval()
    scores = []
    all_pairs = pairs_pos + pairs_neg
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        for start in range(0, len(all_pairs), 16):
            chunk = all_pairs[start : start + 16]
            features = model.tokenizer(
                [pair[0] for pair in chunk], [pair[1] for pair in chunk],
                padding=True, truncation=True, max_length=model.max_seq_length,
                return_tensors="pt", pad_to_multiple_of=8,
            )
            features = {key: value.to("cuda", non_blocking=True) for key, value in features.items()}
            logits = model.transformers_model(**features).logits.squeeze(-1).float()
            # Match CrossEncoder.predict's default sigmoid activation so metric
            # values remain comparable with full-fine-tuning runs.
            scores.extend(torch.sigmoid(logits).cpu().tolist())
        scores = torch.tensor(scores)
    scores_pos, scores_neg = scores[: len(sample)], scores[len(sample) :]

    score_dict: dict[tuple[str, str], float] = {}
    for i, p in enumerate(pairs_pos):
        score_dict[p] = float(scores_pos[i])
    for i, p in enumerate(pairs_neg):
        score_dict[p] = float(scores_neg[i])

    def score_fn(q: str, d: str) -> float:
        return score_dict[(q, d)]

    metrics = trainer.evaluate_batch(sample, score_fn)

    # Score separation: pos - neg
    separations = [float(scores_pos[i] - scores_neg[i]) for i in range(len(sample))]
    avg_separation = round(sum(separations) / len(separations), 4)

    return {
        "loss": metrics.loss,
        "margin_accuracy": metrics.margin_accuracy,
        "avg_pos_score": metrics.avg_pos_score,
        "avg_neg_score": metrics.avg_neg_score,
        "avg_score_separation": avg_separation,
        "eval_samples": len(sample),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the BGE reranker with BF16 and resumable checkpoints.")
    parser.add_argument("--method", choices=("full", "lora"), default="lora")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8, help="Triplets per step (each has a positive and negative pair).")
    parser.add_argument("--checkpoint-every", type=int, default=100)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--allow-length-change-on-resume", action="store_true")
    parser.add_argument("--eval-samples", type=int, default=1000)
    parser.add_argument("--output-dir", type=Path, help="Write this run to a separate directory.")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("Optimized reranker requires a CUDA GPU with BF16 support")
    if min(args.epochs, args.batch_size, args.checkpoint_every, args.max_length, args.eval_samples) < 1:
        raise ValueError("Training arguments must be positive")

    seed = 20261110
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    output_dir = args.output_dir or (OUTPUT_DIR if args.method == "full" else OUTPUT_DIR.with_name(f"{OUTPUT_DIR.name}_{args.method}"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load data
    logger.info("Loading triplets from %s", DATASET_PATH)
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        all_triplets = [json.loads(line) for line in f if line.strip()]

    random.shuffle(all_triplets)
    split_idx = int(len(all_triplets) * 0.8)
    train_triplets = all_triplets[:split_idx]
    eval_triplets = all_triplets[split_idx:]
    logger.info("Dataset split: %d train, %d eval", len(train_triplets), len(eval_triplets))

    # 2. Load Base Model
    logger.info("Loading base reranker: %s", BASE_MODEL_PATH)
    model = CrossEncoder(
        BASE_MODEL_PATH,
        num_labels=1,
        device="cuda",
        max_length=args.max_length,
        model_kwargs={"attn_implementation": "sdpa"},
    )
    if args.method == "lora":
        from peft import LoraConfig, TaskType, get_peft_model

        transformer_module = model[0]
        transformer_module.model = get_peft_model(
            transformer_module.model,
            LoraConfig(
                r=8,
                lora_alpha=16,
                lora_dropout=0.05,
                bias="none",
                task_type=TaskType.SEQ_CLS,
                target_modules=["query", "value"],
                modules_to_save=["classifier"],
            ),
        )
        trainable_count = sum(p.numel() for p in transformer_module.model.parameters() if p.requires_grad)
        logger.info("LoRA trainable parameters: %d", trainable_count)

    # 3. Benchmark BEFORE training
    logger.info("Running baseline benchmark on held-out eval set...")
    before_metrics = evaluate_reranker(model, eval_triplets, eval_sample_size=args.eval_samples)
    logger.info("BASELINE METRICS: %s", json.dumps(before_metrics, indent=2))
    (output_dir / "baseline_metrics.json").write_text(json.dumps(before_metrics, indent=2), encoding="utf-8")

    # 4. Train Model
    logger.info("Starting CrossEncoder fine-tuning on CUDA...")
    train_dataset = TripletDataset(train_triplets)
    train_lengths = measure_triplet_lengths(model.tokenizer, train_triplets, max_length=args.max_length)
    logger.info(
        "Measured train pair lengths: median %d, p90 %d, max %d tokens",
        sorted(train_lengths)[len(train_lengths) // 2],
        sorted(train_lengths)[int(len(train_lengths) * 0.9)],
        max(train_lengths),
    )
    trainable = [parameter for parameter in model.transformers_model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=2e-5, weight_decay=0.01)
    steps_per_epoch = math.ceil(len(train_dataset) / args.batch_size)
    total_steps = args.epochs * steps_per_epoch
    state_path = output_dir / "training_state.pt"
    start_epoch, resume_batch, global_step = 0, 0, 0
    resume_indices: list[int] | None = None
    if args.resume and state_path.exists():
        state = torch.load(state_path, map_location="cpu", weights_only=False)
        checkpoint_length = int(state.get("max_length", 512))
        if checkpoint_length != args.max_length and not args.allow_length_change_on_resume:
            raise ValueError(
                f"checkpoint max_length={checkpoint_length} differs from requested {args.max_length}; "
                "pass --allow-length-change-on-resume to start a shorter-context curriculum"
            )
        if state.get("method", "full") != args.method:
            raise ValueError("checkpoint training method differs from requested method")
        model.transformers_model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        start_epoch, resume_batch, global_step = state["epoch"], state["next_batch"], state["global_step"]
        resume_indices = state.get("epoch_indices")
        random.setstate(state["python_rng"])
        torch.set_rng_state(state["torch_rng"])
        torch.cuda.set_rng_state_all(state["cuda_rng"])
        del state
        gc.collect()
        logger.info(
            "Resuming at epoch %d batch %d (global step %d, checkpoint max length %d)",
            start_epoch + 1, resume_batch, global_step, checkpoint_length,
        )
    logger.info("Training configuration: %d epochs, batch %d triplets, %d steps, BF16 + SDPA, max length %d", args.epochs, args.batch_size, total_steps, args.max_length)

    model.transformers_model.train()
    start_time = time.time()
    starting_step = global_step
    for epoch in range(start_epoch, args.epochs):
        epoch_loss = 0.0
        batch_count = 0
        if epoch == start_epoch and resume_batch and resume_indices:
            indices = resume_indices.copy()
            bucket_start = resume_batch * args.batch_size
        else:
            indices = list(range(len(train_dataset)))
            random.Random(seed + epoch).shuffle(indices)
            bucket_start = 0
        # Token lengths, rather than character counts, prevent almost every
        # random batch from being padded to the 512-token cap.
        bucket_width = args.batch_size * 32
        for offset in range(bucket_start, len(indices), bucket_width):
            window = indices[offset : offset + bucket_width]
            window.sort(key=train_lengths.__getitem__)
            indices[offset : offset + bucket_width] = window
        for batch_index in range(resume_batch if epoch == start_epoch else 0, steps_per_epoch):
            batch_indices = indices[batch_index * args.batch_size : (batch_index + 1) * args.batch_size]
            batch = collate_triplets([train_dataset[i] for i in batch_indices])
            pairs_pos = list(zip(batch["query"], batch["positive"]))
            pairs_neg = list(zip(batch["query"], batch["negative"]))
            pairs = pairs_pos + pairs_neg
            optimizer.zero_grad(set_to_none=True)
            features = model.tokenizer(
                [p[0] for p in pairs], [p[1] for p in pairs], padding=True,
                truncation=True, max_length=args.max_length, return_tensors="pt", pad_to_multiple_of=8,
            )
            features = {k: v.to("cuda", non_blocking=True) for k, v in features.items()}
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model.transformers_model(**features).logits.squeeze(-1).float()
            pos_logits, neg_logits = logits[: len(pairs_pos)], logits[len(pairs_pos) :]

            # Combined Margin Ranking Loss + Binary Cross-Entropy
            margin_loss = F.relu(0.5 - (pos_logits - neg_logits)).mean()
            ones = torch.ones_like(pos_logits)
            zeros = torch.zeros_like(neg_logits)
            bce_loss = (F.binary_cross_entropy_with_logits(pos_logits, ones) + F.binary_cross_entropy_with_logits(neg_logits, zeros)) / 2.0

            loss = margin_loss + 0.5 * bce_loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, max_norm=1.0)
            optimizer.step()

            epoch_loss += loss.item()
            batch_count += 1

            global_step += 1
            next_batch = batch_index + 1
            if global_step % args.checkpoint_every == 0 or next_batch == steps_per_epoch:
                checkpoint = {
                    "model": model.transformers_model.state_dict(), "optimizer": optimizer.state_dict(),
                    "epoch": epoch if next_batch < steps_per_epoch else epoch + 1,
                    "next_batch": next_batch if next_batch < steps_per_epoch else 0,
                    "epoch_indices": indices if next_batch < steps_per_epoch else None,
                    "max_length": args.max_length,
                    "method": args.method,
                    "global_step": global_step, "python_rng": random.getstate(),
                    "torch_rng": torch.get_rng_state(), "cuda_rng": torch.cuda.get_rng_state_all(),
                }
                temp_path = state_path.with_suffix(".tmp")
                torch.save(checkpoint, temp_path)
                os.replace(temp_path, state_path)
            if global_step % 25 == 0 or next_batch == steps_per_epoch:
                logger.info(
                    "Epoch %d/%d [step %d/%d] - %.2f steps/s - segment loss: %.4f (margin: %.4f, bce: %.4f)",
                    epoch + 1, args.epochs, next_batch, steps_per_epoch, (global_step - starting_step) / max(time.time() - start_time, 1), epoch_loss / batch_count,
                    margin_loss.item(), bce_loss.item(),
                )
        resume_batch = 0

    elapsed_s = time.time() - start_time
    logger.info("Training complete in %.2f seconds", elapsed_s)

    # 5. Benchmark AFTER training
    logger.info("Running post-training benchmark on held-out eval set...")
    after_metrics = evaluate_reranker(model, eval_triplets, eval_sample_size=args.eval_samples)
    logger.info("POST-TRAINING METRICS: %s", json.dumps(after_metrics, indent=2))

    # 6. Save Model and Artifacts
    logger.info("Saving fine-tuned model to %s", output_dir)
    if args.method == "lora":
        adapter_dir = output_dir / "adapter"
        adapter_dir.mkdir(parents=True, exist_ok=True)
        transformer_module.model.save_pretrained(adapter_dir)
        model.tokenizer.save_pretrained(adapter_dir)
        transformer_module.model = transformer_module.model.merge_and_unload()
        model.save(str(output_dir / "merged_model"))
    else:
        model.save(str(output_dir))

    report = {
        "model_name": "bge-reranker-v2-m3-code",
        "base_model": BASE_MODEL_PATH,
        "dataset": {
            "total_triplets": len(all_triplets),
            "train_triplets": len(train_triplets),
            "eval_triplets": len(eval_triplets),
        },
        "training": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "precision": "bfloat16",
            "attention": "sdpa",
            "max_length": args.max_length,
            "method": args.method,
            "trainable_parameters": sum(parameter.numel() for parameter in trainable),
            "adapter_path": str((output_dir / "adapter").resolve()) if args.method == "lora" else None,
            "model_path": str((output_dir / "merged_model").resolve()) if args.method == "lora" else str(output_dir.resolve()),
            "learning_rate": 2e-5,
            "duration_seconds": round(elapsed_s, 2),
            "device": "cuda",
            "loss": "margin_ranking_plus_bce",
        },
        "metrics": {
            "before": before_metrics,
            "after": after_metrics,
            "delta": {
                "margin_accuracy": round(after_metrics["margin_accuracy"] - before_metrics["margin_accuracy"], 4),
                "loss": round(after_metrics["loss"] - before_metrics["loss"], 4),
                "avg_pos_score": round(after_metrics["avg_pos_score"] - before_metrics["avg_pos_score"], 4),
                "avg_neg_score": round(after_metrics["avg_neg_score"] - before_metrics["avg_neg_score"], 4),
                "avg_score_separation": round(after_metrics["avg_score_separation"] - before_metrics["avg_score_separation"], 4),
            },
        },
    }

    report_path = output_dir / "train_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Saved report to %s", report_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
