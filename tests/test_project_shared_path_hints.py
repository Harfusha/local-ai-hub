from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from local_ai_hub.project_config import resolve_project_config, resolve_project_context


def test_curated_hints_travel_with_project_and_rank_existing_candidates(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (first / name).write_text("value = 1\n", encoding="utf-8")
    (first / ".local-ai.toml").write_text(
        'entry_points = ["b.py"]\n[shared_path_hints]\nsearch = ["c.py"]\n',
        encoding="utf-8",
    )
    second = tmp_path / "second"
    shutil.copytree(first, second)
    for root, state in ((first, "one"), (second, "two")):
        context = resolve_project_context(root, tmp_path / state)
        assert context.resolution.error_codes == ()
        assert context.settings.shared_path_hints["search"] == ("c.py",)
        candidates = ["a.py", "b.py", "c.py"]
        usage = context.prioritize_paths(candidates, purpose="search", scope="repository", repository_revision="rev")
        assert usage.paths == ("c.py", "b.py", "a.py")
        assert usage.hint_used
        other = context.prioritize_paths(candidates, purpose="test", scope="repository", repository_revision="rev")
        assert other.paths == ("b.py", "a.py", "c.py")
        assert sorted(usage.paths) == sorted(candidates)


def test_missing_shared_hint_cannot_invent_a_candidate(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        '[shared_path_hints]\nsearch = ["missing.py"]\n', encoding="utf-8"
    )
    context = resolve_project_context(tmp_path, tmp_path / "state")
    usage = context.prioritize_paths(["a.py"], purpose="search", scope="repository", repository_revision="rev")
    assert usage.paths == ("a.py",)
    assert not usage.hint_used
    assert usage.fallback_used


@pytest.mark.parametrize("config", [
    '[shared_path_hints]\nsearch = ["../outside"]\n',
    '[shared_path_hints]\nsearch = ["src/**"]\n',
    '[shared_path_hints]\nsearch = "src"\n',
    '[shared_path_hints]\n"invalid purpose" = ["src"]\n',
])
def test_invalid_shared_hint_configuration_uses_existing_fail_closed_policy(tmp_path: Path, config: str) -> None:
    (tmp_path / ".local-ai.toml").write_text(config, encoding="utf-8")
    result = resolve_project_config(tmp_path)
    assert result.error_codes == ("invalid_config",)
    assert not result.settings.shared_path_hints
