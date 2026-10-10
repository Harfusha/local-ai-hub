from __future__ import annotations

from pathlib import Path
import logging
import sqlite3
import pytest
from local_ai_hub import agent_blackboard
from local_ai_hub.agent_blackboard import BlackboardStore, merge_sections, BlackboardSection


def test_blackboard_rollback_failure_is_narrowly_logged_without_masking_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = BlackboardStore(tmp_path / "state.sqlite3")

    class RollbackFailureConnection:
        isolation_level = None

        def execute(self, statement: str):
            if statement == "ROLLBACK":
                raise sqlite3.OperationalError("sensitive database detail")
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(agent_blackboard, "connect_sqlite", lambda *_args, **_kwargs: RollbackFailureConnection())

    def fail_update(*_args, **_kwargs):
        raise RuntimeError("original update failure")

    monkeypatch.setattr(store, "_update_in_transaction", fail_update)
    caplog.set_level(logging.WARNING)

    with pytest.raises(RuntimeError, match="original update failure"):
        store.update(
            board_id="board-1",
            section="architecture",
            content={"pattern": "event-driven"},
            author="codex",
        )

    assert "blackboard rollback failed" in caplog.text
    assert "OperationalError" in caplog.text
    assert "sensitive database detail" not in caplog.text


def test_blackboard_delete_rollback_failure_is_narrowly_logged_without_masking_original_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = BlackboardStore(tmp_path / "state.sqlite3")
    store.update(
        board_id="board-1",
        section="architecture",
        content={"pattern": "event-driven"},
        author="codex",
    )

    class DeleteFailureConnection(sqlite3.Connection):
        def execute(self, statement: str, parameters=()):
            if statement.startswith("DELETE FROM agent_blackboard"):
                raise sqlite3.OperationalError("original delete failure")
            if statement == "ROLLBACK":
                raise sqlite3.OperationalError("sensitive database detail")
            return super().execute(statement, parameters)

    def connect_with_delete_failure(path, **kwargs):
        con = sqlite3.connect(path, factory=DeleteFailureConnection)
        con.row_factory = kwargs.get("row_factory")
        return con

    monkeypatch.setattr(agent_blackboard, "connect_sqlite", connect_with_delete_failure)
    caplog.set_level(logging.WARNING)

    with pytest.raises(sqlite3.OperationalError, match="original delete failure"):
        store.delete("board-1")

    assert "blackboard rollback failed" in caplog.text
    assert "OperationalError" in caplog.text
    assert "sensitive database detail" not in caplog.text


def test_vector_clock_domination():
    # A dominates B
    sec_a = BlackboardSection(
        section="arch", content="newer", author="codex",
        clock={"codex": 2, "claude": 1}, timestamp=100.0, version=2,
    )
    sec_b = BlackboardSection(
        section="arch", content="older", author="claude",
        clock={"codex": 1, "claude": 1}, timestamp=90.0, version=1,
    )
    merged = merge_sections(sec_a, sec_b)
    assert merged.content == "newer"
    assert merged.author == "codex"
    assert merged.clock == {"codex": 2, "claude": 1}


def test_concurrent_conflict_lww_resolution():
    # Concurrent clocks: neither dominates -> LWW by timestamp
    sec_codex = BlackboardSection(
        section="api", content="endpoint_a", author="codex",
        clock={"codex": 2, "claude": 0}, timestamp=150.0, version=1,
    )
    sec_claude = BlackboardSection(
        section="api", content="endpoint_b", author="claude",
        clock={"codex": 0, "claude": 2}, timestamp=160.0, version=1,
    )
    merged = merge_sections(sec_codex, sec_claude)
    # Claude had higher timestamp 160.0 > 150.0
    assert merged.content == "endpoint_b"
    assert merged.author == "claude"
    # Merged clock incorporates both components
    assert merged.clock == {"codex": 2, "claude": 2}


def test_concurrent_merge_is_commutative_when_timestamp_and_author_match():
    left = BlackboardSection(
        section="api",
        content={"a": 1, "z": 2},
        author="same-agent",
        clock={"replica-a": 1, "same-agent": 1},
        timestamp=170.0,
        version=1,
    )
    right = BlackboardSection(
        section="api",
        content={"a": 2, "z": 1},
        author="same-agent",
        clock={"replica-b": 1, "same-agent": 1},
        timestamp=170.0,
        version=1,
    )

    assert merge_sections(left, right) == merge_sections(right, left)
    replica_reloaded = merge_sections(
        BlackboardSection(
            section="api",
            content={"z": 1, "a": 2},
            author="same-agent",
            clock={"replica-b": 1, "same-agent": 1},
            timestamp=170.0,
            version=1,
        ),
        BlackboardSection(
            section="api",
            content={"z": 2, "a": 1},
            author="same-agent",
            clock={"replica-a": 1, "same-agent": 1},
            timestamp=170.0,
            version=1,
        ),
    )
    assert merge_sections(left, right) == replica_reloaded


def test_blackboard_store_persistence_and_multiagent_merge(tmp_path: Path):
    db_path = tmp_path / "state" / "agent_state.sqlite3"
    store = BlackboardStore(db_path)

    # 1. Codex writes "architecture"
    res1 = store.update(
        board_id="board-1",
        section="architecture",
        content={"pattern": "event-driven", "bus": "sqlite"},
        author="codex",
    )
    assert res1["success"] is True
    assert res1["section"]["clock"] == {"codex": 1}

    # 2. Claude writes "test_plan" concurrently
    res2 = store.update(
        board_id="board-1",
        section="test_plan",
        content=["unit tests", "fuzz tests"],
        author="claude",
    )
    assert res2["success"] is True

    # 3. Read board: both sections exist without conflict
    board = store.get(board_id="board-1")
    assert board["success"] is True
    assert "architecture" in board["sections"]
    assert "test_plan" in board["sections"]
    assert board["sections"]["architecture"]["content"]["pattern"] == "event-driven"

    # 4. Codex updates architecture again
    res3 = store.update(
        board_id="board-1",
        section="architecture",
        content={"pattern": "cqrs+event-driven", "bus": "sqlite"},
        author="codex",
    )
    assert res3["section"]["clock"]["codex"] == 2

    # 5. Remote merge from another peer agent (Gemini)
    remote_state = {
        "architecture": {
            "content": {"pattern": "outdated"},
            "author": "gemini",
            "clock": {"codex": 1, "gemini": 1},
            "timestamp": 50.0,
            "version": 1,
        },
        "security_notes": {
            "content": "use hmac tokens",
            "author": "gemini",
            "clock": {"gemini": 1},
            "timestamp": 200.0,
            "version": 1,
        },
    }
    merge_res = store.merge(board_id="board-1", remote_sections=remote_state)
    assert merge_res["success"] is True
    
    final_board = store.get(board_id="board-1")
    # Architecture should still be Codex's newer value because clock codex:2 dominates codex:1
    assert final_board["sections"]["architecture"]["content"]["pattern"] == "cqrs+event-driven"
    # Security notes added
    assert final_board["sections"]["security_notes"]["content"] == "use hmac tokens"

    # 6. List boards
    boards = store.list_boards()
    assert "board-1" in boards


def test_merge_sections_idempotency():
    sec_a = BlackboardSection(
        section="arch", content="older", author="codex",
        clock={"codex": 1}, timestamp=100.0, version=1,
    )
    sec_b = BlackboardSection(
        section="arch", content="newer", author="claude",
        clock={"claude": 1}, timestamp=110.0, version=1,
    )
    m1 = merge_sections(sec_a, sec_b)
    m2 = merge_sections(m1, sec_b)
    m3 = merge_sections(m1, sec_a)
    assert m1.version == 2
    assert m2.version == 2
    assert m3.version == 2
    assert m1.content == m2.content == m3.content == "newer"
    assert m1.clock == m2.clock == m3.clock == {"codex": 1, "claude": 1}

