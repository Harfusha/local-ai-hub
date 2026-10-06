import sys
from pathlib import Path

sys.dont_write_bytecode = True
repo = Path(__file__).resolve().parents[2]
overlay = repo / "handoff/.t12-r5-rebuild-20261001/overlay"
sys.path.insert(0, str(overlay / "src"))

import local_ai_hub

local_ai_hub.__path__.append(r"C:\Users\Adam\.local-ai-hub\src\local_ai_hub")
local_ai_hub.__path__.append(
    r"C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\src\local_ai_hub"
)

import pytest

tests = [
    overlay / "tests/test_t12_llama_model_inventory.py",
    overlay / "tests/test_t12_project_model_consumer.py",
    overlay / "tests/test_t12_gaming_pause_loaded_rows.py",
]
raise SystemExit(
    pytest.main([
        "-c", str(overlay / ".pytest-empty.ini"),
        "-q", "-p", "no:cacheprovider", "--tb=short",
        *(str(path) for path in tests),
    ])
)

