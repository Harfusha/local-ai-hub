"""Automated Hugging Face Hub model publisher for Local AI Hub fine-tuned models.

Handles:
- Safety validation (preventing dataset/source leakage).
- Automatic Model Card generation with benchmark before/after metrics.
- Uploading LoRA adapters (Qwen / Transformers) and Laya checkpoints.
- Single run or matrix batch publishing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# File patterns strictly excluded from public repository uploads
FORBIDDEN_UPLOAD_PATTERNS = [
    "*.jsonl",
    "*.lock",
    "*.tmp",
    "*.bak",
    "data/*",
    "data",
    "*.dataset-manifest.json",
    "*train*.jsonl",
    "*eval*.jsonl",
    "*benchmark-cases*.json",
]


def resolve_hf_token(explicit_token: str | None = None) -> str:
    """Resolve Hugging Face API token from argument, environment, or local cache."""
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()

    env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    try:
        from huggingface_hub import get_token

        cached_token = get_token()
        if cached_token and cached_token.strip():
            return cached_token.strip()
    except Exception:
        pass

    raise RuntimeError(
        "Hugging Face token not found.\n"
        "To authenticate, please do one of the following:\n"
        "  1. Run 'huggingface-cli login' in terminal\n"
        "  2. Set environment variable: $env:HF_TOKEN = 'hf_...'\n"
        "  3. Pass --token flag"
    )


def generate_model_card(run_dir: Path | str, repo_id: str, is_laya: bool = False) -> str:
    """Generate a clean, informative Hugging Face Model Card (README.md)."""
    p = Path(run_dir)
    after_report_path = p / "benchmark-after.json"
    before_report_path = p / "benchmark-before.json"
    training_run_path = (p / "adapter" / "training_run.json") if (p / "adapter" / "training_run.json").exists() else (p / "training-run.json")
    if not training_run_path.exists() and (p / "training_run.json").exists():
        training_run_path = p / "training_run.json"

    after_data = json.loads(after_report_path.read_text(encoding="utf-8")) if after_report_path.exists() else {}
    before_data = json.loads(before_report_path.read_text(encoding="utf-8")) if before_report_path.exists() else {}
    train_data = json.loads(training_run_path.read_text(encoding="utf-8")) if training_run_path.exists() else {}

    base_model = train_data.get("base_model") or after_data.get("base_model") or "Qwen/Qwen2.5-Coder-3B-Instruct"
    task_type = train_data.get("task_type") or ("decision_model" if is_laya else "preprocess_card")

    lines = [
        "---",
        "license: apache-2.0",
        f"base_model: {base_model}",
        f"pipeline_tag: {'text-classification' if is_laya else 'text-generation'}",
        "tags:",
        "  - local-ai-hub",
        "  - code",
        f"  - {'laya' if is_laya else 'lora'}",
        "---",
        "",
        f"# {repo_id}",
        "",
        "Fine-tuned model trained by [Local AI Hub](https://github.com/local-ai-hub) for local repository intelligence.",
        "",
        "## Model Details",
        f"- **Base Model:** `{base_model}`",
        f"- **Task Type:** `{task_type}`",
        f"- **Architecture:** {'Laya ModernBERT router' if is_laya else 'Transformers PEFT LoRA adapter'}",
        "- **License:** Apache 2.0",
        "",
    ]

    if train_data:
        lines.extend([
            "## Training Details",
            f"- **Epochs:** {train_data.get('epochs', len(train_data.get('epochs', [])) if isinstance(train_data.get('epochs'), list) else 'N/A')}",
            f"- **Quantization:** {train_data.get('quantization', 'N/A')}",
            f"- **GPU / Hardware:** {train_data.get('gpu', 'Local GPU')}",
            f"- **Elapsed Seconds:** {train_data.get('elapsed_seconds', 'N/A')}",
            "",
        ])

    after_summary = after_data.get("summary", {})
    before_summary = before_data.get("summary", {}).get("base", {}) if "base" in before_data.get("summary", {}) else before_data.get("summary", {})

    if after_summary or before_summary:
        lines.extend([
            "## Benchmark Results (Paired Evaluation)",
            "",
            "| Metric | Baseline (Before) | Candidate (After) | Delta |",
            "|---|---|---|---|",
        ])
        keys = sorted(set(list(before_summary.keys()) + list(after_summary.keys())))
        for k in keys:
            if isinstance(before_summary.get(k), (int, float)) or isinstance(after_summary.get(k), (int, float)):
                v_before = before_summary.get(k, "N/A")
                v_after = after_summary.get(k, "N/A")
                delta_str = "N/A"
                if isinstance(v_before, (int, float)) and isinstance(v_after, (int, float)):
                    d = v_after - v_before
                    delta_str = f"{d:+.4f}" if isinstance(d, float) else f"{d:+d}"
                    v_before = f"{v_before:.4f}" if isinstance(v_before, float) else str(v_before)
                    v_after = f"{v_after:.4f}" if isinstance(v_after, float) else str(v_after)
                lines.append(f"| `{k}` | {v_before} | {v_after} | {delta_str} |")
        lines.append("")

    lines.extend([
        "## How to Use with Local AI Hub",
        "",
        "### Automatic download:",
        "```bash",
        f"python tools/download_hf_model.py --repo {repo_id}",
        "```",
        "",
        "### In `~/.local-ai-hub/config.toml`:",
        "```toml",
    ])
    if is_laya:
        lines.extend([
            "[laya.runtime]",
            f"checkpoint_path = \"{repo_id}\"",
        ])
    else:
        lines.extend([
            "[models]",
            f"preprocessing_adapter = \"{repo_id}\"",
        ])
    lines.extend([
        "```",
        "",
    ])

    return "\n".join(lines)


def publish_run_to_hf(
    run_dir: Path | str,
    repo_id: str,
    *,
    token: str | None = None,
    private: bool = False,
    commit_message: str | None = None,
) -> dict[str, Any]:
    """Publish a single fine-tuned model run (adapter or Laya checkpoint) to Hugging Face."""
    run_path = Path(run_dir).resolve()
    if not run_path.exists():
        raise FileNotFoundError(f"Run directory not found: {run_path}")

    # Determine artifact directory
    is_laya = False
    if (run_path / "checkpoint").exists() and (run_path / "checkpoint").is_dir():
        artifact_dir = run_path / "checkpoint"
        is_laya = True
    elif (run_path / "adapter").exists() and (run_path / "adapter").is_dir():
        artifact_dir = run_path / "adapter"
    elif any(run_path.glob("*.safetensors")):
        artifact_dir = run_path
    else:
        raise ValueError(f"No model artifacts (adapter/ or checkpoint/ or .safetensors) found in {run_path}")

    # Verify benchmark completion
    after_benchmark = run_path / "benchmark-after.json"
    if not after_benchmark.exists():
        logger.warning("benchmark-after.json not found in %s; proceeding with available artifacts", run_path)

    # Ensure model card README.md exists in artifact dir
    readme_path = artifact_dir / "README.md"
    generated_card = generate_model_card(run_path, repo_id, is_laya=is_laya)
    readme_path.write_text(generated_card, encoding="utf-8")

    # Copy benchmark reports into artifact dir if not present so consumers see metrics
    for rpt in ("benchmark-after.json", "benchmark-before.json"):
        src_rpt = run_path / rpt
        dest_rpt = artifact_dir / rpt
        if src_rpt.exists() and not dest_rpt.exists():
            dest_rpt.write_text(src_rpt.read_text(encoding="utf-8"), encoding="utf-8")

    auth_token = resolve_hf_token(token)

    from huggingface_hub import HfApi

    api = HfApi(token=auth_token)

    logger.info("Creating / checking Hugging Face repository %s (private=%s)...", repo_id, private)
    api.create_repo(repo_id=repo_id, private=private, exist_ok=True, repo_type="model")

    msg = commit_message or f"Upload fine-tuned {artifact_dir.name} from Local AI Hub"
    logger.info("Uploading folder %s to %s...", artifact_dir, repo_id)
    commit_info = api.upload_folder(
        folder_path=str(artifact_dir),
        repo_id=repo_id,
        repo_type="model",
        commit_message=msg,
        ignore_patterns=FORBIDDEN_UPLOAD_PATTERNS,
    )

    repo_url = f"https://huggingface.co/{repo_id}"
    logger.info("Successfully published model to %s", repo_url)
    return {
        "repo_id": repo_id,
        "repo_url": repo_url,
        "artifact_dir": str(artifact_dir),
        "is_laya": is_laya,
        "commit_info": str(commit_info),
        "success": True,
    }


def publish_matrix_to_hf(
    matrix_dir: Path | str,
    repo_prefix: str,
    *,
    token: str | None = None,
    private: bool = False,
) -> list[dict[str, Any]]:
    """Publish all models in a matrix run folder to Hugging Face under repo_prefix/model_name."""
    m_path = Path(matrix_dir).resolve()
    if not m_path.exists():
        raise FileNotFoundError(f"Matrix directory not found: {m_path}")

    # Clean prefix
    prefix = repo_prefix.strip().rstrip("/")

    # Detect model subdirectories
    subdirs = [d for d in m_path.iterdir() if d.is_dir() and ((d / "adapter").exists() or (d / "checkpoint").exists())]
    if not subdirs:
        # Check if matrix_dir itself is a model run
        if (m_path / "adapter").exists() or (m_path / "checkpoint").exists():
            subdirs = [m_path]
        else:
            raise ValueError(f"No model runs found under matrix directory: {m_path}")

    results = []
    for d in sorted(subdirs, key=lambda x: x.name):
        model_name = d.name
        # Sanitize model name for HF repo ID
        clean_model_name = re.sub(r"[^a-zA-Z0-9._-]", "-", model_name)
        full_repo_id = f"{prefix}/{clean_model_name}" if "/" not in prefix else f"{prefix.split('/')[0]}/{prefix.split('/')[1]}-{clean_model_name}"

        logger.info("Publishing matrix component %s -> %s", d.name, full_repo_id)
        res = publish_run_to_hf(d, full_repo_id, token=token, private=private)
        results.append(res)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Local AI Hub fine-tuned models to Hugging Face Hub")
    parser.add_argument("--run-dir", required=True, type=Path, help="Path to single model run or matrix folder")
    parser.add_argument("--repo-id", help="Full repository ID (e.g. username/my-model) for single run")
    parser.add_argument("--repo-prefix", help="Repository prefix (e.g. username) when publishing a matrix of models")
    parser.add_argument("--token", help="Hugging Face token (defaults to HF_TOKEN or huggingface-cli cache)")
    parser.add_argument("--private", action="store_true", help="Create as private repository")
    parser.add_argument("--matrix", action="store_true", help="Treat run-dir as a matrix containing multiple models")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.matrix or args.repo_prefix:
        if not args.repo_prefix and args.repo_id:
            args.repo_prefix = args.repo_id
        if not args.repo_prefix:
            parser.error("--repo-prefix or --repo-id required for matrix publishing")
        res = publish_matrix_to_hf(args.run_dir, args.repo_prefix, token=args.token, private=args.private)
        print(json.dumps(res, indent=2))
        return 0

    if not args.repo_id:
        parser.error("--repo-id required when publishing a single run")

    res = publish_run_to_hf(args.run_dir, args.repo_id, token=args.token, private=args.private)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
