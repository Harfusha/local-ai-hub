from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.agent_context import (
    CompiledContext,
    ContextCompiler,
    ContextElement,
    ContextRequest,
    KnowledgeLink,
)
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.agent_verification import VerificationReceipt, VerificationStore


@pytest.fixture
def compiler(tmp_path: Path) -> ContextCompiler:
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    task_store = TaskStore(state_store)
    verif_store = VerificationStore(state_store, task_store=task_store)

    task_store.create(
        GoalContract(goal="Compile feature", acceptance_criteria=("tests",)),
        ScopeContext(task_id="task-1"),
        task_id="task-1",
    )
    verif_store.record(
        VerificationReceipt.create(
            task_id="task-1",
            criterion="tests",
            passed=True,
            details={"output": "all passed"},
        )
    )

    comp = ContextCompiler(
        state_store=state_store,
        task_store=task_store,
        verification_store=verif_store,
    )
    comp.link(
        source_id="rec-1",
        target_id="src/changed.py",
        relationship="modifies",
        path="src/changed.py",
    )
    comp.link(
        source_id="rec-2",
        target_id="src/other.py",
        relationship="modifies",
        path="src/other.py",
    )
    return comp


def test_compiler_prefers_fresh_task_evidence_within_budget(compiler: ContextCompiler):
    result = compiler.compile(ContextRequest(task_id="task-1", token_budget=80))
    assert result.estimated_tokens <= 80
    assert len(result.elements) > 0
    assert result.elements[0].source_kind == "verification_receipt"


def test_context_request_accepts_phase_focus_and_preload_profile():
    request = ContextRequest(
        task_id="task-1",
        phase="edit",
        focus=("exact symbols", "reuse candidates"),
        preload_profile="python",
        repo_revision="rev-1",
        since_hash="etag-1",
        include_diagnostics=True,
        tenant="tenant-1",
    )

    assert request.phase == "edit"
    assert request.focus == ("exact symbols", "reuse candidates")
    assert request.preload_profile == "python"
    assert request.repo_revision == "rev-1"
    assert request.since_hash == "etag-1"
    assert request.include_diagnostics is True
    assert request.tenant == "tenant-1"


def test_preloads_are_bounded_and_deduplicated(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    first = tmp_path / "README.md"
    duplicate = tmp_path / "docs.md"
    first.write_text("same preload", encoding="utf-8")
    duplicate.write_text("same preload", encoding="utf-8")
    compiler = ContextCompiler(
        state_store,
        config={
            "context": {
                "preloads": {
                    "files": ["README.md", "docs.md", "missing.md"],
                    "max_files": 3,
                    "max_bytes": 100,
                }
            }
        },
    )

    result = compiler.compile(ContextRequest(task_id="task-1", root=str(tmp_path), preload_profile="default"))
    preloads = [element for element in result.elements if element.source_kind == "preload"]

    assert len(preloads) == 1
    assert preloads[0].content == "same preload"
    assert preloads[0].provenance["evidence_ids"]
    assert any(warning["code"] == "preload_missing_file" for warning in result.warnings)


def test_phase_pack_prioritizes_reuse_for_edit(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite3")
    memory_store = MemoryStore(state_store)
    memory_store.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope="task",
        scope_id="task-1",
        key="broad fact",
        value="broad context",
    ))
    memory_store.record(MemoryRecord.create(
        kind=MemoryKind.REUSABLE_CANDIDATE,
        scope="task",
        scope_id="task-1",
        key="reuse candidate",
        value="use this exact implementation",
        symbol_refs=("module.fn",),
    ))
    compiler = ContextCompiler(state_store, memory_store=memory_store)

    result = compiler.compile(ContextRequest(task_id="task-1", phase="edit", token_budget=80))

    assert result.phase == "edit"
    assert result.elements[0].content.startswith("[REUSABLE_CANDIDATE]")


def test_delta_pack_returns_unchanged_etag(tmp_path: Path):
    compiler = ContextCompiler(AgentStateStore(tmp_path / "state.sqlite3"))
    request = ContextRequest(task_id="task-1", phase="review")
    original = compiler.compile(request)

    unchanged = compiler.compile(ContextRequest(task_id="task-1", phase="review", since_hash=original.etag()))

    assert unchanged.unchanged is True
    assert unchanged.delta_from == original.etag()
    assert unchanged.elements == []


def test_disabled_agent_state_returns_stateless_repo_context_warning(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "state.sqlite3", enabled=False)
    compiler = ContextCompiler(state_store)

    result = compiler.compile(ContextRequest(
        task_id="task-1",
        root=str(tmp_path),
        changed_paths=("src/app.py",),
        phase="review",
    ))

    assert any(warning["code"] == "agent_state_disabled" for warning in result.warnings)
    assert any(element.source_kind == "repository_context" for element in result.elements)


def test_change_invalidates_only_linked_records(compiler: ContextCompiler):
    invalidated_count = compiler.invalidate({"src/changed.py"}, "rev-2")
    assert invalidated_count == 1
    # Check that other link remains valid
    active_links = compiler.get_active_links("src/other.py")
    assert len(active_links) == 1
    assert compiler.get_active_links("src/changed.py") == []


def test_context_compile_marks_changed_repository_memory_stale(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    stale_candidate = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="compile-stale",
            value="old evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": str(tmp_path), "repository_revision": "rev-1", "path_refs": ["src/a.py"]},
        )
    )
    unrelated = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="compile-unrelated",
            value="keep evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": str(tmp_path / "other"), "repository_revision": "rev-1", "path_refs": ["src/a.py"]},
        )
    )
    compiler = ContextCompiler(state_store=state_store, memory_store=memory_store)

    request = ContextRequest(
        task_id="task-1",
        root=str(tmp_path),
        repository_revision="rev-2",
        changed_paths=("src/a.py",),
        token_budget=120,
    )
    compiler.compile(request)
    compiler.compile(request)

    assert memory_store.get(stale_candidate.record_id).status is MemoryStatus.STALE
    assert memory_store.get(unrelated.record_id).status is MemoryStatus.CONFIRMED
    assert [event.kind for event in state_store.events(
        stream_id=f"memory:{stale_candidate.scope.value}:compile-stale"
    )].count("memory.staled") == 1


def test_context_compile_caps_normalized_changed_paths_with_diagnostic(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    compiler = ContextCompiler(state_store=state_store)
    for index in range(40):
        compiler.link(
            source_id=f"rec-{index}",
            target_id=f"src/{index}.py",
            relationship="modifies",
            path=f"src/{index}.py",
        )
    changed_paths = tuple(["src/0.py", "src/0.py"] + [f"src/{index}.py" for index in range(1, 40)])

    context = compiler.compile(ContextRequest(
        task_id="task-1",
        root=str(tmp_path),
        changed_paths=changed_paths,
        include_diagnostics=True,
        token_budget=300,
    ))

    assert compiler.get_active_links("src/0.py") == []
    assert compiler.get_active_links("src/31.py") == []
    assert compiler.get_active_links("src/32.py")
    diagnostics = [element for element in context.elements if element.source_kind == "context_diagnostics"]
    assert diagnostics
    assert "changed_paths_truncated=true" in diagnostics[0].content


def test_stale_memory_is_excluded_from_authoritative_context(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    stale = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="stale-finding",
            value="old evidence",
            status=MemoryStatus.STALE,
            provenance={"root": str(tmp_path), "repository_revision": "rev-1", "path_refs": ["src/a.py"]},
        )
    )
    fresh = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="fresh-finding",
            value="current evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": str(tmp_path), "repository_revision": "rev-2", "path_refs": ["src/b.py"]},
        )
    )

    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", root=str(tmp_path), token_budget=120)
    )

    assert stale.record_id not in {element.element_id for element in context.elements}
    assert fresh.record_id in {element.element_id for element in context.elements}
    fresh_element = next(element for element in context.elements if element.element_id == fresh.record_id)
    assert fresh_element.to_dict()["provenance"]["repository_revision"] == "rev-2"


def test_stale_memory_remains_visible_as_diagnostic(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    stale = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="stale-finding",
            value="old evidence",
            status=MemoryStatus.STALE,
            provenance={"root": str(tmp_path), "repository_revision": "rev-1", "path_refs": ["src/a.py"]},
        )
    )

    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", root=str(tmp_path), token_budget=120, include_diagnostics=True)
    )

    diagnostics = [element for element in context.elements if element.source_kind == "memory_diagnostics"]
    assert len(diagnostics) == 1
    assert stale.record_id in diagnostics[0].content


def test_memory_diagnostics_are_repository_scoped(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    repository_a = str(tmp_path / "repository-a")
    repository_b = str(tmp_path / "repository-b")
    stale_a = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="stale-a",
            value="old evidence A",
            status=MemoryStatus.STALE,
            provenance={"root": repository_a, "repository_revision": "rev-1"},
        )
    )
    stale_b = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="stale-b",
            value="old evidence B",
            status=MemoryStatus.STALE,
            provenance={"root": repository_b, "repository_revision": "rev-1"},
        )
    )

    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-a", root=repository_a, token_budget=120, include_diagnostics=True)
    )

    diagnostics = next(element for element in context.elements if element.source_kind == "memory_diagnostics")
    assert stale_a.record_id in diagnostics.content
    assert stale_b.record_id not in diagnostics.content
    assert "stale_count=1" in diagnostics.content


def test_legacy_rootless_memory_is_only_authoritative_without_root(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    concrete_root = str(tmp_path / "repository")
    legacy = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="legacy-rootless",
            value="legacy evidence",
            status=MemoryStatus.CONFIRMED,
            provenance={},
        )
    )

    rootless_context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", token_budget=120)
    )
    assert legacy.record_id in {element.element_id for element in rootless_context.elements}

    scoped_context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", root=concrete_root, token_budget=120, include_diagnostics=True)
    )
    scoped_ids = {element.element_id for element in scoped_context.elements}
    diagnostics = next(element for element in scoped_context.elements if element.source_kind == "memory_diagnostics")
    assert legacy.record_id not in scoped_ids
    assert legacy.record_id in diagnostics.content
    assert "legacy_unscoped_count=1" in diagnostics.content


def test_repository_root_aliases_match_context_scope(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    canonical_root = str(tmp_path / "repository")
    aliased_root = str(tmp_path / "repository" / "child" / "..")
    record = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="aliased-root",
            value="same repository",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": aliased_root},
        )
    )

    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", root=canonical_root, token_budget=120)
    )
    assert record.record_id in {element.element_id for element in context.elements}


def test_unsupported_memory_scopes_require_matching_request_identity(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    records = [
        memory_store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=scope,
                scope_id=scope_id,
                key=f"{scope}-memory",
                value="scoped evidence",
                status=MemoryStatus.CONFIRMED,
            )
        )
        for scope, scope_id in (("clone", "clone-a"), ("worktree", "worktree-a"), ("branch", "branch-a"))
    ]

    unavailable = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", token_budget=200)
    )
    unavailable_ids = {element.element_id for element in unavailable.elements}
    assert unavailable_ids.isdisjoint({record.record_id for record in records})

    matched = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(
            task_id="task-1",
            token_budget=200,
            clone_id="clone-a",
            worktree_id="worktree-a",
            branch="branch-a",
        )
    )
    matched_ids = {element.element_id for element in matched.elements}
    assert {record.record_id for record in records} <= matched_ids


def test_context_filters_before_candidate_limit_with_many_excluded_records(tmp_path: Path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    current_root = str(tmp_path / "current")
    other_root = str(tmp_path / "other")
    for index in range(25):
        memory_store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope="repository",
                key=f"other-{index}",
                value="excluded",
                status=MemoryStatus.CONFIRMED,
                provenance={"root": other_root},
            )
        )
    current = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="current",
            value="authoritative",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": current_root},
        )
    )

    def fail_unbounded_find(*args, **kwargs):
        raise AssertionError("context must use bounded SQL-filtered memory lookup")

    monkeypatch.setattr(memory_store, "find", fail_unbounded_find)
    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", root=current_root, token_budget=120)
    )
    assert current.record_id in {element.element_id for element in context.elements}


def test_context_drops_unsafe_memory_store_fallback(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")

    class LegacyMemoryStore:
        def find(self, *args, **kwargs):
            raise AssertionError("unsafe pre-filter memory fallback must not run")

    context = ContextCompiler(
        state_store=state_store,
        memory_store=LegacyMemoryStore(),
    ).compile(ContextRequest(task_id="task-1", root=str(tmp_path), token_budget=120))

    assert not any(element.source_kind == "memory_record" for element in context.elements)


def test_memory_diagnostics_aggregate_beyond_context_candidate_limit(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    expected_counts = {
        MemoryStatus.STALE: 25,
        MemoryStatus.QUARANTINED: 21,
        MemoryStatus.REJECTED: 22,
        MemoryStatus.SUPERSEDED: 23,
    }
    for status, count in expected_counts.items():
        for index in range(count):
            memory_store.record(
                MemoryRecord.create(
                    kind=MemoryKind.FINDING,
                    scope="repository",
                    key=f"{status.value}-{index}",
                    value="excluded",
                    status=status,
                    provenance={"root": str(tmp_path), "repository_revision": "rev-1", "path_refs": [f"src/{index}.py"]},
                )
            )

    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", root=str(tmp_path), token_budget=300, include_diagnostics=True)
    )

    diagnostics = next(element for element in context.elements if element.source_kind == "memory_diagnostics")
    assert "stale_count=25" in diagnostics.content
    assert "quarantined_count=21" in diagnostics.content
    assert "rejected_count=22" in diagnostics.content
    assert "superseded_count=23" in diagnostics.content
    for status in expected_counts:
        ids = diagnostics.content.split(f"{status.value}_ids=", 1)[1].split(" ", 1)[0]
        assert len([item for item in ids.split(",") if item]) <= 8


def test_authoritative_memory_is_root_and_task_session_scoped(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    memory_store = MemoryStore(state_store)
    current_root = str(tmp_path / "current")
    other_root = str(tmp_path / "other")

    current_repository = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="current-repository",
            value="keep",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": current_root, "repository_revision": "rev-1", "path_refs": ["src/current.py"]},
        )
    )
    for index in range(25):
        memory_store.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope="repository",
                key=f"excluded-{index}",
                value="exclude",
                status=MemoryStatus.STALE,
                provenance={"root": current_root, "repository_revision": "rev-1", "path_refs": [f"src/{index}.py"]},
            )
        )
    wrong_root = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="repository",
            key="wrong-root",
            value="exclude",
            status=MemoryStatus.CONFIRMED,
            provenance={"root": other_root, "repository_revision": "rev-1", "path_refs": ["src/wrong.py"]},
        )
    )
    current_task = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="task",
            scope_id="task-1",
            key="current-task",
            value="keep",
            status=MemoryStatus.CONFIRMED,
        )
    )
    wrong_task = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="task",
            scope_id="task-2",
            key="wrong-task",
            value="exclude",
            status=MemoryStatus.CONFIRMED,
        )
    )
    current_session = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="session",
            scope_id="session-1",
            key="current-session",
            value="keep",
            status=MemoryStatus.CONFIRMED,
        )
    )
    wrong_session = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="session",
            scope_id="session-2",
            key="wrong-session",
            value="exclude",
            status=MemoryStatus.CONFIRMED,
        )
    )
    unscoped_task = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="task",
            key="unscoped-task",
            value="exclude",
            status=MemoryStatus.CONFIRMED,
        )
    )
    unscoped_session = memory_store.record(
        MemoryRecord.create(
            kind=MemoryKind.FINDING,
            scope="session",
            key="unscoped-session",
            value="exclude",
            status=MemoryStatus.CONFIRMED,
        )
    )

    context = ContextCompiler(state_store=state_store, memory_store=memory_store).compile(
        ContextRequest(task_id="task-1", tenant="session-1", root=current_root, token_budget=300)
    )
    element_ids = {element.element_id for element in context.elements}

    assert current_repository.record_id in element_ids
    assert current_task.record_id in element_ids
    assert current_session.record_id in element_ids
    assert wrong_root.record_id not in element_ids
    assert wrong_task.record_id not in element_ids
    assert wrong_session.record_id not in element_ids
    assert unscoped_task.record_id not in element_ids
    assert unscoped_session.record_id not in element_ids
