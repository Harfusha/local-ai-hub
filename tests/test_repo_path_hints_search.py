from __future__ import annotations

from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


class _NoCacheFlight:
    def get_or_compute(self, _key, compute):
        return compute(), False, False


def _services_for_fixture(root: Path) -> LocalAIServices:
    tools = RepositoryTools({
        "search": {
            "prefer_git_files": False,
            "use_ripgrep_if_available": False,
            "use_git_grep_fallback": False,
        },
    })
    # Pin the pure-Python full-search path so this paired check is independent
    # of installed search binaries and measures paths actually read.
    tools._ripgrep_candidates = lambda *_args: (None, False)
    tools._git_grep_candidates = lambda *_args: (None, False)

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"enriched_search": True}}
    services.repo_flight = _NoCacheFlight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "fixture-v1", "kind": "filesystem"}
    services.repo_tools = tools
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.evidence_store = None
    return services


def test_known_path_hint_preserves_relevant_result_and_reads_fewer_fixture_files(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def verify_token(value):\n    return value == 'ok'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "billing.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_auth.py").write_text("def test_other_auth():\n    assert True\n", encoding="utf-8")
    (tmp_path / "docs" / "notes.py").write_text("NOTE = 'unrelated'\n", encoding="utf-8")
    services = _services_for_fixture(tmp_path)

    baseline = services.repo_search(str(tmp_path), "verify_token")
    hinted = services.repo_search(
        str(tmp_path),
        "verify_token",
        path_hints=[{"path": "src/auth.py", "purpose": "known relevant fixture", "scope": "repo_search"}],
    )

    assert baseline["success"] is True
    assert hinted["success"] is True
    assert [hit["path"] for hit in baseline["results"]] == ["src/auth.py"]
    assert [hit["path"] for hit in hinted["results"]] == ["src/auth.py"]
    assert hinted["scanned_files"] < baseline["scanned_files"]
    assert baseline["scanned_files"] == 4
    assert hinted["scanned_files"] == 1
