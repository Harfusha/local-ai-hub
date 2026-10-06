from pathlib import Path
import sys
base = Path(__file__).resolve().parent
sys.path.insert(0, str(base / "src"))
import local_ai_hub.agent_memory as memory
assert Path(memory.__file__).resolve() == base / "src/local_ai_hub/agent_memory.py"
print("SOURCE:", memory.__file__, flush=True)
import pytest
raise SystemExit(pytest.main(["-c", str(base / "pytest.ini"), "-q", "-p", "no:cacheprovider", "--tb=short"] + ['tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records', 'tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen']))
