from __future__ import annotations

import hashlib
from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine


def test_batch_replace_cas_success(tmp_path: Path):
    target = tmp_path / "code.py"
    target.write_text("def hello():\n    return 'old'\n", encoding="utf-8")
    original_sha = hashlib.sha256(target.read_text(encoding="utf-8").encode("utf-8")).hexdigest()

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    res = engine.batch_replace(
        str(tmp_path),
        [{"path": "code.py", "old": "return 'old'", "new": "return 'new'", "expected_sha256": original_sha}],
    )
    assert res["success"] is True, f"Failed: {res}"
    assert res["applied"] is True
    assert "code.py" in res["sha256"]
    assert target.read_text(encoding="utf-8") == "def hello():\n    return 'new'\n"


def test_batch_replace_cas_conflict(tmp_path: Path):
    target = tmp_path / "code.py"
    target.write_text("def hello():\n    return 'old'\n", encoding="utf-8")
    wrong_sha = "0" * 64

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    res = engine.batch_replace(
        str(tmp_path),
        [{"path": "code.py", "old": "return 'old'", "new": "return 'new'", "expected_sha256": wrong_sha}],
    )
    assert res["success"] is False
    assert res["conflict"] is True
    assert "CAS conflict" in res["error"]
    assert target.read_text(encoding="utf-8") == "def hello():\n    return 'old'\n"
