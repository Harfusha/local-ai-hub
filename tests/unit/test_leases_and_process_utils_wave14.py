import math
import pytest
from pathlib import Path

from local_ai_hub.leases import ScopeLeaseStore, _norm_rel
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


def test_scope_lease_store_scalar_coercion_and_path_validation(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "leases")

    # Reject scalar paths (e.g. string instead of list/set of strings)
    res_scalar = store.claim("tenant1", str(tmp_path), "some/file.py")
    assert res_scalar["success"] is False
    assert "paths must be a sequence of path strings" in res_scalar["error"]

    # Reject unordered collections and Path objects; the contract is a sequence of strings.
    assert store.claim("tenant1", str(tmp_path), {"some/file.py"})["success"] is False
    assert store.claim("tenant1", str(tmp_path), [tmp_path / "some" / "file.py"])["success"] is False

    # Reject paths containing invalid elements
    res_invalid_elem = store.claim("tenant1", str(tmp_path), ["valid.py", "bad\x00.py"])
    assert res_invalid_elem["success"] is False
    assert "invalid lease path" in res_invalid_elem["error"]

    # Valid claim with boolean ttl_seconds falls back safely
    res_valid = store.claim("tenant1", str(tmp_path), ["valid.py"], ttl_seconds=True)
    assert res_valid["success"] is True
    lease_id = res_valid["lease_id"]

    # Release rejects scalar non-string lease_id
    res_rel_scalar = store.release("tenant1", 12345)
    assert res_rel_scalar["success"] is False
    assert "lease_id must be a string" in res_rel_scalar["error"]
    assert store.release("tenant1", "")["success"] is False
    assert store.release("tenant1", None)["success"] is False

    # Renew rejects scalar non-string lease_id
    res_renew_scalar = store.renew("tenant1", 12345)
    assert res_renew_scalar["success"] is False
    assert "lease_id must be a string" in res_renew_scalar["error"]

    # Renew with boolean ttl_seconds
    res_renew = store.renew("tenant1", lease_id, ttl_seconds=False)
    assert res_renew["success"] is True

    # Proper release
    res_rel = store.release("tenant1", lease_id)
    assert res_rel["success"] is True


def test_scope_lease_store_tenant_cleanup_is_explicit(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "leases")
    first = store.claim("tenant1", str(tmp_path), ["one.py"])
    second = store.claim("tenant1", str(tmp_path), ["two.py"])
    assert first["success"] and second["success"]

    result = store.release_tenant("tenant1")
    assert result == {"success": True, "released_rows": 2}
    assert store.release("tenant1", first["lease_id"])["released_rows"] == 0


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
