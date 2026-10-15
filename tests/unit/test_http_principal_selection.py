"""Server/client identity selection parity without changing tenant defaults."""
from types import SimpleNamespace

import pytest

from local_ai_hub import http_server
from local_ai_hub.http_identity import request_principal_tenant


@pytest.mark.parametrize(("config", "route", "expected"), [
    ({}, "/api/repo/callers", "http-default"),
    ({}, "/api/repo/impact", "http-default"),
    ({}, "/api/agent-state/tasks", "api-token-default"),
    ({"security": {"api_token": "unit-token"}}, "/api/repo/impact", "api-token-default"),
    ({"security": {"api_token_tenant": "owner", "api_token_principal": "other"}}, "/api/search", "owner"),
    ({"security": {"api_token_principal": "owner"}}, "/api/repo/callers", "owner"),
    ({"browser_bridge": {"tenant": "browser-owner"}}, "/api/browser/capture", "browser-owner"),
    ({"browser_bridge": {"tenant": "browser-owner"}}, "/api/vision/review", "browser-owner"),
])
def test_server_preserves_existing_principal_defaults(monkeypatch, config, route, expected):
    monkeypatch.setattr(http_server, "APP", SimpleNamespace(config=config))
    assert request_principal_tenant(config, route) == expected
    assert http_server.Handler._principal_tenant(SimpleNamespace(path=route)) == expected
