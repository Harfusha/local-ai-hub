from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import mcp_stdio_catalog_support as support


def _transport(monkeypatch, *, exit_code=0, list_error=False):
    calls = []
    child = SimpleNamespace(returncode=None)

    async def spawn(*_args, **_kwargs):
        calls.append("spawn")
        return child

    @asynccontextmanager
    async def client(_params, *, errlog):
        await support.stdio._create_platform_compatible_process()
        try:
            yield object(), object()
        finally:
            calls.append("eof")
            child.returncode = exit_code

    class Session:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def send_request(self, request, _result_type):
            calls.append("initialize")
            assert request.root.params.protocolVersion == "2025-06-18"
            return SimpleNamespace(model_dump=lambda **_kwargs: {"protocolVersion": "2025-06-18"})

        async def send_notification(self, notification):
            assert notification.root.method == "notifications/initialized"
            calls.append("initialized")

        async def list_tools(self):
            calls.append("tools/list")
            if list_error:
                raise RuntimeError("catalog unavailable")
            return SimpleNamespace(model_dump=lambda **_kwargs: {"tools": []})

    monkeypatch.setattr(support.stdio, "_create_platform_compatible_process", spawn)
    monkeypatch.setattr(support, "stdio_client", client)
    monkeypatch.setattr(support, "ClientSession", Session)
    return calls


def _catalog(tmp_path):
    return support.stdio_catalog(
        ["unused-python"], cwd=tmp_path, env={},
        initialize_params={
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "fixture", "version": "1"},
        },
    )


def test_catalog_observes_responses_before_closing_stdin(tmp_path, monkeypatch):
    calls = _transport(monkeypatch)
    assert _catalog(tmp_path) == ({"protocolVersion": "2025-06-18"}, {"tools": []})
    assert calls == ["spawn", "initialize", "initialized", "tools/list", "eof"]


def test_catalog_retains_successful_process_exit_requirement(tmp_path, monkeypatch):
    _transport(monkeypatch, exit_code=1)
    with pytest.raises(AssertionError):
        _catalog(tmp_path)


def test_catalog_failure_still_closes_transport(tmp_path, monkeypatch):
    calls = _transport(monkeypatch, list_error=True)
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        _catalog(tmp_path)
    assert calls[-1] == "eof"
