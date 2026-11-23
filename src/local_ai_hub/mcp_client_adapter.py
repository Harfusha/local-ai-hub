from __future__ import annotations

from typing import Any, Callable

from local_ai_hub.client import HubClient


class _MCPHubClientPostProxy:
    """Expose HubClient state while routing its post calls through the adapter."""

    def __init__(self, client: HubClient, post: Callable[..., Any]) -> None:
        self._client = client
        self._post = post

    def post(self, *args: Any, **kwargs: Any) -> Any:
        return self._post(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

class _MCPHubClientAdapter:
    """Pass MCP action policy metadata through HubClient without changing wire payloads."""

    def __init__(self, client: HubClient) -> None:
        from . import mcp_server as services_module
        self._client = client
        try:
            parameters = services_module.inspect.signature(client.request).parameters
        except (AttributeError, TypeError, ValueError):
            parameters = {}
        self._supports_operational_metadata = {
            "operational_action", "requires_heavy_work"
        } <= set(parameters)
        if self._supports_operational_metadata:
            original_request = client.request

            def request_with_policy(
                path: str, payload: dict[str, Any] | None = None, **kwargs: Any
            ) -> Any:
                action, requires_heavy_work = services_module._CURRENT_OPERATIONAL_CONTEXT.get()
                kwargs.setdefault("operational_action", action or None)
                kwargs.setdefault("requires_heavy_work", requires_heavy_work)
                return original_request(path, payload, **kwargs)

            # HubClient.post() calls self.request(), so metadata reaches in-process
            # transport without bypassing post's replay-safety and payload handling.
            client.request = request_with_policy  # type: ignore[method-assign]

    def get(self, path: str, **kwargs: Any) -> Any:
        from . import mcp_server as services_module
        cancel_event = services_module.CURRENT_REQUEST_CANCEL_EVENT.get()
        if cancel_event is not None:
            kwargs.setdefault("cancel_event", cancel_event)
        if getattr(self._client, "auto_start", False):
            request_timeout = min(
                max(0.2, float(kwargs.get("timeout", 15.0))),
                max(0.2, float(getattr(self._client, "max_request_timeout", 15.0))),
            )
            startup_wait = float(getattr(self._client, "startup_wait", request_timeout))
            request_budget = max(0.2, request_timeout + max(0.0, startup_wait) - 1.0)
            deadline = services_module.time.monotonic() + request_budget
            self.ensure_server(timeout=min(request_budget, startup_wait))
            kwargs["timeout"] = min(request_timeout, max(0.2, deadline - services_module.time.monotonic()))
            # Do not repeat the startup wait inside HubClient.get when the
            # preflight timed out. The preflight owns the startup budget; the
            # remaining request budget is reserved for the bounded HTTP probe.
            kwargs["startup_preflight_complete"] = True
        if self._supports_operational_metadata:
            action, requires_heavy_work = services_module._CURRENT_OPERATIONAL_CONTEXT.get()
            kwargs.setdefault("operational_action", action or None)
            kwargs.setdefault("requires_heavy_work", requires_heavy_work)
        try:
            parameters = services_module.inspect.signature(self._client.get).parameters
            has_var_keyword = any(p.kind == services_module.inspect.Parameter.VAR_KEYWORD for p in parameters.values())
            if not has_var_keyword:
                kwargs = {k: v for k, v in kwargs.items() if k in parameters}
        except (AttributeError, TypeError, ValueError):
            pass
        return self._client.get(path, **kwargs)

    def post(self, *args: Any, **kwargs: Any) -> Any:
        return self._client.post(*args, **kwargs)

    def coord(self, action: str, **kwargs: Any) -> dict[str, Any]:
        from . import mcp_server as services_module
        proxy = services_module._MCPHubClientPostProxy(self._client, self.post)
        return type(self._client).coord(proxy, action, **kwargs)

    def ensure_server(self, *args: Any, **kwargs: Any) -> Any:
        return self._client.ensure_server(*args, **kwargs)

    def status(
        self, detail: str = "brief", scope: str = "process", *,
        min_duration_ms: int = 0, trace_action: str = "",
    ) -> Any:
        if detail == "agent_state":
            return self.get("/api/status?detail=agent_state")
        if detail == "traces":
            return self._client.status(
                detail, scope, min_duration_ms=min_duration_ms, trace_action=trace_action,
            )
        return self.get(f"/api/live/status?light=1&scope={scope}&detail={detail}")

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_client", "_supports_operational_metadata"}:
            super().__setattr__(name, value)
        elif callable(getattr(type(self), name, None)):
            # Keep adapter method overrides on the adapter. Test monkeypatches
            # and instrumentation must not replace HubClient.get with this
            # bound proxy method, which would recurse through __getattr__.
            super().__setattr__(name, value)
        elif hasattr(self, "_client") and self._client is not None:
            setattr(self._client, name, value)
        else:
            super().__setattr__(name, value)
