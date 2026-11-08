"""Owned lifecycle for the experimental local OpenCode provider bridge."""
from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
import threading
from typing import Any
from urllib.parse import urlsplit

from .opencode_provider_bridge import ProviderBridge
from .opencode_inference_session import InferenceSessionError
from .opencode_model_names import validate_local_model_name


def derive_provider_token(nonce: str) -> str:
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", nonce):
        raise ValueError("invalid provider nonce")
    digest = hmac.new(nonce.encode("ascii"), b"local-ai-hub-opencode-provider-v1\0" + nonce.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _upstream_port(url: str) -> int:
    if not isinstance(url, str):
        raise ValueError("Ollama URL must be a loopback HTTP origin")
    try:
        endpoint = urlsplit(url)
        port = endpoint.port
    except ValueError as exc:
        raise ValueError("Ollama URL must be a loopback HTTP origin") from exc
    if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or port is None
            or not 1 <= port <= 65535 or endpoint.netloc != f"127.0.0.1:{port}"
            or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
        raise ValueError("Ollama URL must be a loopback HTTP origin")
    return port


class ProviderService:
    def __init__(self, scheduler: Any, *, upstream_url: str, peer_verifier: Any = None) -> None:
        self._scheduler = scheduler
        self._upstream_url = upstream_url
        self._peer_verifier = peer_verifier
        self._lock = threading.Lock()
        self._server: ProviderBridge | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._stopping = False
        self._stop_error: str | None = None
        self._stopped = threading.Event()
        self._stopped.set()
        self._nonce = ""

    def start(self, model: str) -> dict[str, Any]:
        with self._lock:
            if self._closed or self._stopping or self._server is not None:
                raise RuntimeError("provider service is unavailable or already started")
            try:
                validate_local_model_name(model)
            except ValueError as exc:
                raise InferenceSessionError(str(exc)) from exc
            port = _upstream_port(self._upstream_url)
            nonce = secrets.token_urlsafe(24)
            token = derive_provider_token(nonce)
            from .opencode_models import require_local_source_version
            require_local_source_version(self._upstream_url)
            server = ProviderBridge(self._scheduler, model, token=token, upstream_port=port, peer_verifier=self._peer_verifier)
            try:
                from .opencode_models import canonical_model, ensure_model, local_inventory, local_loaded_models
                ensure_model(model, inventory=lambda: local_inventory(self._upstream_url),
                             pull=lambda _: None, allow_pull=False)
                if any(canonical_model(name) != canonical_model(model) for name in local_loaded_models(self._upstream_url)):
                    raise RuntimeError("another model is already resident in Ollama")
                thread = threading.Thread(target=server.serve_forever, name="opencode-provider", daemon=True)
                thread.start()
            except BaseException:
                try:
                    server.server_close()
                finally:
                    server.session.close()
                raise
            self._server, self._thread = server, thread
            self._nonce = nonce
            self._stop_error = None
            return {"success": True, "host": "127.0.0.1", "port": server.server_port, "model": model, "nonce": nonce}

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._stopping:
                return {"success": True, "state": "stopping"}
            if self._stop_error is not None:
                return {"success": False, "state": "blocked", "error": "provider shutdown did not confirm safe GPU release"}
            if self._server is None:
                return {"success": True, "state": "stopped"}
            return {"success": True, "state": "running", "host": "127.0.0.1", "port": self._server.server_port,
                    "model": self._server.model, "nonce": self._nonce}

    def _stop_worker(self, server: ProviderBridge, thread: threading.Thread | None, done: threading.Event) -> None:
        error = None
        try:
            server.shutdown()
            server.server_close()
            if thread is not None:
                thread.join(timeout=2)
                if thread.is_alive():
                    raise TimeoutError("provider server did not stop")
            # Unknown or active inference raises and leaves the durable fence.
            server.session.close()
        except BaseException as exc:
            error = type(exc).__name__
        with self._lock:
            self._stop_error = error
            self._stopping = False
            if error is None:
                self._server = self._thread = None
                self._nonce = ""
            done.set()

    def request_stop(self, *, expected_nonce: str | None = None) -> threading.Event:
        with self._lock:
            if expected_nonce is not None:
                if (not isinstance(expected_nonce, str) or not expected_nonce.isascii() or not self._nonce
                        or not secrets.compare_digest(expected_nonce, self._nonce)):
                    raise ValueError("provider session does not match")
            if self._server is None or self._stopping or self._stop_error is not None:
                return self._stopped
            self._stopping = True
            self._stopped = threading.Event()
            worker = threading.Thread(target=self._stop_worker, args=(self._server, self._thread, self._stopped), name="opencode-provider-stop", daemon=True)
            try:
                worker.start()
            except BaseException:
                self._stopping = False
                self._stop_error = "ThreadStartError"
                self._stopped.set()
                raise
            return self._stopped

    def stop(self) -> None:
        self.request_stop().wait()
        with self._lock:
            if self._stop_error is not None:
                raise RuntimeError("provider shutdown did not confirm safe GPU release")

    def wait(self, timeout_seconds: float) -> dict[str, Any]:
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= 30):
            raise ValueError("timeout_seconds must be between 0 and 30")
        with self._lock:
            done = self._stopped
        done.wait(timeout_seconds)
        return self.status()

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.stop()
