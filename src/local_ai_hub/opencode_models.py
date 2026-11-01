"""Explicit, bounded model preparation for the experimental OpenCode profile."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from collections.abc import Callable

from local_ai_hub.opencode_provider_service import _upstream_port
from local_ai_hub.opencode_model_names import validate_local_model_name
from local_ai_hub.process_utils import ProcessCleanupUnverifiedError, run_hidden

_MAX_INVENTORY = 4 * 1024 * 1024


class ModelPreparationError(RuntimeError):
    """The model's installed state could not be established."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _local_json(origin: str, endpoint: str) -> object:
    _upstream_port(origin)
    request = urllib.request.Request(origin.rstrip("/") + endpoint, method="GET")
    try:
        deadline = time.monotonic() + 10
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=5) as response:
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("inventory deadline exceeded")
                chunk = response.read1(min(65536, _MAX_INVENTORY + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > _MAX_INVENTORY:
                    raise ValueError("inventory exceeds size limit")
        if len(data) > _MAX_INVENTORY:
            raise ValueError("inventory exceeds size limit")
        return json.loads(data)
    except (OSError, ValueError, UnicodeError) as exc:
        raise ModelPreparationError("local Ollama inventory unavailable or invalid") from exc


def _local_models(origin: str, endpoint: str) -> set[str]:
    payload = _local_json(origin, endpoint)
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"] for row in rows):
        raise ModelPreparationError("local Ollama inventory unavailable or invalid")
    return {row["name"] for row in rows}


def require_local_source_version(origin: str) -> None:
    """Admit only the Ollama release whose :local path has been inspected."""
    payload = _local_json(origin, "/api/version")
    if not isinstance(payload, dict) or payload.get("version") != "0.34.0":
        raise ModelPreparationError("Ollama version is not verified for local-source enforcement")


def local_inventory(origin: str) -> set[str]:
    return _local_models(origin, "/api/tags")


def local_loaded_models(origin: str) -> set[str]:
    return _local_models(origin, "/api/ps")


def canonical_model(model: str) -> str:
    return model if ":" in model.rsplit("/", 1)[-1] else model + ":latest"


def local_pull(executable: str, origin: str, model: str, *, timeout: int = 1800) -> None:
    _upstream_port(origin)
    validate_local_model_name(model)
    env = dict(os.environ)
    env["OLLAMA_HOST"] = origin
    run_hidden([executable, "pull", model], env=env, check=True, timeout=timeout,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_model(model: str, *, inventory: Callable[[], set[str]], pull: Callable[[str], None], allow_pull: bool = True) -> dict:
    validate_local_model_name(model)
    expected = canonical_model(model)
    if model in (installed := inventory()) or expected in installed:
        return {"model": model, "installed": True, "downloaded": False, "runtime_verified": False}
    if not allow_pull:
        raise ModelPreparationError("requested model is not installed and model pulls are disabled")
    try:
        pull(model)
    except subprocess.TimeoutExpired as exc:
        raise ModelPreparationError("model pull outcome unknown after timeout; inspect Ollama before retrying") from exc
    except ProcessCleanupUnverifiedError as exc:
        raise ModelPreparationError("model pull outcome unknown after unconfirmed process cleanup; inspect Ollama before retrying") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ModelPreparationError("model pull failed; inspect Ollama before retrying") from exc
    if model not in (installed := inventory()) and expected not in installed:
        raise ModelPreparationError("model pull returned success but installation was not confirmed by inventory")
    return {"model": model, "installed": True, "downloaded": True, "runtime_verified": False}
