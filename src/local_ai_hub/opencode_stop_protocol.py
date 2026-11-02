"""Experimental authenticated process and whole-session control protocol.

Whole-session cancellation does not claim subtree-only termination and is not
connected to a production launcher.
"""
from __future__ import annotations

import hmac
import math
import struct
import time
from typing import Callable

from .process_utils import _windows_process_identity


class ControlError(RuntimeError):
    def __init__(self, message: str, *, outcome_unknown: bool):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


def control_exchange(pipe, secret: bytes, binding, *, timeout: float,
                     lookup: Callable = _windows_process_identity) -> str:
    """Authorize a single process stop and require a client acknowledgement.

    Request: magic LAC1 or LAC2, 32-byte secret, uint32 PID and uint64 Windows
    creation time, in big-endian order. LAC1 responses: 0 denied, 1 stopped,
    2 unknown. LAC2 response 3 means whole-session cancellation accepted,
    not completed; the job is terminated only after client acknowledgement.
    A lost response after dispatch is outcome-unknown and must not be retried.
    """
    if not isinstance(secret, bytes) or len(secret) != 32:
        raise ValueError("control secret must contain 32 bytes")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError("invalid control timeout")
    deadline = time.monotonic() + timeout
    dispatched = False

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise ControlError("control deadline exceeded", outcome_unknown=dispatched)
        return left

    def read_exact(size):
        output = bytearray()
        while len(output) < size:
            try:
                chunk = pipe.read(size - len(output), min(remaining(), 0.1))
                if chunk is None:
                    raise ControlError("control peer disconnected", outcome_unknown=dispatched)
                if not chunk:
                    continue
                if not isinstance(chunk, bytes) or len(chunk) > size - len(output) or pipe.matches_identity() is not True:
                    raise ControlError("control client identity rejected", outcome_unknown=dispatched)
                output.extend(chunk)
            except ControlError:
                raise
            except Exception as exc:
                raise ControlError("control read failed", outcome_unknown=dispatched) from exc
        return bytes(output)

    request = read_exact(48)
    if request[:4] not in {b"LAC1", b"LAC2"} or not hmac.compare_digest(request[4:36], secret):
        raise ControlError("control authentication failed", outcome_unknown=False)
    pid, creation = struct.unpack(">IQ", request[36:])
    try:
        identity = lookup(pid) if pid and creation else None
    except Exception as exc:
        raise ControlError("control identity lookup failed", outcome_unknown=False) from exc
    if request[:4] == b"LAC2":
        allowed = False
        if (isinstance(identity, dict) and identity.get("pid") == pid
                and type(identity.get("creation_identity")) is int and identity["creation_identity"] == creation):
            try:
                allowed = binding.permits(identity) is True
            except Exception as exc:
                raise ControlError("control authorization failed", outcome_unknown=False) from exc
        try:
            pipe.write(b"\x03" if allowed else b"\x00", remaining())
            if read_exact(1) != b"\x06":
                raise ControlError("control acknowledgement rejected", outcome_unknown=False)
        except ControlError:
            raise
        except Exception as exc:
            raise ControlError("control response failed", outcome_unknown=False) from exc
        if not allowed:
            return "denied"
        try:
            if binding.cancel_job() is not True:
                raise ControlError("session cancellation is unconfirmed", outcome_unknown=True)
        except ControlError:
            raise
        except Exception as exc:
            raise ControlError("session cancellation failed", outcome_unknown=True) from exc
        return "job_cancelled"
    result = False
    if (isinstance(identity, dict) and identity.get("pid") == pid
            and type(identity.get("creation_identity")) is int and identity["creation_identity"] == creation):
        dispatched = True
        try:
            result = binding.stop(identity)
        except Exception as exc:
            raise ControlError("control dispatch failed", outcome_unknown=True) from exc
        if result is not None and type(result) is not bool:
            raise ControlError("invalid control result", outcome_unknown=True)
    status = "stopped" if result is True else "denied" if result is False else "unknown"
    try:
        pipe.write({"denied": b"\x00", "stopped": b"\x01", "unknown": b"\x02"}[status], remaining())
        if read_exact(1) != b"\x06":
            raise ControlError("control acknowledgement rejected", outcome_unknown=dispatched)
    except ControlError:
        raise
    except Exception as exc:
        raise ControlError("control response failed", outcome_unknown=dispatched) from exc
    return status
