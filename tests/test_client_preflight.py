from __future__ import annotations

from local_ai_hub.client import HubClient


def _client(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[server]\nport=11435\nstate_dir='" + (tmp_path / "state").as_posix() + "'\n",
        encoding="utf-8",
    )
    return HubClient(tenant="test", config_path=str(config))


def test_client_rejects_non_git_diff_without_transport(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport must not run")))

    result = client.post("/v1/review/diff", {"root": str(tmp_path)})

    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["preflight"] is True


def test_client_rejects_empty_symbol_without_transport(tmp_path, monkeypatch):
    client = _client(tmp_path)
    monkeypatch.setattr(client, "_pooled_open", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport must not run")))

    result = client.post("/v1/code/symbol", {"root": str(tmp_path), "symbol": "  "})

    assert result["terminal"] is True
    assert result["preflight"] is True
