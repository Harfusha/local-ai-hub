"""Unicode Windows command-line parsing without a shell."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _parser_libraries() -> tuple[Any, Any]:
    import ctypes

    if os.name != "nt":
        raise OSError("Windows command-line parsing requires Windows")
    shell = ctypes.WinDLL("shell32.dll", use_last_error=True, winmode=0x00000800)
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x00000800)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    return shell, kernel


def parse_windows_command_line(command: str) -> list[str]:
    """Parse native quoting and free the single system-owned argv allocation."""
    import ctypes

    if not isinstance(command, str) or "\x00" in command or len(command) > 32767:
        raise ValueError("invalid or oversized Windows command line")
    if not command.strip():
        return []
    shell, kernel = _parser_libraries()
    count = ctypes.c_int()
    # Broker strings allow indentation; the executable must remain argv[0].
    pointer = shell.CommandLineToArgvW(command.lstrip(), ctypes.byref(count))
    if not pointer:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(pointer, ctypes.c_void_p))
