"""Automated Hugging Face model downloader and config provisioner for Local AI Hub.

Allows users to pull fine-tuned models from Hugging Face and automatically
register them in Local AI Hub configuration.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_hf_token(explicit_token: str | None = None) -> str | None:
    """Resolve optional Hugging Face API token."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    try:
        from huggingface_hub import get_token

        cached = get_token()
        if cached and cached.strip():
            return cached.strip()
    except Exception:
        pass
    return None


def get_default_models_dir() -> Path:
    """Return default models directory under Local AI Hub state."""
    state_dir = Path(os.environ.get("LOCAL_AI_HUB_STATE_DIR", Path.home() / ".local-ai-hub" / "state"))
    models_dir = state_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def download_model(
    repo_id: str,
    *,
    destination: Path | str | None = None,
    revision: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Download model repository snapshot from Hugging Face."""
    from huggingface_hub import HfApi, snapshot_download

    auth_token = resolve_hf_token(token)
    api = HfApi(token=auth_token)

    logger.info("Checking repository metadata for %s...", repo_id)
    info = api.repo_info(repo_id=repo_id, revision=revision, repo_type="model")

    repo_slug = repo_id.replace("/", "--")
    if destination:
        dest_dir = Path(destination).resolve()
    else:
        dest_dir = get_default_models_dir() / repo_slug

    dest_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading %s to %s...", repo_id, dest_dir)
    local_path = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(dest_dir),
        token=auth_token,
        ignore_patterns=["*.git*", ".gitattributes"],
    )

    p = Path(local_path)
    # Detect model type
    is_laya = (p / "rl_agent_config.json").exists() or (p / "encoder").exists() or "laya" in repo_id.lower()
    is_lora = (p / "adapter_config.json").exists() or (p / "adapter_model.safetensors").exists()
    gguf_files = list(p.glob("*.gguf"))

    model_type = "gguf" if gguf_files else ("laya" if is_laya else ("lora" if is_lora else "standard"))

    return {
        "repo_id": repo_id,
        "local_path": str(dest_dir),
        "model_type": model_type,
        "commit_sha": getattr(info, "sha", None),
        "gguf_files": [f.name for f in gguf_files],
        "success": True,
    }


def update_config_file(
    config_path: Path | str,
    model_info: dict[str, Any],
) -> bool:
    """Update config.toml with the downloaded model reference."""
    cfg_file = Path(config_path).expanduser().resolve()
    if not cfg_file.exists():
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text("# Local AI Hub User Configuration\n", encoding="utf-8")

    content = cfg_file.read_text(encoding="utf-8")
    local_path_escaped = model_info["local_path"].replace("\\", "/")
    mtype = model_info.get("model_type")

    # Generate snippet
    if mtype == "laya":
        snippet = f'\n[laya.runtime]\ncheckpoint_path = "{local_path_escaped}"\n'
    elif mtype == "lora":
        snippet = f'\n[models]\npreprocessing_adapter = "{local_path_escaped}"\n'
    elif mtype == "gguf" and model_info.get("gguf_files"):
        gguf_path = (Path(model_info["local_path"]) / model_info["gguf_files"][0]).as_posix()
        snippet = f'\n[models]\nlocal_model_path = "{gguf_path}"\n'
    else:
        snippet = f'\n[models]\ndownloaded_model_path = "{local_path_escaped}"\n'

    # Append snippet
    cfg_file.write_text(content.rstrip() + "\n" + snippet, encoding="utf-8")
    logger.info("Updated %s with model configuration snippet.", cfg_file)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Download fine-tuned models from Hugging Face for Local AI Hub")
    parser.add_argument("--repo", required=True, help="Hugging Face repo ID (e.g. username/my-model)")
    parser.add_argument("--dest", type=Path, help="Custom destination folder (default: ~/.local-ai-hub/state/models/)")
    parser.add_argument("--revision", help="Optional Git revision / commit SHA / branch")
    parser.add_argument("--token", help="Optional HF token (for private repos)")
    parser.add_argument("--apply-config", action="store_true", help="Auto-update ~/.local-ai-hub/config.toml")
    parser.add_argument("--config-file", type=Path, default=Path.home() / ".local-ai-hub" / "config.toml")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    res = download_model(args.repo, destination=args.dest, revision=args.revision, token=args.token)

    if args.apply_config:
        update_config_file(args.config_file, res)

    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
