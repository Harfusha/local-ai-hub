from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Iterator, Mapping, Sequence

_request_id: ContextVar[str] = ContextVar("local_ai_request_id", default="")
_trace_id: ContextVar[str] = ContextVar("local_ai_trace_id", default="")
_agent: ContextVar[str] = ContextVar("local_ai_agent", default="")
_tenant: ContextVar[str] = ContextVar("local_ai_tenant", default="")
_observer: ContextVar[Any | None] = ContextVar("local_ai_debug_observer", default=None)
_efficiency_metadata: ContextVar[dict[str, Any] | None] = ContextVar("local_ai_token_efficiency", default=None)


def set_context(
    *,
    request_id: str | None = "",
    trace_id: str | None = "",
    agent: str | None = "",
    tenant: str | None = "",
) -> tuple[Token, Token, Token, Token]:
    request = str(request_id or "") if request_id is not None else ""
    trace = (str(trace_id or "") if trace_id is not None else "") or request
    agent_id = str(agent or "") if agent is not None else ""
    tenant_id = str(tenant or "") if tenant is not None else ""
    return (_request_id.set(request), _trace_id.set(trace), _agent.set(agent_id), _tenant.set(tenant_id))


def reset_context(tokens: tuple[Token, Token, Token, Token] | Sequence[Token] | Token | None) -> None:
    if tokens is None:
        return
    variables = (_request_id, _trace_id, _agent, _tenant)
    if isinstance(tokens, Token):
        for variable in variables:
            try:
                variable.reset(tokens)
                return
            except ValueError:
                continue
        return
    for variable, token in zip(variables, tokens):
        if isinstance(token, Token):
            try:
                variable.reset(token)
            except ValueError:
                pass


@contextmanager
def scoped_context(
    *, request_id: str | None = "", trace_id: str | None = "", agent: str | None = "", tenant: str | None = ""
) -> Iterator[dict[str, Any]]:
    tokens = set_context(request_id=request_id, trace_id=trace_id, agent=agent, tenant=tenant)
    try:
        yield current()
    finally:
        reset_context(tokens)


def set_observer(value: Any | None) -> Token:
    return _observer.set(value)


def reset_observer(token: Token) -> None:
    if not isinstance(token, Token):
        return
    try:
        _observer.reset(token)
    except ValueError:
        pass


@contextmanager
def scoped_observer(value: Any | None) -> Iterator[Any | None]:
    token = set_observer(value)
    try:
        yield value
    finally:
        reset_observer(token)


def observer() -> Any | None:
    return _observer.get()


def set_metadata(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Token:
    """Set payload-free token metadata for the current request context."""
    from .token_accounting import token_efficiency_metadata

    value = dict(metadata or {})
    value.update(fields)
    return _efficiency_metadata.set(token_efficiency_metadata(value))


def reset_metadata(token: Token) -> None:
    if not isinstance(token, Token):
        return
    try:
        _efficiency_metadata.reset(token)
    except ValueError:
        pass


@contextmanager
def scoped_metadata(metadata: Mapping[str, Any] | None = None, **fields: Any) -> Iterator[dict[str, Any]]:
    token = set_metadata(metadata, **fields)
    try:
        yield efficiency_metadata()
    finally:
        reset_metadata(token)


def efficiency_metadata() -> dict[str, Any]:
    metadata = _efficiency_metadata.get()
    return dict(metadata) if metadata is not None else {}


def current() -> dict[str, Any]:
    value = {"request_id": _request_id.get(), "trace_id": _trace_id.get(), "agent": _agent.get(), "tenant": _tenant.get()}
    metadata = efficiency_metadata()
    if metadata:
        value["token_efficiency"] = metadata
    return value
