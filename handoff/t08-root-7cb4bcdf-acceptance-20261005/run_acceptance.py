from pathlib import Path
import sys
base = Path(__file__).resolve().parent
sys.path.insert(0, str(base / "src"))
import local_ai_hub.agent_memory as memory
import local_ai_hub.app as app
assert Path(memory.__file__).resolve() == base / "src/local_ai_hub/agent_memory.py"
assert Path(app.__file__).resolve() == base / "src/local_ai_hub/app.py"
print("SOURCE:", memory.__file__, flush=True)
import pytest
raise SystemExit(pytest.main(["-c", str(base / "pytest.ini"), "-q", "-p", "no:cacheprovider", "--tb=short", "tests/test_agent_memory.py", "tests/test_agent_state_operations.py"]))
