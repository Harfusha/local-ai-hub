import os
from pathlib import Path

import pytest

from local_ai_hub.opencode_appcontainer import AppContainerProfile
from local_ai_hub.opencode_pipe_identity import _valid_sid

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AppContainer")


def test_temporary_profiles_have_distinct_sids_and_are_closed():
    import ctypes
    from ctypes import wintypes

    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    userenv.GetAppContainerFolderPath.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR)]
    userenv.GetAppContainerFolderPath.restype = ctypes.c_long
    kernel.LocalFree.argtypes = [wintypes.LPVOID]
    with AppContainerProfile() as first, AppContainerProfile() as second:
        assert _valid_sid(first.sid) and _valid_sid(second.sid)
        assert first.sid != second.sid and first.name != second.name
        assert first.sid_pointer and second.sid_pointer
        folder_pointer = wintypes.LPWSTR()
        assert userenv.GetAppContainerFolderPath(first.sid, ctypes.byref(folder_pointer)) == 0
        try:
            folder = Path(folder_pointer.value)
            assert folder.is_dir()
        finally:
            kernel.LocalFree(folder_pointer)
        with pytest.raises(RuntimeError):
            first.__enter__()
    with pytest.raises(RuntimeError):
        _ = first.sid_pointer
    with pytest.raises(RuntimeError):
        first.__enter__()
    assert not folder.exists()


def test_failed_deletion_remains_visible_and_can_be_recovered():
    from types import SimpleNamespace

    profile = AppContainerProfile().__enter__()
    native = profile._userenv
    profile._userenv = SimpleNamespace(DeleteAppContainerProfile=lambda _name: 0x80004005)
    try:
        with pytest.raises(OSError, match="profile deletion failed"):
            profile.close()
        assert profile._created is True
        with pytest.raises(RuntimeError):
            _ = profile.sid_pointer
    finally:
        profile._userenv = native
        profile.close()
