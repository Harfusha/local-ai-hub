"""Compute a stage-zero index tree object ID without writing Git objects."""
from __future__ import annotations

import hashlib
import re
from typing import Any

_MODES = {b"100644", b"100755", b"120000", b"160000"}
_MAX_ENTRIES = 100000
_MAX_DEPTH = 128


def index_tree_oid(raw: bytes, head: str) -> str | None:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        return None
    algorithm = "sha1" if len(head) == 40 else "sha256"
    if raw and not raw.endswith(b"\0"):
        return None
    records = raw.split(b"\0")[:-1]
    if len(records) > _MAX_ENTRIES:
        return None
    root: dict[bytes, Any] = {}
    for record in records:
        try:
            meta, name = record.split(b"\t", 1)
            mode, oid, stage = meta.split(b" ")
            if mode not in _MODES or stage != b"0" or len(oid) != len(head) or not re.fullmatch(rb"[0-9a-f]+", oid):
                return None
            if not oid.strip(b"0"):
                return None
            parts = name.split(b"/")
            if len(parts) > _MAX_DEPTH or any(p in {b"", b".", b"..", b".git"} for p in parts):
                return None
            tree = root
            for part in parts[:-1]:
                child = tree.setdefault(part, {})
                if not isinstance(child, dict):
                    return None
                tree = child
            if parts[-1] in tree:
                return None
            tree[parts[-1]] = (mode, bytes.fromhex(oid.decode("ascii")))
        except (ValueError, UnicodeError):
            return None

    def digest(tree: dict[bytes, Any]) -> bytes:
        # Git compares directory names as if suffixed by '/'.
        entries = []
        for name, item in sorted(tree.items(), key=lambda pair: pair[0] + (b"/" if isinstance(pair[1], dict) else b"")):
            if isinstance(item, dict):
                mode, oid = b"40000", digest(item)
            else:
                mode, oid = item
            entries.append(mode + b" " + name + b"\0" + oid)
        body = b"".join(entries)
        return hashlib.new(algorithm, b"tree " + str(len(body)).encode("ascii") + b"\0" + body).digest()

    return digest(root).hex()
