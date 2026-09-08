from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import shutil
import subprocess
from importlib import metadata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.config import load_config

ROOT_CONFIG = ROOT / "config.toml"


def _config_arg() -> str | None:
    return str(ROOT_CONFIG) if ROOT_CONFIG.is_file() else None



def _command_version(name: str) -> str | None:
    exe = shutil.which(name)
    if not exe:
        return None
    for argv in ([exe, "--version"], [exe, "version"]):
        try:
            from local_ai_hub.process_utils import hidden_run_kwargs
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False, **hidden_run_kwargs())
            lines = (cp.stdout or cp.stderr or "").strip().splitlines()
            if lines:
                return lines[0][:200]
        except Exception:
            continue
    return "installed"


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _gpu_info() -> list[dict[str, str]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        from local_ai_hub.process_utils import hidden_run_kwargs
        cp = subprocess.run(
            [exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False, **hidden_run_kwargs(),
        )
        out = []
        for line in cp.stdout.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 3:
                out.append({"name": parts[0][:120], "driver": parts[1][:80], "memory_mib": parts[2][:32]})
        return out
    except Exception:
        return []


def _safe_tuning(cfg: dict) -> dict:
    allowed = (
        "routing", "scheduler", "ollama", "token_saving", "cache", "semantic_cache",
        "workspace_cache", "commands", "prewarm", "search", "rag", "workflow",
        "lossless_router", "local_pipeline", "execution_planner", "preprocessing",
        "tool_agent", "resilience", "observability",
    )
    return {name: cfg.get(name, {}) for name in allowed if isinstance(cfg.get(name), dict)}


def _default_output_path(state_dir: str | Path) -> Path:
    diagnostics_dir = Path(state_dir).expanduser().resolve() / "diagnostics"
    return diagnostics_dir / f"local-ai-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a source/prompt-free Local AI diagnostic report")
    parser.add_argument("--days", type=int, default=30, help="report window (default: 30 days)")
    parser.add_argument("--output", default="", help="output JSON path")
    args = parser.parse_args()

    cfg = load_config(_config_arg())
    client = HubClient(tenant="telemetry-report", config_path=_config_arg())
    try:
        telemetry = client.get(f"/v1/telemetry/report?days={max(1, args.days)}")
    except Exception:
        telemetry = {}
    try:
        status = client.get("/v1/status")
    except Exception:
        status = {}
    report = {
        "diagnostics_schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy": {
            "prompts": "not included", "source_code": "not included", "model_output": "not included",
            "project_paths": "not included by this exporter",
        },
        "environment": {
            "platform": platform.system(), "platform_release": platform.release(),
            "machine": platform.machine(), "python": platform.python_version(), "cpu_count": os.cpu_count(),
            "gpu": _gpu_info(),
            "clients": {"codex": _command_version("codex"), "claude": _command_version("claude"), "gemini": _command_version("gemini")},
            "packages": {
                "serena-agent": _package_version("serena-agent"), "codegraphcontext": _package_version("codegraphcontext"),
                "sentence-transformers": _package_version("sentence-transformers"), "mcp": _package_version("mcp"),
            },
        },
        "runtime": {
            "version": status.get("version"), "ollama_version": status.get("ollama_version"),
            "models": status.get("models"), "scheduler": status.get("scheduler"),
            "generation_cache": status.get("generation_cache"), "semantic_cache": status.get("semantic_cache"),
            "repo_cache": status.get("repo_cache"), "commands": status.get("commands"),
            "preprocessing": status.get("preprocessing"), "tool_agent": status.get("tool_agent"),
            "code_index": status.get("code_index"), "deterministic": status.get("deterministic"),
            "learning": status.get("learning"), "autotune": status.get("autotune"),
            "circuit_breakers": status.get("circuit_breakers"), "fallback_count": status.get("fallback_count"),
            "embeddings": status.get("embeddings"), "reranker": status.get("reranker"),
        },
        "tuning": _safe_tuning(cfg),
        "telemetry": telemetry.get("report", telemetry),
    }
    output = Path(args.output) if args.output else _default_output_path(cfg["server"]["state_dir"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(str(output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
