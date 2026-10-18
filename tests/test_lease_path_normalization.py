from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from local_ai_hub.leases import ScopeLeaseStore


def test_windows_absolute_path_inside_repository_normalizes_on_any_host(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        owner="task-path-normalization",
        root=r"C:\workspace\repo",
        paths=[r"C:\workspace\repo\src\same.py"],
        purpose="path normalization test",
    )

    assert result["success"] is True
    assert result["paths"] == ["src/same.py"]


def test_windows_absolute_path_matching_is_case_insensitive(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        owner="task-path-case",
        root=r"C:\WORKSPACE\REPO",
        paths=[r"c:\workspace\repo\src\Case.py"],
        purpose="path normalization test",
    )

    assert result["success"] is True
    assert result["paths"] == ["src/Case.py"]


def test_windows_root_aliases_and_relative_paths_conflict_case_insensitively(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    first = store.claim(
        owner="task-path-first", root=r"C:\Work\Repo", paths=["src/Foo.py"], purpose="path conflict test"
    )
    second = store.claim(
        owner="task-path-second", root=r"c:\work\repo", paths=["src/foo.py"], purpose="path conflict test"
    )

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

    first = store.claim(
        owner="task-parent-first", root=r"C:\Work\Repo", paths=[first_path], purpose="parent child conflict test"
    )
    second = store.claim(
        owner="task-parent-second", root=r"c:\work\repo", paths=[second_path], purpose="parent child conflict test"
    )

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

    first = store.claim(
        owner="task-root-first", root=first_root, paths=["src/file.py"], purpose="root alias test"
    )
    second = store.claim(
        owner="task-root-second", root=second_root, paths=["src/file.py"], purpose="root alias test"
    )

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

    upper = store.claim(
        owner="task-root-upper", root=str(upper_root), paths=["src/file.py"], purpose="root case test"
    )
    lower = store.claim(
        owner="task-root-lower", root=str(lower_root), paths=["src/file.py"], purpose="root case test"
    )

    assert upper["success"] is True
    assert lower["success"] is True


def test_posix_relative_path_overlap_remains_case_sensitive(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    upper_root, _ = _require_case_sensitive_posix(tmp_path)

    upper = store.claim(
        owner="task-path-upper", root=str(upper_root), paths=["Src/Foo.py"], purpose="path case test"
    )
    lower = store.claim(
        owner="task-path-lower", root=str(upper_root), paths=["src/foo.py"], purpose="path case test"
    )

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
    upper = store.claim(
        owner="task-drive-upper", root="C:Repo", paths=["src/file.py"], purpose="drive relative test"
    )
    lower = store.claim(
        owner="task-drive-lower", root="c:repo", paths=["src/file.py"], purpose="drive relative test"
    )

    assert upper["success"] is True
    assert lower["success"] is True


def test_unc_absolute_path_inside_repository_normalizes_on_any_host(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        owner="task-unc-normalization",
        root=r"\\server\share\repo",
        paths=[r"\\server\share\repo\src\unc.py"],
        purpose="path normalization test",
    )

    assert result["success"] is True
    assert result["paths"] == ["src/unc.py"]


def test_windows_absolute_path_outside_repository_is_rejected_even_with_same_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = ScopeLeaseStore(tmp_path / "state")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim(
            owner="task-path-confinement", root=r"C:\workspace\repo",
            paths=["C:/workspace/other/same.py"], purpose="path confinement test",
        )


def test_unc_escape_and_windows_parent_traversal_are_rejected(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim(
            owner="task-unc-confinement", root=r"\\server\share\repo",
            paths=[r"\\server\share\outside\same.py"], purpose="path confinement test",
        )

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim(
            owner="task-parent-confinement", root=r"C:\workspace\repo",
            paths=[r"C:\workspace\repo\..\outside\same.py"], purpose="path confinement test",
        )


def test_posix_relative_parent_traversal_is_rejected(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError, match="repository-relative"):
        store.claim(
            owner="task-posix-confinement", root=str(repo),
            paths=["../outside/same.py"], purpose="path confinement test",
        )


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
        store.claim(
            owner="task-symlink-escape", root=str(repo), paths=["escape.py"],
            purpose="path confinement test",
        )


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

    result = store.claim(
        owner="task-symlink-inside", root=str(repo), paths=["alias.py"],
        purpose="path normalization test",
    )

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
    result = store.claim(
        owner="task-symlink-relative", root=str(repo), paths=["alias.py"],
        purpose="path normalization test",
    )

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

    first = store.claim(
        owner="task-symlink-first", root=str(repo), paths=[first_path], purpose="symlink conflict test"
    )
    second = store.claim(
        owner="task-symlink-second", root=str(repo), paths=[second_path], purpose="symlink conflict test"
    )

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
        store.claim(
            owner="task-symlink-escape", root=str(repo), paths=["escape.py"],
            purpose="path confinement test",
        )


def test_nonexistent_in_root_target_is_allowed(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "new" / "future.py"

    result = store.claim(
        owner="task-future-path", root=str(repo), paths=["new/future.py"],
        purpose="path normalization test",
    )

    assert target.exists() is False
    assert result["success"] is True
    assert result["paths"] == ["new/future.py"]


def test_foreign_windows_root_allows_repository_relative_target(tmp_path: Path):
    store = ScopeLeaseStore(tmp_path / "state")

    result = store.claim(
        owner="task-foreign-windows-root", root=r"C:\workspace\repo",
        paths=[r"src\new.py"], purpose="path normalization test",
    )

    assert result["success"] is True
    assert result["paths"] == ["src/new.py"]
