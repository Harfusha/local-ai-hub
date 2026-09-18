from __future__ import annotations

import copy
import ipaddress
import os
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when a Local AI Hub configuration cannot be parsed or validated."""


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value))
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(override, dict):
        return copy.deepcopy(override)
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_toml(path: Path, *, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise ConfigError(f"configuration file does not exist: {path}")
        return {}
    if not path.is_file():
        raise ConfigError(f"configuration path is not a file: {path}")
    try:
        with path.open("rb") as fh:
            value = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read TOML configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"configuration root must be a TOML table: {path}")
    return value


def _number(section: dict[str, Any], key: str, *, minimum: float | None = None, maximum: float | None = None) -> None:
    if key not in section:
        return
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be numeric")
    numeric = float(value)
    if minimum is not None and numeric < minimum:
        raise ConfigError(f"{key} must be >= {minimum:g}")
    if maximum is not None and numeric > maximum:
        raise ConfigError(f"{key} must be <= {maximum:g}")


def validate_config(data: dict[str, Any]) -> None:
    """Validate the small set of invariants that can otherwise fail late at runtime.

    Local AI Hub deliberately leaves most feature-specific keys extensible. Validation
    focuses on transport, resource limits, and code-intelligence lifecycle settings.
    """
    for name in ("server", "security", "hardware", "openvino", "scheduler", "commands", "client", "mcp", "code_intelligence", "bundles", "resilience", "ollama", "llama_cpp", "ollama_subagents", "agent_state", "work_orchestrator"):
        if name in data and not isinstance(data[name], dict):
            raise ConfigError(f"[{name}] must be a TOML table")


    work = data.get("work_orchestrator", {})
    if isinstance(work, dict):
        _number(work, "max_active_work_orders", minimum=1, maximum=16)
        _number(work, "max_pending_work_orders", minimum=1, maximum=256)
        _number(work, "worker_idle_seconds", minimum=5, maximum=3600)
        _number(work, "max_steps", minimum=1, maximum=64)
        _number(work, "max_llm_steps", minimum=1, maximum=32)
        _number(work, "max_replans", minimum=0, maximum=4)
        _number(work, "max_seconds", minimum=30, maximum=7200)
        _number(work, "parallel_llm_steps", minimum=1, maximum=8)
        _number(work, "parallel_deterministic_steps", minimum=1, maximum=16)
        _number(work, "step_retry_limit", minimum=0, maximum=4)
        _number(work, "validation_commands", minimum=1, maximum=8)
        _number(work, "max_patch_files", minimum=1, maximum=128)
        _number(work, "max_patch_bytes", minimum=4096, maximum=4 * 1024 * 1024)
        _number(work, "default_max_output_tokens", minimum=64, maximum=4096)
        profile = str(work.get("default_response_profile", "compact")).strip().lower()
        if profile not in {"minimal", "compact", "standard", "debug"}:
            raise ConfigError("work_orchestrator.default_response_profile must be minimal, compact, standard, or debug")

    agent_state = data.get("agent_state", {})
    if isinstance(agent_state, dict):
        _number(agent_state, "event_retention_days", minimum=1, maximum=3650)
        _number(agent_state, "max_payload_bytes", minimum=1024, maximum=10 * 1024 * 1024)
        _number(agent_state, "snapshot_interval_events", minimum=1, maximum=10000)
        _number(agent_state, "cleanup_batch_size", minimum=1, maximum=10000)

    server = data.get("server", {})
    port = server.get("port", 11435)
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("server.port must be an integer between 1 and 65535")
    _number(server, "request_timeout_seconds", minimum=1, maximum=86400)
    _number(server, "request_body_timeout_seconds", minimum=1, maximum=3600)
    _number(server, "max_concurrent_requests", minimum=4, maximum=4096)
    _number(server, "overload_wait_seconds", minimum=0, maximum=10)
    _number(server, "max_request_body_bytes", minimum=1024, maximum=512 * 1024 * 1024)

    hardware = data.get("hardware", {})
    profile = str(hardware.get("profile", "auto") or "auto").lower()
    if profile not in {"auto", "cpu", "integrated", "low", "balanced", "high", "max"}:
        raise ConfigError("hardware.profile must be one of auto, cpu, integrated, low, balanced, high, max")

    openvino = data.get("openvino", {})
    if isinstance(openvino, dict):
        priority = openvino.get("device_priority", ["NPU", "GPU", "CPU"])
        if not isinstance(priority, list) or not priority or not all(isinstance(item, str) and item.strip() for item in priority):
            raise ConfigError("openvino.device_priority must be a non-empty list of device names")

    scheduler = data.get("scheduler", {})
    _number(scheduler, "model_switch_failure_cooldown_seconds", minimum=1, maximum=3600)
    _number(scheduler, "max_caller_wait_timeout_seconds", minimum=1, maximum=86400)

    resilience = data.get("resilience", {})
    _number(resilience, "singleflight_wait_timeout_seconds", minimum=0.1, maximum=3600)
    _number(resilience, "scheduler_wait_timeout_seconds", minimum=0.1, maximum=86400)

    ollama = data.get("ollama", {})
    _number(ollama, "startup_timeout_seconds", minimum=1, maximum=300)

    llama_cpp = data.get("llama_cpp", {})
    if isinstance(llama_cpp, dict):
        mode = str(llama_cpp.get("mode", "auto")).strip().lower()
        if mode not in {"off", "auto", "on"}:
            raise ConfigError("llama_cpp.mode must be off, auto, or on")
        _number(llama_cpp, "model_load_timeout_seconds", minimum=1, maximum=3600)
        models = llama_cpp.get("models", {})
        if not isinstance(models, dict):
            raise ConfigError("llama_cpp.models must be a TOML table")
        for model, entry in models.items():
            if not isinstance(entry, dict):
                raise ConfigError(f"llama_cpp.models.{model} must be a TOML table")
            raw_url = str(entry.get("url", "")).strip()
            try:
                parsed = urlsplit(raw_url)
                if parsed.port is not None and not 1 <= parsed.port <= 65535:
                    raise ValueError("invalid port")
            except ValueError as exc:
                raise ConfigError(f"llama_cpp.models.{model}.url is invalid") from exc
            host = (parsed.hostname or "").lower()
            is_loopback = host in {"localhost", "127.0.0.1", "::1"}
            if not is_loopback:
                try:
                    is_loopback = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    is_loopback = False
            if parsed.scheme not in {"http", "https"} or not is_loopback or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
                raise ConfigError(f"llama_cpp.models.{model}.url must be a loopback HTTP(S) base URL")
            if not str(entry.get("served_model", model)).strip():
                raise ConfigError(f"llama_cpp.models.{model}.served_model must not be empty")
            _number(entry, "context_length", minimum=512, maximum=131072)

    subagents = data.get("ollama_subagents", {})
    if isinstance(subagents, dict):
        profiles = subagents.get("profiles", {})
        if profiles is not None and not isinstance(profiles, dict):
            raise ConfigError("ollama_subagents.profiles must be a TOML table")
        for profile_name, profile in (profiles or {}).items():
            if not isinstance(profile, dict):
                raise ConfigError(f"ollama_subagents.profiles.{profile_name} must be a TOML table")
            _number(profile, "max_steps", minimum=1, maximum=8)
            _number(profile, "max_tool_calls", minimum=1, maximum=16)
            _number(profile, "max_tokens", minimum=64, maximum=8192)
            _number(profile, "temperature", minimum=0, maximum=1)

    client = data.get("client", {})
    _number(client, "health_timeout_seconds", minimum=0.1, maximum=60)
    _number(client, "startup_wait_seconds", minimum=1, maximum=300)
    _number(client, "max_request_timeout_seconds", minimum=5, maximum=86400)

    commands = data.get("commands", {})
    _number(commands, "timeout_seconds", minimum=1, maximum=86400)
    _number(commands, "coalesced_wait_seconds", minimum=1, maximum=3600)
    _number(commands, "terminate_grace_seconds", minimum=0.1, maximum=30)
    _number(commands, "post_kill_drain_seconds", minimum=0.1, maximum=30)
    _number(commands, "max_output_chars", minimum=1024, maximum=100_000_000)

    mcp = data.get("mcp", {})
    for key in ("quick_timeout_seconds", "context_timeout_seconds", "model_timeout_seconds", "long_timeout_seconds", "host_tool_timeout_seconds"):
        _number(mcp, key, minimum=1, maximum=86400)

    intel = data.get("code_intelligence", {})
    for key in ("startup_timeout_seconds", "query_timeout_seconds", "index_timeout_seconds", "session_idle_ttl_seconds"):
        _number(intel, key, minimum=1, maximum=86400)
    _number(intel, "max_sessions_per_backend", minimum=1, maximum=128)
    _number(intel, "failure_threshold", minimum=1, maximum=100)

    bundles = data.get("bundles", {})
    _number(bundles, "max_bundle_bytes", minimum=1024, maximum=512 * 1024 * 1024)
    _number(bundles, "max_json_bytes", minimum=1024, maximum=1024 * 1024 * 1024)
    _number(bundles, "max_rows_per_table", minimum=1, maximum=10_000_000)

    security = data.get("security", {})
    if security is not None:
        if not isinstance(security, dict):
            raise ConfigError("security must be a TOML table")
        allow_remote = security.get("allow_remote")
        if allow_remote is not None and not isinstance(allow_remote, bool):
            raise ConfigError("security.allow_remote must be a boolean")
        bind = str(server.get("bind", "127.0.0.1")).strip().lower()
        if bind not in {"127.0.0.1", "localhost", "::1"}:
            if not bool(allow_remote):
                raise ConfigError("Refusing non-loopback Local AI Hub bind: set [security].allow_remote=true explicitly")
            token = str(security.get("api_token", "") or "")
            if len(token) < 16:
                raise ConfigError("Remote Local AI Hub bind requires [security].api_token with at least 16 characters")



def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(v) for v in value) + "]"
    raise ConfigError(f"unsupported runtime override value: {type(value).__name__}")


def _dump_toml_tables(data: dict[str, Any]) -> str:
    """Serialize the small dashboard runtime-override document.

    This intentionally supports only scalar/list values and nested tables. It is not a
    general TOML writer; the user's primary config file is never rewritten.
    """
    lines: list[str] = []
    def emit(table: dict[str, Any], prefix: str = "") -> None:
        scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
        children = [(k, v) for k, v in table.items() if isinstance(v, dict)]
        if prefix:
            lines.append(f"[{prefix}]")
        for key, value in scalars:
            lines.append(f"{key} = {_toml_scalar(value)}")
        if prefix and (scalars or children):
            lines.append("")
        for key, child in children:
            emit(child, f"{prefix}.{key}" if prefix else key)
    emit(data)
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def runtime_override_path(config_path: str | os.PathLike[str]) -> Path:
    path = Path(config_path).expanduser().resolve(strict=False)
    return path.with_name("config.runtime.toml")


def save_runtime_overrides(config_path: str | os.PathLike[str], patch: dict[str, Any], *, reset: bool = False) -> Path:
    """Atomically persist dashboard-managed overrides without rewriting config.toml."""
    target = runtime_override_path(config_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return target
    current = _read_toml(target) if target.is_file() else {}
    merged = deep_merge(current, patch)
    text = _dump_toml_tables(merged)
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return target

def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    if path is None:
        path = os.environ.get("LOCAL_AI_CONFIG")
    package_dir = Path(__file__).resolve().parent
    source_root = Path(__file__).resolve().parents[2]
    if path is None:
        home_config = Path.home() / ".local-ai-hub" / "config.toml"
        source_config = source_root / "config.toml"
        config_path = home_config if home_config.exists() else source_config if source_config.exists() else home_config
    else:
        config_path = Path(path).expanduser()

    # Prefer defaults next to the selected config (copied install layout), then the
    # source checkout, then package data from a wheel/editable install.
    default_candidates = [
        config_path.resolve(strict=False).parent / "defaults.toml",
        source_root / "defaults.toml",
        package_dir / "defaults.toml",
    ]
    defaults_path = next((candidate for candidate in default_candidates if candidate.is_file()), None)
    if defaults_path is None:
        raise ConfigError("Local AI Hub defaults.toml was not found; reinstall the package")

    defaults = _read_toml(defaults_path, required=True)
    user = _read_toml(config_path, required=path is not None)
    runtime_path = runtime_override_path(config_path)
    runtime = _read_toml(runtime_path)

    # Hardware tuning is an overlay on defaults, then user/runtime overrides.
    # This makes the stock install portable while keeping every knob overridable.
    hardware_cfg = deep_merge(deep_merge(defaults.get("hardware", {}), user.get("hardware", {})), runtime.get("hardware", {}))
    try:
        from .hardware import detect_hardware, profile_overrides
        detected = detect_hardware(str(hardware_cfg.get("profile", "auto")))
        if bool(hardware_cfg.get("auto_tune", True)):
            defaults = deep_merge(defaults, profile_overrides(str(detected.get("profile", "balanced")), detected))
    except Exception as exc:
        detected = {"profile": str(hardware_cfg.get("profile", "auto")), "detection_error": type(exc).__name__}

    data = _expand(deep_merge(deep_merge(defaults, user), runtime))
    validate_config(data)
    data["_hardware"] = detected
    data["_config_path"] = str(config_path.resolve(strict=False))
    data["_defaults_path"] = str(defaults_path.resolve())
    data["_runtime_override_path"] = str(runtime_path)
    return data
