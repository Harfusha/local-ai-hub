from dataclasses import replace
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


class IncidentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "agent-state.sqlite3"
        self.state = AgentStateStore(db_path)
        self.incidents = IncidentStore(self.state)

    def tearDown(self):
        self.temp_dir.cleanup()

    def capture(self, revision="rev-a", message="No module named pytest"):
        return self.incidents.capture(ToolOutcome(
            tool_name="local_ai_command",
            command="python -m pytest -q",
            error=message,
            exit_code=1,
            state_revision=revision,
        ))

    def test_identical_error_across_revisions_updates_one_incident(self):
        first = self.capture("rev-a")
        second = self.capture("rev-b")

        self.assertEqual(first.incident_id, second.incident_id)
        self.assertEqual(second.state_revision, "rev-b")
        self.assertEqual(second.attempts, 2)
        self.assertEqual(len(self.incidents.list_incidents()), 1)

    def test_ignored_error_stays_suppressed_and_can_be_restored(self):
        incident = self.capture()
        self.assertEqual(
            self.incidents.retry_decision(incident.fingerprint, "rev-a").action,
            "stop",
        )

        ignored = self.incidents.set_ignored(incident.incident_id)
        self.assertEqual(ignored.status, "ignored")
        self.assertEqual(self.incidents.retry_decision(incident.fingerprint, "rev-a").action, "proceed")
        self.assertEqual(len(self.incidents.list_incidents(status="ignored")), 1)
        self.assertEqual(self.incidents.find_negative_knowledge(), [])

        repeated = self.capture("rev-b")
        self.assertEqual(repeated.status, "ignored")
        self.assertEqual(repeated.attempts, 2)
        self.assertEqual(len(self.incidents.list_incidents()), 1)

        restored = self.incidents.set_ignored(incident.incident_id, ignored=False)
        self.assertEqual(restored.status, "unresolved")
        self.assertEqual(self.incidents.retry_decision(incident.fingerprint, "rev-b").action, "stop")

    def test_recurrence_reopens_previously_resolved_incident(self):
        incident = self.capture()
        resolved = self.incidents.resolve(
            incident.incident_id,
            verified_fix="Install pytest in the active environment",
            confidence=0.95,
        )
        self.assertEqual(resolved.status, "resolved")

        reopened = self.capture("rev-b")
        self.assertEqual(reopened.status, "unresolved")
        self.assertFalse(reopened.resolved)
        self.assertEqual(self.incidents.retry_decision(incident.fingerprint, "rev-b").action, "stop")

    def test_legacy_duplicate_rows_are_grouped_without_losing_attempts(self):
        incident = self.capture()
        duplicate = replace(
            incident,
            incident_id="inc_legacy_duplicate",
            state_revision="rev-old",
            attempts=3,
            updated_at=incident.updated_at - 1,
        )
        self.incidents._save_record(duplicate)

        grouped = self.incidents.list_incidents()
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0].incident_id, incident.incident_id)
        self.assertEqual(grouped[0].attempts, 4)
        self.assertEqual(len(self.incidents.find_negative_knowledge()), 1)

    def test_old_incident_table_gains_ignore_flag_without_being_dropped(self):
        db_path = Path(self.temp_dir.name) / "legacy-state.sqlite3"
        state = AgentStateStore(db_path)
        state._ensure_schema()
        con = sqlite3.connect(db_path)
        try:
            con.execute(
                """
                CREATE TABLE agent_incidents (
                    incident_id TEXT PRIMARY KEY, operation_class TEXT NOT NULL,
                    error_class TEXT NOT NULL, signature_hash TEXT NOT NULL,
                    redacted_message TEXT NOT NULL, state_revision TEXT NOT NULL,
                    attempts INTEGER NOT NULL, evidence_ids TEXT NOT NULL, root_cause TEXT,
                    verified_fix TEXT, confidence REAL NOT NULL, resolved INTEGER NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL,
                    affected_paths TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            con.execute(
                """INSERT INTO agent_incidents VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "inc_legacy", "local_ai_command", "CommandExecutionError", "sig",
                    "No module named pytest", "rev-old", 1, "[]", None, None, 0.0,
                    0, 1.0, 1.0, None, "[]",
                ),
            )
            con.commit()
        finally:
            con.close()

        rows = IncidentStore(state).list_incidents()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].incident_id, "inc_legacy")
        self.assertFalse(rows[0].ignored)


if __name__ == "__main__":
    unittest.main()
