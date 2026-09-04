from __future__ import annotations

from local_ai_hub.services import LocalAIServices
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Deterministic:
    def context_pack(self, root, query, *, max_chars, max_raw_evidence):
        return {"success": True, "root": root, "query": query, "context": "fast facts", "evidence": [], "estimated_tokens": 2}


def test_fast_context_returns_explicit_full_continuation():
    services = LocalAIServices.__new__(LocalAIServices)
    services.deterministic = _Deterministic()
    services.config = {"deterministic": {"context_max_chars": 5200, "context_raw_evidence": 5}}
    services._repo_cached = lambda _op, _root, _params, compute: compute()

    result = services.fast_context("C:/repo", "find route", 2000)

    assert result["context_source"] == "deterministic-fast"
    assert result["degraded"] is True
    assert result["continuation"]["mode"] == "full"


def test_shipped_mcp_entrypoints_default_context_to_fast_and_telemetry_to_process():
    source = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")

    assert '"mode": "full" if mode == "full" else "fast"' in source
    assert 'scope: str = "process"' in source
    assert 'scope={scope}' in source

    wrapper = (ROOT / "mcp/local_ai_mcp.py").read_text(encoding="utf-8")
    assert "from local_ai_hub.mcp_server import mcp" in wrapper


def test_shipped_mcp_status_uses_lightweight_live_endpoint_by_default():
    source = (ROOT / "src/local_ai_hub/mcp_server.py").read_text(encoding="utf-8")

    assert 'CLIENT.get(f"/v1/live/status?light=1&scope={scope}")' in source
    assert '"token_saving": status.get("observability")' in source


def test_context_http_endpoint_defaults_to_fast_for_older_mcp_clients():
    source = (ROOT / "src/local_ai_hub/http_server.py").read_text(encoding="utf-8")

    assert 'payload.get("mode", "fast")' in source
