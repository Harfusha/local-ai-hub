from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from local_ai_hub.config import load_config
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.reranker import Reranker

cfg = load_config(str(root / "config.toml"))
features = cfg.get("features", {})

if features.get("rag", True) and cfg["models"].get("embedding_backend", "sentence-transformers") == "sentence-transformers":
    emb = EmbeddingModel(cfg)
    result = emb.encode(["Local AI model preload check."], query=False)
    if not result.get("success"):
        raise SystemExit(f"Embedding preload failed: {result.get('error')}")
    print(f"Embedding ready: {emb.model_name} on {emb.device}")

if features.get("reranker", True):
    rr = Reranker(cfg)
    if not rr._ensure_model():
        raise SystemExit(f"Reranker preload failed: {rr.status().get('load_error')}")
    print(f"Reranker ready: {rr.model_name} on {rr.device}")
