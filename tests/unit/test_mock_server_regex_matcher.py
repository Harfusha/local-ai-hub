"""Deferred bundle regressions: matching uses no network or project execution."""
import json

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.mock_matching import compile_mock_matcher


def test_regex_and_query_wildcards_match_dynamic_requests():
    matcher = compile_mock_matcher({
        "method": "GET", "path_regex": r"^/users/[0-9]+$",
        "query_matchers": {"name": "Ada*", "page": "?"},
    })
    assert matcher.matches("GET", "/users/42?name=Adam&page=2&extra=allowed")
    assert not matcher.matches("GET", "/users/no?name=Adam&page=2")
    assert not matcher.matches("GET", "/users/42?name=Bob&page=2")
    assert not matcher.matches("GET", "/users/42?name=Adam")
    assert not matcher.matches("POST", "/users/42?name=Adam&page=2")


def test_template_escapes_literal_regex_metacharacters():
    matcher = compile_mock_matcher({"method": "GET", "path": "/v1.0/items/{id}"})
    assert matcher.matches("GET", "/v1.0/items/abc")
    assert not matcher.matches("GET", "/v1x0/items/abc")
    assert not matcher.matches("GET", "/v1.0/items/a/b")


@pytest.mark.parametrize("pattern", [r"(a+)+$", r"a|b", r".*.*", r"(a)\1", r"a{50000}"])
def test_unsafe_regex_is_rejected_before_server_start(pattern):
    with pytest.raises(ValueError):
        compile_mock_matcher({"method": "GET", "path_regex": pattern})


def test_query_duplicates_and_limits_are_explicit():
    matcher = compile_mock_matcher({"path": "/items", "query_matchers": {"tag": "good*"}})
    assert matcher.matches("GET", "/items?tag=bad&tag=good-value")
    assert not matcher.matches("GET", "/items?" + "&".join("tag=good" for _ in range(65)))
    assert not matcher.matches("GET", "/items?tag=" + "g" * 5000)


def test_invalid_matcher_spec_never_binds_a_listener(tmp_path, monkeypatch):
    import socketserver

    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid matcher must fail before bind")

    monkeypatch.setattr(socketserver, "TCPServer", forbidden)
    spec = tmp_path / "cassette.json"
    spec.write_text(json.dumps({"routes": [{"method": "GET", "path_regex": "(a+)+"}]}), encoding="utf-8")
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}})
    result = broker.mock_server_start(str(tmp_path), spec_path=str(spec), port=0)
    assert result["success"] is False
    assert "unsupported" in result["error"]
