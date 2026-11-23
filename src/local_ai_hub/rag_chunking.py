from __future__ import annotations

import bisect
from functools import lru_cache
import hashlib
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Any

from .json_utils import dumps as json_dumps
from .rag_constants import (
    _REGEX_AST_BUDGET_SECONDS,
    _REGEX_AST_MAX_BLOCK_DEPTH,
    _REGEX_AST_MAX_BLOCKS,
    _REGEX_AST_MAX_SOURCE_CHARS,
    _RUST_LIFETIME_RE,
)

def _check_rag_publish_budget(*, started_at: float, stage: str, budget_seconds: float) -> None:
    elapsed_seconds = time.monotonic() - started_at
    if elapsed_seconds > budget_seconds:
        raise TimeoutError(
            "SQLite write transaction exceeded its duration budget "
            f"(RAG index publish; stage={stage}; "
            f"elapsed_ms={int(elapsed_seconds * 1000)}; "
            f"budget_ms={int(budget_seconds * 1000)})"
        )



def _reverse_text_order(value: str) -> tuple[int, ...]:
    """Heap key where lexically smaller text has higher semantic rank."""
    return tuple(-ord(char) for char in value) + (1,)


def _canonical_fragment_text(text: str) -> str:
    """Normalize transport-only differences without changing source semantics."""
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


def _fragment_hash(text: str) -> str:
    return hashlib.sha1(
        _canonical_fragment_text(text).encode("utf-8"), usedforsecurity=False
    ).hexdigest()


@lru_cache(maxsize=131_072)
def _simhash_shingle_hash(shingle: str) -> int:
    return int(
        hashlib.md5(shingle.encode("utf-8"), usedforsecurity=False).hexdigest()[:16],
        16,
    )


def _simhash(text: str) -> int:
    """Compute 64-bit SimHash of text based on character 4-grams."""
    try:
        from .native_kernels import is_native_enabled, simhash_text
        if is_native_enabled():
            return simhash_text(text)
    except Exception:
        pass

    clean = re.sub(r"\s+", " ", text.lower().strip())
    if len(clean) < 4:
        shingles = [clean] if clean else []
    else:
        shingles = [clean[i : i + 4] for i in range(len(clean) - 3)]
    if not shingles:
        return 0

    # Start at -N, then add two for each set bit. This is mathematically
    # identical to adding +1/-1 for every bit, without 64 Python bit tests
    # per shingle.
    v = [-len(shingles)] * 64
    for s in shingles:
        h = _simhash_shingle_hash(s)
        while h:
            lsb = h & -h
            v[lsb.bit_length() - 1] += 2
            h ^= lsb
    fp = 0
    for i in range(64):
        if v[i] > 0:
            fp |= (1 << i)
    return fp


def _python_ast_chunks(text: str, size: int | Any = 4500, overlap: int | Any = 450) -> list[str]:
    from .rag import RAGStore

    store = RAGStore.__new__(RAGStore)
    sz = size if isinstance(size, int) else 4500
    ov = overlap if isinstance(overlap, int) else 450
    return store._python_ast_chunks(text, sz, ov)


def _regex_ast_chunks(text: str, language: str, size: int = 4500) -> list[str]:
    """Conservatively split brace languages without cutting balanced code blocks.

    This is lexical grouping, not parsing: each outermost brace block stays whole,
    including oversized classes or functions. Ambiguous, malformed, or over-budget
    input is kept as one complete chunk rather than split at an unsafe boundary.
    """
    if language not in {"typescript", "javascript", "c_sharp", "go", "rust", "java", "cpp", "c", "php"}:
        return []
    if len(text) > _REGEX_AST_MAX_SOURCE_CHARS or size < 1:
        return [text] if text.strip() else []

    deadline = time.monotonic() + _REGEX_AST_BUDGET_SECONDS
    spans: list[tuple[int, int]] = []
    safe_newlines: list[int] = []
    braces: list[int] = []
    segment_start = 0
    index = 0
    text_length = len(text)

    def skip_escaped_quote(start: int, quote: str) -> tuple[int, bool]:
        cursor = start + 1
        while cursor < text_length:
            if cursor % 8192 == 0 and time.monotonic() >= deadline:
                return text_length, False
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == quote:
                return cursor + 1, True
            cursor += 1
        return text_length, False

    def skip_verbatim_quote(quote_index: int) -> tuple[int, bool]:
        cursor = quote_index + 1
        while cursor < text_length:
            if cursor % 8192 == 0 and time.monotonic() >= deadline:
                return text_length, False
            if text[cursor] == '"':
                if cursor + 1 < text_length and text[cursor + 1] == '"':
                    cursor += 2
                    continue
                return cursor + 1, True
            cursor += 1
        return text_length, False

    while index < text_length:
        if index % 8192 == 0 and time.monotonic() >= deadline:
            return [text] if text.strip() else []

        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            if newline >= 0:
                safe_newlines.append(newline + 1)
            index = text_length if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            cursor = index + 2
            depth = 1
            while cursor < text_length and depth:
                if cursor % 8192 == 0 and time.monotonic() >= deadline:
                    return [text] if text.strip() else []
                if text.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif text.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            if depth:
                return [text] if text.strip() else []
            index = cursor
            continue

        if language == "c_sharp" and text[index] in "$@":
            if re.match(r"(?:\$+@?|@\$+)\"", text[index:]):
                # Interpolation expressions may contain quoted strings and
                # nested braces; this scanner cannot prove their boundaries.
                return [text] if text.strip() else []

        if language == "c_sharp" and (text.startswith('@"', index)
                or text.startswith('$@"', index) or text.startswith('@$"', index)):
            quote_index = index + 1 if text.startswith('@"', index) else index + 2
            index, closed = skip_verbatim_quote(quote_index)
            if not closed:
                return [text] if text.strip() else []
            continue

        raw_prefix = None
        if language == "rust":
            if text.startswith("br", index):
                raw_prefix = index + 2
            elif text[index] == "r":
                raw_prefix = index + 1
        if raw_prefix is not None:
            hash_end = raw_prefix
            while hash_end < text_length and text[hash_end] == "#":
                if hash_end % 8192 == 0 and time.monotonic() >= deadline:
                    return [text] if text.strip() else []
                hash_end += 1
            if hash_end < text_length and text[hash_end] == '"':
                terminator = '"' + text[raw_prefix:hash_end]
                close_at = text.find(terminator, hash_end + 1)
                if close_at < 0:
                    return [text] if text.strip() else []
                index = close_at + len(terminator)
                continue

        if language == "c_sharp" and text[index] == '"':
            quote_end = index
            while quote_end < text_length and text[quote_end] == '"':
                if quote_end % 8192 == 0 and time.monotonic() >= deadline:
                    return [text] if text.strip() else []
                quote_end += 1
            delimiter_size = quote_end - index
            if delimiter_size >= 3:
                delimiter = '"' * delimiter_size
                close_at = text.find(delimiter, quote_end)
                if close_at < 0:
                    return [text] if text.strip() else []
                index = close_at + delimiter_size
                continue

        if language == "rust" and text[index] == "'":
            lifetime = _RUST_LIFETIME_RE.match(text, index)
            if lifetime is not None:
                # ``match(text, index)`` returns absolute match offsets.
                after_lifetime = lifetime.end()
                if after_lifetime >= text_length or text[after_lifetime] != "'":
                    index = after_lifetime
                    continue

        if text[index] in "'\"`":
            if language == "typescript" and text[index] == "`":
                first_close = text.find("`", index + 1)
                interpolation = text.find("${", index + 1, first_close if first_close >= 0 else text_length)
                if interpolation >= 0:
                    expression_close = text.find("}", interpolation + 2, first_close if first_close >= 0 else text_length)
                    if expression_close < 0:
                        # Nested templates inside ${...} need a real template
                        # lexer; keep the source whole rather than ending early.
                        return [text] if text.strip() else []
            index, closed = skip_escaped_quote(index, text[index])
            if not closed:
                return [text] if text.strip() else []
            continue

        if language == "typescript" and text[index] == "/":
            prefix = text[max(0, index - 32):index].rstrip()
            previous = prefix[-1:] if prefix else ""
            starts_expression = (
                not prefix
                or previous in "([{=,:;!?&|+-*%^~>"
                or re.search(r"\b(?:return|throw|case|yield|await|else|do)\s*$", prefix) is not None
            )
            if starts_expression:
                cursor = index + 1
                in_character_class = False
                closed = False
                while cursor < text_length and text[cursor] not in "\r\n":
                    if cursor % 8192 == 0 and time.monotonic() >= deadline:
                        return [text] if text.strip() else []
                    if text[cursor] == "\\":
                        cursor += 2
                        continue
                    if text[cursor] == "[":
                        in_character_class = True
                    elif text[cursor] == "]":
                        in_character_class = False
                    elif text[cursor] == "/" and not in_character_class:
                        cursor += 1
                        while cursor < text_length and text[cursor].isalpha():
                            cursor += 1
                        closed = True
                        break
                    cursor += 1
                if closed:
                    index = cursor
                    continue
                return [text] if text.strip() else []

        if text[index] == "\n":
            safe_newlines.append(index + 1)

        if text[index] == "{":
            if language == "typescript" and not braces:
                # A typed function can contain a structural return type before
                # its body. Brace balancing alone cannot distinguish that type
                # from the body, so retain this source as one safe unit.
                header = text[segment_start:index]
                suffix = header[-512:]
                if len(header) > 512 and re.search(r"\)[ \t]*:[ \t]*$", suffix):
                    return [text] if text.strip() else []
                if re.search(r"\bfunction\b[^;{}]*\)[ \t]*:[ \t]*$", suffix):
                    return [text] if text.strip() else []
            if len(braces) >= _REGEX_AST_MAX_BLOCK_DEPTH:
                return [text] if text.strip() else []
            if not braces:
                braces.append(segment_start)
            else:
                braces.append(index)
            index += 1
            continue
        if text[index] == "}":
            if not braces:
                return [text] if text.strip() else []
            braces.pop()
            index += 1
            if not braces:
                if len(spans) >= _REGEX_AST_MAX_BLOCKS:
                    return [text] if text.strip() else []
                cursor = index
                while cursor < text_length and text[cursor] in " \t":
                    cursor += 1
                if cursor < text_length and text[cursor] == "\r":
                    cursor += 1
                if cursor < text_length and text[cursor] == "\n":
                    cursor += 1
                    index = cursor
                    safe_newlines.append(cursor)
                spans.append((segment_start, index))
                segment_start = index
            continue
        index += 1

    if braces:
        return [text] if text.strip() else []
    if not spans:
        return [text] if text.strip() else []
    if len(spans) + int(segment_start < text_length) > _REGEX_AST_MAX_BLOCKS:
        return [text] if text.strip() else []

    chunks: list[str] = []

    def split_at_safe_newlines(start: int, end: int) -> list[str]:
        parts: list[str] = []
        cursor = start
        while end - cursor > size:
            break_index = bisect.bisect_right(safe_newlines, cursor + size) - 1
            if break_index < 0 or safe_newlines[break_index] <= cursor:
                break_index = bisect.bisect_right(safe_newlines, cursor)
                if break_index >= len(safe_newlines) or safe_newlines[break_index] >= end:
                    break
            boundary = safe_newlines[break_index]
            parts.append(text[cursor:boundary])
            cursor = boundary
        if cursor < end:
            parts.append(text[cursor:end])
        return parts

    pending_parts: list[str] = []
    pending_chars = 0
    for start, end in spans:
        if time.monotonic() >= deadline:
            return [text] if text.strip() else []
        block = text[start:end]
        if pending_parts and pending_chars + len(block) > size:
            chunks.append("".join(pending_parts))
            pending_parts = []
            pending_chars = 0
        if len(block) > size:
            if pending_parts:
                chunks.append("".join(pending_parts))
                pending_parts = []
                pending_chars = 0
            chunks.extend(split_at_safe_newlines(start, end))
        else:
            pending_parts.append(block)
            pending_chars += len(block)
    # Unbraced declarations/expressions in the tail have no proven safe split.
    # Keep the entire tail together even when it exceeds the requested size.
    if segment_start < text_length:
        tail = text[segment_start:]
        if pending_parts and pending_chars + len(tail) <= size:
            pending_parts.append(tail)
            pending_chars += len(tail)
        else:
            if pending_parts:
                chunks.append("".join(pending_parts))
            pending_parts = [tail]
    if time.monotonic() >= deadline:
        return [text] if text.strip() else []
    if pending_parts:
        chunks.append("".join(pending_parts))
    return chunks


def _serialize_embedding(vector: Any) -> bytes | str | None:
    try:
        values = [float(value) for value in vector]
        if values and not any(value != 0.0 for value in values):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    if not values or not all(math.isfinite(value) for value in values) or not any(value != 0.0 for value in values):
        return None
    try:
        import numpy as np
        packed = np.asarray(values, dtype=np.float32)
        if not np.isfinite(packed).all() or float(np.linalg.norm(packed)) <= 1e-9:
            return None
        return sqlite3.Binary(packed.tobytes())
    except ImportError:
        return json_dumps(values, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError):
        return None


def _read_bounded_file(
    path: Path, max_bytes: int, *, root: Path | None = None,
) -> bytes | None:
    """Bounded no-follow source read, rejecting path/descriptor identity races.

    Reject symlinks and Windows reparse points before reading, and compare
    opened descriptor identity with the path both before and after the read.
    The root (when supplied) constrains every traversed path component.
    """
    limit = max(0, int(max_bytes))
    try:
        def safe_components() -> bool:
            if root is None:
                return True
            relative = path.relative_to(root)
            if not relative.parts or ".." in relative.parts:
                return False
            current = root
            for part in relative.parts:
                current = current / part
                component_stat = current.stat(follow_symlinks=False)
                if (
                    stat.S_ISLNK(component_stat.st_mode)
                    or bool(getattr(component_stat, "st_file_attributes", 0) & 0x400)
                ):
                    return False
            return True

        if not safe_components():
            return None
        before = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or bool(getattr(before, "st_file_attributes", 0) & 0x400)
        ):
            return None
        flags = (
            os.O_RDONLY | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            raw = source.read(limit + 1)
            finished = os.fstat(source.fileno())
        after = path.stat(follow_symlinks=False)
        identity = lambda info: (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or len(raw) > limit
            or identity(before) != identity(opened)
            or identity(opened) != identity(finished)
            or identity(finished) != identity(after)
            or not safe_components()
        ):
            return None
        return raw
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def _rag_source_still_current(
    root: Path, rel: str, *, expected_hash: str, expected_size: int,
    expected_mtime_ns: int, max_bytes: int,
) -> bool:
    """Recheck actual bytes and identity after embedding, before publishing.

    A workspace lock does not prevent the editor from rewriting a file.
    This deliberately rejects same-size/mtime rollbacks and symlink swaps;
    it is a bounded last-moment check, not an immutable filesystem snapshot.
    """
    if not rel or not isinstance(expected_hash, str):
        return False
    relative = Path(rel.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return False
    candidate = root
    try:
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                return False
        if candidate.resolve(strict=True) != candidate:
            return False
        before = candidate.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or (
            before.st_size != expected_size or before.st_mtime_ns != expected_mtime_ns
        ):
            return False
        flags = (
            os.O_RDONLY | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        fd = os.open(candidate, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(max_bytes + 1)
            closed = os.fstat(stream.fileno())
        after = candidate.stat(follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        return bool(
            len(raw) <= max_bytes
            and identity(before) == identity(opened) == identity(closed) == identity(after)
            and not candidate.is_symlink()
            and candidate.resolve(strict=True) == candidate
            and hashlib.sha1(raw, usedforsecurity=False).hexdigest() == expected_hash
        )
    except (OSError, RuntimeError, ValueError):
        return False

