from __future__ import annotations

import argparse
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from sentence_transformers import SentenceTransformer

from tools.model_training.eval_retrieval import RetrievalEvaluator
from tools.model_training.train_embeddings import EmbeddingsTrainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_MODEL_PATH = str(Path.home() / ".cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a")
DATASET_PATH = Path("state/retrieval_triplets.jsonl")
OUTPUT_DIR = Path("state/experiments/model-training/runs/embeddings/run_bge_small_matryoshka_optimized")


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


def compute_matryoshka_loss(
    q_emb: torch.Tensor,
    pos_emb: torch.Tensor,
    neg_emb: torch.Tensor,
    dims: tuple[int, ...] = (128, 256, 384),
    temperature: float = 0.05,
) -> torch.Tensor:
    total_loss = torch.tensor(0.0, device=q_emb.device)
    for dim in dims:
        d = min(dim, q_emb.shape[-1])
        q_norm = F.normalize(q_emb[:, :d], p=2, dim=-1)
        pos_norm = F.normalize(pos_emb[:, :d], p=2, dim=-1)
        neg_norm = F.normalize(neg_emb[:, :d], p=2, dim=-1)

        sim_pos = torch.sum(q_norm * pos_norm, dim=-1) / temperature
        sim_neg = torch.sum(q_norm * neg_norm, dim=-1) / temperature

        # InfoNCE loss between positive and negative
        loss = F.softplus(sim_neg - sim_pos).mean()
        total_loss = total_loss + loss
    return total_loss / len(dims)


def evaluate_embeddings(
    model: SentenceTransformer,
    eval_triplets: list[dict[str, Any]],
    eval_sample_size: int = 1000,
    dims: tuple[int, ...] = (128, 256, 384),
) -> dict[str, Any]:
    sample = eval_triplets[:eval_sample_size]

    # 1. EmbeddingsTrainer evaluation
    trainer = EmbeddingsTrainer(matryoshka_dims=dims)

    queries = [x["query"] for x in sample]
    positives = [x["positive"] for x in sample]
    negatives = [x["negative"] for x in sample]

    model.eval()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        all_embs = model.encode(
            queries + positives + negatives,
            batch_size=128,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    q_embs = all_embs[: len(queries)]
    pos_embs = all_embs[len(queries) : 2 * len(queries)]
    neg_embs = all_embs[2 * len(queries) :]

    q_map = {q: q_embs[i].tolist() for i, q in enumerate(queries)}
    doc_map: dict[str, list[float]] = {}
    for i, p in enumerate(positives):
        doc_map[p] = pos_embs[i].tolist()
    for i, n in enumerate(negatives):
        doc_map[n] = neg_embs[i].tolist()

    trainer_metrics = trainer.evaluate_batch(
        sample,
        query_embed_fn=lambda q: q_map[q],
        doc_embed_fn=lambda d: doc_map[d],
    )

    # 2. Retrieval IR evaluation (MRR, NDCG, Hit@k)
    ir_evaluator = RetrievalEvaluator(top_k=10)
    # Build candidate pool of all positives + negatives from first 200 queries
    pool_queries = queries[:200]
    ground_truth = {f"q_{i}": f"pos_{i}" for i in range(len(pool_queries))}
    candidate_pool = {}
    pool_docs_list = []
    pool_ids = []
    for i in range(len(pool_queries)):
        candidate_pool[f"pos_{i}"] = positives[i]
        candidate_pool[f"neg_{i}"] = negatives[i]
        pool_ids.extend([f"pos_{i}", f"neg_{i}"])
        pool_docs_list.extend([positives[i], negatives[i]])

    with torch.no_grad():
        pool_doc_embs = model.encode(pool_docs_list, batch_size=64, convert_to_tensor=True, show_progress_bar=False)
        pool_q_embs = model.encode(pool_queries, batch_size=64, convert_to_tensor=True, show_progress_bar=False)

    pool_doc_embs = F.normalize(pool_doc_embs, p=2, dim=-1)
    pool_q_embs = F.normalize(pool_q_embs, p=2, dim=-1)
    sim_matrix = torch.matmul(pool_q_embs, pool_doc_embs.T)  # (n_queries, n_candidates)

    def rank_fn(query_id: str, pool_items: list[tuple[str, str]]) -> list[str]:
        q_idx = int(query_id.split("_")[1])
        scores = sim_matrix[q_idx].cpu().tolist()
        scored_pairs = list(zip(pool_ids, scores))
        scored_pairs.sort(key=lambda x: x[1], reverse=True)
        return [pair[0] for pair in scored_pairs]

    ir_metrics = ir_evaluator.evaluate(
        queries=list(ground_truth.keys()),
        ground_truth=ground_truth,
        candidate_pool=candidate_pool,
        rank_fn=rank_fn,
    )

    return {
        "accuracy": trainer_metrics["accuracy"],
        "matryoshka_loss": trainer_metrics["loss"],
        "mrr": ir_metrics.mrr,
        "ndcg": ir_metrics.ndcg,
        "hit_at_1": ir_metrics.hit_at_1,
        "hit_at_5": ir_metrics.hit_at_5,
        "hit_at_10": ir_metrics.hit_at_10,
        "eval_samples": len(sample),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Matryoshka bi-encoder with optional PEFT LoRA.")
    parser.add_argument("--method", choices=("full", "lora"), default="lora")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1:
        raise ValueError("epochs and batch-size must be positive")
    output_dir = OUTPUT_DIR if args.method == "full" else OUTPUT_DIR.with_name(f"{OUTPUT_DIR.name}_{args.method}")
    seed = 20261110
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

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
    logger.info("Loading base model: %s", BASE_MODEL_PATH)
    model = SentenceTransformer(BASE_MODEL_PATH, device="cuda")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("Optimized embedding training requires CUDA BF16 support")
    torch.backends.cuda.matmul.allow_tf32 = True

    # 3. Benchmark BEFORE training
    logger.info("Running baseline benchmark on held-out eval set...")
    before_metrics = evaluate_embeddings(model, eval_triplets, eval_sample_size=1000)
    logger.info("BASELINE METRICS: %s", json.dumps(before_metrics, indent=2))
    (output_dir / "baseline_metrics.json").write_text(json.dumps(before_metrics, indent=2), encoding="utf-8")

    if args.method == "lora":
        from peft import LoraConfig, TaskType, get_peft_model

        transformer = model[0]
        transformer.model = get_peft_model(
            transformer.auto_model,
            LoraConfig(
                r=8,
                lora_alpha=16,
                lora_dropout=0.05,
                bias="none",
                task_type=TaskType.FEATURE_EXTRACTION,
                target_modules=["query", "value"],
            ),
        )
        trainable_count = sum(p.numel() for p in transformer.model.parameters() if p.requires_grad)
        logger.info("LoRA trainable parameters: %d", trainable_count)

    # 4. Train Model
    logger.info("Starting Matryoshka contrastive fine-tuning on CUDA...")
    train_dataset = TripletDataset(train_triplets)
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        collate_fn=collate_triplets,
        pin_memory=True,
    )

    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=2e-5, weight_decay=0.01)
    epochs = args.epochs
    steps_per_epoch = len(train_loader)
    total_steps = epochs * steps_per_epoch
    logger.info("Training configuration: %d epochs, %d batches/epoch, total %d steps", epochs, steps_per_epoch, total_steps)

    model.train()
    start_time = time.time()
    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        batch_count = 0
        for batch in train_loader:
            optimizer.zero_grad()
            # Tokenize and encode
            texts = batch["query"] + batch["positive"] + batch["negative"]
            features = model.tokenizer(texts, padding=True, truncation=True, max_length=512, pad_to_multiple_of=8, return_tensors="pt")
            features = {k: v.to("cuda", non_blocking=True) for k, v in features.items()}

            with torch.autocast("cuda", dtype=torch.bfloat16):
                embeddings = model(features)["sentence_embedding"].float()
            size = len(batch["query"])
            q_out, pos_out, neg_out = embeddings[:size], embeddings[size : 2 * size], embeddings[2 * size :]

            loss = compute_matryoshka_loss(q_out, pos_out, neg_out, dims=(128, 256, 384))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, max_norm=1.0)
            optimizer.step()

            epoch_loss += loss.item()
            batch_count += 1

            if batch_count % 150 == 0 or batch_count == steps_per_epoch:
                logger.info("Epoch %d/%d [step %d/%d] - loss: %.4f", epoch, epochs, batch_count, steps_per_epoch, epoch_loss / batch_count)

    elapsed_s = time.time() - start_time
    logger.info("Training complete in %.2f seconds", elapsed_s)

    # 5. Benchmark AFTER training
    logger.info("Running post-training benchmark on held-out eval set...")
    after_metrics = evaluate_embeddings(model, eval_triplets, eval_sample_size=1000)
    logger.info("POST-TRAINING METRICS: %s", json.dumps(after_metrics, indent=2))

    # 6. Save Model and Artifacts
    logger.info("Saving fine-tuned model to %s", output_dir)
    if args.method == "lora":
        adapter_dir = output_dir / "adapter"
        adapter_dir.mkdir(parents=True, exist_ok=True)
        transformer = model[0]
        transformer.model.save_pretrained(adapter_dir)
        transformer.tokenizer.save_pretrained(adapter_dir)
        transformer.model = transformer.model.merge_and_unload()
        model.save(str(output_dir / "merged_model"))
    else:
        model.save(str(output_dir))

    report = {
        "model_name": "bge-small-en-v1.5-matryoshka-code",
        "base_model": BASE_MODEL_PATH,
        "dataset": {
            "total_triplets": len(all_triplets),
            "train_triplets": len(train_triplets),
            "eval_triplets": len(eval_triplets),
        },
        "training": {
            "epochs": epochs,
            "batch_size": args.batch_size,
            "method": args.method,
            "trainable_parameters": sum(parameter.numel() for parameter in trainable),
            "adapter_path": str((output_dir / "adapter").resolve()) if args.method == "lora" else None,
            "model_path": str((output_dir / "merged_model").resolve()) if args.method == "lora" else str(output_dir.resolve()),
            "learning_rate": 2e-5,
            "duration_seconds": round(elapsed_s, 2),
            "device": "cuda",
            "precision": "bfloat16-mixed",
            "forward_passes_per_step": 1,
            "matryoshka_dims": [128, 256, 384],
        },
        "metrics": {
            "before": before_metrics,
            "after": after_metrics,
            "delta": {
                "accuracy": round(after_metrics["accuracy"] - before_metrics["accuracy"], 4),
                "matryoshka_loss": round(after_metrics["matryoshka_loss"] - before_metrics["matryoshka_loss"], 4),
                "mrr": round(after_metrics["mrr"] - before_metrics["mrr"], 4),
                "ndcg": round(after_metrics["ndcg"] - before_metrics["ndcg"], 4),
                "hit_at_1": round(after_metrics["hit_at_1"] - before_metrics["hit_at_1"], 4),
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
