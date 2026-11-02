"""Fail-closed HTTP route admission for the OpenCode local client profile.

This is only one layer of the local-only design. It does not authenticate the
agent label or stop independently scheduled background work.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import hmac
import re
from typing import Any

_PROFILE = "opencode-local"
_LOCAL_GENERATION_BLOCKED: ContextVar[bool] = ContextVar("opencode_local_generation_blocked", default=False)


def derive_local_profile_token(master: str, nonce: str) -> str | None:
    """Derive a restricted credential for one provider session."""
    if (not isinstance(master, str) or not master.isascii() or not 32 <= len(master) <= 1024
            or any(character.isspace() for character in master)):
        return None
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", nonce):
        return None
    signature = hmac.new(master.encode("ascii"), b"local-ai-hub-opencode-profile-v1\0" + nonce.encode("ascii"), hashlib.sha256).hexdigest()
    return f"lahoc1.{nonce}.{signature}"


def local_profile_config(config: dict[str, Any], token: str) -> dict[str, Any]:
    """Make a client-only copy without owner or supervisor credentials."""
    if not isinstance(token, str) or (token and not re.fullmatch(r"lahoc1\.[A-Za-z0-9_-]{20,128}\.[0-9a-f]{64}", token)):
        raise ValueError("opencode-local requires a restricted profile credential")
    security = config.get("security", {})
    if not isinstance(security, dict):
        raise ValueError("invalid security configuration")
    return {**config, "security": {**security, "api_token": token, "supervisor_token": "", "action_tokens": {}}}
_READ_PATHS = frozenset({"/health", "/ready", "/api/status", "/api/mode", "/api/live/status?light=1"})
_POST_PATHS = frozenset({
    "/api/repo/code-index", "/api/repo/callers", "/api/search", "/api/rag/search",
    "/api/artifact/get", "/api/artifact/list",
    "/api/evidence/get", "/api/evidence/verify",
    "/api/leases/claim_batch", "/api/leases/release",
    "/api/agent-state/tasks", "/api/agent-state/verification", "/api/agent-state/memory",
    "/api/opencode/provider/start", "/api/opencode/provider/status", "/api/opencode/provider/stop",
    "/api/opencode/provider/wait",
})
_ACTIONS = {
    "/api/agent-state/tasks": frozenset({"create", "get", "list", "count", "checkpoint", "complete", "transition"}),
    "/api/agent-state/verification": frozenset({"completion", "receipt", "project_command"}),
    "/api/agent-state/memory": frozenset({"record", "get", "find"}),
}


@contextmanager
def generation_scope(agent: str):
    """Restrict synchronous nested work without relaxing an outer restriction."""
    token = _LOCAL_GENERATION_BLOCKED.set(_LOCAL_GENERATION_BLOCKED.get() or agent == _PROFILE)
    try:
        yield
    finally:
        _LOCAL_GENERATION_BLOCKED.reset(token)


def scoped_http_request(handler):
    @wraps(handler)
    def guarded(self, *args, **kwargs):
        with generation_scope(self._agent()):
            return handler(self, *args, **kwargs)
    return guarded


def generation_denial() -> dict[str, Any] | None:
    if not _LOCAL_GENERATION_BLOCKED.get():
        return None
    return {"success": False, "error_code": "opencode_generation_disabled", "error": "internal generation is disabled for opencode-local", "terminal": True, "retryable": False}


def path_allowed(agent: str, method: str, path: str) -> bool:
    if agent != _PROFILE:
        return True
    if method == "GET":
        return path in _READ_PATHS
    if method == "POST":
        return path in _POST_PATHS
    return False


def payload_allowed(agent: str, path: str, payload: Any) -> bool:
    if agent != _PROFILE:
        return True
    if path not in _POST_PATHS or not isinstance(payload, dict):
        return False
    actions = _ACTIONS.get(path)
    if actions is None:
        return True
    action = payload.get("action")
    return isinstance(action, str) and action in actions
