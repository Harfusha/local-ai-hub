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

from local_ai_hub.config import load_config
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.reranker import Reranker


def run_prefetch_local_nlp(
    cfg: dict[str, Any], *, allow_hf_downloads: bool | None = None,
) -> dict[str, Any]:
    """Preload embedding and reranker models according to configuration."""
    clean_cfg = dict(cfg) if isinstance(cfg, dict) else {}
    features = clean_cfg.get("features")
    if not isinstance(features, dict):
        features = {}
    clean_cfg["features"] = features

    raw_models = clean_cfg.get("models")
    models = dict(raw_models) if isinstance(raw_models, dict) else {}
    if allow_hf_downloads is not None:
        models["allow_hf_downloads"] = allow_hf_downloads
    clean_cfg["models"] = models

    report: dict[str, Any] = {
        "success": True,
        "embedding": {"status": "not_selected"},
        "reranker": {"status": "not_selected"},
        "downloads_enabled": models.get("allow_hf_downloads") is True,
    }

    if features.get("rag", True) and models.get("embedding_backend", "sentence-transformers") == "sentence-transformers":
        emb = EmbeddingModel(clean_cfg)
        result = emb.encode(["Local AI model preload check."], query=False)
        if not result.get("success"):
            report["success"] = False
            report["embedding_error"] = result.get("error")
            report["embedding"] = {
                "status": "unavailable",
                "model": result.get("model", emb.model_name),
                "backend": result.get("backend"),
                "device": result.get("device"),
            }
        else:
            report["embedding"] = {
                "status": "ready",
                "model": result.get("model", emb.model_name),
                "backend": result.get("backend"),
                "device": result.get("device", str(emb.device)),
            }

    if features.get("reranker", True):
        rr = Reranker(clean_cfg)
        if not rr._ensure_model():
            report["success"] = False
            rr_status = rr.status()
            report["reranker_error"] = rr_status.get("load_error")
            report["reranker"] = {
                "status": "unavailable",
                "model": rr_status.get("model", rr.model_name),
                "backend": rr_status.get("active_backend", rr_status.get("backend")),
                "device": rr_status.get("active_device", rr_status.get("device")),
            }
        else:
            rr_status = rr.status()
            report["reranker"] = {
                "status": "ready",
                "model": rr_status.get("model", rr.model_name),
                "backend": rr_status.get("active_backend", rr_status.get("backend")),
                "device": rr_status.get("active_device", rr_status.get("device")),
            }

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch local NLP models.")
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result.")
    downloads = parser.add_mutually_exclusive_group()
    downloads.add_argument("--allow-hf-downloads", dest="allow_hf_downloads", action="store_true")
    downloads.add_argument("--no-hf-downloads", dest="allow_hf_downloads", action="store_false")
    parser.set_defaults(allow_hf_downloads=None)
    args = parser.parse_args(argv)

    config_path = ROOT / "config.toml"
    if args.config:
        if "\0" in args.config:
            print("Invalid config path: embedded null byte", file=sys.stderr)
            return 1
        config_path = Path(args.config)

    cfg = load_config(str(config_path) if config_path.exists() else None)
    report = run_prefetch_local_nlp(cfg, allow_hf_downloads=args.allow_hf_downloads)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=str))
        return 0 if report.get("success") else 1

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
