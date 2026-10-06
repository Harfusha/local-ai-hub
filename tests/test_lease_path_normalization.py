from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore


def test_windows_absolute_path_inside_repository_normalizes_on_any_host(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        "agent",
        r"C:\workspace\repo",
        [r"C:\workspace\repo\src\same.py"],
    )

    assert result["success"] is True
    assert result["paths"] == ["src/same.py"]


def test_windows_absolute_path_matching_is_case_insensitive(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        "agent",
        r"C:\WORKSPACE\REPO",
        [r"c:\workspace\repo\src\Case.py"],
    )

    assert result["success"] is True
    assert result["paths"] == ["src/Case.py"]


def test_windows_root_aliases_and_relative_paths_conflict_case_insensitively(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    first = store.claim("agent-one", r"C:\Work\Repo", ["src/Foo.py"])
    second = store.claim("agent-two", r"c:\work\repo", ["src/foo.py"])

    assert first["success"] is True
    assert second["success"] is False


@pytest.mark.parametrize(
    "first_path,second_path",
    [("src", "src/file.py"), ("src/file.py", "src")],
)
def test_windows_parent_child_scopes_conflict_in_both_claim_orders(
    tmp_path: Path, first_path: str, second_path: str
):
    store = ScopeLeaseStore(tmp_path / "state")

    first = store.claim("agent-one", r"C:\Work\Repo", [first_path])
    second = store.claim("agent-two", r"c:\work\repo", [second_path])

    assert first["success"] is True
    assert second["success"] is False


@pytest.mark.parametrize(
    "first_root,second_root",
    [
        (r"C:\Work\Repo", r"c:\work\repo\sub\.."),
        (r"\\server\share\repo", r"\\SERVER\SHARE\Repo\sub\.."),
    ],
)
def test_windows_root_aliases_with_dot_segments_share_identity(
    tmp_path: Path, first_root: str, second_root: str
):
    store = ScopeLeaseStore(tmp_path / "state")

    first = store.claim("agent-one", first_root, ["src/file.py"])
    second = store.claim("agent-two", second_root, ["src/file.py"])

    assert first["success"] is True
    assert second["success"] is False


def _require_case_sensitive_posix(tmp_path: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        pytest.skip("POSIX paths may be case-sensitive only on non-Windows hosts")

    upper_root = tmp_path / "Repo"
    lower_root = tmp_path / "repo"
    upper_root.mkdir()
    try:
        lower_root.mkdir()
    except FileExistsError:
        pytest.skip("filesystem does not distinguish path case")
    return upper_root, lower_root


def test_posix_root_identity_remains_case_sensitive(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    upper_root, lower_root = _require_case_sensitive_posix(tmp_path)

    upper = store.claim("agent-one", str(upper_root), ["src/file.py"])
    lower = store.claim("agent-two", str(lower_root), ["src/file.py"])

    assert upper["success"] is True
    assert lower["success"] is True


def test_posix_relative_path_overlap_remains_case_sensitive(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    upper_root, _ = _require_case_sensitive_posix(tmp_path)

    upper = store.claim("agent-one", str(upper_root), ["Src/Foo.py"])
    lower = store.claim("agent-two", str(upper_root), ["src/foo.py"])

    assert upper["success"] is True
    assert lower["success"] is True


def test_posix_drive_relative_names_keep_case_sensitive_root_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    if os.name == "nt":
        pytest.skip("drive-relative POSIX path names are unavailable on Windows")

    monkeypatch.chdir(tmp_path)
    upper_root = tmp_path / "C:Repo"
    lower_root = tmp_path / "c:repo"
    upper_root.mkdir()
    try:
        lower_root.mkdir()
    except FileExistsError:
        pytest.skip("filesystem does not distinguish path case")

    store = ScopeLeaseStore(tmp_path / "state")
    upper = store.claim("agent-one", "C:Repo", ["src/file.py"])
    lower = store.claim("agent-two", "c:repo", ["src/file.py"])

    assert upper["success"] is True
    assert lower["success"] is True


def test_unc_absolute_path_inside_repository_normalizes_on_any_host(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        "agent",
        r"\\server\share\repo",
        [r"\\server\share\repo\src\unc.py"],
    )

    assert result["success"] is True
    assert result["paths"] == ["src/unc.py"]


def test_windows_absolute_path_outside_repository_is_rejected_even_with_same_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = ScopeLeaseStore(tmp_path / "state")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim("agent", r"C:\workspace\repo", ["C:/workspace/other/same.py"])


def test_unc_escape_and_windows_parent_traversal_are_rejected(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim("agent", r"\\server\share\repo", [r"\\server\share\outside\same.py"])

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim("agent", r"C:\workspace\repo", [r"C:\workspace\repo\..\outside\same.py"])


def test_posix_relative_parent_traversal_is_rejected(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim("agent", str(repo), ["../outside/same.py"])


def test_relative_symlink_escape_is_rejected(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.touch()
    link = repo / "escape.py"

    try:
        link.symlink_to(outside)
    except NotImplementedError as exc:
        pytest.skip(f"symlink creation is unsupported: {exc}")
    except OSError as exc:
        unsupported_errnos = {
            getattr(errno, name)
            for name in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP", "EPERM")
            if hasattr(errno, name)
        }
        if exc.errno in unsupported_errnos or getattr(exc, "winerror", None) in {50, 1314}:
            pytest.skip(f"symlink creation is unsupported: {exc}")
        raise

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim("agent", str(repo), ["escape.py"])


def test_relative_symlink_within_repository_is_allowed(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "inside.py"
    target.touch()
    link = repo / "alias.py"

    try:
        link.symlink_to(target)
    except NotImplementedError as exc:
        pytest.skip(f"symlink creation is unsupported: {exc}")
    except OSError as exc:
        unsupported_errnos = {
            getattr(errno, name)
            for name in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP", "EPERM")
            if hasattr(errno, name)
        }
        if exc.errno in unsupported_errnos or getattr(exc, "winerror", None) in {50, 1314}:
            pytest.skip(f"symlink creation is unsupported: {exc}")
        raise

    result = store.claim("agent", str(repo), ["alias.py"])

    assert result["success"] is True
    assert result["paths"] == ["alias.py"]


def test_relative_symlink_target_within_repository_is_allowed(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "inside.py"
    target.touch()
    link = repo / "alias.py"
    relative_target = Path("inside.py")

    try:
        link.symlink_to(relative_target)
    except NotImplementedError as exc:
        pytest.skip(f"symlink creation is unsupported: {exc}")
    except OSError as exc:
        unsupported_errnos = {
            getattr(errno, name)
            for name in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP", "EPERM")
            if hasattr(errno, name)
        }
        if exc.errno in unsupported_errnos or getattr(exc, "winerror", None) in {50, 1314}:
            pytest.skip(f"symlink creation is unsupported: {exc}")
        raise

    assert link.readlink() == relative_target
    result = store.claim("agent", str(repo), ["alias.py"])

    assert result["success"] is True
    assert result["paths"] == ["alias.py"]


@pytest.mark.parametrize(
    ("first_path", "second_path"),
    [("alias.py", "inside.py"), ("inside.py", "alias.py")],
)
def test_symlink_alias_and_target_scopes_conflict_in_both_orders(
    tmp_path: Path, first_path: str, second_path: str
):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "inside.py"
    target.touch()
    link = repo / "alias.py"
    try:
        link.symlink_to(Path("inside.py"))
    except NotImplementedError as exc:
        pytest.skip(f"symlink creation is unsupported: {exc}")
    except OSError as exc:
        unsupported_errnos = {
            getattr(errno, name)
            for name in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP", "EPERM")
            if hasattr(errno, name)
        }
        if exc.errno in unsupported_errnos or getattr(exc, "winerror", None) in {50, 1314}:
            pytest.skip(f"symlink creation is unsupported: {exc}")
        raise

    first = store.claim("first-agent", str(repo), [first_path])
    second = store.claim("second-agent", str(repo), [second_path])

    assert first["success"] is True
    assert second["success"] is False


def test_relative_symlink_target_escape_is_rejected(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.py"
    outside.touch()
    link = repo / "escape.py"
    relative_target = Path("..") / outside.name

    try:
        link.symlink_to(relative_target)
    except NotImplementedError as exc:
        pytest.skip(f"symlink creation is unsupported: {exc}")
    except OSError as exc:
        unsupported_errnos = {
            getattr(errno, name)
            for name in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP", "EPERM")
            if hasattr(errno, name)
        }
        if exc.errno in unsupported_errnos or getattr(exc, "winerror", None) in {50, 1314}:
            pytest.skip(f"symlink creation is unsupported: {exc}")
        raise

    assert link.readlink() == relative_target
    with pytest.raises(ValueError, match="repository-relative"):
        store.claim("agent", str(repo), ["escape.py"])


def test_nonexistent_in_root_target_is_allowed(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "new" / "future.py"

    result = store.claim("agent", str(repo), ["new/future.py"])

    assert target.exists() is False
    assert result["success"] is True
    assert result["paths"] == ["new/future.py"]


def test_foreign_windows_root_allows_repository_relative_target(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim("agent", r"C:\workspace\repo", [r"src\new.py"])

    assert result["success"] is True
    assert result["paths"] == ["src/new.py"]
