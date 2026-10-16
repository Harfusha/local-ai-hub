from concurrent.futures import ThreadPoolExecutor

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore


def record(memory, root, text, *, tenant="tenant-a", kind=MemoryKind.FACT, task_id=""):
    return memory.record(MemoryRecord.create(
        kind=kind, scope=AgentScope.TASK if task_id else AgentScope.REPOSITORY,
        scope_id=task_id or str(root), key=text, value=text,
        status=MemoryStatus.CONFIRMED, source="user",
        provenance={"root": str(root), "tenant": tenant, "repository_id": str(root)},
    ), actor="user")


def store(tmp_path):
    return MemoryStore(AgentStateStore(tmp_path / "state.sqlite3"))


def test_repository_memory_requires_explicit_current_repository_identity(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    wanted = record(memory, root, "Renderer cache layout")
    assert memory.find_for_context(root=str(root), tenant="tenant-a") == []
    assert memory.find_for_context(
        root=str(root), coordination_id="different-repository", tenant="tenant-a"
    ) == []
    assert [item.record_id for item in memory.find_for_context(
        root=str(root), coordination_id=str(root), tenant="tenant-a"
    )] == [wanted.record_id]


def test_goal_selection_finds_older_relevant_memory_before_recent_limit(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    relevant = record(memory, root, "Renderer cache invalidation depends on the theme revision")
    for number in range(25):
        record(memory, root, f"Database backup shard number {number}")
    with memory.task_retrieval_scope("Fix renderer theme cache invalidation", root=str(root), tenant="tenant-a", task_id="task-a"):
        found = memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id="task-a")
    assert [item.record_id for item in found] == [relevant.record_id]
    assert len(memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a")) == 20


def test_goal_specific_fact_is_not_displaced_by_general_project_rules(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    wanted = record(memory, root, "Renderer cache invalidation uses the theme revision")
    for number in range(25):
        record(memory, root, f"Keep generated file group {number} read-only", kind=MemoryKind.CONVENTION)
    with memory.task_retrieval_scope("Fix renderer theme cache", root=str(root), tenant="tenant-a", task_id="task-a"):
        found = memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id="task-a")
    assert found[0].record_id == wanted.record_id


def test_goal_selection_has_no_unrelated_noise_but_preserves_project_rules_and_task_state(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    record(memory, root, "Database backups run on Mondays")
    with memory.task_retrieval_scope("Fix renderer theme", root=str(root), tenant="tenant-a", task_id="task-a"):
        assert memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id="task-a") == []
    rule = record(memory, root, "Always keep generated files read-only", kind=MemoryKind.CONVENTION)
    state = record(memory, root, "Previous attempt stopped at review", task_id="task-a")
    with memory.task_retrieval_scope("Fix renderer theme", root=str(root), tenant="tenant-a", task_id="task-a"):
        found = memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id="task-a")
    assert {item.record_id for item in found} == {rule.record_id, state.record_id}


def test_goal_selection_keeps_unicode_and_tenant_repository_isolation(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    wanted = record(memory, root, "Tlačítko používá předlohu nabídky")
    record(memory, root, "Tlačítko používá cizí předlohu", tenant="tenant-b")
    record(memory, tmp_path / "foreign", "Tlačítko používá jiný projekt")
    with memory.task_retrieval_scope("Oprav TLAČÍTKO předlohu", root=str(root), tenant="tenant-a", task_id="task-a"):
        found = memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id="task-a")
    assert [item.record_id for item in found] == [wanted.record_id]


def test_goal_selection_does_not_miss_relevant_terms_after_a_long_preamble(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    wanted = record(memory, root, " ".join(["background"] * 40) + " renderer cache invalidation")
    with memory.task_retrieval_scope("Fix renderer cache", root=str(root), tenant="tenant-a", task_id="task-a"):
        found = memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id="task-a")
    assert [item.record_id for item in found] == [wanted.record_id]


def test_goal_selection_is_request_local_and_restores_after_exception(tmp_path):
    memory = store(tmp_path)
    root = tmp_path / "repo"
    renderer = record(memory, root, "Renderer cache layout")
    database = record(memory, root, "Database backup layout")

    def lookup(goal, task_id):
        with memory.task_retrieval_scope(goal, root=str(root), tenant="tenant-a", task_id=task_id):
            return [item.record_id for item in memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a", task_id=task_id)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lookup, "Fix renderer cache", "task-a")
        second = pool.submit(lookup, "Fix database backup", "task-b")
        assert first.result(timeout=5) == [renderer.record_id]
        assert second.result(timeout=5) == [database.record_id]
    try:
        with memory.task_retrieval_scope("renderer", root=str(root), tenant="tenant-a", task_id="task-a"):
            raise ValueError("abort request")
    except ValueError:
        pass
    assert {item.record_id for item in memory.find_for_context(root=str(root), coordination_id=str(root), tenant="tenant-a")} == {renderer.record_id, database.record_id}
