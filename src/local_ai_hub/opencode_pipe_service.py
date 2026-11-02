"""Experimental owner for the authenticated AppContainer pipe relay.

This is not an isolation boundary or a production launcher by itself.
"""
from __future__ import annotations

import socket
import threading

from .opencode_pipe_bridge import BridgeError, relay_connection
from .opencode_winpipe import WindowsPipeListener


class PipeService:
    """Keep an exclusive pipe name while relaying sequential clients to one port."""

    def __init__(self, sid: str, secret: bytes, router_port: int):
        if not isinstance(secret, bytes) or len(secret) != 32:
            raise ValueError("bridge secret must contain 32 bytes")
        if type(router_port) is not int or not 1 <= router_port <= 65535:
            raise ValueError("valid loopback router port required")
        self._listener = WindowsPipeListener(sid)
        self.name = self._listener.name
        self._secret, self._port = secret, router_port
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active = None
        self._failure = None
        self._thread = None

    def __enter__(self):
        if self._thread is not None:
            raise RuntimeError("relay service cannot be restarted")
        self._listener.__enter__()
        self._thread = threading.Thread(target=self._serve, name="opencode-pipe-relay", daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self._listener.__exit__(None, None, None)
            raise
        return self

    def _serve(self):
        try:
            while not self._stop.is_set():
                try:
                    pipe = self._listener.accept(timeout=0.5, stop=self._stop)
                except TimeoutError:
                    continue
                except InterruptedError:
                    if self._stop.is_set():
                        break
                    raise
                with self._lock:
                    self._active = pipe
                    stopping = self._stop.is_set()
                try:
                    if not stopping:
                        try:
                            relay_connection(pipe, self._secret,
                                             lambda: socket.create_connection(("127.0.0.1", self._port), timeout=5),
                                             timeout=120)
                        except (BridgeError, OSError):
                            pass  # A rejected or disconnected peer does not stop the service.
                finally:
                    with self._lock:
                        pipe.close()
                        self._active = None
        except BaseException as exc:
            self._failure = exc
        finally:
            try:
                self._listener.__exit__(None, None, None)
            except BaseException as exc:
                if self._failure is None:
                    self._failure = exc

    def check_health(self):
        if self._failure is not None:
            raise RuntimeError("relay service failed") from self._failure
        if self._thread is None or not self._thread.is_alive() or self._stop.is_set():
            raise RuntimeError("relay service is not running")

    def close(self):
        if self._thread is None:
            raise RuntimeError("relay service was not started")
        self._stop.set()
        with self._lock:
            if self._active is not None:
                self._active.close()
        self._thread.join(timeout=7)
        if self._thread.is_alive():
            raise RuntimeError("relay service shutdown was not confirmed")
        if self._failure is not None:
            raise RuntimeError("relay service failed") from self._failure

    def __exit__(self, *_args):
        self.close()
