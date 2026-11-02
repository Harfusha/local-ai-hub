import os
import uuid

import pytest

from local_ai_hub.opencode_pipe_identity import PipeIdentityError, matches_pipe_client


@pytest.mark.parametrize("sid", ["", "S-1-1-0", "S-1-15-2-1", "S-1-15-2-1-2-3-4-5-6-4294967296", "S-1-15-2-1-2-3-4-5-6-07"])
def test_rejects_invalid_container_identity(sid):
    with pytest.raises(ValueError):
        matches_pipe_client(1, sid)


@pytest.mark.parametrize("handle", [0, -1, True, None])
def test_rejects_invalid_pipe_handle(handle):
    with pytest.raises(ValueError):
        matches_pipe_client(handle, "S-1-15-2-1-2-3-4-5-6-7")


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe impersonation")
def test_same_user_without_appcontainer_is_not_authorized():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = "\\\\.\\pipe\\lah-identity-test-" + uuid.uuid4().hex
    server = kernel.CreateNamedPipeW(name, 3, 0, 1, 128, 128, 1000, None)
    assert server not in (None, ctypes.c_void_p(-1).value)
    client = kernel.CreateFileW(name, 0xC0000000, 0, None, 3, 0, None)
    assert client not in (None, ctypes.c_void_p(-1).value)
    try:
        written = wintypes.DWORD()
        assert kernel.WriteFile(client, b"x", 1, ctypes.byref(written), None)
        data = ctypes.create_string_buffer(1)
        count = wintypes.DWORD()
        assert kernel.ReadFile(server, data, 1, ctypes.byref(count), None)
        assert matches_pipe_client(server, "S-1-15-2-1-2-3-4-5-6-7") is False
    finally:
        kernel.CloseHandle(client)
        kernel.CloseHandle(server)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe impersonation")
def test_non_pipe_handle_cannot_authorize():
    with pytest.raises(PipeIdentityError, match="impersonate"):
        matches_pipe_client(1, "S-1-15-2-1-2-3-4-5-6-7")
