from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.config import load_config
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.reranker import Reranker


def run_prefetch_local_nlp(cfg: dict[str, Any]) -> dict[str, Any]:
    """Preload embedding and reranker models according to configuration."""
    clean_cfg = dict(cfg) if isinstance(cfg, dict) else {}
    features = clean_cfg.get("features")
    if not isinstance(features, dict):
        features = {}
    clean_cfg["features"] = features

    models = clean_cfg.get("models")
    if not isinstance(models, dict):
        models = {}
    clean_cfg["models"] = models

    report: dict[str, Any] = {"success": True, "embedding": None, "reranker": None}

    if features.get("rag", True) and models.get("embedding_backend", "sentence-transformers") == "sentence-transformers":
        emb = EmbeddingModel(clean_cfg)
        result = emb.encode(["Local AI model preload check."], query=False)
        if not result.get("success"):
            report["success"] = False
            report["embedding_error"] = result.get("error")
        else:
            report["embedding"] = {"model": emb.model_name, "device": str(emb.device)}

    if features.get("reranker", True):
        rr = Reranker(clean_cfg)
        if not rr._ensure_model():
            report["success"] = False
            report["reranker_error"] = rr.status().get("load_error")
        else:
            report["reranker"] = {"model": rr.model_name, "device": str(rr.device)}

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch local NLP models.")
    parser.add_argument("--config", help="Path to config.toml")
    args = parser.parse_args(argv)

    config_path = ROOT / "config.toml"
    if args.config:
        if "\0" in args.config:
            print("Invalid config path: embedded null byte", file=sys.stderr)
            return 1
        config_path = Path(args.config)

    cfg = load_config(str(config_path) if config_path.exists() else None)
    report = run_prefetch_local_nlp(cfg)

    if not report.get("success"):
        if report.get("embedding_error"):
            print(f"Embedding preload failed: {report.get('embedding_error')}", file=sys.stderr)
        if report.get("reranker_error"):
            print(f"Reranker preload failed: {report.get('reranker_error')}", file=sys.stderr)
        return 1

    if report.get("embedding"):
        emb_info = report["embedding"]
        print(f"Embedding ready: {emb_info.get('model')} on {emb_info.get('device')}")
    if report.get("reranker"):
        rr_info = report["reranker"]
        print(f"Reranker ready: {rr_info.get('model')} on {rr_info.get('device')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
