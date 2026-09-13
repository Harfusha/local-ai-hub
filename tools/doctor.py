from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from local_ai_hub.client import HubClient
from local_ai_hub.config import load_config
from local_ai_hub.doctor_support import probe_hub_status
from local_ai_hub.http_server import validate_network_security


def project_python() -> Path:
    candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    )
    return next((path for path in candidates if path.exists()), Path(sys.executable))


def runtime_module_available(module: str) -> bool:
    interpreter = project_python()
    try:
        from local_ai_hub.process_utils import hidden_run_kwargs
        result = subprocess.run(
            [str(interpreter), "-c", f"import {module}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
            **hidden_run_kwargs(),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False



def command_version(name: str) -> str | None:
    exe = shutil.which(name)
    if not exe:
        return None
    for args in ([exe, "--version"], [exe, "version"]):
        try:
            from local_ai_hub.process_utils import hidden_run_kwargs
            cp = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False, **hidden_run_kwargs())
            text = (cp.stdout or cp.stderr or "").strip().splitlines()
            if text:
                return text[0][:200]
        except Exception:
            continue
    return "installed"

def tool_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(re.findall(r"(?m)^@mcp\.tool\(\)\s*$", path.read_text(encoding="utf-8")))
    except Exception:
        return 0


cfg = load_config(str(root / "config.toml"))
client = HubClient(tenant="doctor", config_path=str(root / "config.toml"), auto_start=False)
hub_probe = probe_hub_status(client)
status = hub_probe["status"]
hub_online = bool(hub_probe["hub_online"])
status_available = bool(hub_probe["status_available"])
try:
    telemetry_report = client.get("/api/telemetry/report?days=30")
except Exception:
    telemetry_report = {}
models = cfg.get("models", {})
configured_generation: list[str] = []
for key in ("background_code", "fast_code", "heavy_code", "reasoning", "general"):
    model = str(models.get(key, ""))
    if model and model not in configured_generation:
        configured_generation.append(model)
installed = set(status.get("installed_models", [])) if isinstance(status, dict) else set()
missing_models = [m for m in configured_generation if installed and m not in installed]

mcp_file = root / "src" / "local_ai_hub" / "mcp_server.py"
state_dir = Path(cfg.get("server", {}).get("state_dir", "~/.local-ai-hub/state")).expanduser()
install_dir = Path(cfg.get("setup", {}).get("install_dir", "~/.local-ai-hub")).expanduser()
codegraph_candidates = [
    install_dir / "tool-envs" / "codegraph" / "Scripts" / "codegraphcontext.exe",
    install_dir / "tool-envs" / "codegraph" / "Scripts" / "cgc.exe",
    install_dir / "tool-envs" / "codegraph" / "bin" / "codegraphcontext",
    install_dir / "tool-envs" / "codegraph" / "bin" / "cgc",
]

warnings: list[str] = []
openvino_requested = str(models.get("embedding_backend", "")).lower() == "openvino" or str(models.get("reranker_backend", "")).lower() == "openvino"
openvino_installed = runtime_module_available("openvino")
if openvino_requested and not openvino_installed:
    warnings.append("OpenVINO acceleration is configured but runtime is not installed in hub environment; embeddings/reranking will fall back to CPU. Run: pip install -r requirements-openvino.txt")

hw_detected = status.get("hardware") or cfg.get("_hardware") or {}
gpus = hw_detected.get("gpus", []) if isinstance(hw_detected, dict) else []
npus = hw_detected.get("npus", []) if isinstance(hw_detected, dict) else []
has_nvidia = any(str(g.get("vendor", "")).lower() == "nvidia" for g in gpus if isinstance(g, dict))
has_igpu = any(bool(g.get("integrated")) or "intel" in str(g.get("name", "")).lower() or "radeon" in str(g.get("name", "")).lower() for g in gpus if isinstance(g, dict))

if npus and not openvino_installed:
    warnings.append("NPU hardware detected, but openvino is not installed in hub environment. Embeddings and reranker will burn CPU. Run: pip install -r requirements-openvino.txt && python tools/prefetch_openvino.py")

if os.name == "nt" and (has_igpu or cfg.get("hardware", {}).get("profile") == "integrated") and not has_nvidia:
    if not os.environ.get("OLLAMA_VULKAN"):
        warnings.append("Integrated GPU detected on Windows, but OLLAMA_VULKAN is not set in the environment. Ollama may run LLMs entirely on CPU. Run in PowerShell: [System.Environment]::SetEnvironmentVariable('OLLAMA_VULKAN', '1', 'User') and restart Ollama.")
try:
    validate_network_security(cfg)
    network_security = "ok"
except Exception as exc:
    network_security = f"invalid: {exc}"
    warnings.append(str(exc))
if not hub_online:
    warnings.append("Local AI Hub is not online")
elif not status_available:
    warnings.append("Local AI Hub health check passed but its status endpoint did not return diagnostic data")
if status.get("hub_online", False) and not status.get("ollama_online", False):
    warnings.append("Ollama is not online")
if missing_models:
    warnings.append("Missing configured Ollama models: " + ", ".join(missing_models))
if not mcp_file.exists():
    warnings.append(f"Selected MCP surface file is missing: {mcp_file}")
telemetry_summary = ((telemetry_report.get("report") or {}).get("summary") or {}) if isinstance(telemetry_report, dict) else {}
writer = telemetry_summary.get("writer", {}) if isinstance(telemetry_summary, dict) else {}
if int(writer.get("dropped", 0) or 0) > 0:
    warnings.append(f"Telemetry queue dropped {writer.get('dropped')} events; increase [observability].queue_size or reduce logging volume")
if int(writer.get("writer_errors", 0) or 0) > 0:
    warnings.append(f"Telemetry writer has {writer.get('writer_errors')} errors; inspect logs/telemetry database health")

loaded_details = status.get("loaded_model_details", []) if isinstance(status, dict) else []
background_gpu = status.get("background_gpu", {}) if isinstance(status, dict) else {}
execution_summary = (status.get("model_execution") or (status.get("runtime_profile", {}) or {}).get("execution", {})) if isinstance(status, dict) else {}
ollama_profile = status.get("ollama_profile", {}) if isinstance(status, dict) else {}
if not ollama_profile:
    try:
        from local_ai_hub.ollama import OllamaRuntime
        ollama_profile = OllamaRuntime(cfg).managed_profile_status()
    except Exception:
        pass
diag_cfg = cfg.get("diagnostics", {})
if (
    bool(diag_cfg.get("warn_if_external_ollama_profile_unknown", True))
    and status.get("ollama_online", False)
    and isinstance(ollama_profile, dict)
    and not bool(ollama_profile.get("profile_verifiable", False))
):
    expected = ollama_profile.get("expected", {}) if isinstance(ollama_profile, dict) else {}
    warnings.append(
        "Ollama is already running outside the hub-managed process; Local AI Hub cannot verify the configured "
        f"foreground profile (NUM_PARALLEL={expected.get('num_parallel', cfg.get('ollama', {}).get('num_parallel', 1))}, "
        f"integrated-GPU admission={expected.get('allow_integrated_gpu', cfg.get('ollama', {}).get('allow_integrated_gpu', False))}, "
        f"Vulkan={expected.get('enable_vulkan', cfg.get('ollama', {}).get('enable_vulkan', False))}, "
        f"Flash Attention={expected.get('flash_attention', cfg.get('ollama', {}).get('flash_attention', True))}, "
        f"KV cache={expected.get('kv_cache_type', cfg.get('ollama', {}).get('kv_cache_type', 'q8_0'))}). "
        "Restart Ollama under the hub/service or apply the equivalent environment before starting Ollama."
    )
fast_model = str(models.get("fast_code", ""))
smart_models = {str(models.get("heavy_code", "")), str(models.get("reasoning", ""))}
background_model = str(models.get("background_code", ""))
expected_context = {
    str(item.get("model", "")): int(item.get("num_ctx", 0) or 0)
    for item in (execution_summary.get("models", []) if isinstance(execution_summary, dict) else [])
    if isinstance(item, dict) and item.get("model")
}
for row in loaded_details if isinstance(loaded_details, list) else []:
    if not isinstance(row, dict):
        continue
    model_name = str(row.get("name", ""))
    offload = float(row.get("cpu_offload_fraction", 0.0) or 0.0)
    limit = float(diag_cfg.get("max_fast_cpu_offload_fraction", 0.08)) if model_name == fast_model else float(diag_cfg.get("max_smart_cpu_offload_fraction", 0.20)) if model_name in smart_models else 1.0
    if offload > limit:
        warnings.append(f"{model_name} CPU offload is {offload:.0%}, above the configured {limit:.0%} target; close GPU-heavy apps first, then reduce context/concurrency only if needed")
    actual_ctx = int(row.get("context_length", 0) or 0)
    desired_ctx = int(expected_context.get(model_name, 0) or 0)
    if desired_ctx and actual_ctx and actual_ctx < desired_ctx:
        warnings.append(f"{model_name} is loaded with context {actual_ctx}, below the target {desired_ctx}; unload/reload it through the hub so the execution profile is applied")

if isinstance(background_gpu, dict) and background_gpu.get("enabled"):
    bg_error = str(background_gpu.get("last_error") or "")
    if bg_error and (
        bool(background_gpu.get("startup_circuit_open"))
        or float(background_gpu.get("retry_after_seconds", 0.0) or 0.0) > 0.0
    ):
        warnings.append("Background GPU worker: " + bg_error)
    bg_limit = float(cfg.get("background_gpu", {}).get("max_cpu_offload_fraction", 0.12))
    for row in background_gpu.get("models", []) if isinstance(background_gpu.get("models"), list) else []:
        if not isinstance(row, dict):
            continue
        offload = float(row.get("cpu_offload_fraction", 0.0) or 0.0)
        if offload > bg_limit:
            warnings.append(f"{background_model} background CPU offload is {offload:.0%}, above the configured {bg_limit:.0%} target; reduce background concurrency/context only if measured throughput is poor")

report = {
    "version": status.get("version") if isinstance(status, dict) else None,
    "python": sys.version.split()[0],
    "config": {
        "user": cfg.get("_config_path"),
        "defaults": cfg.get("_defaults_path"),
        "mcp_surface": "compact",
        "mcp_tool_count": tool_count(mcp_file),
        "network_security": network_security,
    },
    "runtime": {
        "ollama_command": shutil.which("ollama"),
        "ripgrep_command": shutil.which("rg"),
        "fd_command": shutil.which("fd") or shutil.which("fdfind"),
        "ast_grep_command": shutil.which("ast-grep") or shutil.which("sg"),
        "repomix_command": shutil.which("repomix"),
        "jq_command": shutil.which("jq"),
        "tokcount_command": shutil.which("tokcount"),
        "trim_run_command": shutil.which("trim-run"),
        "repo_map_command": shutil.which("repo-map"),
        "hub_online": hub_online,
        "ollama_online": status.get("ollama_online") if isinstance(status, dict) else False,
        "active_model": (status.get("scheduler") or {}).get("active_model") if isinstance(status, dict) else None,
        "configured_generation_models": configured_generation,
        "missing_generation_models": missing_models,
        "model_execution": execution_summary,
        "loaded_model_details": loaded_details,
        "ollama_profile": ollama_profile,
        "background_gpu": background_gpu,
        "sentence_transformers": runtime_module_available("sentence_transformers"),
        "openvino": {"requested": openvino_requested, "installed": openvino_installed, "status": status.get("accelerators") if isinstance(status, dict) else None},
        "codegraph_executable": next((str(p) for p in codegraph_candidates if p.exists()), None),
        "hardware": cfg.get("_hardware", {}),
        "code_intelligence": status.get("code_intelligence") if isinstance(status, dict) else None,
        "preprocessing": status.get("preprocessing") if isinstance(status, dict) else None,
        "tool_agent": status.get("tool_agent") if isinstance(status, dict) else None,
        "code_index": status.get("code_index") if isinstance(status, dict) else None,
        "deterministic": status.get("deterministic") if isinstance(status, dict) else None,
        "evidence_store": status.get("evidence_store") if isinstance(status, dict) else None,
        "learning": status.get("learning") if isinstance(status, dict) else None,
        "autotune": status.get("autotune") if isinstance(status, dict) else None,
        "agent_state": status.get("agent_state") if isinstance(status, dict) else None,
        "clients": {"codex": command_version("codex"), "claude": command_version("claude"), "gemini": command_version("gemini")},
        "observability": {"summary": telemetry_summary, "report_command": f"{sys.executable} {root / 'tools' / 'telemetry_report.py'} --days 30"},
    },
    "state": {
        "directory": str(state_dir),
        "shared_cache": (state_dir / "cache.sqlite3").exists(),
        "rag": (state_dir / "rag.sqlite3").exists(),
        "workspace_memory": (state_dir / "workspace_memory.sqlite3").exists(),
        "preprocessing": (state_dir / "preprocess.sqlite3").exists(),
        "telemetry": (state_dir / "telemetry.sqlite3").exists(),
        "operational_log": str(state_dir / "logs" / "hub.log"),
        "code_index": (state_dir / "code-index.sqlite3").exists(),
        "deterministic": (state_dir / "deterministic.sqlite3").exists(),
        "evidence": (state_dir / "evidence.sqlite3").exists(),
        "learning": (state_dir / "learning.sqlite3").exists(),
        "recovery": (state_dir / "recovery.sqlite3").exists(),
        "agent_state": (state_dir / "agent_state.sqlite3").exists(),
    },
    "skill_paths": {
        "agent_skills_standard": str(Path.home() / ".agents" / "skills" / "local-ai-orchestrator" / "SKILL.md"),
        "codex": str(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills" / "local-ai-orchestrator" / "SKILL.md"),
        "claude": str(Path.home() / ".claude" / "skills" / "local-ai-orchestrator" / "SKILL.md"),
        "gemini": str(Path.home() / ".gemini" / "skills" / "local-ai-orchestrator" / "SKILL.md"),
    },
    "warnings": warnings,
}
for key, value in report["skill_paths"].items():
    report["skill_paths"][key] = {"path": value, "exists": Path(value).exists()}
print(json.dumps(report, indent=2, ensure_ascii=False))
