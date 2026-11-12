from __future__ import annotations

import copy
import ipaddress
import math
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .file_locks import exclusive_file_update


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
    result = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def get_table(data: Any, key: str) -> dict[str, Any]:
    """Safely retrieve a nested dictionary table from a config or section."""
    if not isinstance(data, dict):
        return {}
    val = data.get(key)
    return val if isinstance(val, dict) else {}


def get_feature(data: Any, feature: str, default: bool = True) -> bool:
    """Safely retrieve a boolean feature flag from configuration."""
    features = get_table(data, "features")
    val = features.get(feature)
    if isinstance(val, bool):
        return val
    return default


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


def _number(
    section: dict[str, Any],
    key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    label: str | None = None,
) -> None:
    if key not in section:
        return
    value = section[key]
    setting = label or key
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{setting} must be numeric")
    try:
        numeric = float(value)
    except OverflowError as exc:
        raise ConfigError(f"{setting} is outside the supported numeric range") from exc
    if minimum is not None and numeric < minimum:
        raise ConfigError(f"{setting} must be >= {minimum:g}")
    if maximum is not None and numeric > maximum:
        raise ConfigError(f"{setting} must be <= {maximum:g}")


def validate_config(data: dict[str, Any]) -> None:
    """Validate the small set of invariants that can otherwise fail late at runtime.

    Local AI Hub deliberately leaves most feature-specific keys extensible. Validation
    focuses on transport, resource limits, and code-intelligence lifecycle settings.
    """
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be a TOML table")

    for name in ("server", "security", "hardware", "openvino", "scheduler", "laya", "commands", "client", "mcp", "code_intelligence", "code_index", "bundles", "resilience", "ollama", "llama_cpp", "ollama_subagents", "agent_state", "work_orchestrator", "browser_bridge", "headless", "features", "rag"):
        if name in data and not isinstance(data[name], dict):
            raise ConfigError(f"[{name}] must be a TOML table")

    if "scope" in data.get("rag", {}):
        raise ConfigError("rag.scope was removed; use actual workspace/repository scope")

    server = data.get("server", {})
    if isinstance(server, dict) and server.get("bind", "127.0.0.1") != "127.0.0.1":
        raise ConfigError("server.bind must be 127.0.0.1; Local AI Hub is loopback-only")

    code_index = data.get("code_index", {})
    if isinstance(code_index, dict):
        _number(code_index, "max_index_bytes", minimum=1_048_576, maximum=100 * 1024 * 1024 * 1024)

    for retired_key in ("max_queued_per_tenant", "max_inflight_per_tenant"):
        if retired_key in data.get("scheduler", {}):
            raise ConfigError(f"scheduler.{retired_key} was removed; Local AI Hub has a single local owner")


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

    from .automation import validate_config as validate_automation_config
    try:
        validate_automation_config(data.get("automation", {}))
    except (ValueError, TypeError) as exc:
        raise ConfigError(str(exc)) from exc
    browser_bridge = data.get("browser_bridge", {})
    if isinstance(browser_bridge, dict):
        if "enabled" in browser_bridge and not isinstance(browser_bridge["enabled"], bool):
            raise ConfigError("browser_bridge.enabled must be a boolean")
        allowed_origins = browser_bridge.get("allowed_origins", [])
        if not isinstance(allowed_origins, list) or len(allowed_origins) > 32 or not all(isinstance(item, str) and item.strip() for item in allowed_origins):
            raise ConfigError("browser_bridge.allowed_origins must be a list of non-empty strings")
        if any("*" in item for item in allowed_origins):
            raise ConfigError("browser_bridge.allowed_origins must contain exact origins; wildcards are not allowed")
        if "tenant" in browser_bridge:
            raise ConfigError("browser_bridge.tenant was removed; Local AI Hub has a single local owner")
        _number(browser_bridge, "capability_ttl_seconds", minimum=1, maximum=3600)
        _number(browser_bridge, "max_payload_bytes", minimum=1024, maximum=64 * 1024 * 1024)
        _number(browser_bridge, "max_screenshot_bytes", minimum=1024, maximum=32 * 1024 * 1024)
        _number(browser_bridge, "max_dom_chars", minimum=1024, maximum=16 * 1024 * 1024)
        _number(browser_bridge, "max_context_chars", minimum=1024, maximum=16 * 1024 * 1024)
        _number(browser_bridge, "max_elements", minimum=1, maximum=4096)

    server = data.get("server", {})
    port = server.get("port", 11435)
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError("server.port must be an integer between 1 and 65535")
    _number(server, "request_timeout_seconds", minimum=1, maximum=86400)
    _number(server, "request_body_timeout_seconds", minimum=1, maximum=3600)
    _number(server, "max_concurrent_requests", minimum=4, maximum=4096)
    _number(server, "overload_wait_seconds", minimum=0, maximum=10)
    _number(server, "max_request_body_bytes", minimum=1024, maximum=512 * 1024 * 1024)

    headless = data.get("headless", {})
    _number(
        headless,
        "health_probe_timeout_seconds",
        minimum=0.1,
        maximum=5.0,
        label="headless.health_probe_timeout_seconds",
    )

    hardware = data.get("hardware", {})
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise ConfigError("models must be a TOML table")
    if not isinstance(models.get("allow_hf_downloads", False), bool):
        raise ConfigError("models.allow_hf_downloads must be boolean")
    profile = str(hardware.get("profile", "auto") or "auto").lower()
    if profile not in {"auto", "cpu", "integrated", "low", "balanced", "medium", "high", "max"}:
        raise ConfigError("hardware.profile must be one of auto, cpu, integrated, low, balanced, medium, high, max")

    openvino = data.get("openvino", {})
    if isinstance(openvino, dict):
        priority = openvino.get("device_priority", ["NPU", "GPU", "CPU"])
        if not isinstance(priority, list) or not priority or not all(isinstance(item, str) and item.strip() for item in priority):
            raise ConfigError("openvino.device_priority must be a non-empty list of device names")

    scheduler = data.get("scheduler", {})
    _number(scheduler, "model_switch_failure_cooldown_seconds", minimum=1, maximum=3600)
    _number(scheduler, "idle_timeout_seconds", minimum=0, maximum=86400)
    _number(scheduler, "max_caller_wait_timeout_seconds", minimum=1, maximum=86400)

    laya = data.get("laya", {})
    _number(laya, "idle_unload_seconds", minimum=600, maximum=600, label="laya.idle_unload_seconds")
    idle_unload_seconds = laya.get("idle_unload_seconds") if isinstance(laya, dict) else None
    if isinstance(idle_unload_seconds, (int, float)) and not isinstance(idle_unload_seconds, bool) and not math.isfinite(float(idle_unload_seconds)):
        raise ConfigError("laya.idle_unload_seconds must be finite")
    laya_runtime = laya.get("runtime", {}) if isinstance(laya, dict) else {}
    if not isinstance(laya_runtime, dict):
        raise ConfigError("laya.runtime must be a table")
    laya_reviewers = laya.get("reviewers", {}) if isinstance(laya, dict) else {}
    if not isinstance(laya_reviewers, dict):
        raise ConfigError("laya.reviewers must be a table")
    reviewer_public_keys = laya_reviewers.get("public_keys", [])
    if (type(reviewer_public_keys) is not list
            or any(type(key) is not str or not key.strip() for key in reviewer_public_keys)):
        raise ConfigError("laya.reviewers.public_keys must be a list of OpenSSH public-key strings")
    allow_laya_cpu = laya_runtime.get("allow_cpu", False)
    if type(allow_laya_cpu) is not bool:
        raise ConfigError("laya.runtime allow_cpu must be a boolean")
    checkpoint_path = laya_runtime.get("checkpoint_path", "")
    revision = laya_runtime.get("revision", "")
    expected_hashes = laya_runtime.get("expected_sha256", {})
    checkpoint_configured = checkpoint_path != "" or revision != "" or expected_hashes != {}
    if checkpoint_configured:
        if (not isinstance(checkpoint_path, str) or not checkpoint_path
                or not Path(checkpoint_path).is_absolute()):
            raise ConfigError("laya.runtime requires an absolute checkpoint_path")
        if (not isinstance(revision, str) or not revision or Path(checkpoint_path).name != revision):
            raise ConfigError("laya.runtime requires revision matching the checkpoint directory")
        if not isinstance(expected_hashes, dict) or not expected_hashes:
            raise ConfigError("laya.runtime requires expected_sha256 hashes")
        for filename, digest in expected_hashes.items():
            if (not isinstance(filename, str) or Path(filename).is_absolute()
                    or ".." in Path(filename).parts or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ConfigError("laya.runtime expected_sha256 contains an invalid path or digest")

    resilience = data.get("resilience", {})
    _number(resilience, "singleflight_wait_timeout_seconds", minimum=0.1, maximum=3600)
    _number(resilience, "repository_search_timeout_seconds", minimum=0.1, maximum=900)
    _number(resilience, "scheduler_wait_timeout_seconds", minimum=0.1, maximum=86400)

    ollama = data.get("ollama", {})
    _number(ollama, "startup_timeout_seconds", minimum=1, maximum=300)

    llama_cpp = data.get("llama_cpp", {})
    if isinstance(llama_cpp, dict):
        mode = str(llama_cpp.get("mode", "auto")).strip().lower()
        if mode not in {"off", "auto", "on"}:
            raise ConfigError("llama_cpp.mode must be off, auto, or on")
        backend = llama_cpp.get("backend", "auto")
        if not isinstance(backend, str) or backend not in {"auto", "cuda"}:
            raise ConfigError("llama_cpp.backend must be auto or cuda")
        cache_types = {"f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"}
        for cache_key in ("cache_type_k", "cache_type_v"):
            cache_type = llama_cpp.get(cache_key)
            if cache_type is not None and (not isinstance(cache_type, str) or cache_type not in cache_types):
                raise ConfigError(f"llama_cpp.{cache_key} must be a supported llama.cpp KV cache type")
        if "managed_model_sha256" in llama_cpp:
            digest = llama_cpp["managed_model_sha256"]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ConfigError("llama_cpp.managed_model_sha256 must be a lowercase SHA-256 digest")
        _number(llama_cpp, "model_load_timeout_seconds", minimum=1, maximum=3600)
        _number(llama_cpp, "startup_timeout_seconds", minimum=1, maximum=3600)
        model_filename = str(llama_cpp.get("managed_model_filename", "hub-qwen-15.gguf")).strip()
        if not model_filename or Path(model_filename).name != model_filename or not model_filename.lower().endswith(".gguf"):
            raise ConfigError("llama_cpp.managed_model_filename must be a .gguf filename inside the managed model directory")
        models = llama_cpp.get("models", {})
        if not isinstance(models, dict):
            raise ConfigError("llama_cpp.models must be a TOML table")
        if "managed_model_logical" in llama_cpp:
            logical = llama_cpp["managed_model_logical"]
            if ("managed_model_sha256" not in llama_cpp or not isinstance(logical, str)
                    or not logical or logical != logical.strip() or "vl" in logical.lower()
                    or not isinstance(models.get(logical), dict)):
                raise ConfigError("llama_cpp.managed_model_logical must select one configured text model with a managed model digest")
        if "managed_with_ollama" in llama_cpp:
            mixed = llama_cpp["managed_with_ollama"]
            if not isinstance(mixed, bool):
                raise ConfigError("llama_cpp.managed_with_ollama must be a boolean")
            if mixed and (mode != "on" or backend != "cuda" or "managed_model_logical" not in llama_cpp
                          or not isinstance(data.get("ollama"), dict) or data["ollama"].get("enabled") is not True):
                raise ConfigError("llama_cpp.managed_with_ollama requires enabled Ollama, managed CUDA, and an explicit model")
            if mixed and isinstance(data.get("smart_ollama"), dict) and bool(data["smart_ollama"].get("enabled", False)):
                raise ConfigError("llama_cpp.managed_with_ollama does not support smart_ollama")
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
            for filename_key, digest_key in (("model_filename", "model_sha256"), ("mmproj_filename", "mmproj_sha256")):
                filename = entry.get(filename_key)
                digest = entry.get(digest_key)
                if filename is None and digest is None:
                    continue
                if (not isinstance(filename, str) or not filename or Path(filename).name != filename
                        or not filename.lower().endswith(".gguf")):
                    raise ConfigError(f"llama_cpp.models.{model}.{filename_key} must be a .gguf filename inside the managed model directory")
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ConfigError(f"llama_cpp.models.{model}.{digest_key} must be a lowercase SHA-256 digest")
            gpu_layers = entry.get("gpu_layers")
            if gpu_layers is not None and (type(gpu_layers) is not int or not 0 <= gpu_layers <= 999):
                raise ConfigError(f"llama_cpp.models.{model}.gpu_layers must be an integer between 0 and 999")

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
    _number(commands, "max_output_bytes", minimum=1024, maximum=400_000_000)

    mcp = data.get("mcp", {})
    for key in ("quick_timeout_seconds", "context_timeout_seconds", "model_timeout_seconds", "long_timeout_seconds", "host_tool_timeout_seconds"):
        _number(mcp, key, minimum=1, maximum=86400)

    intel = data.get("code_intelligence", {})
    for key in ("startup_timeout_seconds", "query_timeout_seconds", "index_timeout_seconds", "session_idle_ttl_seconds"):
        _number(intel, key, minimum=1, maximum=86400)
    _number(intel, "soft_timeout_seconds", minimum=0.1, maximum=300)
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
        for retired_key in ("api_token", "supervisor_token", "action_tokens", "api_token_permissions"):
            if retired_key in security:
                raise ConfigError(f"security.{retired_key} was removed; remove Hub API token configuration")
        if "allow_remote" in security:
            raise ConfigError("security.allow_remote was removed; Local AI Hub has no remote access mode")
        for key in ("allowed_hosts", "allowed_origins"):
            if security.get(key):
                raise ConfigError(f"security.{key} was removed; Local AI Hub accepts local origins only")
        for retired_key in ("api_token_tenant", "api_token_principal", "tenant_derivation_key", "users"):
            if retired_key in security:
                raise ConfigError(f"security.{retired_key} was removed; Local AI Hub has a single local owner")

        allowed_roots = security.get("allowed_roots", [])
        if (
            not isinstance(allowed_roots, list)
            or len(allowed_roots) > 32
            or any(not isinstance(root, str) or not root.strip() or len(root.strip()) > 4096 or "\0" in root for root in allowed_roots)
        ):
            raise ConfigError("security.allowed_roots must be a list of at most 32 non-empty paths of at most 4096 characters")
        try:
            if any(not Path(root.strip()).expanduser().is_absolute() for root in allowed_roots):
                raise ConfigError("security.allowed_roots entries must be absolute paths")
        except (ValueError, OSError) as exc:
            raise ConfigError(f"security.allowed_roots invalid path: {exc}") from exc
        if security.get("allow_anonymous") is True:
            raise ConfigError("security.allow_anonymous was removed; Hub access is loopback-only and uses no API token")
        if "client_host" in server:
            raise ConfigError("server.client_host was removed; Hub clients connect only to 127.0.0.1")
        bind = str(server.get("bind", "127.0.0.1"))
        if bind != "127.0.0.1":
            raise ConfigError("Refusing non-approved Local AI Hub bind: server.bind must be 127.0.0.1")



def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
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
    if isinstance(config_path, str) and "\0" in config_path:
        raise ConfigError("invalid configuration path: embedded null byte")
    try:
        path = Path(config_path).expanduser().resolve(strict=False)
    except (ValueError, OSError) as exc:
        raise ConfigError(f"invalid configuration path: {exc}") from exc
    return path.with_name("config.runtime.toml")


def save_runtime_overrides(config_path: str | os.PathLike[str], patch: dict[str, Any], *, reset: bool = False) -> Path:
    """Atomically persist dashboard-managed overrides without rewriting config.toml."""
    target = runtime_override_path(config_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_update(target):
        if reset:
            target.unlink(missing_ok=True)
            return target
        current = _read_toml(target) if target.is_file() else {}
        text = _dump_toml_tables(deep_merge(current, patch))
        descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        tmp = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    return target

def load_config(path: str | os.PathLike[str] | None = None, *, probe_hardware: bool = True) -> dict[str, Any]:
    if path is None:
        path = os.environ.get("LOCAL_AI_CONFIG")
    if isinstance(path, str) and "\0" in path:
        raise ConfigError("invalid configuration path: embedded null byte")
    package_dir = Path(__file__).resolve().parent
    source_root = Path(__file__).resolve().parents[2]
    if path is None:
        home_config = Path.home() / ".local-ai-hub" / "config.toml"
        source_config = source_root / "config.toml"
        config_path = home_config if home_config.exists() else source_config if source_config.exists() else home_config
    else:
        try:
            config_path = Path(path).expanduser()
        except (ValueError, OSError) as exc:
            raise ConfigError(f"invalid configuration path: {exc}") from exc

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
        if not probe_hardware:
            # Transport clients read explicit policy/settings without per-client
            # device subprocesses. The shared server owns automatic tuning and
            # model selection; its default full probe/overlay is unchanged.
            detected = {"profile": str(hardware_cfg.get("profile", "auto")), "inventory_deferred": True}
        else:
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
