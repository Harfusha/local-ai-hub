from pathlib import Path
import os, sys
base = Path(__file__).resolve().parent
sys.path.insert(0, str(base / "src"))
os.environ["PYTHONPATH"] = str(base / "src")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
import local_ai_hub.agent_memory as memory
import local_ai_hub.agent_tasks as tasks
import local_ai_hub.agent_events as events
import local_ai_hub.app as app
for module in (memory, tasks, events, app):
    assert Path(module.__file__).resolve().is_relative_to(base / "src")
    print("SOURCE:", module.__file__, flush=True)
import pytest
raise SystemExit(pytest.main(["-c", str(base / "pytest.ini"), "-q", "-p", "no:cacheprovider", "--tb=short", "--basetemp", str(base / "test-temp")] + ['tests/test_agent_t08_cache_isolation.py', 'tests/test_agent_t08_crash_after_commit.py', 'tests/test_agent_t08_durable_contract.py', 'tests/test_agent_t08_event_page_snapshot.py', 'tests/test_agent_t08_live_order.py', 'tests/test_agent_t08_migration_recovery.py', 'tests/test_agent_t08_receipt_transaction.py', 'tests/test_agent_incident_scope.py', 'tests/test_lease_atomic_deadlock.py', 'tests/test_agent_task_memory_adoption.py', 'tests/test_agent_t08_completion_validation.py', 'tests/test_t05_agent_state_migrations.py', 'tests/test_project_memory_audit_completion.py', 'tests/test_agent_memory_t08_tombstones.py', 'tests/test_agent_memory_t08_rollback_masking.py', 'tests/test_memory_delete_identity_contract.py', 'tests/test_t05_memory_delete_artifacts.py', 'tests/test_t05_memory_fts_atomicity.py', 'tests/test_agent_state_e2e.py::test_local_app_wires_scoped_memory_adoption_on_create_and_resume', 'tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records', 'tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen', 'tests/test_agent_crash_recovery.py::test_committed_event_append_survives_restart_before_publish', 'tests/test_agent_crash_recovery.py::test_committed_task_creation_survives_restart_before_publish', 'tests/test_agent_crash_recovery.py::test_committed_task_transition_survives_restart_before_publish', 'tests/test_agent_crash_recovery.py::test_crash_after_task_event_append_before_commit_rolls_back_projection_and_event', 'tests/test_agent_crash_recovery.py::test_os_exit_after_task_event_insert_rolls_back_projection_and_event', 'tests/test_agent_crash_recovery.py::test_committed_task_checkpoint_survives_restart_before_publish', 'tests/test_agent_crash_recovery.py::test_committed_task_completion_survives_restart_before_publish', 'tests/test_agent_crash_recovery.py::test_committed_task_failure_survives_restart_before_publish']))
