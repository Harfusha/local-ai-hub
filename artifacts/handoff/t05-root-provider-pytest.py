"""Run T05 tests against the root-current T08 event provider without copying it."""

import importlib.util
import sys
from pathlib import Path

import pytest

candidate_src = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(candidate_src))
import local_ai_hub

provider_path = r"C:\Users\Adam\.local-ai-hub\src\local_ai_hub\agent_events.py"
spec = importlib.util.spec_from_file_location("local_ai_hub.agent_events", provider_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load root event provider: {provider_path}")
provider = importlib.util.module_from_spec(spec)
sys.modules["local_ai_hub.agent_events"] = provider
spec.loader.exec_module(provider)
raise SystemExit(pytest.main(sys.argv[1:]))
