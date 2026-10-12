from __future__ import annotations

import contextvars
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from local_ai_hub import project_config, trace_context
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_memory import MemoryStatus
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_context import ContextCompiler
from local_ai_hub.agent_tasks import GoalContract, TaskStore
from local_ai_hub.token_accounting import json_tokens


guard_state = contextvars.ContextVar("test_snapshot_guard", default=None)


class Memory:
    def __init__(self, root):
        self.records = [SimpleNamespace(
            record_id="memory-1", status=MemoryStatus.CONFIRMED,
            scope=AgentScope.REPOSITORY, scope_id=str(root), expires_at=None,
            sensitivity="normal", source="user", confidence=1.0,
            created_at=1.0, updated_at=2.0, evidence_ids=(),
            provenance={"root": str(root), "tenant": "tenant-a", "version": "v1"},
        )]
        self.observed = []

    @contextmanager
    def task_retrieval_scope(self, goal, *, root, tenant, task_id):
        assert guard_state.get() is None
        token = guard_state.set((goal, root, tenant, task_id))
        try:
            yield
        finally:
            guard_state.reset(token)

    def observe(self, stage):
        self.observed.append((stage, guard_state.get(), trace_context.current().get("tenant"), threading.current_thread()))

    def diagnostic_summary(self, **kwargs):
        self.observe("diagnostics")
        return {}

    def find(self, **kwargs):
        self.observe("find")
        return []

    def find_for_context(self, **kwargs):
        self.observe("second_find")
        return self.records

    def task_relevance_score(self, record, goal, *, task_id):
        self.observe("ranking")
        return 1


class Compiler:
    def __init__(self, memory, content="verified useful fact"):
        self.memory = memory
        self.content = content

    def compile(self, request):
        self.memory.observe("compile")
        return SimpleNamespace(elements=tuple(
            SimpleNamespace(source_kind="memory_record", element_id=record.record_id, content=self.content)
            for record in self.memory.records
        ), warnings=())


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    tasks = TaskStore(AgentStateStore(tmp_path / "state.sqlite3"))
    memory = Memory(root)
    compiler = Compiler(memory)
    incidents = SimpleNamespace(find_negative_knowledge=lambda *args, **kwargs: [])
    tasks.set_memory_adoption(memory_store=memory, context_compiler=compiler, incident_store=incidents)
    monkeypatch.setattr(project_config, "resolve_project_context", lambda *args: SimpleNamespace(coordination_id=""))
    context = ScopeContext(repository_id=str(root), task_id="snapshot-task", session_id="session-a", branch="main")
    return tasks, memory, compiler, incidents, root, context


def lookup(setup, *, previous=None):
    tasks, _, _, _, root, context = setup
    token = trace_context.set_context(tenant="tenant-a")
    try:
        return tasks._task_memory_context("snapshot-task", GoalContract(goal="use verified fact"), context, root_override=str(root), previous=previous)
    finally:
        trace_context.reset_context(token)


@pytest.mark.parametrize("stage", ["resolve", "compile", "diagnostics", "find", "second_find", "ranking", "negative"])
def test_deadline_bounds_real_blocking_backend_at_every_lookup_stage(setup, monkeypatch, stage):
    tasks, memory, compiler, incidents, _, _ = setup
    entered, release = threading.Event(), threading.Event()
    targets = {
        "resolve": (project_config, "resolve_project_context"),
        "compile": (compiler, "compile"),
        "diagnostics": (memory, "diagnostic_summary"),
        "find": (memory, "find"),
        "second_find": (memory, "find_for_context"),
        "ranking": (memory, "task_relevance_score"),
        "negative": (incidents, "find_negative_knowledge"),
    }
    target, name = targets[stage]
    original = getattr(target, name)

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(3)  # Baseline remains bounded while proving its sync wait.
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, blocked)
    try:
        started = time.perf_counter()
        snapshot = lookup(setup)
        elapsed = time.perf_counter() - started
        assert entered.is_set()
        assert elapsed < 1.2  # 1s deadline plus scheduling tolerance.
        assert snapshot["items"] == []
        assert snapshot["warnings"] == [{"code": "memory_lookup_deadline_exceeded"}]
        assert json_tokens(snapshot) <= 512
        assert snapshot["estimated_tokens"] == json_tokens(snapshot)
    finally:
        release.set()


def test_concurrent_never_returning_backend_has_bounded_admission_and_daemon_worker(setup, monkeypatch):
    _, memory, compiler, _, _, _ = setup
    entered, release = threading.Event(), threading.Event()
    workers = []

    def blocked(request):
        workers.append(threading.current_thread())
        entered.set()
        release.wait()
        return SimpleNamespace(elements=(), warnings=())

    monkeypatch.setattr(compiler, "compile", blocked)
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        first = pool.submit(lookup, setup)
        assert entered.wait(1)
        others = [pool.submit(lookup, setup) for _ in range(7)]
        first_snapshot = first.result(timeout=1.3)
        snapshots = [future.result(timeout=0.3) for future in others]
        assert len(workers) == 1
        assert workers[0].daemon
        assert first_snapshot["warnings"] == [{"code": "memory_lookup_deadline_exceeded"}]
        assert all(snapshot["warnings"] == [{"code": "memory_lookup_busy"}] for snapshot in snapshots)
        assert all(json_tokens(snapshot) <= 512 for snapshot in [first_snapshot, *snapshots])
        assert all(snapshot["estimated_tokens"] == json_tokens(snapshot) for snapshot in [first_snapshot, *snapshots])
    finally:
        release.set()
        pool.shutdown(wait=True)


def test_relevance_guard_and_trace_context_cover_all_steps_and_reset_between_requests(setup):
    _, memory, _, _, root, context = setup
    before = asdict(context)
    snapshots = [lookup(setup), lookup(setup)]
    assert all(snapshot["items"][0]["id"] == "memory-1" for snapshot in snapshots)
    expected = ("use verified fact", str(root), "tenant-a", "snapshot-task")
    assert {entry[0] for entry in memory.observed} >= {"compile", "diagnostics", "find", "second_find"}
    assert all(entry[1] == expected and entry[2] == "tenant-a" for entry in memory.observed)
    assert len({entry[3].ident for entry in memory.observed}) == 1
    assert all(entry[3].daemon for entry in memory.observed)
    assert guard_state.get() is None
    assert asdict(context) == before
    mismatch = lookup(setup, previous={"tenant_key": "other-tenant"})
    assert mismatch["items"] == []
    assert mismatch["warnings"] == [{"code": "memory_tenant_mismatch"}]


def test_metadata_heavy_snapshot_budget_counts_entire_serialized_envelope(setup):
    _, memory, compiler, _, _, _ = setup
    record = memory.records[0]
    record.record_id = "memory-" + "a" * 32
    record.evidence_ids = tuple("ev_" + hashlib.sha256(str(index).encode()).hexdigest() for index in range(8))
    record.provenance["version"] = "version-" + "b" * 64
    record.provenance["repository_revision"] = "c" * 64
    compiler.content = "verified useful fact " * 500
    snapshot = lookup(setup)
    assert json_tokens(snapshot) <= 512
    assert snapshot["items"]
    item = snapshot["items"][0]
    assert item["id"] == record.record_id
    assert item["scope_id"] == record.scope_id
    assert item["version"] == record.provenance["version"]
    assert item["provenance"]["evidence_ids"] == list(record.evidence_ids)
    assert item["provenance"]["repository_revision"] == "c" * 64
    assert item["validity"]["expires_at"] is None
    assert snapshot["estimated_tokens"] == json_tokens(snapshot)


def test_negative_knowledge_preserves_version_expiry_and_skips_invalid_expired(setup):
    _, memory, _, incidents, _, _ = setup
    memory.records = []
    expiry = time.time() + 600
    base = {"verified_fix": "confirmed reusable recovery", "error_class": "failure", "state_revision": "rev-7", "updated_at": 2.0, "confidence": 1.0, "provenance": {"repository_key": "r", "tenant_key": "t"}}
    incidents.find_negative_knowledge = lambda *args, **kwargs: [
        {**base, "incident_id": "fresh", "expires_at": expiry},
        {**base, "incident_id": "expired", "expires_at": time.time() - 1},
        {**base, "incident_id": "invalid", "expires_at": "broken"},
    ]
    snapshot = lookup(setup)
    assert [item["id"] for item in snapshot["items"]] == ["fresh"]
    assert snapshot["items"][0]["version"] == "rev-7"
    assert snapshot["items"][0]["validity"]["expires_at"] == expiry
    assert json_tokens(snapshot) <= 512


def test_empty_relevant_snapshot_is_silent(setup):
    setup[1].records = []
    assert lookup(setup) is None
    assert lookup(setup, previous={"tenant_key": ""}) is None


def test_unavailable_snapshot_accounts_for_entire_warning_envelope(setup, monkeypatch):
    def unavailable(request):
        raise RuntimeError("private backend error detail")

    monkeypatch.setattr(setup[2], "compile", unavailable)
    snapshot = lookup(setup)
    assert snapshot["warnings"] == [{"code": "memory_context_unavailable"}]
    assert snapshot["estimated_tokens"] == json_tokens(snapshot)
    assert 0 < snapshot["estimated_tokens"] <= 512
    assert snapshot["instruction"] == ""
    assert "private backend error detail" not in repr(snapshot)


def test_task_creation_continues_when_real_backend_is_blocked(setup, monkeypatch):
    tasks, _, compiler, _, root, context = setup
    release = threading.Event()
    monkeypatch.setattr(compiler, "compile", lambda request: release.wait(3))
    token = trace_context.set_context(tenant="tenant-a")
    try:
        started = time.perf_counter()
        task = tasks.create(GoalContract(goal="use verified fact"), context, task_id="snapshot-task", repo_root=str(root))
        assert time.perf_counter() - started < 1.2
        assert task.task_id == "snapshot-task"
        assert task.checkpoint.state_data["memory_context"]["warnings"] == [{"code": "memory_lookup_deadline_exceeded"}]
    finally:
        release.set()
        trace_context.reset_context(token)


def test_deadline_covers_relevance_guard_entry_without_late_compile(setup, monkeypatch):
    _, memory, compiler, _, _, _ = setup
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls = []

    @contextmanager
    def blocked_guard(*args, **kwargs):
        entered.set()
        release.wait(3)
        try:
            yield
        finally:
            exited.set()

    monkeypatch.setattr(memory, "task_retrieval_scope", blocked_guard)
    monkeypatch.setattr(compiler, "compile", lambda request: calls.append(request))
    try:
        started = time.perf_counter()
        snapshot = lookup(setup)
        assert time.perf_counter() - started < 1.2
        assert entered.is_set()
        assert snapshot["warnings"] == [{"code": "memory_lookup_deadline_exceeded"}]
    finally:
        release.set()
    assert exited.wait(1)
    assert calls == []


def test_negative_expiry_uses_full_scoped_incident_when_finder_omits_it(setup):
    _, memory, _, incidents, _, _ = setup
    memory.records = []
    expiry = time.time() + 600
    incidents.find_negative_knowledge = lambda *args, **kwargs: [{
        "incident_id": "full-incident", "verified_fix": "verified fix", "state_revision": "rev-9",
        "provenance": {"repository_key": "r", "tenant_key": "t"},
    }]
    incidents.get = lambda record_id: SimpleNamespace(repository_key="r", tenant_key="t", expires_at=expiry)
    snapshot = lookup(setup)
    assert snapshot["items"][0]["version"] == "rev-9"
    assert snapshot["items"][0]["validity"]["expires_at"] == expiry


def test_real_create_and_resume_keep_older_goal_fact_ahead_of_general_conventions(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    state = AgentStateStore(tmp_path / "ranked-state.sqlite3")
    tasks = TaskStore(state)
    memory = MemoryStore(state)
    compiler = ContextCompiler(state, task_store=tasks, memory_store=memory)
    tasks.set_memory_adoption(memory_store=memory, context_compiler=compiler)
    wanted = memory.record(MemoryRecord.create(
        kind=MemoryKind.FACT, scope=AgentScope.REPOSITORY, scope_id=str(root),
        key="renderer theme cache invalidation", value="Renderer theme cache invalidation uses the theme revision",
        status=MemoryStatus.CONFIRMED, confidence=1.0, source="user",
        provenance={"root": str(root), "tenant": "tenant-a"},
    ), actor="user")
    for index in range(25):
        memory.record(MemoryRecord.create(
            kind=MemoryKind.CONVENTION, scope=AgentScope.REPOSITORY, scope_id=str(root),
            key=f"rule{index}", value="Keep files immutable", status=MemoryStatus.CONFIRMED,
            confidence=1.0, source="user", provenance={"root": str(root), "tenant": "tenant-a"},
        ), actor="user")
    compiled_ids = []
    compile_context = compiler.compile

    def observed_compile(request):
        result = compile_context(request)
        compiled_ids.append({element.element_id for element in result.elements if element.source_kind == "memory_record"})
        return result

    compiler.compile = observed_compile
    token = trace_context.set_context(tenant="tenant-a")
    try:
        task = tasks.create(
            GoalContract(goal="Fix renderer theme cache invalidation"),
            ScopeContext(repository_id=str(root), task_id="ranked-snapshot"),
            task_id="ranked-snapshot", repo_root=str(root),
        )
        assert wanted.record_id in compiled_ids[-1]
        created_snapshot = task.checkpoint.state_data["memory_context"]
        assert created_snapshot["items"][0]["id"] == wanted.record_id
        assert json_tokens(created_snapshot) <= 512
        resumed = tasks.resume(task.task_id, actor="user", idempotency_key="ranked-resume")
        assert wanted.record_id in compiled_ids[-1]
        snapshot = resumed.checkpoint.state_data["memory_context"]
        assert snapshot["items"][0]["id"] == wanted.record_id
        assert json_tokens(snapshot) <= 512
    finally:
        trace_context.reset_context(token)


def test_scorer_only_receives_scope_validated_compiled_records(setup, monkeypatch):
    _, memory, compiler, _, root, _ = setup
    valid = memory.records[0]
    foreign = SimpleNamespace(**{**vars(valid), "record_id": "foreign", "scope_id": str(root.parent / "foreign"), "provenance": {"root": str(root.parent / "foreign"), "tenant": "tenant-a"}})
    uncompiled = SimpleNamespace(**{**vars(valid), "record_id": "uncompiled"})
    memory.records = [valid, foreign, uncompiled]
    monkeypatch.setattr(compiler, "compile", lambda request: SimpleNamespace(elements=tuple(
        SimpleNamespace(source_kind="memory_record", element_id=record.record_id, content="verified useful fact")
        for record in (valid, foreign)
    ), warnings=()))
    scored = []

    def score(record, goal, *, task_id):
        scored.append(record.record_id)
        return 100

    monkeypatch.setattr(memory, "task_relevance_score", score)
    snapshot = lookup(setup)
    assert scored == [valid.record_id]
    assert [item["id"] for item in snapshot["items"]] == [valid.record_id]
