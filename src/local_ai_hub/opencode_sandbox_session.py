"""Experimental composition of OpenCode AppContainer transport components.

This does not grant workspace access or provide a complete interactive launcher.
"""
from __future__ import annotations

import os
import secrets
import socket
import threading
from contextlib import ExitStack
from pathlib import Path

from .opencode_appcontainer import AppContainerProfile
from .opencode_container_process import run_in_appcontainer
from .opencode_local_router import LocalRouter
from .opencode_owned_stop import OwnedJobBinding
from .opencode_pipe_service import PipeService
from .opencode_stop_service import StopService


def _select_client_port() -> int:
    """Ask the OS for an available ephemeral port; later binding can still race."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        if type(port) is not int or not 1024 <= port <= 65535:
            raise OSError("OS did not provide a usable ephemeral port")
        return port


class SandboxSession:
    """Own one profile, fixed-target router, authenticated pipes and job."""

    def __init__(self, hub_port: int, provider_port: int):
        self._hub_port, self._provider_port = hub_port, provider_port
        self._lock = threading.Lock()
        self._state = "new"
        self._used = False
        self._running = False
        self._run_cleanup_confirmed = False
        self._resources_closed = False
        self._stack = None
        self.client_port = None
        self._relay_secret = self._stop_secret = None
        self.profile = self.router = self.relay = self.control = self.binding = None

    def __enter__(self):
        with self._lock:
            if self._state != "new":
                raise RuntimeError("sandbox session cannot be reused")
            self._state = "opening"
        stack = ExitStack()
        try:
            self.profile = stack.enter_context(AppContainerProfile())
            self.router = stack.enter_context(LocalRouter(self._hub_port, self._provider_port))
            self.client_port = _select_client_port()
            self.router.register_client_port(self.client_port)
            self._relay_secret, self._stop_secret = secrets.token_bytes(32), secrets.token_bytes(32)
            self.binding = OwnedJobBinding()
            self.relay = stack.enter_context(PipeService(self.profile.sid, self._relay_secret, self.router.port))
            self.control = stack.enter_context(StopService(self.profile.sid, self._stop_secret, self.binding))
        except BaseException:
            self._state = "closed"
            try:
                stack.close()
            finally:
                self._relay_secret = self._stop_secret = None
            raise
        self._stack = stack
        self._state = "open"
        return self

    def run(self, argv, *, cwd, env, timeout, stdio=None):
        if not isinstance(env, dict) or any(not isinstance(key, str) for key in env):
            raise ValueError("invalid environment")
        names = {"LOCAL_AI_PIPE_NAME", "LOCAL_AI_PIPE_SECRET", "LOCAL_AI_STOP_PIPE", "LOCAL_AI_STOP_SECRET", "LOCAL_AI_CLIENT_PORT"}
        if any(key.upper() in names for key in env):
            raise ValueError("sandbox transport environment is reserved")
        with self._lock:
            if self._state != "open" or self._used:
                raise RuntimeError("sandbox session is not available")
            self._used = True
            self._running = True
            process_env = dict(env)
            process_env.update({"LOCAL_AI_PIPE_NAME": self.relay.name, "LOCAL_AI_PIPE_SECRET": self._relay_secret.hex(),
                                "LOCAL_AI_STOP_PIPE": self.control.name, "LOCAL_AI_STOP_SECRET": self._stop_secret.hex(),
                                "LOCAL_AI_CLIENT_PORT": str(self.client_port)})
        try:
            result = run_in_appcontainer(self.profile, argv, cwd=cwd, env=process_env, timeout=timeout, stdio=stdio,
                                         binding=self.binding, services=(self.relay, self.control))
            with self._lock:
                self._run_cleanup_confirmed = True
            return result
        finally:
            with self._lock:
                self._running = False

    @property
    def cleanup_confirmed(self):
        """Whether owned cleanup returned successfully; not a filesystem proof."""
        with self._lock:
            return self._state == "closed" and self._resources_closed and (not self._used or self._run_cleanup_confirmed)

    def build_runtime_config(self, cfg, *, install_dir, hub_python, client_config, model):
        """Return V2 config and sanitized client TOML; caller must stage both safely.

        Path checks here are not an ACL, symlink, or workspace confinement boundary.
        """
        from .generator import generate_opencode_runtime_config
        from .opencode_launcher import _client_profile_config

        if not isinstance(cfg, dict):
            raise ValueError("Hub configuration must be an object")
        try:
            root, python, config = (Path(value) for value in (install_dir, hub_python, client_config))
            if not all(value.is_absolute() for value in (root, python, config)):
                raise ValueError("absolute staged paths are required")
            root, python, config = root.resolve(), python.resolve(), config.resolve()
            relative = config.relative_to(root)
            python_relative = python.relative_to(root)
            if not relative.parts or not python_relative.parts:
                raise ValueError("client configuration must be a staged file")
        except (TypeError, OSError, RuntimeError, ValueError) as exc:
            raise ValueError("invalid staged configuration paths") from exc
        with self._lock:
            if self._state != "open" or self._used:
                raise RuntimeError("sandbox session is not available")
            port = self.client_port
        runtime = generate_opencode_runtime_config(cfg, root, python, model=model, provider_port=port, hub_port=port)
        server = runtime["mcp"]["servers"].pop("local-ai")
        server["environment"]["LOCAL_AI_CONFIG"] = str(config)
        site = python.parent / "Lib" / "site-packages"
        server["environment"]["PYTHONPATH"] = os.pathsep.join(str(path) for path in (
            root / "src", site / "win32", site / "win32" / "lib", site / "pythonwin"))
        runtime["plugins"].append({"package": str(root / "tools" / "opencode_mcp"), "options": {"server": server}})
        return runtime, _client_profile_config(cfg, port, state_dir=config.parent / "mcp-state")

    def __exit__(self, exc_type, exc, traceback):
        with self._lock:
            if self._state != "open":
                raise RuntimeError("sandbox session is not active")
            if self._running:
                raise RuntimeError("sandbox session still has a running process")
            self._state = "closed"
        try:
            result = self._stack.__exit__(exc_type, exc, traceback)
            with self._lock:
                self._resources_closed = True
            return result
        finally:
            self._relay_secret = self._stop_secret = None
