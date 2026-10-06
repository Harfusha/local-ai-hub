from pathlib import Path
import sys
base = Path(__file__).resolve().parent
sys.path.insert(0, str(base / "src"))
import local_ai_hub.agent_memory as memory
import local_ai_hub.agent_tasks as tasks
import local_ai_hub.app as app
for module in (memory, tasks, app):
    assert Path(module.__file__).resolve().is_relative_to(base / "src")
    print("SOURCE:", module.__file__, flush=True)
import pytest
raise SystemExit(pytest.main(["-c", str(base / "pytest.ini"), "-q", "-p", "no:cacheprovider", "--tb=short"] + ['tests/test_agent_task_memory_adoption.py', 'tests/test_agent_incident_scope.py', 'tests/test_agent_state_e2e.py::test_local_app_wires_scoped_memory_adoption_on_create_and_resume', 'tests/test_project_memory_audit_completion.py', 'tests/test_agent_memory_t08_tombstones.py', 'tests/test_agent_memory_t08_rollback_masking.py', 'tests/test_memory_delete_identity_contract.py', 'tests/test_t05_memory_delete_artifacts.py', 'tests/test_t05_memory_fts_atomicity.py']))
