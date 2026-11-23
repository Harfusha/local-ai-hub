"""CLI interface for Local AI Hub model distribution and verification."""
from __future__ import annotations

import argparse
# import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from local_ai_hub.model_distribution import (
    DISTRIBUTION_REGISTRY,
    compute_file_sha256,
    ensure_distribution_model,
    is_ollama_model_present,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local AI Hub Model Distribution Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    status_cmd = sub.add_parser("status", help="Check status of fine-tuned models in Ollama and state")
    status_cmd.add_argument("--endpoint", default="http://127.0.0.1:11434")

    sync_cmd = sub.add_parser("sync", help="Ensure all fine-tuned models are registered in Ollama")
    sync_cmd.add_argument("--model", choices=list(DISTRIBUTION_REGISTRY.keys()), default=None)
    sync_cmd.add_argument("--no-download", action="store_true")
    sync_cmd.add_argument("--force-register", action="store_true")

    publish_cmd = sub.add_parser("inspect-artifact", help="Compute SHA256 and metadata for a newly trained GGUF file")
    publish_cmd.add_argument("file", type=Path)

    args = parser.parse_args()

    if args.command == "status":
        print("=== Local AI Hub Fine-Tuned Model Status ===")
        for key, entry in DISTRIBUTION_REGISTRY.items():
            if entry["kind"] == "ollama_gguf":
                mname = entry["model_name"]
                in_ollama = is_ollama_model_present(mname, args.endpoint)
                local_file = Path("state/models") / entry["filename"]
                has_file = local_file.is_file()
                size_str = f"{local_file.stat().st_size / (1024**3):.2f} GB" if has_file else "missing"
                print(f"[{'x' if in_ollama else ' '}] {key:<25} | Ollama: {'READY' if in_ollama else 'MISSING':<7} | Local file: {size_str}")
            elif entry["kind"] == "safetensors_checkpoint":
                target_dir = Path(entry["target_dir"])
                has_model = (target_dir / "model.safetensors").is_file()
                print(f"[{'x' if has_model else ' '}] {key:<25} | Checkpoint: {'READY' if has_model else 'MISSING':<7} | Path: {entry['target_dir']}")
        return 0

    if args.command == "sync":
        models_to_sync = [args.model] if args.model else list(DISTRIBUTION_REGISTRY.keys())
        for m in models_to_sync:
            entry = DISTRIBUTION_REGISTRY[m]
            if entry["kind"] != "ollama_gguf":
                continue
            print(f"Syncing {m}...")
            res = ensure_distribution_model(
                m,
                root=Path.cwd(),
                allow_download=not args.no_download,
                force_register=args.force_register,
            )
            print(f"Result for {m}: {res.get('status')} - {res.get('message', res.get('file', ''))}")
        return 0

    if args.command == "inspect-artifact":
        path = args.file
        if not path.is_file():
            print(f"Error: file not found: {path}", file=sys.stderr)
            return 1
        sha = compute_file_sha256(path)
        size = path.stat().st_size
        print(f"File:        {path}")
        print(f"Size (bytes): {size} ({size / (1024**3):.2f} GB)")
        print(f"SHA-256:     {sha}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
