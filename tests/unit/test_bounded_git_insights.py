"""Deferred source contracts for bounded Git history and hotspot ranking."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import validate_operation_arguments


def _engine(tmp_path: Path) -> DeterministicEngine:
    return DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})


def _make_repo_active(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    monkeypatch.setattr(mcp_server.FEATURES, "repo", True)
    monkeypatch.setattr(mcp_server.FEATURES, "agent_os", True)
    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)


def test_history_search_uses_two_bounded_literal_searches_and_deduplicates(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = []
    commit = b"a" * 40
    record = (
        commit + b"\0A+B [Ops]\\Name\0" + b"2026-01-10T12:00:00+00:00"
        + b"\0needle subject\0\n"
    )
    literal_author = "A+B [Ops]\\Name <a+b@example.com>"

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=record, stdout_truncated=False, stderr_truncated=False)

    monkeypatch.setattr("local_ai_hub.deterministic.run_hidden", fake_run)
    monkeypatch.setattr("local_ai_hub.deterministic.shutil.which", lambda _name: "git.exe")
    result = _engine(tmp_path).git_history_search(
        str(repo), "needle", 5, author=literal_author, since="2026-01-01",
        until="2026-01-31", path="src/a.py",
    )

    assert len(calls) == 2
    assert all(call[1]["timeout"] <= 8 for call in calls)
    assert all(call[1]["max_output_bytes"] == 1_048_576 for call in calls)
    assert all("--literal-pathspecs" in call[0] and "--no-textconv" in call[0] for call in calls)
    assert all("--fixed-strings" in call[0] for call in calls)
    assert all(f"--author={literal_author}" in call[0] and "src/a.py" in call[0] for call in calls)
    assert all(any(arg.startswith("--since-as-filter=@") for arg in call[0]) for call in calls)
    assert result["complete"] is True
    assert result["count"] == 1
    assert result["commits"][0]["match_type"] == "message, diff_content"


def test_history_search_reports_partial_git_failure_as_incomplete(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = b"b" * 40
    record = commit + b"\0Ada\0" + b"2026-01-10T12:00:00+00:00" + b"\0needle\0\n"
    responses = iter((
        SimpleNamespace(returncode=0, stdout=record, stdout_truncated=False, stderr_truncated=False),
        SimpleNamespace(returncode=128, stdout=b"", stdout_truncated=False, stderr_truncated=False),
    ))
    monkeypatch.setattr("local_ai_hub.deterministic.run_hidden", lambda *_args, **_kwargs: next(responses))
    result = _engine(tmp_path).git_history_search(str(repo), "needle")
    assert result["success"] is True
    assert result["complete"] is False
    assert "diff_content_search_failed" in result["incomplete_reasons"]


@pytest.mark.parametrize("field,value", [
    ("since", "yesterday"),
    ("until", "2026-01-01T12:00:00"),
    ("path", "../outside.py"),
])
def test_history_search_rejects_invalid_filter_before_git(tmp_path, monkeypatch, field, value):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("local_ai_hub.deterministic.run_hidden", lambda *_args, **_kwargs: pytest.fail("Git must not run"))
    result = _engine(tmp_path).git_history_search(str(repo), "needle", **{field: value})
    assert result["success"] is False


def test_hotspots_apply_ninety_day_half_life_and_report_raw_churn(tmp_path, monkeypatch):
    from local_ai_hub import deterministic

    repo = tmp_path / "repo"
    source = repo / "src" / "a.py"
    source.parent.mkdir(parents=True)
    source.write_text("if True:\n    pass\n", encoding="utf-8")
    # On Windows path ctime can be birth time while handle ctime follows mtime.
    # Deliberately separate those timestamps without changing file identity.
    os.utime(source, ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
    now = 1_800_000_000.0
    timestamp = int(now - 90 * 86_400)
    output = b"\0LAH_HOTSPOT:" + str(timestamp).encode() + b"\0\0\nsrc/a.py\0"
    monkeypatch.setattr(deterministic.time, "time", lambda: now)
    monkeypatch.setattr("local_ai_hub.deterministic.shutil.which", lambda _name: "git.exe")
    monkeypatch.setattr(
        deterministic,
        "run_hidden",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=output, stdout_truncated=False, stderr_truncated=False,
        ),
    )

    result = _engine(tmp_path).find_hotspots(str(repo), days=180, limit=10)
    assert result["complete"] is True
    assert result["algorithm"] == "git-recency-half-life-90d-v1"
    assert result["hotspots"][0]["churn_commits"] == 1
    assert result["hotspots"][0]["recency_weighted_churn"] == pytest.approx(0.5)
    assert result["recency_half_life_days"] == 90


def test_hotspot_truncation_is_incomplete_and_not_cached(tmp_path, monkeypatch):
    from local_ai_hub import deterministic

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("local_ai_hub.deterministic.shutil.which", lambda _name: "git.exe")
    monkeypatch.setattr(
        deterministic,
        "run_hidden",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=b"", stdout_truncated=True, stderr_truncated=False,
        ),
    )
    result = _engine(tmp_path).find_hotspots(str(repo))
    assert result["complete"] is False
    assert "git_output_truncated" in result["incomplete_reasons"]


@pytest.mark.parametrize("legacy", [{"diff": "90"}, {"max_tokens": 90}])
def test_hotspot_contract_rejects_retired_inputs(legacy):
    assert validate_operation_arguments("local_ai_repo", "hotspots", legacy) is not None


def test_history_filters_are_scoped_to_history_action():
    assert validate_operation_arguments(
        "local_ai_repo", "code_index", {"author": "Ada"}
    ) is not None
    assert validate_operation_arguments(
        "local_ai_repo", "code_index", {"max_commits": 4}
    ) is not None


def test_mcp_hotspots_forwards_only_canonical_window_and_limit(monkeypatch, tmp_path):
    _make_repo_active(monkeypatch)
    calls = []
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _profile: 1)
    monkeypatch.setattr(mcp_server, "_compact", lambda value, *_args, **_kwargs: value)
    monkeypatch.setattr(
        mcp_server, "CLIENT",
        SimpleNamespace(post=lambda route, payload, **_kwargs: calls.append((route, payload)) or {"success": True}),
    )

    result = mcp_server._local_ai_repo_impl(
        action="hotspots", root=str(tmp_path), days=9, limit=7,
    )
    assert result == {"success": True}
    assert calls == [("/api/repo/hotspots", {"root": str(tmp_path), "days": 9, "limit": 7})]


@pytest.mark.parametrize("legacy", [{"diff": "90"}, {"max_tokens": 90}])
def test_mcp_hotspots_does_not_forward_retired_aliases(monkeypatch, tmp_path, legacy):
    _make_repo_active(monkeypatch)
    calls = []
    monkeypatch.setattr(
        mcp_server, "CLIENT",
        SimpleNamespace(post=lambda *args, **kwargs: calls.append((args, kwargs))),
    )
    result = mcp_server._local_ai_repo_impl(
        action="hotspots", root=str(tmp_path), **legacy,
    )
    assert result["success"] is False
    assert calls == []


@pytest.mark.parametrize("field,value", [
    ("max_commits", 4), ("author", "Ada"), ("since", "2026-01-01"),
    ("until", "2026-01-31"), ("days", 9), ("limit", 7),
])
def test_direct_mcp_impl_rejects_history_and_hotspot_fields_outside_actions(
    monkeypatch, tmp_path, field, value,
):
    _make_repo_active(monkeypatch)
    calls = []
    monkeypatch.setattr(
        mcp_server, "CLIENT",
        SimpleNamespace(post=lambda *args, **kwargs: calls.append((args, kwargs))),
    )
    result = mcp_server._local_ai_repo_impl(
        action="route" if field == "limit" else "code_index", root=str(tmp_path), **{field: value},
    )
    assert result["success"] is False
    assert calls == []


def test_mcp_hotspots_uses_canonical_default_window_and_limit(monkeypatch, tmp_path):
    _make_repo_active(monkeypatch)
    calls = []
    monkeypatch.setattr(mcp_server, "_client_root", lambda value: value)
    monkeypatch.setattr(mcp_server, "_timeout", lambda _profile: 1)
    monkeypatch.setattr(
        mcp_server, "_compact", lambda value, *_args, **_kwargs: value,
    )
    monkeypatch.setattr(
        mcp_server, "CLIENT",
        SimpleNamespace(post=lambda route, payload, **_kwargs: calls.append((route, payload)) or {"success": True}),
    )
    result = mcp_server._local_ai_repo_impl(action="hotspots", root=str(tmp_path))
    assert result == {"success": True}
    assert calls == [("/api/repo/hotspots", {"root": str(tmp_path), "days": 30, "limit": 20})]
