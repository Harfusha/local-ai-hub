"""Experimental per-launch Windows AppContainer profile ownership."""
from __future__ import annotations

import os
import uuid

from .opencode_pipe_identity import _valid_sid


class AppContainerProfile:
    """Own a new randomly named profile; no capabilities or ACLs are granted."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("AppContainer profiles require Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes, self._types = ctypes, wintypes
        self._userenv = ctypes.WinDLL("userenv", use_last_error=True)
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._userenv.CreateAppContainerProfile.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                             wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID)]
        self._userenv.CreateAppContainerProfile.restype = ctypes.c_long
        self._userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
        self._userenv.DeleteAppContainerProfile.restype = ctypes.c_long
        self._advapi.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
        self._advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        self._advapi.FreeSid.argtypes = [wintypes.LPVOID]
        self._advapi.FreeSid.restype = wintypes.LPVOID
        self._kernel.LocalFree.argtypes = [wintypes.LPVOID]
        self._kernel.LocalFree.restype = wintypes.LPVOID
        self.name = "LocalAIHub-" + uuid.uuid4().hex
        self.sid = None
        self._pointer = wintypes.LPVOID()
        self._created = False
        self._entered = False

    @property
    def sid_pointer(self):
        if not self._created or not self._pointer.value:
            raise RuntimeError("AppContainer SID is not available")
        return self._pointer

    def __enter__(self):
        if self._entered:
            raise RuntimeError("AppContainer profile cannot be reused")
        self._entered = True
        hr = self._userenv.CreateAppContainerProfile(self.name, self.name, self.name, None, 0,
                                                      self._ctypes.byref(self._pointer))
        if hr != 0:
            raise OSError(f"AppContainer profile creation failed: 0x{hr & 0xffffffff:08x}")
        self._created = True
        try:
            value = self._types.LPWSTR()
            if not self._advapi.ConvertSidToStringSidW(self._pointer, self._ctypes.byref(value)):
                raise OSError(self._ctypes.get_last_error(), "cannot inspect AppContainer SID")
            try:
                self.sid = value.value
            finally:
                self._kernel.LocalFree(value)
            if not _valid_sid(self.sid):
                raise RuntimeError("invalid AppContainer SID")
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        sid_release_failed = False
        if self._pointer.value:
            sid_release_failed = bool(self._advapi.FreeSid(self._pointer))
            if not sid_release_failed:
                self._pointer = self._types.LPVOID()
        if self._created:
            hr = self._userenv.DeleteAppContainerProfile(self.name)
            if hr != 0:
                raise OSError(f"AppContainer profile deletion failed: 0x{hr & 0xffffffff:08x}")
            self._created = False
        if sid_release_failed:
            raise OSError("cannot release AppContainer SID")

    def __exit__(self, *_args):
        self.close()
