from pathlib import Path
import os, sys
base = Path(__file__).resolve().parent
sys.path.insert(0, str(base / "src"))
os.environ["PYTHONPATH"] = str(base / "src")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
import local_ai_hub.agent_events as events
import local_ai_hub.agent_tasks as tasks
import local_ai_hub.agent_verification as verification
for module in (events, tasks, verification):
    assert Path(module.__file__).resolve().is_relative_to(base / "src")
    print("SOURCE:", module.__file__, flush=True)
import pytest
raise SystemExit(pytest.main(["-c", str(base / "pytest.ini"), "-q", "-p", "no:cacheprovider", "--tb=short", "--basetemp", str(base / "test-temp")] + ['tests/test_agent_events.py', 'tests/test_agent_tasks.py', 'tests/test_agent_verification.py', 'tests/test_agent_crash_recovery.py', 'tests/test_agent_state_reliability.py']))
