from contextlib import closing
import sqlite3

from local_ai_hub.agent_events import AgentStateStore


def test_schema_preflight_accepts_budget_external_reservation_index(tmp_path):
    path = tmp_path / "agent_state.sqlite"
    AgentStateStore(path)._ensure_schema()

    with closing(sqlite3.connect(path)) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS agent_external_call_reservations (
                invocation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                reserved_at REAL NOT NULL
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_external_reservations_task "
            "ON agent_external_call_reservations(task_id)"
        )

        AgentStateStore._classify_schema(con)
