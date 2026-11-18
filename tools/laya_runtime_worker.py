"""Persistent JSON-lines worker for Laya's isolated optional environment."""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import json
import sys
from pathlib import Path
from typing import Any


MODEL_NAME = "local-ai-hub-multilingual"
MAX_LINE_BYTES = 64 * 1024
protocol_stdout = sys.stdout
# Third-party model loading may print progress. Keep stdout exclusively for the
# bounded parent/worker protocol.
sys.stdout = sys.stderr


def _reply(value: dict[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)
    protocol_stdout.write(raw + "\n")
    protocol_stdout.flush()


def _json_default(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return tolist()
    raise TypeError(f"unsupported Laya result value: {type(value).__name__}")


def _device_of(agent: Any) -> str:
    body = getattr(agent, "model", None)
    parameters = getattr(body, "parameters", None)
    if not callable(parameters):
        raise RuntimeError("Laya model does not expose parameter placement")
    try:
        parameter = next(iter(parameters()))
    except StopIteration as exc:
        raise RuntimeError("Laya model has no parameters") from exc
    device = getattr(parameter, "device", None)
    if device is None:
        raise RuntimeError("Laya model device is unavailable")
    return str(device)


def _open(payload: dict[str, Any]) -> tuple[Any, str, str]:
    checkpoint = Path(payload.get("checkpoint_path", ""))
    revision = payload.get("revision")
    hashes = payload.get("expected_sha256")
    device = payload.get("device")
    if not checkpoint.is_absolute() or checkpoint.name != revision:
        raise ValueError("checkpoint path and pinned revision do not match")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("pinned checkpoint hashes are required")
    if not isinstance(device, str) or not device:
        raise ValueError("selected Laya device is invalid")

    module = importlib.import_module("laya")
    router_type = getattr(module, "Router", None)
    if not callable(router_type):
        raise RuntimeError("installed Laya runtime does not expose Router")
    try:
        parameters = inspect.signature(router_type).parameters
    except (TypeError, ValueError) as exc:
        raise RuntimeError("cannot verify installed Laya Router API") from exc
    accepts_extra = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())

    def accepts(name: str) -> bool:
        return name in parameters or accepts_extra

    options: dict[str, Any] = {
        "models": {MODEL_NAME: str(checkpoint)},
        "device": device,
        "default": MODEL_NAME,
        "max_loaded": 1,
        "preload": False,
    }
    if accepts("sha256_digests"):
        options["sha256_digests"] = {MODEL_NAME: hashes}
    elif accepts("agent_kwargs"):
        options["agent_kwargs"] = {"expected_sha256": hashes}
    else:
        raise RuntimeError("Laya Router cannot verify pinned checkpoint hashes")
    if accepts("vega"):
        options["vega"] = False

    router = router_type(**options)
    load = getattr(router, "load", None)
    unload = getattr(router, "unload", None)
    loaded = getattr(router, "loaded", None)
    if not callable(load) or not callable(unload) or loaded is None:
        raise RuntimeError("Laya Router lacks its public load/unload API")
    if loaded:
        unload()
        if getattr(router, "loaded", None):
            raise RuntimeError("preloaded Laya model cleanup was not confirmed")
        raise RuntimeError("Laya Router unexpectedly preloaded a model")

    agent = load(MODEL_NAME)
    if agent is None or MODEL_NAME not in router.loaded:
        raise RuntimeError("Laya Router did not retain the requested checkpoint")
    actual_device = _device_of(agent)
    if actual_device != device:
        try:
            unload(MODEL_NAME)
        finally:
            if MODEL_NAME in getattr(router, "loaded", {}):
                raise RuntimeError("Laya device mismatch and unload was not confirmed")
        raise RuntimeError("Laya model loaded on a different device")
    try:
        version = importlib.metadata.version("laya")
    except importlib.metadata.PackageNotFoundError:
        version = str(getattr(module, "__version__", "unreported"))
    return router, actual_device, version


def main() -> int:
    router = None
    failed = False
    for raw in sys.stdin.buffer:
        if len(raw) > MAX_LINE_BYTES:
            _reply({"success": False, "error": "worker request exceeds the size limit"})
            failed = True
            break
        try:
            request = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            _reply({"success": False, "error": "worker request is invalid JSON"})
            failed = True
            break
        if type(request) is not dict:
            _reply({"success": False, "error": "worker request must be an object"})
            failed = True
            break
        action = request.get("action")
        try:
            if action == "load" and router is None:
                router, device, version = _open(request)
                _reply({"success": True, "loaded": True, "device": device, "version": version})
            elif action == "predict" and router is not None:
                state, questions = request.get("state"), request.get("questions")
                if type(state) is not dict or type(questions) is not dict:
                    raise ValueError("typed Laya input must be objects")
                result = router.predict(state, questions, model=MODEL_NAME)
                if type(result) is not dict:
                    raise ValueError("Laya returned an invalid result")
                encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=_json_default)
                if len(encoded.encode("utf-8")) > MAX_LINE_BYTES:
                    raise ValueError("Laya result exceeds the size limit")
                _reply({"success": True, "result": json.loads(encoded)})
            elif action == "close" and router is not None:
                router.unload(MODEL_NAME)
                loaded = getattr(router, "loaded", None)
                if loaded is None or MODEL_NAME in loaded:
                    raise RuntimeError("Laya Router unload was not confirmed")
                router = None
                _reply({"success": True, "closed": True})
                return 0
            else:
                raise ValueError("unsupported worker action")
        except Exception as exc:
            _reply({"success": False, "error": f"{type(exc).__name__}: {str(exc)[:384]}"})
            failed = True
            break

    if router is not None:
        try:
            router.unload(MODEL_NAME)
            if MODEL_NAME in getattr(router, "loaded", {}):
                failed = True
        except Exception:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
