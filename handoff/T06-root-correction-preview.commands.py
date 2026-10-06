from __future__ import annotations

import ast
import base64
import codecs
import getpass
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
import re
import ntpath
import queue
import shlex
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from functools import wraps
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from .cache import SQLiteCache, TieredCache, stable_hash
from .command_transactions import (
    create_private_transaction_snapshot_with_manifest,
    validate_transaction_output,
    verify_transaction_source_unchanged,
)
from .leases import ScopeLeaseStore
from .features import rollout_feature_enabled
from .process_utils import (
    _resume_suspended_process,
    assign_process_to_job,
    canonical_root,
    close_job_object,
    create_job_object_kill_on_close,
    hidden_run_kwargs,
    process_identity,
    terminate_job_object,
    terminate_tree,
)
from .state_paths import configured_state_dir
from .json_utils import dumps as json_dumps

_GLOBAL_WINDOWS_JOB = create_job_object_kill_on_close() if os.name == "nt" else None
_PROJECT_COMMAND_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_PROJECT_COMMAND_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROJECT_COMMAND_ENV_BLOCKED = {
    "BASH_ENV",
    "COMSPEC",
    "ENV",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_PREFIX",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "PATH",
    "PATHEXT",
    "SHELL",
}


def _is_unsafe_project_command_env_key(key: str) -> bool:
    normalized = key.upper()
    return normalized in _PROJECT_COMMAND_ENV_BLOCKED or normalized.startswith("GIT_CONFIG_")
_MAX_PROJECT_COMMAND_ARGS = 128
_MAX_PROJECT_COMMAND_ENV_ENTRIES = 128
_MAX_PROJECT_COMMAND_ENV_BYTES = 65_536
_COMMAND_LOG_QUEUE_MAX_CHUNKS = 256

_NETWORK_RESPONSE_HEADER_ALLOWLIST = {
    "cache-control",
    "content-length",
    "content-type",
    "date",
}
_NETWORK_SECRET_RE = re.compile(
    r'''(?i)(["']?(?:access[_-]?token|api[_-]?key|authorization|client[_-]?secret|password|refresh[_-]?token|secret|token)["']?\s*[:=]\s*["']?)([^"'\s,;}\]]+)'''
)
_NETWORK_AUTH_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_NETWORK_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_CASSETTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DNS_RESOLVER_SLOTS = threading.BoundedSemaphore(4)
_MAX_CASSETTE_BYTES = 1_048_576


class _RecoveredDaemonProcess:
    """Minimal poll/wait/kill facade for a daemon verified after a Hub restart."""

    def __init__(self, pid: int, identity: dict[str, Any]):
        self.pid = pid
        self.identity = identity

    def poll(self) -> int | None:
        return None if process_identity(self.pid) == self.identity else 0

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(f"pid {self.pid}", timeout)
            time.sleep(0.025)
        return 0

    def kill(self) -> None:
        if self.poll() is None:
            terminate_tree(self.pid, grace_seconds=0.1)

_SECRET_PATTERNS = [
    re.compile(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+"),
    re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{16,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(aws_secret_access_key\s*=\s*)([^\s]+)"),
]

_DIAGNOSTIC_PATTERNS = [
    re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+)(?::(?P<col>\d+))?[:\s]+(?P<msg>.+)$"),
    re.compile(r"^FAILED\s+(?P<path>[^:\s]+)(?:::(?P<msg>.+))?$"),
]

_MAX_INVOCATION_ERROR_CHARS = 256
_MAX_ROLLBACK_PATHS = 128
_MAX_ROLLBACK_FILE_BYTES = 16 * 1024 * 1024
_MAX_ROLLBACK_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_ROLLBACK_METADATA_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _NetworkPolicyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        object.__setattr__(self, "code", code)
class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port), self.timeout, self.source_address
        )
class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
def _network_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("network", {})
    return value if isinstance(value, dict) else {}
def _network_limit(network: dict[str, Any], name: str, default: int, maximum: int) -> int:
    try:
        value = int(network.get(name, default))
    except (TypeError, ValueError, OverflowError):
        value = default
    return min(maximum, max(1, value))
def _redirect_limit(network: dict[str, Any]) -> int:
    try:
        value = int(network.get("max_redirects", 3))
    except (TypeError, ValueError, OverflowError):
        value = 3
    return min(5, max(0, value))
def _private_network_allowed(host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address, scopes: Any) -> bool:
    if isinstance(scopes, str):
        scopes = [scopes]
    if not isinstance(scopes, (list, tuple, set)):
        return False
    normalized_host = host.rstrip(".").lower()
    for raw_scope in scopes:
        if not isinstance(raw_scope, str):
            continue
        scope = raw_scope.strip()
        if not scope:
            continue
        if scope.rstrip(".").lower() == normalized_host:
            return True
        try:
            network = ipaddress.ip_network(scope, strict=False)
        except ValueError:
            continue
        if address in network:
            return True
    return False
def _bounded_getaddrinfo(host: str, port: int, timeout: float) -> list[tuple[Any, ...]]:
    deadline = time.monotonic() + max(0.0, timeout)
    if not _DNS_RESOLVER_SLOTS.acquire(timeout=max(0.0, timeout)):
        raise _NetworkPolicyError("network_timeout", "Network name resolution timed out")
    outcome: dict[str, Any] = {}
    completed = threading.Event()

    def resolve() -> None:
        try:
            outcome["addresses"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            _DNS_RESOLVER_SLOTS.release()
            completed.set()

    worker = threading.Thread(target=resolve, name="local-ai-network-dns", daemon=True)
    try:
        worker.start()
    except RuntimeError as exc:
        _DNS_RESOLVER_SLOTS.release()
        raise _NetworkPolicyError("network_dns_failed", "Network target could not be resolved") from exc
    if not completed.wait(max(0.0, deadline - time.monotonic())):
        raise _NetworkPolicyError("network_timeout", "Network name resolution timed out")
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("addresses", [])

def _resolve_network_target(
    config: dict[str, Any], url: str, timeout: float
) -> tuple[str, str, int, str, str, str]:
    network = _network_config(config)
    if not isinstance(url, str) or len(url) > 8192:
        raise _NetworkPolicyError("invalid_network_url", "URL is invalid or exceeds its size limit")
    try:
        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        explicit_port = parsed.port
        port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
    except ValueError:
        raise _NetworkPolicyError("invalid_network_url", "URL is invalid") from None
    if scheme not in {"http", "https"} or not hostname or parsed.username is not None or parsed.password is not None:
        raise _NetworkPolicyError("invalid_network_url", "Only credential-free HTTP and HTTPS URLs are allowed")
    if not 1 <= port <= 65535 or "%" in hostname:
        raise _NetworkPolicyError("invalid_network_url", "URL host or port is invalid")
    try:
        host = hostname.encode("idna").decode("ascii").rstrip(".").lower()
        addresses = _bounded_getaddrinfo(host, port, timeout)
    except _NetworkPolicyError:
        raise
    except (UnicodeError, OSError, ValueError):
        raise _NetworkPolicyError("network_dns_failed", "Network target could not be resolved") from None
    resolved: list[str] = []
    scopes = network.get("allow_private_hosts", [])
    for family, _socktype, _proto, _canonname, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        raw_address = str(sockaddr[0])
        if "%" in raw_address:
            raise _NetworkPolicyError("network_scope_denied", "Scoped IPv6 targets are not allowed")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            raise _NetworkPolicyError("network_dns_failed", "Network target returned an invalid address") from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global and not _private_network_allowed(host, address, scopes):
            raise _NetworkPolicyError("network_scope_denied", "Private network target is outside configured scope")
        candidate = str(address)
        if candidate not in resolved:
            resolved.append(candidate)
    if not resolved:
        raise _NetworkPolicyError("network_dns_failed", "Network target returned no usable addresses")
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return scheme, host, port, resolved[0], path, parsed.geturl()
def _validated_network_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {"User-Agent": "LocalAIHub/1.0", "Connection": "close"}
    if not isinstance(headers, Mapping) or len(headers) > 64:
        raise _NetworkPolicyError("invalid_network_headers", "Request headers must be a small object")
    result: dict[str, str] = {"Connection": "close"}
    total = 0
    forbidden = {"connection", "content-length", "host", "proxy-authorization", "transfer-encoding"}
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or not _NETWORK_HEADER_NAME_RE.fullmatch(raw_name):
            raise _NetworkPolicyError("invalid_network_headers", "Request header name is invalid")
        name = raw_name.strip()
        value = str(raw_value)
        if name.lower() in forbidden or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise _NetworkPolicyError("invalid_network_headers", "Request header is not allowed")
        total += len(name.encode("ascii")) + len(value.encode("utf-8"))
        if len(value) > 8192 or total > 16384:
            raise _NetworkPolicyError("invalid_network_headers", "Request headers exceed configured bounds")
        result[name] = value
    return result
def _redact_network_text(value: str) -> str:
    redacted = _NETWORK_SECRET_RE.sub(r"\1[redacted]", value)
    return _NETWORK_AUTH_RE.sub(r"\1 [redacted]", redacted)
def _safe_network_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parsed.port
        authority = host if port is None else f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), authority, parsed.path, "", ""))[:2048]
    except (TypeError, ValueError):
        return ""


def _safe_response_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(name).lower(): str(value)[:1024]
        for name, value in headers.items()
        if str(name).lower() in _NETWORK_RESPONSE_HEADER_ALLOWLIST
    }
def _perform_network_request(
    config: dict[str, Any],
    url: str,
    *,
    method: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
    max_response_bytes: int,
    follow_redirects: bool,
) -> tuple[int, dict[str, str], bytes]:
    network = _network_config(config)
    max_redirects = _redirect_limit(network)
    deadline = time.monotonic() + max(0.0, timeout)
    try:
        initial_scheme = urlsplit(url).scheme.lower()
    except ValueError:
        raise _NetworkPolicyError("invalid_network_url", "URL is invalid") from None
    current_url = url
    redirects = 0
    previous_origin: tuple[str, str, int] | None = None
    request_headers = dict(headers)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _NetworkPolicyError("network_timeout", "Network request timed out")
        scheme, host, port, address, path, _ = _resolve_network_target(config, current_url, remaining)
        if initial_scheme == "https" and scheme != "https":
            raise _NetworkPolicyError("network_redirect_downgrade", "HTTPS redirects cannot downgrade to HTTP")
        origin = (scheme, host, port)
        if previous_origin is not None and origin != previous_origin:
            request_headers = {"Connection": "close"}
        connection_type = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _NetworkPolicyError("network_timeout", "Network request timed out")
        connection = connection_type(host, port, address, remaining)
        timed_out = threading.Event()

        def abort_request() -> None:
            timed_out.set()
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

        timer = threading.Timer(remaining, abort_request)
        timer.daemon = True
        timer.start()
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            status = int(response.status)
            response_headers = {str(name).lower(): str(value) for name, value in response.getheaders()}
            location = response_headers.get("location", "")
            if follow_redirects and method == "GET" and status in {301, 302, 303, 307, 308} and location:
                if redirects >= max_redirects:
                    raise _NetworkPolicyError("network_redirect_limit", "Network redirect limit reached")
                current_url = urljoin(current_url, location)
                redirects += 1
                previous_origin = origin
                continue
            response_body = response.read(max_response_bytes + 1)
            if timed_out.is_set():
                raise _NetworkPolicyError("network_timeout", "Network request timed out")
            return status, response_headers, response_body
        except _NetworkPolicyError:
            raise
        except Exception:
            if timed_out.is_set():
                raise _NetworkPolicyError("network_timeout", "Network request timed out") from None
            raise
        finally:
            timer.cancel()
            connection.close()

@dataclass(frozen=True)
class RollbackFileSnapshot:
    content: bytes | None
    mode: int | None
    xattrs: dict[str, bytes]
    windows_dacl: bytes | None
    atime_ns: int | None
    mtime_ns: int | None


@dataclass(frozen=True)
class RollbackSnapshot:
    root: Path
    root_identity: tuple[int, int]
    files: dict[str, RollbackFileSnapshot]
    root_guard: int
    postimages: dict[str, "RollbackPostimage"] = field(default_factory=dict)


@dataclass(frozen=True)
class RollbackPostimage:
    safe: bool
    fingerprint: tuple[int, int, int, int, int, int, str, str] | None
    reason: str = ""


def _get_windows_dacl(fd: int) -> bytes:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_security_info = advapi32.GetSecurityInfo
    get_security_info.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    get_security_info.restype = wintypes.DWORD
    descriptor = ctypes.c_void_p()
    status = get_security_info(msvcrt.get_osfhandle(fd), 1, 0x4, None, None, None, None, ctypes.byref(descriptor))
    if status:
        raise OSError(status, "cannot snapshot rollback target DACL")
    try:
        advapi32.GetSecurityDescriptorLength.argtypes = [ctypes.c_void_p]
        advapi32.GetSecurityDescriptorLength.restype = wintypes.DWORD
        length = int(advapi32.GetSecurityDescriptorLength(descriptor))
        if length <= 0 or length > _MAX_ROLLBACK_METADATA_BYTES:
            raise OSError("rollback target DACL exceeds metadata limit")
        return ctypes.string_at(descriptor, length)
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(descriptor)


def _set_windows_dacl(fd: int, descriptor: bytes) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.SetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    advapi32.SetKernelObjectSecurity.restype = wintypes.BOOL
    security_descriptor = ctypes.create_string_buffer(descriptor)
    if not advapi32.SetKernelObjectSecurity(msvcrt.get_osfhandle(fd), 0x4, security_descriptor):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target DACL")


def _restore_windows_file_attributes(fd: int, mode: int | None) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation_time", ctypes.c_int64),
            ("last_access_time", ctypes.c_int64),
            ("last_write_time", ctypes.c_int64),
            ("change_time", ctypes.c_int64),
            ("file_attributes", wintypes.DWORD),
        ]

    set_information = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    set_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    set_information.restype = wintypes.BOOL
    attributes = 0x00000001 if mode is not None and not mode & stat.S_IWRITE else 0x00000080
    basic_info = FileBasicInfo(0, 0, 0, 0, attributes)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    if not set_information(handle, 0, ctypes.byref(basic_info), ctypes.sizeof(basic_info)):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target attributes")


def _restore_windows_file_times(fd: int, atime_ns: int | None, mtime_ns: int | None) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def to_filetime(value: int | None) -> FileTime | None:
        if value is None:
            return None
        ticks = (int(value) + 11644473600 * 1_000_000_000) // 100
        return FileTime(ticks & 0xFFFFFFFF, ticks >> 32)

    access_time, write_time = to_filetime(atime_ns), to_filetime(mtime_ns)
    set_file_time = ctypes.WinDLL("kernel32", use_last_error=True).SetFileTime
    set_file_time.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    set_file_time.restype = wintypes.BOOL
    if not set_file_time(
        msvcrt.get_osfhandle(fd), None,
        ctypes.byref(access_time) if access_time is not None else None,
        ctypes.byref(write_time) if write_time is not None else None,
    ):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target file times")


def _delete_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    set_information = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    set_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    set_information.restype = wintypes.BOOL
    delete = ctypes.c_ubyte(1)
    if not set_information(wintypes.HANDLE(handle), 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise OSError(ctypes.get_last_error(), "cannot remove rollback target by handle")


def _rename_windows_handle(handle: int, parent_handle: int, name: str) -> None:
    import ctypes
    from ctypes import wintypes

    class RenameFlags(ctypes.Union):
        _fields_ = [("replace_if_exists", wintypes.BOOLEAN), ("flags", wintypes.DWORD)]

    class FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("rename_flags", RenameFlags),
            ("replace_if_exists_legacy", wintypes.BOOLEAN),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        ]

    encoded_name = name.encode("utf-16-le")
    info_size = ctypes.sizeof(FileRenameInfo) + len(encoded_name)
    info_buffer = ctypes.create_string_buffer(info_size)
    info = ctypes.cast(info_buffer, ctypes.POINTER(FileRenameInfo)).contents
    info.rename_flags.replace_if_exists = 1
    info.replace_if_exists_legacy = 1
    info.root_directory = wintypes.HANDLE(parent_handle)
    info.file_name_length = len(encoded_name)
    ctypes.memmove(ctypes.addressof(info_buffer) + FileRenameInfo.file_name.offset, encoded_name, len(encoded_name))

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

    ntdll = ctypes.WinDLL("ntdll")
    set_information = ntdll.NtSetInformationFile
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
    ]
    set_information.restype = wintypes.LONG
    io_status = IoStatusBlock()
    status = int(set_information(wintypes.HANDLE(handle), ctypes.byref(io_status), info_buffer, info_size, 10))
    if status < 0:
        status_to_error = ntdll.RtlNtStatusToDosError
        status_to_error.argtypes = [wintypes.LONG]
        status_to_error.restype = wintypes.ULONG
        raise OSError(int(status_to_error(status)), "cannot install rollback target by handle")


def _windows_dacl_bytes(descriptor: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(descriptor)
    present, dacl, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
    if not get_dacl(buffer, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise OSError(ctypes.get_last_error(), "cannot inspect rollback DACL")
    if not present.value:
        return b"absent"
    if not dacl.value:
        return b"null"
    header = ctypes.string_at(dacl, 4)
    return ctypes.string_at(dacl, int.from_bytes(header[2:4], "little"))


def _acquire_rollback_root(root: Path) -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        root_access = 0x0001 | 0x0080 | 0x00100000
        if len(root.parts) == 1:
            root_access |= 0x0002 | 0x0040
        handle = kernel32.CreateFileW(
            str(root.anchor),
            root_access,
            0x1 | 0x2,  # share read/write; omit delete sharing to pin the root
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "cannot pin rollback volume root")
        current = int(handle)
        try:
            attributes, _reparse_tag = _windows_handle_attributes(current)
            if attributes & 0x400:
                raise ValueError("rollback volume root cannot be a reparse point")
            if not attributes & 0x10:
                raise ValueError("rollback volume root is not a directory")
            components = root.parts[1:]
            for index, component in enumerate(components):
                child = _open_rollback_relative_handle(
                    current,
                    component,
                    directory=True,
                    mutation=index == len(components) - 1,
                )
                if child is None:
                    raise FileNotFoundError(f"rollback root component is missing: {component}")
                try:
                    _close_rollback_root(current)
                except BaseException:
                    _close_rollback_root(child)
                    raise
                current = child
            return current
        except BaseException:
            try:
                _close_rollback_root(current)
            except OSError:
                pass
            raise
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("safe rollback-root acquisition requires O_NOFOLLOW support")
    anchor_fd = os.open(
        root.anchor,
        os.O_RDONLY | nofollow | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        root_handle, _owned = _open_rollback_parent_handle(anchor_fd, list(root.parts[1:]))
        return root_handle
    finally:
        os.close(anchor_fd)


def _close_rollback_root(handle: int) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(handle):
            raise OSError(ctypes.get_last_error(), "cannot close rollback root handle")
    else:
        os.close(handle)


def _rollback_snapshot_open_flags() -> int:
    flags = os.O_RDONLY | (getattr(os, "O_NOFOLLOW", 0) if os.name != "nt" else getattr(os, "O_BINARY", 0))
    if os.name != "nt":
        flags |= getattr(os, "O_NOATIME", 0)
    return flags


def _rollback_root_identity(handle: int) -> tuple[int, int]:
    if os.name == "nt":
        return _windows_handle_identity(handle)
    root_stat = os.fstat(handle)
    return root_stat.st_dev, root_stat.st_ino


def _windows_handle_attributes(handle: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    tag_info = FileAttributeTagInfo()
    if not get_info(handle, 9, ctypes.byref(tag_info), ctypes.sizeof(tag_info)):
        raise OSError(ctypes.get_last_error(), "cannot inspect rollback handle attributes")
    return int(tag_info.FileAttributes), int(tag_info.ReparseTag)


def _windows_handle_identity(handle: int) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_low", wintypes.DWORD), ("creation_high", wintypes.DWORD),
            ("access_low", wintypes.DWORD), ("access_high", wintypes.DWORD),
            ("write_low", wintypes.DWORD), ("write_high", wintypes.DWORD),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    get_info.restype = wintypes.BOOL
    info = FileInfo()
    if not get_info(handle, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "cannot verify pinned rollback root identity")
    index = (int(info.index_high) << 32) | int(info.index_low)
    return int(info.volume), index


def _open_rollback_relative_handle(
    root_handle: int,
    name: str,
    *,
    directory: bool,
    mutation: bool = False,
    create: bool = False,
) -> int | None:
    """Open one root-relative child without following reparse points."""
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    name_buffer = ctypes.create_unicode_buffer(name)
    name_bytes = len(name.encode("utf-16-le"))
    unicode_name = UnicodeString(name_bytes, name_bytes + 2, ctypes.cast(name_buffer, wintypes.LPWSTR))
    object_attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(root_handle),
        ctypes.pointer(unicode_name),
        0x40,  # OBJ_CASE_INSENSITIVE
        None,
        None,
    )
    io_status = IoStatusBlock()
    handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    nt_create_file.restype = wintypes.LONG
    desired_access = (
        0x0001 | 0x0020 | 0x0080 | 0x00100000
        if directory
        else 0x0001 | 0x0080 | 0x0100 | 0x00020000 | 0x00100000
    )
    if mutation:
        desired_access |= (0x0002 | 0x0040) if directory else (0x00010000 | 0x00040000)
    if create and not directory:
        desired_access |= 0x0002
    create_options = 0x20 | 0x00200000 | (0x1 if directory else 0)
    status = int(
        nt_create_file(
            ctypes.byref(handle), desired_access, ctypes.byref(object_attributes),
            ctypes.byref(io_status), None, 0, 0x1 | 0x2, 2 if create else 1, create_options, None, 0,
        )
    )
    status_code = status & 0xFFFFFFFF
    if status_code in {0xC0000034, 0xC000003A}:
        return None
    if create and status_code == 0xC0000035:
        raise FileExistsError(f"rollback temporary path already exists: {name[:160]}")
    if status < 0:
        status_to_error = ntdll.RtlNtStatusToDosError
        status_to_error.argtypes = [wintypes.LONG]
        status_to_error.restype = wintypes.ULONG
        raise OSError(int(status_to_error(status)), "cannot open rollback path relative to pinned root")

    raw_handle = int(handle.value)
    try:
        attributes, _reparse_tag = _windows_handle_attributes(raw_handle)
        if attributes & 0x400:
            raise ValueError("rollback paths cannot be reparse points")
        if directory and not attributes & 0x10:
            raise ValueError("rollback root path component is not a directory")
        if not directory and attributes & 0x10:
            raise ValueError("rollback target is a directory")
        return raw_handle
    except BaseException:
        _close_rollback_root(raw_handle)
        raise


def _open_rollback_parent_handle(
    root_handle: int,
    components: list[str],
    *,
    mutation: bool = False,
) -> tuple[int, bool]:
    """Open parent directory by walking each component from a pinned root."""
    if os.name == "nt":
        current = root_handle
        owned = False
        try:
            for index, component in enumerate(components):
                child = _open_rollback_relative_handle(
                    current,
                    component,
                    directory=True,
                    mutation=mutation and index == len(components) - 1,
                )
                if child is None:
                    raise FileNotFoundError(f"rollback parent component is missing: {component}")
                if owned:
                    try:
                        _close_rollback_root(current)
                    except BaseException:
                        _close_rollback_root(child)
                        raise
                current = child
                owned = True
            return current, owned
        except BaseException:
            if owned:
                try:
                    _close_rollback_root(current)
                except OSError:
                    pass
            raise

    current = os.dup(root_handle)
    try:
        for component in components:
            nofollow = getattr(os, "O_NOFOLLOW", None)
            if nofollow is None:
                raise OSError("safe nested rollback paths require O_NOFOLLOW support")
            flags = os.O_RDONLY | nofollow | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            child = os.open(component, flags, dir_fd=current)
            try:
                child_stat = os.fstat(child)
            except BaseException:
                os.close(child)
                raise
            if not stat.S_ISDIR(child_stat.st_mode):
                os.close(child)
                raise ValueError("rollback parent component is not a directory")
            os.close(current)
            current = child
        return current, True
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _open_rollback_snapshot_file(root_handle: int, name: str) -> int | None:
    import msvcrt

    raw_handle = _open_rollback_relative_handle(root_handle, name, directory=False)
    if raw_handle is None:
        return None
    try:
        return msvcrt.open_osfhandle(raw_handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _close_rollback_root(raw_handle)
        raise
def _restore_windows_atime(fd: int, atime_ns: int) -> None:
    """Restore access time through the already pinned snapshot handle."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetFileTime.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
    ]
    kernel32.SetFileTime.restype = wintypes.BOOL
    windows_epoch_ns = 11644473600 * 1_000_000_000
    filetime_value = (int(atime_ns) + windows_epoch_ns) // 100
    access_time = _FileTime(filetime_value & 0xFFFFFFFF, filetime_value >> 32)
    if not kernel32.SetFileTime(msvcrt.get_osfhandle(fd), None, ctypes.byref(access_time), None):
        raise OSError(ctypes.get_last_error(), "cannot restore rollback target access time")


def _wait_windows_job_empty(job_handle: Any, timeout_ms: int = 2500) -> bool:
    """Wait until Windows signals that a daemon Job Object has no live processes."""
    if os.name != "nt" or not job_handle:
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return int(kernel32.WaitForSingleObject(wintypes.HANDLE(job_handle), max(0, int(timeout_ms)))) == 0


def _stop_daemon_tree(info: dict[str, Any]) -> bool:
    """Stop the owned daemon tree without signaling a recycled Windows PID."""
    process = info["process"]
    job_handle = getattr(process, "_local_ai_job_handle", None)
    if os.name == "nt" and isinstance(job_handle, int) and not isinstance(job_handle, bool):
        try:
            terminate_job_object(job_handle)
            if not _wait_windows_job_empty(job_handle):
                return False
            if not close_job_object(job_handle):
                return False
            process._local_ai_job_handle = None
            return True
        except Exception:
            return False
    if os.name == "nt":
        expected = info.get("identity")
        current = process_identity(int(info["pid"]))
        if current is None:
            return True
        if expected and current != expected:
            return False
    try:
        return bool(terminate_tree(int(info["pid"]), grace_seconds=1.5))
    except Exception:
        return False


def _snapshot_rollback_scope(
    cwd: str,
    paths: list[str] | None,
) -> tuple[RollbackSnapshot | None, str | None]:
    if not paths:
        return None, "rollback paths are required"
    if not isinstance(paths, list) or len(paths) > _MAX_ROLLBACK_PATHS:
        return None, "rollback paths must be a list of at most 128 files"
    root_guard: int | None = None
    parent_handles: list[int] = []
    try:
        root = Path(cwd).resolve(strict=True)
        if not root.is_dir():
            return None, "rollback root must be a directory"
        root_guard = _acquire_rollback_root(root)
        root_identity = _rollback_root_identity(root_guard)
        state: dict[str, RollbackFileSnapshot] = {}
        seen_paths: set[str] = set()
        total_bytes = 0
        for raw in paths:
            entry_stat = None
            if not isinstance(raw, str) or not raw or "\x00" in raw:
                raise ValueError("rollback paths must be non-empty relative file paths")
            portable = raw.replace("\\", "/")
            drive, _ = ntpath.splitdrive(raw)
            parts = portable.split("/")
            if drive or ntpath.isabs(raw) or portable.startswith("/") or any(p in {"", ".", ".."} for p in parts):
                raise ValueError(f"invalid rollback path: {raw[:160]}")
            reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)), "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}
            if any(
                ":" in part
                or part.endswith((".", " "))
                or part.split(".", 1)[0].rstrip(" .").upper() in reserved
                for part in parts
            ):
                raise ValueError(f"invalid platform-specific rollback path: {raw[:160]}")
            key = Path(*parts).as_posix()
            comparison_key = key.casefold() if os.name == "nt" else key
            if comparison_key in seen_paths:
                raise ValueError(f"duplicate rollback path: {raw[:160]}")
            seen_paths.add(comparison_key)
            parent_guard, parent_owned = _open_rollback_parent_handle(root_guard, parts[:-1])
            if parent_owned:
                parent_handles.append(parent_guard)
            leaf = parts[-1]
            snapshot_fd: int | None = None
            if os.name != "nt":
                try:
                    entry_stat = os.stat(leaf, dir_fd=parent_guard, follow_symlinks=False)
                except FileNotFoundError:
                    entry_stat = None
                if entry_stat is not None and stat.S_ISLNK(entry_stat.st_mode):
                    raise ValueError(f"rollback paths cannot be symlinks: {raw[:160]}")
            if os.name == "nt":
                snapshot_fd = _open_rollback_snapshot_file(parent_guard, leaf)
                if snapshot_fd is not None:
                    try:
                        entry_stat = os.fstat(snapshot_fd)
                    except BaseException:
                        fd_to_close = snapshot_fd
                        snapshot_fd = None
                        try:
                            os.close(fd_to_close)
                        except OSError:
                            pass
                        raise
            if entry_stat is not None:
                try:
                    if not stat.S_ISREG(entry_stat.st_mode):
                        raise ValueError(f"rollback path must be a regular file: {raw[:160]}")
                    if entry_stat.st_nlink > 1:
                        raise ValueError(f"rollback does not accept multiply-linked files: {raw[:160]}")
                    size = entry_stat.st_size
                    if size > _MAX_ROLLBACK_FILE_BYTES or total_bytes + size > _MAX_ROLLBACK_TOTAL_BYTES:
                        raise ValueError("rollback snapshot exceeds the 16 MiB per-file or 64 MiB total limit")
                    if os.name != "nt":
                        open_flags = _rollback_snapshot_open_flags()
                        snapshot_fd = os.open(leaf, open_flags, dir_fd=parent_guard)
                    if snapshot_fd is None:
                        raise ValueError(f"rollback target disappeared during snapshot: {raw[:160]}")
                    fd = snapshot_fd
                    opened_stat = os.fstat(fd)
                    if (
                        (os.name != "nt" and (opened_stat.st_dev, opened_stat.st_ino) != (entry_stat.st_dev, entry_stat.st_ino))
                        or opened_stat.st_nlink > 1
                    ):
                        raise ValueError(f"rollback target changed during snapshot: {raw[:160]}")
                    with os.fdopen(fd, "rb", closefd=False) as source:
                        content = source.read(_MAX_ROLLBACK_FILE_BYTES + 1)
                    final_stat = os.fstat(fd)
                    stable_fields = (opened_stat.st_size, opened_stat.st_mtime_ns, opened_stat.st_ctime_ns)
                    final_fields = (final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ctime_ns)
                    if len(content) > _MAX_ROLLBACK_FILE_BYTES or stable_fields != final_fields or final_stat.st_nlink > 1:
                        raise ValueError(f"rollback target changed during snapshot: {raw[:160]}")
                    if os.name != "nt" and not getattr(os, "O_NOATIME", 0):
                        try:
                            os.utime(fd, ns=(opened_stat.st_atime_ns, opened_stat.st_mtime_ns))
                        except (OSError, TypeError, ValueError) as exc:
                            raise ValueError("cannot preserve file access time during rollback snapshot") from exc
                    elif os.name == "nt":
                        _restore_windows_atime(fd, opened_stat.st_atime_ns)
                    xattrs: dict[str, bytes] = {}
                    metadata_size = 0
                    if os.name != "nt" and hasattr(os, "listxattr"):
                        for attr_name in os.listxattr(fd):
                            attr_value = os.getxattr(fd, attr_name)
                            metadata_size += len(attr_name.encode("utf-8", errors="surrogateescape")) + len(attr_value)
                            if metadata_size > _MAX_ROLLBACK_METADATA_BYTES:
                                raise ValueError("rollback extended metadata exceeds 1 MiB")
                            xattrs[attr_name] = attr_value
                    windows_dacl = _get_windows_dacl(fd) if os.name == "nt" else None
                finally:
                    if snapshot_fd is not None:
                        os.close(snapshot_fd)
                        snapshot_fd = None
                if total_bytes + len(content) > _MAX_ROLLBACK_TOTAL_BYTES:
                    raise ValueError("rollback snapshot exceeds the 64 MiB total limit")
                total_bytes += len(content)
                mode = stat.S_IMODE(entry_stat.st_mode)
                file_snapshot = RollbackFileSnapshot(content, mode, xattrs, windows_dacl, entry_stat.st_atime_ns, entry_stat.st_mtime_ns)
            else:
                file_snapshot = RollbackFileSnapshot(None, None, {}, None, None, None)
            state[key] = file_snapshot
            if parent_owned:
                _close_rollback_root(parent_guard)
                parent_handles.remove(parent_guard)
        return RollbackSnapshot(root, root_identity, state, root_guard), None
    except (OSError, ValueError, TypeError) as exc:
        for parent_handle in parent_handles:
            try:
                _close_rollback_root(parent_handle)
            except OSError:
                pass
        if root_guard is not None:
            try:
                _close_rollback_root(root_guard)
            except OSError:
                pass
        return None, f"cannot snapshot rollback scope: {str(exc)[:256]}"


def _rollback_postimage_at(parent_handle: int, leaf: str) -> RollbackPostimage:
    fd: int | None = None
    try:
        if os.name == "nt":
            fd = _open_rollback_snapshot_file(parent_handle, leaf)
            if fd is None:
                return RollbackPostimage(True, None)
            opened_stat = os.fstat(fd)
        else:
            try:
                entry_stat = os.stat(leaf, dir_fd=parent_handle, follow_symlinks=False)
            except FileNotFoundError:
                return RollbackPostimage(True, None)
            if stat.S_ISLNK(entry_stat.st_mode):
                return RollbackPostimage(False, None, "symlink postimage")
            if not stat.S_ISREG(entry_stat.st_mode):
                return RollbackPostimage(False, None, "non-file postimage")
            if entry_stat.st_nlink != 1:
                return RollbackPostimage(False, None, "external aliases")
            fd = os.open(leaf, _rollback_snapshot_open_flags(), dir_fd=parent_handle)
            opened_stat = os.fstat(fd)
            if (opened_stat.st_dev, opened_stat.st_ino) != (entry_stat.st_dev, entry_stat.st_ino):
                return RollbackPostimage(False, None, "postimage changed while opening")
        if not stat.S_ISREG(opened_stat.st_mode):
            return RollbackPostimage(False, None, "non-file postimage")
        if opened_stat.st_nlink != 1:
            return RollbackPostimage(False, None, "external aliases")
        with os.fdopen(fd, "rb", closefd=False) as source:
            content = source.read(_MAX_ROLLBACK_FILE_BYTES + 1)
        final_stat = os.fstat(fd)
        identity = (opened_stat.st_dev, opened_stat.st_ino)
        stable_before = (
            identity,
            opened_stat.st_size,
            opened_stat.st_mtime_ns,
            opened_stat.st_ctime_ns,
            stat.S_IMODE(opened_stat.st_mode),
            opened_stat.st_nlink,
        )
        stable_after = (
            (final_stat.st_dev, final_stat.st_ino),
            final_stat.st_size,
            final_stat.st_mtime_ns,
            final_stat.st_ctime_ns,
            stat.S_IMODE(final_stat.st_mode),
            final_stat.st_nlink,
        )
        if len(content) > _MAX_ROLLBACK_FILE_BYTES or stable_before != stable_after:
            return RollbackPostimage(False, None, "postimage changed while reading")
        metadata_digest = hashlib.sha256()
        metadata_size = 0
        if os.name != "nt" and hasattr(os, "listxattr"):
            for attr_name in sorted(os.listxattr(fd)):
                name_bytes = attr_name.encode("utf-8", errors="surrogateescape")
                attr_value = os.getxattr(fd, attr_name)
                metadata_size += len(name_bytes) + len(attr_value)
                if metadata_size > _MAX_ROLLBACK_METADATA_BYTES:
                    return RollbackPostimage(False, None, "postimage metadata exceeds limit")
                metadata_digest.update(len(name_bytes).to_bytes(4, "big"))
                metadata_digest.update(name_bytes)
                metadata_digest.update(len(attr_value).to_bytes(4, "big"))
                metadata_digest.update(attr_value)
        elif os.name == "nt":
            dacl = _get_windows_dacl(fd)
            if dacl is not None:
                metadata_digest.update(dacl)
        final_stat = os.fstat(fd)
        stable_after = (
            (final_stat.st_dev, final_stat.st_ino),
            final_stat.st_size,
            final_stat.st_mtime_ns,
            final_stat.st_ctime_ns,
            stat.S_IMODE(final_stat.st_mode),
            final_stat.st_nlink,
        )
        if stable_before != stable_after:
            return RollbackPostimage(False, None, "postimage changed while reading")
        return RollbackPostimage(
            True,
            (*identity, final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ctime_ns,
             stat.S_IMODE(final_stat.st_mode), hashlib.sha256(content).hexdigest(),
             metadata_digest.hexdigest()),
        )
    except (OSError, ValueError) as exc:
        reason = "external aliases" if "reparse" in str(exc).lower() else f"unverifiable postimage: {exc}"
        return RollbackPostimage(False, None, reason[:160])
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def _capture_rollback_postimages(snapshot: RollbackSnapshot) -> None:
    """Record stable after-images only for the caller-declared rollback paths."""
    for relative in snapshot.files:
        parts = relative.split("/")
        try:
            parent_handle, parent_owned = _open_rollback_parent_handle(
                snapshot.root_guard,
                parts[:-1],
            )
        except (OSError, ValueError) as exc:
            snapshot.postimages[relative] = RollbackPostimage(
                False, None, f"unverifiable postimage parent: {exc}"[:160]
            )
            continue
        try:
            snapshot.postimages[relative] = _rollback_postimage_at(parent_handle, parts[-1])
        finally:
            if parent_owned:
                _close_rollback_root(parent_handle)


def _restore_rollback_scope(
    cwd: str,
    snapshot: RollbackSnapshot,
) -> None:
    root = Path(cwd).resolve(strict=True)
    # POSIX cannot atomically bind this path check to later dirfd writes. After
    # the check, every mutation stays relative to the snapshot's pinned root.
    current_root_handle = _acquire_rollback_root(root)
    try:
        current_root_identity = _rollback_root_identity(current_root_handle)
    finally:
        _close_rollback_root(current_root_handle)
    root_identity = _rollback_root_identity(snapshot.root_guard)
    if (
        root_identity != snapshot.root_identity
        or current_root_identity != snapshot.root_identity
        or root != snapshot.root
    ):
        raise OSError("rollback root changed since snapshot")
    if set(snapshot.postimages) != set(snapshot.files):
        raise OSError("rollback postimages were not captured for the complete write set")
    incomplete: list[str] = []
    for relative, file_snapshot in snapshot.files.items():
        content, mode = file_snapshot.content, file_snapshot.mode
        parts = relative.split("/")
        parent_handle, parent_owned = _open_rollback_parent_handle(
            snapshot.root_guard,
            parts[:-1],
            mutation=True,
        )
        leaf = parts[-1]
        try:
            expected_postimage = snapshot.postimages.get(relative)
            current_postimage = _rollback_postimage_at(parent_handle, leaf)
            if (
                expected_postimage is None
                or not expected_postimage.safe
                or not current_postimage.safe
                or expected_postimage.fingerprint != current_postimage.fingerprint
            ):
                incomplete.append(relative)
                continue

            def postimage_still_matches() -> bool:
                latest = _rollback_postimage_at(parent_handle, leaf)
                return (
                    expected_postimage.safe
                    and latest.safe
                    and expected_postimage.fingerprint == latest.fingerprint
                )

            if os.name != "nt":
                try:
                    current_stat = os.stat(leaf, dir_fd=parent_handle, follow_symlinks=False)
                except FileNotFoundError:
                    current_stat = None
                if current_stat is not None and stat.S_ISDIR(current_stat.st_mode):
                    raise OSError(f"refusing to replace rollback directory: {relative}")
                if current_stat is not None and (stat.S_ISLNK(current_stat.st_mode) or current_stat.st_nlink > 1):
                    incomplete.append(relative)
                    continue
                if content is None:
                    if current_stat is not None:
                        if not postimage_still_matches():
                            incomplete.append(relative)
                            continue
                        os.unlink(leaf, dir_fd=parent_handle)
                    continue
                temp_name = f".local-ai-rollback-{uuid.uuid4().hex}"
                fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=parent_handle,
                )
                try:
                    with os.fdopen(fd, "wb", closefd=False) as temp_file:
                        temp_file.write(content)
                        temp_file.flush()
                        os.fsync(temp_file.fileno())
                    if mode is not None:
                        os.fchmod(fd, mode)
                    for attr_name, attr_value in file_snapshot.xattrs.items():
                        os.setxattr(fd, attr_name, attr_value)
                    if file_snapshot.atime_ns is not None and file_snapshot.mtime_ns is not None:
                        os.utime(fd, ns=(file_snapshot.atime_ns, file_snapshot.mtime_ns))
                    if not postimage_still_matches():
                        incomplete.append(relative)
                        continue
                    if expected_postimage.fingerprint is None:
                        # linkat-style creation is atomic and fails if a foreign
                        # writer creates the previously absent leaf after our check.
                        os.link(
                            temp_name,
                            leaf,
                            src_dir_fd=parent_handle,
                            dst_dir_fd=parent_handle,
                            follow_symlinks=False,
                        )
                        os.unlink(temp_name, dir_fd=parent_handle)
                    else:
                        # POSIX has no portable compare-and-replace primitive for
                        # an existing leaf; this last check narrows, but cannot
                        # eliminate, external-writer TOCTOU.
                        os.replace(
                            temp_name,
                            leaf,
                            src_dir_fd=parent_handle,
                            dst_dir_fd=parent_handle,
                        )
                finally:
                    os.close(fd)
                    try:
                        os.unlink(temp_name, dir_fd=parent_handle)
                    except FileNotFoundError:
                        pass
                continue

            import msvcrt

            if content is None and not postimage_still_matches():
                incomplete.append(relative)
                continue
            target_handle = _open_rollback_relative_handle(
                parent_handle,
                leaf,
                directory=False,
                mutation=True,
            )
            target_fd: int | None = None
            if target_handle is not None:
                try:
                    target_fd = msvcrt.open_osfhandle(target_handle, os.O_RDONLY | os.O_BINARY)
                except BaseException:
                    _close_rollback_root(target_handle)
                    raise
                try:
                    current_stat = os.fstat(target_fd)
                except BaseException:
                    os.close(target_fd)
                    raise
                if content is None and expected_postimage.fingerprint is not None:
                    expected_fields = expected_postimage.fingerprint[:6]
                    observed_fields = (
                        current_stat.st_dev,
                        current_stat.st_ino,
                        current_stat.st_size,
                        current_stat.st_mtime_ns,
                        current_stat.st_ctime_ns,
                        stat.S_IMODE(current_stat.st_mode),
                    )
                    if expected_fields != observed_fields:
                        incomplete.append(relative)
                        os.close(target_fd)
                        target_fd = None
                        continue
                if current_stat.st_nlink > 1:
                    incomplete.append(relative)
                    if target_fd is not None:
                        os.close(target_fd)
                        target_fd = None
                    continue
            else:
                current_stat = None
            if content is None:
                if target_fd is not None:
                    if current_stat is not None and current_stat.st_nlink > 1:
                        os.close(target_fd)
                        continue
                    try:
                        _delete_windows_handle(msvcrt.get_osfhandle(target_fd))
                    finally:
                        os.close(target_fd)
                continue
            if target_fd is not None:
                os.close(target_fd)

            temp_name = f".local-ai-rollback-{uuid.uuid4().hex}"
            temp_handle = _open_rollback_relative_handle(
                parent_handle,
                temp_name,
                directory=False,
                mutation=True,
                create=True,
            )
            if temp_handle is None:
                raise OSError("cannot create rollback temporary file")
            try:
                temp_fd = msvcrt.open_osfhandle(temp_handle, os.O_RDWR | os.O_BINARY)
            except BaseException:
                _close_rollback_root(temp_handle)
                raise
            renamed = False
            try:
                with os.fdopen(temp_fd, "wb", closefd=False) as temp_file:
                    temp_file.write(content)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                _restore_windows_file_attributes(temp_fd, mode)
                _restore_windows_file_times(temp_fd, file_snapshot.atime_ns, file_snapshot.mtime_ns)
                if file_snapshot.windows_dacl is not None:
                    _set_windows_dacl(temp_fd, file_snapshot.windows_dacl)
                if not postimage_still_matches():
                    incomplete.append(relative)
                    continue
                _rename_windows_handle(
                    msvcrt.get_osfhandle(temp_fd),
                    parent_handle,
                    leaf,
                    replace_if_exists=expected_postimage.fingerprint is not None,
                )
                renamed = True
            finally:
                import sys

                pending_error = sys.exc_info()[1]
                try:
                    if not renamed:
                        temp_os_handle = msvcrt.get_osfhandle(temp_fd)
                        try:
                            _delete_windows_handle(temp_os_handle)
                        except OSError as first_delete_error:
                            try:
                                _delete_windows_handle(temp_os_handle)
                            except OSError as retry_delete_error:
                                detail = (
                                    f"rollback temporary cleanup failed for {relative}: "
                                    f"{retry_delete_error} (first attempt: {first_delete_error})"
                                )
                                if pending_error is not None:
                                    if hasattr(pending_error, "add_note"):
                                        pending_error.add_note(detail)
                                    else:
                                        pending_error.args = (*pending_error.args, detail)
                                else:
                                    raise OSError(detail) from retry_delete_error
                finally:
                    os.close(temp_fd)
        finally:
            if parent_owned:
                _close_rollback_root(parent_handle)
    if incomplete:
        names = ", ".join(incomplete[:8])
        raise OSError(
            "rollback skipped changed postimages or paths with external aliases for: "
            f"{names}"
        )


@dataclass(frozen=True)
class CommandInvocation:
    """Validated subprocess input that cannot request shell interpretation."""

    argv: list[str]
    cwd: str | None = None
    shell: bool = False


@dataclass(frozen=True)
class _ResolvedProjectCommand:
    alias: str
    command: str | CommandInvocation
    environment: dict[str, str]
    config_digest: str
    cache_context: str


def _patch_write_paths(root: Path, patch: bytes, timeout: float) -> list[str]:
    """Return patch paths only after rejecting escapes and symlink traversal."""
    result = subprocess.run(
        ["git", "apply", "--numstat", "-z"],
        input=patch,
        cwd=str(root),
        capture_output=True,
        check=False,
        timeout=timeout,
        **hidden_run_kwargs(),
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or "patch write set could not be inspected")

    records = result.stdout.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(records) - 1:
        fields = records[index].split(b"\t", 2)
        index += 1
        if len(fields) != 3:
            raise ValueError("patch write set is malformed")
        if fields[2]:
            candidates = [os.fsdecode(fields[2])]
        else:
            if index + 1 >= len(records) - 1:
                raise ValueError("patch rename write set is malformed")
            candidates = [os.fsdecode(records[index]), os.fsdecode(records[index + 1])]
            index += 2
        paths.extend(candidates)

    if not paths or len(paths) > 512:
        raise ValueError("patch write set must contain 1 to 512 paths")
    root = root.resolve(strict=True)
    safe_paths: list[str] = []
    for raw in paths:
        drive, _ = ntpath.splitdrive(raw)
        parts = raw.split("/")
        if (
            not raw
            or drive
            or raw.startswith(("/", "\\"))
            or "\\" in raw
            or ":" in raw
            or any(part in {"", ".", ".."} for part in parts)
            or any(ord(char) < 32 for char in raw)
        ):
            raise ValueError("patch write path is not a safe relative path")
        candidate = root
        for part in parts:
            candidate = candidate / part
            if candidate.is_symlink() or (
                callable(getattr(candidate, "is_junction", None)) and candidate.is_junction()
            ):
                raise ValueError("patch write path cannot traverse a symlink or junction")
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("patch write path escapes the worktree") from exc
        safe_paths.append("/".join(parts))
    return list(dict.fromkeys(safe_paths))


def _invocation_error(reason: str, error: str) -> dict[str, Any]:
    return {
        "safe": False,
        "reason": reason,
        "error": error[:_MAX_INVOCATION_ERROR_CHARS],
        "terminal": True,
        "retryable": False,
    }


def _invocation_cwd(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, os.PathLike):
        converted = os.fspath(value)
        if isinstance(converted, str):
            return converted
    raise TypeError("cwd must be a string or path-like value")


def validate_invocation(invocation: Any) -> dict[str, Any]:
    """Validate structured argv input; raw command strings are never parsed here."""
    try:
        if isinstance(invocation, str):
            return _invocation_error(
                "unstructured_shell_text",
                "command must be structured argv; raw shell text is not accepted",
            )

        if isinstance(invocation, CommandInvocation):
            argv = invocation.argv
            cwd_value = invocation.cwd
            shell = invocation.shell
        elif isinstance(invocation, Mapping):
            if "argv" not in invocation:
                return _invocation_error("missing_argv", "structured invocation requires argv")
            argv = invocation["argv"]
            cwd_value = invocation.get("cwd")
            shell = invocation.get("shell", False)
        elif isinstance(invocation, (list, tuple)):
            argv = invocation
            cwd_value = None
            shell = False
        else:
            return _invocation_error("invalid_invocation_type", "invocation must be argv list or structured mapping")

        if shell is not False:
            reason = "shell_true_not_allowed" if shell is True else "invalid_shell_flag"
            return _invocation_error(reason, "structured invocation must set shell=False")
        if not isinstance(argv, (list, tuple)):
            return _invocation_error("argv_not_sequence", "argv must be a list or tuple of strings")
        if not argv:
            return _invocation_error("empty_argv", "argv must contain an executable")

        for index, value in enumerate(argv):
            if not isinstance(value, str):
                return _invocation_error(
                    "argv_argument_not_string",
                    f"argv argument at index {index} must be a string",
                )
            if "\x00" in value:
                return _invocation_error("nul_in_argv", f"argv argument at index {index} contains NUL")
        if not argv[0].strip():
            return _invocation_error("empty_executable", "argv executable must not be empty")

        cwd = _invocation_cwd(cwd_value)
        return {
            "safe": True,
            "reason": "ok",
            "argv": list(argv),
            "cwd": cwd,
            "shell": False,
            "terminal": False,
            "retryable": False,
        }
    except Exception as exc:
        return _invocation_error(
            "invocation_serialization_error",
            f"invocation serialization failed: {type(exc).__name__}"[:_MAX_INVOCATION_ERROR_CHARS],
        )


def build_invocation(
    executable: str,
    args: Sequence[str] = (),
    *,
    cwd: str | os.PathLike[str] | None = None,
) -> CommandInvocation:
    """Build validated argv input for subprocess APIs; never construct shell text."""
    if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
        raise ValueError("args must be a list or tuple of strings")
    result = validate_invocation({"argv": [executable, *args], "cwd": cwd, "shell": False})
    if not result["safe"]:
        raise ValueError(result["error"])
    return CommandInvocation(argv=result["argv"], cwd=result["cwd"], shell=False)


def _redact_secrets(text: str) -> str:
    if not text:
        return ""
    res = text
    for pat in _SECRET_PATTERNS:
        if pat.groups == 2:
            res = pat.sub(r"\1***", res)
        elif pat.groups == 1:
            res = pat.sub(r"\1***", res)
        else:
            res = pat.sub("***REDACTED_SECRET***", res)
    return res


class _BoundedStreamBuffer:
    """Bounded rolling buffer that retains the most recent output characters without OOM."""

    def __init__(self, max_chars: int, redact: bool = True):
        self.max_chars = max(1024, int(max_chars))
        self.chunks: deque[str] = deque()
        self.total_chars = 0
        self.total_lines = 0
        self.lock = threading.Lock()
        self.redact = redact

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        cleaned = _redact_secrets(chunk) if self.redact else chunk
        if len(cleaned) > self.max_chars:
            cleaned = cleaned[-self.max_chars:]
        with self.lock:
            self.chunks.append(cleaned)
            self.total_chars += len(cleaned)
            self.total_lines += 1
            while self.chunks and (self.total_chars - len(self.chunks[0])) >= self.max_chars:
                discarded = self.chunks.popleft()
                self.total_chars -= len(discarded)

    def getvalue(self) -> str:
        with self.lock:
            return "".join(self.chunks)[-self.max_chars:]

    def write(self, chunk: str) -> None:
        self.append(chunk)

    def peek(self, chars: int = 500) -> str:
        if chars <= 0:
            return ""
        with self.lock:
            if not self.chunks:
                return ""
            collected: list[str] = []
            collected_len = 0
            for chunk in reversed(self.chunks):
                collected.append(chunk)
                collected_len += len(chunk)
                if collected_len >= chars:
                    break
            joined = "".join(reversed(collected))
            return joined[-chars:]


_INTERACTIVE_PATTERNS = [
    re.compile(r"\[[yY]/[nN]\]"),
    re.compile(r"\(yes/no\)", re.IGNORECASE),
    re.compile(r"password(\s+for\s+.*)?:", re.IGNORECASE),
    re.compile(r"press\s+any\s+key", re.IGNORECASE),
    re.compile(r"do\s+you\s+want\s+to\s+continue", re.IGNORECASE),
]


def _is_interactive_prompt(text: str) -> bool:
    """Check if output tail looks like an interactive user prompt."""
    if not text:
        return False
    tail = text[-300:] if len(text) > 300 else text
    return any(p.search(tail) for p in _INTERACTIVE_PATTERNS)


def _stable_rollback_status(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = method(self, *args, **kwargs)
        rollback_key = "auto_rollback" if method.__name__ == "patch_and_verify" else "rollback_on_failure"
        rollback_default = method.__name__ == "patch_and_verify"
        if kwargs.get(rollback_key, rollback_default) and isinstance(result, dict):
            result.setdefault("rolled_back", False)
        return result
    return wrapped


class CommandBroker:
    """Safe shared command runner with repo-state-aware cache and single-flight."""

    READ_ONLY = {
        "git", "rg", "ripgrep", "grep", "findstr", "where", "which",
        "fd", "fdfind", "find", "cat", "type", "head", "tail", "wc",
        "diff", "cmp", "sort", "uniq", "cut", "tr", "file", "stat",
        "echo", "pwd", "tree", "jq", "yq", "ls", "dir",
        "tasklist", "whoami", "hostname", "systeminfo", "ver", "ipconfig", "netstat",
        "fc", "comp", "attrib", "set", "env", "printenv",
    }
    READ_FILTERS = {
        "grep", "ripgrep", "rg", "findstr", "select-string", "find", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "jq", "yq",
        "cat", "type", "format-table", "select-object", "convertto-json", "convertfrom-json", "out-string", "out-null", "tee", "more", "less",
    }
    VALIDATORS = {
        "pytest", "phpunit", "phpstan", "ruff", "mypy", "eslint", "tsc", "cargo",
        "dotnet", "go", "npm", "pnpm", "yarn", "bun", "composer", "make", "cmake",
        "ctest", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "flake8", "pylint",
        "black", "isort", "bandit", "shellcheck", "yamllint",
    }
    PURE_VALIDATORS = {
        "pytest", "phpunit", "phpstan", "pest", "ruff", "mypy", "eslint", "tsc",
        "pyflakes", "flake8", "pylint", "bandit", "radon", "yamllint", "shellcheck",
        "markdownlint", "biome", "oxlint", "clippy", "coverage", "vitest", "jest",
        "mocha", "ava", "playwright", "cypress", "tox", "nox", "pre-commit",
    }
    MUTATING_WORDS = {
        "commit", "push", "pull", "merge", "rebase", "reset", "clean", "checkout", "switch", "restore", "add", "stash", "apply",
        "install", "update", "upgrade", "publish", "deploy", "migrate", "migration", "seed", "format", "fix", "write", "delete", "remove",
    }
    DANGEROUS_EXES = {"rm", "del", "erase", "rmdir", "shutdown", "reboot", "poweroff", "mkfs", "diskpart", "format"}

    def __init__(self, config: dict[str, Any], artifacts: Any = None, repo_state: Any = None):
        self.config = config
        self.artifacts = artifacts
        if repo_state is None:
            from .repo_state import RepoStateTracker
            repo_state = RepoStateTracker(config)
        self.repo_state = repo_state
        cfg = config.get("commands", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.policy_blocking = bool(cfg.get("policy_blocking", False))
        self.timeout = int(cfg.get("timeout_seconds", 1800))
        self.max_output_chars = int(cfg.get("max_output_chars", 2_000_000))
        self.inline_chars = int(cfg.get("inline_output_chars", 5000))
        self.daemon_log_max_bytes = min(2 * 1024 * 1024, max(1024, int(cfg.get("daemon_log_max_bytes", 512 * 1024))))
        self.daemon_ttl_seconds = min(7 * 24 * 60 * 60, max(1, int(cfg.get("daemon_ttl_seconds", 24 * 60 * 60))))
        self.max_daemons = min(32, max(1, int(cfg.get("daemon_max_count", 16))))
        self._daemon_owner_id = self._get_daemon_owner_id()
        self.coalesce_wait_seconds = max(1.0, float(cfg.get("coalesced_wait_seconds", 90.0)))
        self.terminate_grace_seconds = max(0.1, float(cfg.get("terminate_grace_seconds", 2.0)))
        self.post_kill_drain_seconds = max(0.1, float(cfg.get("post_kill_drain_seconds", 2.0)))
        workspace_cache = config.get("workspace_cache", {})
        self.git_snapshot_timeout = max(0.5, float(workspace_cache.get("git_status_timeout_seconds", 2.5)))
        state_dir = configured_state_dir(config)
        self._transaction_state_dir = state_dir / "command-transactions"
        self._transaction_leases = ScopeLeaseStore(state_dir)
        self._active_transaction_roots: dict[str, Path] = {}
        self._transaction_roots_lock = threading.RLock()
        self._daemon_state_dir = state_dir / "daemons"
        self._daemon_registry_path = self._daemon_state_dir / "registry.json"
        l1_entries = int(cfg.get("l1_entries", 128))
        self.success_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:success", int(cfg.get("success_ttl_seconds", 43200)), int(cfg.get("max_entries", 5000))), l1_entries, int(cfg.get("l1_ttl_seconds", 900)))
        self.failure_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:failure", int(cfg.get("failure_ttl_seconds", 180)), int(cfg.get("max_failure_entries", 1000))), max(32, l1_entries // 2), min(300, int(cfg.get("l1_ttl_seconds", 900))))
        self.suppression_cache = TieredCache(SQLiteCache(state_dir / "cache.sqlite3", "command:suppression", int(cfg.get("suppression_ttl_seconds", 900)), int(cfg.get("max_suppression_entries", 2000))), max(32, l1_entries // 2), min(300, int(cfg.get("l1_ttl_seconds", 900))))
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._last: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.coalesced = 0
        self.coalesced_timeouts = 0
        self.executed = 0
        self.blocked = 0
        self.suppressed = 0
        self.cancelled = 0
        self._blocked_by_reason: dict[str, int] = {}
        self._active_commands: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_cancel_keys: dict[str, tuple[str, str]] = {}
        self._daemons: dict[str, dict[str, Any]] = {}
        self._daemons_lock = threading.Lock()
        self._daemon_slots = threading.BoundedSemaphore(self.max_daemons)
        self._load_daemon_registry()
        self.incident_store: Any = None
        self.verification_store: Any = None
        self.policy_engine: Any = None
        self.task_store: Any = None
        self.error_distiller: Any = None

    def set_policy_engine(self, policy_engine: Any) -> None:
        self.policy_engine = policy_engine

    def set_task_store(self, task_store: Any) -> None:
        self.task_store = task_store

    def authorize_auxiliary_action(self, action: str, *, endpoint: str = "", task_id: str = "") -> dict[str, Any]:
        """Authorize auxiliary process actions at their final broker boundary."""
        from .agent_policy import AUXILIARY_ACTION_POLICIES, ActionRequest, CapabilityGrant, RiskClass

        action_name = str(action or "").strip().lower().replace("-", "_")
        policy_config = self.config.get("agent_policy", {})
        policy_enabled = isinstance(policy_config, dict) and bool(policy_config.get("enabled", True))
        developer_authorized = (
            policy_enabled
            and isinstance(policy_config, dict)
            and bool(policy_config.get("allow_developer_authorized_mutations", False))
        )
        engine = self.policy_engine
        if engine is None or not callable(getattr(engine, "authorize", None)):
            return {
                "success": False,
                "allowed": False,
                "requires_approval": True,
                "reason": "auxiliary action policy engine unavailable",
                "owner": "agent_policy",
                "side_effect_class": AUXILIARY_ACTION_POLICIES.get(action_name, (None, "unknown"))[1],
                "terminal": True,
                "retryable": False,
            }
        if action_name not in AUXILIARY_ACTION_POLICIES:
            return {
                "success": False,
                "allowed": False,
                "reason": f"unknown auxiliary action '{action_name}' denied",
                "owner": "agent_policy",
                "side_effect_class": "unknown",
                "terminal": True,
                "retryable": False,
            }

        grant = None
        if developer_authorized:
            grant = CapabilityGrant(
                grant_id="configured-local-development-policy",
                allowed=frozenset({action_name}),
            )
        decision = engine.authorize(
            ActionRequest(
                action=action_name,
                risk_class=RiskClass.READ,
                details={
                    "auxiliary_action": True,
                    "policy_enabled": policy_enabled,
                    "endpoint": str(endpoint),
                },
            ),
            task=None,
            grant=grant,
        )
        result = decision.to_dict()
        result.update({
            "success": bool(decision.allowed),
            "allowed": bool(decision.allowed),
            "terminal": not bool(decision.allowed),
            "retryable": False,
        })
        if not decision.allowed:
            result["error"] = decision.reason
        return result

    def _require_task_worktree(
        self,
        task_id: str,
        cwd: str | Path,
        command: str | CommandInvocation | None = None,
    ) -> str | None:
        if not task_id or self.task_store is None:
            return "mutating commands require a registered task-owned worktree"
        try:
            task = self.task_store.get(task_id)
            checkpoint = getattr(task, "checkpoint", None)
            state_data = getattr(checkpoint, "state_data", {})
            worktree = state_data.get("worktree") if isinstance(state_data, Mapping) else None
            registered_path = worktree.get("worktree_path") if isinstance(worktree, Mapping) else None
            if not registered_path or worktree.get("success") is not True:
                return "mutating commands require a registered task-owned worktree"
            requested = Path(cwd).expanduser().resolve(strict=True)
            if isinstance(command, CommandInvocation) and command.cwd:
                invocation_cwd = Path(command.cwd).expanduser().resolve(strict=True)
                if os.path.normcase(str(invocation_cwd)) != os.path.normcase(str(requested)):
                    return "structured command cwd must match the broker cwd"
                requested = invocation_cwd
            registered = Path(str(registered_path)).expanduser().resolve(strict=True)
            if not requested.is_dir() or not registered.is_dir():
                return "registered task worktree is unavailable"
            common = os.path.commonpath([str(requested), str(registered)])
            if os.path.normcase(common) != os.path.normcase(str(registered)):
                return "mutating command cwd must be inside the registered task-owned worktree"
            return self._reject_git_worktree_overrides(command, requested, registered)
        except Exception:
            return "registered task worktree could not be verified"

    def _reject_git_worktree_overrides(
        self,
        command: str | CommandInvocation | None,
        cwd: Path,
        registered: Path,
    ) -> str | None:
        git_path_keys = {
            "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        }

        def is_git_override(key: str) -> bool:
            normalized = key.upper()
            return normalized in git_path_keys or normalized.startswith("GIT_CONFIG_")

        if command is None:
            return None
        if isinstance(command, CommandInvocation):
            tokens = list(command.argv)
            if any(is_git_override(key) for key in (getattr(command, "env", None) or {})):
                return "mutating Git command cannot override repository paths"
            token_groups = [tokens]
        elif isinstance(command, str):
            assignment = re.compile(
                r"(?i)(?:^|[\s;&|])(?:(?:export|set)\s+)?(?:\$env:)?"
                r"(GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_COMMON_DIR|GIT_OBJECT_DIRECTORY|"
                r"GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_CONFIG_[A-Z0-9_]+)"
                r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
            )
            if assignment.search(command):
                return "mutating Git command cannot override repository paths"
            segments = [command]
            for delimiter in (";", "&&", "||", "|"):
                segments = [
                    part
                    for segment in segments
                    for _found, part in self._split_outside_quotes(segment, (delimiter,))
                ]
            token_groups = [self._tokens(segment) for segment in segments]
        else:
            return "mutating command could not be checked against its task worktree"

        for tokens in token_groups:
            if not tokens:
                continue
            if any(
                re.fullmatch(r"(?i)GIT_[A-Z0-9_]+=.+", token)
                for token in tokens
            ):
                return "mutating Git command cannot override repository paths"
            executable = ntpath.basename(tokens[0].strip('"').replace("/", "\\")).lower()
            if re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", executable) != "git":
                continue
            index = 1
            while index < len(tokens):
                argument = tokens[index]
                lowered = argument.lower()
                if lowered in {"--git-dir", "--work-tree", "--separate-git-dir"} or any(
                    lowered.startswith(f"{option}=")
                    for option in ("--git-dir", "--work-tree", "--separate-git-dir")
                ):
                    return "mutating Git command cannot override repository paths"
                if lowered.startswith("--config-env=") and lowered.split("=", 2)[1] in {
                    "core.worktree", "core.indexfile",
                }:
                    return "mutating Git command cannot override repository paths"
                if lowered == "--config-env" and index + 1 < len(tokens):
                    setting = tokens[index + 1].split("=", 1)[0].lower()
                    if setting in {"core.worktree", "core.indexfile"}:
                        return "mutating Git command cannot override repository paths"
                    index += 2
                    continue
                if argument == "-c" and index + 1 < len(tokens):
                    setting = tokens[index + 1].split("=", 1)[0].lower()
                    if setting in {"core.worktree", "core.indexfile"}:
                        return "mutating Git command cannot override repository paths"
                    index += 2
                    continue
                if argument == "-c":
                    return "mutating Git command has an incomplete configuration override"
                if argument.startswith("-c") and len(argument) > 2:
                    setting = argument[2:].split("=", 1)[0].lower()
                    if setting in {"core.worktree", "core.indexfile"}:
                        return "mutating Git command cannot override repository paths"
                    index += 1
                    continue
                target_value = ""
                if argument == "-C":
                    if index + 1 >= len(tokens):
                        return "mutating Git command has an incomplete worktree override"
                    target_value = tokens[index + 1]
                    index += 2
                elif argument.startswith("-C") and len(argument) > 2:
                    target_value = argument[2:]
                    index += 1
                else:
                    index += 1
                    continue
                target = Path(target_value).expanduser()
                if not target.is_absolute():
                    target = cwd / target
                resolved = target.resolve(strict=False)
                common = os.path.commonpath([str(resolved), str(registered)])
                if os.path.normcase(common) != os.path.normcase(str(registered)):
                    return "mutating Git command cannot target paths outside the registered task worktree"
        return None

    def set_incident_store(self, incident_store: Any) -> None:
        self.incident_store = incident_store

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def _record_command_verification(
        self,
        result: dict[str, Any],
        *,
        tenant: str,
        task_id: str,
        criterion: str,
        command: str,
        command_id: str,
        command_digest: str,
        repository_revision: str,
        duration_ms: float,
        cached: bool = False,
    ) -> None:
        if not result.get("success") or not task_id or self.verification_store is None:
            return
        try:
            if self.artifacts is None:
                raise RuntimeError("artifact store unavailable")
            from .agent_verification import VerificationReceipt, classify_verification_command

            evidence_type = classify_verification_command(command)
            if evidence_type not in {"test", "benchmark"}:
                return
            task_store = self.task_store or getattr(self.verification_store, "task_store", None)
            task = task_store.get(task_id) if task_store is not None else None
            verified_owner = str(getattr(task, "owner", "") or tenant).strip()
            state_data = getattr(getattr(task, "checkpoint", None), "state_data", {}) or {}
            mutation_generation = int(state_data.get("mutation_generation", 0) or 0)
            exit_code = result.get("exit_code")
            if type(exit_code) is not int or exit_code != 0 or not verified_owner:
                return

            proof = {
                "kind": "work_command_verification",
                "task_id": task_id,
                "owner": verified_owner,
                "criterion": criterion,
                "command_id": command_id,
                "command_sha256": command_digest,
                "exit_code": exit_code,
                "repository_revision": repository_revision,
                "mutation_generation": mutation_generation,
                "passed": True,
                "result": {"success": result.get("success") is True, "exit_code": exit_code},
                "duration_ms": max(0.0, float(duration_ms or 0)),
                "cached": cached,
            }
            if hasattr(self.artifacts, "put_json"):
                evidence_id = self.artifacts.put_json(proof, verified_owner, "command_verification")
            elif hasattr(self.artifacts, "put"):
                evidence_id = self.artifacts.put(json_dumps(proof), verified_owner, "command_verification", "application/json")
            else:
                evidence_id = ""
            if not evidence_id:
                raise RuntimeError("verification evidence was not persisted")
            receipt = VerificationReceipt.create(
                task_id=task_id,
                criterion=criterion,
                passed=True,
                command_id=command_id,
                evidence_id=str(evidence_id),
                repository_revision=repository_revision,
                owner=verified_owner,
                mutation_generation=mutation_generation,
                evidence_type=evidence_type,
                details={
                    "exit_code": proof["exit_code"],
                    "duration_ms": proof["duration_ms"],
                    "cached": cached,
                },
            )
            self.verification_store.record(receipt)
            result["verification_receipt"] = receipt.to_dict()
            result["verification_evidence_id"] = str(evidence_id)
        except Exception:
            result["verification_receipt_warning"] = (
                "command succeeded but durable verification evidence was unavailable"
            )

    def set_error_distiller(self, error_distiller: Any) -> None:
        """Set the optional local-model fallback for unstructured command failures."""
        self.error_distiller = error_distiller

    @staticmethod
    def _daemon_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
        """Inherit a minimal OS runtime environment; add only explicit, bounded overrides."""
        key_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        inherited_allowlist = {
            "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
            "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "VIRTUAL_ENV", "LANG", "LANGUAGE", "TZ",
        }
        result = {
            key: value
            for key, value in os.environ.items()
            if key_pattern.fullmatch(key)
            and (key.upper() in inherited_allowlist or key.upper().startswith("LC_"))
            and isinstance(value, str)
            and "\x00" not in value
        }
        if extra is None:
            return result
        if not isinstance(extra, dict) or len(extra) > 128:
            raise ValueError("daemon environment must be a mapping with at most 128 entries")
        total_bytes = 0
        for key, value in extra.items():
            if not isinstance(key, str) or not key_pattern.fullmatch(key):
                raise ValueError("daemon environment contains an invalid variable name")
            normalized_key = key.upper()
            if normalized_key in {
                "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            } or normalized_key.startswith("GIT_CONFIG_"):
                raise ValueError("daemon environment cannot override Git repository paths")
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError(f"daemon environment value for {key} must be a NUL-free string")
            total_bytes += len(key.encode("utf-8")) + len(value.encode("utf-8"))
            if len(key) > 255 or len(value) > 32_767 or total_bytes > 64 * 1024:
                raise ValueError("daemon environment exceeds the supported size limit")
            if os.name == "nt":
                for existing in list(result):
                    if existing.casefold() == key.casefold():
                        del result[existing]
            result[key] = value
        return result

    @staticmethod
    def _get_daemon_owner_id() -> str:
        try:
            owner = getpass.getuser()
        except Exception:
            owner = f"uid:{os.getuid()}" if hasattr(os, "getuid") else "local-ai-hub"
        return hashlib.sha256(f"local-ai-daemon-owner:{owner}".encode("utf-8")).hexdigest()[:32]

    @classmethod
    def _daemon_argv(cls, command: str | Sequence[str]) -> tuple[list[str] | None, str, str | None]:
        if isinstance(command, str):
            if not command.strip() or len(command) > 8192:
                return None, "", "daemon command must be a non-empty string of at most 8192 characters"
            argv = cls._tokens(command)
            executable = ""
            if argv:
                executable = (ntpath.basename(argv[0]) if os.name == "nt" else Path(argv[0]).name).casefold()
            explicit_shells = {"sh", "bash", "dash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
            if cls._needs_shell(command) and executable not in explicit_shells:
                return None, "", "daemon command contains shell syntax; implicit shell execution is not allowed"
            label = cls._safe_label(command)
        elif isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray)):
            if not command or len(command) > 128:
                return None, "", "daemon argv must contain 1 to 128 arguments"
            if any(not isinstance(arg, str) or "\x00" in arg or len(arg) > 8192 for arg in command):
                return None, "", "daemon argv entries must be NUL-free strings of at most 8192 characters"
            argv = list(command)
            if not argv[0]:
                return None, "", "daemon argv[0] must name an executable"
            if sum(len(arg.encode("utf-8")) for arg in argv) > 32 * 1024:
                return None, "", "daemon argv exceeds the 32 KiB size limit"
            label = cls._safe_label(shlex.join(argv))
        else:
            return None, "", "daemon command must be a string or structured argv list"
        if not argv:
            return None, "", "daemon command could not be parsed"
        return argv, label, None

    def _schedule_daemon_expiry(self, info: dict[str, Any]) -> None:
        previous = info.get("ttl_timer")
        if previous is not None:
            previous.cancel()
        delay = max(0.0, float(info["expires_at"]) - time.time())
        timer = threading.Timer(delay, self._expire_daemon, args=(info["daemon_id"],))
        timer.daemon = True
        info["ttl_timer"] = timer
        timer.start()

    def _release_daemon_slot(self, info: dict[str, Any]) -> None:
        if not info.get("_slot_acquired") or info.get("_slot_released"):
            return
        info["_slot_released"] = True
        try:
            self._daemon_slots.release()
        except ValueError:
            pass

    def _refresh_daemon_capacity(self) -> None:
        now = time.time()
        changed = False
        with self._daemons_lock:
            for info in self._daemons.values():
                if info["process"].poll() is None:
                    continue
                reader = info.get("reader_thread")
                if reader is not None:
                    reader.join(timeout=0.1)
                self._close_daemon_log(info)
                info.setdefault("stopped_at", now)
                self._release_daemon_slot(info)
                changed = True
            if changed:
                self._persist_daemon_registry()

    def _expire_daemon(self, daemon_id: str) -> None:
        for attempt in range(3):
            result = self.stop_daemon(daemon_id)
            if result.get("process_tree_stopped") is True or result.get("status") == "not_found":
                return
            if attempt < 2:
                time.sleep(0.25)
        with self._daemons_lock:
            info = self._daemons.get(daemon_id)
            if info is not None:
                info["ttl_stop_failed"] = True

    def _watch_daemon_exit(self, daemon_id: str, process: subprocess.Popen[Any]) -> None:
        """Reap descendants promptly when a daemon leader exits on its own."""
        while True:
            try:
                process.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
            except (OSError, ValueError):
                return
        status = self.daemon_status(daemon_id)
        if status.get("process_tree_stopped") is not True:
            self._expire_daemon(daemon_id)

    def _load_daemon_registry(self) -> None:
        """Reattach only live PIDs whose executable and creation identity still match."""
        registry = self._daemon_registry_path
        try:
            if registry.is_symlink() or registry.stat().st_size > 256 * 1024:
                return
            with registry.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != 2:
            return
        rows = payload.get("daemons")
        if not isinstance(rows, list):
            return
        expected_dir = self._daemon_state_dir.resolve(strict=False)
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            daemon_id = row.get("daemon_id")
            pid = row.get("pid")
            identity = row.get("identity")
            if (
                not isinstance(daemon_id, str)
                or not re.fullmatch(r"dmn_[0-9a-f]{32}", daemon_id)
                or isinstance(pid, bool)
                or not isinstance(pid, int)
                or not isinstance(identity, dict)
                or identity.get("pid") != pid
                or row.get("owner_id") != self._daemon_owner_id
                or process_identity(pid) != identity
            ):
                continue
            if not self._daemon_slots.acquire(blocking=False):
                try:
                    terminate_tree(pid, grace_seconds=self.terminate_grace_seconds)
                except Exception:
                    pass
                continue
            log_path = self._daemon_state_dir / f"{daemon_id}.log"
            try:
                if log_path.is_symlink() or log_path.resolve(strict=False).parent != expected_dir:
                    self._daemon_slots.release()
                    continue
                log_fh = log_path.open("r+b")
                log_fh.seek(0, os.SEEK_END)
                size = log_fh.tell()
                log_fh.seek(max(0, size - self.daemon_log_max_bytes), os.SEEK_SET)
                log_buffer = bytearray(log_fh.read(self.daemon_log_max_bytes))
            except OSError:
                self._daemon_slots.release()
                continue
            try:
                started_at = float(row.get("started_at"))
                expires_at = float(row.get("expires_at"))
            except (TypeError, ValueError, OverflowError):
                log_fh.close()
                self._daemon_slots.release()
                continue
            if not (0 < started_at < float("inf") and started_at <= expires_at < float("inf")):
                log_fh.close()
                self._daemon_slots.release()
                continue
            name = row.get("name")
            command = row.get("command")
            info = {
                "daemon_id": daemon_id,
                "process": _RecoveredDaemonProcess(pid, identity),
                "pid": pid,
                "identity": identity,
                "owner_id": self._daemon_owner_id,
                "name": self._safe_label(name) if isinstance(name, str) else daemon_id,
                "command": self._safe_label(command) if isinstance(command, str) else "",
                "cwd": "",
                "log_path": str(log_path),
                "log_fh": log_fh,
                "log_buffer": log_buffer,
                "log_lock": threading.Lock(),
                "reader_thread": None,
                "_log_closed": False,
                "started_at": started_at,
                "expires_at": expires_at,
                "_slot_acquired": True,
                "_slot_released": False,
            }
            self._daemons[daemon_id] = info
        for info in self._daemons.values():
            try:
                self._schedule_daemon_expiry(info)
            except RuntimeError:
                info["ttl_timer"] = None

    def _persist_daemon_registry(self) -> bool:
        """Atomically persist bounded, secret-redacted daemon identity metadata."""
        try:
            self._daemon_state_dir.mkdir(parents=True, exist_ok=True)
            registry = self._daemon_registry_path
            if registry.is_symlink():
                return False
            rows: list[dict[str, Any]] = []
            for daemon_id, info in self._daemons.items():
                process = info["process"]
                if process.poll() is not None:
                    continue
                identity = info.get("identity")
                if not isinstance(identity, dict) or identity.get("pid") != int(info["pid"]):
                    continue
                rows.append(
                    {
                        "daemon_id": daemon_id,
                        "pid": int(info["pid"]),
                        "identity": identity,
                        "owner_id": info["owner_id"],
                        "name": self._safe_label(str(info.get("name", daemon_id)))[:128],
                        "command": self._safe_label(str(info.get("command", ""))),
                        "started_at": float(info["started_at"]),
                        "expires_at": float(info["expires_at"]),
                    }
                )
                if len(rows) >= 50:
                    break
            payload = json.dumps({"version": 2, "daemons": rows}, ensure_ascii=True, separators=(",", ":"))
            temp_path = registry.with_name(f"registry.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, registry)
            except Exception:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise
            return True
        except (OSError, TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _flush_daemon_log(info: dict[str, Any]) -> None:
        log_fh = info.get("log_fh")
        log_buffer = info.get("log_buffer")
        if log_fh is None or not isinstance(log_buffer, bytearray) or info.get("_log_closed"):
            return
        log_lock = info.get("log_lock")
        try:
            if log_lock is None:
                log_fh.seek(0)
                log_fh.truncate()
                log_fh.write(bytes(log_buffer))
                log_fh.flush()
            else:
                with log_lock:
                    log_fh.seek(0)
                    log_fh.truncate()
                    log_fh.write(bytes(log_buffer))
                    log_fh.flush()
        except (OSError, ValueError):
            pass

    @classmethod
    def _capture_daemon_output(cls, read_fh: Any, info: dict[str, Any], max_bytes: int) -> None:
        try:
            while True:
                chunk = read_fh.read(64 * 1024)
                if not chunk:
                    break
                with info["log_lock"]:
                    buffer = info["log_buffer"]
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        del buffer[: len(buffer) - max_bytes]
        except (OSError, ValueError):
            pass
        finally:
            try:
                read_fh.close()
            except Exception:
                pass
            cls._flush_daemon_log(info)

    @classmethod
    def _close_daemon_log(cls, info: dict[str, Any]) -> None:
        """Close a daemon log handle exactly once, including natural exits."""
        if info.get("_log_closed"):
            return
        cls._flush_daemon_log(info)
        try:
            info["log_fh"].close()
        except Exception:
            pass
        info["_log_closed"] = True

    @staticmethod
    def _tokens(command: str) -> list[str]:
        try:
            tokens = shlex.split(command, posix=(os.name != "nt"))
            if os.name == "nt":
                return [t[1:-1] if (len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")))) else t for t in tokens]
            return tokens
        except ValueError:
            return []

    @staticmethod
    def _strip_null_redirections(cmd: str) -> str:
        c = re.sub(r"\s*(?:2>&1|2>\s*(?:/dev/null|nul|\$null)|>\s*(?:/dev/null|nul|\$null)|\|\s*Out-Null)\s*$", "", cmd, flags=re.IGNORECASE)
        return c.strip()

    @staticmethod
    def _split_outside_quotes(s: str, delimiters: tuple[str, ...]) -> list[tuple[str, str]]:
        parts = []
        current = []
        in_quote = False
        quote_char = ''
        i = 0
        n = len(s)
        last_delim = ''
        while i < n:
            c = s[i]
            if in_quote:
                current.append(c)
                if c == quote_char:
                    in_quote = False
                i += 1
                continue
            if c in ('"', "'"):
                in_quote = True
                quote_char = c
                current.append(c)
                i += 1
                continue
            matched_delim = None
            for d in delimiters:
                if s[i:i+len(d)] == d:
                    matched_delim = d
                    break
            if matched_delim:
                parts.append((last_delim, "".join(current).strip()))
                current = []
                last_delim = matched_delim
                i += len(matched_delim)
            else:
                current.append(c)
                i += 1
        if current or last_delim:
            parts.append((last_delim, "".join(current).strip()))
        return [(d, p) for d, p in parts if p]

    @staticmethod
    def _is_powershell_command(cmd: str) -> bool:
        trimmed = cmd.strip()
        if trimmed.startswith(("$", "&")):
            return True
        ps_prefixes = (
            "get-", "set-", "test-", "invoke-", "start-", "stop-", "select-", "format-",
            "where-", "out-", "new-", "remove-", "clear-", "write-", "read-", "measure-",
            "compare-", "convertfrom-", "convertto-", "add-type",
        )
        first = trimmed.split()[0].lower() if trimmed.split() else ""
        return any(first.startswith(p) for p in ps_prefixes)

    def classify(self, command: str) -> dict[str, Any]:
        cfg = self.config.get("commands", {})
        trimmed = self._strip_null_redirections(command.strip())
        if not trimmed:
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "empty or unparsable command"}

        # Direct PowerShell syntax or explicit pwsh/powershell invocation
        if self._is_powershell_command(trimmed) or trimmed.lower().startswith(("pwsh", "powershell")):
            return self._classify_single(trimmed)

        # Compound sequences (; or &&) outside quotes
        seq_parts = self._split_outside_quotes(trimmed, (";", "&&"))
        if len(seq_parts) > 1:
            classifications = []
            for _, subcmd in seq_parts:
                sub_res = self.classify(subcmd)
                if not sub_res.get("allowed"):
                    return sub_res
                classifications.append(sub_res)
            classes = [result.get("class", "unknown") for result in classifications]
            order = ["dangerous", "unknown", "mutating", "build", "validation", "read"]
            for o in order:
                if o in classes:
                    return {
                        "class": o,
                        "cacheable": False,
                        "allowed": bool(cfg.get(f"allow_{o}", o in {"read", "validation", "build"})),
                        "replay_safe": o == "validation" and all(
                            bool(result.get("replay_safe", result.get("class") == "read"))
                            for result in classifications
                        ),
                        "reason": f"compound sequence ({o})",
                    }
            return {"class": "read", "cacheable": False, "allowed": True, "reason": "compound sequence"}

        # Pipelines (|) outside quotes
        pipe_parts = self._split_outside_quotes(trimmed, ("|",))
        if len(pipe_parts) > 1:
            first_delim, first_cmd = pipe_parts[0]
            first_res = self._classify_single(first_cmd)
            if not first_res.get("allowed"):
                return first_res
            for _, stage in pipe_parts[1:]:
                stok = self._tokens(stage)
                if not stok:
                    continue
                sexe = ntpath.basename(stok[0].strip('"').replace("/", "\\")).lower()
                sexe_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", sexe)
                if sexe_base not in self.READ_FILTERS and sexe_base not in self.READ_ONLY:
                    return {"class": "unknown", "cacheable": False, "allowed": False, "reason": f"pipeline filter {sexe_base} not allowed"}
            return {
                "class": first_res.get("class", "read"),
                "cacheable": False,
                "allowed": True,
                "replay_safe": bool(first_res.get("replay_safe", False)),
                "reason": "pipeline with safe filters",
            }

        return self._classify_single(trimmed)

    def _classify_single(self, command: str) -> dict[str, Any]:
        tokens = self._tokens(command)
        if not tokens:
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "empty or unparsable command"}
        raw_exe = tokens[0].strip('"').replace("/", "\\")
        exe = ntpath.basename(raw_exe).lower() or Path(tokens[0].strip('"')).name.lower()
        exe_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", exe)
        lower = [t.lower() for t in tokens[1:]]
        cfg = self.config.get("commands", {})

        if exe_base in self.DANGEROUS_EXES:
            return {"class": "dangerous", "cacheable": False, "allowed": False, "reason": "dangerous executable"}

        extra_allowed = set(str(x).strip().lower() for x in cfg.get("extra_allowed_tools", []))
        if exe_base in extra_allowed:
            return {"class": "validation", "cacheable": True, "allowed": True, "reason": f"user-whitelisted tool: {exe_base}"}

        # PowerShell commands or script blocks
        if self._is_powershell_command(command) or exe_base in {"pwsh", "powershell"}:
            cmd_lower = command.lower()
            ps_dangerous = (
                "remove-item", "format-volume", "stop-computer", "restart-computer",
                "stop-process", "invoke-webrequest", "invoke-restmethod", "start-bitstransfer",
                "set-executionpolicy", "new-service", "stop-service", "rmdir /s", "del /s",
                "-encodedcommand", " -e ", " -enc ",
            )
            if any(d in cmd_lower for d in ps_dangerous):
                return {"class": "dangerous", "cacheable": False, "allowed": False, "reason": "dangerous or network powershell command"}

            ps_mutating = (
                "set-content", "add-content", "out-file", "new-item", "copy-item",
                "move-item", "rename-item", "clear-content", "git push", "git commit",
                "git merge", "git reset", "git rebase", "git checkout -b", "git branch -d",
            )
            if any(m in cmd_lower for m in ps_mutating):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "mutating powershell command"}

            validation_keywords = {"test", "validate", "check", "audit", "-runtests", "pester"}
            if any(w in cmd_lower for w in validation_keywords):
                return {"class": "validation", "cacheable": False, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "powershell validation command"}
            if any(w in cmd_lower for w in extra_allowed):
                return {"class": "validation", "cacheable": False, "allowed": bool(cfg.get("allow_validation", True)), "reason": "user-whitelisted powershell tool"}

            ps_read_prefixes = ("get-", "select-", "measure-", "format-", "test-path", "where-", "out-string", "compare-", "convertfrom-", "convertto-")
            first_word = command.strip().split()[0].lower() if command.strip() else ""
            if any(first_word.startswith(p) or f" {p}" in cmd_lower for p in ps_read_prefixes):
                return {"class": "read", "cacheable": False, "allowed": bool(cfg.get("allow_read", True)), "reason": "powershell read command"}

            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "unrecognized powershell command"}

        # Reject dangerous shell subshells in raw non-powershell commands
        unquoted = re.sub(r'("[^"]*"|\'[^\']*\')', '', command)
        if any(op in unquoted for op in ("`", "$(")):
            return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "shell subshells are not accepted"}

        if exe_base == "git":
            unsafe_git_flags = {"--paginate", "--exec-path", "--config-env"}
            if any(flag in unsafe_git_flags or flag.startswith(("--exec-path=", "--config-env=", "--upload-pack=", "--receive-pack=")) for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "git flags may execute a pager or external program"}
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-c" and idx < len(tokens) - 1:
                    config_pair = tokens[idx + 1].lower()
                    if any(config_pair.startswith(bad) for bad in ("core.pager", "pager.", "alias.", "core.fsmonitor", "core.sshcommand")):
                        return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "git -c config may execute arbitrary commands"}

            skip_next = False
            sub = ""
            sub_idx = 0
            for idx, token in enumerate(tokens[1:], 1):
                if skip_next:
                    skip_next = False
                    continue
                if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--no-optional-locks", "--no-pager"}:
                    if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
                        skip_next = True
                    continue
                if token.startswith("-"):
                    continue
                sub = token.lower()
                sub_idx = idx
                break

            if not sub:
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only git"}

            git_read_subs = {
                "status", "diff", "show", "log", "grep", "ls-files", "rev-parse",
                "branch", "tag", "describe", "blame", "remote", "cat-file", "check-ignore",
                "check-attr", "merge-base", "shortlog", "ls-tree", "var", "reflog",
                "version", "whatchanged", "for-each-ref", "show-ref", "rev-list", "diff-tree",
                "hash-object", "check-ref-format", "name-rev", "count-objects", "ls-remote",
                "verify-pack", "verify-commit", "verify-tag",
            }
            if sub in git_read_subs:
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"read-only git {sub}"}

            if sub == "stash":
                stash_args = [t.lower() for t in tokens[sub_idx + 1:] if not t.startswith("-")]
                stash_sub = stash_args[0] if stash_args else "list"
                if stash_sub in {"list", "show"}:
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"read-only git stash {stash_sub}"}

            if sub == "worktree":
                wt_args = [t.lower() for t in tokens[sub_idx + 1:] if not t.startswith("-")]
                wt_sub = wt_args[0] if wt_args else "list"
                if wt_sub in {"list"}:
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"read-only git worktree {wt_sub}"}

            if sub == "config":
                config_args = [t.lower() for t in tokens[sub_idx + 1:]]
                read_flags = {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin", "--show-scope"}
                if any(rf in config_args for rf in read_flags):
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only git config"}

            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"git {sub} may mutate"}

        if exe_base in self.READ_ONLY and exe_base != "git":
            if exe_base in {"rg", "ripgrep"} and any(flag == "--pre" or flag.startswith("--pre=") for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "ripgrep preprocessor may execute arbitrary programs"}
            if exe_base == "find" and any(flag in {"-exec", "-execdir", "-ok", "-okdir", "-delete"} for flag in lower):
                return {"class": "unknown", "cacheable": False, "allowed": False, "reason": "find execution flags are not allowed"}
            return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"{exe_base} read command"}

        if exe_base in {"python", "python3", "py"}:
            dash_m = None
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-m" and idx < len(tokens) - 1:
                    dash_m = tokens[idx + 1].lower()
                    break
            if dash_m is not None:
                validation_modules = {
                    "pytest", "ruff", "mypy", "unittest", "flake8", "compileall", "pyflakes",
                    "pylint", "bandit", "coverage", "tox", "nox", "pre_commit", "pre-commit",
                }
                if dash_m in validation_modules:
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"python -m {dash_m} validation"}
                if dash_m in {"build", "wheel", "setuptools", "flit"}:
                    return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} packaging"}
                if dash_m in {"local_ai_hub", "local_ai_hub.generator"}:
                    return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} dynamic artifacts generator"}
                if dash_m == "pip":
                    pip_sub = [t.lower() for t in tokens[2:] if not t.startswith("-")]
                    pip_action = pip_sub[0] if pip_sub else ""
                    if pip_action in {"list", "show", "check"} or any(flag in lower for flag in {"--version", "-v"}):
                        return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"python -m pip {pip_action or 'info'}"}
                    if pip_action in {"install", "uninstall", "download"}:
                        return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"python -m pip {pip_action} changes environment"}
                if dash_m in {"json.tool", "platform", "sysconfig", "site", "venv", "pydoc"}:
                    return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"python -m {dash_m} inspection"}
                if dash_m in {"black", "isort"}:
                    if any(f in lower for f in {"--check", "--diff"}):
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"python -m {dash_m} validation"}
                    return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"python -m {dash_m} format without --check"}

            dash_c = None
            for idx, arg in enumerate(tokens[1:], 1):
                if arg == "-c" and idx < len(tokens) - 1:
                    dash_c = tokens[idx + 1]
                    break
            if dash_c is not None:
                _DANGEROUS_INLINE = (
                    "os.system(", "os.popen(", "subprocess.", "exec(", "eval(", "__import__(",
                    "importlib.", "ctypes.", "shutil.rmtree", "shutil.move", "os.remove(",
                    "os.unlink(", "os.rmdir(", "socket.", "pty.",
                )
                dash_c_lower = dash_c.lower()
                if any(pat in dash_c_lower for pat in _DANGEROUS_INLINE):
                    return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code contains potentially dangerous call"}

                is_validation = False
                try:
                    tree = ast.parse(dash_c)

                    def _literal_only(node: ast.AST) -> bool:
                        if isinstance(node, ast.Constant):
                            return True
                        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                            return all(_literal_only(item) for item in node.elts)
                        if isinstance(node, ast.Dict):
                            return all(
                                key is not None and _literal_only(key) and _literal_only(value)
                                for key, value in zip(node.keys, node.values)
                            )
                        return False

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            func_name = ""
                            if isinstance(node.func, ast.Name):
                                func_name = node.func.id
                            elif isinstance(node.func, ast.Attribute):
                                func_name = node.func.attr
                            if func_name in {"exec", "eval", "compile"}:
                                return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"python -c inline code contains dangerous call: {func_name}"}
                            if func_name == "open":
                                return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code accesses files with unknown side effects"}
                            if func_name in {"write_text", "write_bytes", "touch", "unlink", "mkdir", "rmdir", "rename", "replace"}:
                                return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"python -c inline code may mutate files: {func_name}"}
                            safe_builtin_calls = {
                                "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
                                "len", "list", "max", "min", "print", "range", "repr", "round",
                                "set", "sorted", "str", "sum", "tuple", "zip",
                            }
                            if (
                                not isinstance(node.func, ast.Name)
                                or func_name not in safe_builtin_calls
                                or not all(_literal_only(arg) for arg in node.args)
                                or not all(_literal_only(keyword.value) for keyword in node.keywords)
                            ):
                                return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"python -c inline code has unverified call: {func_name or 'dynamic'}"}
                        elif isinstance(node, ast.Import):
                            if any(alias.name != "sys" for alias in node.names):
                                return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code imports module with unknown side effects"}
                        elif isinstance(node, ast.ImportFrom):
                            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code imports module with unknown side effects"}
                        elif isinstance(node, ast.Assert):
                            is_validation = True
                except SyntaxError:
                    return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "python -c inline code contains invalid syntax"}

                if not is_validation:
                    tokens_in_code = set(re.findall(r"\b\w+\b", dash_c_lower))
                    validation_keywords = {"test", "validate", "check", "audit", "doctor", "selftest", "report", "assert"}
                    if validation_keywords & tokens_in_code:
                        is_validation = True

                if is_validation:
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "python inline validation"}
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "python inline read"}

            non_flag_args = [t for t in tokens[1:] if not t.startswith("-")]
            if non_flag_args:
                script_name = Path(non_flag_args[0].replace("\\", "/")).name.lower()
                sub_args = [t.lower() for t in non_flag_args[1:]]
                if script_name in {"hubctl.py", "hubctl"}:
                    sub = sub_args[0] if sub_args else ""
                    if sub == "tasks":
                        is_mutating = any(t in lower for t in {"--complete", "--fail"})
                        if is_mutating:
                            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "hubctl tasks status mutation"}
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "hubctl tasks status check"}
                    if sub in {"status", "service-status", "agent-state", "dashboard", "watch", "memory", "doctor", "logs"}:
                        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"hubctl {sub} status check"}
                    if sub == "generate":
                        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "hubctl generate dynamic artifacts"}
                    if sub in {"start", "stop", "restart", "cleanup"}:
                        return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"hubctl {sub} service lifecycle mutation"}
                if script_name in {"setup.py", "setup"}:
                    if any(t in lower for t in {"--generate-only", "--help", "-h"}):
                        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "setup.py generate dynamic artifacts"}
                if any(f in arg.lower() for arg in non_flag_args for f in ("test", "validate", "check", "flow", "status", "audit", "doctor", "selftest", "report", "bench", "benchmark", "inspect", "diagnose", "eval", "summary")):
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "python validation script"}
                if any(f in script_name for f in ("generate", "build", "compile", "bundle")):
                    return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "python build/generate script"}
                if not any(token.lower() in self.MUTATING_WORDS for token in non_flag_args[1:]):
                    return {"class": "read", "cacheable": False, "allowed": bool(cfg.get("allow_read", True)), "reason": "python read script"}

        if exe_base == "hubctl":
            sub = lower[0] if lower else ""
            if sub == "tasks":
                is_mutating = any(t in lower for t in {"--complete", "--fail"})
                if is_mutating:
                    return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "hubctl tasks status mutation"}
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "hubctl tasks status check"}
            if sub in {"status", "service-status", "agent-state", "dashboard", "watch", "memory", "doctor", "logs"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"hubctl {sub} status check"}
            if sub == "generate":
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "hubctl generate dynamic artifacts"}
            if sub in {"start", "stop", "restart", "cleanup"}:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"hubctl {sub} service lifecycle mutation"}

        if exe_base == "php" and lower:
            php_target = ntpath.basename(lower[0].replace("/", "\\"))
            if any(name in php_target for name in ("phpunit", "phpstan", "pest")):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "PHP validation tool"}

        if exe_base in {"black", "isort"}:
            if any(f in lower for f in {"--check", "--diff"}):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} check"}
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} format without --check"}

        if exe_base in self.PURE_VALIDATORS or any(name in exe_base for name in ("phpunit", "phpstan", "pytest", "pest", "flake8", "pylint", "shellcheck", "yamllint")):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} validation tool"}

        positional_verbs = [t.lower() for t in tokens[1:] if not t.startswith(("-", "/"))]
        primary_verb = positional_verbs[0] if positional_verbs else ""

        if exe_base == "dotnet":
            flag_info = {"--info", "--version", "--list-sdks", "--list-runtimes", "--help", "-h", "-v"}
            if any(f in lower for f in flag_info) and not any(v in lower for v in ("build", "test", "run", "clean", "publish")):
                return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only dotnet inspection"}
            if primary_verb in {"test", "vstest"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "dotnet test"}
            if primary_verb in {"build", "compile", "pack", "restore", "clean", "run", "msbuild"}:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"dotnet {primary_verb}"}
            if primary_verb == "format":
                if any(f in lower for f in {"--verify-no-changes", "--check"}):
                    return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "dotnet format check"}
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "dotnet format changes source without --verify-no-changes"}

        package_tools = {"npm", "pnpm", "yarn", "bun"}
        if exe_base in package_tools:
            mutating = {"install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade", "publish", "link", "unlink", "pack", "version"}
            if primary_verb in mutating:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} {primary_verb} changes dependencies or publishes artifacts"}
            script = ""
            if primary_verb in {"run", "run-script"} and len(positional_verbs) > 1:
                script = positional_verbs[1]
            elif primary_verb:
                script = primary_verb
            safe_validation = {"test", "lint", "check", "typecheck", "type-check", "analyse", "analyze", "audit"}
            safe_build = {"build", "compile"}
            if script in safe_validation:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} safe validation script"}
            if script in safe_build:
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} safe build script"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} script is not in the safe validation/build allowlist"}

        if exe_base == "composer":
            if primary_verb in {"install", "update", "upgrade", "remove", "require", "create-project", "dump-autoload", "global"}:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"composer {primary_verb} may change dependencies or generated files"}
            if primary_verb in {"validate", "audit", "test", "phpunit", "phpstan", "analyse", "analyze", "check"}:
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "composer validation command"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "composer command is not in the safe validation allowlist"}

        if exe_base == "make":
            if any(v in {"clean", "install", "uninstall", "deploy", "publish", "release"} for v in positional_verbs):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "make target may mutate or deploy"}
            safe_validation = {"test", "tests", "check", "lint", "validate", "verify", "typecheck"}
            safe_build = {"build", "compile", "all"}
            if positional_verbs and all(v in safe_validation for v in positional_verbs):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "make validation target"}
            if positional_verbs and all(v in safe_build for v in positional_verbs):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "make build target"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "make target is not in the safe validation/build allowlist"}

        if exe_base == "cargo":
            if primary_verb in {"fmt"} and "--check" not in lower:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "cargo fmt changes source without --check"}
            if primary_verb in {"test", "check", "clippy", "bench"} or (primary_verb == "fmt" and "--check" in lower):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "cargo validation command"}
            if primary_verb == "build":
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "cargo build"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "cargo command is not in the safe validation/build allowlist"}

        if exe_base in {"go", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "cmake", "ctest"}:
            if any(v in self.MUTATING_WORDS or v in {"tidy", "publish", "deploy", "release"} for v in positional_verbs):
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} command may mutate project or publish artifacts"}
            validation_words = {"test", "tests", "check", "verify", "lint", "vet", "clippy", "ctest"}
            build_words = {"build", "compile", "package", "assemble"}
            if exe_base == "ctest" or any(v in validation_words for v in positional_verbs):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} validation command"}
            if exe_base == "cmake" or any(v in build_words for v in positional_verbs):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} build command"}
            return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} command is not in the safe validation/build allowlist"}

        if exe_base in self.VALIDATORS:
            if primary_verb in self.MUTATING_WORDS:
                return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"mutating verb {primary_verb}"}
            if any(x in positional_verbs for x in ("build", "compile")):
                return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "build command"}
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "validation/test command"}

        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "command not in safe broker allowlist"}

    @staticmethod
    def _safe_label(command: str) -> str:
        # Local dashboard metadata only; redact common credential-bearing options.
        text = re.sub(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)", r"\1***", command.strip())
        text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1***", text)
        return text[:240]

    @classmethod
    def _needs_shell(cls, command: str) -> bool:
        trimmed = command.strip()
        if cls._is_powershell_command(trimmed):
            return True
        seq = cls._split_outside_quotes(trimmed, (";", "&&", "||", "|", ">", "<"))
        if len(seq) > 1:
            return True
        if any(op in trimmed for op in ("2>&1", "| Out-Null", "| out-null", ">nul", "> nul")):
            return True
        return False

    def _tool_identity(self, command: str, cwd: str) -> dict[str, Any]:
        if self._needs_shell(command):
            raw = (shutil.which("pwsh") or shutil.which("powershell") or "powershell") if os.name == "nt" else (shutil.which("sh") or "/bin/sh")
            candidate = Path(raw)
            try:
                stat = candidate.stat()
                return {"path": str(candidate.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
            except Exception:
                return {"path": str(candidate)}
        tokens = self._tokens(command)
        if not tokens:
            return {}
        raw = tokens[0].strip('"')
        candidate = Path(raw)
        if not candidate.is_absolute():
            local = (Path(cwd) / candidate).resolve(strict=False)
            resolved = local if local.exists() else Path(shutil.which(raw) or raw)
        else:
            resolved = candidate
        try:
            stat = resolved.stat()
            return {"path": str(resolved.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except Exception:
            return {"path": str(resolved)}

    def _key(
        self,
        command: str,
        cwd: str,
        classification: dict[str, Any],
        *,
        cache_context: str = "",
    ) -> tuple[str, dict[str, Any]]:
        state = self.repo_state.fingerprint(cwd)
        commands_config = self.config.get("commands", {})
        env_keys = commands_config.get("environment_keys", ["CI", "NODE_ENV", "APP_ENV", "PYTHONPATH"])
        env = {str(k): os.environ.get(str(k), "") for k in env_keys}
        payload = {
            "command": command.strip(), "cwd": str(Path(cwd).resolve()), "class": classification.get("class"),
            "repo": state.get("fingerprint"), "env": env, "python": sys.version_info[:3], "tool": self._tool_identity(command, cwd),
            "policy": {
                "blocking": self.policy_blocking,
                "allow_read": bool(commands_config.get("allow_read", True)),
                "allow_validation": bool(commands_config.get("allow_validation", True)),
                "allow_build": bool(commands_config.get("allow_build", True)),
                "allow_mutating": bool(commands_config.get("allow_mutating", False)),
                "allow_unknown": bool(commands_config.get("allow_unknown", False)),
                "extra_allowed_tools": sorted(
                    str(tool).strip().lower()
                    for tool in commands_config.get("extra_allowed_tools", [])
                ),
            },
        }
        if cache_context:
            payload["context"] = cache_context
        key = stable_hash(payload)
        return key, state

    def _attempt_key(self, command: str, cwd: str, *, cache_context: str = "") -> str:
        tokens = self._tokens(command)
        cmd_str = " ".join(tokens) if tokens else command.strip()
        commands_config = self.config.get("commands", {})
        payload = {
            "command": cmd_str,
            "cwd": str(Path(cwd).resolve()),
            "tool": self._tool_identity(command, cwd),
            "policy": {
                "blocking": self.policy_blocking,
                "allow_read": bool(commands_config.get("allow_read", True)),
                "allow_validation": bool(commands_config.get("allow_validation", True)),
                "allow_build": bool(commands_config.get("allow_build", True)),
                "allow_mutating": bool(commands_config.get("allow_mutating", False)),
                "allow_unknown": bool(commands_config.get("allow_unknown", False)),
                "extra_allowed_tools": sorted(
                    str(tool).strip().lower()
                    for tool in commands_config.get("extra_allowed_tools", [])
                ),
            },
        }
        if cache_context:
            payload["context"] = cache_context
        return stable_hash(payload)

    def _mark_rollback_outcome_unknown(
        self,
        result: dict[str, Any],
        *,
        command_key: str,
        attempt_key: str,
        error: BaseException,
        rollback_paths: Sequence[str] | None = None,
    ) -> None:
        result.update({
            "rolled_back": False,
            "rollback_paths": list(rollback_paths or ()),
            "rollback_error": str(error)[:512],
            "outcome_unknown": True,
            "fail_closed": True,
            "incident_required": True,
            "cache_hit": False,
            "coalesced": False,
            "retryable": False,
        })
        invalidation_errors: list[str] = []
        for cache, cache_key in (
            (self.success_cache, command_key),
            (self.failure_cache, command_key),
            (self.suppression_cache, attempt_key),
        ):
            try:
                deleted = cache.delete(cache_key)
                if deleted is False:
                    invalidation_errors.append("cache delete reported failure")
            except Exception as cache_exc:
                invalidation_errors.append(str(cache_exc)[:160])
        with self._lock:
            self._last.pop(command_key, None)
        if invalidation_errors:
            result["cache_invalidation_failed"] = True
            result["cache_invalidation_errors"] = invalidation_errors


    def _capture_rollback_unknown_incident(
        self,
        result: dict[str, Any],
        *,
        command: str,
        repository_revision: str = "",
    ) -> None:
        if self.incident_store is None:
            return
        try:
            from .agent_incidents import ToolOutcome

            incident = self.incident_store.capture(ToolOutcome(
                tool_name="command",
                command=command,
                error=f"rollback failed; command filesystem outcome is unknown: {result.get('rollback_error', '')}",
                exit_code=int(result.get("exit_code", 1) or 1),
                state_revision=repository_revision,
                timed_out=bool(result.get("timed_out")),
                cancelled=bool(result.get("cancelled")),
                metadata={"outcome_unknown": True, "rollback_error": result.get("rollback_error", "")},
                affected_paths=tuple(result.get("rollback_paths", ())),
            ))
            if incident:
                result["incident_id"] = incident.incident_id
                result["incident_recorded"] = True
        except Exception:
            pass

    def _unavailable_executable(self, command: str, cwd: str) -> str | None:
        if self._needs_shell(command):
            if os.name == "nt":
                return None if (shutil.which("pwsh") or shutil.which("powershell")) else "powershell"
            return None if (shutil.which("sh") or Path("/bin/sh").exists()) else "sh"
        tokens = self._tokens(command)
        if not tokens:
            return None
        raw = tokens[0].strip('"')
        if os.name == "nt" and raw.lower() in {"ver", "set"}:
            return None if shutil.which("cmd") else "cmd"
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        has_path = any(marker in raw for marker in ("/", "\\"))
        if has_path:
            return None if candidate.exists() else raw
        return None if shutil.which(raw) else raw

    @staticmethod
    def _non_retryable_failure(result: dict[str, Any]) -> bool:
        if result.get("success") or result.get("timed_out"):
            return False
        text = (str(result.get("error", "")) + "\n" + str(result.get("stderr", ""))).lower()
        return int(result.get("exit_code", 0) or 0) == 127 or any(marker in text for marker in (
            "failed to spawn process", "command not found", "is not recognized as an internal", "no such file or directory",
        ))

    _INTERACTIVE_PATTERNS = [
        re.compile(r"\[y/n\]", re.I),
        re.compile(r"\(y/n\)", re.I),
        re.compile(r"password\s*:", re.I),
        re.compile(r"enter\s+(?:passphrase|password|pin|key|choice)", re.I),
        re.compile(r"press\s+(?:any\s+key|enter)\s+to\s+continue", re.I),
        re.compile(r"do\s+you\s+want\s+to\s+continue\s*\?", re.I),
        re.compile(r"are\s+you\s+sure\s*\?", re.I),
    ]

    @classmethod
    def _is_interactive_prompt(cls, text: str) -> bool:
        if not text:
            return False
        return any(p.search(text) for p in cls._INTERACTIVE_PATTERNS)

    def _execute(
        self,
        command: str,
        cwd: str,
        timeout: int,
        cancel_event: threading.Event | None = None,
        log_callback: Any | None = None,
        *,
        argv_override: Sequence[str] | None = None,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        tokens = self._tokens(command)
        if argv_override is not None:
            argv = list(argv_override)
        elif self._needs_shell(command):
            if os.name == "nt":
                shell_bin = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
                argv = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", command]
            else:
                if self._is_powershell_command(command) and shutil.which("pwsh"):
                    argv = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", command]
                else:
                    argv = ["/bin/sh", "-c", command]
        elif os.name == "nt":
            raw0 = tokens[0].strip('"') if tokens else ""
            if raw0.lower() in {"ver", "set"}:
                comspec = os.environ.get("COMSPEC", "cmd.exe")
                argv = [comspec, "/d", "/c", command]
            else:
                suffix = Path(raw0).suffix.lower()
                resolved = shutil.which(raw0) or shutil.which(raw0, path=cwd)
                if (resolved and Path(resolved).suffix.lower() in {".bat", ".cmd"}) or suffix in {".bat", ".cmd"}:
                    comspec = os.environ.get("COMSPEC", "cmd.exe")
                    argv = [comspec, "/d", "/c"] + tokens
                else:
                    argv = tokens
        else:
            argv = tokens
        proc_env = os.environ.copy()
        proc_env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc_env["PYTHONIOENCODING"] = "utf-8"
        if environment_overrides:
            proc_env.update(environment_overrides)
        kwargs: dict[str, Any] = {
            "cwd": str(Path(cwd).resolve()), "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "env": proc_env,
        }
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(argv, **kwargs)
            if os.name == "nt" and _GLOBAL_WINDOWS_JOB is not None:
                try:
                    assign_process_to_job(_GLOBAL_WINDOWS_JOB, process.pid)
                except Exception:
                    pass
        except OSError as exc:
            return {
                "success": False, "exit_code": 127, "timed_out": False,
                "stdout": "", "stderr": str(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": f"failed to spawn process: {exc}",
            }

        out_buf = _BoundedStreamBuffer(self.max_output_chars)
        err_buf = _BoundedStreamBuffer(self.max_output_chars)
        callback_queue: queue.Queue[tuple[str, str]] | None = (
            queue.Queue(maxsize=_COMMAND_LOG_QUEUE_MAX_CHUNKS)
            if log_callback is not None
            else None
        )
        callback_dropped = 0
        callback_drop_lock = threading.Lock()
        readers_remaining = 2
        readers_lock = threading.Lock()
        readers_done = threading.Event()

        def _dispatch_logs() -> None:
            assert callback_queue is not None and log_callback is not None
            while True:
                try:
                    item = callback_queue.get(timeout=0.05)
                except queue.Empty:
                    if readers_done.is_set():
                        return
                    continue
                try:
                    log_callback(*item)
                except Exception:
                    pass
                finally:
                    callback_queue.task_done()

        log_dispatcher = (
            threading.Thread(target=_dispatch_logs, name="command-log-dispatch", daemon=True)
            if callback_queue is not None
            else None
        )
        if log_dispatcher is not None:
            log_dispatcher.start()

        def _publish_log(stream_name: str, text: str) -> None:
            nonlocal callback_dropped
            if callback_queue is None:
                return
            try:
                callback_queue.put_nowait((stream_name, text))
            except queue.Full:
                with callback_drop_lock:
                    callback_dropped += 1

        def _reader(stream: Any, buf: _BoundedStreamBuffer, stream_name: str) -> None:
            last_callback_time = 0.0
            callback_min_interval = 0.005  # Max ~200 callbacks/sec to prevent downstream lock/choking
            pending_batch: list[str] = []
            decoder = io.IncrementalNewlineDecoder(
                codecs.getincrementaldecoder("utf-8")(errors="replace"),
                translate=True,
            )
            read_chunk = getattr(stream, "read1", None) or stream.read
            try:
                for raw_chunk in iter(lambda: read_chunk(65536), b""):
                    if not raw_chunk:
                        break
                    chunk = decoder.decode(raw_chunk)
                    if not chunk:
                        continue
                    buf.append(chunk)
                    if log_callback:
                        now = time.monotonic()
                        if now - last_callback_time >= callback_min_interval:
                            if pending_batch:
                                text = "".join(pending_batch) + chunk
                                pending_batch.clear()
                            else:
                                text = chunk
                            last_callback_time = now
                            _publish_log(stream_name, text)
                        else:
                            pending_batch.append(chunk)
                            if len(pending_batch) >= 50:
                                text = "".join(pending_batch)
                                pending_batch.clear()
                                last_callback_time = now
                                _publish_log(stream_name, text)
                tail = decoder.decode(b"", final=True)
                if tail:
                    buf.append(tail)
                    pending_batch.append(tail)
                if log_callback and pending_batch:
                    _publish_log(stream_name, "".join(pending_batch))
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
                nonlocal readers_remaining
                with readers_lock:
                    readers_remaining -= 1
                    if readers_remaining == 0:
                        readers_done.set()

        t_out = threading.Thread(target=_reader, args=(process.stdout, out_buf, "stdout"), daemon=True)
        t_err = threading.Thread(target=_reader, args=(process.stderr, err_buf, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        timed_out = False
        cancelled = False
        aborted_interactive = False
        deadline = time.monotonic() + max(1, timeout)
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            peek_out = out_buf.peek(500)
            peek_err = err_buf.peek(500)
            if self._is_interactive_prompt(peek_out) or self._is_interactive_prompt(peek_err):
                aborted_interactive = True
                break
            time.sleep(0.02)

        if timed_out or cancelled or aborted_interactive:
            try:
                terminate_tree(process.pid, grace_seconds=self.terminate_grace_seconds)
            except Exception:
                pass
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=max(2.0, self.terminate_grace_seconds))
            except Exception:
                pass
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass

        # A successful child can exit before the reader/callback threads finish
        # publishing their last SSE/event chunks.  Keep the drain bounded, but
        # give callback delivery a small scheduler-load margin so callers never
        # observe a successful command before its final stream evidence exists.
        drain_seconds = max(self.post_kill_drain_seconds, 5.0)
        drain_deadline = time.monotonic() + drain_seconds
        t_out.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        t_err.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        if log_dispatcher is not None:
            log_dispatcher.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        try:
            if process.stdout and not process.stdout.closed:
                process.stdout.close()
        except Exception:
            pass
        try:
            if process.stderr and not process.stderr.closed:
                process.stderr.close()
        except Exception:
            pass
        try:
            process.wait(timeout=1.0)
        except Exception:
            pass

        stdout = out_buf.getvalue()
        stderr = err_buf.getvalue()
        self.executed += 1
        return {
            "success": (not timed_out) and (not cancelled) and (not aborted_interactive) and process.returncode == 0,
            "exit_code": -9 if (timed_out or cancelled or aborted_interactive) else int(process.returncode or 0),
            "timed_out": timed_out, "cancelled": cancelled, "aborted_interactive": aborted_interactive,
            "stdout": stdout, "stderr": stderr,
            "log_chunks_dropped": callback_dropped,
            "log_dispatch_incomplete": bool(log_dispatcher and log_dispatcher.is_alive()),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            **({"error": "interactive_prompt_detected: command aborted because it requested interactive input"} if aborted_interactive else {"error": "command cancelled"} if cancelled else {"error": f"command timed out after {timeout}s"} if timed_out else {}),
        }

    @staticmethod
    def _cancel_key(command: str, cwd: str) -> str:
        return stable_hash({"command": command.strip(), "cwd": str(Path(cwd).resolve())})

    @staticmethod
    def _tenant_identity(tenant: str) -> str:
        """Return collision-resistant tenant identity without retaining its raw value."""
        return stable_hash({"tenant": str(tenant)})

    @staticmethod
    def _public_active(active: dict[str, Any]) -> dict[str, Any]:
        """Expose bounded active-command metadata without tenant identity or raw tenant."""
        return {key: value for key, value in active.items() if key not in {"tenant", "tenant_identity"}}

    def cancel(self, command: str, cwd: str, tenant: str, *, execution_id: str = "") -> dict[str, Any]:
        """Request bounded cancellation of one currently running broker command."""
        lookup = self._cancel_key(command, cwd)
        tenant_key = self._tenant_identity(tenant)
        with self._lock:
            if execution_id:
                matches = [
                    item for item, active in self._active_commands.items()
                    if active.get("execution_id") == execution_id and active.get("tenant_identity") == tenant_key
                ]
            else:
                matches = [item for item, value in self._active_cancel_keys.items() if value == (lookup, tenant_key)]
            if len(matches) > 1:
                return {
                    "success": False, "terminal": True, "retryable": False,
                    "error": "multiple matching active commands; provide execution_id",
                    "execution_ids": [str(self._active_commands[item].get("execution_id", "")) for item in matches],
                }
            key = matches[0] if matches else ""
            event = self._cancel_events.get(key) if key else None
            active = self._public_active(dict(self._active_commands.get(key, {}))) if key else {}
            if event is None:
                return {"success": False, "terminal": True, "retryable": False, "error": "no matching active command"}
            event.set()
            self.cancelled += 1
        return {"success": True, "cancellation_requested": True, "execution_id": active.get("execution_id", ""), "active": active}

    @staticmethod
    def _extract_diagnostics(result: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
        # stdout/stderr are captured independently, so their true interleaving is
        # unavailable. Preserve each stream's order while preferring explicit
        # failures over informational diagnostics and warnings from a failed run.
        # This keeps an early stdout warning from masking the useful stderr error.
        streams = (str(result.get("stdout", "")), str(result.get("stderr", "")))
        failures: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        patterns = _DIAGNOSTIC_PATTERNS
        failure_terms = ("error", "fatal", "exception", "traceback", "assertionerror", "panic", "failed", "failure")
        for text in streams:
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                matched = None
                matched_failure = False
                for pattern_index, pattern in enumerate(patterns):
                    m = pattern.match(line)
                    if m:
                        matched = m
                        # The dedicated pytest `FAILED path::test` pattern keeps
                        # the path but strips the word FAILED from its message.
                        # Preserve its failure semantics from the original line.
                        matched_failure = pattern_index == 1
                        break
                message = ""
                diagnostic: dict[str, Any] | None = None
                if matched:
                    data = matched.groupdict()
                    message = str(data.get("msg") or line)[:500]
                    diagnostic = {
                        "path": data.get("path", ""),
                        "line": int(data.get("line") or 0),
                        "column": int(data.get("col") or 0),
                        "message": message,
                    }
                elif any(term in line.lower() for term in failure_terms):
                    message = line[:500]
                    diagnostic = {"path": "", "line": 0, "column": 0, "message": message}
                if diagnostic is None:
                    continue
                target = failures if (
                    matched_failure
                    or any(term in line.lower() for term in failure_terms)
                ) else others
                if len(target) < limit:
                    target.append(diagnostic)
        return (failures + others)[:limit]

    @classmethod
    def _first_failure_summary(cls, result: dict[str, Any]) -> dict[str, Any]:
        """Return first deterministic failure location without replaying verbose logs."""
        diagnostics = list(result.get("diagnostics") or cls._extract_diagnostics(result, limit=1))
        if diagnostics:
            first = diagnostics[0]
            return {
                "path": str(first.get("path") or ""),
                "line": int(first.get("line") or 0),
                "message": str(first.get("message") or "").strip()[:500],
            }
        return {
            "path": "",
            "line": 0,
            "message": cls._distill_error(result)[:500],
        }

    @staticmethod
    def _failure_preview(summary: dict[str, Any]) -> str:
        """Expose only the narrow first-failure slice in command results."""
        path = str(summary.get("path") or "")
        line = int(summary.get("line") or 0)
        message = str(summary.get("message") or "").strip()
        if path and line:
            return f"{path}:{line}: {message}"[:800]
        if path:
            return f"{path}: {message}"[:800]
        return message[:800]

    @staticmethod
    def _deterministic_summary(result: dict[str, Any], limit: int = 60) -> str:
        text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))).strip()
        lines = text.splitlines()
        if len(lines) <= limit:
            return text
        needles = ("error", "fail", "fatal", "warning", "assert", "exception", "traceback", "passed", "failed", "success", "tests", "errors")
        selected = [line for line in lines if any(n in line.lower() for n in needles)]
        # Keep final framework summary because pytest/phpunit/cargo/go normally report counts there.
        tail = lines[-min(12, len(lines)):]
        for line in tail:
            if line not in selected:
                selected.append(line)
        if len(selected) < limit // 2:
            selected = lines[: max(8, limit // 5)] + selected
        return "\n".join(selected[:limit])

    @staticmethod
    def _distill_error(result: dict[str, Any]) -> str:
        """Extract a high-density, concise 1-3 line failure cause from command output."""
        if result.get("success"):
            return ""
        diagnostics = result.get("diagnostics", [])
        if diagnostics:
            parts = []
            for d in diagnostics[:2]:
                path = d.get("path")
                line = d.get("line")
                msg = str(d.get("message") or "").strip()
                if path and line:
                    parts.append(f"{path}:{line}: {msg}")
                elif msg:
                    parts.append(msg)
            if parts:
                return "\n".join(parts)[:300]
        text = (str(result.get("stderr", "")) + "\n" + str(result.get("stdout", ""))).strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            for ln in reversed(lines):
                if any(k in ln.lower() for k in ("error", "failed", "exception", "fatal", "traceback")):
                    return ln[:240]
            return lines[-1][:240]
        return f"Command failed with exit code {result.get('exit_code', 1)}"

    @staticmethod
    def _needs_model_error_distillation(result: dict[str, Any]) -> bool:
        if result.get("diagnostics"):
            return False
        text = (str(result.get("stderr", "")) + "\n" + str(result.get("stdout", ""))).strip()
        return bool(text)

    @staticmethod
    def _transaction_docker_argv(
        transaction_id: str,
        transaction_root: Path,
        command: str,
        image: str,
        *,
        read_only_mount: bool = False,
    ) -> list[str]:
        mount_mode = "ro" if read_only_mount else "rw"
        return [
            "docker", "run", "--rm", "--init", "--name", f"local-ai-{transaction_id}",
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=2g",
            "--cpus=2", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
            "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTEST_ADDOPTS=-p no:cacheprovider",
            "--env", "GIT_CONFIG_GLOBAL=/workspace/.git/transaction-global-config",
            "--env", "GIT_CONFIG_SYSTEM=/dev/null", "--env", "GIT_CONFIG_NOSYSTEM=1",
            "--volume", f"{transaction_root}:/workspace:{mount_mode}", "--workdir", "/workspace",
            image, "/bin/sh", "-lc", command,
        ]

    @staticmethod
    def _transaction_docker_ready() -> tuple[bool, str]:
        executable = shutil.which("docker")
        if not executable:
            return False, "docker executable not found for private command transaction"
        try:
            probe = subprocess.run(
                [executable, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                **hidden_run_kwargs(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Docker engine unavailable for private command transaction: {str(exc)[:240]}"
        if probe.returncode != 0 or not probe.stdout.strip():
            detail = (probe.stderr or probe.stdout or "Docker engine unavailable").strip()[:240]
            return False, f"Docker engine unavailable for private command transaction: {detail}"
        return True, ""

    def _transaction_stop_container(transaction_id: str) -> bool:
        executable = shutil.which("docker")
        if not executable:
            return False
        name = f"local-ai-{transaction_id}"
        try:
            probe = subprocess.run(
                [executable, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                **hidden_run_kwargs(),
            )
            if probe.returncode != 0 or not probe.stdout.strip():
                return False
            subprocess.run(
                [executable, "rm", "--force", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                **hidden_run_kwargs(),
            )
            remaining = subprocess.run(
                [executable, "inspect", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=8,
                **hidden_run_kwargs(),
            )
            return remaining.returncode != 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _transaction_root_for_context(self, transaction_id: str) -> Path:
        with self._transaction_roots_lock:
            active = self._active_transaction_roots.get(transaction_id)
        return active if active is not None else (self._transaction_state_dir / transaction_id)

    def _transaction_file_matches(left: RollbackFileSnapshot, right: RollbackFileSnapshot) -> bool:
        return (
            left.content == right.content
            and left.mode == right.mode
            and left.xattrs == right.xattrs
            and left.mtime_ns == right.mtime_ns
        )

    def _recover_partial_transaction_import(
        self,
        source: Path,
        source_snapshot: RollbackSnapshot,
        transaction_snapshot: RollbackSnapshot,
        paths: list[str],
    ) -> bool:
        current, error = _snapshot_rollback_scope(str(source), paths)
        if error or current is None:
            return False
        try:
            _capture_rollback_postimages(current)
            restore_paths: list[str] = []
            for path in paths:
                observed = current.files[path]
                before = source_snapshot.files[path]
                after = transaction_snapshot.files[path]
                if self._transaction_file_matches(observed, before):
                    continue
                if not self._transaction_file_matches(observed, after):
                    return False
                source_snapshot.postimages[path] = current.postimages[path]
                restore_paths.append(path)
            if restore_paths:
                rollback = RollbackSnapshot(
                    root=source_snapshot.root,
                    root_identity=source_snapshot.root_identity,
                    files={path: source_snapshot.files[path] for path in restore_paths},
                    root_guard=source_snapshot.root_guard,
                    postimages={path: source_snapshot.postimages[path] for path in restore_paths},
                )
                _restore_rollback_scope(str(source), rollback)
            verified, verify_error = _snapshot_rollback_scope(str(source), paths)
            if verify_error or verified is None:
                return False
            try:
                return all(
                    self._transaction_file_matches(verified.files[path], source_snapshot.files[path])
                    for path in paths
                )
            finally:
                _close_rollback_root(verified.root_guard)
        except (OSError, ValueError):
            return False
        finally:
            _close_rollback_root(current.root_guard)

    @staticmethod
    def _transaction_file_payload(snapshot: RollbackFileSnapshot) -> dict[str, Any]:
        return {
            "content": base64.b64encode(snapshot.content).decode("ascii") if snapshot.content is not None else None,
            "mode": snapshot.mode,
            "xattrs": {
                name: base64.b64encode(value).decode("ascii")
                for name, value in snapshot.xattrs.items()
            },
            "windows_dacl": base64.b64encode(snapshot.windows_dacl).decode("ascii")
            if snapshot.windows_dacl is not None else None,
            "atime_ns": snapshot.atime_ns,
            "mtime_ns": snapshot.mtime_ns,
        }

    def _transaction_file_from_payload(payload: Any) -> RollbackFileSnapshot:
        if not isinstance(payload, dict):
            raise ValueError("transaction journal file entry is invalid")
        encoded_content = payload.get("content")
        content = base64.b64decode(encoded_content, validate=True) if encoded_content is not None else None
        raw_xattrs = payload.get("xattrs", {})
        if not isinstance(raw_xattrs, dict) or len(raw_xattrs) > 256:
            raise ValueError("transaction journal metadata is invalid")
        xattrs = {
            str(name): base64.b64decode(value, validate=True)
            for name, value in raw_xattrs.items()
        }
        encoded_dacl = payload.get("windows_dacl")
        windows_dacl = base64.b64decode(encoded_dacl, validate=True) if encoded_dacl is not None else None
        mode = payload.get("mode")
        atime_ns = payload.get("atime_ns")
        mtime_ns = payload.get("mtime_ns")
        if mode is not None and not isinstance(mode, int):
            raise ValueError("transaction journal mode is invalid")
        if atime_ns is not None and not isinstance(atime_ns, int):
            raise ValueError("transaction journal atime is invalid")
        if mtime_ns is not None and not isinstance(mtime_ns, int):
            raise ValueError("transaction journal mtime is invalid")
        return RollbackFileSnapshot(content, mode, xattrs, windows_dacl, atime_ns, mtime_ns)

    def _persist_transaction_journal(path: Path, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _recover_transaction_journals(
        self,
        source: Path,
        task_id: str,
        transaction_parent: Path,
        lease_tenant: str,
    ) -> dict[str, Any] | None:
        for journal_path in sorted(transaction_parent.glob("*.journal.json")):
            lease: dict[str, Any] | None = None
            journal: dict[str, Any] = {}
            try:
                if journal_path.stat().st_size > 96 * 1024 * 1024:
                    raise ValueError("transaction journal exceeds size limit")
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                if not isinstance(journal, dict):
                    raise ValueError("transaction journal is invalid")
                if journal.get("schema") != 1:
                    raise ValueError("transaction journal schema is unsupported")
                if journal.get("source_root") != str(source) or journal.get("task_id") != task_id:
                    continue
                files = journal.get("files")
                paths = journal.get("paths")
                if (
                    not isinstance(files, dict)
                    or not isinstance(paths, list)
                    or len(paths) != len(set(paths))
                    or set(paths) != set(files)
                ):
                    raise ValueError("transaction journal write set is invalid")
                if any(not isinstance(path, str) or not isinstance(entries, dict) for path, entries in files.items()):
                    raise ValueError("transaction journal file entry is invalid")
                if any(
                    not isinstance(path, str)
                    or not path
                    or Path(path).is_absolute()
                    or ".." in Path(path).parts
                    for path in paths
                ):
                    raise ValueError("transaction journal path is invalid")
                before = {path: self._transaction_file_from_payload(files[path].get("before")) for path in paths}
                after = {path: self._transaction_file_from_payload(files[path].get("after")) for path in paths}
                lease = self._transaction_leases.claim(
                    tenant=lease_tenant,
                    root=str(source),
                    paths=list(paths),
                    ttl_seconds=300,
                    purpose=f"recover command transaction {journal.get('transaction_id', '')}",
                )
                if not lease.get("success"):
                    return {
                        "success": False,
                        "transaction_id": str(journal.get("transaction_id", "")),
                        "transaction_status": "recovery_required",
                        "failure_kind": "destination_conflict",
                        "outcome_unknown": True,
                        "retryable": False,
                        "terminal": True,
                        "error": str(lease.get("error") or "transaction recovery lease denied")[:512],
                    }
                current, scope_error = _snapshot_rollback_scope(str(source), list(paths))
                if scope_error or current is None:
                    raise OSError(scope_error or "cannot inspect transaction recovery targets")
                try:
                    _capture_rollback_postimages(current)
                    pending: list[str] = []
                    for path in paths:
                        observed = current.files[path]
                        if self._transaction_file_matches(observed, after[path]):
                            continue
                        if not self._transaction_file_matches(observed, before[path]):
                            raise OSError(f"transaction recovery conflict at {path}")
                        pending.append(path)
                    if pending:
                        import_files = {
                            path: RollbackFileSnapshot(
                                after[path].content,
                                after[path].mode,
                                after[path].xattrs,
                                current.files[path].windows_dacl,
                                after[path].atime_ns,
                                after[path].mtime_ns,
                            )
                            for path in pending
                        }
                        import_snapshot = RollbackSnapshot(
                            current.root,
                            current.root_identity,
                            import_files,
                            current.root_guard,
                            {path: current.postimages[path] for path in pending},
                        )
                        _restore_rollback_scope(str(source), import_snapshot)
                    verified, verify_error = _snapshot_rollback_scope(str(source), list(paths))
                    if verify_error or verified is None:
                        raise OSError(verify_error or "cannot verify recovered transaction outputs")
                    try:
                        if not all(
                            self._transaction_file_matches(verified.files[path], after[path])
                            for path in paths
                        ):
                            raise OSError("transaction recovery postimages did not verify")
                    finally:
                        _close_rollback_root(verified.root_guard)
                finally:
                    _close_rollback_root(current.root_guard)
                journal_path.unlink()
                transaction_root_value = journal.get("transaction_root")
                if isinstance(transaction_root_value, str):
                    transaction_root = Path(transaction_root_value).resolve(strict=False)
                    try:
                        transaction_relative = transaction_root.relative_to(
                            transaction_parent.resolve(strict=True)
                        )
                    except ValueError:
                        pass
                    else:
                        if transaction_relative.parts:
                            shutil.rmtree(transaction_root, ignore_errors=True)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return {
                    "success": False,
                    "transaction_id": str(journal.get("transaction_id", "")),
                    "transaction_status": "recovery_required",
                    "failure_kind": "destination_conflict",
                    "outcome_unknown": True,
                    "retryable": False,
                    "terminal": True,
                    "error": str(exc)[:512],
                }
            finally:
                if lease is not None and lease.get("success"):
                    self._transaction_leases.release(lease_tenant, str(lease.get("lease_id") or ""))
        return None

    def _run_private_transaction(
        self,
        command: str,
        source_root: str | Path,
        tenant: str,
        *,
        task_id: str,
        paths: list[str],
        timeout: int,
        docker_image: str,
        cancel_event: threading.Event | None = None,
        log_callback: Any | None = None,
        operation: Any | None = None,
        command_key: str = "",
        attempt_key: str = "",
    ) -> dict[str, Any]:
        transaction_id = uuid.uuid4().hex
        if not isinstance(docker_image, str) or not docker_image.strip() or "\x00" in docker_image:
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "discarded", "failure_kind": "sandbox_unavailable",
                "error": "invalid Docker image for private command transaction",
                "terminal": True, "retryable": False,
            }
        ready, ready_error = self._transaction_docker_ready()
        if not ready:
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "discarded", "failure_kind": "sandbox_unavailable",
                "error": ready_error, "mutation_sandbox_required": True,
                "terminal": True, "retryable": False,
            }

        source = Path(canonical_root(source_root)).resolve(strict=True)
        if not attempt_key:
            attempt_key = self._attempt_key(command, str(source))
        if not command_key:
            try:
                command_key, _transaction_state = self._key(
                    command, str(source), self.classify(command)
                )
            except (OSError, ValueError, RuntimeError):
                command_key = ""
        transaction_name = f"command-transaction:{transaction_id}"
        transaction_parent = self._transaction_state_dir
        source_resolved = source.resolve(strict=True)
        transaction_parent_resolved = transaction_parent.resolve(strict=False)
        try:
            transaction_parent_resolved.relative_to(source_resolved)
            overlaps_source = True
        except ValueError:
            try:
                source_resolved.relative_to(transaction_parent_resolved)
                overlaps_source = True
            except ValueError:
                overlaps_source = False
        if overlaps_source:
            fallback = Path(tempfile.gettempdir()) / "local-ai-hub-command-transactions"
            state_key = hashlib.sha256(str(self._transaction_state_dir.resolve()).encode("utf-8")).hexdigest()[:20]
            transaction_parent = fallback / state_key
        transaction_parent.mkdir(parents=True, exist_ok=True)
        try:
            recovery = self._recover_transaction_journals(
                source, task_id, transaction_parent,
                f"recovery:{task_id}:{hashlib.sha256(str(source).encode()).hexdigest()[:16]}",
            )
        except OSError as exc:
            return {
                "success": False,
                "transaction_id": transaction_id,
                "transaction_status": "recovery_required",
                "failure_kind": "destination_conflict",
                "outcome_unknown": True,
                "retryable": False,
                "terminal": True,
                "error": str(exc)[:512],
            }
        if recovery is not None:
            recovery.setdefault("transaction_id", transaction_id)
            if recovery.get("outcome_unknown"):
                recovery_paths = recovery.get("rollback_paths", paths)
                if not isinstance(recovery_paths, list):
                    recovery_paths = paths
                recovery_error = RuntimeError(str(recovery.get("error") or "transaction recovery outcome is unknown"))
                self._mark_rollback_outcome_unknown(
                    recovery,
                    command_key=command_key,
                    attempt_key=attempt_key,
                    error=recovery_error,
                    rollback_paths=recovery_paths,
                )
                self._capture_rollback_unknown_incident(recovery, command=command)
            return recovery
        lease = self._transaction_leases.claim(
            tenant=transaction_name,
            root=str(source),
            paths=paths,
            ttl_seconds=min(7200, max(30, int(timeout) + 60)),
            purpose=f"command transaction task={task_id}",
        )
        if not lease.get("success"):
            return {
                "success": False, "transaction_id": transaction_id,
                "transaction_status": "discarded", "failure_kind": "destination_conflict",
                "error": str(lease.get("error") or "transaction write-set lease denied")[:512],
                "terminal": True, "retryable": False,
            }

        transaction_root = transaction_parent / transaction_id
        source_snapshot: RollbackSnapshot | None = None
        transaction_snapshot: RollbackSnapshot | None = None
        retain_transaction = False
        retain_lease = False
        result: dict[str, Any] = {
            "success": False, "transaction_id": transaction_id,
            "transaction_status": "discarded", "failure_kind": "command_failed",
            "terminal": True, "retryable": False,
        }
        try:
            source_snapshot, scope_error = _snapshot_rollback_scope(str(source), paths)
            if scope_error or source_snapshot is None:
                result.update({
                    "error": scope_error or "cannot snapshot transaction write set",
                    "failure_kind": "destination_conflict",
                })
                return result
            _capture_rollback_postimages(source_snapshot)
            if any(not entry.safe for entry in source_snapshot.postimages.values()):
                result.update({
                    "error": "transaction source write set could not be verified",
                    "failure_kind": "destination_conflict",
                })
                return result

            transaction_parent.mkdir(parents=True, exist_ok=True)
            transaction_root, baseline = create_private_transaction_snapshot_with_manifest(
                source, transaction_root
            )
            with self._transaction_roots_lock:
                self._active_transaction_roots[transaction_id] = transaction_root.resolve(strict=True)
            if callable(operation):
                try:
                    execution = operation(transaction_root, transaction_id)
                except subprocess.TimeoutExpired as exc:
                    execution = {
                        "success": False,
                        "exit_code": -1,
                        "timed_out": True,
                        "cleanup_unconfirmed": True,
                        "error": f"transaction operation timed out: {exc}",
                        "stdout": "",
                        "stderr": "",
                    }
            else:
                argv = self._transaction_docker_argv(
                    transaction_id, transaction_root, command, docker_image
                )
                try:
                    execution = self._execute(
                        argv,
                        str(transaction_root),
                        timeout,
                        cancel_event,
                        log_callback=log_callback,
                    )
                except subprocess.TimeoutExpired as exc:
                    execution = {
                        "success": False,
                        "exit_code": -1,
                        "timed_out": True,
                        "cleanup_unconfirmed": True,
                        "error": f"transaction command timed out: {exc}",
                        "stdout": "",
                        "stderr": "",
                    }
            result.update(execution)
            result["transaction_id"] = transaction_id

            cleanup_confirmed = not bool(execution.get("cleanup_unconfirmed"))
            if execution.get("timed_out") or execution.get("cancelled") or not cleanup_confirmed:
                cleanup_confirmed = self._transaction_stop_container(transaction_id)
            if not cleanup_confirmed:
                retain_transaction = True
                retain_lease = True
                self._mark_rollback_outcome_unknown(
                    result,
                    command_key=command_key,
                    attempt_key=attempt_key,
                    error=OSError("transaction container termination could not be confirmed"),
                    rollback_paths=paths,
                )
                self._capture_rollback_unknown_incident(result, command=command)
                result.update({
                    "success": False,
                    "transaction_status": "recovery_required",
                    "failure_kind": "child_termination_unconfirmed",
                    "outcome_unknown": True,
                    "retryable": False,
                    "terminal": True,
                    "error": "transaction container termination could not be confirmed",
                })
                return result
            if execution.get("cleanup_unconfirmed"):
                execution["cleanup_unconfirmed"] = False
                result["cleanup_unconfirmed"] = False

            if not execution.get("success"):
                try:
                    verify_transaction_source_unchanged(source, baseline, paths)
                except (OSError, ValueError) as exc:
                    retain_transaction = True
                    retain_lease = True
                    self._mark_rollback_outcome_unknown(
                        result,
                        command_key=command_key,
                        attempt_key=attempt_key,
                        error=exc,
                        rollback_paths=paths,
                    )
                    self._capture_rollback_unknown_incident(result, command=command)
                    result.update({
                        "success": False,
                        "transaction_status": "recovery_required",
                        "failure_kind": "destination_conflict",
                        "rolled_back": False,
                        "fail_closed": True,
                        "incident_required": True,
                        "rollback_paths": list(paths),
                        "outcome_unknown": True,
                        "retryable": False,
                        "terminal": True,
                        "error": str(exc)[:512],
                    })
                    return result
                if execution.get("outcome_unknown") or execution.get("cleanup_unconfirmed"):
                    if not result.get("incident_required"):
                        self._mark_rollback_outcome_unknown(
                            result,
                            command_key=command_key,
                            attempt_key=attempt_key,
                            error=OSError(str(result.get("error") or "transaction outcome is unknown")),
                            rollback_paths=paths,
                        )
                        self._capture_rollback_unknown_incident(result, command=command)
                    result.update({
                        "success": False,
                        "transaction_status": "discarded",
                        "failure_kind": "command_outcome_unknown",
                        "rolled_back": bool(result.get("rolled_back", True)),
                        "source_unchanged": True,
                        "outcome_unknown": True,
                        "fail_closed": True,
                        "incident_required": True,
                        "retryable": False,
                        "terminal": True,
                    })
                    return result
                result.update({
                    "success": False,
                    "transaction_status": "discarded",
                    "failure_kind": (
                        "timeout" if execution.get("timed_out") else
                        "cancelled" if execution.get("cancelled") else "command_failed"
                    ),
                    "outcome_unknown": False,
                    "rolled_back": True,
                    "source_unchanged": True,
                    "retryable": False,
                    "terminal": True,
                })
                return result

            try:
                verify_transaction_source_unchanged(source, baseline, paths)
                changes = validate_transaction_output(baseline, transaction_root, paths)
            except (OSError, ValueError) as exc:
                source_conflict = "source path changed while command was running" in str(exc)
                if source_conflict:
                    retain_transaction = True
                    retain_lease = True
                    self._mark_rollback_outcome_unknown(
                        result,
                        command_key=command_key,
                        attempt_key=attempt_key,
                        error=exc,
                        rollback_paths=paths,
                    )
                    self._capture_rollback_unknown_incident(result, command=command)
                result.update({
                    "success": False,
                    "transaction_status": "recovery_required" if source_conflict else "discarded",
                    "failure_kind": (
                        "undeclared_output" if "undeclared transaction output" in str(exc)
                        else "destination_conflict" if source_conflict
                        else "import_failed"
                    ),
                    "outcome_unknown": source_conflict,
                    "rolled_back": not source_conflict,
                    "source_unchanged": not source_conflict,
                    "retryable": False,
                    "terminal": True,
                    "error": str(exc)[:512],
                })
                return result

            changed_paths = list(changes)
            try:
                if changed_paths:
                    transaction_snapshot, output_error = _snapshot_rollback_scope(
                        str(transaction_root), changed_paths
                    )
                    if output_error or transaction_snapshot is None:
                        raise OSError(output_error or "cannot snapshot transaction outputs")
                    expected_preimages = {
                        path: source_snapshot.postimages[path]
                        for path in changed_paths
                    }
                    imported_files = {
                        path: RollbackFileSnapshot(
                            content=transaction_snapshot.files[path].content,
                            mode=transaction_snapshot.files[path].mode,
                            xattrs=transaction_snapshot.files[path].xattrs,
                            windows_dacl=source_snapshot.files[path].windows_dacl,
                            atime_ns=transaction_snapshot.files[path].atime_ns,
                            mtime_ns=transaction_snapshot.files[path].mtime_ns,
                        )
                        for path in changed_paths
                    }
                    import_snapshot = RollbackSnapshot(
                        root=source_snapshot.root,
                        root_identity=source_snapshot.root_identity,
                        files=imported_files,
                        root_guard=source_snapshot.root_guard,
                        postimages=expected_preimages,
                    )
                    journal_path = transaction_parent / f"{transaction_id}.journal.json"
                    journal_payload = {
                        "schema": 1,
                        "transaction_id": transaction_id,
                        "task_id": task_id,
                        "source_root": str(source),
                        "transaction_root": str(transaction_root),
                        "paths": changed_paths,
                        "files": {
                            path: {
                                "before": self._transaction_file_payload(source_snapshot.files[path]),
                                "after": self._transaction_file_payload(imported_files[path]),
                            }
                            for path in changed_paths
                        },
                    }
                    self._persist_transaction_journal(journal_path, journal_payload)
                    try:
                        _restore_rollback_scope(str(source), import_snapshot)
                    except Exception as import_error:
                        restored = self._recover_partial_transaction_import(
                            source, source_snapshot, transaction_snapshot, changed_paths
                        )
                        if restored:
                            journal_path.unlink(missing_ok=True)
                            result.update({
                                "success": False,
                                "transaction_status": "discarded",
                                "failure_kind": "import_failed",
                                "outcome_unknown": False,
                                "retryable": False,
                                "terminal": True,
                                "rolled_back": True,
                                "error": f"transaction output import failed; source restored: {str(import_error)[:384]}",
                            })
                            return result
                        raise OSError(f"transaction output import failed: {str(import_error)[:384]}") from import_error

                    verify_snapshot, verify_error = _snapshot_rollback_scope(
                        str(source), changed_paths
                    )
                    if verify_error or verify_snapshot is None:
                        raise OSError(verify_error or "cannot verify imported transaction outputs")
                    try:
                        for path in changed_paths:
                            if not self._transaction_file_matches(
                                verify_snapshot.files[path], transaction_snapshot.files[path]
                            ):
                                raise OSError(f"imported transaction output changed: {path}")
                    finally:
                        _close_rollback_root(verify_snapshot.root_guard)
                    journal_path.unlink()
                    try:
                        descriptor = os.open(transaction_parent, os.O_RDONLY)
                    except OSError:
                        descriptor = None
                    if descriptor is not None:
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                result.update({
                    "success": True,
                    "transaction_status": "committed",
                    "failure_kind": "",
                    "outcome_unknown": False,
                    "retryable": False,
                    "terminal": True,
                    "imported_paths": changed_paths if 'changed_paths' in locals() else [],
                })
            except Exception as exc:
                retain_transaction = True
                retain_lease = True
                result.update({
                    "success": False,
                    "transaction_status": "recovery_required",
                    "failure_kind": "destination_conflict" if "changed" in str(exc).lower() else "import_failed",
                    "outcome_unknown": True,
                    "retryable": False,
                    "terminal": True,
                    "error": str(exc)[:512],
                })
            return result
        except Exception as exc:
            result.update({
                "success": False,
                "transaction_status": "discarded",
                "failure_kind": "command_failed",
                "error": str(exc)[:512],
                "retryable": False,
                "terminal": True,
            })
            return result
        finally:
            if transaction_snapshot is not None:
                try:
                    _close_rollback_root(transaction_snapshot.root_guard)
                except OSError:
                    pass
            if source_snapshot is not None:
                try:
                    _close_rollback_root(source_snapshot.root_guard)
                except OSError:
                    pass
            if not retain_transaction:
                shutil.rmtree(transaction_root, ignore_errors=True)
            with self._transaction_roots_lock:
                self._active_transaction_roots.pop(transaction_id, None)
            if not retain_lease:
                self._transaction_leases.release(transaction_name, str(lease.get("lease_id") or ""))


    def _distill_error_with_model(self, result: dict[str, Any]) -> str:
        if not callable(self.error_distiller):
            return ""
        payload = {
            "exit_code": int(result.get("exit_code", 1) or 1),
            "summary": str(result.get("summary", ""))[:4000],
            "diagnostics": list(result.get("diagnostics", []))[:2],
        }
        try:
            distilled = self.error_distiller(payload)
        except Exception:
            return ""
        if isinstance(distilled, dict):
            distilled = distilled.get("text", distilled.get("summary", ""))
        return str(distilled or "").strip()[:300]

    def _resolve_project_command(
        self,
        alias: str,
        cwd: str,
        *,
        args: Sequence[str] = (),
    ) -> _ResolvedProjectCommand:
        """Resolve one explicit project alias without invoking a process."""
        from .project_config import (
            CommandDefinition,
            ProjectConfigError,
            resolve_project_context,
        )

        if not isinstance(alias, str) or not _PROJECT_COMMAND_ALIAS_RE.fullmatch(alias):
            raise ProjectConfigError("invalid_command_alias")
        if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
            raise ProjectConfigError("invalid_command_arguments")
        if len(args) > _MAX_PROJECT_COMMAND_ARGS or any(
            not isinstance(item, str) or len(item) > 4096 or "\x00" in item
            for item in args
        ):
            raise ProjectConfigError("invalid_command_arguments")

        context = resolve_project_context(cwd, configured_state_dir(self.config))
        command_root = Path(cwd).expanduser().resolve(strict=True)
        try:
            command_root.relative_to(context.root)
        except ValueError:
            raise ProjectConfigError("command_outside_project") from None

        if not isinstance(context.config_digest, str) or not context.config_digest:
            raise ProjectConfigError("invalid_config")
        definition = context.settings.commands.get(alias)
        if definition is None:
            raise ProjectConfigError("command_alias_not_found")

        command_env_references = dict(context.settings.env_references)
        if isinstance(definition, str):
            if args:
                raise ProjectConfigError("string_command_does_not_accept_arguments")
            command: str | CommandInvocation = definition
        elif isinstance(definition, CommandDefinition):
            command_env_references.update(definition.env_references)
            invocation = CommandInvocation(
                argv=[*definition.argv, *args],
                cwd=str(command_root),
                shell=False,
            )
            invocation_result = validate_invocation(invocation)
            if not invocation_result.get("safe"):
                raise ProjectConfigError("invalid_command_definition")
            command = invocation
        else:
            raise ProjectConfigError("invalid_command_definition")

        project_environment = dict(context.settings.env)
        if len(project_environment) + len(command_env_references) > _MAX_PROJECT_COMMAND_ENV_ENTRIES:
            raise ProjectConfigError("invalid_command_environment")
        environment: dict[str, str] = {}
        environment_size = 0
        for target_name, value in project_environment.items():
            if (
                not isinstance(target_name, str)
                or not _PROJECT_COMMAND_ENV_KEY_RE.fullmatch(target_name)
                or _is_unsafe_project_command_env_key(target_name)
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise ProjectConfigError("invalid_command_environment")
            environment_size += len(target_name.encode("utf-8")) + len(value.encode("utf-8"))
            if environment_size > _MAX_PROJECT_COMMAND_ENV_BYTES:
                raise ProjectConfigError("command_environment_too_large")
            environment[target_name] = value

        for target_name, source_name in command_env_references.items():
            if (
                not isinstance(target_name, str)
                or not _PROJECT_COMMAND_ENV_KEY_RE.fullmatch(target_name)
                or _is_unsafe_project_command_env_key(target_name)
                or not isinstance(source_name, str)
                or not _PROJECT_COMMAND_ENV_KEY_RE.fullmatch(source_name)
            ):
                raise ProjectConfigError("invalid_command_environment")
            if source_name not in os.environ:
                raise ProjectConfigError("command_environment_unavailable")
            value = os.environ[source_name]
            if not isinstance(value, str) or "\x00" in value:
                raise ProjectConfigError("invalid_command_environment")
            environment_size += len(target_name.encode("utf-8")) + len(value.encode("utf-8"))
            if environment_size > _MAX_PROJECT_COMMAND_ENV_BYTES:
                raise ProjectConfigError("command_environment_too_large")
            environment[target_name] = value

        cache_context = stable_hash(
            {
                "alias": alias,
                "config_digest": context.config_digest,
                "environment": environment,
            }
        )
        return _ResolvedProjectCommand(
            alias=alias,
            command=command,
            environment=environment,
            config_digest=context.config_digest,
            cache_context=cache_context,
        )

    def run_project_command(
        self,
        alias: str,
        cwd: str,
        tenant: str = "agent",
        *,
        args: Sequence[str] = (),
        timeout: int | None = None,
        force: bool = False,
        task_id: str = "",
        criterion: str = "",
        log_callback: Any | None = None,
        snapshot: bool = False,
        rollback_on_failure: bool = False,
        rollback_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run an explicit project command alias through normal broker policy."""
        from .project_config import ProjectConfigError

        try:
            resolved = self._resolve_project_command(alias, cwd, args=args)
        except ProjectConfigError as exc:
            return {
                "success": False,
                "error": f"project command unavailable: {exc.code}",
                "project_command_error": exc.code,
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
        except (OSError, RuntimeError, TypeError, ValueError):
            return {
                "success": False,
                "error": "project command configuration could not be resolved",
                "project_command_error": "configuration_resolution_failed",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }

        return self.run(
            resolved.command,
            cwd,
            tenant,
            timeout=timeout,
            force=force,
            task_id=task_id,
            criterion=criterion,
            log_callback=log_callback,
            snapshot=snapshot,
            rollback_on_failure=rollback_on_failure,
            rollback_paths=rollback_paths,
            _environment_overrides=resolved.environment,
            _cache_context=resolved.cache_context,
        )

    @_stable_rollback_status
    def run(
        self,
        command: str | CommandInvocation,
        cwd: str,
        tenant: str = "agent",
        *,
        timeout: int | None = None,
        force: bool = False,
        task_id: str = "",
        criterion: str = "",
        record_verification: bool = True,
        auto_fix: bool = False,
        fix_generator: Any | None = None,
        max_repair_attempts: int = 3,
        log_callback: Any | None = None,
        snapshot: bool = False,
        rollback_on_failure: bool = False,
        sandbox: str = "local",
        docker_image: str = "python:3.11-slim",
        bypass_cache: bool = False,
        paths: list[str] | None = None,
        rollback_paths: list[str] | None = None,
        _environment_overrides: Mapping[str, str] | None = None,
        _cache_context: str = "",
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "command broker disabled"}
        argv_override: list[str] | None = None
        if isinstance(command, CommandInvocation):
            invocation_result = validate_invocation(command)
            if not invocation_result.get("safe"):
                return {**invocation_result, "success": False, "preflight": True}
            argv_override = list(invocation_result["argv"])
            invocation_cwd = invocation_result.get("cwd")
            if invocation_cwd is not None:
                try:
                    if Path(invocation_cwd).resolve(strict=False) != Path(cwd).resolve(strict=False):
                        return {
                            "success": False,
                            "error": "structured invocation working directory does not match command working directory",
                            "preflight": True,
                            "terminal": True,
                            "retryable": False,
                        }
                except (OSError, TypeError, ValueError):
                    return {
                        "success": False,
                        "error": "structured invocation working directory is invalid",
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }
            command = shlex.join(argv_override)
        if not isinstance(command, str):
            return {
                "success": False,
                "error": "command must be a string or validated argv invocation",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
        if not isinstance(_cache_context, str):
            return {
                "success": False,
                "error": "project command cache context is invalid",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
        if _environment_overrides is not None:
            if not isinstance(_environment_overrides, Mapping) or len(_environment_overrides) > _MAX_PROJECT_COMMAND_ENV_ENTRIES:
                return {
                    "success": False,
                    "error": "project command environment is invalid",
                    "preflight": True,
                    "terminal": True,
                    "retryable": False,
                }
            environment_size = 0
            for name, value in _environment_overrides.items():
                if (
                    not isinstance(name, str)
                    or not _PROJECT_COMMAND_ENV_KEY_RE.fullmatch(name)
                    or name.upper() in _PROJECT_COMMAND_ENV_BLOCKED
                    or not isinstance(value, str)
                    or "\x00" in value
                ):
                    return {
                        "success": False,
                        "error": "project command environment is invalid",
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }
                environment_size += len(name.encode("utf-8")) + len(value.encode("utf-8"))
                if environment_size > _MAX_PROJECT_COMMAND_ENV_BYTES:
                    return {
                        "success": False,
                        "error": "project command environment is too large",
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }
        if rollback_on_failure and auto_fix:
            return {"success": False, "error": "rollback_on_failure is supported only for direct run actions", "rollback_unsupported_action": True, "terminal": True, "retryable": False}
        rollback_state: RollbackSnapshot | None = None
        original_command = command
        classification = self.classify(original_command)
        is_mutating = classification.get("class") == "mutating"
        if is_mutating or auto_fix or rollback_on_failure:
            worktree_error = self._require_task_worktree(task_id, cwd, original_command)
            if worktree_error:
                return {
                    "success": False,
                    "error": worktree_error,
                    "mutation_worktree_required": True,
                    "terminal": True,
                    "retryable": False,
                }
        declared_paths = paths if paths is not None else (rollback_paths if rollback_on_failure else None)
        if is_mutating and not declared_paths:
            return {"success": False, "error": "mutating command requires an explicit non-empty paths write set", "mutation_write_set_required": True, "terminal": True, "retryable": False}
        if rollback_on_failure and paths is not None and rollback_paths is not None:
            if {value.replace(chr(92), "/") for value in paths} != {value.replace(chr(92), "/") for value in rollback_paths}:
                return {"success": False, "error": "paths and rollback_paths must describe the same write set", "mutation_write_set_invalid": True, "terminal": True, "retryable": False}
        if (is_mutating or rollback_on_failure) and _environment_overrides:
            return {"success": False, "error": "mutating transaction does not accept project environment overrides", "terminal": True, "retryable": False}
        if sandbox == "docker" and not is_mutating:
            if not shutil.which("docker"):
                return {
                    "success": False,
                    "error": "docker executable not found for sandbox mode",
                    "terminal": True,
                    "retryable": False,
                }
            abs_cwd = str(Path(cwd).resolve())
            command = f'docker run --rm -v "{abs_cwd}:/workspace" -w /workspace {docker_image} {command}'
        if task_id and self.policy_engine:
            budget = self.policy_engine.get_budget(task_id)
            if budget.is_exhausted():
                return {
                    "success": False,
                    "error": f"task budget exhausted ({task_id}): max_tokens={budget.max_tokens}, max_compute_seconds={budget.max_compute_seconds}",
                    "terminal": True,
                    "retryable": False,
                    "budget_exhausted": True,
                }
        attempt_key = (
            self._attempt_key(command, cwd, cache_context=_cache_context)
            if _cache_context
            else self._attempt_key(command, cwd)
        )
        if not force and not bypass_cache and not is_mutating:
            suppressed = self.suppression_cache.get(attempt_key)
            if isinstance(suppressed, dict):
                self.suppressed += 1
                result = dict(suppressed)
                result.update({"suppression_cache_hit": True, "classification": classification})
                return self._compact(result, tenant, command)
        is_dangerous = classification.get("class") == "dangerous"
        if is_dangerous or (not classification["allowed"] and self.policy_blocking):
            with self._lock:
                self.blocked += 1
                reason = str(classification.get("reason", "policy"))[:120]
                self._blocked_by_reason[reason] = self._blocked_by_reason.get(reason, 0) + 1
            result = {
                "success": False, "error": f"command blocked: {classification['reason']}",
                "classification": classification, "policy_blocked": True, "terminal": True, "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return result
        cwd_path = Path(cwd).expanduser().resolve(strict=False)
        if not cwd_path.is_dir():
            result = {
                "success": False,
                "error": f"working directory does not exist: {cwd_path}",
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return result
        unavailable = self._unavailable_executable(command, cwd)
        if unavailable:
            result = {
                "success": False, "error": f"command executable is unavailable: {unavailable}",
                "exit_code": 127, "classification": classification, "preflight": True, "terminal": True, "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        if not Path(cwd).is_dir():
            result = {
                "success": False, "error": f"working directory does not exist: {cwd}",
                "exit_code": 1, "classification": classification, "preflight": True, "terminal": True, "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        try:
            if _cache_context:
                key, state = self._key(
                    command, cwd, classification, cache_context=_cache_context
                )
            else:
                key, state = self._key(command, cwd, classification)
        except ValueError as exc:
            result = {
                "success": False,
                "error": str(exc),
                "classification": classification,
                "preflight": True,
                "terminal": True,
                "retryable": False,
            }
            if not force and not bypass_cache and not is_mutating:
                self.suppression_cache.set(attempt_key, result)
            return self._compact(result, tenant, command)
        cacheable = bool(classification["cacheable"]) and not is_mutating
        if cacheable and not force and not bypass_cache:
            cached = self.success_cache.get(key) or self.failure_cache.get(key)
            if isinstance(cached, dict):
                stale_key = key
                invalidate_repo_state = getattr(self.repo_state, "invalidate", None)
                if callable(invalidate_repo_state):
                    invalidate_repo_state(cwd)
                try:
                    if _cache_context:
                        key, state = self._key(
                            command, cwd, classification, cache_context=_cache_context
                        )
                    else:
                        key, state = self._key(command, cwd, classification)
                except ValueError:
                    cached = None
                else:
                    if key != stale_key:
                        cached = self.success_cache.get(key) or self.failure_cache.get(key)
            if isinstance(cached, dict):
                self.hits += 1
                result = dict(cached)
                result.update({"cache_hit": True, "coalesced": False, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
                self._record_command_verification(
                    result,
                    tenant=tenant,
                    task_id=task_id,
                    criterion=criterion or f"command:{self._safe_label(command)}",
                    command=command,
                    command_id=f"cache_{uuid.uuid4().hex}",
                    command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    repository_revision=str(state.get("fingerprint", "")),
                    duration_ms=float(result.get("duration_ms", 0) or 0),
                    cached=True,
                )
                return self._compact(result, tenant, command)

        singleflight = not is_mutating and not bypass_cache
        event: threading.Event | None = None
        owner = False
        if singleflight:
            refreshed_for_inflight = False
            while True:
                with self._lock:
                    event = self._inflight.get(key)
                    if event is None:
                        event = threading.Event(); self._inflight[key] = event; owner = True
                        break
                    if refreshed_for_inflight:
                        owner = False; self.coalesced += 1
                        break
                invalidate_repo_state = getattr(self.repo_state, "invalidate", None)
                if not callable(invalidate_repo_state):
                    refreshed_for_inflight = True
                    continue
                invalidate_repo_state(cwd)
                try:
                    if _cache_context:
                        key, state = self._key(command, cwd, classification, cache_context=_cache_context)
                    else:
                        key, state = self._key(command, cwd, classification)
                except ValueError as exc:
                    return self._compact({
                        "success": False,
                        "error": str(exc),
                        "classification": classification,
                        "preflight": True,
                        "terminal": True,
                        "retryable": False,
                    }, tenant, command)
                refreshed_for_inflight = True
        if singleflight and not owner:
            # A second agent should benefit from single-flight without being trapped
            # behind a very long build/test command. The owner keeps running and will
            # populate the cache; the waiter gets a bounded in-progress response.
            wait_budget = min(max(1.0, float(timeout or self.timeout) + 5.0), self.coalesce_wait_seconds)
            if not event.wait(wait_budget):
                with self._lock:
                    self.coalesced_timeouts += 1
                    active = self._public_active(dict(self._active_commands.get(key, {})))
                return {
                    "success": False, "in_progress": True, "retryable": True,
                    "error": "identical command is still running in another agent; do not start a duplicate",
                    "classification": classification, "repo_state": state, "active": active,
                }
            with self._lock:
                last_result = self._last.get(key)
            if last_result is None:
                return {
                    "success": False,
                    "error": "command ended without a definitive cacheable result",
                    "outcome_unknown": True,
                    "retryable": True,
                    "cache_hit": False,
                    "coalesced": False,
                    "classification": classification,
                    "repo_state": state,
                }
            result = dict(last_result)
            result.update({"cache_hit": True, "coalesced": True, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
            return self._compact(result, tenant, command)

        # Acquire rollback handles only after every preflight and early-return path.
        # Otherwise a rejected task can retain the root directory handle on Windows.
        if rollback_on_failure and not is_mutating:
            rollback_state, scope_error = _snapshot_rollback_scope(cwd, rollback_paths)
            if scope_error:
                key = "rollback_scope_required" if scope_error == "rollback paths are required" else "rollback_scope_invalid"
                return {
                    "success": False,
                    "error": scope_error,
                    key: True,
                    "terminal": True,
                    "retryable": False,
                }

        self.misses += 1
        started_wall = time.time()
        cancel_event = threading.Event()
        execution_id = uuid.uuid4().hex
        execution_key = key if singleflight else f"mutation:{execution_id}"
        tenant_identity = self._tenant_identity(tenant)
        with self._lock:
            self._active_commands[execution_key] = {
                "command": self._safe_label(command), "cwd": Path(cwd).name or str(Path(cwd)),
                "class": str(classification.get("class", "")),
                "tenant_identity": tenant_identity, "started_at": started_wall,
                "timeout_seconds": int(timeout or self.timeout), "execution_id": execution_id,
            }
            self._cancel_events[execution_key] = cancel_event
            self._active_cancel_keys[execution_key] = (self._cancel_key(command, cwd), tenant_identity)
        git_snapshot = None
        if snapshot:
            try:
                cp_rev = subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=cwd, capture_output=True, text=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if cp_rev.returncode == 0:
                    cp_untracked = subprocess.run(
                        ["git", "ls-files", "--others", "--exclude-standard"],
                        cwd=cwd, capture_output=True, text=True, check=False,
                        timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                    )
                    git_snapshot = {
                        "cwd": cwd,
                        "untracked": set(cp_untracked.stdout.splitlines()),
                    }
            except Exception:
                pass
        try:
            if is_mutating or rollback_on_failure:
                result = self._run_private_transaction(
                    command, cwd, tenant,
                    task_id=task_id,
                    paths=list(declared_paths or []),
                    timeout=int(timeout or self.timeout),
                    docker_image=docker_image,
                    cancel_event=cancel_event,
                    log_callback=log_callback,
                    command_key=key,
                    attempt_key=attempt_key,
                )
            else:
                result = self._execute(
                    command,
                    cwd,
                    int(timeout or self.timeout),
                    cancel_event,
                    log_callback=log_callback,
                    argv_override=argv_override,
                    environment_overrides=_environment_overrides,
                )
            # CPython compileall reports missing targets as a diagnostic while
            # still exiting 0. A green exit code must not hide that no target
            # was compiled.
            combined_output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
            if result.get("success") and "compileall" in command.lower() and re.search(r"can't\s+list\s+['\"]?[^\r\n]+", combined_output, re.I):
                result.update({
                    "success": False,
                    "exit_code": 1,
                    "error": "compileall reported an unavailable target",
                    "terminal": True,
                    "retryable": False,
                    "target_missing": True,
                })
            if rollback_state is not None and rollback_on_failure and not result.get("success"):
                try:
                    _capture_rollback_postimages(rollback_state)
                    _restore_rollback_scope(cwd, rollback_state)
                    result["rolled_back"] = True
                except Exception as rb_exc:
                    self._mark_rollback_outcome_unknown(
                        result, command_key=key, attempt_key=attempt_key, error=rb_exc,
                        rollback_paths=rollback_paths,
                    )
            elif snapshot and git_snapshot:
                result["snapshot_taken"] = True
            result["diagnostics"] = self._extract_diagnostics(result)
            if not result.get("success") and not result.get("cancelled"):
                result["error_distillation"] = self._distill_error(result)
                result["error_distillation_source"] = "deterministic"
                if self._needs_model_error_distillation(result):
                    model_distillation = self._distill_error_with_model(result)
                    if model_distillation:
                        result["error_distillation"] = model_distillation
                        result["error_distillation_source"] = "local_model"
            diag_paths = [d["path"] for d in result.get("diagnostics", []) if d.get("path")]
            if (
                not result.get("success")
                and (not result.get("cancelled") or result.get("outcome_unknown"))
                and self.incident_store is not None
            ):
                try:
                    from .agent_incidents import ToolOutcome
                    inc = self.incident_store.capture(ToolOutcome(
                        tool_name="command",
                        command=command,
                        error=(
                            f"rollback failed; filesystem outcome unknown: {result.get('rollback_error', '')}"
                            if result.get("outcome_unknown")
                            else str(result.get("error") or result.get("stderr") or ("exit code " + str(result.get("exit_code", 1))))
                        ),
                        exit_code=int(result.get("exit_code", 1)),
                        state_revision=str(state.get("fingerprint", "")),
                        repository_root=cwd,
                        timed_out=bool(result.get("timed_out")),
                        cancelled=bool(result.get("cancelled")),
                        metadata={"outcome_unknown": True, "rollback_error": result.get("rollback_error", "")} if result.get("outcome_unknown") else {},
                        affected_paths=tuple(set(diag_paths)),
                    ))
                    if inc and result.get("outcome_unknown"):
                        result["incident_id"] = inc.incident_id
                        result["incident_recorded"] = True
                    if inc and (inc.root_cause or inc.verified_fix):
                        result["remediation"] = {
                            "incident_id": inc.incident_id,
                            "root_cause": inc.root_cause,
                            "verified_fix": inc.verified_fix,
                            "confidence": inc.confidence,
                            "attempts": inc.attempts,
                        }
                except Exception:
                    pass

            if self.incident_store is not None:
                try:
                    target_paths = set(diag_paths)
                    for cp in state.get("changed_paths", []):
                        target_paths.add(str(cp))
                    # Historical incidents are actionable only when the current
                    # command failed; successful runs must not emit stale alarms.
                    if target_paths and not result.get("success") and not result.get("cancelled"):
                        regs = self.incident_store.find_regressions(
                            list(target_paths),
                            state_revision=str(state.get("fingerprint") or ""),
                        )
                        if regs:
                            result["regression_warnings"] = regs
                    search_query = command
                    if not result.get("success") and result.get("error_distillation"):
                        search_query = f"{command} {result['error_distillation']}"
                    pitfalls = self.incident_store.find_negative_knowledge(query=search_query, limit=3)
                    if pitfalls:
                        result["known_pitfalls"] = [
                            {"incident_id": p.get("incident_id"), "root_cause": p.get("root_cause"), "verified_fix": p.get("verified_fix")}
                            for p in pitfalls if p.get("root_cause") or p.get("verified_fix")
                        ]
                except Exception:
                    pass

            raw = dict(result)
            uncertain_outcome = any(
                bool(result.get(flag))
                for flag in ("timed_out", "cancelled", "aborted_interactive", "outcome_unknown", "in_progress")
            )
            if cacheable and not bypass_cache and not uncertain_outcome:
                (self.success_cache if result.get("success") else self.failure_cache).set(key, raw)
            if not result.get("outcome_unknown"):
                self._record_command_verification(
                    result,
                    tenant=tenant,
                    task_id=task_id,
                    criterion=criterion or f"command:{self._safe_label(command)}",
                    command=command,
                    command_id=execution_id,
                    command_digest=hashlib.sha256(command.encode("utf-8")).hexdigest(),
                    repository_revision=str(state.get("fingerprint", "")),
                    duration_ms=float(result.get("duration_ms", 0) or 0),
                )
            if not force and not bypass_cache and not is_mutating and not uncertain_outcome and self._non_retryable_failure(raw):
                raw.update({"terminal": True, "retryable": False})
                self.suppression_cache.set(attempt_key, raw)
            if singleflight:
                with self._lock:
                    if len(self._last) > 128:
                        old_keys = list(self._last.keys())[:64]
                        for k in old_keys:
                            self._last.pop(k, None)
                    if uncertain_outcome:
                        self._last.pop(key, None)
                    else:
                        self._last[key] = raw
            result.update({"cache_hit": False, "coalesced": False, "classification": classification, "repo_state": state, "repository_revision": str(state.get("fingerprint", ""))})
        except subprocess.TimeoutExpired:
            timeout_result = {"success": False, "error": "command timed out", "timed_out": True, "classification": classification, "cache_hit": False}
            if rollback_state is not None:
                try:
                    _restore_rollback_scope(cwd, rollback_state)
                    timeout_result["rolled_back"] = True
                except Exception as rb_exc:
                    self._mark_rollback_outcome_unknown(
                        timeout_result, command_key=key, attempt_key=attempt_key, error=rb_exc,
                    )
                    self._capture_rollback_unknown_incident(
                        timeout_result, command=command,
                        repository_revision=str(state.get("fingerprint", "")),
                    )
            return timeout_result
        finally:
            if rollback_state is not None:
                try:
                    _close_rollback_root(rollback_state.root_guard)
                except OSError:
                    pass
            with self._lock:
                if singleflight:
                    self._inflight.pop(key, None)
                self._active_commands.pop(execution_key, None)
                self._cancel_events.pop(execution_key, None)
                self._active_cancel_keys.pop(execution_key, None)
                if event is not None:
                    event.set()

        if task_id and self.policy_engine:
            try:
                from .agent_policy import BudgetCost
                elapsed_s = float(result.get("duration_ms", 0) or 0) / 1000.0
                self.policy_engine.consume(task_id, BudgetCost(compute_seconds=elapsed_s, external_calls=1))
            except Exception:
                pass

        compacted = self._compact(result, tenant, command)
        compacted["execution_id"] = execution_id
        if auto_fix and not compacted.get("success") and not compacted.get("cancelled"):
            repaired = self.repair_loop(
                command, cwd, tenant,
                max_attempts=max_repair_attempts,
                task_id=task_id, criterion=criterion,
                timeout=timeout,
                fix_generator=fix_generator,
                initial_result=compacted,
            )
            repaired["execution_id"] = execution_id
            return repaired
        return compacted

    @_stable_rollback_status
    def patch_and_verify(
        self,
        patch: str,
        cwd: str | Path,
        tenant: str,
        *,
        command: str = "",
        criterion: str = "",
        task_id: str = "",
        record_verification: bool = True,
        timeout: int | None = None,
        auto_rollback: bool = True,
        log_callback: Any | None = None,
        docker_image: str = "python:3.11-slim",
        _transaction_context: str = "",
    ) -> dict[str, Any]:
        """Apply a unified diff, run verification tests, and auto-rollback on failure."""
        cwd_path = Path(cwd).resolve(strict=True) if _transaction_context else Path(canonical_root(cwd))
        if not patch or not patch.strip():
            return {"success": False, "error": "patch text is empty", "terminal": True, "retryable": False}
        if _transaction_context:
            transaction_root = self._transaction_root_for_context(_transaction_context).resolve(strict=True)
            if cwd_path != transaction_root:
                return {"success": False, "error": "private transaction cwd does not match transaction context", "terminal": True, "retryable": False}
        else:
            worktree_error = self._require_task_worktree(task_id, cwd_path)
            if worktree_error:
                return {
                    "success": False,
                    "error": worktree_error,
                    "mutation_worktree_required": True,
                    "terminal": True,
                    "retryable": False,
                }
        patch_bytes = patch.encode("utf-8")
        try:
            write_paths = _patch_write_paths(cwd_path, patch_bytes, self.git_snapshot_timeout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch write set rejected: {str(exc)[:512]}",
                "terminal": True,
                "retryable": False,
            }
        if not _transaction_context:
            return self._run_private_transaction(
                command=command or criterion or "patch verification",
                source_root=cwd_path,
                tenant=tenant,
                task_id=task_id,
                paths=write_paths,
                timeout=int(timeout or self.timeout),
                docker_image=docker_image,
                log_callback=log_callback,
                operation=lambda transaction_root, transaction_id: self.patch_and_verify(
                    patch, transaction_root, tenant,
                    command=command, criterion=criterion, task_id=task_id,
                    record_verification=record_verification, timeout=timeout,
                    auto_rollback=auto_rollback, log_callback=log_callback,
                    docker_image=docker_image, _transaction_context=transaction_id,
                ),
            )

        def _mark_patch_rollback_unknown(
            failure: dict[str, Any],
            rollback_error: str,
            *,
            incident_command: str,
            repository_revision: str = "",
        ) -> None:
            failure.update({
                "rollback_error": rollback_error[:512],
                "rollback_paths": list(write_paths),
                "outcome_unknown": True,
                "fail_closed": True,
                "incident_required": True,
                "cache_hit": False,
                "coalesced": False,
                "retryable": False,
                "terminal": True,
            })
            cache_invalidation_errors: list[str] = []
            try:
                classification = self.classify(incident_command)
                command_key, _state = self._key(incident_command, str(cwd_path), classification)
                attempt_key = self._attempt_key(incident_command, str(cwd_path))
                for cache, key in (
                    (self.success_cache, command_key),
                    (self.failure_cache, command_key),
                    (self.suppression_cache, attempt_key),
                ):
                    try:
                        if cache.delete(key) is False:
                            cache_invalidation_errors.append("cache delete reported failure")
                    except Exception as cache_exc:
                        cache_invalidation_errors.append(str(cache_exc)[:160])
                with self._lock:
                    self._last.pop(command_key, None)
            except Exception as cache_exc:
                cache_invalidation_errors.append(str(cache_exc)[:160])
            if cache_invalidation_errors:
                failure["cache_invalidation_failed"] = True
                failure["cache_invalidation_errors"] = cache_invalidation_errors
            self._capture_rollback_unknown_incident(
                failure,
                command=incident_command,
                repository_revision=repository_revision,
            )

        # 2. Check if patch applies cleanly
        check_proc = subprocess.run(
            ["git", "apply", "--check", "--whitespace=nowarn"],
            input=patch_bytes,
            cwd=str(cwd_path), capture_output=True, check=False,
            timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
        )
        if check_proc.returncode != 0:
            err_msg = check_proc.stderr.decode("utf-8", errors="replace")
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch check failed: {err_msg.strip()}",
                "terminal": True,
                "retryable": False,
            }

        # 3. Apply patch
        try:
            apply_proc = subprocess.run(
                ["git", "apply", "--whitespace=nowarn"],
                input=patch_bytes,
                cwd=str(cwd_path), capture_output=True, check=False,
                timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
            )
        except subprocess.TimeoutExpired as exc:
            failure = {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": "Patch application timed out; filesystem outcome is unknown",
            }
            _mark_patch_rollback_unknown(
                failure,
                str(exc),
                incident_command=command or criterion or "patch apply",
            )
            return failure
        if apply_proc.returncode != 0:
            err_msg = apply_proc.stderr.decode("utf-8", errors="replace")
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch apply failed: {err_msg.strip()}",
                "terminal": True,
                "retryable": False,
            }

        # 4. Helper rollback closure
        def _do_rollback() -> tuple[bool, str | None]:
            try:
                _patch_write_paths(cwd_path, patch_bytes, self.git_snapshot_timeout)
                reverse_check = subprocess.run(
                    ["git", "apply", "--reverse", "--check", "--whitespace=nowarn"],
                    input=patch_bytes,
                    cwd=str(cwd_path), capture_output=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if reverse_check.returncode != 0:
                    forward_check = subprocess.run(
                        ["git", "apply", "--check", "--whitespace=nowarn"],
                        input=patch_bytes,
                        cwd=str(cwd_path), capture_output=True, check=False,
                        timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                    )
                    if forward_check.returncode == 0:
                        return False, "rollback patch removal could not be confirmed after concurrent changes"
                    detail = reverse_check.stderr.decode("utf-8", errors="replace").strip()
                    return False, detail or "rollback patch conflicts with concurrent changes"
                reverse_apply = subprocess.run(
                    ["git", "apply", "--reverse", "--whitespace=nowarn"],
                    input=patch_bytes,
                    cwd=str(cwd_path), capture_output=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if reverse_apply.returncode == 0:
                    return True, None
                detail = reverse_apply.stderr.decode("utf-8", errors="replace").strip()
                return False, detail or "rollback patch could not be applied"
            except Exception as exc:
                return False, f"{type(exc).__name__}: {exc}"

        # 5. Syntax pre-flight check on modified Python files
        modified_py_files = [
            cwd_path.joinpath(*path.split("/"))
            for path in write_paths
            if path.endswith(".py")
        ]

        for py_file in modified_py_files:
            if py_file.is_file():
                try:
                    compile(py_file.read_bytes(), str(py_file), "exec")
                except SyntaxError as syn_err:
                    rolled_back = False
                    rollback_error = None
                    if auto_rollback:
                        rolled_back, rollback_error = _do_rollback()
                    failure = {
                        "success": False,
                        "applied": False,
                        "rolled_back": rolled_back,
                        "error": f"Syntax error in modified file {py_file.name}: {syn_err.msg}",
                        "diagnostics": [{"path": str(py_file.relative_to(cwd_path)), "message": syn_err.msg}],
                    }
                    if rollback_error:
                        _mark_patch_rollback_unknown(
                            failure,
                            rollback_error,
                            incident_command=command or criterion or "patch validation",
                        )
                    return failure

        # 6. Determine test command
        test_cmd = command.strip() or criterion.strip()
        auto_detected_tests: list[str] = []
        if test_cmd.lower() == "auto":
            all_modified: list[str] = []
            all_modified.extend(write_paths)

            try:
                from .repo_tools import RepositoryTools
                from .deterministic import DeterministicEngine
                rt = RepositoryTools(self.config)
                det = DeterministicEngine(self.config, rt)
                aff = det.affected_tests(str(cwd_path), changed_paths=all_modified)
                auto_detected_tests = aff.get("test_files", []) if isinstance(aff, dict) else []
            except Exception:
                auto_detected_tests = []

            if auto_detected_tests:
                if any(tf.endswith(".py") for tf in auto_detected_tests):
                    test_cmd = f"python -m pytest {' '.join(auto_detected_tests[:5])} -q"
                elif any(tf.endswith((".ts", ".js")) for tf in auto_detected_tests):
                    test_cmd = f"npm test -- {' '.join(auto_detected_tests[:5])}"
                elif any(tf.endswith(".cs") for tf in auto_detected_tests):
                    test_cmd = "dotnet test"
                else:
                    test_cmd = f"python -m pytest {' '.join(auto_detected_tests[:5])} -q"
            else:
                test_cmd = ""

        if not test_cmd:
            return {
                "success": True,
                "applied": True,
                "tests_passed": True,
                "affected_tests_run": [],
                "message": "Patch applied cleanly and passed syntax verification (no tests required or specified)",
            }

        # 7. Run validation command
        run_res = self.run(
            test_cmd, str(cwd_path), tenant,
            timeout=timeout, force=True, task_id=task_id, criterion=criterion,
            paths=write_paths,
            record_verification=record_verification,
            rollback_on_failure=auto_rollback, rollback_paths=write_paths,
            log_callback=log_callback,
            docker_image=docker_image,
            _transaction_context=_transaction_context,
        )

        run_outcome_unknown = bool(
            run_res.get("outcome_unknown") or run_res.get("cleanup_unconfirmed")
        )
        if run_res.get("success") and not run_outcome_unknown:
            rcpt_data = run_res.get("verification_receipt")
            if (
                record_verification
                and not rcpt_data
                and task_id
                and self.verification_store is not None
            ):
                try:
                    import uuid
                    from .agent_verification import VerificationReceipt
                    rcpt = VerificationReceipt.create(
                        task_id=task_id,
                        criterion=criterion or f"patch:{self._safe_label(test_cmd)}",
                        passed=True,
                        command_id=test_cmd,
                        evidence_id=str(run_res.get("artifact_id") or ""),
                        repository_revision=str(run_res.get("repository_revision") or ""),
                        details={"exit_code": 0, "duration_ms": run_res.get("duration_ms", 0)},
                    )
                    self.verification_store.record(rcpt)
                    rcpt_data = rcpt.to_dict()
                except Exception:
                    pass

            return {
                "success": True,
                "applied": True,
                "tests_passed": True,
                "command": test_cmd,
                "affected_tests_run": auto_detected_tests,
                "duration_ms": run_res.get("duration_ms"),
                "verification_receipt": rcpt_data,
                "message": "Patch applied and verified successfully",
            }
        else:
            rolled_back = False
            rollback_error = None
            if auto_rollback and not run_res.get("cleanup_unconfirmed"):
                rolled_back, rollback_error = _do_rollback()
            failure = {
                "success": False,
                "applied": False,
                "rolled_back": rolled_back,
                "error": (
                    "Validation outcome is unknown after applying patch"
                    if run_outcome_unknown
                    else "Validation command failed after applying patch"
                ),
                "command": test_cmd,
                "affected_tests_run": auto_detected_tests,
                "exit_code": run_res.get("exit_code"),
                "stdout": run_res.get("stdout"),
                "stderr": run_res.get("stderr"),
                "diagnostics": run_res.get("diagnostics", []),
                "remediation": run_res.get("remediation"),
            }
            if rollback_error or run_outcome_unknown:
                _mark_patch_rollback_unknown(
                    failure,
                    rollback_error
                    or str(run_res.get("rollback_error") or "validation outcome is unknown"),
                    incident_command=test_cmd,
                    repository_revision=str(run_res.get("repository_revision") or ""),
                )
            return failure

    def preflight(
        self,
        cwd: str | Path,
        tenant: str = "default",
        *,
        paths: list[str] | None = None,
        timeout: int = 10,
    ) -> dict[str, Any]:
        """Perform fast syntax and typecheck pre-flight on modified or specified files."""
        cwd_path = Path(canonical_root(cwd))
        if not cwd_path.is_dir():
            return {"success": False, "error": "Working directory does not exist"}

        target_files = [p.replace("\\", "/").strip() for p in (paths or []) if p]
        if not target_files:
            cp = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(cwd_path), capture_output=True, text=True, check=False,
                timeout=5, **hidden_run_kwargs()
            )
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        target_files.append(parts[1].replace("\\", "/").strip())

        if not target_files:
            return {
                "success": True,
                "clean": True,
                "checker": "none",
                "message": "No modified files detected for pre-flight check",
                "errors": [],
            }

        py_files = [f for f in target_files if f.endswith(".py") and (cwd_path / f).is_file()]
        ts_files = [f for f in target_files if f.endswith((".ts", ".tsx", ".js", ".jsx")) and (cwd_path / f).is_file()]

        errors: list[dict[str, Any]] = []
        checker = "none"

        if py_files:
            checker = "py_compile"
            for pf in py_files:
                p_path = cwd_path / pf
                try:
                    compile(p_path.read_bytes(), str(p_path), "exec")
                except SyntaxError as err:
                    errors.append({
                        "file": pf,
                        "line": err.lineno or 1,
                        "message": str(err.msg),
                        "level": "syntax_error",
                    })

        if ts_files and not errors and (cwd_path / "tsconfig.json").is_file():
            checker = "tsc"
            try:
                cp_tsc = subprocess.run(
                    ["npx", "tsc", "--noEmit", "--pretty", "false"],
                    cwd=str(cwd_path), capture_output=True, text=True, check=False,
                    timeout=timeout, **hidden_run_kwargs()
                )
                if cp_tsc.returncode != 0:
                    for line in cp_tsc.stdout.splitlines():
                        if ": error TS" in line:
                            parts = line.split(":", 3)
                            if len(parts) >= 4:
                                errors.append({
                                    "file": parts[0].strip(),
                                    "line": int(parts[1].strip() or 1),
                                    "col": int(parts[2].strip() or 1),
                                    "message": parts[3].strip(),
                                    "level": "type_error",
                                })
            except Exception:
                pass

        return {
            "success": True,
            "clean": len(errors) == 0,
            "checker": checker,
            "target_files": target_files[:10],
            "errors_count": len(errors),
            "errors": errors[:5],
            "message": "Pre-flight clean" if not errors else f"Found {len(errors)} pre-flight issue(s)",
        }

    def repair_loop(
        self,
        command: str,
        cwd: str | Path,
        tenant: str,
        *,
        max_attempts: int = 3,
        task_id: str = "",
        criterion: str = "",
        timeout: int | None = None,
        fix_generator: Any | None = None,
        initial_result: dict[str, Any] | None = None,
        log_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Execute autonomous self-healing test loop on command failure.

        Synthesizes candidate diffs/patches, applies them with in-memory file backups,
        re-tests, and if successful, mints a VerificationReceipt and keeps the fix.
        If all attempts fail, cleanly rolls back all modified files to pristine state.
        """
        cwd_path = Path(canonical_root(cwd))
        initial = initial_result or self.run(
            command, str(cwd_path), tenant, timeout=timeout, force=True,
            task_id=task_id, criterion=criterion, auto_fix=False, log_callback=log_callback,
        )
        if initial.get("success"):
            return {
                "success": True,
                "repaired": False,
                "attempts": 0,
                "result": initial,
                "message": "command passed without repair",
            }

        classification = self.classify(command)
        uncertain = bool(initial.get("outcome_unknown") or initial.get("timed_out") or initial.get("in_progress"))
        if uncertain or classification.get("class") in {"mutating", "dangerous"}:
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": bool(uncertain or classification.get("class") == "mutating"),
                "attempts": 0,
                "result": initial,
                "message": "repair skipped because command outcome or side effects are unsafe to replay",
            }

        original_files: dict[Path, str | None] = {}
        attempt_history: list[dict[str, Any]] = []
        last_result = initial
        generated_patches: dict[str, str] | None = None
        generator_invoked = False

        try:
            for attempt in range(1, max(1, max_attempts) + 1):
                patches: dict[str, str] = {}
                if callable(fix_generator):
                    # A repair loop may retry applying the same bounded candidate,
                    # but it must never amplify one failed command into repeated
                    # local-model inference calls or send subsequent raw outputs.
                    if not generator_invoked:
                        generator_invoked = True
                        try:
                            gen_res = fix_generator(command, str(cwd_path), last_result)
                            if isinstance(gen_res, dict):
                                generated_patches = {str(k): str(v) for k, v in gen_res.items()}
                        except Exception as exc:
                            attempt_history.append({"attempt": attempt, "error": f"fix generator error: {exc}"})
                            continue
                    patches = dict(generated_patches or {})
                elif self.incident_store is not None:
                    rem = last_result.get("remediation") or {}
                    fix = rem.get("verified_fix")
                    if isinstance(fix, dict):
                        patches = {str(k): str(v) for k, v in fix.items()}

                if not patches:
                    attempt_history.append({"attempt": attempt, "error": "no candidate patches synthesized"})
                    continue

                applied_paths: list[Path] = []
                for rel_path, new_content in patches.items():
                    target = (cwd_path / rel_path).resolve()
                    try:
                        target.relative_to(cwd_path)
                    except ValueError:
                        try:
                            target_canon = Path(canonical_root(target))
                            target_canon.relative_to(cwd_path)
                            target = target_canon
                        except ValueError:
                            continue
                    if target not in original_files:
                        original_files[target] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(new_content, encoding="utf-8")
                    if target.suffix.lower() in {".py", ".pyw"}:
                        pycache = target.parent / "__pycache__"
                        if pycache.is_dir():
                            for pyc in pycache.glob(f"{target.stem}*.pyc"):
                                try:
                                    pyc.unlink(missing_ok=True)
                                except Exception:
                                    pass
                    applied_paths.append(target)

                re_result = self.run(command, str(cwd_path), tenant, timeout=timeout, force=True, auto_fix=False, log_callback=log_callback)
                last_result = re_result
                attempt_history.append({
                    "attempt": attempt,
                    "applied_files": [str(p.relative_to(cwd_path)) for p in applied_paths],
                    "success": bool(re_result.get("success")),
                    "re_stderr": re_result.get("stderr"),
                    "re_exit_code": re_result.get("exit_code"),
                })

                if re_result.get("success"):
                    rcpt_dict = None
                    if task_id and self.verification_store is not None:
                        try:
                            from .agent_verification import VerificationReceipt
                            criterion_text = criterion or f"repair:{self._safe_label(command)}"
                            evidence_id = str(re_result.get("artifact_id") or "")
                            if not evidence_id:
                                evidence_id = self.artifacts.put_json(
                                    {
                                        "schema": "local-ai-command-validation/v1",
                                        "task_id": task_id,
                                        "criterion": criterion_text,
                                        "command_label": self._safe_label(command),
                                        "exit_code": int(re_result.get("exit_code", 0) or 0),
                                        "duration_ms": re_result.get("duration_ms"),
                                        "repository_revision": str(
                                            re_result.get("repository_revision")
                                            or re_result.get("repo_state", {}).get("fingerprint", "")
                                        ),
                                        "attempt": attempt,
                                        "repaired_paths": [
                                            str(p.relative_to(cwd_path)) for p in applied_paths
                                        ],
                                    },
                                    tenant,
                                    "command_validation",
                                )
                                re_result["artifact_id"] = evidence_id
                            rcpt = VerificationReceipt.create(
                                task_id=task_id,
                                criterion=criterion_text,
                                passed=True,
                                command_id=command,
                                evidence_id=evidence_id,
                                repository_revision=str(re_result.get("repository_revision") or re_result.get("repo_state", {}).get("fingerprint", "")),
                                details={
                                    "exit_code": 0,
                                    "attempts": attempt,
                                    "repaired_paths": [str(p.relative_to(cwd_path)) for p in applied_paths],
                                },
                            )
                            self.verification_store.record(rcpt)
                            rcpt_dict = rcpt.to_dict()
                        except Exception:
                            pass

                    if self.incident_store is not None:
                        try:
                            rem = initial.get("remediation") or {}
                            inc_id = rem.get("incident_id")
                            if inc_id:
                                self.incident_store.record_decision(
                                    inc_id,
                                    action="apply_verified_fix",
                                    verified_fix=json_dumps([str(p.relative_to(cwd_path)) for p in applied_paths]),
                                    confidence=1.0,
                                )
                        except Exception:
                            pass

                    original_files.clear()
                    return {
                        "success": True,
                        "repaired": True,
                        "attempts": attempt,
                        "patches_applied": [str(p.relative_to(cwd_path)) for p in applied_paths],
                        "verification_receipt": rcpt_dict,
                        "result": re_result,
                    }
                else:
                    for target, orig_content in list(original_files.items()):
                        if orig_content is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.write_text(orig_content, encoding="utf-8")
                        if target.suffix.lower() in {".py", ".pyw"}:
                            pycache = target.parent / "__pycache__"
                            if pycache.is_dir():
                                for pyc in pycache.glob(f"{target.stem}*.pyc"):
                                    try:
                                        pyc.unlink(missing_ok=True)
                                    except Exception:
                                        pass
                    original_files.clear()

        finally:
            for target, orig_content in original_files.items():
                try:
                    if orig_content is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.write_text(orig_content, encoding="utf-8")
                except Exception:
                    pass

        return {
            "success": False,
            "repaired": False,
            "attempts": len(attempt_history),
            "history": attempt_history,
            "original_result": initial,
            "error": "Self-healing repair loop exhausted without passing command.",
        }

    def format(
        self,
        root: str,
        paths: list[str] | None = None,
        tenant: str = "agent",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Automatically detect local code formatters and format paths or repository."""
        resolved_root = Path(canonical_root(root))
        if not resolved_root.is_dir():
            return {"success": False, "error": f"Directory not found: {root}"}

        target_str = " ".join(f'"{p}"' for p in paths) if paths else "."
        cmd = None
        formatter_name = None

        if (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt")):
            if shutil.which("ruff"):
                cmd = f"ruff format {target_str}"
                formatter_name = "ruff"
            elif shutil.which("black"):
                cmd = f"black {target_str}"
                formatter_name = "black"
        elif (resolved_root / "package.json").exists():
            if shutil.which("prettier"):
                cmd = f"prettier --write {target_str}"
                formatter_name = "prettier"
        elif (resolved_root / "Cargo.toml").exists():
            if shutil.which("cargo"):
                cmd = "cargo fmt"
                formatter_name = "cargo fmt"
        elif (resolved_root / "go.mod").exists():
            if shutil.which("gofmt"):
                cmd = f"gofmt -w {target_str}"
                formatter_name = "gofmt"
        elif any((resolved_root / f).is_file() for f in os.listdir(str(resolved_root)) if f.endswith((".sln", ".csproj"))):
            if shutil.which("dotnet"):
                cmd = "dotnet format"
                formatter_name = "dotnet format"

        if not cmd:
            if shutil.which("ruff"):
                cmd = f"ruff format {target_str}"
                formatter_name = "ruff"
            elif shutil.which("black"):
                cmd = f"black {target_str}"
                formatter_name = "black"

        if not cmd:
            return {"success": False, "error": "No supported code formatter found in PATH (tried ruff, black, prettier, cargo, gofmt, dotnet)"}

        res = self.run(cmd, str(resolved_root), tenant=tenant, timeout=timeout or 60, force=True)
        res["formatter"] = formatter_name
        return res

    def lint_fix(
        self,
        root: str,
        command: str | None = None,
        paths: list[str] | None = None,
        tenant: str = "agent",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Automatically run project linters in auto-fix mode to resolve style/lint issues."""
        resolved_root = Path(root).expanduser().resolve(strict=False)
        if not resolved_root.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root}"}

        target_str = " ".join(f'"{p}"' for p in paths) if paths else "."
        cmd = command
        linter_name = "custom"

        if not cmd:
            if (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt")):
                if shutil.which("ruff"):
                    cmd = f"ruff check --fix {target_str}"
                    linter_name = "ruff"
                elif shutil.which("autopep8"):
                    cmd = f"autopep8 --in-place --aggressive {target_str}"
                    linter_name = "autopep8"
            elif (resolved_root / "package.json").exists():
                if shutil.which("eslint"):
                    cmd = f"eslint --fix {target_str}"
                    linter_name = "eslint"
                elif shutil.which("npm"):
                    cmd = "npm run lint -- --fix"
                    linter_name = "npm lint"
            elif (resolved_root / "Cargo.toml").exists():
                if shutil.which("cargo"):
                    cmd = "cargo fix --allow-no-vcs"
                    linter_name = "cargo fix"
            elif (resolved_root / "go.mod").exists():
                if shutil.which("golangci-lint"):
                    cmd = f"golangci-lint run --fix {target_str}"
                    linter_name = "golangci-lint"
                elif shutil.which("gofmt"):
                    cmd = f"gofmt -w {target_str}"
                    linter_name = "gofmt"

        if not cmd:
            if shutil.which("ruff"):
                cmd = f"ruff check --fix {target_str}"
                linter_name = "ruff"

        if not cmd:
            return {"success": False, "error": "No supported linter with auto-fix found in PATH (tried ruff, eslint, cargo, golangci-lint)"}

        res = self.run(cmd, str(resolved_root), tenant=tenant, timeout=timeout or 120, force=True)
        res["linter"] = linter_name
        return res

    def spawn_daemon(
        self,
        command: str | Sequence[str],
        cwd: str,
        name: str = "",
        env: dict[str, str] | None = None,
        *,
        task_id: str = "",
    ) -> dict[str, Any]:
        """Spawn a detached background daemon process with bounded logging and lifecycle tracking."""
        argv, command_label, command_error = self._daemon_argv(command)
        if command_error or argv is None:
            return {"success": False, "error": command_error or "daemon command could not be parsed"}
        authorization = self.authorize_auxiliary_action(
            "spawn_daemon", endpoint="commands.spawn_daemon", task_id=task_id
        )
        if not authorization.get("allowed", False):
            return {
                "success": False,
                "error": authorization.get("reason", "daemon action denied by policy"),
                "policy": authorization,
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        invocation: str | CommandInvocation = (
            command
            if isinstance(command, str)
            else CommandInvocation(argv=argv, cwd=cwd, shell=False)
        )
        worktree_error = self._require_task_worktree(task_id, cwd, invocation)
        if worktree_error:
            return {
                "success": False,
                "error": worktree_error,
                "mutation_worktree_required": True,
                "terminal": True,
                "retryable": False,
            }
        classification_command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        classification = self.classify(classification_command)
        if classification.get("class") == "dangerous" or (
            not classification.get("allowed", False) and self.policy_blocking
        ):
            return {
                "success": False,
                "error": f"daemon command blocked: {classification.get('reason', 'policy')}",
                "classification": classification,
                "policy_blocked": True,
                "terminal": True,
                "retryable": False,
            }
        if not isinstance(name, str) or len(name) > 128 or any(ord(ch) < 32 for ch in name):
            return {"success": False, "error": "daemon name must be a control-free string of at most 128 characters"}
        resolved_cwd = Path(cwd).expanduser().resolve(strict=False)
        if not resolved_cwd.is_dir():
            return {"success": False, "error": f"working directory does not exist: {cwd}"}
        try:
            proc_env = self._daemon_environment(env)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        self._refresh_daemon_capacity()
        if not self._daemon_slots.acquire(blocking=False):
            return {"success": False, "error": "maximum active daemon count reached", "retryable": False}

        import uuid
        daemon_id = f"dmn_{uuid.uuid4().hex}"
        state_dir = configured_state_dir(self.config)
        log_dir = state_dir / "daemons"
        log_path = log_dir / f"{daemon_id}.log"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_fh = log_path.open("w+b")
        except OSError as exc:
            self._daemon_slots.release()
            return {"success": False, "error": f"could not prepare daemon log: {exc}"}
        read_fh = None
        write_fh = None

        kwargs: dict[str, Any] = {
            "cwd": str(resolved_cwd),
            "stdout": None,
            "stderr": subprocess.STDOUT,
            "env": proc_env,
        }
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        else:
            kwargs["start_new_session"] = True

        job_handle = None
        process = None
        try:
            if os.name == "nt":
                job_handle = create_job_object_kill_on_close()
                if not job_handle:
                    raise OSError("unable to create a kill-on-close daemon Job Object")
            read_fd, write_fd = os.pipe()
            read_fh = os.fdopen(read_fd, "rb", buffering=0)
            write_fh = os.fdopen(write_fd, "wb", buffering=0)
            kwargs["stdout"] = write_fh
            launch_authorization = self.authorize_auxiliary_action(
                "spawn_daemon", endpoint="commands.spawn_daemon", task_id=task_id
            )
            if not launch_authorization.get("allowed", False):
                if job_handle:
                    close_job_object(job_handle)
                for handle in (read_fh, write_fh):
                    if handle is not None:
                        try:
                            handle.close()
                        except OSError:
                            pass
                log_fh.close()
                self._daemon_slots.release()
                try:
                    log_path.unlink()
                except OSError:
                    pass
                return {
                    "success": False,
                    "error": launch_authorization.get("reason", "daemon action denied by policy"),
                    "policy": launch_authorization,
                    "policy_blocked": True,
                    "terminal": True,
                    "retryable": False,
                }
            process = subprocess.Popen(argv, **kwargs)
            if job_handle:
                process._local_ai_job_handle = job_handle
                if not assign_process_to_job(job_handle, process.pid):
                    raise OSError("unable to assign suspended daemon to its Job Object")
                if not _resume_suspended_process(process):
                    raise OSError("unable to resume suspended daemon process")
            write_fh.close()
            write_fh = None
        except (OSError, ValueError) as exc:
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if job_handle:
                close_job_object(job_handle)
            for handle in (read_fh, write_fh):
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
            log_fh.close()
            self._daemon_slots.release()
            return {"success": False, "error": f"failed to spawn daemon: {exc}"}

        started_at = time.time()
        info = {
            "daemon_id": daemon_id,
            "process": process,
            "pid": process.pid,
            "identity": process_identity(process.pid),
            "owner_id": self._daemon_owner_id,
            "name": name or daemon_id,
            "command": command_label,
            "cwd": str(resolved_cwd),
            "log_path": str(log_path),
            "log_fh": log_fh,
            "log_buffer": bytearray(),
            "log_lock": threading.Lock(),
            "_log_closed": False,
            "started_at": started_at,
            "expires_at": started_at + self.daemon_ttl_seconds,
            "_slot_acquired": True,
            "_slot_released": False,
        }
        reader = threading.Thread(
            target=self._capture_daemon_output,
            args=(read_fh, info, self.daemon_log_max_bytes),
            name=f"local-ai-daemon-log-{daemon_id}",
            daemon=True,
        )
        info["reader_thread"] = reader
        with self._daemons_lock:
            if len(self._daemons) > 50:
                dead = [d for d, inf in self._daemons.items() if inf["process"].poll() is not None]
                if len(dead) > 20:
                    dead.sort(key=lambda d: float(self._daemons[d].get("stopped_at", self._daemons[d].get("started_at", 0))))
                    for old_d in dead[:len(dead) - 20]:
                        self._close_daemon_log(self._daemons[old_d])
                        self._daemons.pop(old_d, None)
            self._daemons[daemon_id] = info
        try:
            reader.start()
        except RuntimeError as exc:
            try:
                _stop_daemon_tree(info)
                process.wait(timeout=2.0)
            except Exception:
                pass
            try:
                read_fh.close()
            except OSError:
                pass
            self._close_daemon_log(info)
            with self._daemons_lock:
                self._daemons.pop(daemon_id, None)
            self._release_daemon_slot(info)
            return {"success": False, "error": f"failed to start daemon log reader: {exc}"}
        try:
            self._schedule_daemon_expiry(info)
        except RuntimeError as exc:
            stopped = self.stop_daemon(daemon_id)
            return {
                "success": False,
                "error": f"failed to schedule daemon TTL cleanup: {exc}",
                "daemon_id": daemon_id if not stopped.get("success") else None,
                "cleanup_success": bool(stopped.get("success")),
            }
        watcher = threading.Thread(
            target=self._watch_daemon_exit,
            args=(daemon_id, process),
            name=f"local-ai-daemon-watch-{daemon_id}",
            daemon=True,
        )
        info["watcher_thread"] = watcher
        try:
            watcher.start()
        except RuntimeError as exc:
            stopped = self.stop_daemon(daemon_id)
            return {
                "success": False,
                "error": f"failed to start daemon lifecycle watcher: {exc}",
                "cleanup_success": bool(stopped.get("success")),
            }
        with self._daemons_lock:
            registry_saved = self._persist_daemon_registry()
        if not registry_saved:
            stopped = self.stop_daemon(daemon_id)
            return {
                "success": False,
                "error": "daemon registry could not be written; newly started process was stopped",
                "cleanup_success": bool(stopped.get("success")),
            }

        return {
            "success": True,
            "daemon_id": daemon_id,
            "pid": process.pid,
            "name": name or daemon_id,
            "command": command_label,
            "status": "running",
            "log_path": str(log_path),
            "owner_id": self._daemon_owner_id,
            "ttl_seconds": self.daemon_ttl_seconds,
        }

    def daemon_status(self, daemon_id: str | None = None) -> dict[str, Any]:
        """Check status of one or all background daemons."""
        now = time.time()
        with self._daemons_lock:
            if daemon_id:
                info = self._daemons.get(daemon_id)
                if not info:
                    return {"success": False, "error": f"daemon not found: {daemon_id}"}
                proc = info["process"]
                alive = proc.poll() is None
                newly_stopped = not alive and "stopped_at" not in info
                if not alive:
                    tree_stopped = info.get("process_tree_stopped") is True
                    if not tree_stopped:
                        tree_stopped = _stop_daemon_tree(info)
                        info["process_tree_stopped"] = tree_stopped
                    reader = info.get("reader_thread")
                    if reader is not None:
                        reader.join(timeout=0.2)
                    if reader is None or not reader.is_alive():
                        self._close_daemon_log(info)
                    if tree_stopped:
                        timer = info.get("ttl_timer")
                        if timer is not None:
                            timer.cancel()
                        self._release_daemon_slot(info)
                        info.setdefault("stopped_at", now)
                        if newly_stopped:
                            self._persist_daemon_registry()
                self._flush_daemon_log(info)
                with info.get("log_lock", threading.Lock()):
                    log_tail = bytes(info.get("log_buffer", b""))[-8192:].decode("utf-8", errors="replace")
                log_tail = "\n".join(log_tail.splitlines()[-30:])
                return {
                    "success": True,
                    "daemon_id": daemon_id,
                    "alive": alive,
                    "running": alive,
                    "pid": info["pid"],
                    "status": "running" if alive else ("stopped" if info.get("process_tree_stopped") is True else "cleanup_unconfirmed"),
                    "process_tree_stopped": info.get("process_tree_stopped") is True,
                    "exit_code": proc.poll(),
                    "uptime_seconds": round(now - float(info["started_at"]), 1),
                    "owner_id": info.get("owner_id", ""),
                    "ttl_remaining_seconds": max(0.0, round(float(info.get("expires_at", now)) - now, 1)),
                    "name": info["name"],
                    "command": self._safe_label(info["command"]),
                    "log_tail": log_tail,
                }
            items = []
            registry_changed = False
            for d_id, info in self._daemons.items():
                proc = info["process"]
                alive = proc.poll() is None
                if not alive:
                    tree_stopped = info.get("process_tree_stopped") is True
                    if not tree_stopped:
                        tree_stopped = _stop_daemon_tree(info)
                        info["process_tree_stopped"] = tree_stopped
                    reader = info.get("reader_thread")
                    if reader is not None:
                        reader.join(timeout=0.2)
                    if reader is None or not reader.is_alive():
                        self._close_daemon_log(info)
                    if tree_stopped:
                        registry_changed = registry_changed or "stopped_at" not in info
                        timer = info.get("ttl_timer")
                        if timer is not None:
                            timer.cancel()
                        self._release_daemon_slot(info)
                        info.setdefault("stopped_at", now)
                items.append({
                    "daemon_id": d_id,
                    "alive": alive,
                    "running": alive,
                    "pid": info["pid"],
                    "status": "running" if alive else ("stopped" if info.get("process_tree_stopped") is True else "cleanup_unconfirmed"),
                    "process_tree_stopped": info.get("process_tree_stopped") is True,
                    "exit_code": proc.poll(),
                    "uptime_seconds": round(now - float(info["started_at"]), 1),
                    "owner_id": info.get("owner_id", ""),
                    "ttl_remaining_seconds": max(0.0, round(float(info.get("expires_at", now)) - now, 1)),
                    "name": info["name"],
                    "command": self._safe_label(info["command"]),
                })
            if registry_changed:
                self._persist_daemon_registry()
            return {"success": True, "daemons": items, "count": len(items)}

    def stop_daemon(self, daemon_id: str) -> dict[str, Any]:
        """Terminate a background daemon process tree cleanly."""
        with self._daemons_lock:
            info = self._daemons.get(daemon_id)
            if not info:
                return {"success": False, "error": f"daemon not found: {daemon_id}"}
            proc = info["process"]
            tree_stopped = info.get("process_tree_stopped") is True
            if not tree_stopped:
                try:
                    # The leader may have exited while descendants remain in its
                    # process group/tree; stop the owned tree even after leader exit.
                    tree_stopped = _stop_daemon_tree(info)
                except Exception:
                    tree_stopped = False
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
            if not tree_stopped:
                try:
                    tree_stopped = _stop_daemon_tree(info)
                except Exception:
                    tree_stopped = False
            if proc.poll() is None:
                return {
                    "success": False,
                    "daemon_id": daemon_id,
                    "status": "running",
                    "running": True,
                    "alive": True,
                    "process_tree_stopped": False,
                    "pid": info["pid"],
                    "error": "daemon did not stop within the bounded termination window",
                }
            if not tree_stopped:
                return {
                    "success": False,
                    "daemon_id": daemon_id,
                    "status": "cleanup_unconfirmed",
                    "running": False,
                    "alive": False,
                    "process_tree_stopped": False,
                    "pid": info["pid"],
                    "error": "daemon leader stopped but process-tree cleanup could not be confirmed",
                }
            info["process_tree_stopped"] = True
            timer = info.get("ttl_timer")
            if timer is not None:
                timer.cancel()
            reader = info.get("reader_thread")
            if reader is not None:
                reader.join(timeout=2.5)
            self._close_daemon_log(info)
            self._release_daemon_slot(info)
            info["stopped_at"] = time.time()
            if len(self._daemons) > 50:
                dead = [d for d, inf in self._daemons.items() if inf["process"].poll() is not None]
                if len(dead) > 20:
                    dead.sort(key=lambda d: float(self._daemons[d].get("stopped_at", self._daemons[d].get("started_at", 0))))
                    for old_d in dead[:len(dead) - 20]:
                        self._close_daemon_log(self._daemons[old_d])
                        self._daemons.pop(old_d, None)
            self._persist_daemon_registry()
            return {
                "success": True,
                "daemon_id": daemon_id,
                "status": "stopped",
                "running": False,
                "alive": False,
                "process_tree_stopped": True,
                "exit_code": proc.poll(),
            }

    def _cassette_paths(
        self, cassette_name: str, state_dir: str | None = None, *, create: bool = False
    ) -> tuple[Path, Path] | _NetworkPolicyError:
        if (
            not isinstance(cassette_name, str)
            or not _CASSETTE_NAME_RE.fullmatch(cassette_name)
            or cassette_name in {".", ".."}
        ):
            return _NetworkPolicyError("invalid_cassette_name", "Cassette name must be a safe filename")
        configured_root = configured_state_dir(self.config).resolve(strict=False)
        try:
            requested_root = Path(state_dir).expanduser().resolve(strict=False) if state_dir else configured_root
        except (OSError, TypeError, ValueError):
            return _NetworkPolicyError("invalid_cassette_root", "Cassette directory is invalid")
        if not requested_root.is_relative_to(configured_root):
            return _NetworkPolicyError("invalid_cassette_root", "Cassette directory must stay under configured state root")
        cassette_dir = requested_root / "cassettes"
        if cassette_dir.is_symlink():
            return _NetworkPolicyError("invalid_cassette_root", "Cassette directory cannot be a symlink")
        if create:
            try:
                cassette_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return _NetworkPolicyError("invalid_cassette_root", "Cassette directory is unavailable")
        try:
            resolved_dir = cassette_dir.resolve(strict=create)
        except OSError:
            return _NetworkPolicyError("invalid_cassette_root", "Cassette directory is unavailable")
        if not resolved_dir.is_relative_to(configured_root):
            return _NetworkPolicyError("invalid_cassette_root", "Cassette directory escaped configured state root")
        cassette_file = resolved_dir / f"{cassette_name}.json"
        if cassette_file.is_symlink():
            return _NetworkPolicyError("invalid_cassette_path", "Cassette file cannot be a symlink")
        return resolved_dir, cassette_file

    @staticmethod
    def _write_cassette_atomic(
        cassette_dir: Path, cassette_name: str, content: str
    ) -> None:
        """Atomically write a cassette without following a swapped directory link."""
        temp_name = f".{Path(cassette_name).stem}.{uuid.uuid4().hex}.tmp"
        if os.name != "nt":
            import stat

            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow:
                raise OSError("no-follow cassette write is unavailable")
            directory_flags = (
                os.O_RDONLY
                | nofollow
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            directory_fd = os.open(cassette_dir, directory_flags)
            temp_created = False
            temp_fd = -1
            try:
                opened_stat = os.fstat(directory_fd)
                path_stat = os.stat(cassette_dir, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(opened_stat.st_mode)
                    or not stat.S_ISDIR(path_stat.st_mode)
                    or (opened_stat.st_dev, opened_stat.st_ino)
                    != (path_stat.st_dev, path_stat.st_ino)
                ):
                    raise OSError("cassette directory changed during validation")
                file_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | nofollow
                    | getattr(os, "O_CLOEXEC", 0)
                )
                temp_fd = os.open(
                    temp_name,
                    file_flags,
                    0o600,
                    dir_fd=directory_fd,
                )
                temp_created = True
                stream = os.fdopen(temp_fd, "w", encoding="utf-8")
                temp_fd = -1
                with stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(
                    temp_name,
                    cassette_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            finally:
                if temp_fd >= 0:
                    os.close(temp_fd)
                if temp_created:
                    try:
                        os.unlink(temp_name, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
                os.close(directory_fd)
            return

        import ctypes
        from ctypes import wintypes

        class _FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        class _FileInfo(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation", _FileTime),
                ("access", _FileTime),
                ("write", _FileTime),
                ("volume", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        get_info = kernel32.GetFileInformationByHandle
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
        get_info.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        invalid_handle = wintypes.HANDLE(-1).value
        directory_handle = create_file(
            str(cassette_dir),
            0x80,
            0x1 | 0x2,
            None,
            3,
            0x02200000,
            None,
        )
        if directory_handle in (None, invalid_handle):
            raise OSError(ctypes.get_last_error(), "cannot safely open cassette directory")
        temp_file = cassette_dir / temp_name
        try:
            info = _FileInfo()
            if not get_info(directory_handle, ctypes.byref(info)):
                raise OSError(ctypes.get_last_error(), "cannot inspect cassette directory")
            if not info.attributes & 0x10 or info.attributes & 0x400:
                raise OSError("cassette directory is not a regular directory")
            with temp_file.open("x", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_file, cassette_dir / cassette_name)
        finally:
            try:
                temp_file.unlink()
            except FileNotFoundError:
                pass
            close_handle(directory_handle)

    @staticmethod
    def _open_cassette_replay_file(cassette_dir: Path, cassette_name: str) -> int:
        if os.name != "nt":
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if not nofollow:
                raise OSError("no-follow cassette open is unavailable")
            directory_flags = (
                os.O_RDONLY
                | nofollow
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
            )
            directory_fd = os.open(cassette_dir, directory_flags)
            try:
                file_flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0)
                return os.open(cassette_name, file_flags, dir_fd=directory_fd)
            finally:
                os.close(directory_fd)

        import ctypes
        import msvcrt
        from ctypes import wintypes

        class _FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

        class _FileInfo(ctypes.Structure):
            _fields_ = [
                ("attributes", wintypes.DWORD),
                ("creation", _FileTime),
                ("access", _FileTime),
                ("write", _FileTime),
                ("volume", wintypes.DWORD),
                ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD),
                ("index_low", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        get_info = kernel32.GetFileInformationByHandle
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
        get_info.restype = wintypes.BOOL
        get_file_type = kernel32.GetFileType
        get_file_type.argtypes = [wintypes.HANDLE]
        get_file_type.restype = wintypes.DWORD
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        invalid_handle = wintypes.HANDLE(-1).value
        directory_handle = invalid_handle
        file_handle = invalid_handle

        def attributes(handle: Any) -> int:
            info = _FileInfo()
            if not get_info(handle, ctypes.byref(info)):
                raise OSError(ctypes.get_last_error(), "cannot inspect cassette handle")
            return int(info.attributes)

        try:
            directory_handle = create_file(
                str(cassette_dir),
                0x80,
                0x1 | 0x2,
                None,
                3,
                0x02200000,
                None,
            )
            if directory_handle in (None, invalid_handle):
                raise OSError(ctypes.get_last_error(), "cannot safely open cassette directory")
            directory_attributes = attributes(directory_handle)
            if not directory_attributes & 0x10 or directory_attributes & 0x400:
                raise OSError("cassette directory is not a regular directory")

            file_handle = create_file(
                str(cassette_dir / cassette_name),
                0x80000000,
                0x1 | 0x2 | 0x4,
                None,
                3,
                0x00200080,
                None,
            )
            if file_handle in (None, invalid_handle):
                raise OSError(ctypes.get_last_error(), "cannot safely open cassette file")
            file_attributes = attributes(file_handle)
            if file_attributes & (0x10 | 0x400) or get_file_type(file_handle) != 1:
                raise OSError("cassette file is not a regular file")
            descriptor = msvcrt.open_osfhandle(
                int(file_handle), os.O_RDONLY | os.O_BINARY
            )
            file_handle = invalid_handle
            return descriptor
        finally:
            if file_handle not in (None, invalid_handle):
                close_handle(file_handle)
            if directory_handle not in (None, invalid_handle):
                close_handle(directory_handle)

    def http_probe(
        self,
        url: str,
        expected_status: int = 200,
        json_path: str | None = None,
        timeout: float = 5.0,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute a fast, bounded headless HTTP/API endpoint probe."""
        try:
            network = _network_config(self.config)
            response_limit = _network_limit(network, "max_response_bytes", 65536, 4 * 1024 * 1024)
            configured_timeout = float(network.get("timeout_seconds", 10.0))
            requested_timeout = float(timeout)
            if not math.isfinite(configured_timeout) or not math.isfinite(requested_timeout):
                raise _NetworkPolicyError("invalid_network_timeout", "Network timeout is invalid")
            bounded_timeout = max(0.1, min(60.0, configured_timeout, requested_timeout))
            request_headers = _validated_network_headers(headers or None)
            t0 = time.perf_counter()
            status_code, response_headers, body_bytes = _perform_network_request(
                self.config,
                url.strip(),
                method="GET",
                headers=request_headers,
                body=None,
                timeout=bounded_timeout,
                max_response_bytes=response_limit,
                follow_redirects=True,
            )
            elapsed = time.perf_counter() - t0
            safe_headers = _safe_response_headers(response_headers)
            if len(body_bytes) > response_limit:
                return {
                    "success": False,
                    "status_code": status_code,
                    "expected_status": expected_status,
                    "error_code": "response_too_large",
                    "error": "HTTP response exceeds configured byte limit",
                    "body_length": response_limit + 1,
                    "body_truncated": True,
                    "latency_ms": round(elapsed * 1000, 1),
                    "headers": safe_headers,
                }
            body_text = body_bytes.decode("utf-8", errors="replace")
        except _NetworkPolicyError as exc:
            elapsed = time.perf_counter() - t0 if "t0" in locals() else 0.0
            return {
                "success": False,
                "status_code": 0,
                "error_code": exc.code,
                "error": str(exc),
                "latency_ms": round(elapsed * 1000, 1),
            }
        except Exception as exc:
            elapsed = time.perf_counter() - t0 if "t0" in locals() else 0.0
            return {
                "success": False,
                "status_code": 0,
                "error_code": "network_request_failed",
                "error": f"request failed: {type(exc).__name__}",
                "latency_ms": round(elapsed * 1000, 1),
            }

        matches_status = (status_code == expected_status)
        json_match = None
        if json_path:
            try:
                parsed = json.loads(body_text)
                if isinstance(parsed, dict):
                    json_match = bool(parsed.get(json_path) is not None)
                elif isinstance(parsed, list):
                    json_match = (len(parsed) > 0)
                else:
                    json_match = True
            except Exception:
                json_match = False

        success = matches_status and (json_match is not False)
        return {
            "success": success,
            "status_code": status_code,
            "expected_status": expected_status,
            "latency_ms": round(elapsed * 1000, 1),
            "body_preview": _redact_network_text(body_text)[:500],
            "body_length": len(body_bytes),
            "json_matched": json_match,
            "headers": safe_headers,
        }

    def stash_save(
        self,
        cwd: str,
        message: str = "local_ai_hub_stash",
        *,
        task_id: str = "",
    ) -> dict[str, Any]:
        """Save dirty working tree state to Git stash."""
        resolved = str(Path(cwd).resolve())
        cmd = ["git", "stash", "push", "-u", "-m", message]
        worktree_error = self._require_task_worktree(task_id, resolved)
        if worktree_error:
            return {
                "success": False,
                "error": worktree_error,
                "mutation_worktree_required": True,
                "terminal": True,
                "retryable": False,
            }
        res = self._execute(cmd, resolved, timeout=30)
        return {
            "success": res.get("success", False),
            "stdout": res.get("stdout", "").strip(),
            "stashed": "Saved working directory" in res.get("stdout", "") or "No local changes" in res.get("stdout", ""),
        }

    def stash_restore(self, cwd: str, *, task_id: str = "") -> dict[str, Any]:
        """Restore most recent Git stash."""
        resolved = str(Path(cwd).resolve())
        cmd = ["git", "stash", "pop"]
        worktree_error = self._require_task_worktree(task_id, resolved)
        if worktree_error:
            return {
                "success": False,
                "error": worktree_error,
                "mutation_worktree_required": True,
                "terminal": True,
                "retryable": False,
            }
        res = self._execute(cmd, resolved, timeout=30)
        return {
            "success": res.get("success", False),
            "stdout": res.get("stdout", "").strip(),
            "stderr": res.get("stderr", "").strip(),
        }

    def record_mock(self, url: str, cassette_name: str, state_dir: str | None = None) -> dict[str, Any]:
        """Record an HTTP request/response as an offline mock cassette."""
        paths = self._cassette_paths(cassette_name, state_dir, create=True)
        if isinstance(paths, _NetworkPolicyError):
            return {"success": False, "error_code": paths.code, "error": str(paths)}
        cassette_dir, cassette_file = paths
        probe = self.http_probe(url, timeout=10.0)
        if not probe.get("success"):
            return {
                "success": False,
                "error_code": probe.get("error_code", "network_request_failed"),
                "error": "failed to fetch URL",
        }
        data = {
            "url": _safe_network_url(url),
            "recorded_at": time.time(),
            "status_code": probe["status_code"],
            "headers": probe.get("headers", {}),
            "body": probe.get("body_preview", ""),
            "body_length": probe.get("body_length", 0),
        }
        try:
            self._write_cassette_atomic(
                cassette_dir,
                cassette_file.name,
                json_dumps(data, indent=2),
            )
        except OSError:
            return {
                "success": False,
                "error_code": "cassette_write_failed",
                "error": "failed to write cassette",
            }
        return {
            "success": True,
            "cassette": str(cassette_file),
            "url": _safe_network_url(url),
            "status_code": probe["status_code"],
        }

    def replay_mock(self, cassette_name: str, state_dir: str | None = None) -> dict[str, Any]:
        """Replay an offline mock cassette."""
        paths = self._cassette_paths(cassette_name, state_dir)
        if isinstance(paths, _NetworkPolicyError):
            return {"success": False, "error_code": paths.code, "error": str(paths)}
        cassette_dir, cassette_file = paths
        if not cassette_file.is_file():
            return {"success": False, "error": f"cassette not found: {cassette_name}"}
        try:
            if cassette_file.is_symlink():
                return {"success": False, "error_code": "invalid_cassette_path", "error": "Cassette file cannot be a symlink"}
            try:
                descriptor = self._open_cassette_replay_file(cassette_dir, cassette_file.name)
            except (OSError, _NetworkPolicyError):
                return {
                    "success": False,
                    "error_code": "invalid_cassette_path",
                    "error": "Cassette could not be opened safely",
                }
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    return {"success": False, "error_code": "invalid_cassette_path", "error": "Cassette must be a regular file"}
                if os.fstat(stream.fileno()).st_size > _MAX_CASSETTE_BYTES:
                    return {"success": False, "error_code": "cassette_too_large", "error": "Cassette exceeds the 1 MiB limit"}
                raw = stream.read(_MAX_CASSETTE_BYTES + 1)
            if len(raw) > _MAX_CASSETTE_BYTES:
                return {"success": False, "error_code": "cassette_too_large", "error": "Cassette exceeds the 1 MiB limit"}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return {"success": False, "error": "cassette must contain a JSON object"}
            if isinstance(data.get("url"), str):
                data["url"] = _safe_network_url(data["url"])
            if isinstance(data.get("headers"), Mapping):
                data["headers"] = _safe_response_headers(data["headers"])
            if isinstance(data.get("body"), str):
                data["body"] = _redact_network_text(data["body"])
            return {"success": True, "replayed": True, **data}
        except Exception as exc:
            return {"success": False, "error": f"failed to read cassette: {exc}"}

    def diff_hunk_stage(self, cwd: str, patch: str, *, task_id: str = "") -> dict[str, Any]:
        """Apply and stage a diff hunk directly to the git index using git apply --cached."""
        resolved = str(Path(cwd).resolve())
        if not patch or not patch.strip():
            return {"success": False, "error": "patch content must not be empty"}
        worktree_error = self._require_task_worktree(task_id, resolved)
        if worktree_error:
            return {
                "success": False,
                "error": worktree_error,
                "mutation_worktree_required": True,
                "terminal": True,
                "retryable": False,
            }
        if not shutil.which("git"):
            return {"success": False, "error": "git executable not found"}
        try:
            proc = subprocess.run(
                ["git", "apply", "--cached", "--whitespace=nowarn", "-"],
                input=patch.encode("utf-8"),
                capture_output=True,
                cwd=resolved,
                check=False,
                timeout=30,
                **hidden_run_kwargs(),
            )
            clean = (proc.returncode == 0)
            return {
                "success": clean,
                "exit_code": proc.returncode,
                "stdout": proc.stdout.decode("utf-8", errors="replace").strip(),
                "stderr": proc.stderr.decode("utf-8", errors="replace").strip() if not clean else "",
                "staged": clean,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def test_flaky_detect(
        self,
        cwd: str,
        command: str,
        runs: int = 5,
        timeout_per_run: int = 30,
    ) -> dict[str, Any]:
        """Run a test command N times to detect flaky or intermittent failures."""
        resolved = str(Path(cwd).resolve())
        bounded_runs = max(2, min(int(runs), 20))
        results: list[dict[str, Any]] = []
        passed_count = 0
        failed_count = 0
        for i in range(1, bounded_runs + 1):
            res = self._execute(command, resolved, timeout=timeout_per_run)
            is_ok = bool(res.get("success") and res.get("exit_code") == 0)
            if is_ok:
                passed_count += 1
            else:
                failed_count += 1
            results.append({
                "run": i,
                "success": is_ok,
                "exit_code": res.get("exit_code", -1),
                "duration_ms": res.get("duration_ms", 0),
                "stdout_preview": (res.get("stdout") or "")[:200],
                "stderr_preview": (res.get("stderr") or "")[:200],
            })
        is_flaky = (passed_count > 0 and failed_count > 0)
        return {
            "success": True,
            "command": command,
            "total_runs": bounded_runs,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(passed_count / bounded_runs, 2),
            "flaky": is_flaky,
            "status": "flaky" if is_flaky else "stable_pass" if passed_count == bounded_runs else "stable_fail",
            "runs": results,
        }

    @staticmethod
    def _webhook_payload_preflight(payload: dict[str, Any], byte_limit: int) -> str | None:
        minimum_bytes = 0
        active_containers: set[int] = set()

        def json_string_size(value: str) -> int | None:
            size = 2
            for character in value:
                codepoint = ord(character)
                if codepoint in (0x22, 0x5C):
                    size += 2
                elif codepoint < 0x20:
                    size += 2 if codepoint in (0x08, 0x09, 0x0A, 0x0C, 0x0D) else 6
                elif 0xD800 <= codepoint <= 0xDFFF:
                    return None
                elif codepoint < 0x80:
                    size += 1
                elif codepoint < 0x800:
                    size += 2
                elif codepoint < 0x10000:
                    size += 3
                else:
                    size += 4
                if size > byte_limit:
                    return size
            return size

        def dictionary_items(value: dict[Any, Any]):
            for key, item in value.items():
                yield key, True
                yield item, False

        stack: list[tuple[Any, int | None]] = [(iter(((payload, False),)), None)]
        while stack:
            iterator, container_id = stack[-1]
            try:
                value, is_key = next(iterator)
            except StopIteration:
                stack.pop()
                if container_id is not None:
                    active_containers.discard(container_id)
                continue

            if is_key and type(value) is not str:
                return "invalid_webhook_payload"
            if type(value) is str:
                string_size = json_string_size(value)
                if string_size is None:
                    return "invalid_webhook_payload"
                minimum_bytes += string_size
            elif type(value) is dict:
                if is_key:
                    return "invalid_webhook_payload"
                identity = id(value)
                if identity in active_containers:
                    return "invalid_webhook_payload"
                active_containers.add(identity)
                count = len(value)
                minimum_bytes += 2 + (2 * count - 1 if count else 0)
                stack.append((iter(dictionary_items(value)), identity))
            elif type(value) in (list, tuple):
                if is_key:
                    return "invalid_webhook_payload"
                identity = id(value)
                if identity in active_containers:
                    return "invalid_webhook_payload"
                active_containers.add(identity)
                count = len(value)
                minimum_bytes += 2 + (count - 1 if count else 0)
                stack.append((iter((item, False) for item in value), identity))
            elif value is None:
                minimum_bytes += 6 if is_key else 4
            elif type(value) is bool:
                minimum_bytes += (6 if value else 7) if is_key else (4 if value else 5)
            elif type(value) is int:
                bits = abs(value).bit_length()
                upper_digits = (
                    1
                    if value == 0
                    else (bits * 30103 + 99999) // 100000 + (1 if value < 0 else 0)
                )
                key_quotes = 2 if is_key else 0
                remaining_bytes = byte_limit - minimum_bytes - key_quotes
                if upper_digits > remaining_bytes + 1:
                    return "payload_too_large"
                try:
                    minimum_bytes += len(str(value)) + key_quotes
                except (ValueError, OverflowError):
                    return "invalid_webhook_payload"
            elif type(value) is float:
                # Float spellings vary by the active JSON backend (notably for
                # non-finite values), so size the scalar with that backend.
                minimum_bytes += len(json_dumps(value).encode("utf-8"))
            else:
                return "invalid_webhook_payload"

            if minimum_bytes > byte_limit:
                return "payload_too_large"
            if len(stack) > 900:
                return "invalid_webhook_payload"
        return None
    def webhook_replay(
        self,
        url: str,
        payload: dict[str, Any] | str,
        secret: str = "",
        signature_header: str = "X-Hub-Signature-256",
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Deliver a mock webhook payload with HMAC-SHA256 signature to a target endpoint."""
        import hmac

        try:
            network = _network_config(self.config)
            payload_limit = _network_limit(network, "max_payload_bytes", 1_048_576, 4 * 1024 * 1024)
            response_limit = _network_limit(network, "max_response_bytes", 65536, 4 * 1024 * 1024)
            if isinstance(payload, dict):
                preflight_error = self._webhook_payload_preflight(payload, payload_limit)
                if preflight_error is not None:
                    return {
                        "success": False,
                        "error_code": preflight_error,
                        "error": "Webhook payload exceeds the configured limit or contains unsupported values",
                    }
                body_bytes = json_dumps(payload).encode("utf-8")
            else:
                if len(payload) > payload_limit:
                    return {
                        "success": False,
                        "error_code": "payload_too_large",
                        "error": "Webhook payload exceeds configured byte limit",
                    }
                body_bytes = str.encode(payload, "utf-8")
            if len(body_bytes) > payload_limit:
                return {
                    "success": False,
                    "error_code": "payload_too_large",
                    "error": "Webhook payload exceeds configured byte limit",
                }
            if (
                not isinstance(signature_header, str)
                or not _NETWORK_HEADER_NAME_RE.fullmatch(signature_header)
                or signature_header.lower() in {"connection", "content-length", "host", "transfer-encoding"}
            ):
                raise _NetworkPolicyError("invalid_network_headers", "Signature header name is invalid")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "LocalAIHub-WebhookReplay/3.0",
            }
            if secret:
                signature = hmac.new(str(secret).encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
                headers[signature_header] = f"sha256={signature}"
            request_headers = _validated_network_headers(headers)
            configured_timeout = float(network.get("timeout_seconds", 10.0))
            requested_timeout = float(timeout)
            if not math.isfinite(configured_timeout) or not math.isfinite(requested_timeout):
                raise _NetworkPolicyError("invalid_network_timeout", "Network timeout is invalid")
            bounded_timeout = max(0.1, min(60.0, configured_timeout, requested_timeout))
            started = time.perf_counter()
            status, response_headers, response_body = _perform_network_request(
                self.config,
                url,
                method="POST",
                headers=request_headers,
                body=body_bytes,
                timeout=bounded_timeout,
                max_response_bytes=response_limit,
                follow_redirects=False,
            )
            duration = round((time.perf_counter() - started) * 1000, 1)
            safe_headers = _safe_response_headers(response_headers)
            if status in {301, 302, 303, 307, 308}:
                return {
                    "success": False,
                    "status_code": status,
                    "duration_ms": duration,
                    "error_code": "network_redirect_blocked",
                    "error": "Webhook redirects are disabled",
                    "headers": safe_headers,
                }
            if len(response_body) > response_limit:
                return {
                    "success": False,
                    "status_code": status,
                    "duration_ms": duration,
                    "error_code": "response_too_large",
                    "error": "HTTP response exceeds configured byte limit",
                    "body_length": response_limit + 1,
                    "body_truncated": True,
                    "headers": safe_headers,
                }
            response_text = response_body.decode("utf-8", errors="replace")
            return {
                "success": 200 <= status < 300,
                "status_code": status,
                "duration_ms": duration,
                "body_preview": _redact_network_text(response_text)[:500],
                "body_length": len(response_body),
                "headers": safe_headers,
            }
        except _NetworkPolicyError as exc:
            duration = round((time.perf_counter() - started) * 1000, 1) if "started" in locals() else 0.0
            return {"success": False, "error_code": exc.code, "error": str(exc), "duration_ms": duration}
        except Exception as exc:
            duration = round((time.perf_counter() - started) * 1000, 1) if "started" in locals() else 0.0
            return {
                "success": False,
                "error_code": "network_request_failed",
                "error": f"request failed: {type(exc).__name__}",
                "duration_ms": duration,
            }

    def mock_server_start(
        self,
        root: str = ".",
        spec_path: str | None = None,
        port: int = 11440,
    ) -> dict[str, Any]:
        """Start an in-process mock HTTP server delivering simulated OpenAPI endpoints."""
        import http.server
        import socketserver

        target_port = int(port or 11440)
        with self._lock:
            if not hasattr(self, "_mock_servers"):
                self._mock_servers: dict[int, dict[str, Any]] = {}

            if target_port in self._mock_servers:
                srv_info = self._mock_servers[target_port]
                if srv_info.get("alive"):
                    return {"success": True, "running": True, "port": target_port, "routes": srv_info.get("routes", [])}

        endpoints = []
        resolved_root = str(Path(root).resolve())
        if spec_path:
            p_spec = Path(spec_path)
            if not p_spec.is_absolute():
                p_spec = Path(resolved_root) / p_spec
            if p_spec.is_file():
                try:
                    spec_data = json.loads(p_spec.read_text(encoding="utf-8"))
                    paths = spec_data.get("paths", {})
                    for p_url, methods in paths.items():
                        for m, defn in methods.items():
                            endpoints.append({
                                "method": m.upper(),
                                "path": p_url,
                                "summary": defn.get("summary", ""),
                                "responses": defn.get("responses", {}),
                            })
                except Exception:
                    pass

        if not endpoints:
            from .deterministic import DeterministicEngine
            det = DeterministicEngine(self.config)
            spec = det.extract_api_spec(resolved_root)
            endpoints = spec.get("endpoints", [])

        if not endpoints:
            endpoints = [{"method": "GET", "path": "/api/health", "summary": "Health check"}]

        raw_cors_origins = _network_config(self.config).get("mock_server_cors_origins", [])
        if isinstance(raw_cors_origins, str):
            raw_cors_origins = [raw_cors_origins]
        cors_origins = {
            str(origin).strip()
            for origin in raw_cors_origins
            if isinstance(origin, str) and origin.strip() and origin.strip() != "*"
        } if isinstance(raw_cors_origins, (list, tuple, set)) else set()

        class MockHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send_cors_headers(self):
                origin = self.headers.get("Origin", "")
                self.send_header("Vary", "Origin")
                if origin in cors_origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

            def do_OPTIONS(self):
                self.send_response(204)
                self._send_cors_headers()
                self.end_headers()

            def _handle(self, method: str):
                path_only = self.path.split("?", 1)[0]
                matched = None
                for ep in endpoints:
                    if ep.get("method") == method:
                        ep_path = ep.get("path", "")
                        regex_p = "^" + re.sub(r"\{[a-zA-Z0-9_]+\}", "[^/]+", ep_path) + "$"
                        if ep_path == path_only or re.match(regex_p, path_only):
                            matched = ep
                            break

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                resp = {
                    "mock": True,
                    "status": 200,
                    "method": method,
                    "path": path_only,
                    "endpoint": matched or {"path": path_only, "synthetic": True},
                    "data": {"id": 1, "name": "mock_resource", "timestamp": time.time()},
                }
                self.wfile.write(json_dumps(resp).encode("utf-8"))

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        try:
            httpd = ReusableTCPServer(("127.0.0.1", target_port), MockHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True, name=f"mock-srv-{target_port}")
            thread.start()
            with self._lock:
                self._mock_servers[target_port] = {
                    "server": httpd,
                    "thread": thread,
                    "port": target_port,
                    "routes": [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints[:20]],
                    "alive": True,
                    "started_at": time.time(),
                }
            return {
                "success": True,
                "port": target_port,
                "routes_count": len(endpoints),
                "sample_routes": [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints[:10]],
                "status": "listening",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "port": target_port}

    def mock_server_stop(self, port: int = 11440) -> dict[str, Any]:
        """Stop a running mock HTTP server."""
        target_port = int(port or 11440)
        with self._lock:
            srv_info = getattr(self, "_mock_servers", {}).get(target_port)
            if not srv_info or not srv_info.get("alive"):
                return {"success": False, "error": f"no active mock server on port {target_port}"}
            try:
                srv_info["server"].shutdown()
                srv_info["server"].server_close()
                srv_info["alive"] = False
                if len(self._mock_servers) > 32:
                    dead = [p for p, info in self._mock_servers.items() if not info.get("alive")]
                    for p in dead:
                        self._mock_servers.pop(p, None)
                return {"success": True, "stopped": True, "port": target_port}
            except Exception as exc:
                return {"success": False, "error": str(exc), "port": target_port}

    def mock_server_status(self, port: int = 11440) -> dict[str, Any]:
        """Check status of mock HTTP server."""
        target_port = int(port or 11440)
        with self._lock:
            srv_info = getattr(self, "_mock_servers", {}).get(target_port)
            if not srv_info:
                return {"success": True, "running": False, "port": target_port}
            return {
                "success": True,
                "running": bool(srv_info.get("alive")),
                "port": target_port,
                "uptime_seconds": round(time.time() - srv_info.get("started_at", time.time()), 1),
                "routes": srv_info.get("routes", []),
            }


    def _compact(self, result: dict[str, Any], tenant: str, command: str) -> dict[str, Any]:
        stdout = str(result.get("stdout", "")); stderr = str(result.get("stderr", ""))
        combined_chars = len(stdout) + len(stderr)
        diagnostic_artifacts_enabled = rollout_feature_enabled(self.config, "diagnostic_artifacts")
        local_diagnostic_dispatch_enabled = rollout_feature_enabled(self.config, "local_diagnostic_dispatch")
        diagnostic_artifacts_unavailable = {
            "available": False,
            "unsupported": True,
            "feature": "diagnostic_artifacts",
            "error": "diagnostic artifacts are disabled (features.diagnostic_artifacts=false)",
        }
        result["summary"] = self._deterministic_summary(result)
        classification = result.get("classification") if isinstance(result.get("classification"), dict) else {}
        if classification:
            # Keep the policy decision visible even in compact responses.
            result["allowed"] = bool(classification.get("allowed", False))
            result["class"] = str(classification.get("class", "unknown"))
            result["reason"] = str(classification.get("reason", ""))[:240]
        diagnostics = list(result.get("diagnostics") or self._extract_diagnostics(result))
        failure_summary = self._first_failure_summary({**result, "diagnostics": diagnostics})
        if result.get("remediation"):
            rem = result["remediation"]
            fix_msg = rem.get("verified_fix") or rem.get("root_cause")
            if fix_msg:
                diagnostics.insert(0, {
                    "path": "",
                    "line": 0,
                    "column": 0,
                    "message": f"Remediation guidance: {fix_msg}",
                })
        result["diagnostics"] = diagnostics
        if not result.get("success") and not result.get("cancelled"):
            result["failure_summary"] = failure_summary
            result["preview"] = self._failure_preview(failure_summary)
            # Low-confidence short failures do not get the full-log artifact below.
            # Retain only the already-bounded diagnostic so the repair gate receives
            # a safe reference without persisting the raw command output.
            if combined_chars <= self.inline_chars and not result.get("artifact_id") and not failure_summary.get("path"):
                if local_diagnostic_dispatch_enabled and self.artifacts is not None:
                    diagnostic = str(result["preview"])[:800]
                    result["artifact_id"] = self.artifacts.put(diagnostic, tenant, "local_diagnostic_context")
                elif not diagnostic_artifacts_enabled:
                    result["diagnostic_artifacts"] = diagnostic_artifacts_unavailable
                elif self.artifacts is not None:
                    diagnostic = str(result["preview"])[:800]
                    result["artifact_id"] = self.artifacts.put(diagnostic, tenant, "command_diagnostic")
        if combined_chars > self.inline_chars:
            full = f"$ {command}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            if local_diagnostic_dispatch_enabled and not diagnostic_artifacts_enabled and self.artifacts is not None:
                diagnostic = str(result.get("preview", ""))[:800]
                result["artifact_id"] = self.artifacts.put(diagnostic, tenant, "local_diagnostic_context")
            elif not diagnostic_artifacts_enabled:
                result["diagnostic_artifacts"] = diagnostic_artifacts_unavailable
            elif self.artifacts is not None:
                result["artifact_id"] = self.artifacts.put(full, tenant, "command")
            result["stdout"] = stdout[: self.inline_chars // 2]
            result["stderr"] = stderr[-self.inline_chars // 2:]
            result["output_truncated"] = True
        else:
            result["output_truncated"] = False
        return result

    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            active = [
                self._public_active(dict(v, age_ms=max(0, int((now - float(v.get("started_at", now))) * 1000))))
                for v in self._active_commands.values()
            ]
            blocked_by_reason = dict(sorted(self._blocked_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))[:12])
        return {
            "enabled": self.enabled, "hits": self.hits, "misses": self.misses, "cancelled": self.cancelled,
            "coalesced_waiters": self.coalesced, "coalesced_wait_timeouts": self.coalesced_timeouts, "executed": self.executed,
            "blocked": self.blocked, "blocked_by_reason": blocked_by_reason,
            "suppressed": self.suppressed, "suppression_cache": self.suppression_cache.stats(),
            "active_count": len(active), "active": active[:24],
            "success_cache": self.success_cache.stats(), "failure_cache": self.failure_cache.stats(),
        }
