"""Pinned, integrity-checked downloads for the selected public Hub models."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Mapping


TRAINED_MODEL_FILES: dict[str, list[str]] = {
    "Harfusha/local-ai-hub-laya-run-expanded": [
        "model.safetensors", "rl_agent_config.json", "encoder/config.json",
        "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json",
        "README.md", "LICENSE",
    ],
    "Harfusha/local-ai-hub-bge-small-en-v1-5-code": [
        "*.json", "*.safetensors", "1_Pooling/*.json", "README.md",
    ],
    "Harfusha/local-ai-hub-bge-reranker-v2-m3-code": [
        "*.json", "*.safetensors", "README.md", "LICENSE",
    ],
    "Harfusha/local-ai-hub-preprocess-qwen25-coder-0-5b": [
        "*.gguf", "README.md", "LICENSE",
    ],
    "Harfusha/local-ai-hub-preprocess-qwen25-coder-1-5b": [
        "*.gguf", "README.md", "LICENSE",
    ],
}


def download_trained_model(
    repo_id: str,
    revision: str,
    expected_sha256: str | Mapping[str, str],
    *,
    allow_download: bool = False,
) -> Path:
    """Resolve an allowlisted pinned model, downloading only when opted in."""
    patterns = TRAINED_MODEL_FILES.get(repo_id)
    if patterns is None:
        raise ValueError(f"trained model repository is not allowlisted: {repo_id}")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("trained model revision must be a pinned Hugging Face commit")
    if type(allow_download) is not bool:
        raise ValueError("allow_download must be a boolean")
    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(
        repo_id=repo_id,
        revision=revision,
        allow_patterns=patterns,
        local_files_only=not allow_download,
    ))
    expected = ({"model.safetensors": expected_sha256}
                if isinstance(expected_sha256, str) else dict(expected_sha256))
    if not expected:
        raise ValueError("trained model artifact hashes are required")
    for relative, digest in expected.items():
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("trained model hash manifest is invalid")
        path = snapshot / relative
        if not path.is_file():
            raise FileNotFoundError(f"required trained model file is absent: {relative}")
        actual = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                actual.update(chunk)
        if actual.hexdigest() != digest:
            raise ValueError(f"trained model SHA-256 mismatch: {relative}")
    return snapshot


def resolve_laya_checkpoint(
    runtime_cfg: Mapping[str, object], models_cfg: Mapping[str, object]
) -> tuple[str, str, dict[str, str]]:
    """Resolve pinned local Laya weights; network download needs explicit config opt-in."""
    checkpoint_path = runtime_cfg.get("checkpoint_path")
    revision = runtime_cfg.get("revision")
    expected_sha256 = runtime_cfg.get("expected_sha256")
    if isinstance(checkpoint_path, str) and checkpoint_path:
        if not isinstance(revision, str) or not revision:
            raise RuntimeError("Laya checkpoint revision is not configured")
        if not isinstance(expected_sha256, dict) or not expected_sha256:
            raise RuntimeError("Laya checkpoint hashes are not configured")
        return checkpoint_path, revision, expected_sha256

    repo_id = runtime_cfg.get("hf_repo_id")
    hf_revision = runtime_cfg.get("hf_revision")
    hf_sha256 = runtime_cfg.get("hf_sha256")
    if not isinstance(repo_id, str) or not isinstance(hf_revision, str) or not isinstance(hf_sha256, dict) or not hf_sha256:
        raise RuntimeError("Laya checkpoint is not configured")
    checkpoint = download_trained_model(
        repo_id,
        hf_revision,
        hf_sha256,
        allow_download=models_cfg.get("allow_hf_downloads") is True,
    )
    return str(checkpoint), hf_revision, hf_sha256
