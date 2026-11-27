"""Small, fail-closed primitives for the managed OpenCode pipe broker."""

from __future__ import annotations

import hmac
import http.client
import re
import time
import threading


MAX_PIPE_FRAME_BYTES = 65_536
SESSION_SECRET_BYTES = 32
MAX_HTTP_HEADER_BYTES = 16_384
MAX_HTTP_BODY_BYTES = 4 * 1024 * 1024
MAX_HUB_RESPONSE_BYTES = 64 * 1024 * 1024
_APPCONTAINER_SID = re.compile(r"S-1-15-2-(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*))*\Z")
_ANY_SID = re.compile(r"S-1-(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*))*\Z")
_LOGON_SID = re.compile(r"S-1-5-5-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)\Z")
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")


def build_pipe_name(session_id: str) -> str:
    """Return an unqualified per-session pipe path for the AppContainer bridge."""
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("invalid session ID")
    return rf"\\.\pipe\lah-opencode-{session_id}"


def _appcontainer_sid(value: object) -> str:
    if (not isinstance(value, str) or len(value) > 184
            or _APPCONTAINER_SID.fullmatch(value) is None):
        raise ValueError("expected an AppContainer SID")
    return value


def build_pipe_sddl(appcontainer_sid: str, owner_sid: str) -> str:
    """Keep owner access and grant the package only pipe data rights."""
    package_sid = _appcontainer_sid(appcontainer_sid)
    if (not isinstance(owner_sid, str) or len(owner_sid) > 184
            or _ANY_SID.fullmatch(owner_sid) is None):
        raise ValueError("expected a Windows token owner SID")
    # 0x12019B = read/write data, read-control, synchronize and attributes;
    # it excludes FILE_CREATE_PIPE_INSTANCE, WRITE_DAC and WRITE_OWNER.
    return f"D:P(A;;GA;;;SY)(A;;GA;;;{owner_sid})(A;;0x12019B;;;{package_sid})"


def _token_logon_sid(token_handle: int) -> str:
    """Return the unique Windows logon SID from a token's enabled logon groups."""
    import win32security

    groups = win32security.GetTokenInformation(token_handle, win32security.TokenGroups)
    values = [
        win32security.ConvertSidToStringSid(sid)
        for sid, attributes in groups
        if attributes & 0xC0000000 == 0xC0000000
    ]
    if len(values) != 1 or _LOGON_SID.fullmatch(values[0]) is None:
        raise PermissionError("Windows token did not contain exactly one valid logon SID")
    return values[0]


def verify_client_identity(
    observed_appcontainer_sid: str | None,
    expected_appcontainer_sid: str,
    observed_session_id: int,
    expected_session_id: int,
    observed_logon_sid: str | None,
    expected_logon_sid: str,
) -> bool:
    """Require the exact AppContainer and logon session; unknown fails closed."""
    try:
        observed = _appcontainer_sid(observed_appcontainer_sid)
        expected = _appcontainer_sid(expected_appcontainer_sid)
    except ValueError:
        return False
    if (not isinstance(observed_logon_sid, str) or not isinstance(expected_logon_sid, str)
            or _LOGON_SID.fullmatch(observed_logon_sid) is None
            or _LOGON_SID.fullmatch(expected_logon_sid) is None):
        return False
    if (isinstance(observed_session_id, bool) or not isinstance(observed_session_id, int)
            or isinstance(expected_session_id, bool) or not isinstance(expected_session_id, int)):
        return False
    return (
        hmac.compare_digest(observed, expected)
        and hmac.compare_digest(observed_logon_sid, expected_logon_sid)
        and observed_session_id == expected_session_id
    )


def verify_session_secret(observed: bytes, expected: bytes) -> bool:
    """Verify the one-session 256-bit bearer nonce without accepting short keys."""
    return (
        isinstance(observed, bytes)
        and isinstance(expected, bytes)
        and len(observed) == SESSION_SECRET_BYTES
        and len(expected) == SESSION_SECRET_BYTES
        and hmac.compare_digest(observed, expected)
    )


def encode_response_frame(payload: bytes, *, end: bool = False) -> bytes:
    """Encode the bounded length-prefixed response format used by the bridge."""
    if not isinstance(payload, bytes):
        raise ValueError("frame payload must be bytes")
    if end:
        if payload:
            raise ValueError("end frame must be empty")
        return b"\x00\x00\x00\x00"
    if not 1 <= len(payload) <= MAX_PIPE_FRAME_BYTES:
        raise ValueError("frame payload exceeds the permitted frame size")
    return len(payload).to_bytes(4, "big") + payload


def parse_hub_chat_request(raw: bytes) -> bytes:
    """Validate one bounded OpenCode request and return only its JSON body.

    The caller must construct a new HTTP request to the fixed Hub origin and
    `/api/chat/completions` path. Incoming Host and hop-by-hop headers are never
    returned or forwarded.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_HTTP_HEADER_BYTES + MAX_HTTP_BODY_BYTES:
        raise ValueError("HTTP request exceeds the permitted length")
    head, separator, body = raw.partition(b"\r\n\r\n")
    if not separator or len(head) > MAX_HTTP_HEADER_BYTES:
        raise ValueError("invalid HTTP request header length")
    if b"\n" in head.replace(b"\r\n", b"") or b"\r" in head.replace(b"\r\n", b""):
        raise ValueError("invalid HTTP line endings")
    lines = head.split(b"\r\n")
    try:
        request_line = lines[0].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid HTTP request line") from exc
    if request_line != "POST /api/chat/completions HTTP/1.1":
        raise ValueError("HTTP route is not allowed")

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or b":" not in line or line[:1] in (b" ", b"\t"):
            raise ValueError("invalid HTTP header")
        key, value = line.split(b":", 1)
        try:
            name = key.decode("ascii").lower()
            text = value.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("invalid HTTP header encoding") from exc
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9a-z-]+", name):
            raise ValueError("invalid HTTP header name")
        if name in headers:
            raise ValueError("duplicate HTTP header")
        if any(ord(char) < 0x20 and char != "\t" for char in text):
            raise ValueError("invalid HTTP header value")
        headers[name] = text

    if "transfer-encoding" in headers:
        raise ValueError("HTTP transfer encoding is not supported")
    if "expect" in headers:
        raise ValueError("HTTP expectations are not supported")
    if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("HTTP content type must be application/json")
    raw_length = headers.get("content-length")
    if not raw_length or not raw_length.isascii() or not raw_length.isdecimal():
        raise ValueError("HTTP content length is invalid")
    length = int(raw_length)
    if not 1 <= length <= MAX_HTTP_BODY_BYTES or len(body) != length:
        raise ValueError("HTTP body length does not match its content length")
    return body


def forward_hub_chat(
    body: bytes,
    *,
    hub_port: int,
    api_token: str | None = None,
    timeout: float = 120.0,
) -> tuple[int, str, bytes]:
    """Forward JSON to the fixed loopback Hub endpoint with bounded output.

    The caller supplies the Hub's configured port and optional configured API
    token. No client-provided authority, path, proxy, or headers are accepted.
    """
    if isinstance(hub_port, bool) or not isinstance(hub_port, int) or not 1 <= hub_port <= 65535:
        raise ValueError("Hub port must be an integer from 1 to 65535")
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_HTTP_BODY_BYTES:
        raise ValueError("Hub request body exceeds the permitted length")
    if api_token is not None and (
        not isinstance(api_token, str)
        or not api_token
        or len(api_token) > 4096
        or any(ord(char) < 0x21 or ord(char) > 0x7E for char in api_token)
    ):
        raise ValueError("Hub API token is invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
        raise ValueError("Hub timeout must be greater than 0 and at most 600 seconds")

    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "Connection": "close",
        "Accept": "application/json, text/event-stream",
    }
    if api_token is not None:
        headers["Authorization"] = f"Bearer {api_token}"

    connection = http.client.HTTPConnection("127.0.0.1", hub_port, timeout=float(timeout))
    try:
        connection.request("POST", "/api/chat/completions", body=body, headers=headers)
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "").strip()
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type not in {"application/json", "text/event-stream"}:
            raise ValueError("Hub returned an unsupported content type")
        declared = response.getheader("Content-Length")
        if declared is not None:
            if not declared.isascii() or not declared.isdecimal() or int(declared) > MAX_HUB_RESPONSE_BYTES:
                raise ValueError("Hub response exceeds the permitted length")
        result = response.read(MAX_HUB_RESPONSE_BYTES + 1)
        if len(result) > MAX_HUB_RESPONSE_BYTES:
            raise ValueError("Hub response exceeds the permitted length")
        return response.status, content_type, result
    finally:
        connection.close()


def frame_http_response(status: int, content_type: str, body: bytes) -> tuple[bytes, ...]:
    """Encode a bounded HTTP response as bridge frames plus the terminal frame."""
    if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status <= 599:
        raise ValueError("Hub response status is invalid")
    if (not isinstance(content_type, str) or len(content_type) > 256
            or any(ord(char) < 0x20 or ord(char) > 0x7E for char in content_type)):
        raise ValueError("Hub response content type is invalid")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"application/json", "text/event-stream"}:
        raise ValueError("Hub response content type is not allowed")
    if not isinstance(body, bytes) or len(body) > MAX_HUB_RESPONSE_BYTES:
        raise ValueError("Hub response exceeds the permitted length")

    reason = http.client.responses.get(status, "Response")
    header = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    wire = header + body
    if len(wire) > MAX_HUB_RESPONSE_BYTES:
        raise ValueError("Hub response exceeds the permitted wire length")
    frames = tuple(
        encode_response_frame(wire[offset:offset + MAX_PIPE_FRAME_BYTES])
        for offset in range(0, len(wire), MAX_PIPE_FRAME_BYTES)
    )
    return frames + (encode_response_frame(b"", end=True),)


def _token_appcontainer_sid(token_handle: int) -> str | None:
    """Read TokenAppContainerSid (31), which pywin32 does not expose yet."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_token_information.restype = wintypes.BOOL
    required = wintypes.DWORD(0)
    get_token_information(wintypes.HANDLE(token_handle), 31, None, 0, ctypes.byref(required))
    if required.value == 0:
        return None
    buffer = ctypes.create_string_buffer(required.value)
    if not get_token_information(
        wintypes.HANDLE(token_handle), 31, buffer, required.value, ctypes.byref(required)
    ):
        raise ctypes.WinError(ctypes.get_last_error())

    class _TokenAppContainerInformation(ctypes.Structure):
        _fields_ = [("AppContainerSid", wintypes.LPVOID)]

    sid_pointer = ctypes.cast(buffer, ctypes.POINTER(_TokenAppContainerInformation)).contents.AppContainerSid
    if not sid_pointer:
        return None
    sid_text = wintypes.LPWSTR()
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    if not convert_sid(sid_pointer, ctypes.byref(sid_text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return sid_text.value
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(sid_text, wintypes.HLOCAL))


def _create_windows_opencode_pipe(pipe_name: str, appcontainer_sid: str):
    """Create one first-instance pipe for SYSTEM, owner and one package SID."""
    if __import__("sys").platform != "win32":
        raise OSError("OpenCode named-pipe listener requires Windows")
    import pywintypes
    import win32api
    import win32con
    import win32pipe
    import win32security

    owner_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
    )
    try:
        owner_sid = win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(owner_token, win32security.TokenOwner)
        )
    finally:
        win32api.CloseHandle(owner_token)
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        build_pipe_sddl(appcontainer_sid, owner_sid), win32security.SDDL_REVISION_1
    )
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    attributes.bInheritHandle = False
    open_mode = (
        win32pipe.PIPE_ACCESS_DUPLEX
        | win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE
        | win32con.FILE_FLAG_OVERLAPPED
    )
    pipe_mode = (
        win32pipe.PIPE_TYPE_BYTE
        | win32pipe.PIPE_READMODE_BYTE
        | win32pipe.PIPE_WAIT
        | win32pipe.PIPE_REJECT_REMOTE_CLIENTS
    )
    return win32pipe.CreateNamedPipe(
        pipe_name,
        open_mode,
        pipe_mode,
        1,
        MAX_PIPE_FRAME_BYTES,
        MAX_PIPE_FRAME_BYTES,
        0,
        attributes,
    )


class WindowsOpenCodePipeListener:
    """One-request Windows listener bound to an AppContainer and logon session.

    The managed launcher must own this listener's process lifetime. This class
    does not itself establish filesystem, network-egress, or GPU isolation.
    """

    def __init__(
        self,
        *,
        session_id: str,
        appcontainer_sid: str,
        windows_session_id: int,
        secret: bytes,
        hub_port: int,
        hub_api_token: str | None = None,
        io_timeout: float = 120.0,
    ) -> None:
        self.session_id = session_id
        self.pipe_name = build_pipe_name(session_id)
        self.appcontainer_sid = _appcontainer_sid(appcontainer_sid)
        if (isinstance(windows_session_id, bool) or not isinstance(windows_session_id, int)
                or windows_session_id < 0):
            raise ValueError("invalid Windows session ID")
        if not isinstance(secret, bytes) or len(secret) != SESSION_SECRET_BYTES:
            raise ValueError("session secret must be exactly 32 bytes")
        if isinstance(io_timeout, bool) or not isinstance(io_timeout, (int, float)) or not 0 < io_timeout <= 600:
            raise ValueError("pipe I/O timeout must be greater than 0 and at most 600 seconds")
        # Validate the remaining bounded Hub settings before creating a pipe.
        if isinstance(hub_port, bool) or not isinstance(hub_port, int) or not 1 <= hub_port <= 65535:
            raise ValueError("Hub port must be an integer from 1 to 65535")
        if hub_api_token is not None and (
            not isinstance(hub_api_token, str) or not hub_api_token or len(hub_api_token) > 4096
            or any(ord(char) < 0x21 or ord(char) > 0x7E for char in hub_api_token)
        ):
            raise ValueError("Hub API token is invalid")
        self.windows_session_id = windows_session_id
        self.secret = bytes(secret)
        self.hub_port = hub_port
        self.hub_api_token = hub_api_token
        self.io_timeout = float(io_timeout)
        self.pipe_ready = threading.Event()
        self._stop_event = threading.Event()
        self._active_pipe_lock = threading.Lock()
        self._active_pipe_handle: int | None = None
        self._serve_error: BaseException | None = None

    def stop(self) -> None:
        """Cancel pending pipe I/O; the owning thread remains responsible for close."""
        self._stop_event.set()
        with self._active_pipe_lock:
            pipe_handle = self._active_pipe_handle
        if pipe_handle:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
            kernel32.CancelIoEx.restype = wintypes.BOOL
            kernel32.CancelIoEx(wintypes.HANDLE(pipe_handle), None)

    def serve_forever(self) -> None:
        """Recreate the authenticated one-request pipe until stopped or an unknown error."""
        self._serve_error = None
        while not self._stop_event.is_set():
            try:
                self.serve_once()
            except Exception as exc:
                if self._stop_event.is_set():
                    return
                self._serve_error = exc
                raise

    def serve_once(self) -> None:
        """Accept, authenticate, forward, frame and acknowledge one request."""
        if __import__("sys").platform != "win32":
            raise OSError("OpenCode named-pipe listener requires Windows")
        import pywintypes
        import win32api
        import win32pipe
        import win32security
        import ctypes
        from ctypes import wintypes

        host_token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
        )
        try:
            host_logon_sid = _token_logon_sid(int(host_token))
        finally:
            win32api.CloseHandle(host_token)
        handle = _create_windows_opencode_pipe(self.pipe_name, self.appcontainer_sid)
        with self._active_pipe_lock:
            self._active_pipe_handle = int(handle)
        self.pipe_ready.clear()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _OVERLAPPED(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_size_t),
                ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
        kernel32.ConnectNamedPipe.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED)]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED)]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        kernel32.GetOverlappedResult.restype = wintypes.BOOL
        kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
        kernel32.CancelIoEx.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        pipe_handle = wintypes.HANDLE(int(handle))
        client_deadline: list[float | None] = [None]

        def begin_overlapped():
            event = kernel32.CreateEventW(None, True, False, None)
            if not event:
                raise ctypes.WinError(ctypes.get_last_error())
            operation = _OVERLAPPED()
            operation.hEvent = event
            return operation, event

        def wait_overlapped(operation, event, operation_name: str) -> int:
            deadline = client_deadline[0]
            remaining = self.io_timeout if deadline is None else deadline - time.monotonic()
            timeout_ms = max(0, int(remaining * 1000))
            result = kernel32.WaitForSingleObject(event, timeout_ms)
            if result == 258:  # WAIT_TIMEOUT
                kernel32.CancelIoEx(pipe_handle, ctypes.byref(operation))
                kernel32.WaitForSingleObject(event, 0xFFFFFFFF)
                raise TimeoutError(f"{operation_name} timed out")
            if result != 0:  # WAIT_OBJECT_0
                raise ctypes.WinError(ctypes.get_last_error())
            transferred = wintypes.DWORD(0)
            if not kernel32.GetOverlappedResult(
                pipe_handle, ctypes.byref(operation), ctypes.byref(transferred), False
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return transferred.value

        try:
            if self._stop_event.is_set():
                return
            operation, event = begin_overlapped()
            try:
                connected = kernel32.ConnectNamedPipe(pipe_handle, ctypes.byref(operation))
                error = 0 if connected else ctypes.get_last_error()
                if not connected and error == 535:  # ERROR_PIPE_CONNECTED
                    pass
                elif not connected and error == 997:  # ERROR_IO_PENDING
                    self.pipe_ready.set()
                    if self._stop_event.is_set():
                        kernel32.CancelIoEx(pipe_handle, None)
                    wait_overlapped(operation, event, "named-pipe connection")
                elif not connected:
                    raise ctypes.WinError(error)
            finally:
                win32api.CloseHandle(event)
            self.pipe_ready.set()
            if self._stop_event.is_set():
                return
            client_deadline[0] = time.monotonic() + self.io_timeout

            def read_some(limit: int) -> bytes:
                buffer = ctypes.create_string_buffer(limit)
                transferred = wintypes.DWORD(0)
                operation, event = begin_overlapped()
                try:
                    complete = kernel32.ReadFile(
                        pipe_handle, buffer, limit, ctypes.byref(transferred), ctypes.byref(operation)
                    )
                    error = 0 if complete else ctypes.get_last_error()
                    if not complete and error == 997:
                        transferred.value = wait_overlapped(operation, event, "named-pipe read")
                    elif not complete:
                        raise ctypes.WinError(error)
                    if transferred.value == 0:
                        raise ConnectionError("named-pipe client disconnected")
                    return buffer.raw[:transferred.value]
                finally:
                    win32api.CloseHandle(event)

            def read_exact(length: int) -> bytes:
                result = bytearray()
                while len(result) < length:
                    result.extend(read_some(min(4096, length - len(result))))
                return bytes(result)

            # Windows cannot impersonate a named-pipe client until it has written
            # data. Read only the fixed-size nonce before impersonation; do not
            # parse or forward anything until identity and nonce both pass.
            observed_secret = read_exact(SESSION_SECRET_BYTES)
            impersonated = False
            token = None
            try:
                win32security.ImpersonateNamedPipeClient(handle)
                impersonated = True
                token = win32security.OpenThreadToken(
                    win32api.GetCurrentThread(), win32security.TOKEN_QUERY, True
                )
                observed_sid = _token_appcontainer_sid(int(token))
                observed_session = win32security.GetTokenInformation(token, win32security.TokenSessionId)
                observed_logon_sid = _token_logon_sid(int(token))
                if not verify_client_identity(
                    observed_sid, self.appcontainer_sid, observed_session,
                    self.windows_session_id, observed_logon_sid, host_logon_sid,
                ):
                    raise PermissionError("named-pipe client identity did not match this session")
            finally:
                try:
                    if token is not None:
                        win32api.CloseHandle(token)
                finally:
                    if impersonated:
                        win32security.RevertToSelf()

            def write_all(payload: bytes) -> None:
                offset = 0
                while offset < len(payload):
                    chunk = payload[offset:]
                    buffer = ctypes.create_string_buffer(chunk, len(chunk))
                    transferred = wintypes.DWORD(0)
                    operation, event = begin_overlapped()
                    try:
                        complete = kernel32.WriteFile(
                            pipe_handle, buffer, len(chunk), ctypes.byref(transferred), ctypes.byref(operation)
                        )
                        error = 0 if complete else ctypes.get_last_error()
                        if not complete and error == 997:
                            transferred.value = wait_overlapped(operation, event, "named-pipe write")
                        elif not complete:
                            raise ctypes.WinError(error)
                        if transferred.value == 0:
                            raise ConnectionError("named-pipe client closed while receiving a response")
                        offset += transferred.value
                    finally:
                        win32api.CloseHandle(event)

            if not verify_session_secret(observed_secret, self.secret):
                raise PermissionError("named-pipe session secret did not match")
            request = _read_pipe_http_request(read_some, read_exact)
            body = parse_hub_chat_request(request)
            status, content_type, response_body = forward_hub_chat(
                body, hub_port=self.hub_port, api_token=self.hub_api_token, timeout=self.io_timeout
            )
            for frame in frame_http_response(status, content_type, response_body):
                write_all(frame)
            if read_exact(1) != b"\x06":
                raise PermissionError("named-pipe response acknowledgement is invalid")
        finally:
            with self._active_pipe_lock:
                self._active_pipe_handle = None
            try:
                win32pipe.DisconnectNamedPipe(handle)
            except Exception:
                pass
            win32api.CloseHandle(handle)


def _read_pipe_http_request(read_some, read_exact) -> bytes:
    """Read one HTTP request from a byte pipe without consuming extra bytes."""
    raw = bytearray()
    header_end = -1
    while header_end < 0:
        if len(raw) >= MAX_HTTP_HEADER_BYTES + 4:
            raise ValueError("HTTP request header exceeds the permitted length")
        raw.extend(read_some(min(4096, MAX_HTTP_HEADER_BYTES + 4 - len(raw))))
        marker = raw.find(b"\r\n\r\n")
        if marker >= 0:
            header_end = marker + 4
    head = bytes(raw[:header_end - 4])
    if len(head) > MAX_HTTP_HEADER_BYTES:
        raise ValueError("HTTP request header exceeds the permitted length")
    content_lengths = []
    for line in head.split(b"\r\n")[1:]:
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        if key.strip().lower() == b"content-length":
            content_lengths.append(value.strip())
    if len(content_lengths) != 1 or not content_lengths[0].isdigit():
        raise ValueError("HTTP content length is invalid")
    expected = int(content_lengths[0])
    if not 1 <= expected <= MAX_HTTP_BODY_BYTES:
        raise ValueError("HTTP body length exceeds the permitted length")
    total = header_end + expected
    if len(raw) > total:
        raise ValueError("unexpected bytes after the HTTP request body")
    if len(raw) < total:
        raw.extend(read_exact(total - len(raw)))
    return bytes(raw)
