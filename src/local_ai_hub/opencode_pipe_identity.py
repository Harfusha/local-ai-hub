"""Experimental Windows pipe identity check; not yet a dispatch service.

Call only on the server end after reading a bounded initial byte. Windows
impersonates the security context of the last message read from that pipe.
"""
from __future__ import annotations

import os
import re


class PipeIdentityError(RuntimeError):
    """The client token could not be inspected or impersonation reverted."""


def _valid_sid(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"S-1-15-2-(?:[0-9]+-){6}[0-9]+", value):
        return False
    parts = value.split("-")[4:]
    return all((part == "0" or not part.startswith("0")) and int(part) <= 0xFFFFFFFF for part in parts)


def matches_pipe_client(pipe_handle: int, expected_sid: str) -> bool:
    """Check the impersonated client token against one AppContainer SID.

    The caller must discard unauthenticated input and never dispatch when this
    returns false or raises. A failed revert is an error, never authorization.
    """
    if type(pipe_handle) is not int or pipe_handle <= 0:
        raise ValueError("invalid pipe handle")
    if not _valid_sid(expected_sid):
        raise ValueError("invalid AppContainer SID")
    if os.name != "nt":
        raise PipeIdentityError("Windows named-pipe identity is unavailable")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    advapi.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi.ImpersonateNamedPipeClient.argtypes = [wintypes.HANDLE]
    advapi.ImpersonateNamedPipeClient.restype = wintypes.BOOL
    advapi.OpenThreadToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenThreadToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi.EqualSid.restype = wintypes.BOOL
    advapi.RevertToSelf.argtypes = []
    advapi.RevertToSelf.restype = wintypes.BOOL
    kernel.GetCurrentThread.argtypes = []
    kernel.GetCurrentThread.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [wintypes.LPVOID]

    expected = wintypes.LPVOID()
    if not advapi.ConvertStringSidToSidW(expected_sid, ctypes.byref(expected)):
        raise PipeIdentityError("cannot resolve AppContainer SID")
    try:
        if not advapi.ImpersonateNamedPipeClient(pipe_handle):
            raise PipeIdentityError("cannot impersonate pipe client")
        token = wintypes.HANDLE()
        try:
            if not advapi.OpenThreadToken(kernel.GetCurrentThread(), 0x0008, True, ctypes.byref(token)):
                raise PipeIdentityError("cannot inspect pipe client token")
            size = wintypes.DWORD()
            container = wintypes.DWORD()
            if not advapi.GetTokenInformation(token, 29, ctypes.byref(container), ctypes.sizeof(container), ctypes.byref(size)):
                raise PipeIdentityError("cannot inspect AppContainer status")
            if container.value != 1:
                return False
            size = wintypes.DWORD()
            ctypes.set_last_error(0)
            if advapi.GetTokenInformation(token, 31, None, 0, ctypes.byref(size)) or ctypes.get_last_error() != 122 or not 0 < size.value <= 65536:
                raise PipeIdentityError("cannot size AppContainer identity")
            data = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, 31, data, size.value, ctypes.byref(size)):
                raise PipeIdentityError("cannot inspect AppContainer identity")
            actual = ctypes.cast(data, ctypes.POINTER(wintypes.LPVOID)).contents
            return bool(actual.value) and bool(advapi.EqualSid(expected, actual))
        finally:
            if token.value:
                kernel.CloseHandle(token)
            if not advapi.RevertToSelf():
                raise PipeIdentityError("cannot revert pipe client impersonation")
    finally:
        kernel.LocalFree(expected)
