from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_ai_hub.accelerators import accelerator_status  # noqa: E402
from local_ai_hub.config import load_config  # noqa: E402
from local_ai_hub.embeddings import EmbeddingModel  # noqa: E402
from local_ai_hub.reranker import Reranker  # noqa: E402


def main() -> int:
    config_path = ROOT / "config.toml"
    cfg = load_config(str(config_path) if config_path.exists() else None)
    report: dict[str, object] = {"accelerators": accelerator_status(cfg)}
    models = cfg.get("models", {})

    if str(models.get("embedding_backend", "")) == "openvino":
        embedding = EmbeddingModel(cfg)
        report["embedding"] = embedding.encode(["local ai hub accelerator warmup"], query=False, priority=1)
        report["embedding_status"] = embedding.status()

    if bool(cfg.get("features", {}).get("reranker", True)) and str(models.get("reranker_backend", "")) == "openvino":
        reranker = Reranker(cfg)
        report["reranker"] = reranker.rerank("local ai", ["local ai hub accelerator warmup"], top_k=1, priority=1)
        report["reranker_status"] = reranker.status()

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    # Warmup is best-effort. CPU fallback is a valid result; setup must not become
    # unusable merely because a vendor driver rejects one model on NPU/iGPU.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
