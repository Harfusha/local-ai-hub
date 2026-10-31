from pathlib import Path
from local_ai_hub.leases import ScopeLeaseStore

def test_lease_store_rejects_drive_relative_and_relative_roots(tmp_path: Path, monkeypatch):
    store = ScopeLeaseStore(tmp_path / "leases.sqlite3")

    # 1. Relative path rejected
    res = store.claim(owner="agent1", root="some/relative/path", paths=["file.txt"])
    assert res["success"] is False
    assert res["error"] == "root must be an absolute repository root"

    # 2. Drive-relative path on Windows (e.g. C:repo) rejected
    res = store.claim(owner="agent1", root="C:repo", paths=["file.txt"])
    assert res["success"] is False
    assert res["error"] == "root must be an absolute repository root"

    # 3. Drive-relative path simulated under POSIX (os.name = "posix") rejected
    monkeypatch.setattr("local_ai_hub.leases.os.name", "posix")
    res = store.claim(owner="agent1", root="C:repo", paths=["file.txt"])
    assert res["success"] is False
    assert res["error"] == "root must be an absolute repository root"

    # 4. Valid absolute Windows path accepted
    valid_root = str((tmp_path / "valid").resolve())
    (tmp_path / "valid").mkdir(parents=True, exist_ok=True)
    res_win = store.claim(owner="agent1", root=valid_root, paths=["file.txt"], coordination_id="coord1")
    assert res_win["success"] is True
