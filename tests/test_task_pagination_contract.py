from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import ScopeContext
from local_ai_hub.agent_tasks import GoalContract, TaskStore


def task_store(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    store = TaskStore(AgentStateStore(tmp_path / "tasks.sqlite", enabled=True))
    for task_id, goal in (("a", "needle alpha"), ("b", "other"), ("c", "needle charlie")):
        store.create(GoalContract(goal=goal), ScopeContext(repository_id="repository"),
                     task_id=task_id, actor="owner", repo_root=str(root))
    return store


def test_existing_positional_include_stale_and_query_keep_their_meaning(tmp_path):
    store = task_store(tmp_path)
    rows = store.list_tasks(None, 100, True, "needle")
    assert {row.task_id for row in rows} == {"a", "c"}


def test_offset_applies_after_search_filtering(tmp_path):
    store = task_store(tmp_path)
    expected = list(store.list_tasks(query="needle", include_stale=True))
    assert len(expected) == 2
    first = store.list_tasks(limit=1, offset=0, query="needle", include_stale=True)
    second = store.list_tasks(limit=1, offset=1, query="needle", include_stale=True)
    assert [row.task_id for row in first] == [expected[0].task_id]
    assert [row.task_id for row in second] == [expected[1].task_id]


def test_unfiltered_pages_are_disjoint_and_cover_the_full_order(tmp_path):
    store = task_store(tmp_path)
    full = list(store.list_tasks(include_stale=True))
    pages = [store.list_tasks(limit=1, offset=i, include_stale=True) for i in range(3)]
    actual = [row.task_id for page in pages for row in page]
    assert actual == [row.task_id for row in full]
    assert len(actual) == len(set(actual)) == 3
