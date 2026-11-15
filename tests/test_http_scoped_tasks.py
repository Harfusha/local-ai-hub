"""Repository-scoped task pagination must filter before counting the page."""
from __future__ import annotations

from dataclasses import dataclass

from local_ai_hub.http_scoped_tasks import page_scoped_tasks


@dataclass
class Task:
    root: str
    name: str


class Store:
    def __init__(self, tasks):
        self.tasks = tasks

    def list_tasks(self, *, status, limit, offset, include_stale, query):
        return self.tasks[offset:offset + limit]


def page(store, root, limit, offset, **kwargs):
    return page_scoped_tasks(
        store.list_tasks, lambda task: task.root == root, status=None,
        limit=limit, offset=offset, include_stale=False, query="",
        **kwargs,
    )


def test_root_is_filtered_before_pagination_and_offset():
    tasks = [Task("other", str(i)) for i in range(30)] + [
        Task("target", str(i)) for i in range(13)
    ]
    store = Store(tasks)
    a = page(store, "target", 5, 0)
    b = page(store, "target", 5, a["next_offset"])
    c = page(store, "target", 5, b["next_offset"])
    assert [item.name for item in a["tasks"]] == [str(i) for i in range(5)]
    assert [item.name for item in b["tasks"]] == [str(i) for i in range(5, 10)]
    assert [item.name for item in c["tasks"]] == [str(i) for i in range(10, 13)]
    assert a["has_more"] and b["has_more"]
    assert c["has_more"] is False
    assert c["incomplete"] is False


def test_scoped_scan_budget_never_reports_an_unchecked_empty_page_as_complete():
    store = Store([Task("other", str(i)) for i in range(20)] + [Task("target", "found")])
    result = page(store, "target", 5, 0, max_scan=10, chunk_size=5)
    assert result["tasks"] == []
    assert result["has_more"] is True
    assert result["incomplete"] is True


def test_unavailable_root_can_finish_with_complete_empty_page():
    store = Store([Task("other", "one")])
    result = page(store, "target", 5, 0)
    assert result["tasks"] == []
    assert result["has_more"] is False
    assert result["incomplete"] is False
    assert result["total_count"] == 0
