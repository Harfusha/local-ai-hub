"""Shared loopback MCP streamable HTTP application."""

from __future__ import annotations

import ipaddress
import asyncio
import json
import socket
import threading
import time

from starlette.responses import JSONResponse


class _LoopbackOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            peer = scope.get("client")
            loopback = bool(peer) and ipaddress.ip_address(peer[0]).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


class _DisconnectCancellation:
    """Translate a disconnected HTTP tool call into MCP session cancellation."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = scope.get("headers", [])
        sessions = [v for k, v in headers if k.lower() == b"mcp-session-id"]
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/mcp" or len(sessions) != 1:
            await self.app(scope, receive, send)
            return
        chunks = []
        size = 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body", b"")
            size += len(chunk)
            if size > 4 * 1024 * 1024:
                await JSONResponse({"error": "request too large"}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not event.get("more_body", False):
                break
        body = b"".join(chunks)
        try:
            message = json.loads(body)
        except (ValueError, UnicodeError):
            message = None
        request_id = message.get("id") if isinstance(message, dict) and message.get("method") == "tools/call" else None
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Future()

        task = asyncio.create_task(self.app(scope, replay, send))
        if request_id is None or isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            await task
            return
        disconnected = asyncio.create_task(receive())
        try:
            done, _ = await asyncio.wait((task, disconnected), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
                return
            if disconnected.result()["type"] != "http.disconnect":
                await task
                return
            cancel_body = json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                      "params": {"requestId": request_id, "reason": "HTTP client disconnected"}},
                                     separators=(",", ":")).encode()
            cancel_scope = dict(scope)
            cancel_scope["headers"] = [(k, v) for k, v in headers if k.lower() != b"content-length"] + [
                (b"content-length", str(len(cancel_body)).encode())]
            sent = False

            async def cancel_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": cancel_body, "more_body": False}
                await asyncio.Future()

            async def discard(_message):
                pass

            await asyncio.wait_for(self.app(cancel_scope, cancel_receive, discard), timeout=2)
        finally:
            disconnected.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, disconnected, return_exceptions=True)


def create_app(*, server=None):
    """Expose the same MCP tools without creating a server for every client."""
    if server is None:
        from .mcp_server import mcp as server

    server.settings.stateless_http = False
    server.settings.json_response = True
    app = server.streamable_http_app()
    app.add_middleware(_DisconnectCancellation)
    app.add_middleware(_LoopbackOnly)
    return app


class HTTPMCPService:
    """Own one loopback listener and its bounded server thread."""

    def __init__(self, *, port: int, server=None):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be an integer between 0 and 65535")
        self.app = create_app(server=server)
        self.port = port
        self._runner = None
        self._thread = None
        self._listener = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, timeout: float = 5.0) -> None:
        import uvicorn

        if self._thread is not None:
            raise RuntimeError("HTTP MCP service has already been started")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen(128)
            self.port = listener.getsockname()[1]
            self._listener = listener
            runner = uvicorn.Server(uvicorn.Config(self.app, log_config=None, log_level="warning", lifespan="on"))
            self._runner = runner
            thread = threading.Thread(target=runner.run, kwargs={"sockets": [listener]},
                                      name="local-ai-mcp-http", daemon=True)
            self._thread = thread
            thread.start()
            deadline = time.monotonic() + max(0.0, timeout)
            while thread.is_alive() and not runner.started and time.monotonic() < deadline:
                thread.join(timeout=min(0.02, max(0.0, deadline - time.monotonic())))
            if not runner.started:
                self.stop(timeout=timeout)
                raise RuntimeError("HTTP MCP service did not start")
        except BaseException:
            listener.close()
            raise

    def stop(self, *, timeout: float = 5.0) -> None:
        if self._runner is not None:
            self._runner.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
            if self._thread.is_alive():
                raise TimeoutError("HTTP MCP service did not stop")
        if self._listener is not None:
            self._listener.close()
