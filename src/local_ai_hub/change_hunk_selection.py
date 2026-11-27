"""Materialize a selected subset of observed zero-context text hunks."""
from __future__ import annotations

import hashlib
import re

from .change_atoms import _HUNK, identity
from .change_semantics import _blob_matches, _lines, reconstruct_blob

_INDEX = re.compile(rb"^index ([0-9a-f]{40}|[0-9a-f]{64})\.\.([0-9a-f]{40}|[0-9a-f]{64}) (100644|100755)$")
_MAX_BYTES = 256 * 1024


def patch_blob_pair(patch: bytes) -> tuple[str, str, str]:
    lines = patch.split(b"\n")
    if len(lines) < 5 or not lines[0].startswith(b"diff --git "):
        raise ValueError("Unsupported hunk patch")
    match = _INDEX.fullmatch(lines[1])
    if match is None or not lines[2].startswith(b"--- ") or not lines[3].startswith(b"+++ ") or not _HUNK.match(lines[4]):
        raise ValueError("Partial staging supports regular text modifications without mode changes only")
    old, new, mode = (part.decode("ascii") for part in match.groups())
    if len(old) != len(new) or not old.strip("0") or not new.strip("0"):
        raise ValueError("Unsupported blob pair")
    return old, new, mode


def select_hunks(
    before: bytes, patch: bytes, root: str, path: str, atom_id: str, selected: list[str],
) -> tuple[bytes, str]:
    old, new, mode = patch_blob_pair(patch)
    if len(before) > _MAX_BYTES or not _blob_matches(before, old):
        raise ValueError("Old blob identity or size does not match")
    if identity("patch-v1", root, path, "unstaged", hashlib.sha256(patch).hexdigest()) != atom_id:
        raise ValueError("Observed patch changed")
    if reconstruct_blob(before, patch, new) is None:
        raise ValueError("Full patch cannot be independently reconstructed")
    if not selected or len(selected) > 64 or len(set(selected)) != len(selected):
        raise ValueError("Select 1–64 distinct hunk IDs")
    lines = patch.split(b"\n")
    starts = [i for i, line in enumerate(lines) if _HUNK.match(line)]
    if len(starts) > 64:
        raise ValueError("Hunk observation truncated")
    source = _lines(before)
    output: list[bytes] = []
    cursor = 0
    seen: set[str] = set()
    for start, end in zip(starts, starts[1:] + [len(lines)]):
        digest = hashlib.sha256(b"\n".join(lines[start:end]) + b"\n").hexdigest()
        hunk_id = identity("hunk-v1", root, path, "unstaged", digest)
        if hunk_id not in selected:
            continue
        seen.add(hunk_id)
        match = _HUNK.match(lines[start])
        assert match is not None
        old_start, old_count, _, new_count = match.groups()
        count = int(old_count or b"1")
        at = int(old_start) - int(count != 0)
        if not cursor <= at <= len(source):
            raise ValueError("Overlapping hunk ranges")
        output.extend(source[cursor:at])
        cursor = at
        body = lines[start + 1:end]
        if body and body[-1] == b"":
            body = body[:-1]
        i = 0
        removed = added = 0
        while i < len(body):
            flag, content = body[i][:1], body[i][1:] + b"\n"
            i += 1
            if i < len(body) and body[i] == b"\\ No newline at end of file":
                content = content[:-1]
                i += 1
            if flag == b"-":
                if cursor >= len(source) or source[cursor] != content:
                    raise ValueError("Hunk preimage mismatch")
                cursor += 1
                removed += 1
            elif flag == b"+":
                output.append(content)
                added += 1
            else:
                raise ValueError("Expected zero-context patch")
        if removed != count or added != int(new_count or b"1"):
            raise ValueError("Hunk line counts do not match")
    if seen != set(selected):
        raise ValueError("Unknown or stale hunk ID")
    output.extend(source[cursor:])
    result = b"".join(output)
    if len(result) > _MAX_BYTES:
        raise ValueError("Selected blob exceeds budget")
    return result, mode
