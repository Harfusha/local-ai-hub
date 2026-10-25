from concurrent.futures import Future

import pytest

from local_ai_hub import treesitter_parser as parser


def _isolated_parent(monkeypatch, response=True, error=None):
    calls = []

    class WorkerPool:
        def submit(self, callback, *args):
            calls.append((callback, args))
            future = Future()
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(response)
            return future

    monkeypatch.setattr(parser, "_IN_WORKER", False)
    monkeypatch.setattr(parser, "_INIT_ATTEMPTED", False)
    monkeypatch.setattr(parser, "_PARSERS", {})
    monkeypatch.setattr(parser, "_LANGUAGES", {})
    monkeypatch.setattr(parser, "_WORKER_DISABLED_CAUSE", None)
    monkeypatch.setattr(parser, "_use_isolated_worker", lambda: True)
    monkeypatch.setattr(parser, "_get_worker_pool", WorkerPool)
    monkeypatch.setattr(
        parser, "_init_treesitter",
        lambda: pytest.fail("availability must not load native parsers in the parent"),
    )
    return calls


def test_isolated_availability_uses_worker_instead_of_empty_parent_parser_table(monkeypatch):
    calls = _isolated_parent(monkeypatch)

    assert parser.is_treesitter_available("python") is True
    assert len(calls) == 1
    assert calls[0][1] == ("python",)


@pytest.mark.parametrize("response", [False, None, 1, "true", {"available": True}])
def test_isolated_availability_requires_explicit_worker_boolean(monkeypatch, response):
    calls = _isolated_parent(monkeypatch, response=response)

    assert parser.is_treesitter_available("python") is False
    assert len(calls) == 1


def test_disabled_worker_availability_neither_imports_nor_dispatches(monkeypatch):
    calls = _isolated_parent(monkeypatch)
    monkeypatch.setattr(parser, "_WORKER_DISABLED_CAUSE", "verified_access_violation")

    assert parser.is_treesitter_available("python") is False
    assert calls == []


def test_worker_availability_failure_is_explicit_and_fail_closed(monkeypatch):
    calls = _isolated_parent(monkeypatch, error=TimeoutError("worker did not answer"))
    disabled = []
    monkeypatch.setattr(parser, "_disable_worker_pool", lambda cause: disabled.append(cause))

    assert parser.is_treesitter_available("python") is False
    assert len(calls) == 1
    assert len(disabled) == 1
    assert "TimeoutError" in disabled[0]
