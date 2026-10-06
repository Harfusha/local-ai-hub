from contextlib import closing
from dataclasses import replace
import threading
import time

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub import agent_memory as agent_memory_module
from local_ai_hub.agent_memory import AgentScope, MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStatus, TaskStore
from local_ai_hub.sqlite_support import connect_sqlite
from local_ai_hub.swarm import SwarmCoordinator


def _memory_stream_id(scope: AgentScope, scope_id: str, key: str) -> str:
    builder = getattr(agent_memory_module, "_memory_event_stream_id", None)
    if callable(builder):
        return builder(scope, scope_id, key)
    return f"memory:{scope.value}:{key}"


def test_concurrent_event_appends_publish_in_committed_sequence_order(tmp_path, monkeypatch):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    subscriber = state_store.subscribe()
    first_publish_entered = threading.Event()
    release_first_publish = threading.Event()
    second_append_started = threading.Event()
    second_lock_attempted = threading.Event()
    second_publish_entered = threading.Event()
    second_published_before_release = []
    publish = state_store._publish
    append_publish_lock = getattr(state_store, "_append_publish_lock", threading.Lock())
    second_thread = None

    class ObservedAppendPublishLock:
        def __enter__(self):
            if threading.current_thread() is second_thread:
                second_lock_attempted.set()
            append_publish_lock.acquire()

        def __exit__(self, *_args):
            append_publish_lock.release()

    monkeypatch.setattr(
        state_store,
        "_append_publish_lock",
        ObservedAppendPublishLock(),
        raising=False,
    )

    def delay_first_publish(event):
        if event.seq == 1:
            first_publish_entered.set()
            assert release_first_publish.wait(timeout=5)
        elif event.seq == 2:
            second_publish_entered.set()
            second_published_before_release.append(not release_first_publish.is_set())
        publish(event)

    monkeypatch.setattr(state_store, "_publish", delay_first_publish)
    first = AgentEvent.create("task:live-order", "task.updated", {"n": 1})
    second = AgentEvent.create("task:live-order", "task.updated", {"n": 2})
    errors = []

    def append(event, started=None):
        if started is not None:
            started.set()
        try:
            state_store.append(event)
        except BaseException as exc:
            errors.append(exc)

    first_thread = threading.Thread(target=append, args=(first,))
    first_thread.start()
    assert first_publish_entered.wait(timeout=5)
    second_thread = threading.Thread(target=append, args=(second, second_append_started))
    second_thread.start()
    assert second_append_started.wait(timeout=5)
    deadline = time.monotonic() + 5
    while not second_lock_attempted.is_set() and not second_publish_entered.is_set():
        if time.monotonic() >= deadline:
            break
        threading.Event().wait(0.001)
    second_lock_was_used = second_lock_attempted.is_set()
    release_first_publish.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert second_lock_was_used
    assert second_published_before_release == [False]
    assert [subscriber.get_nowait().seq, subscriber.get_nowait().seq] == [1, 2]


@pytest.mark.parametrize("task_writer", ["create", "update", "receipt"])
def test_task_event_commits_share_append_publish_order_lock(tmp_path, monkeypatch, task_writer):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)
    task_id = f"task-live-order-{task_writer}"
    stream_id = f"task:{task_id}"
    if task_writer in {"update", "receipt"}:
        tasks.create(
            GoalContract(goal="preserve event order"),
            ScopeContext(task_id=task_id),
            task_id=task_id,
        )
        first_seq = 2
    else:
        first_seq = 1

    subscriber = state_store.subscribe()
    first_publish_entered = threading.Event()
    release_first_publish = threading.Event()
    task_lock_attempted = threading.Event()
    task_publish_entered = threading.Event()
    task_published_before_release = []
    errors = []
    publish = state_store._publish
    append_publish_lock = state_store._append_publish_lock
    task_thread = None
    publication_calls = []
    ordered_publication = state_store.ordered_event_publication

    def track_ordered_publication(con):
        if threading.current_thread() is task_thread:
            publication_calls.append(True)
        return ordered_publication(con)

    monkeypatch.setattr(state_store, "ordered_event_publication", track_ordered_publication)

    class ObservedAppendPublishLock:
        def __enter__(self):
            if threading.current_thread() is task_thread:
                task_lock_attempted.set()
            append_publish_lock.acquire()

        def __exit__(self, *_args):
            append_publish_lock.release()

    monkeypatch.setattr(state_store, "_append_publish_lock", ObservedAppendPublishLock())

    def delay_first_publish(event):
        if event.seq == first_seq:
            first_publish_entered.set()
            assert release_first_publish.wait(timeout=5)
        elif event.seq == first_seq + 1:
            task_publish_entered.set()
            if not release_first_publish.is_set():
                task_published_before_release.append(event.seq)
        publish(event)

    monkeypatch.setattr(state_store, "_publish", delay_first_publish)
    first_event = AgentEvent.create(stream_id, "task.preexisting", {"n": first_seq})

    def append_first():
        try:
            state_store.append(first_event)
        except BaseException as exc:
            errors.append(exc)

    def write_task():
        try:
            if task_writer == "create":
                tasks.create(
                    GoalContract(goal="preserve event order"),
                    ScopeContext(task_id=task_id),
                    task_id=task_id,
                )
            elif task_writer == "update":
                tasks.transition(
                    task_id,
                    TaskStatus.ACTIVE,
                    reason="test order",
                    actor="test",
                    idempotency_key="task-live-order-update",
                )
            else:
                tasks.add_verification_receipt(task_id, "live-order", "receipt-1")
        except BaseException as exc:
            errors.append(exc)

    first_thread = threading.Thread(target=append_first)
    first_thread.start()
    assert first_publish_entered.wait(timeout=5)
    task_thread = threading.Thread(target=write_task)
    task_thread.start()
    deadline = time.monotonic() + 5
    while not task_lock_attempted.is_set() and not task_publish_entered.is_set():
        if time.monotonic() >= deadline:
            break
        threading.Event().wait(0.001)
    lock_was_used = task_lock_attempted.is_set()
    release_first_publish.set()
    first_thread.join(timeout=5)
    task_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not task_thread.is_alive()
    assert errors == []
    assert lock_was_used
    assert publication_calls == [True]
    assert task_published_before_release == []
    published = [subscriber.get_nowait(), subscriber.get_nowait()]
    assert [event.seq for event in published] == [first_seq, first_seq + 1]
    recovered = state_store.event_page(stream_id)
    assert recovered["last_seq"] == recovered["next_seq"] == first_seq + 1
    state_store.unsubscribe(subscriber)


def test_ordered_event_publication_serializes_caller_owned_batch(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    subscriber = state_store.subscribe()
    first_publish_entered = threading.Event()
    release_first_publish = threading.Event()
    second_lock_attempted = threading.Event()
    second_publish_entered = threading.Event()
    second_published_early = []
    errors = []
    publish = state_store._publish
    append_publish_lock = state_store._append_publish_lock
    second_thread = None

    class ObservedAppendPublishLock:
        def __enter__(self):
            if threading.current_thread() is second_thread:
                second_lock_attempted.set()
            append_publish_lock.acquire()

        def __exit__(self, *_args):
            append_publish_lock.release()

    monkeypatch.setattr(state_store, "_append_publish_lock", ObservedAppendPublishLock())

    def delay_first_publish(event):
        if event.seq == 1:
            first_publish_entered.set()
            assert release_first_publish.wait(timeout=5)
        elif event.seq == 2:
            second_publish_entered.set()
            if not release_first_publish.is_set():
                second_published_early.append(event.seq)
        publish(event)

    monkeypatch.setattr(state_store, "_publish", delay_first_publish)
    first_event = AgentEvent.create("task:ordered-batch", "task.first", {"n": 1})
    second_event = AgentEvent.create("task:ordered-batch", "task.second", {"n": 2})

    def append_first():
        try:
            state_store.append(first_event)
        except BaseException as exc:
            errors.append(exc)

    def append_second_in_caller_transaction():
        try:
            with closing(connect_sqlite(db_path, isolation_level=None)) as con:
                with state_store.ordered_event_publication(con) as publish_committed:
                    con.execute("BEGIN IMMEDIATE")
                    result = state_store.append_in_transaction(con, second_event)
                    con.execute("COMMIT")
                    publish_committed([result.event])
        except BaseException as exc:
            errors.append(exc)

    first_thread = threading.Thread(target=append_first)
    first_thread.start()
    assert first_publish_entered.wait(timeout=5)
    second_thread = threading.Thread(target=append_second_in_caller_transaction)
    second_thread.start()
    deadline = time.monotonic() + 5
    while (
        not second_lock_attempted.is_set()
        and not second_publish_entered.is_set()
        and not errors
    ):
        if time.monotonic() >= deadline:
            break
        threading.Event().wait(0.001)
    lock_was_used = second_lock_attempted.is_set()
    release_first_publish.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert lock_was_used
    assert second_publish_entered.is_set()
    assert second_published_early == []
    assert [subscriber.get_nowait().seq, subscriber.get_nowait().seq] == [1, 2]


@pytest.mark.parametrize("writer", ["memory", "blackboard", "swarm"])
def test_t08_store_writers_publish_same_stream_in_commit_order(tmp_path, monkeypatch, writer):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    if writer == "memory":
        memory = MemoryStore(state_store)
        stream_id = _memory_stream_id(AgentScope.REPOSITORY, "repo", "ordered")

        def write(value):
            memory.record(
                MemoryRecord.create(
                    kind=MemoryKind.FINDING,
                    scope=AgentScope.REPOSITORY,
                    scope_id="repo",
                    key="ordered",
                    value={"value": value},
                    evidence_ids=(f"evidence-{value}",),
                ),
                idempotency_key=f"ordered-{value}",
            )
    elif writer == "blackboard":
        board = BlackboardStore(db_path, state_store=state_store)
        stream_id = "blackboard:ordered:section"

        def write(value):
            return board.update("ordered", "section", {"value": value}, author="agent")
    else:
        coordinator = SwarmCoordinator(db_path, state_store=state_store)
        dispatched = coordinator.dispatch("ordered publication", root=str(tmp_path))
        assert dispatched["success"] is True
        stream_id = f"swarm:{dispatched['swarm_id']}"

        def write(value):
            if value == 1:
                return coordinator.step(
                    dispatched["swarm_id"], "Coder", "submit_patch", {"value": value}
                )
            return coordinator.step(
                dispatched["swarm_id"], "Tester", "submit_result", {"passed": True}
            )

    initial_seq = state_store.event_page(stream_id)["last_seq"]
    subscriber = state_store.subscribe()
    first_publish_entered = threading.Event()
    release_first_publish = threading.Event()
    second_started = threading.Event()
    second_lock_attempted = threading.Event()
    second_publish_entered = threading.Event()
    second_published_before_release = []
    publish = state_store._publish
    append_publish_lock = state_store._append_publish_lock
    second_thread = None

    class ObservedAppendPublishLock:
        def __enter__(self):
            if threading.current_thread() is second_thread:
                second_lock_attempted.set()
            append_publish_lock.acquire()

        def __exit__(self, *_args):
            append_publish_lock.release()

    monkeypatch.setattr(state_store, "_append_publish_lock", ObservedAppendPublishLock())

    def delay_first_publish(event):
        if event.stream_id == stream_id and event.seq == initial_seq + 1:
            first_publish_entered.set()
            assert release_first_publish.wait(timeout=5)
        elif event.stream_id == stream_id and event.seq > initial_seq + 1:
            second_publish_entered.set()
            if not release_first_publish.is_set():
                second_published_before_release.append(event.seq)
        publish(event)

    monkeypatch.setattr(state_store, "_publish", delay_first_publish)
    errors = []

    def run_write(value, started=None):
        if started is not None:
            started.set()
        try:
            result = write(value)
            if isinstance(result, dict) and result.get("success") is False:
                errors.append(result)
        except BaseException as exc:
            errors.append(exc)

    first_thread = threading.Thread(target=run_write, args=(1,))
    first_thread.start()
    assert first_publish_entered.wait(timeout=5)
    second_thread = threading.Thread(target=run_write, args=(2, second_started))
    second_thread.start()
    assert second_started.wait(timeout=5)
    deadline = time.monotonic() + 3
    while not second_lock_attempted.is_set() and not second_publish_entered.is_set():
        if time.monotonic() >= deadline:
            break
        threading.Event().wait(0.001)
    lock_was_attempted = second_lock_attempted.is_set()
    release_first_publish.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert lock_was_attempted
    assert second_published_before_release == []
    published = []
    while not subscriber.empty():
        event = subscriber.get_nowait()
        if event.stream_id == stream_id:
            published.append(event)
    seqs = [event.seq for event in published]
    assert seqs == sorted(seqs)
    assert len(seqs) >= 2
    state_store.unsubscribe(subscriber)

def test_ordered_event_publication_rejects_committed_row_content_mismatch(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    state_store._ensure_schema()
    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        result = state_store.append_in_transaction(
            con, AgentEvent.create("task:publication-row", "task.created", {"n": 1})
        )
        con.execute("COMMIT")
    subscriber = state_store.subscribe()
    forged = replace(result.event, payload={"n": 2})

    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        with state_store.ordered_event_publication(con) as publish_committed:
            with pytest.raises(RuntimeError, match="event is not committed"):
                publish_committed([forged])

    assert subscriber.empty()
    state_store.unsubscribe(subscriber)

@pytest.mark.parametrize("batch_kind", ("duplicate", "out_of_order"))
def test_ordered_event_publication_rejects_duplicate_or_out_of_order_batch(
    tmp_path, batch_kind
):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    state_store._ensure_schema()
    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        con.execute("BEGIN IMMEDIATE")
        first = state_store.append_in_transaction(
            con, AgentEvent.create("task:publication-validation", "task.one", {"n": 1})
        )
        second = state_store.append_in_transaction(
            con, AgentEvent.create("task:publication-validation", "task.two", {"n": 2})
        )
        con.execute("COMMIT")
    subscriber = state_store.subscribe()

    events = [first.event, first.event] if batch_kind == "duplicate" else [second.event, first.event]
    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        with state_store.ordered_event_publication(con) as publish_committed:
            with pytest.raises(ValueError, match="stream sequence order"):
                publish_committed(events)

    assert subscriber.empty()
    state_store.unsubscribe(subscriber)

def test_ordered_event_publication_rejects_publish_after_scope_closes(tmp_path):
    db_path = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(db_path)
    state_store._ensure_schema()
    subscriber = state_store.subscribe()
    with closing(connect_sqlite(db_path, isolation_level=None)) as con:
        with state_store.ordered_event_publication(con) as publish_committed:
            con.execute("BEGIN IMMEDIATE")
            result = state_store.append_in_transaction(
                con, AgentEvent.create("task:closed-publication", "task.created", {})
            )
            con.execute("COMMIT")

        with pytest.raises(RuntimeError, match="scope is closed"):
            publish_committed([result.event])

    assert subscriber.empty()
    state_store.unsubscribe(subscriber)
