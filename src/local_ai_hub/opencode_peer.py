"""Windows connection ownership checks for the experimental OpenCode bridge."""
from __future__ import annotations

import ctypes
import json
import os
import socket
from pathlib import Path
from typing import Any

from .process_utils import process_owner_state


class PeerIdentityError(OSError):
    """The exact connected peer could not be matched to managed Ollama."""


def _connected_server_pid(connection: socket.socket) -> int:
    if os.name != "nt" or connection.family != socket.AF_INET:
        raise PeerIdentityError("Windows IPv4 peer identity is unavailable")
    from ctypes import wintypes

    local_host, local_port = connection.getsockname()[:2]
    remote_host, remote_port = connection.getpeername()[:2]
    if local_host != "127.0.0.1" or remote_host != "127.0.0.1":
        raise PeerIdentityError("peer is not IPv4 loopback")

    class Row(ctypes.Structure):
        _fields_ = [("state", wintypes.DWORD), ("local_addr", wintypes.DWORD),
                    ("local_port", wintypes.DWORD), ("remote_addr", wintypes.DWORD),
                    ("remote_port", wintypes.DWORD), ("pid", wintypes.DWORD)]

    try:
        api = ctypes.WinDLL("iphlpapi", use_last_error=True)
        query = api.GetExtendedTcpTable
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                          wintypes.ULONG, wintypes.ULONG, wintypes.ULONG]
        query.restype = wintypes.DWORD
        size = wintypes.DWORD(0)
        result = query(None, ctypes.byref(size), False, socket.AF_INET, 4, 0)
        if result != 122 or not 4 <= size.value <= 16 * 1024 * 1024:
            raise PeerIdentityError("TCP ownership table unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        if query(buffer, ctypes.byref(size), False, socket.AF_INET, 4, 0) != 0:
            raise PeerIdentityError("TCP ownership table changed or is unavailable")
        count = int.from_bytes(buffer.raw[:4], "little")
        row_size = ctypes.sizeof(Row)
        if count > 500_000 or 4 + count * row_size > size.value:
            raise PeerIdentityError("invalid TCP ownership table")
        expected_local = int.from_bytes(socket.inet_aton(remote_host), "little")
        expected_remote = int.from_bytes(socket.inet_aton(local_host), "little")
        matches = set()
        for index in range(count):
            row = Row.from_buffer_copy(buffer, 4 + index * row_size)
            if (row.state == 5 and row.local_addr == expected_local and row.remote_addr == expected_remote
                    and socket.ntohs(row.local_port & 0xffff) == remote_port
                    and socket.ntohs(row.remote_port & 0xffff) == local_port and row.pid > 0):
                matches.add(int(row.pid))
        if len(matches) != 1:
            raise PeerIdentityError("connected server process is ambiguous or unavailable")
        return matches.pop()
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, PeerIdentityError):
            raise
        raise PeerIdentityError("TCP peer ownership lookup failed") from exc


def _read_owner(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "ollama.owner.json"
    try:
        if path.is_symlink():
            raise ValueError("owner record is a symlink")
        with path.open("rb") as stream:
            raw = stream.read(16_385)
        if len(raw) > 16_384:
            raise ValueError("owner record too large")
        owner = json.loads(raw)
        if not isinstance(owner, dict) or type(owner.get("pid")) is not int or owner["pid"] <= 0:
            raise ValueError("invalid owner record")
        return owner
    except (OSError, ValueError, UnicodeError) as exc:
        raise PeerIdentityError("managed Ollama ownership is unavailable") from exc


def verify_supervised_peer(connection: socket.socket, state_dir: Path) -> None:
    """Match the established TCP peer to the current supervised owner record."""
    state_dir = Path(state_dir)
    owner = _read_owner(state_dir)
    if process_owner_state(owner, state_dir, "ollama") != "owned":
        raise PeerIdentityError("managed Ollama process identity is unverified")
    if _connected_server_pid(connection) != owner["pid"]:
        raise PeerIdentityError("TCP peer is not the managed Ollama process")
    if _read_owner(state_dir) != owner or process_owner_state(owner, state_dir, "ollama") != "owned":
        raise PeerIdentityError("managed Ollama ownership changed during verification")
