from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_context import CompiledContext, ContextCompiler, ContextElement, ContextRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.task_context import build_context_request


def test_context_etag_changes_when_freshness_or_provenance_changes() -> None:
    element = ContextElement(
        element_id="memory-1",
        source_kind="memory",
        content="same content",
        estimated_tokens=3,
        reason="relevant",
        freshness=0.4,
        provenance={"revision": "r1"},
    )
    first = CompiledContext(elements=[element], estimated_tokens=3, token_budget=512)

    refreshed = replace(element, freshness=0.9, provenance={"revision": "r2"})
    second = replace(first, elements=[refreshed])

    assert first.text() == second.text()
    assert first.etag() != second.etag()


def test_effective_preload_settings_have_stable_but_sensitive_digest(tmp_path) -> None:
    settings = {"context": {"preloads": {"profiles": {"review": {"max_files": 4}}}}}
    first = ContextCompiler(AgentStateStore(tmp_path / "first.sqlite3"), config=settings)
    same = ContextCompiler(AgentStateStore(tmp_path / "same.sqlite3"), config=settings)
    changed = ContextCompiler(
        AgentStateStore(tmp_path / "changed.sqlite3"),
        config={"context": {"preloads": {"profiles": {"review": {"max_files": 6}}}}},
    )

    assert first.settings_digest_for_profile("review") == same.settings_digest_for_profile("review")
    assert first.settings_digest_for_profile("review") != changed.settings_digest_for_profile("review")


def test_context_identity_uses_effective_preload_settings_when_digest_is_not_supplied(tmp_path) -> None:
    settings = {"context": {"preloads": {"profiles": {"review": {"max_files": 4}}}}}
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"), config=settings)
    request = ContextRequest(task_id="task-1", token_budget=512, preload_profile="review")

    first = compiler.compile(request)
    settings["context"]["preloads"]["profiles"]["review"]["max_files"] = 6
    changed = compiler.compile(replace(request, since_hash=first.etag()))

    assert changed.etag() != first.etag()
    assert changed.unchanged is False


def test_request_digest_keeps_project_and_preload_settings_sensitive(tmp_path) -> None:
    request = ContextRequest(
        task_id="task-1",
        root=str(tmp_path),
        preload_profile="work",
        settings_digest="a" * 32,
    )
    compiler_a = ContextCompiler(
        AgentStateStore(tmp_path / "state-a.sqlite3"),
        config={"context": {"preloads": {"profiles": {"work": {"include": ["src/a.py"]}}}}},
    )
    compiler_b = ContextCompiler(
        AgentStateStore(tmp_path / "state-b.sqlite3"),
        config={"context": {"preloads": {"profiles": {"work": {"include": ["src/b.py"]}}}}},
    )

    assert compiler_a.compile(request).etag() != compiler_b.compile(request).etag()


def test_resolved_project_context_digest_changes_compiler_identity(tmp_path, monkeypatch) -> None:
    project_config = ModuleType("local_ai_hub.project_config")
    project_config.resolve_pinned_context = lambda _root, _settings: ()
    project_config.resolve_entry_points = lambda _root, _settings: ()
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)
    settings = SimpleNamespace(pinned_context=(), entry_points=())

    def resolved_context(config_digest: str, hinted_path: str):
        return SimpleNamespace(
            root=tmp_path,
            settings=settings,
            config_digest=config_digest,
            path_hints=lambda **_kwargs: (SimpleNamespace(path=hinted_path),),
        )

    payload = {"task_id": "task-7", "root": str(tmp_path), "repo_revision": "rev-7"}
    first_request = build_context_request(
        payload,
        settings_digest="profile-digest",
        project_context=resolved_context("a" * 32, "src/current.py"),
    )
    changed_config_request = build_context_request(
        payload,
        settings_digest="profile-digest",
        project_context=resolved_context("b" * 32, "src/current.py"),
    )
    changed_hint_request = build_context_request(
        payload,
        settings_digest="profile-digest",
        project_context=resolved_context("a" * 32, "src/other.py"),
    )
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))

    first = compiler.compile(first_request)
    changed_config = compiler.compile(changed_config_request)
    changed_hint = compiler.compile(changed_hint_request)

    assert first_request.settings_digest != changed_config_request.settings_digest
    assert first_request.path_hints != changed_hint_request.path_hints
    assert first.etag() != changed_config.etag()
    assert first.etag() != changed_hint.etag()


def test_context_delta_history_is_scoped_to_semantic_request_identity(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    request = ContextRequest(
        task_id="task-1",
        token_budget=512,
        root=str(tmp_path / "repo-a"),
        session_id="session-a",
        phase="review",
        focus=("cache identity",),
    )

    first = compiler.compile(request)
    unchanged = compiler.compile(replace(request, since_hash=first.etag()))
    different_root = compiler.compile(
        replace(request, root=str(tmp_path / "repo-b"), since_hash=first.etag())
    )
    different_phase = compiler.compile(
        replace(request, phase="handoff", since_hash=first.etag())
    )
    different_session = compiler.compile(
        replace(request, session_id="session-b", since_hash=first.etag())
    )

    assert unchanged.unchanged is True
    assert different_root.unchanged is False
    assert different_root.etag() != first.etag()
    assert different_root.delta_from == first.etag()
    assert different_phase.unchanged is False
    assert different_phase.etag() != first.etag()
    assert different_session.unchanged is False
    assert different_session.etag() != first.etag()


def test_scope_changes_return_full_seeded_context_instead_of_unrelated_delta(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("stable context preload", encoding="utf-8")
    other_root = tmp_path / "repo-other"
    other_root.mkdir()
    (other_root / "README.md").write_text("stable context preload", encoding="utf-8")
    compiler = ContextCompiler(
        AgentStateStore(tmp_path / "agent_state.sqlite3"),
        config={"context": {"preloads": {"files": ["README.md"]}}},
    )
    request = ContextRequest(
        task_id="task-1",
        token_budget=512,
        root=str(root),
        session_id="session-a",
        focus=("cache identity",),
        preload_profile="default",
    )
    first = compiler.compile(request)
    assert first.elements
    known_ids = {element.element_id for element in first.elements}
    changes = (
        {"root": str(other_root)},
        {"task_id": "task-2"},
        {"session_id": "session-b"},
        {"focus": ("artifact expiry",)},
        {"preload_profile": "alternate"},
        {"token_budget": 256},
        {"include_kinds": ("preload",)},
        {"clone_id": "clone-b"},
        {"worktree_id": "worktree-b"},
        {"branch": "branch-b"},
        {"repository_id": "repository-b"},
        {"repo_revision": "revision-b"},
        {"settings_digest": "settings-digest-b"},
    )

    for change in changes:
        current = compiler.compile(replace(request, since_hash=first.etag(), **change))
        assert current.unchanged is False, change
        assert current.etag() != first.etag(), change
        assert known_ids.issubset({element.element_id for element in current.elements}), change


def test_invalid_settings_digest_is_omitted_from_context_identity(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    request = ContextRequest(task_id="task-1", token_budget=512, settings_digest=None)
    first = compiler.compile(request)
    invalid = compiler.compile(
        replace(request, since_hash=first.etag(), settings_digest="x" * 129)
    )

    assert invalid.unchanged is True


def test_context_identity_includes_bounded_path_hints(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    request = ContextRequest(
        task_id="task-1",
        token_budget=512,
        path_hints=({"path": "src/alpha.py", "purpose": "implementation", "scope": "file"},),
    )

    first = compiler.compile(request)
    changed = compiler.compile(
        replace(
            request,
            since_hash=first.etag(),
            path_hints=({"path": "src/beta.py", "purpose": "implementation", "scope": "file"},),
        )
    )

    assert changed.unchanged is False
    assert changed.etag() != first.etag()


def test_context_identity_distinguishes_path_hints_beyond_inline_limit(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    request = ContextRequest(
        task_id="task-1",
        token_budget=512,
        path_hints=({"path": "a" * 1024 + "x"},),
    )
    first = compiler.compile(request)

    changed = compiler.compile(
        replace(
            request,
            since_hash=first.etag(),
            path_hints=({"path": "a" * 1024 + "y"},),
        )
    )

    assert changed.unchanged is False
    assert changed.etag() != first.etag()


def test_context_identity_caps_path_hints_at_64(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    hints = tuple({"path": f"src/file-{index}.py"} for index in range(64))
    request = ContextRequest(task_id="task-1", token_budget=512, path_hints=hints)

    first = compiler.compile(request)
    extra_hint = compiler.compile(
        replace(
            request,
            since_hash=first.etag(),
            path_hints=hints + ({"path": "src/overflow.py"},),
        )
    )

    assert extra_hint.unchanged is True


def test_context_identity_tracks_path_hint_mapping_fields(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    hint = {
        "path": "src/alpha.py",
        "purpose": "implementation",
        "scope": "file",
        "config_digest": "config-a",
    }
    request = ContextRequest(task_id="task-1", token_budget=512, path_hints=(hint,))

    first = compiler.compile(request)
    changed = compiler.compile(
        replace(
            request,
            since_hash=first.etag(),
            path_hints=({
                "path": "src/alpha.py",
                "purpose": "implementation",
                "scope": "file",
                "config_digest": "config-b",
            },),
        )
    )

    assert changed.unchanged is False
    assert changed.etag() != first.etag()


def test_context_request_builder_preserves_trusted_hints_outside_payload() -> None:
    trusted_hints = tuple(
        {"path": f"src/owned-{index}.py", "purpose": "implementation", "scope": "file"}
        for index in range(65)
    )
    request = build_context_request(
        {
            "task_id": "task-1",
            "path_hints": [{"path": "src/untrusted.py"}],
            "settings_digest": "untrusted-digest",
            "session_id": "session-a",
        },
        trusted_path_hints=trusted_hints,
        settings_digest="trusted-digest",
    )

    assert request.path_hints == trusted_hints[:64]
    assert request.settings_digest == "trusted-digest"
    assert request.session_id == "session-a"


def test_context_compiler_rejects_non_mapping_path_hint(tmp_path) -> None:
    compiler = ContextCompiler(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    request = ContextRequest(
        task_id="task-1",
        token_budget=512,
        path_hints=(SimpleNamespace(path="src/owned.py"),),
    )

    with pytest.raises(ValueError, match="path hint"):
        compiler.compile(request)


def test_context_request_builder_rejects_malformed_trusted_path_hint() -> None:
    with pytest.raises(ValueError, match="path hint"):
        build_context_request(
            {"task_id": "task-1"},
            trusted_path_hints=({"path": "src/owned.py", "scope": 42},),
        )


def test_context_request_builder_rejects_non_mapping_path_hint() -> None:
    with pytest.raises(ValueError, match="path hint"):
        build_context_request(
            {"task_id": "task-1"},
            trusted_path_hints=(SimpleNamespace(path="src/owned.py"),),
        )


def test_context_request_builder_omits_non_printable_settings_digest() -> None:
    request = build_context_request(
        {"task_id": "task-1", "settings_digest": "payload-digest"},
        settings_digest="bad\ndigest",
    )

    assert request.settings_digest is None


def test_context_request_builder_consumes_resolved_project_context(tmp_path, monkeypatch) -> None:
    project_digest = "a" * 32
    for relative in (
        "docs/pinned.md",
        "src/main.py",
        "src/request.py",
        "src/saved.py",
        "src/expired.py",
        "src/malformed-expiry.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("safe", encoding="utf-8")
    project_settings = SimpleNamespace(
        pinned_context=("docs/pinned.md",),
        entry_points=("src/main.py",),
    )
    saved_hint = SimpleNamespace(
        path="src/saved.py",
        purpose="repository_search",
        scope="task",
        evidence_id="evidence-7",
        provenance="verified_search",
        repository_revision="rev-7",
        config_digest=project_digest,
        expires_at="2099-01-01T00:00:00Z",
    )
    stale_hint = SimpleNamespace(
        path="src/stale.py",
        purpose="repository_search",
        scope="task",
        evidence_id="evidence-stale",
        provenance="verified_search",
        repository_revision="old-revision",
        config_digest=project_digest,
        expires_at="2099-01-01T00:00:00Z",
    )
    expired_hint = SimpleNamespace(
        path="src/expired.py",
        purpose="repository_search",
        scope="task",
        evidence_id="evidence-expired",
        provenance="verified_search",
        repository_revision="rev-7",
        config_digest=project_digest,
        expires_at="2000-01-01T00:00:00Z",
    )
    malformed_expiry_hint = SimpleNamespace(
        path="src/malformed-expiry.py",
        purpose="repository_search",
        scope="task",
        evidence_id="evidence-malformed-expiry",
        provenance="verified_search",
        repository_revision="rev-7",
        config_digest=project_digest,
        expires_at="not-a-timestamp",
    )
    saved_query = {}
    project_context = SimpleNamespace(
        root=tmp_path,
        settings=project_settings,
        config_digest=project_digest,
        path_hints=lambda **kwargs: (
            saved_query.update(kwargs)
            or (saved_hint, stale_hint, expired_hint, malformed_expiry_hint)
        ),
    )
    project_config = ModuleType("local_ai_hub.project_config")
    project_config.resolve_pinned_context = lambda root, settings: tuple(
        Path(root) / path for path in settings.pinned_context
    )
    project_config.resolve_entry_points = lambda root, settings: tuple(
        Path(root) / path for path in settings.entry_points
    )
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", project_config)

    request = build_context_request(
        {
            "task_id": "task-7",
            "root": str(tmp_path),
            "repo_revision": "rev-7",
            "session_id": "session-7",
            "path_hints": [{"path": "payload/untrusted.py"}],
        },
        trusted_path_hints=({"path": str(tmp_path / "src/request.py"), "provenance": "trusted_request"},),
        project_context=project_context,
    )

    assert saved_query == {
        "purpose": "repository_search",
        "scope": "task",
        "repository_revision": "rev-7",
    }
    assert request.settings_digest == project_digest
    assert request.session_id == "session-7"
    assert [hint["path"] for hint in request.path_hints] == [
        "docs/pinned.md",
        "src/main.py",
        "src/request.py",
        "src/saved.py",
    ]
    assert request.path_hints[0]["provenance"] == "project_config:pinned_context"
    assert request.path_hints[1]["provenance"] == "project_config:entry_point"
    assert request.path_hints[-1]["evidence_id"] == "evidence-7"
    assert all(hint.get("evidence_id") != "evidence-stale" for hint in request.path_hints)
    assert all(hint.get("evidence_id") != "evidence-expired" for hint in request.path_hints)
    assert all(
        hint.get("evidence_id") != "evidence-malformed-expiry"
        for hint in request.path_hints
    )
    assert all(hint["path"] != "payload/untrusted.py" for hint in request.path_hints)

    worktree_settings = SimpleNamespace(
        pinned_context=("docs/worktree.md",),
        entry_points=("src/worktree_main.py",),
    )
    for relative in (*worktree_settings.pinned_context, *worktree_settings.entry_points):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("worktree", encoding="utf-8")
    worktree_context = SimpleNamespace(
        root=tmp_path,
        settings=worktree_settings,
        config_digest="b" * 32,
        path_hints=lambda **kwargs: (),
    )
    worktree_request = build_context_request(
        {"task_id": "task-7", "root": str(tmp_path), "repo_revision": "rev-7"},
        project_context=worktree_context,
    )
    compiler = ContextCompiler(AgentStateStore(tmp_path / "compiler.sqlite3"))
    assert compiler.compile(request).etag() != compiler.compile(worktree_request).etag()

    other_root = tmp_path / "other-root"
    other_root.mkdir()
    mismatched_context = SimpleNamespace(
        root=other_root,
        settings=worktree_settings,
        config_digest="c" * 32,
        path_hints=lambda **kwargs: (),
    )
    with pytest.raises(ValueError, match="does not match request root"):
        build_context_request(
            {"task_id": "task-7", "root": str(tmp_path)},
            project_context=mismatched_context,
        )

    escaping_hint = SimpleNamespace(
        path=str(tmp_path.parent / "outside.md"),
        purpose="repository_search",
        scope="task",
        evidence_id="evidence-outside",
        provenance="verified_search",
        repository_revision="rev-7",
        config_digest=project_digest,
        expires_at="2026-09-29T00:00:00Z",
    )
    escaping_context = SimpleNamespace(
        root=tmp_path,
        settings=project_settings,
        config_digest=project_digest,
        path_hints=lambda **kwargs: (escaping_hint,),
    )
    with pytest.raises(ValueError, match="escapes root"):
        build_context_request(
            {"task_id": "task-7", "root": str(tmp_path), "repo_revision": "rev-7"},
            trusted_path_hints=({"path": str(tmp_path.parent / "outside-request.py")},),
            project_context=escaping_context,
        )
