import os
import threading

import pytest

from local_ai_hub.opencode_winpipe import WindowsPipeListener

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows named pipes")
SID = "S-1-15-2-1-2-3-4-5-6-7"


def test_listener_wait_and_idle_read_are_bounded():
    with WindowsPipeListener(SID) as listener:
        with pytest.raises(TimeoutError):
            listener.accept(timeout=0.05)


def test_same_user_is_rejected_and_message_io_is_bounded():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    with WindowsPipeListener(SID) as listener:
        client = kernel.CreateFileW(listener.name, 0x0012019B, 0, None, 3, 0, None)
        assert client not in (None, ctypes.c_void_p(-1).value)
        try:
            pipe = listener.accept(timeout=1)
            try:
                assert pipe.read(32, 0.05) == b""
                sent = wintypes.DWORD()
                assert kernel.WriteFile(client, b"hello", 5, ctypes.byref(sent), None)
                assert pipe.read(32, 1) == b"hello"
                assert pipe.matches_identity() is False
                pipe.write(b"reply", 1)
                data = ctypes.create_string_buffer(5)
                count = wintypes.DWORD()
                assert kernel.ReadFile(client, data, 5, ctypes.byref(count), None)
                assert data.raw[:count.value] == b"reply"
            finally:
                pipe.close()
        finally:
            kernel.CloseHandle(client)


def test_listener_can_be_cancelled_without_a_client():
    stop = threading.Event()
    with WindowsPipeListener(SID) as listener:
        stop.set()
        with pytest.raises(InterruptedError):
            listener.accept(timeout=1, stop=stop)


def test_client_disconnect_before_accept_keeps_listener_available():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    with WindowsPipeListener(SID) as listener:
        client = kernel.CreateFileW(listener.name, 0x0012019B, 0, None, 3, 0, None)
        assert client not in (None, ctypes.c_void_p(-1).value)
        kernel.CloseHandle(client)
        with pytest.raises(TimeoutError):
            listener.accept(timeout=0.1)
        accepted = []
        worker = threading.Thread(target=lambda: accepted.append(listener.accept(timeout=2)))
        worker.start()
        kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        assert kernel.WaitNamedPipeW(listener.name, 1000)
        client = kernel.CreateFileW(listener.name, 0x0012019B, 0, None, 3, 0, None)
        assert client not in (None, ctypes.c_void_p(-1).value)
        worker.join(timeout=2)
        assert len(accepted) == 1
        accepted[0].close()
        kernel.CloseHandle(client)


def test_listener_retains_exclusive_name_across_connections():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel.WaitNamedPipeW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = ctypes.c_void_p(-1).value
    with WindowsPipeListener(SID) as listener:
        for _ in range(2):
            accepted = []
            worker = threading.Thread(target=lambda: accepted.append(listener.accept(timeout=2)))
            worker.start()
            assert kernel.WaitNamedPipeW(listener.name, 1000)
            client = kernel.CreateFileW(listener.name, 0x0012019B, 0, None, 3, 0, None)
            assert client not in (None, invalid)
            worker.join(timeout=2)
            assert len(accepted) == 1
            pipe = accepted[0]
            with pytest.raises(RuntimeError):
                listener.accept(timeout=0.1)
            pipe.close()
            kernel.CloseHandle(client)
            competing = kernel.CreateNamedPipeW(listener.name, 3 | 0x00080000, 1 | 2 | 4 | 8, 1, 65536, 65536, 1000, None)
            if competing not in (None, invalid):
                kernel.CloseHandle(competing)
            assert competing == invalid
