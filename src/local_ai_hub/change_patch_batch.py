"""Bounded batches of canonical Git patches, with exact-path partition checks."""
from __future__ import annotations

import os
import re
from collections.abc import Callable

MAX_PATCH_BYTES = 512 * 1024
MAX_BATCH_PATHS = 8
PATCH_FLAGS = (
    "diff", "--patch", "--binary", "--full-index", "--no-renames", "--no-ext-diff",
    "--no-textconv", "--no-color", "--unified=0", "--no-indent-heuristic",
    "--diff-algorithm=myers", "--submodule=short", "--ignore-submodules=none",
    "--src-prefix=a/", "--dst-prefix=b/", "--no-relative",
)
_HEADER = re.compile(rb"^diff --git ", re.MULTILINE)
_ESCAPES = {7: b"\\a", 8: b"\\b", 9: b"\\t", 10: b"\\n", 11: b"\\v",
            12: b"\\f", 13: b"\\r", 34: b'\\"', 92: b"\\\\"}


def patch_arguments(paths: list[str], *, staged: bool) -> tuple[str, ...]:
    return (*PATCH_FLAGS, *(("--cached",) if staged else ()), "--",
            *(":(literal)" + path for path in paths))


def patch_output_limit(args: tuple[str, ...]) -> int:
    count = sum(arg.startswith(":(literal)") for arg in args[args.index("--") + 1:]) if "--" in args else 1
    return MAX_PATCH_BYTES * max(1, min(MAX_BATCH_PATHS, count))


def _quote(value: bytes) -> bytes:
    # Match Git's core.quotePath=true C quoting, including non-UTF8 names.
    if all(32 <= byte < 127 and byte not in _ESCAPES for byte in value):
        return value
    return b'"' + b"".join(
        _ESCAPES.get(byte, bytes([byte]) if 32 <= byte < 127 else f"\\{byte:03o}".encode("ascii"))
        for byte in value
    ) + b'"'


def partition_patches(raw: bytes, paths: list[str]) -> dict[str, bytes]:
    if not 1 <= len(paths) <= MAX_BATCH_PATHS or len(set(paths)) != len(paths):
        raise ValueError("Invalid Git patch batch")
    expected = {}
    for path in paths:
        name = os.fsencode(path)
        header = b"diff --git " + _quote(b"a/" + name) + b" " + _quote(b"b/" + name)
        if header in expected:
            raise ValueError("Ambiguous Git patch header")
        expected[header] = path
    starts = [match.start() for match in _HEADER.finditer(raw)]
    if not starts or starts[0] != 0 or len(starts) != len(paths) or not raw.endswith(b"\n"):
        raise ValueError("Incomplete Git patch batch")
    result = {}
    for start, end in zip(starts, [*starts[1:], len(raw)]):
        patch = raw[start:end]
        header = patch.split(b"\n", 1)[0]
        path = expected.get(header)
        if path is None or path in result or len(patch) > MAX_PATCH_BYTES:
            raise ValueError("Unmatched or oversized Git patch batch member")
        result[path] = patch
    if result.keys() != set(paths):
        raise ValueError("Git patch batch scope differs")
    return result


class PatchBatchReader:
    """Lazily retain at most one eight-path raw batch per scope."""
    def __init__(self, git: Callable[..., bytes], paths: list[str], *, staged: bool):
        self.git = git
        self.staged = staged
        self.chunks = [paths[i:i + MAX_BATCH_PATHS] for i in range(0, len(paths), MAX_BATCH_PATHS)]
        self.positions = {path: i for i, chunk in enumerate(self.chunks) for path in chunk}
        self.active = -1
        self.patches: dict[str, bytes] = {}
        self.batch_reads = 0

    def read(self, path: str) -> bytes:
        position = self.positions.get(path, -1)
        if position != self.active and position >= 0:
            self.active = position
            self.patches = {}
            chunk = self.chunks[position]
            if len(chunk) > 1:
                try:
                    self.patches = partition_patches(self.git(*patch_arguments(chunk, staged=self.staged)), chunk)
                    self.batch_reads += 1
                except ValueError:
                    # Oversized, missing, ambiguous, or unsupported batches
                    # fall back to exact one-path reads, never inferred bytes.
                    self.patches = {}
        patch = self.patches.pop(path, None)
        return patch if patch is not None else self.git(*patch_arguments([path], staged=self.staged))
