from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from local_ai_hub.project_config import (
    PathHint,
    PathHintUsage,
    ProjectPathHintStore,
    prioritize_paths_with_hints,
    resolve_project_context,
    validate_path_hint,
)


def test_path_hint_telemetry_metadata_excludes_candidate_paths() -> None:
    usage = PathHintUsage(
        paths=("private/customer_source.py",),
        hint_used=True,
        fallback_used=False,
        hint_helped=None,
    )

    metadata = usage.telemetry_metadata()

    assert metadata == {
        "hint_used": True,
        "fallback_used": False,
        "hint_helped": None,
    }
    assert "paths" not in metadata
    assert "private/customer_source.py" not in repr(metadata)


def test_path_hint_telemetry_metadata_normalizes_malformed_runtime_values() -> None:
    usage = PathHintUsage(
        paths=(),
        hint_used="private/hint.txt",  # type: ignore[arg-type]
        fallback_used="private/fallback.txt",  # type: ignore[arg-type]
        hint_helped=True,  # type: ignore[arg-type]
    )

    assert usage.telemetry_metadata() == {
        "hint_used": False,
        "fallback_used": False,
        "hint_helped": None,
    }


def test_cakephp_button_hint_prioritizes_templates_without_narrowing_results(
    tmp_path: Path,
) -> None:
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "templates" / "element" / "button.php").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("x")
    candidates = ("src/button.py", "templates/element/button.php")
    hint = PathHint(
        path="templates/element",
        purpose="find_button",
        scope="repository_search",
        evidence_id="evidence-1",
        provenance="verified_search",
        repository_revision="rev-1",
        config_digest="digest-1",
    )

    usage = prioritize_paths_with_hints(
        tmp_path,
        candidates,
        (hint,),
        purpose="find_button",
        scope="repository_search",
        repository_revision="rev-1",
        config_digest="digest-1",
    )

    assert usage.paths == ("templates/element/button.php", "src/button.py")
    assert set(usage.paths) == set(candidates)
    assert usage.hint_used is True
    assert usage.fallback_used is False
    assert usage.hint_helped is None


def test_hint_freshness_scope_existence_and_containment_are_rechecked(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x")
    valid = PathHint(
        path="src/main.py",
        purpose="entry",
        scope="repo",
        evidence_id="e-1",
        provenance="test",
        repository_revision="rev-1",
        config_digest="digest-1",
    )
    assert validate_path_hint(
        tmp_path,
        valid,
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-1",
        learned=True,
    ) == (tmp_path / "src" / "main.py").resolve()
    assert validate_path_hint(
        tmp_path,
        valid,
        purpose="entry",
        scope="repo",
        repository_revision="rev-2",
        config_digest="digest-1",
        learned=True,
    ) is None
    assert validate_path_hint(
        tmp_path,
        valid,
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-2",
        learned=True,
    ) is None
    assert validate_path_hint(
        tmp_path,
        PathHint("../secret", "entry", "repo"),
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-1",
    ) is None


def test_persisted_hints_share_only_within_same_git_common_directory(
    tmp_path: Path, monkeypatch
) -> None:
    state = tmp_path / "state"
    common = tmp_path / "shared.git"
    common.mkdir()
    first = tmp_path / "first"
    second = tmp_path / "second"
    other = tmp_path / "other"
    for root in (first, second, other):
        (root / "src").mkdir(parents=True)
        (root / "src" / "main.py").write_text("x")

    import local_ai_hub.project_config as project_config

    monkeypatch.setattr(
        project_config,
        "_git_common_dir",
        lambda root: common if root != other else None,
    )
    store = ProjectPathHintStore(state, first)
    store.add(
        PathHint(
            path="src/main.py",
            purpose="entry",
            scope="repo",
            evidence_id="evidence-1",
            provenance="verified_search",
            repository_revision="rev-1",
            config_digest="digest-1",
        )
    )

    linked = ProjectPathHintStore(state, second)
    isolated = ProjectPathHintStore(state, other)
    assert len(
        linked.find(
            purpose="entry",
            scope="repo",
            repository_revision="rev-1",
            config_digest="digest-1",
        )
    ) == 1
    assert isolated.find(
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-1",
    ) == ()
    assert linked.find(
        purpose="entry",
        scope="repo",
        repository_revision="rev-2",
        config_digest="digest-1",
    ) == ()


def test_shared_namespace_scopes_hints_within_git_common_directory(
    tmp_path: Path, monkeypatch
) -> None:
    import local_ai_hub.project_config as project_config

    state = tmp_path / "state"
    shared_common = tmp_path / "shared.git"
    isolated_common = tmp_path / "isolated.git"
    shared_common.mkdir()
    isolated_common.mkdir()
    first, linked, isolated, other_namespace = (
        tmp_path / name
        for name in ("first", "linked", "isolated", "other_namespace")
    )
    for root in (first, linked, isolated):
        (root / "src").mkdir(parents=True)
        (root / "src" / "main.py").write_text("x", encoding="utf-8")
        (root / ".local-ai.toml").write_text(
            'shared_namespace = "team"\n', encoding="utf-8"
        )
    (other_namespace / "src").mkdir(parents=True)
    (other_namespace / "src" / "main.py").write_text("x", encoding="utf-8")
    (other_namespace / ".local-ai.toml").write_text(
        'shared_namespace = "other"\n', encoding="utf-8"
    )

    monkeypatch.setattr(
        project_config,
        "_git_common_dir",
        lambda root: isolated_common if root == isolated else shared_common,
    )
    first_context = resolve_project_context(first, state)
    linked_context = resolve_project_context(linked, state)
    isolated_context = resolve_project_context(isolated, state)
    other_namespace_context = resolve_project_context(other_namespace, state)
    hint = PathHint(
        path="src/main.py",
        purpose="entry",
        scope="task",
        evidence_id="evidence-team",
        provenance="verified_search",
        repository_revision="rev-1",
        config_digest=first_context.config_digest,
    )
    first_context.save_path_hint(hint)

    assert linked_context.path_hints(
        purpose="entry", scope="task", repository_revision="rev-1"
    ) == (hint,)
    assert isolated_context.path_hints(
        purpose="entry", scope="task", repository_revision="rev-1"
    ) == ()
    assert other_namespace_context.path_hints(
        purpose="entry", scope="task", repository_revision="rev-1"
    ) == ()


def test_expired_hint_falls_back_and_reports_unhelpful_hint(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x")
    hint = PathHint(
        path="missing",
        purpose="entry",
        scope="repo",
        evidence_id="e-1",
        provenance="test",
        repository_revision="rev-1",
        config_digest="digest-1",
        expires_at="2020-01-01T00:00:00Z",
    )
    usage = prioritize_paths_with_hints(
        tmp_path,
        ("src/main.py",),
        (hint,),
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-1",
    )

    assert usage.paths == ("src/main.py",)
    assert usage.hint_used is False
    assert usage.fallback_used is True
    assert usage.hint_helped is None
    assert validate_path_hint(
        tmp_path,
        hint,
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-1",
        now=datetime.now(timezone.utc),
        learned=True,
    ) is None


def test_project_context_reuses_only_current_evidence_bound_hints(
    tmp_path: Path, monkeypatch
) -> None:
    import local_ai_hub.project_config as project_config

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x")
    git_lookups = 0

    def no_git(_root: Path) -> None:
        nonlocal git_lookups
        git_lookups += 1
        return None

    monkeypatch.setattr(project_config, "_git_common_dir", no_git)
    (tmp_path / ".local-ai.toml").write_text(
        'shared_namespace = "sample"\n', encoding="utf-8"
    )

    context = resolve_project_context(tmp_path, tmp_path / "state")
    assert git_lookups == 1
    assert sorted(path.name for path in (tmp_path / "state").iterdir()) == [
        "project-path-hints.sqlite3"
    ]
    hint = PathHint(
        path="src/main.py",
        purpose="entry",
        scope="task",
        evidence_id="evidence-1",
        provenance="verified_search",
        repository_revision="rev-1",
        config_digest=context.config_digest,
    )
    context.save_path_hint(hint)

    assert context.path_hints(
        purpose="entry", scope="task", repository_revision="rev-1"
    ) == (hint,)
    assert context.path_hints(
        purpose="entry", scope="task", repository_revision="rev-2"
    ) == ()


def test_project_context_prioritizes_candidates_with_current_saved_hints(
    tmp_path: Path, monkeypatch
) -> None:
    import local_ai_hub.project_config as project_config

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x")
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / ".local-ai.toml").write_text(
        'shared_namespace = "sample"\n[retrieval_weights]\nlexical = 0.6\n',
        encoding="utf-8",
    )
    context = resolve_project_context(tmp_path, tmp_path / "state")
    context.save_path_hint(
        PathHint(
            path="src/main.py",
            purpose="repository_search",
            scope="task",
            evidence_id="evidence-1",
            provenance="verified_search",
            repository_revision="rev-1",
            config_digest=context.config_digest,
        )
    )

    usage = context.prioritize_paths(
        ("docs/readme.md", "src/main.py", "tests/test_main.py"),
        purpose="repository_search",
        scope="task",
        repository_revision="rev-1",
    )

    assert usage.paths == ("src/main.py", "docs/readme.md", "tests/test_main.py")
    assert usage.hint_used is True
    assert usage.fallback_used is False
    assert usage.hint_helped is None

    (tmp_path / ".local-ai.toml").write_text(
        'shared_namespace = "sample"\n[retrieval_weights]\nlexical = 0.7\n',
        encoding="utf-8",
    )
    updated_context = resolve_project_context(tmp_path, tmp_path / "state")
    stale_usage = updated_context.prioritize_paths(
        ("docs/readme.md", "src/main.py", "tests/test_main.py"),
        purpose="repository_search",
        scope="task",
        repository_revision="rev-1",
    )

    assert updated_context.config_digest != context.config_digest
    assert stale_usage.paths == ("docs/readme.md", "src/main.py", "tests/test_main.py")
    assert stale_usage.hint_used is False


def test_project_context_prioritizes_entry_points_then_request_hints_then_saved(
    tmp_path: Path, monkeypatch
) -> None:
    import local_ai_hub.project_config as project_config

    for relative in (
        "src/main.py",
        "templates/button.php",
        "saved/result.py",
        "secret/keys.txt",
        "other/file.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    (tmp_path / ".local-ai.toml").write_text(
        'entry_points = ["src/main.py"]\n'
        'exclude_paths = ["secret/**"]\n',
        encoding="utf-8",
    )
    context = resolve_project_context(tmp_path, tmp_path / "state")
    context.save_path_hint(
        PathHint(
            path="saved/result.py",
            purpose="repository_search",
            scope="task",
            evidence_id="evidence-1",
            provenance="verified_search",
            repository_revision="rev-1",
            config_digest=context.config_digest,
        )
    )

    usage = context.prioritize_paths(
        (
            "other/file.py",
            "saved/result.py",
            "secret/keys.txt",
            "templates/button.php",
            "src/main.py",
        ),
        purpose="repository_search",
        scope="task",
        repository_revision="rev-1",
        path_hints=(
            PathHint(
                path="templates",
                purpose="repository_search",
                scope="task",
            ),
            PathHint(
                path="secret",
                purpose="repository_search",
                scope="task",
            ),
        ),
    )

    assert usage.paths == (
        "src/main.py",
        "secret/keys.txt",
        "templates/button.php",
        "saved/result.py",
        "other/file.py",
    )
    assert set(usage.paths) == {
        "other/file.py",
        "saved/result.py",
        "secret/keys.txt",
        "templates/button.php",
        "src/main.py",
    }
    assert usage.hint_used is True
    assert usage.fallback_used is False
    assert project_config.path_is_allowed(
        tmp_path,
        "secret/keys.txt",
        context.settings,
        phase="repository_search",
    ) is False


def test_project_context_caps_request_hints_at_sixty_four(
    tmp_path: Path, monkeypatch
) -> None:
    import local_ai_hub.project_config as project_config

    (tmp_path / "other.py").write_text("x", encoding="utf-8")
    (tmp_path / "late.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(project_config, "_git_common_dir", lambda _root: None)
    context = resolve_project_context(tmp_path, tmp_path / "state")
    hints = tuple(
        PathHint(path=f"missing-{index}.py", purpose="search", scope="repo")
        for index in range(64)
    ) + (PathHint(path="late.py", purpose="search", scope="repo"),)

    usage = context.prioritize_paths(
        ("other.py", "late.py"),
        purpose="search",
        scope="repo",
        repository_revision="rev-1",
        path_hints=hints,
    )

    assert usage.paths == ("other.py", "late.py")
    assert usage.hint_used is False
    assert usage.fallback_used is True


def test_current_hint_is_not_starved_by_stale_rows(tmp_path: Path) -> None:
    (tmp_path / "fresh.py").write_text("x")
    store = ProjectPathHintStore(tmp_path / "state", tmp_path, git_common_dir=None)
    with closing(store._connect()) as connection, connection:
        connection.executemany(
            """INSERT INTO project_path_hints
               (project_id, path, purpose, scope, evidence_id, provenance,
                repository_revision, config_digest, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                (
                    store.project_id,
                    f"aaa/stale-{index:03}.py",
                    "entry",
                    "repo",
                    f"stale-{index}",
                    "old_evidence",
                    "old-revision",
                    "old-digest",
                )
                for index in range(257)
            ),
        )
        connection.execute(
            """INSERT INTO project_path_hints
               (project_id, path, purpose, scope, evidence_id, provenance,
                repository_revision, config_digest, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                store.project_id,
                "fresh.py",
                "entry",
                "repo",
                "fresh-evidence",
                "verified_search",
                "current-revision",
                "current-digest",
            ),
        )
        connection.commit()

    found = store.find(
        purpose="entry",
        scope="repo",
        repository_revision="current-revision",
        config_digest="current-digest",
    )

    assert tuple(hint.path for hint in found) == ("fresh.py",)


def test_path_hint_prioritization_preserves_duplicate_candidates(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x")

    usage = prioritize_paths_with_hints(
        tmp_path,
        ("src/main.py", "src/main.py"),
        (),
        purpose="entry",
        scope="repo",
        repository_revision="rev-1",
        config_digest="digest-1",
    )

    assert usage.paths == ("src/main.py", "src/main.py")


def test_hint_store_caps_rows_without_evicting_newest_other_revision(
    tmp_path: Path, monkeypatch
) -> None:
    import local_ai_hub.project_config as project_config

    (tmp_path / "main.py").write_text("x")
    monkeypatch.setattr(project_config, "_MAX_HINTS_PER_PROJECT", 2)
    store = ProjectPathHintStore(tmp_path / "state", tmp_path, git_common_dir=None)

    for index in range(3):
        store.add(
            PathHint(
                path="main.py",
                purpose="entry",
                scope="repo",
                evidence_id=f"evidence-{index}",
                provenance="verified_search",
                repository_revision=f"revision-{index}",
                config_digest="digest",
            )
        )

    with closing(store._connect()) as connection, connection:
        rows = connection.execute(
            """SELECT repository_revision FROM project_path_hints
               WHERE project_id = ? ORDER BY rowid""",
            (store.project_id,),
        ).fetchall()

    assert rows == [("revision-1",), ("revision-2",)]
