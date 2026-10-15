from __future__ import annotations

import pytest

from local_ai_hub import http_server


@pytest.mark.parametrize("revision", [True, 7, None, "", "   ", " x", "x ", "x" * 257])
def test_completion_rejects_malformed_repository_revision_pin(revision):
    with pytest.raises(http_server.RequestBodyError):
        http_server.Handler._validate_payload(
            "/api/agent-state/verification",
            {"action": "completion", "repository_revision": revision},
        )


def test_completion_missing_pin_and_exact_pin_are_valid():
    http_server.Handler._validate_payload(
        "/api/agent-state/verification", {"action": "completion"}
    )
    http_server.Handler._validate_payload(
        "/api/agent-state/verification",
        {"action": "completion", "repository_revision": "opaque-current-id"},
    )
    assert http_server._completion_revision_pin_matches(
        "opaque-current-id", "opaque-current-id"
    )
    assert not http_server._completion_revision_pin_matches(
        "opaque-stale-id", "opaque-current-id"
    )


def test_completion_fingerprint_typeerror_does_not_retry_old_signature():
    class RepoState:
        calls = 0

        def fingerprint(self, root, *, force):
            self.calls += 1
            assert root == "repo"
            assert force is True
            raise TypeError("fingerprint failed internally")

    class Snapshot:
        revision = "snapshot-current"
        degraded = False
        error = None

    class RepoTools:
        calls = 0

        def git_snapshot(self, root):
            self.calls += 1
            assert root == "repo"
            return Snapshot()

    state = RepoState()
    tools = RepoTools()
    revision, stop = http_server._completion_revision_or_stop("repo", tools, state)

    assert revision == "snapshot-current"
    assert stop is None
    assert state.calls == 1
    assert tools.calls == 1
