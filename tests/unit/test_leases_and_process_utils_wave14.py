import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore, _norm_rel, _overlap
from local_ai_hub.process_utils import is_valid_pid, pid_alive, clean_git_env


def test_norm_rel_hardening():
    # Valid relative paths
    assert _norm_rel(".") == "."
    assert _norm_rel("src/foo.py") == "src/foo.py"
    assert _norm_rel("foo/bar/../baz.py") == "foo/baz.py"

    # Invalid paths: empty, None, boolean, null byte, escaping
    with pytest.raises(ValueError):
        _norm_rel("")

    with pytest.raises(ValueError):
        _norm_rel("   ")

    with pytest.raises(ValueError):
        _norm_rel(None)

    with pytest.raises(ValueError):
        _norm_rel(True)

    with pytest.raises(ValueError):
        _norm_rel("src/\x00/foo.py")

    with pytest.raises(ValueError):
        _norm_rel("../escaping.py")

    assert _overlap(".", "src/module.py") is True
    assert _overlap("src/module.py", "../escape.py") is True
    assert _overlap("src/module.py", 42) is True


def test_scope_lease_store_scalar_coercion_and_path_validation(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "leases")

    # Reject scalar paths (e.g. string instead of list/set of strings)
    res_scalar = store.claim(owner="execution-1", root=str(tmp_path), paths="some/file.py")
    assert res_scalar["success"] is False
    assert "paths must be a sequence of path strings" in res_scalar["error"]

    # Reject unordered collections and Path objects; the contract is a sequence of strings.
    assert store.claim(owner="execution-1", root=str(tmp_path), paths={"some/file.py"})["success"] is False
    assert store.claim(owner="execution-1", root=str(tmp_path), paths=[tmp_path / "some" / "file.py"])["success"] is False

    # Reject scalar identity coercions before opening a lease transaction.
    assert store.claim(owner=1, root=str(tmp_path), paths=["valid.py"])["error"] == "invalid owner"
    assert store.claim(owner="execution-1", root=tmp_path, paths=["valid.py"])["error"] == "invalid root"
    assert store.claim(owner="execution-1", root=str(tmp_path), paths=["valid.py"], purpose=1)["error"] == "invalid purpose"
    assert store.claim(
        owner="execution-1", root=str(tmp_path), paths=["valid.py"], coordination_id=42
    )["error"] == "invalid project coordination id"

    # Reject paths containing invalid elements
    res_invalid_elem = store.claim(owner="execution-1", root=str(tmp_path), paths=["valid.py", "bad\x00.py"])
    assert res_invalid_elem["success"] is False
    assert "invalid lease path" in res_invalid_elem["error"]

    # Invalid TTL values reject instead of silently selecting a default.
    res_invalid_ttl = store.claim(owner="execution-1", root=str(tmp_path), paths=["invalid.py"], ttl_seconds=True)
    assert res_invalid_ttl["success"] is False
    assert res_invalid_ttl["error"] == "ttl_seconds must be a positive integer"
    res_invalid_float_ttl = store.claim(owner="execution-1", root=str(tmp_path), paths=["invalid-float.py"], ttl_seconds=900.0)
    assert res_invalid_float_ttl["success"] is False

    res_valid = store.claim(owner="execution-1", root=str(tmp_path), paths=["valid.py"])
    assert res_valid["success"] is True
    lease_id = res_valid["lease_id"]

    # Release rejects scalar non-string lease_id
    res_rel_scalar = store.release(owner="execution-1", lease_id=12345)
    assert res_rel_scalar["success"] is False
    assert "lease_id must be a string" in res_rel_scalar["error"]
    assert store.release(owner="execution-1", lease_id="")["success"] is False
    assert store.release(owner="execution-1", lease_id=None)["success"] is False
    assert store.release(owner="   ", lease_id="lease-id")["success"] is False

    # Renew rejects scalar non-string lease_id
    res_renew_scalar = store.renew(owner="execution-1", lease_id=12345)
    assert res_renew_scalar["success"] is False
    assert "lease_id must be a string" in res_renew_scalar["error"]

    # Renew rejects boolean TTL rather than silently selecting a default.
    res_renew = store.renew(owner="execution-1", lease_id=lease_id, ttl_seconds=False)
    assert res_renew["success"] is False
    assert res_renew["error"] == "ttl_seconds must be a positive integer"

    # Proper release
    res_rel = store.release(owner="execution-1", lease_id=lease_id)
    assert res_rel["success"] is True


def test_scope_lease_store_writer_cleanup_is_explicit(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "leases")
    first = store.claim(owner="execution-1", root=str(tmp_path), paths=["one.py"])
    second = store.claim(owner="execution-1", root=str(tmp_path), paths=["two.py"])
    assert first["success"] and second["success"]

    result = store.release_owner(owner="execution-1")
    assert result == {"success": True, "released_rows": 2}
    assert store.release(owner="execution-1", lease_id=first["lease_id"])["released_rows"] == 0


def test_scope_lease_store_read_and_renew_inputs_fail_closed(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "leases")

    assert store.renew(owner=1, lease_id="lease-id")["error"] == "invalid owner"
    assert store.renew(owner="execution-1", lease_id=" lease-id ")["error"] == "invalid lease_id"
    assert store.list(coordination_id=42) == []
    assert store.list(root=tmp_path) == []
    assert store.waits(coordination_id=True) == []
    assert store.check_path(42, root=str(tmp_path))["error"] == "path must be a string"
    assert store.check_path(
        "file.py", root=str(tmp_path), coordination_id=42
    )["error"] == "invalid project coordination id"


def test_corrupt_live_lease_path_blocks_claim_and_check(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "leases")
    held = store.claim(owner="writer-a:execution-1", root=str(tmp_path), paths=["owned/file.py"])
    assert held["success"] is True
    with closing(sqlite3.connect(store.path)) as con:
        with con:
            con.execute(
                "UPDATE leases SET path=? WHERE lease_id=?",
                ("../outside.py", held["lease_id"]),
            )

    claim = store.claim(owner="writer-b:execution-2", root=str(tmp_path), paths=["unrelated.py"])
    assert claim["success"] is False
    assert "overlaps another active agent lease" in claim["error"]
    assert store.check_path("unrelated.py", root=str(tmp_path))["leased"] is True


def test_process_utils_pid_and_env_hardening():
    assert is_valid_pid(True) is False
    assert is_valid_pid(False) is False
    assert is_valid_pid(None) is False
    assert is_valid_pid(-1) is False
    assert is_valid_pid(0) is False
    assert is_valid_pid(12345) is True

    assert pid_alive(True) is False
    assert pid_alive(False) is False

    cleaned = clean_git_env(
        base_env={"GIT_DIR": ".git", "PATH": "/usr/bin", "FOO": "BAR"},
        extra_env={"EXTRA": "VAL", "NULL\x00": "DROP"},
    )
    assert "GIT_DIR" not in cleaned
    assert cleaned["PATH"] == "/usr/bin"
    assert cleaned["FOO"] == "BAR"
    assert cleaned["EXTRA"] == "VAL"
    assert "NULL\x00" not in cleaned
