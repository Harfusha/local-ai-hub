from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.accelerators import accelerator_status  # noqa: E402
from local_ai_hub.config import load_config  # noqa: E402
from local_ai_hub.embeddings import EmbeddingModel  # noqa: E402
from local_ai_hub.reranker import Reranker  # noqa: E402


def run_prefetch_openvino(cfg: dict[str, Any]) -> dict[str, object]:
    """Prefetch and warmup openvino models."""
    clean_cfg = dict(cfg) if isinstance(cfg, dict) else {}
    models = clean_cfg.get("models")
    if not isinstance(models, dict):
        models = {}
    clean_cfg["models"] = models

    features = clean_cfg.get("features")
    if not isinstance(features, dict):
        features = {}
    clean_cfg["features"] = features

    report: dict[str, object] = {"accelerators": accelerator_status(clean_cfg)}

    if str(models.get("embedding_backend", "")) == "openvino":
        embedding = EmbeddingModel(clean_cfg)
        report["embedding"] = embedding.encode(["local ai hub accelerator warmup"], query=False, priority=1)
        report["embedding_status"] = embedding.status()

    if bool(features.get("reranker", True)) and str(models.get("reranker_backend", "")) == "openvino":
        reranker = Reranker(clean_cfg)
        report["reranker"] = reranker.rerank("local ai", ["local ai hub accelerator warmup"], top_k=1, priority=1)
        report["reranker_status"] = reranker.status()

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch OpenVINO accelerator models.")
    parser.add_argument("--config", help="Path to config.toml")
    args = parser.parse_args(argv)

    config_path = ROOT / "config.toml"
    if args.config:
        if "\0" in args.config:
            print("Invalid config path: embedded null byte", file=sys.stderr)
            return 1
        config_path = Path(args.config)

    cfg = load_config(str(config_path) if config_path.exists() else None)
    report = run_prefetch_openvino(cfg)

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    # Warmup is best-effort. CPU fallback is a valid result; setup must not become
    # unusable merely because a vendor driver rejects one model on NPU/iGPU.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
