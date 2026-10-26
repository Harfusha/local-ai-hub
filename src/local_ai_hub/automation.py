"""Owned UI sessions. Browser contexts are not host/network security sandboxes."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

AUTOMATION_REQUEST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["op"],
    "properties": {
        "op": {"type": "string", "enum": ["open", "act", "status", "close"]},
        "mode": {"type": "string", "enum": ["isolated", "extension", "desktop", "desktop_sandbox"]},
        **{name: {"type": "string", "maxLength": 12000} for name in
           ("url", "session_id", "session_key", "request_id", "command", "selector", "text", "key", "option", "destination", "application")},
        **{name: {"type": "boolean"} for name in ("checked", "accept")},
        **{name: {"type": "number", "minimum": -10000, "maximum": 10000} for name in ("x", "y")},
        "window_id": {"type": "integer", "minimum": 1, "maximum": (1 << 63) - 1},
        "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 120},
        "files": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "maxLength": 4096}},
    },
}


def error(code: str, message: str, status: int = 400, **fields: Any) -> dict[str, Any]:
    return {"success": False, "error_code": code, "error": message, "status_code": status,
            "terminal": True, "retryable": False, **fields}


def _url(value: str, *, rule: bool = False) -> tuple[str, str, int, str]:
    if (not isinstance(value, str) or not value or len(value) > 4096 or value != value.strip()
            or any(ord(c) < 33 for c in value) or "\\" in value or "*" in value):
        raise ValueError("URL must be an explicit canonical HTTP(S) target")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or (rule and (parsed.query or parsed.fragment))):
        raise ValueError("target must be an HTTP(S) origin and optional path, without credentials or wildcards")
    host = parsed.hostname
    if not host.isascii() or host.endswith(".") or "%" in host:
        raise ValueError("target hostname must be canonical ASCII")
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("invalid target port")
    path = parsed.path or "/"
    decoded = unquote(path, errors="strict")
    if ("%" in decoded or "\\" in decoded or "//" in decoded or
            any(part in {".", ".."} for part in decoded.split("/")) or
            any(ord(c) < 32 for c in decoded) or decoded.count("/") != path.count("/")):
        raise ValueError("ambiguous target path")
    return parsed.scheme, host.lower(), port, decoded


class TargetPolicy:
    def __init__(self, rules: list[str]):
        if not isinstance(rules, list) or len(rules) > 256:
            raise ValueError("allowed_targets must be a bounded list")
        self.rules = tuple(_url(rule, rule=True) for rule in rules)

    def allows(self, value: str) -> bool:
        try:
            scheme, host, port, path = _url(value)
        except (TypeError, ValueError, UnicodeError):
            return False
        return any((scheme, host, port) == entry[:3] and
                   (entry[3] == "/" or path == entry[3].rstrip("/") or path.startswith(entry[3].rstrip("/") + "/"))
                   for entry in self.rules)


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ValueError("automation must be an object")
    allowed = {"enabled", "allowed_targets", "max_sessions", "session_ttl_seconds", "timeout_seconds",
               "max_output_chars", "max_binary_bytes", "playwright_command", "winapp_executable",
               "allowed_applications", "allowed_sandbox_applications", "sandbox_enabled", "allowed_file_roots", "profile_directory", "allow_physical_input"}
    if set(config) - allowed:
        raise ValueError("unknown automation configuration field")
    for name in ("enabled", "allow_physical_input", "sandbox_enabled"):
        if name in config and type(config[name]) is not bool:
            raise ValueError(f"automation.{name} must be boolean")
    TargetPolicy(config.get("allowed_targets", []))
    for name, default, low, high in (("max_sessions", 8, 1, 1024), ("session_ttl_seconds", 900, 1, 3600),
                                    ("timeout_seconds", 20, 1, 120), ("max_output_chars", 12000, 256, 65536),
                                    ("max_binary_bytes", 8388608, 1024, 33554432)):
        value = config.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"automation.{name} must be an integer in {low}..{high}")
    command = config.get("playwright_command", [])
    if not isinstance(command, list) or len(command) > 16 or any(not isinstance(v, str) or not v or "\0" in v for v in command):
        raise ValueError("automation.playwright_command must be an explicit argument vector")
    if command and (not Path(command[0]).is_absolute() or Path(command[0]).suffix.lower() in {".cmd", ".bat", ".ps1"}):
        raise ValueError("automation.playwright_command requires an absolute native executable, never a shell script")
    for name in ("winapp_executable", "profile_directory"):
        if name in config and not isinstance(config[name], str):
            raise ValueError(f"automation.{name} must be a string")
    executable = config.get("winapp_executable", "")
    if executable and (not Path(executable).is_absolute() or Path(executable).suffix.lower() != ".exe"):
        raise ValueError("automation.winapp_executable requires an absolute .exe path")
    apps = config.get("allowed_applications", {})
    if not isinstance(apps, dict) or len(apps) > 128 or any(not isinstance(k, str) or not k or
            not isinstance(v, str) or not Path(v).is_absolute() for k, v in apps.items()):
        raise ValueError("automation.allowed_applications must map names to absolute executable paths")
    guest_apps = config.get("allowed_sandbox_applications", {})
    if not isinstance(guest_apps, dict) or len(guest_apps) > 128 or any(not isinstance(k, str) or not k or
            not isinstance(v, str) or not PureWindowsPath(v).is_absolute() for k, v in guest_apps.items()):
        raise ValueError("automation.allowed_sandbox_applications must map names to absolute guest executable paths")
    roots = config.get("allowed_file_roots", [])
    if not isinstance(roots, list) or len(roots) > 32 or any(not isinstance(v, str) or not Path(v).is_absolute() for v in roots):
        raise ValueError("automation.allowed_file_roots must contain absolute paths")


@dataclass
class _Session:
    owner: tuple[str, str]
    key: str
    mode: str
    backend: Any
    expires: float
    lock: Any = field(default_factory=threading.Lock)
    journal: Any = field(default_factory=OrderedDict)
    fenced: bool = False
    close_requested: bool = False
    window_id: int = 0


class AutomationBroker:
    """Bounded active capacity; no fixed count of agents and no implicit retries."""
    def __init__(self, config: dict[str, Any], *, backend_factory: Callable, clock=time.monotonic):
        validate_config(config)
        self.config = dict(config)
        self.policy = TargetPolicy(config.get("allowed_targets", []))
        self.factory = backend_factory
        self.clock = clock
        self.sessions: dict[str, _Session] = {}
        self.lock = threading.RLock()
        self.desktop_lock = threading.Lock()
        self.closed = False
        self._stop = threading.Event()
        self._reaper = None

    def _drop(self, identity: str, session: _Session) -> None:
        session.fenced = True
        session.backend.close()
        self.sessions.pop(identity, None)

    def _reap_loop(self):
        while not self._stop.wait(min(30, self.config.get("session_ttl_seconds", 900))):
            try:
                self.reap()
            except Exception:
                # Retain the fenced session and its capacity if cleanup failed.
                continue

    def reap(self) -> None:
        with self.lock:
            for identity, session in list(self.sessions.items()):
                if session.expires <= self.clock() and session.lock.acquire(blocking=False):
                    try:
                        self._drop(identity, session)
                    finally:
                        session.lock.release()

    def execute(self, *, root: str, task_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not self.config.get("enabled", False) or self.closed:
            return error("automation_disabled", "automation is disabled", 403)
        try:
            if not isinstance(root, str) or not Path(root).is_absolute() or not Path(root).is_dir():
                raise ValueError("explicit existing absolute root required")
            if not isinstance(task_id, str) or not task_id.strip() or task_id != task_id.strip() or len(task_id) > 256:
                raise ValueError("explicit task_id required")
            if not isinstance(request, dict):
                raise ValueError("automation request must be an object")
            allowed = {"op", "mode", "url", "session_id", "session_key", "request_id", "command", "selector",
                       "text", "key", "option", "checked", "destination", "x", "y", "accept", "files",
                       "window_id", "application", "timeout_seconds"}
            if set(request) - allowed:
                raise ValueError("unknown automation request field")
            timeout = request.get("timeout_seconds", self.config.get("timeout_seconds", 20))
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= self.config.get("timeout_seconds", 20):
                raise ValueError("timeout_seconds exceeds configured deadline or is invalid")
            owner = str(Path(root).resolve(strict=True)), task_id
            self.reap()
            if request.get("op") == "open":
                return self._open(owner, request)
            if request.get("op") not in {"act", "close", "status"}:
                raise ValueError("op must be open, act, status or close")
            with self.lock:
                session = self.sessions.get(request.get("session_id", ""))
                key = request.get("session_key")
                if session is None or session.owner != owner or not isinstance(key, str) or not hmac.compare_digest(session.key, key):
                    return error("session_not_owned", "session is unavailable or not owned by this task", 403)
                if not session.lock.acquire(blocking=False):
                    if request["op"] == "close":
                        session.fenced = True
                        session.close_requested = True
                        cancel = getattr(session.backend, "cancel", None)
                        if callable(cancel):
                            cancel()
                        return error("session_cancelling", "in-flight operation fenced; cleanup follows cancellation", 409,
                                     cancel_requested=True, outcome_unknown=True)
                    return error("session_busy", "session already has an executing operation", 409)
            try:
                if request["op"] == "close":
                    with self.lock:
                        self._drop(request["session_id"], session)
                    return {"success": True, "automation": {"closed": True}}
                if request["op"] == "status":
                    return {"success": True, "automation": {"session_id": request["session_id"], "mode": session.mode,
                            "fenced": session.fenced, "expires_in_seconds": max(0, session.expires - self.clock())}}
                if session.fenced:
                    return error("session_fenced", "uncertain operation fenced this session; close it", 409)
                return self._act(session, request, timeout)
            finally:
                try:
                    if self.closed or session.close_requested:
                        with self.lock:
                            self._drop(request["session_id"], session)
                finally:
                    session.lock.release()
        except (ValueError, TypeError, OSError) as exc:
            return error("invalid_automation_request", str(exc)[:300])

    def _open(self, owner, request):
        if set(request) - {"op", "mode", "url", "window_id", "application", "timeout_seconds"}:
            raise ValueError("open accepts only mode, URL/window target and timeout")
        mode = request.get("mode")
        if mode not in {"isolated", "extension", "desktop", "desktop_sandbox"}:
            raise ValueError("unsupported automation mode")
        if mode in {"desktop", "desktop_sandbox"} and (
                type(request.get("window_id")) is not int or not 0 < request["window_id"] < 1 << 63 or
                not isinstance(request.get("application"), str) or not request["application"]):
            raise ValueError("desktop sessions require an explicit application and window_id")
        if mode in {"isolated", "extension"} and not self.policy.allows(request.get("url", "")):
            return error("target_denied", "browser target is not allowed", 403)
        with self.lock:
            if len(self.sessions) >= self.config.get("max_sessions", 8):
                return error("automation_capacity", "active session capacity reached; close or expire a session", 429)
            if mode == "extension" and any(s.mode == mode for s in self.sessions.values()):
                return error("profile_busy", "personal browser profile is already leased", 409)
            if mode in {"desktop", "desktop_sandbox"} and any(s.mode == mode and s.window_id == request["window_id"] for s in self.sessions.values()):
                return error("window_busy", "desktop window is already leased", 409)
            try:
                backend = self.factory(mode, self.config, request, self.policy)
            except Exception as exc:
                return error("backend_unavailable", f"automation backend could not start ({type(exc).__name__}): {str(exc)[:160]}", 503)
            identity, key = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
            self.sessions[identity] = _Session(owner, key, mode, backend,
                self.clock() + self.config.get("session_ttl_seconds", 900), window_id=request.get("window_id", 0))
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._reap_loop, name="hub-automation-expiry", daemon=True)
                self._reaper.start()
            return {"success": True, "automation": {"session_id": identity, "session_key": key, "mode": mode,
                    "expires_in_seconds": self.config.get("session_ttl_seconds", 900),
                    "isolation": "browser_context" if mode == "isolated" else mode,
                    "network_egress_isolated": False}}

    def _act(self, session, request, timeout):
        identity = request.get("request_id")
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 128:
            raise ValueError("act requires a non-empty request_id of at most 128 characters")
        command = request.get("command")
        if command not in {"navigate", "snapshot", "click", "fill", "press", "select", "check", "hover", "drag",
                           "scroll", "screenshot", "dialog", "upload", "download", "new_tab", "close_tab", "tabs", "switch_tab",
                           "inspect", "invoke", "set_value", "get_value", "focus"}:
            raise ValueError("unsupported command; arbitrary code and shell are not capabilities")
        if command in {"navigate", "new_tab"} and not self.policy.allows(request.get("url", "")):
            return error("target_denied", "navigation target is not allowed", 403)
        if command == "upload":
            files = request.get("files")
            roots = [Path(p).resolve(strict=True) for p in self.config.get("allowed_file_roots", [])]
            if not isinstance(files, list) or not 1 <= len(files) <= 16 or not roots:
                raise ValueError("upload requires explicit configured file roots and 1..16 files")
            resolved_files = []
            for file in files:
                if not isinstance(file, str) or not Path(file).is_absolute():
                    raise ValueError("upload paths must be absolute")
                path = Path(file).resolve(strict=True)
                if not path.is_file() or not any(path.is_relative_to(r) for r in roots):
                    raise ValueError("upload file is outside configured roots")
                if path.stat().st_size > self.config.get("max_binary_bytes", 8388608):
                    raise ValueError("upload exceeds transfer bound")
                resolved_files.append(str(path))
            request = {**request, "files": resolved_files}
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
        ).hexdigest()
        if identity in session.journal:
            previous, result = session.journal[identity]
            return result if hmac.compare_digest(previous, fingerprint) else error("request_id_conflict", "request_id already identifies a different operation", 409)
        if len(session.journal) >= 256:
            return error("session_request_limit", "session journal is full; close and open a new session", 409)
        exclusive = session.mode in {"desktop", "desktop_sandbox"}
        if exclusive and not self.desktop_lock.acquire(blocking=False):
            return error("desktop_busy", "desktop input is owned by another operation", 409)
        try:
            try:
                result = session.backend.execute(request, timeout)
                if not isinstance(result, dict):
                    raise RuntimeError("malformed backend response")
                if result.get("url") and not self.policy.allows(result["url"]):
                    session.fenced = True
                    result = error("target_changed", "target left the allowed scope; session fenced", 403)
                elif result.get("success") is False:
                    result = error(result.get("error_code", "automation_failed"), result.get("error", "operation failed"),
                                   outcome_unknown=result.get("outcome_unknown", False))
                    if result.get("outcome_unknown"):
                        session.fenced = True
                else:
                    result = {"success": True, "automation": result}
            except Exception as exc:
                session.fenced = True
                result = error("automation_outcome_unknown", f"operation did not complete reliably ({type(exc).__name__}); do not replay", 504,
                               outcome_unknown=True)
            if session.fenced:
                session.backend.close()
            session.journal[identity] = fingerprint, result
            session.expires = self.clock() + self.config.get("session_ttl_seconds", 900)
            return result
        finally:
            if exclusive:
                self.desktop_lock.release()

    def close(self) -> None:
        self._stop.set()
        pending = False
        with self.lock:
            self.closed = True
            for identity, session in list(self.sessions.items()):
                session.fenced = True
                if session.lock.acquire(blocking=False):
                    try:
                        self._drop(identity, session)
                    finally:
                        session.lock.release()
                else:
                    pending = True
                    cancel = getattr(session.backend, "cancel", None)
                    if callable(cancel):
                        cancel()
        if self._reaper and self._reaper is not threading.current_thread():
            self._reaper.join(1)
        if pending:
            raise TimeoutError("automation operations are cancelling; cleanup is still pending")
