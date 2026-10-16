from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
import math
from typing import Any, Iterator, Mapping

_request_id: ContextVar[str] = ContextVar("local_ai_request_id", default="")
_trace_id: ContextVar[str] = ContextVar("local_ai_trace_id", default="")
_agent: ContextVar[str] = ContextVar("local_ai_agent", default="")
_tenant: ContextVar[str] = ContextVar("local_ai_tenant", default="")
_observer: ContextVar[Any | None] = ContextVar("local_ai_debug_observer", default=None)
_efficiency_metadata: ContextVar[dict[str, Any]] = ContextVar("local_ai_token_efficiency", default={})


def _sanitize_ident(val: Any, limit: int = 256) -> str:
    if val is None:
        return ""
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or (isinstance(limit, float) and not math.isfinite(limit)):
        lim = 256
    else:
        lim = int(limit)
    if lim < 0:
        return ""
    text = str(val) if not isinstance(val, str) else val
    clean = "".join(ch for ch in text if ch >= " " and ch != "\x7f").strip()
    return clean[:lim]


def set_context(*, request_id: Any = "", trace_id: Any = "", agent: Any = "", tenant: Any = "") -> tuple[Token, Token, Token, Token]:
    req = _sanitize_ident(request_id)
    tr = _sanitize_ident(trace_id or req)
    ag = _sanitize_ident(agent)
    ten = _sanitize_ident(tenant)
    return (_request_id.set(req), _trace_id.set(tr), _agent.set(ag), _tenant.set(ten))


def reset_context(tokens: Any) -> None:
    if not isinstance(tokens, (tuple, list)):
        return
    for var, token in zip((_request_id, _trace_id, _agent, _tenant), tokens):
        if isinstance(token, Token):
            try:
                var.reset(token)
            except (ValueError, RuntimeError):
                pass


@contextmanager
def trace_scope(*, request_id: Any = "", trace_id: Any = "", agent: Any = "", tenant: Any = "") -> Iterator[dict[str, Any]]:
    tokens = set_context(request_id=request_id, trace_id=trace_id, agent=agent, tenant=tenant)
    try:
        yield current()
    finally:
        reset_context(tokens)


def set_observer(value: Any | None) -> Token:
    return _observer.set(value)


def reset_observer(token: Any) -> None:
    if isinstance(token, Token):
        try:
            _observer.reset(token)
        except (ValueError, RuntimeError):
            pass


def observer() -> Any | None:
    return _observer.get()


@contextmanager
def observer_scope(value: Any | None) -> Iterator[Any | None]:
    token = set_observer(value)
    try:
        yield value
    finally:
        reset_observer(token)


def set_metadata(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Token:
    """Set payload-free token metadata for the current request context."""
    from .token_accounting import token_efficiency_metadata

    value = dict(metadata) if isinstance(metadata, Mapping) else {}
    value.update(fields)
    return _efficiency_metadata.set(token_efficiency_metadata(value))


def reset_metadata(token: Any) -> None:
    if isinstance(token, Token):
        try:
            _efficiency_metadata.reset(token)
        except (ValueError, RuntimeError):
            pass


def efficiency_metadata() -> dict[str, Any]:
    return dict(_efficiency_metadata.get())


# Descriptive aliases keep integrations free to choose either terminology.
set_efficiency_metadata = set_metadata
reset_efficiency_metadata = reset_metadata


@contextmanager
def metadata_scope(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Iterator[dict[str, Any]]:
    token = set_metadata(metadata, **fields)
    try:
        yield efficiency_metadata()
    finally:
        reset_metadata(token)


def clear_context() -> None:
    _request_id.set("")
    _trace_id.set("")
    _agent.set("")
    _tenant.set("")
    _observer.set(None)
    _efficiency_metadata.set({})


def has_context() -> bool:
    return bool(_request_id.get() or _trace_id.get())


def is_trace_active() -> bool:
    return bool(_trace_id.get())


def current_request_id() -> str:
    return _request_id.get()


def current_trace_id() -> str:
    return _trace_id.get()


def current_agent() -> str:
    return _agent.get()


def current_tenant() -> str:
    return _tenant.get()


def current() -> dict[str, Any]:
    value = {"request_id": _request_id.get(), "trace_id": _trace_id.get(), "agent": _agent.get(), "tenant": _tenant.get()}
    metadata = efficiency_metadata()
    if metadata:
        value["token_efficiency"] = metadata
    return value

