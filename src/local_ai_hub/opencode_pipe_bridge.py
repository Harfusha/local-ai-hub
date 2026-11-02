"""Bounded authenticated stream relay for the experimental sandbox bridge.

The caller supplies the named-pipe adapter and a fixed-target socket factory.
This module is not integrated into the launcher or a production pipe server.
"""
from __future__ import annotations

import hmac
import math
import socket
import threading
import time
from typing import Any, Callable

_MAX_REQUEST = 4 * 1024 * 1024 + 65536
_MAX_RESPONSE = 64 * 1024 * 1024


class BridgeError(RuntimeError):
    """The peer, transport, or bounded relay could not be verified."""


def relay_connection(pipe: Any, secret: bytes, connect: Callable[[], Any], *, timeout: float) -> None:
    """Relay only after identity and secret verification; authenticate each read.

    Pipe reads return None on EOF and b'' on a bounded idle wait. The pipe's
    identity method must inspect the security context of the last read message.
    Responses use four-byte big-endian lengths, a zero end frame, and a single
    authenticated 0x06 acknowledgement before the server disconnects.
    """
    if not isinstance(secret, bytes) or len(secret) != 32:
        raise ValueError("bridge secret must contain 32 bytes")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("invalid bridge timeout")
    deadline = time.monotonic() + timeout
    target = None
    finished = threading.Event()
    end_sent = threading.Event()
    failures: list[BaseException] = []
    reader = None

    def left() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BridgeError("bridge deadline exceeded")
        return remaining

    def authenticated_read() -> bytes | None:
        chunk = pipe.read(65536, min(left(), 0.1))
        if chunk is None or chunk == b"":
            return chunk
        if not isinstance(chunk, bytes) or pipe.matches_identity() is not True:
            raise BridgeError("pipe client identity rejected")
        return chunk

    def receive_response() -> None:
        received = 0
        try:
            while not finished.is_set():
                target.settimeout(min(left(), 0.1))
                try:
                    data = target.recv(65536)
                except (TimeoutError, socket.timeout):
                    continue
                if not data:
                    break
                received += len(data)
                if received > _MAX_RESPONSE:
                    raise BridgeError("bridge response limit exceeded")
                pipe.write(len(data).to_bytes(4, "big") + data, left())
            finished.set()
            pipe.write(b"\x00\x00\x00\x00", left())
        except (OSError, BridgeError) as exc:
            failures.append(exc)
        finally:
            finished.set()
            end_sent.set()

    try:
        handshake = bytearray()
        extra = b""
        while len(handshake) < len(secret):
            data = authenticated_read()
            if data is None:
                raise BridgeError("incomplete bridge handshake")
            if not data:
                continue
            needed = len(secret) - len(handshake)
            handshake.extend(data[:needed])
            extra = data[needed:]
        if not hmac.compare_digest(handshake, secret):
            raise BridgeError("bridge handshake rejected")
        target = connect()
        target.settimeout(min(left(), 0.1))
        reader = threading.Thread(target=receive_response, daemon=True)
        reader.start()
        sent = 0
        acknowledgement = None
        while not finished.is_set():
            data = extra if extra else authenticated_read()
            extra = b""
            if finished.is_set():
                acknowledgement = data
                break
            if data is None:
                raise BridgeError("pipe closed before response")
            if not data:
                continue
            sent += len(data)
            if sent > _MAX_REQUEST:
                raise BridgeError("bridge request limit exceeded")
            target.sendall(data)
        if not end_sent.wait(left()):
            raise BridgeError("bridge response deadline exceeded")
        if failures:
            raise BridgeError("bridge response failed") from failures[0]
        while acknowledgement == b"" or acknowledgement is None:
            acknowledgement = authenticated_read()
            if acknowledgement is None:
                raise BridgeError("pipe closed before acknowledgement")
        if acknowledgement != b"\x06":
            raise BridgeError("invalid bridge acknowledgement")
    finally:
        finished.set()
        if target is not None:
            try:
                target.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            target.close()
        pipe.close()
        if reader is not None:
            reader.join(timeout=1)
