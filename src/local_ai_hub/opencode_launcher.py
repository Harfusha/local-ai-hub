"""Experimental, isolated OpenCode launch using the Hub provider lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .generator import generate_opencode_runtime_config
from .opencode_models import ModelPreparationError, ensure_model, local_inventory
from .opencode_provider_service import derive_provider_token
from .opencode_boundary import derive_local_profile_token
from .state_paths import configured_state_dir


class LaunchError(RuntimeError):
    """A local OpenCode launch or its provider cleanup was not confirmed."""


# Runtime essentials only. Credential names are open-ended and cannot be
# reliably removed using suffixes such as _TOKEN or _API_KEY.
_LOCAL_ENVIRONMENT = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
    "TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "PUBLIC", "USERNAME", "USER",
    "SHELL", "TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "PSMODULEPATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
})

_PROFILE_BOOLEAN_TABLES = ("features", "code_intelligence", "commands", "coord", "coordination",
                           "artifacts", "token_saving", "preprocessing", "async_jobs",
                           "work_orchestrator", "speculative_lint", "monitoring")


def _client_profile_config(cfg: dict, hub_port: int, *, state_dir: Path | None = None) -> str:
    lines = ["[server]", f"port = {hub_port}"]
    if state_dir is not None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("client state directory must be absolute")
        lines.append(f"state_dir = {json.dumps(str(state_dir), separators=(',', ':'))}")
    for section in _PROFILE_BOOLEAN_TABLES:
        source = cfg.get(section)
        if not isinstance(source, dict):
            continue
        entries = [(key, value) for key, value in source.items() if isinstance(key, str) and type(value) is bool]
        if entries:
            lines.extend(("", f"[{section}]"))
            lines.extend(f"{json.dumps(key, separators=(',', ':'))} = {str(value).lower()}" for key, value in sorted(entries))
    return "\n".join(lines) + "\n"


def _run_owned_process(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> int:
    """Run the interactive Windows CLI in a kill-on-close process tree."""
    if os.name != "nt":
        raise LaunchError("the experimental interactive launcher currently supports Windows only")
    from .process_utils import (_resume_suspended_process, assign_process_to_job, close_job_object,
                                create_job_object_kill_on_close, terminate_job_object, wait_job_object_empty)

    job = create_job_object_kill_on_close()
    if not job:
        raise LaunchError("cannot create a process ownership job")
    process = None
    assigned = False
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, creationflags=0x00000004)
        assigned = assign_process_to_job(job, process.pid)
        if not assigned or not _resume_suspended_process(process):
            raise LaunchError("cannot establish process ownership")
        return process.wait(timeout=timeout)
    finally:
        cleanup_confirmed = True
        try:
            if assigned:
                terminated = bool(terminate_job_object(job))
                empty = bool(wait_job_object_empty(job))
                cleanup_confirmed = terminated and empty
            elif process is not None and process.poll() is None:
                process.kill()
            if process is not None:
                process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            cleanup_confirmed = False
        finally:
            if not close_job_object(job):
                cleanup_confirmed = False
        if not cleanup_confirmed:
            raise LaunchError("OpenCode process cleanup was not confirmed")


def launch_opencode(
    client: Any, *, install_dir: Path, hub_python: Path, executable: Path,
    project: Path, model: str, run_child: Callable[..., int] = _run_owned_process,
    timeout_seconds: float = 28_800,
) -> int:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 43_200:
        raise ValueError("launch timeout must be between 1 and 43200 seconds")
    install_dir, executable, project = Path(install_dir).resolve(), Path(executable).resolve(), Path(project).resolve()
    if not project.is_dir() or not executable.is_file() or not (install_dir / "tools" / "opencode_goal" / "index.js").is_file():
        raise LaunchError("project, OpenCode executable or goal plugin is unavailable")
    cfg = client.config
    hub_token = cfg.get("security", {}).get("api_token", "")
    hub_port = cfg.get("server", {}).get("port")
    derive_provider_token(hub_token, "validation-nonce-0123456789")
    generate_opencode_runtime_config(cfg, install_dir, hub_python, model=model, provider_port=1, hub_port=hub_port)
    try:
        ensure_model(model, inventory=lambda: local_inventory(cfg.get("server", {}).get("ollama_url", "")),
                     pull=lambda _: None, allow_pull=False)
    except (ModelPreparationError, ValueError) as exc:
        raise LaunchError(f"model preflight failed: {exc}") from exc
    profile = configured_state_dir(cfg) / "opencode-local"
    for part in ("data", "cache", "state"):
        (profile / part).mkdir(parents=True, exist_ok=True)
    try:
        started = client.post("/api/opencode/provider/start", {"model": model}, timeout=55)
    except Exception:
        raise LaunchError("provider start was not confirmed; inspect provider status") from None
    if (not isinstance(started, dict) or started.get("success") is not True or started.get("host") != "127.0.0.1"
            or started.get("model") != model or type(started.get("port")) is not int
            or not 1 <= started["port"] <= 65535 or not isinstance(started.get("nonce"), str)):
        raise LaunchError("provider start was not confirmed; inspect provider status")
    nonce = started["nonce"]
    try:
        provider_token = derive_provider_token(hub_token, nonce)
        profile_token = derive_local_profile_token(hub_token, nonce)
        if profile_token is None:
            raise ValueError("invalid OpenCode profile credential")
    except ValueError:
        raise LaunchError("provider start was not confirmed; inspect provider status") from None

    failure: BaseException | None = None
    result = 1
    try:
        runtime = generate_opencode_runtime_config(cfg, install_dir, hub_python, model=model, provider_port=started["port"], hub_port=hub_port)
        env = {key: value for key, value in os.environ.items() if key.upper() in _LOCAL_ENVIRONMENT}
        with tempfile.TemporaryDirectory(prefix="config-", dir=profile) as config_dir:
            # Only non-secret transport settings go into the child profile.
            # The owner configuration is never passed as the MCP config path.
            profile_config = Path(config_dir) / "hub-client.toml"
            profile_config.write_text(_client_profile_config(cfg, hub_port), encoding="utf-8")
            runtime["mcp"]["servers"]["local-ai"]["environment"]["LOCAL_AI_CONFIG"] = str(profile_config)
            env.update({
                "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_CONFIG_CONTENT": json.dumps(runtime, separators=(",", ":")),
                "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "OPENCODE_CONFIG_DIR": config_dir, "LOCAL_AI_HUB_TOKEN": profile_token,
                "LOCAL_AI_OPENCODE_PROVIDER_TOKEN": provider_token,
                "XDG_CONFIG_HOME": config_dir, "XDG_DATA_HOME": str(profile / "data"),
                "XDG_CACHE_HOME": str(profile / "cache"), "XDG_STATE_HOME": str(profile / "state"),
            })
            result = run_child([str(executable), "--standalone", str(project)], cwd=project, env=env, timeout=timeout_seconds)
    except BaseException as exc:
        failure = exc
    try:
        stopped = client.post("/api/opencode/provider/stop", {"nonce": nonce}, timeout=15)
        if not isinstance(stopped, dict) or stopped.get("success") is not True or stopped.get("state") not in {"stopping", "stopped"}:
            raise LaunchError("provider shutdown was not confirmed")
        final = client.post("/api/opencode/provider/wait", {"timeout_seconds": 20}, timeout=25)
        if not isinstance(final, dict) or final.get("success") is not True or final.get("state") != "stopped":
            raise LaunchError("provider shutdown was not confirmed")
    except Exception:
        raise LaunchError("provider shutdown was not confirmed; inspect provider status") from None
    if failure is not None:
        raise failure
    if type(result) is not int:
        raise LaunchError("OpenCode exit status was not confirmed")
    return result
