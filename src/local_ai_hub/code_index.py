from __future__ import annotations

from .json_utils import dumps as json_dumps

import ast
import copy
import errno
import json
import logging
import os
import re
import sqlite3
import threading
import time
import weakref
from contextlib import closing, contextmanager
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from . import __version__

_PARSER_ANALYZER_VERSION = f"{__version__}:call-edges-v16-multiline-arrow-scope"
from .cache import MemoryLRUCache, stable_hash
from .normalizer import tokenize_query_terms
from .process_utils import canonical_root
from .repo_tools import FileTooLargeError, is_root_archive_path
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    initialize_wal,
    is_busy_error,
    quick_sanity_check,
    sqlite_batches,
    SQLiteChangeObserver,
)
from .sqlite_counts import global_row_counts, initialize_row_counts

_CODE_INDEX_INIT_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_CODE_INDEX_INIT_LOCKS_GUARD = threading.Lock()


@contextmanager
def _code_index_initialization_lock(db_path: Path) -> Iterator[None]:
    """Serialize schema creation and corrupt-cache recovery across processes."""
    lock_path = db_path.with_name(db_path.name + ".init.lock")
    lock_key = os.path.normcase(str(lock_path.resolve()))
    with _CODE_INDEX_INIT_LOCKS_GUARD:
        thread_lock = _CODE_INDEX_INIT_LOCKS.get(lock_key)
        if thread_lock is None:
            thread_lock = threading.RLock()
            _CODE_INDEX_INIT_LOCKS[lock_key] = thread_lock

    with thread_lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()

            deadline = time.monotonic() + 30.0
            locked = False
            if os.name == "nt":
                import msvcrt

                while not locked:
                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                    except OSError as exc:
                        if (
                            getattr(exc, "winerror", None) not in {33, 36}
                            and exc.errno not in {errno.EACCES, errno.EDEADLK, errno.EAGAIN}
                        ):
                            raise
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out waiting for code-index initialization lock") from exc
                        time.sleep(0.05)
            else:
                import fcntl

                while not locked:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except BlockingIOError as exc:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("timed out waiting for code-index initialization lock") from exc
                        time.sleep(0.05)

            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _root_archive_path_sql(path_expression: str = "path") -> str:
    # Apply the inventory policy to legacy rows before SQL LIMIT as well.
    # One predicate keeps scanning and persisted-index retrieval in agreement.
    return f"NOT hub_root_archive_path({path_expression})"


MAX_IMPACT_DEPENDENTS = 100_000

IDENT = re.compile(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b")
GENERIC_DEF = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|async|export|abstract|virtual|override|sealed|readonly)\s+)*(class|interface|trait|enum|struct|record|function|func|fn|def|type)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w./@-]+)|(?:use|require_once|include_once|require|include|using)\b\s*\(?\s*[\'\"]?([^\'\";]+)[\'\"]?\s*\)?)")
ARROW_DEF = re.compile(r"^\s*(?:(?:export|default|public|private|protected|internal|static|readonly|const|let|var)\s+)*([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>")
INLINE_ARROW_DEF = re.compile(r"(?<![\w$])(?:(?:export|default|public|private|protected|internal|static|readonly|const|let|var)\s+)*([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>")
GO_METHOD = re.compile(r"^\s*func\s*(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
TYPED_METHOD = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|async|virtual|override|abstract|sealed|synchronized|native)\s+)*(?:[A-Za-z_$][\w.$<>,?\[\]]*\s+)+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^;{}]*)\)\s*(?:\{|=>|throws\b|where\b)")
JS_METHOD = re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^)]*)\)\s*\{")
TRAILING_CALL_AFTER_CLOSE = re.compile(r"}\s*;?\s*(?:[A-Za-z_$][\w$]*\s*\??\.\s*)*[A-Za-z_$][A-Za-z0-9_$]*\s*\(")
_CONTROL_NAMES = {"if","for","while","switch","catch","return","new","throw","using","lock","foreach","typeof","sizeof","default"}


def _javascript_regex_end(chars: list[str], start: int) -> int | None:
    in_character_class = False
    escaped = False
    i = start + 1
    while i < len(chars) and chars[i] not in "\r\n":
        char = chars[i]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            in_character_class = True
        elif char == "]":
            in_character_class = False
        elif char == "/" and not in_character_class:
            i += 1
            while i < len(chars) and (chars[i].isalpha() or chars[i].isdigit()):
                i += 1
            return i
        i += 1
    return None


def _javascript_regex_can_start(chars: list[str], offset: int) -> bool:
    previous = offset - 1
    while previous >= 0 and chars[previous].isspace():
        previous -= 1
    if previous < 0:
        return True
    if chars[previous] in "=([{,:;!&|?~^*%+-":
        return True
    if chars[previous] == ")":
        depth = 0
        cursor = previous
        while cursor >= 0:
            if chars[cursor] == ")":
                depth += 1
            elif chars[cursor] == "(":
                depth -= 1
                if depth == 0:
                    prefix = "".join(chars[max(0, cursor - 16):cursor])
                    if re.search(r"(?<![\w$.])(?:if|while|for|with)\s*$", prefix):
                        return True
                    break
            cursor -= 1
    if chars[previous] == "}":
        depth = 0
        cursor = previous
        while cursor >= 0:
            if chars[cursor] == "}":
                depth += 1
            elif chars[cursor] == "{":
                depth -= 1
                if depth == 0:
                    prefix = "".join(chars[max(0, cursor - 80):cursor])
                    if re.search(r"(?<![\w$.])(?:if|while|for|with|switch|catch)\s*\([^{}]*\)\s*$", prefix):
                        return True
                    if re.search(r"\b(?:else|do|finally)\s*$", prefix):
                        return True
                    segment_start = cursor - 1
                    while segment_start >= 0 and chars[segment_start] not in ";{}":
                        segment_start -= 1
                    prior_source = "".join(chars[segment_start + 1:cursor])
                    declaration_patterns = (
                        r"(?:^|[\r\n])\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                        r"function\s*\*?\s*[A-Za-z_$][A-Za-z0-9_$]*\s*\([^{}]*\)\s*$",
                        r"(?:^|[\r\n])\s*(?:export\s+)?(?:default\s+)?class\s+"
                        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\s+extends\b[^{}]*)?\s*$",
                    )
                    for pattern in declaration_patterns:
                        declaration = re.search(pattern, prior_source)
                        if declaration is None:
                            continue
                        before_declaration = prior_source[:declaration.start()].rstrip()
                        if not before_declaration or before_declaration[-1] not in "=([{,:!&|?~^*%+-<>/.":
                            return True
                    break
            cursor -= 1
    if previous > 0 and chars[previous - 1:previous + 1] == ["=", ">"]:
        return True
    prefix = "".join(chars[max(0, offset - 24):offset])
    return bool(re.search(r"(?<![\w$.])(?:return|case|throw|delete|void|typeof|instanceof|in|of|yield|await|else|do)\s*$", prefix))


def _quoted_literal_end(text: str, start: int, limit: int) -> int | None:
    quote_at = start
    verbatim = False
    if text.startswith(("$@\"", "@$\""), start):
        quote_at = start + 2
        verbatim = True
    elif text.startswith('@"', start):
        quote_at = start + 1
        verbatim = True
    elif text[start] == "$" and start + 1 < limit and text[start + 1] in "\"'`":
        quote_at = start + 1
    elif text[start] not in "\"'`":
        return None

    quote = text[quote_at]
    quote_run = quote_at
    while quote_run < limit and text[quote_run] == quote:
        quote_run += 1
    delimiter_size = quote_run - quote_at if quote in "\"'" and quote_run - quote_at >= 3 else 1
    cursor = quote_at + delimiter_size
    while cursor < limit:
        if delimiter_size > 1 and text[cursor] == quote:
            run_end = cursor + 1
            while run_end < limit and text[run_end] == quote:
                run_end += 1
            if run_end - cursor >= delimiter_size:
                return cursor + delimiter_size
            cursor = run_end
            continue
        if delimiter_size == 1 and text[cursor] == quote:
            if verbatim and quote == '"' and cursor + 1 < limit and text[cursor + 1] == quote:
                cursor += 2
                continue
            return cursor + 1
        if not verbatim and text[cursor] == "\\":
            cursor += 2
        else:
            cursor += 1
    return limit


def _find_interpolation_close(
    text: str,
    chars: list[str],
    start: int,
    limit: int,
    language: str,
    closing_braces: int = 1,
) -> int | None:
    brace_depth = 0
    cursor = start
    while cursor < limit:
        if text.startswith("//", cursor):
            newline = text.find("\n", cursor + 2, limit)
            cursor = limit if newline < 0 else newline + 1
            continue
        if text.startswith("/*", cursor):
            close = text.find("*/", cursor + 2, limit)
            cursor = limit if close < 0 else close + 2
            continue
        literal_end = _quoted_literal_end(text, cursor, limit)
        if literal_end is not None:
            cursor = max(cursor + 1, literal_end)
            continue
        if (
            language in {"javascript", "typescript", "tsx"}
            and text[cursor] == "/"
            and _javascript_regex_can_start(chars, cursor)
        ):
            regex_end = _javascript_regex_end(chars, cursor)
            if regex_end is not None:
                cursor = min(limit, regex_end)
                continue
        if text[cursor] == "{":
            brace_depth += 1
        elif text[cursor] == "}":
            if brace_depth:
                brace_depth -= 1
            else:
                run_end = cursor + 1
                while run_end < limit and text[run_end] == "}":
                    run_end += 1
                if run_end - cursor >= closing_braces:
                    return cursor
                cursor = run_end
                continue
        cursor += 1
    return None


def _interpolated_code_spans(
    text: str,
    start: int,
    end: int,
    language: str,
    mode: str,
    chars: list[str],
    *,
    verbatim: bool = False,
    brace_count: int = 1,
    raw_string: bool = False,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    if mode == "javascript":
        while cursor < end:
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text.startswith("${", cursor):
                close = _find_interpolation_close(text, chars, cursor + 2, end, language)
                if close is not None:
                    spans.append((cursor, close + 1))
                    cursor = close + 1
                    continue
            cursor += 1
        return spans

    while cursor < end:
        if not raw_string and not verbatim and text[cursor] == "\\":
            cursor += 2
            continue
        if not raw_string and brace_count == 1 and text.startswith("{{", cursor):
            cursor += 2
            continue
        if text[cursor] == "{" and text.startswith("{" * brace_count, cursor):
            close = _find_interpolation_close(
                text, chars, cursor + brace_count, end, language, closing_braces=brace_count
            )
            if close is not None:
                span_end = close + brace_count
                spans.append((cursor, span_end))
                cursor = span_end
                continue
        if not raw_string and brace_count == 1 and text.startswith("}}", cursor):
            cursor += 2
            continue
        cursor += 1
    return spans


def _interpolated_literal_end(
    text: str,
    chars: list[str],
    body_start: int,
    limit: int,
    language: str,
    mode: str,
    quote: str,
    *,
    verbatim: bool = False,
    delimiter_size: int = 1,
    brace_count: int = 1,
    raw_string: bool = False,
) -> int:
    cursor = body_start
    while cursor < limit:
        if mode == "javascript":
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text.startswith("${", cursor):
                close = _find_interpolation_close(text, chars, cursor + 2, limit, language)
                if close is None:
                    return limit
                cursor = close + 1
                continue
        else:
            if not raw_string and not verbatim and text[cursor] == "\\":
                cursor += 2
                continue
            if not raw_string and brace_count == 1 and (
                text.startswith("{{", cursor) or text.startswith("}}", cursor)
            ):
                cursor += 2
                continue
            if text[cursor] == "{" and text.startswith("{" * brace_count, cursor):
                close = _find_interpolation_close(
                    text, chars, cursor + brace_count, limit, language, closing_braces=brace_count
                )
                if close is None:
                    return limit
                cursor = close + brace_count
                continue
        if raw_string and text.startswith(quote * delimiter_size, cursor):
            return cursor + delimiter_size
        if not raw_string and text[cursor] == quote:
            if verbatim and quote == '"' and cursor + 1 < limit and text[cursor + 1] == quote:
                cursor += 2
                continue
            return cursor + 1
        cursor += 1
    return limit


_QUERY_CACHE_GENERATIONS: dict[str, int] = {}
_QUERY_CACHE_GENERATION_LOCK = threading.Lock()


def _query_cache_generation(database_key: str) -> int:
    with _QUERY_CACHE_GENERATION_LOCK:
        return _QUERY_CACHE_GENERATIONS.get(database_key, 0)


def _advance_query_cache_generation(database_key: str) -> None:
    with _QUERY_CACHE_GENERATION_LOCK:
        _QUERY_CACHE_GENERATIONS[database_key] = _QUERY_CACHE_GENERATIONS.get(database_key, 0) + 1


def _arrow_body_column(symbol: dict[str, Any], declaration_line: str) -> int | None:
    name = str(symbol.get("name") or "")
    if not name:
        return None
    name_match = re.search(rf"\b{re.escape(name)}\b", declaration_line)
    if name_match is None:
        return None
    arrow = declaration_line.find("=>", name_match.end())
    if arrow < 0:
        return None
    declaration = re.search(rf"\b{re.escape(name)}(?:\s*<[^(){{}};]*>)?\s*\(", declaration_line[name_match.start():])
    if declaration is None:
        return arrow
    open_paren = name_match.start() + declaration.end() - 1
    depth = 1
    cursor = open_paren + 1
    while cursor < len(declaration_line) and depth:
        if declaration_line[cursor] == "(":
            depth += 1
        elif declaration_line[cursor] == ")":
            depth -= 1
        cursor += 1
    if depth or arrow < cursor:
        return None
    body_open = declaration_line.find("{", cursor)
    if body_open >= 0 and body_open < arrow:
        return None
    return arrow


def _callable_line_body_bounds(
    symbol: dict[str, Any], source_line: str, line_number: int,
) -> tuple[int, int] | None:
    name = str(symbol.get("name") or "")
    if not name:
        return None
    try:
        start_line = int(symbol.get("line", 0))
    except (TypeError, ValueError, OverflowError):
        return None
    signature = str(symbol.get("signature") or "")
    signature_arrow = _arrow_body_column(symbol, signature)
    if line_number > start_line and signature_arrow is not None:
        arrow_tail = signature[signature_arrow + 2:].strip()
        try:
            end_line = int(symbol.get("end_line", start_line))
        except (TypeError, ValueError, OverflowError):
            end_line = start_line
        if not arrow_tail.startswith("{") and line_number <= end_line:
            body_start = len(source_line) - len(source_line.lstrip())
            if body_start < len(source_line):
                return _expression_body_bounds(source_line, body_start)
    if line_number == start_line + 1 and signature_arrow is not None:
        arrow_tail = signature[signature_arrow + 2:].strip()
        if not arrow_tail:
            body_start = len(source_line) - len(source_line.lstrip())
            if body_start >= len(source_line):
                return None
            if source_line[body_start] == "{":
                depth = 0
                for pos in range(body_start, len(source_line)):
                    if source_line[pos] == "{":
                        depth += 1
                    elif source_line[pos] == "}":
                        depth -= 1
                        if depth == 0:
                            return body_start + 1, pos
                return body_start + 1, len(source_line)
            return _expression_body_bounds(source_line, body_start)

    name_match = re.search(rf"\b{re.escape(name)}\b", source_line)
    if name_match is None:
        return None
    arrow = _arrow_body_column(symbol, source_line)
    if arrow is not None:
        body_start = arrow + 2
        while body_start < len(source_line) and source_line[body_start].isspace():
            body_start += 1
    else:
        declaration = re.search(rf"\b{re.escape(name)}\s*\(", source_line[name_match.start():])
        if declaration is None:
            return None
        open_paren = name_match.start() + declaration.end() - 1
        paren_depth = 1
        cursor = open_paren + 1
        while cursor < len(source_line) and paren_depth:
            if source_line[cursor] == "(":
                paren_depth += 1
            elif source_line[cursor] == ")":
                paren_depth -= 1
            cursor += 1
        if paren_depth:
            return None
        body_start = source_line.find("{", cursor)
        if body_start < 0:
            return None
        body_start += 1

    if body_start >= len(source_line):
        return None

    if source_line[body_start - 1] == "{" and arrow is not None:
        brace_start = body_start - 1
        depth = 0
        for pos in range(brace_start, len(source_line)):
            if source_line[pos] == "{":
                depth += 1
            elif source_line[pos] == "}":
                depth -= 1
                if depth == 0:
                    return body_start, pos
        return body_start, len(source_line)

    if arrow is None:
        brace_start = body_start - 1
        depth = 0
        for pos in range(brace_start, len(source_line)):
            if source_line[pos] == "{":
                depth += 1
            elif source_line[pos] == "}":
                depth -= 1
                if depth == 0:
                    return body_start, pos
        return body_start, len(source_line)

    return _expression_body_bounds(source_line, body_start)


def _expression_body_bounds(source_line: str, body_start: int) -> tuple[int, int]:
    parens = brackets = braces = 0
    for pos in range(body_start, len(source_line)):
        char = source_line[pos]
        if char == "(":
            parens += 1
        elif char == ")":
            parens = max(0, parens - 1)
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets = max(0, brackets - 1)
        elif char == "{":
            braces += 1
        elif char == "}":
            if braces == 0:
                return body_start, pos
            braces -= 1
        elif char == ";" and parens == brackets == braces == 0:
            return body_start, pos
    return body_start, len(source_line)


def _arrow_expression_end_line(lines: list[str], start_line: int, arrow_column: int) -> int:
    line_index = start_line
    column = arrow_column + 2
    while line_index < len(lines):
        while column < len(lines[line_index]) and lines[line_index][column].isspace():
            column += 1
        if column < len(lines[line_index]):
            break
        line_index += 1
        column = 0
    if line_index >= len(lines):
        return min(start_line, len(lines) - 1)

    first_body_line = line_index
    parens = brackets = braces = 0
    max_line = min(len(lines), first_body_line + 2500)
    for current_line in range(first_body_line, max_line):
        if current_line > first_body_line and parens == brackets == braces == 0:
            previous = lines[current_line - 1].rstrip()
            following = lines[current_line].lstrip()
            continuations = (".", "?.", "(", "[", ",", "+", "-", "*", "/", "%", "&&", "||", "??", "?", ":")
            if not following or not previous or not (
                previous.endswith(continuations) or following.startswith(continuations)
            ):
                return current_line - 1
        current_column = column if current_line == first_body_line else 0
        line = lines[current_line]
        while current_column < len(line):
            char = line[current_column]
            if char == ";" and parens == brackets == braces == 0:
                return current_line
            if char == "(":
                parens += 1
            elif char == ")":
                parens = max(0, parens - 1)
            elif char == "[":
                brackets += 1
            elif char == "]":
                brackets = max(0, brackets - 1)
            elif char == "{":
                braces += 1
            elif char == "}":
                if braces == 0:
                    return current_line
                braces -= 1
            current_column += 1
    return max(first_body_line, max_line - 1)


def _arrow_body_close_position(
    lines: list[str], start_line: int, arrow_column: int,
) -> tuple[int, int] | None:
    line_index = start_line
    column = arrow_column + 2
    while line_index < len(lines):
        while column < len(lines[line_index]) and lines[line_index][column].isspace():
            column += 1
        if column < len(lines[line_index]):
            break
        line_index += 1
        column = 0
    if line_index >= len(lines) or lines[line_index][column] != "{":
        return None

    return _matching_brace_close_position(lines, line_index, column)


def _matching_brace_close_position(
    lines: list[str], start_line: int, open_column: int,
) -> tuple[int, int] | None:
    depth = 0
    for current_line in range(start_line, len(lines)):
        current_column = open_column if current_line == start_line else 0
        while current_column < len(lines[current_line]):
            char = lines[current_line][current_column]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return current_line + 1, current_column
            current_column += 1
    return None


def _callable_block_close_position(
    lines: list[str], symbol: dict[str, Any],
) -> tuple[int, int] | None:
    name = str(symbol.get("name") or "")
    try:
        start_line = int(symbol.get("line", 0)) - 1
    except (TypeError, ValueError, OverflowError):
        return None
    if not name or start_line < 0 or start_line >= len(lines):
        return None

    line = lines[start_line]
    name_match = re.search(rf"\b{re.escape(name)}\b", line)
    if name_match is None:
        return None
    declaration = re.search(rf"\b{re.escape(name)}(?:\s*<[^(){{}};]*>)?\s*\(", line[name_match.start():])
    arrow_column = _arrow_body_column(symbol, line)
    if declaration is None:
        if arrow_column is not None:
            return _arrow_body_close_position(lines, start_line, arrow_column)
        return None
    open_paren_line = start_line
    open_paren_column = name_match.start() + declaration.end() - 1
    depth = 1
    current_line = open_paren_line
    current_column = open_paren_column + 1
    while current_line < len(lines) and depth:
        while current_column < len(lines[current_line]) and depth:
            char = lines[current_line][current_column]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            current_column += 1
        if depth:
            current_line += 1
            current_column = 0
    if depth:
        return None

    if arrow_column is not None:
        return _arrow_body_close_position(lines, start_line, arrow_column)

    end_line = int(symbol.get("end_line", start_line + 1))
    limit = min(len(lines), max(start_line + 1, end_line) + 1)
    while current_line < limit:
        line_text = lines[current_line]
        while current_column < len(line_text):
            char = line_text[current_column]
            if char == ";" or line_text.startswith("=>", current_column):
                return None
            if char == "{":
                return _matching_brace_close_position(lines, current_line, current_column)
            current_column += 1
        current_line += 1
        current_column = 0
    return None


def _callable_needs_close_position(lines: list[str], symbol: dict[str, Any]) -> bool:
    try:
        start_line = int(symbol.get("line", 0)) - 1
        end_line = int(symbol.get("end_line", start_line + 1)) - 1
    except (TypeError, ValueError, OverflowError):
        return False
    if start_line < 0 or start_line >= len(lines):
        return False

    declaration_line = lines[start_line]
    if "=>" in declaration_line:
        arrow_column = _arrow_body_column(symbol, declaration_line)
        if arrow_column is not None:
            body = declaration_line[arrow_column + 2:].strip()
            if not body and start_line + 1 < len(lines):
                body = lines[start_line + 1].strip()
            if body.startswith("{"):
                return True

    if end_line < 0 or end_line >= len(lines):
        return False
    closing_line = lines[end_line]
    return "}" in closing_line and TRAILING_CALL_AFTER_CLOSE.search(closing_line) is not None


def _call_edge_source(
    symbols: list[dict[str, Any]], line: int, *, column: int | None = None, source_line: str | None = None,
) -> str:
    callers = []
    for symbol in symbols:
        if str(symbol.get("kind", "")).lower() not in {"method", "function", "func", "fn", "def"}:
            continue
        try:
            start_line = int(symbol.get("line", 0))
            end_line = int(symbol.get("end_line", start_line))
        except (TypeError, ValueError, OverflowError):
            continue
        if start_line <= line <= end_line:
            body_span = 1 << 30
            scope_end = (1 << 30, 1 << 30)
            if column is not None:
                close_position = symbol.get("_body_close_position")
                if isinstance(close_position, tuple) and len(close_position) == 2:
                    close_line, close_column = close_position
                    if line > close_line or (line == close_line and column >= close_column):
                        continue
                    scope_end = (int(close_line), int(close_column))
            if column is not None and source_line is not None:
                signature = str(symbol.get("signature") or "")
                body_bounds = None
                if "=>" in signature and _arrow_body_column(symbol, signature) is not None:
                    body_bounds = _callable_line_body_bounds(symbol, source_line, line)
                if body_bounds is not None and not (body_bounds[0] <= column < body_bounds[1]):
                    continue
                if body_bounds is not None:
                    body_span = body_bounds[1] - body_bounds[0]
                    body_end = (line, body_bounds[1])
                    scope_end = min(scope_end, body_end)
            callers.append((start_line, -end_line, -scope_end[0], -scope_end[1], -body_span, symbol))
    if not callers:
        return "<module>"
    symbol = max(callers, key=lambda item: item[:5])[5]
    source = str(symbol.get("name_path") or symbol.get("name") or "<module>")
    return source.replace("\\", "/")


def _edge_endpoint_name(endpoint: str) -> str:
    """Return the searchable terminal name for a qualified edge endpoint."""
    return str(endpoint).replace("\\", "/").rsplit("/", 1)[-1].rsplit("::", 1)[-1]


def _mask_non_code(text: str, language: str, *, mask_literals: bool = True) -> str:
    """Blank comments and literals while preserving source offsets and lines."""
    chars = list(text)
    length = len(chars)
    hash_comments = language in {"php", "yaml"}

    def blank(start: int, end: int) -> None:
        for pos in range(start, min(end, length)):
            if chars[pos] not in "\r\n":
                chars[pos] = " "

    i = 0
    while i < length:
        if chars[i] in "\r\n":
            i += 1
            continue

        if chars[i:i + 2] == ["/", "/"]:
            end = i + 2
            while end < length and chars[end] not in "\r\n":
                end += 1
            blank(i, end)
            i = end
            continue

        if chars[i:i + 2] == ["/", "*"]:
            start = i
            depth = 1
            i += 2
            while i < length and depth:
                if chars[i:i + 2] == ["/", "*"]:
                    depth += 1
                    i += 2
                elif chars[i:i + 2] == ["*", "/"]:
                    depth -= 1
                    i += 2
                else:
                    i += 1
            blank(start, i)
            continue

        if hash_comments and chars[i] == "#" and not (
            language == "php" and i + 1 < length and chars[i + 1] == "["
        ):
            end = i + 1
            while end < length and chars[end] not in "\r\n":
                end += 1
            blank(i, end)
            i = end
            continue

        if (
            language in {"javascript", "typescript", "tsx"}
            and chars[i] == "/"
            and _javascript_regex_can_start(chars, i)
        ):
            regex_end = _javascript_regex_end(chars, i)
            if regex_end is not None:
                if mask_literals:
                    blank(i, regex_end)
                i = regex_end
                continue

        if language == "rust" and chars[i] == "'" and i + 1 < length:
            ident_end = i + 1
            if chars[ident_end] == "_" or chars[ident_end].isalpha():
                ident_end += 1
                while ident_end < length and (chars[ident_end] == "_" or chars[ident_end].isalnum()):
                    ident_end += 1
                if ident_end >= length or chars[ident_end] != "'":
                    i += 1
                    continue

        start = i
        quote_at = i
        raw_terminator = ""
        verbatim = False
        interpolation_mode = ""
        interpolation_braces = 1
        interpolation_raw_string = False

        # Rust raw strings: r#"..."# and br##"..."##.
        raw_base = i + 2 if text.startswith(("br", "cr"), i) else i + 1 if chars[i] == "r" else -1
        if raw_base >= 0:
            hashes_at = raw_base
            while hashes_at < length and chars[hashes_at] == "#":
                hashes_at += 1
            if hashes_at < length and chars[hashes_at] == '"':
                quote_at = hashes_at
                raw_terminator = '"' + "#" * (hashes_at - raw_base)
            else:
                raw_base = -1
        if raw_base < 0 and language == "csharp" and (text.startswith('$@"', i) or text.startswith('@$"', i)):
            quote_at = i + 2
            verbatim = True
            interpolation_mode = "csharp"
        elif raw_base < 0 and language == "csharp" and chars[i] == "$":
            dollars_end = i
            while dollars_end < length and chars[dollars_end] == "$":
                dollars_end += 1
            if dollars_end < length and chars[dollars_end] == '"':
                quote_at = dollars_end
                interpolation_mode = "csharp"
                interpolation_braces = dollars_end - i
                interpolation_raw_string = text.startswith('"""', quote_at)
            else:
                i += 1
                continue
        elif raw_base < 0 and language == "csharp" and text.startswith('@"', i):
            quote_at = i + 1
            verbatim = True
        elif raw_base < 0 and chars[i] == '$' and i + 1 < length and chars[i + 1] in "\"'`":
            quote_at = i + 1
        elif raw_base < 0 and language in {"javascript", "typescript", "tsx"} and chars[i] == '`':
            quote_at = i
            interpolation_mode = "javascript"
        elif raw_base < 0 and chars[i] in "\"'`":
            quote_at = i
        elif raw_base < 0:
            i += 1
            continue

        quote = chars[quote_at]
        delimiter_size = 1
        if quote in "\"'":
            quote_run = quote_at
            while quote_run < length and chars[quote_run] == quote:
                quote_run += 1
            if quote_run - quote_at >= 3:
                delimiter_size = quote_run - quote_at
        if interpolation_mode:
            end = _interpolated_literal_end(
                text,
                chars,
                quote_at + delimiter_size,
                length,
                language,
                interpolation_mode,
                quote,
                verbatim=verbatim,
                delimiter_size=delimiter_size,
                brace_count=interpolation_braces,
                raw_string=interpolation_raw_string,
            )
        elif raw_terminator:
            close = text.find(raw_terminator, quote_at + 1)
            end = length if close < 0 else close + len(raw_terminator)
        else:
            end = quote_at + delimiter_size
            while end < length:
                if delimiter_size >= 3 and chars[end] == quote:
                    quote_run = end
                    while quote_run < length and chars[quote_run] == quote:
                        quote_run += 1
                    if quote_run - end >= delimiter_size:
                        end += delimiter_size
                        break
                    end = quote_run
                    continue
                if delimiter_size == 1 and chars[end] == quote:
                    if verbatim and end + 1 < length and chars[end + 1] == quote:
                        end += 2
                        continue
                    end += 1
                    break
                if not verbatim and chars[end] == "\\":
                    end += 2
                else:
                    end += 1
        if mask_literals:
            blank(start, end)
            if interpolation_mode:
                spans = _interpolated_code_spans(
                    text,
                    quote_at + delimiter_size,
                    max(quote_at + delimiter_size, end - delimiter_size),
                    language,
                    interpolation_mode,
                    chars,
                    verbatim=verbatim,
                    brace_count=interpolation_braces,
                    raw_string=interpolation_raw_string,
                )
                for span_start, span_end in spans:
                    masked = _mask_non_code(text[span_start:span_end], language, mask_literals=True)
                    chars[span_start:span_end] = masked
        i = max(end, start + 1)

    return "".join(chars)


_DECLARATION_CALL_PATTERNS = (
    re.compile(r"\b(?:function|func|fn|def)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
    re.compile(
        r"\b(?:(?:public|private|protected|internal|static|final|async|virtual|override|abstract|sealed|synchronized|native)\s+)*(?:[A-Za-z_$][\w.$<>,?\[\]]*\s+)+([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^;{}]*\)\s*(?:\{|=>|throws\b|where\b)"
    ),
)


def _declaration_call_spans(line: str) -> set[tuple[int, int]]:
    return {
        match.span(1)
        for pattern in _DECLARATION_CALL_PATTERNS
        for match in pattern.finditer(line)
    }


def _escape_like_literal(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


class CodeIndex:
    def __init__(self, config: dict[str, Any], repo_tools: Any):
        self.config = config
        self.repo_tools = repo_tools
        self.db_path = Path(config["server"]["state_dir"]) / "code-index.sqlite3"
        self.parse_blob_max = int(config.get("code_index", {}).get("parse_blob_max_entries", 100000))
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not ensure_incremental_vacuum(self.db_path).get("success"):
            logging.getLogger(__name__).warning("code-index database incremental vacuum setup incomplete")
        self._status_cache: dict[str, Any] = {}
        self._rev_cache = {}
        self._rev_lock = threading.Lock()
        self._parse_blob_l1 = MemoryLRUCache(max_entries=4096, ttl_seconds=3600)
        self._parse_diagnostic = threading.local()
        self._query_l1 = MemoryLRUCache(max_entries=2048, ttl_seconds=1800)
        self._symbol_l1 = MemoryLRUCache(max_entries=2048, ttl_seconds=1800)
        self._impact_result_l1 = MemoryLRUCache(max_entries=512, ttl_seconds=1800)
        self._impact_path_format_l1 = MemoryLRUCache(max_entries=256, ttl_seconds=1800)
        self._impact_candidate_count_l1 = MemoryLRUCache(max_entries=256, ttl_seconds=1800)
        self._query_cache_generation_key = str(self.db_path.resolve())
        self._init_db()
        self._cache_observer = SQLiteChangeObserver(self.db_path)
        self._cache_guard = threading.RLock()
        self._observed_data_version: int | None = None
        self._reindex_callback: Any = None
        self._reindex_notifications = MemoryLRUCache(max_entries=512, ttl_seconds=30)

    def set_reindex_callback(self, callback: Any) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("reindex callback must be callable or None")
        self._reindex_callback = callback

    def _cache_generation(self) -> int:
        with self._cache_guard:
            version = self._cache_observer.version()
            if version is None or version != self._observed_data_version:
                for cache in (
                    getattr(self, "_query_l1", None),
                    getattr(self, "_symbol_l1", None),
                    getattr(self, "_parse_blob_l1", None),
                    getattr(self, "_impact_result_l1", None),
                    getattr(self, "_impact_path_format_l1", None),
                    getattr(self, "_impact_candidate_count_l1", None),
                ):
                    if cache is not None:
                        cache.clear()
                self._status_cache.clear()
                self._advance_query_cache_generation()
            self._observed_data_version = version
            return _query_cache_generation(self._query_cache_generation_key)

    def close(self) -> None:
        observer = getattr(self, "_cache_observer", None)
        if observer is not None:
            observer.close()

    def _advance_query_cache_generation(self) -> None:
        # A generation key makes in-flight pre-update queries unreachable after
        # any index mutation without clearing the bounded cache under readers.
        # The registry is shared by CodeIndex instances that use this database.
        _advance_query_cache_generation(self._query_cache_generation_key)

    def _connect(self, *, register_archive_function: bool = True) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=5.0, row_factory=sqlite3.Row)
        try:
            con.execute("PRAGMA recursive_triggers=ON")
            if register_archive_function:
                con.create_function("hub_root_archive_path", 1, is_root_archive_path, deterministic=True)
        except Exception:
            con.close()
            raise
        try:
            con.execute("PRAGMA cache_size=-16000")
            con.execute("PRAGMA mmap_size=134217728")
        except sqlite3.OperationalError:
            pass
        return con

    def _schema(self, con: sqlite3.Connection) -> None:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS files(
            root TEXT,
            path TEXT,
            content_hash TEXT,
            analyzer_version TEXT,
            language TEXT,
            updated_at REAL,
            mtime_ns INTEGER,
            size_bytes INTEGER,
            PRIMARY KEY(root, path)
        );
        CREATE TABLE IF NOT EXISTS symbols(
            root TEXT,
            path TEXT,
            name TEXT,
            kind TEXT,
            line INTEGER,
            end_line INTEGER,
            container TEXT,
            name_path TEXT,
            signature TEXT,
            access TEXT,
            docstring TEXT,
            PRIMARY KEY(root, path, name_path, line)
        );
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(root, name);
        CREATE INDEX IF NOT EXISTS idx_symbols_name_lc ON symbols(root, lower(name));
        CREATE INDEX IF NOT EXISTS idx_symbols_name_path ON symbols(root, name_path);
        CREATE INDEX IF NOT EXISTS idx_symbols_name_path_lc ON symbols(root, lower(name_path));
        CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(root, path);
        CREATE INDEX IF NOT EXISTS idx_symbols_container ON symbols(root, container);

        CREATE TABLE IF NOT EXISTS refs(
            root TEXT,
            path TEXT,
            name TEXT,
            line INTEGER,
            kind TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_refs_name ON refs(root, name);
        CREATE INDEX IF NOT EXISTS idx_refs_name_path ON refs(root, name, path);
        CREATE INDEX IF NOT EXISTS idx_refs_name_lc ON refs(root, lower(name));
        CREATE INDEX IF NOT EXISTS idx_refs_path ON refs(root, path);

        CREATE TABLE IF NOT EXISTS edges(
            root TEXT,
            src TEXT,
            dst TEXT,
            src_name TEXT,
            dst_name TEXT,
            kind TEXT,
            path TEXT,
            line INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(root, src);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(root, dst);
        CREATE INDEX IF NOT EXISTS idx_edges_dst_path ON edges(root, dst, path);
        CREATE INDEX IF NOT EXISTS idx_edges_path ON edges(root, path);

        CREATE TABLE IF NOT EXISTS parse_blobs(
            content_hash TEXT,
            analyzer_version TEXT,
            language TEXT,
            payload_json TEXT,
            updated_at REAL,
            PRIMARY KEY(content_hash, analyzer_version, language)
        );
        CREATE INDEX IF NOT EXISTS idx_parse_blobs_updated ON parse_blobs(updated_at);
        """)
        edge_columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(edges)").fetchall()}
        file_columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(files)").fetchall()}
        if not {"src_name", "dst_name"}.issubset(edge_columns) or not {
            "analyzer_version", "mtime_ns", "size_bytes"
        }.issubset(file_columns):
            # Derived state is disposable: let the existing initialization
            # recovery archive and rebuild it instead of migrating old rows.
            raise sqlite3.DatabaseError("stale derived code-index schema; rebuild this cache")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_root_kind_dst_name ON edges(root, kind, dst_name)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_root_kind_src_name ON edges(root, kind, src_name)"
        )
        initialize_row_counts(con, ("files", "symbols", "refs", "edges"))

    def _init_db(self) -> None:
        with _code_index_initialization_lock(self.db_path):
            self._initialize_db()

    def _initialize_db(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                if not quick_sanity_check(con):
                    raise sqlite3.DatabaseError("code-index sanity check failed")
                self._schema(con)
                con.commit()
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            stamp = int(time.time())
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.db_path) + suffix)
                    if side.exists():
                        side.unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                self._schema(con)
                con.commit()

    @staticmethod
    def _lang(path: str) -> str:
        suffix = Path(path).suffix.lower()
        return {
            ".py": "python",
            ".cs": "csharp",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".php": "php",
            ".java": "java",
            ".cpp": "cpp",
            ".go": "go",
            ".rs": "rust",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
        }.get(suffix, "generic")

    def _project_config_context(self, root: str) -> tuple[Any | None, Any | None]:
        try:
            from importlib import import_module

            api = import_module("local_ai_hub.project_config")
        except ModuleNotFoundError as exc:
            if exc.name == "local_ai_hub.project_config":
                return None, None
            raise
        state_dir = self.config.get("server", {}).get("state_dir", "state")
        return api, api.resolve_project_context(root, state_dir)

    @staticmethod
    def _language_for_path(path: str, settings: Any | None) -> str:
        from .treesitter_parser import language_for_path
        suffix = Path(path).suffix.lower()
        overrides = getattr(settings, "language_overrides", {}) if settings is not None else {}
        for language, override in overrides.items() if hasattr(overrides, "items") else ():
            extensions = override.get("text_extensions", ()) if hasattr(override, "get") else ()
            if suffix in {str(extension).lower() for extension in extensions}:
                return str(language).strip().lower()
        if suffix == ".tsx":
            return "tsx"
        return language_for_path(path, CodeIndex._lang(path), settings)

    def _remove_indexed_paths(self, root: str, paths: list[str]) -> None:
        if not paths:
            return
        c_root = canonical_root(root)
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            for path in paths:
                for table in ("files", "symbols", "refs", "edges"):
                    con.execute(f"DELETE FROM {table} WHERE root=? AND path=?", (c_root, path))
            con.commit()
        self._advance_query_cache_generation()

    def _parse_python(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if len(text) > self.repo_tools.max_file_bytes or len(text.encode("utf-8")) > self.repo_tools.max_file_bytes:
            return [], [], []
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return syms, refs, edges

        stack: list[str] = []
        overloads: dict[str, int] = {}

        class V(ast.NodeVisitor):
            def visit_ClassDef(s, n):
                container = "/".join(stack)
                name_path = (container + "/" if container else "") + n.name
                doc = ast.get_docstring(n) or ""
                doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""
                bases = [ast.unparse(b) for b in n.bases]

                syms.append({
                    "name": n.name,
                    "kind": "class",
                    "line": n.lineno,
                    "end_line": getattr(n, "end_lineno", n.lineno),
                    "container": container,
                    "name_path": name_path,
                    "signature": f"class {n.name}({', '.join(bases)})" if bases else f"class {n.name}",
                    "access": "public" if not n.name.startswith("_") else "private",
                    "docstring": doc_summary[:200],
                })
                for b in bases:
                    edges.append({"src": name_path, "dst": b, "kind": "inherits", "line": n.lineno})

                stack.append(n.name)
                s.generic_visit(n)
                stack.pop()

            def visit_FunctionDef(s, n):
                container = "/".join(stack)
                base_name_path = (container + "/" if container else "") + n.name
                idx = overloads.get(base_name_path, 0)
                overloads[base_name_path] = idx + 1
                name_path = base_name_path if idx == 0 else f"{base_name_path}[{idx}]"
                doc = ast.get_docstring(n) or ""
                doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""

                try:
                    args_str = ast.unparse(n.args) if getattr(n, "args", None) else ""
                except Exception:
                    args_str = ", ".join(a.arg for a in n.args.args)
                try:
                    ret = ast.unparse(n.returns) if getattr(n, "returns", None) else ""
                except Exception:
                    ret = ""
                fn_kw = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
                sig = f"{fn_kw} {n.name}({args_str})" + (f" -> {ret}" if ret else "")

                is_method = bool(stack)
                kind = "method" if is_method else "function"
                if any(isinstance(d, ast.Name) and d.id == "property" for d in n.decorator_list):
                    kind = "property"

                syms.append({
                    "name": n.name,
                    "kind": kind,
                    "line": n.lineno,
                    "end_line": getattr(n, "end_lineno", n.lineno),
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not n.name.startswith("_") else "private",
                    "docstring": doc_summary[:200],
                })

                stack.append(n.name)
                s.generic_visit(n)
                stack.pop()

            def visit_AsyncFunctionDef(s, n):
                s.visit_FunctionDef(n)

            def visit_Call(s, n):
                name = ""
                if isinstance(n.func, ast.Name):
                    name = n.func.id
                elif isinstance(n.func, ast.Attribute):
                    name = n.func.attr
                if name:
                    refs.append({"name": name, "line": getattr(n, "lineno", 0), "kind": "call"})
                    edges.append({"src": "/".join(stack) or "<module>", "dst": name, "kind": "calls", "line": getattr(n, "lineno", 0)})
                s.generic_visit(n)

            def visit_Import(s, n):
                for a in n.names:
                    edges.append({"src": "<module>", "dst": a.name, "kind": "imports", "line": n.lineno})

            def visit_ImportFrom(s, n):
                module = "." * n.level + (n.module or "")
                targets = {module} if module else set()
                for alias in n.names:
                    if alias.name != "*":
                        separator = "" if not module or module.endswith(".") else "."
                        targets.add(f"{module}{separator}{alias.name}")
                for target in sorted(targets):
                    edges.append({"src": "<module>", "dst": target, "kind": "imports", "line": n.lineno})

        V().visit(tree)
        return syms, refs, edges

    @staticmethod
    def _brace_metadata(lines: list[str]) -> tuple[dict[int, int], list[int | None]]:
        """Build brace pairs and next-opening positions in one linear pass.

        End-line metadata is only informational, but repeatedly scanning hundreds
        of lines for every symbol made large C#/JS files quadratic to parse.
        """
        pairs: dict[int, int] = {}
        stack: list[int] = []
        has_open = ["{" in line.split("//", 1)[0] for line in lines]
        for index, line in enumerate(lines):
            for char in line.split("//", 1)[0]:
                if char == "{":
                    stack.append(index)
                elif char == "}" and stack:
                    pairs[stack.pop()] = index
        next_open: list[int | None] = [None] * len(lines)
        nearest: int | None = None
        for index in range(len(lines) - 1, -1, -1):
            if has_open[index]:
                nearest = index
            next_open[index] = nearest
        return pairs, next_open

    @staticmethod
    def _block_end_line(start_index: int, pairs: dict[int, int], next_open: list[int | None], max_lines: int) -> int:
        opening = next_open[start_index] if 0 <= start_index < len(next_open) else None
        if opening is None or opening - start_index >= max_lines:
            return start_index + 1
        closing = pairs.get(opening)
        return (closing + 1) if closing is not None else start_index + 1

    @staticmethod
    def _call_owners_by_line(symbols: list[dict[str, Any]], line_count: int) -> list[str]:
        """Map source lines to the narrowest enclosing fallback function symbol."""
        function_kinds = {"function", "method", "constructor", "func", "fn"}
        starts: dict[int, list[dict[str, Any]]] = {}
        for symbol in symbols:
            start = int(symbol.get("line", 0))
            end = int(symbol.get("end_line", 0))
            if str(symbol.get("kind", "")).lower() in function_kinds and 1 <= start <= end <= line_count:
                starts.setdefault(start, []).append(symbol)

        owners = ["<module>"] * (line_count + 1)
        active: list[dict[str, Any]] = []
        for line in range(1, line_count + 1):
            active = [symbol for symbol in active if int(symbol.get("end_line", 0)) >= line]
            active.extend(starts.get(line, ()))
            if active:
                owner = min(
                    active,
                    key=lambda symbol: (
                        int(symbol.get("end_line", 0)) - int(symbol.get("line", 0)),
                        -int(symbol.get("line", 0)),
                    ),
                )
                owners[line] = str(owner.get("name_path") or owner.get("name") or "<module>")
        return owners

    def _parse_csharp(self, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        lines = _mask_non_code(text, "csharp").splitlines()
        brace_pairs, next_open = self._brace_metadata(lines)

        class_re = re.compile(
            r"^\s*(?:\[[^\]]+\]\s*)*(?:(public|private|protected|internal|static|abstract|sealed|partial)\s+)*(class|interface|struct|enum|record)\s+([A-Za-z0-9_]+)(?:<[^>]+>)?(?:\s*:\s*([A-Za-z0-9_,\s<>]+))?",
            re.M,
        )
        method_re = re.compile(
            r"^\s*(?:\[[^\]]+\]\s*)*(?:(public|private|protected|internal|static|virtual|override|abstract|async|sealed)\s+)*(?:([A-Za-z0-9_<>\[\]?]+)\s+)?([A-Za-z0-9_]+)\s*\(([^;{}]*)\)\s*(?:where\s+.*?)?(?:\{|=>|;)",
            re.M,
        )
        prop_re = re.compile(
            r"^\s*(?:(public|private|protected|internal|static|virtual|override|abstract)\s+)+([A-Za-z0-9_<>\[\]?]+)\s+([A-Za-z0-9_]+)\s*\{[^}]*\}",
            re.M,
        )
        using_re = re.compile(r"^\s*using\s+(?:static\s+)?([A-Za-z0-9_.]+);")

        container_stack: list[tuple[str, str, int, int]] = []
        overloads: dict[str, int] = {}
        class_names: set[str] = set()

        for i, line in enumerate(lines, 1):
            um = using_re.match(line)
            if um:
                edges.append({"src": "<module>", "dst": um.group(1), "kind": "imports", "line": i})

        for i, line in enumerate(lines, 1):
            container_stack = [c for c in container_stack if c[3] >= i]
            curr_container = "/".join(c[0] for c in container_stack)

            cm = class_re.match(line)
            if cm:
                access = cm.group(1) or "internal"
                kind = cm.group(2)
                name = cm.group(3)
                class_names.add(name)
                heritage = cm.group(4) or ""

                end_l = self._block_end_line(i - 1, brace_pairs, next_open, 3500)

                container_stack.append((name, kind, i, end_l))
                name_path = (curr_container + "/" if curr_container else "") + name

                doc = ""
                if i > 1:
                    prev = lines[i - 2].strip()
                    if prev.startswith("///"):
                        doc = re.sub(r"<[^>]+>", "", prev.replace("///", "")).strip()

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": i,
                    "end_line": end_l,
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {kind} {name}" + (f" : {heritage.strip()}" if heritage else ""),
                    "access": access,
                    "docstring": doc[:200],
                })

                if heritage:
                    for base in heritage.split(","):
                        b = base.strip().split("<")[0].strip()
                        if b:
                            edges.append({"src": name_path, "dst": b, "kind": "inherits" if "class" in kind else "implements", "line": i})
                curr_container = "/".join(c[0] for c in container_stack)
                method_text = line[cm.end():]
                class_body_open = method_text.find("{")
                if class_body_open >= 0:
                    method_text = method_text[class_body_open + 1:]
            else:
                method_text = line

            if not cm and i < len(lines) and re.match(r"^\s*\{", lines[i]):
                method_text += "\n" + lines[i]
            mm = method_re.match(method_text)
            if (
                mm
                and not mm.group(2)
                and (mm.group(3) != curr_container.rsplit("/", 1)[-1] or "{" not in method_text)
            ):
                mm = None
            if mm and mm.group(3) not in _CONTROL_NAMES:
                access = mm.group(1) or "private"
                ret_type = mm.group(2) or "void"
                name = mm.group(3)
                params = mm.group(4) or ""

                end_l = i
                if "{" in method_text:
                    opening = i - 1 if "{" in line else i
                    closing = brace_pairs.get(opening)
                    if closing is not None and closing - (i - 1) < 800:
                        end_l = closing + 1
                elif "=>" in method_text:
                    end_l = max(end_l, _arrow_expression_end_line(lines, i - 1, method_text.find("=>")) + 1)

                base_name_path = (curr_container + "/" if curr_container else "") + name
                idx = overloads.get(base_name_path, 0)
                overloads[base_name_path] = idx + 1
                name_path = base_name_path if idx == 0 else f"{base_name_path}[{idx}]"

                syms.append({
                    "name": name,
                    "kind": "method" if curr_container else "function",
                    "line": i,
                    "end_line": max(i, end_l),
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {ret_type} {name}({params.strip()})",
                    "access": access,
                    "docstring": "",
                })

            pm = prop_re.match(line)
            if pm:
                access = pm.group(1)
                prop_type = pm.group(2)
                prop_name = pm.group(3)
                name_path = (curr_container + "/" if curr_container else "") + prop_name
                syms.append({
                    "name": prop_name,
                    "kind": "property",
                    "line": i,
                    "end_line": i,
                    "container": curr_container,
                    "name_path": name_path,
                    "signature": f"{access} {prop_type} {prop_name} {{ get; set; }}",
                    "access": access,
                    "docstring": "",
                })

        for symbol in syms:
            if _callable_needs_close_position(lines, symbol):
                close_position = _callable_block_close_position(lines, symbol)
                if close_position is not None:
                    symbol["_body_close_position"] = close_position

        call_pattern = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{2,})\s*\(")
        for i, line in enumerate(lines, 1):
            cleaned = line
            declaration_spans = _declaration_call_spans(cleaned)
            for m in call_pattern.finditer(cleaned):
                cname = m.group(1)
                if cname.lower() not in _CONTROL_NAMES and m.span(1) not in declaration_spans:
                    refs.append({"name": cname, "line": i, "kind": "call"})
                    edges.append({
                        "src": _call_edge_source(syms, i, column=m.start(1), source_line=line),
                        "dst": cname,
                        "kind": "calls",
                        "line": i,
                    })

        for symbol in syms:
            symbol.pop("_body_close_position", None)
        return syms, refs, edges

    def _parse_generic(self, text: str, lang: str = "generic") -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        syms: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        raw_lines = text.splitlines()
        lines = _mask_non_code(text, lang).splitlines()
        brace_pairs, next_open = self._brace_metadata(lines)

        ns_pattern = re.compile(r"^\s*namespace\s+([A-Za-z0-9_\\]+)")
        curr_namespace = ""
        for line in lines:
            nm = ns_pattern.match(line)
            if nm:
                curr_namespace = nm.group(1).rstrip(";")
                break

        raw_syms: list[dict[str, Any]] = []
        for i, line in enumerate(lines, 1):
            m = GENERIC_DEF.match(line)
            declarations: list[tuple[str, str]] = []
            if m:
                declarations.append((m.group(1), m.group(2)))
            else:
                for pattern in (ARROW_DEF, GO_METHOD, TYPED_METHOD, JS_METHOD):
                    mm = pattern.search(line) if pattern is TYPED_METHOD else pattern.match(line)
                    if mm and mm.group(1).lower() not in _CONTROL_NAMES:
                        declarations.append(("function", mm.group(1)))
                        break
            if "=>" in line:
                known_names = {name for _kind, name in declarations}
                declarations.extend(
                    ("function", match.group(1))
                    for match in INLINE_ARROW_DEF.finditer(line)
                    if match.group(1) not in known_names
                )
            raw_sig = raw_lines[i - 1].strip() if i - 1 < len(raw_lines) else line.strip()
            # Keep a terminal arrow: multiline expression-body call ownership
            # uses it to stop at the body's terminating semicolon.
            clean_sig = re.sub(r"\s*(?:\{|;)\s*$", "", raw_sig)[:160]
            for kind, name in declarations:
                raw_syms.append({
                    "name": name,
                    "kind": kind,
                    "line": i,
                    "end_line": i,
                    "container": curr_namespace,
                    "name_path": f"{curr_namespace}\\{name}" if curr_namespace else name,
                    "signature": clean_sig,
                    "access": "public",
                    "docstring": "",
                })

            im = IMPORT.match(raw_lines[i - 1]) if line.strip() else None
            if im:
                dst = next((x for x in im.groups() if x), "")
                edges.append({"src": "<module>", "dst": dst, "kind": "imports", "line": i})

        for s in raw_syms:
            start_l = s["line"] - 1
            declaration_line = lines[start_l] if 0 <= start_l < len(lines) else str(s.get("signature", ""))
            arrow_offset = declaration_line.find("=>")
            if arrow_offset >= 0:
                body = declaration_line[arrow_offset + 2:].strip()
                if not body and start_l + 1 < len(lines):
                    body = lines[start_l + 1].strip()
                if body and not body.startswith("{"):
                    end_l = _arrow_expression_end_line(lines, start_l, arrow_offset) + 1
                elif not body:
                    end_l = start_l + 1
                else:
                    end_l = self._block_end_line(start_l, brace_pairs, next_open, 2500)
            else:
                end_l = self._block_end_line(start_l, brace_pairs, next_open, 2500)
            s["end_line"] = max(s["line"], end_l)
            if _callable_needs_close_position(lines, s):
                close_position = _callable_block_close_position(lines, s)
                if close_position is not None:
                    s["_body_close_position"] = close_position
            syms.append(s)

        call_re = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]{2,})\s*\(")
        for i, line in enumerate(lines, 1):
            declaration_spans = _declaration_call_spans(line)
            for m in call_re.finditer(line):
                name = m.group(1)
                if name.lower() not in _CONTROL_NAMES and m.span(1) not in declaration_spans:
                    refs.append({"name": name, "line": i, "kind": "call"})
                    edges.append({
                        "src": _call_edge_source(syms, i, column=m.start(1), source_line=line),
                        "dst": name,
                        "kind": "calls",
                        "line": i,
                    })

        for symbol in syms:
            symbol.pop("_body_close_position", None)
        return syms, refs, edges

    def _tree_source_key(self, root: str, path: str) -> str:
        return stable_hash({"database": str(self.db_path.resolve()), "root": root,
                            "path": path, "analyzer": _PARSER_ANALYZER_VERSION})

    @staticmethod
    def _sync_file_rows(con: sqlite3.Connection, table: str, root: str, path: str,
                        rows: list[tuple[Any, ...]]) -> dict[str, int]:
        """Retain identical metadata rows, including duplicate reference occurrences."""
        columns = {
            "symbols": "name,kind,line,end_line,container,name_path,signature,access,docstring",
            "refs": "name,line,kind",
            "edges": "src,dst,src_name,dst_name,kind,line",
        }[table]
        if table == "symbols":
            # Match INSERT OR REPLACE's last occurrence for the existing primary key.
            rows = list({(row[5], row[2]): row for row in rows}.values())
        wanted = Counter(rows)
        removed: list[tuple[int]] = []
        retained = 0
        for old in con.execute(f"SELECT rowid,{columns} FROM {table} WHERE root=? AND path=?", (root, path)):
            value = tuple(old)[1:]
            if wanted[value]:
                wanted[value] -= 1
                retained += 1
            else:
                removed.append((old[0],))
        con.executemany(f"DELETE FROM {table} WHERE rowid=?", removed)
        added = [(root, path, *value) for value, count in wanted.items() for _ in range(count)]
        placeholders = ",".join("?" for _ in range(len(columns.split(",")) + 2))
        con.executemany(f"INSERT INTO {table}(root,path,{columns}) VALUES({placeholders})", added)
        return {"retained": retained, "deleted": len(removed), "inserted": len(added)}

    def _parse_file_content_report(
        self, text: str, lang: str, *, source_key: str | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        parser_report: dict[str, Any] = {
            "status": "unavailable", "parser": "tree_sitter",
            "fallback_reason": "parser_unavailable", "syntax_error_count": 0,
        }
        try:
            from .treesitter_parser import parse_treesitter_with_status
            parser_report = (parse_treesitter_with_status(text, lang, source_key=source_key)
                             if source_key is not None else parse_treesitter_with_status(text, lang))
            ts_res = parser_report.get("result")
            if ts_res is not None and (ts_res[0] or ts_res[2]):
                diagnostic = {
                    "status": str(parser_report.get("status") or "unknown"),
                    "parser": str(parser_report.get("parser") or "tree_sitter"),
                    "fallback_used": False,
                    "syntax_error_count": int(parser_report.get("syntax_error_count", 0) or 0),
                    "syntax_error_count_truncated": bool(parser_report.get("syntax_error_count_truncated", False)),
                }
                for field in ("incremental", "tree_cache_hit", "tree_reused", "edit", "incremental_fallback"):
                    if field in parser_report:
                        diagnostic[field] = parser_report[field]
                return (*ts_res, diagnostic)
        except Exception as exc:
            parser_report = {
                "status": "failed", "parser": "tree_sitter",
                "fallback_reason": "parser_error", "error_type": type(exc).__name__,
                "syntax_error_count": 0,
            }

        if lang == "python":
            parsed = self._parse_python(text)
        elif lang == "csharp":
            parsed = self._parse_csharp(text)
        else:
            parsed = self._parse_generic(text, lang)
        syntax_error_count = int(parser_report.get("syntax_error_count", 0) or 0)
        diagnostic = {
            "status": "syntax_error" if syntax_error_count else "fallback",
            "parser": str(parser_report.get("parser") or "tree_sitter"),
            "fallback_used": True,
            "fallback_reason": str(parser_report.get("fallback_reason") or "no_extracted_nodes"),
            "syntax_error_count": syntax_error_count,
            "syntax_error_count_truncated": bool(parser_report.get("syntax_error_count_truncated", False)),
        }
        if parser_report.get("error_type"):
            diagnostic["error_type"] = str(parser_report["error_type"])
        if "worker_cleanup_confirmed" in parser_report:
            diagnostic["worker_cleanup_confirmed"] = bool(parser_report["worker_cleanup_confirmed"])
        return (*parsed, diagnostic)


    def _parse_file_content(self, text: str, lang: str, *, source_key: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        symbols, refs, edges, diagnostic = (self._parse_file_content_report(text, lang, source_key=source_key)
                                          if source_key is not None else self._parse_file_content_report(text, lang))
        self._parse_diagnostic.value = diagnostic
        return symbols, refs, edges

    def _parse_blob_get(self, content_hash: str, language: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        cached = self._parse_blob_get_with_report(content_hash, language)
        return cached[0] if cached is not None else None


    def _parse_blob_get_with_report(
        self, content_hash: str, language: str
    ) -> tuple[tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]] | None:
        key = f"{content_hash}:{_PARSER_ANALYZER_VERSION}:{language}"
        cached = self._parse_blob_l1.get(key)
        if cached is not None:
            if len(cached) >= 4 and isinstance(cached[3], dict):
                return (cached[0], cached[1], cached[2]), dict(cached[3])
            return (cached[0], cached[1], cached[2]), {"status": "unknown", "parser": "unknown", "fallback_used": False}
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT payload_json FROM parse_blobs WHERE content_hash=? AND analyzer_version=? AND language=?", (content_hash, _PARSER_ANALYZER_VERSION, language)).fetchone()
            if row:
                data = json.loads(str(row[0]))
                if isinstance(data, dict):
                    res = (list(data.get("symbols", [])), list(data.get("refs", [])), list(data.get("edges", [])))
                    diagnostic = data.get("parse_outcome")
                    if not isinstance(diagnostic, dict):
                        diagnostic = {"status": "unknown", "parser": "unknown", "fallback_used": False}
                    self._parse_blob_l1.set(key, (*res, dict(diagnostic)))
                    return res, dict(diagnostic)
        except Exception:
            pass
        return None

    def _parse_blob_put(
        self, content_hash: str, language: str,
        syms: list[dict[str, Any]], refs: list[dict[str, Any]], edges: list[dict[str, Any]],
        parse_outcome: dict[str, Any] | None = None,
    ) -> None:
        key = f"{content_hash}:{_PARSER_ANALYZER_VERSION}:{language}"
        diagnostic = dict(parse_outcome or {"status": "unknown", "parser": "unknown", "fallback_used": False})
        self._parse_blob_l1.set(key, (syms, refs, edges, diagnostic))
        try:
            payload = json_dumps({"symbols": syms, "refs": refs, "edges": edges, "parse_outcome": diagnostic}, ensure_ascii=False, separators=(",", ":"))
            with self._lock, closing(self._connect()) as con:
                con.execute("INSERT OR REPLACE INTO parse_blobs(content_hash, analyzer_version, language, payload_json, updated_at) VALUES(?,?,?,?,?)", (content_hash, _PARSER_ANALYZER_VERSION, language, payload, time.time()))
                count = int(con.execute("SELECT COUNT(*) FROM parse_blobs").fetchone()[0])
                if count > self.parse_blob_max:
                    con.execute("DELETE FROM parse_blobs WHERE rowid IN (SELECT rowid FROM parse_blobs ORDER BY updated_at ASC LIMIT ?)", (max(100, count - self.parse_blob_max),))
                con.commit()
        except Exception:
            pass

    def files_needing_reindex(self, root: str, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Select paths with changed content or stale parser analyzer versions."""
        c_root = canonical_root(root)
        if not items:
            return []
        api, project_context = self._project_config_context(c_root)
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and not api.phase_is_allowed(settings, "call_graph"):
            return []
        existing: dict[str, tuple[str, str, str]] = {}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            for batch in sqlite_batches(list(dict.fromkeys(str(path) for path, _ in items))):
                placeholders = ",".join("?" for _ in batch)
                rows = con.execute(
                    f"SELECT path,content_hash,analyzer_version,language FROM files WHERE root=? AND path IN ({placeholders})",
                    (c_root, *batch),
                ).fetchall()
                for row in rows:
                    existing[str(row["path"])] = (
                        str(row["content_hash"] or ""), str(row["analyzer_version"] or ""),
                        str(row["language"] or ""),
                    )
        pending = []
        for path, content_hash in items:
            path = str(path)
            if api is not None and settings is not None:
                target = Path(c_root) / path
                try:
                    size_bytes = target.stat().st_size
                except OSError:
                    continue
                if not api.path_is_allowed(c_root, target, settings, phase="call_graph", size_bytes=size_bytes):
                    continue
            language = self._language_for_path(path, settings)
            if existing.get(path) != (str(content_hash), _PARSER_ANALYZER_VERSION, language):
                pending.append((path, str(content_hash)))
        return pending

    def _mark_file_unindexable(self, root: str, path: str, language: str) -> None:
        """Retain authorized path metadata while removing stale parsed data."""
        updated_at = time.time()
        with self._lock, closing(self._connect()) as con:
            for table in ("symbols", "refs", "edges"):
                con.execute(f"DELETE FROM {table} WHERE root=? AND path=?", (root, path))
            con.execute(
                "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
                "VALUES(?,?,NULL,NULL,?,?,NULL,NULL) "
                "ON CONFLICT(root,path) DO UPDATE SET content_hash=NULL, "
                "analyzer_version=NULL, language=excluded.language, updated_at=excluded.updated_at, "
                "mtime_ns=NULL, size_bytes=NULL",
                (root, path, language, updated_at),
            )
            con.commit()
        self._advance_query_cache_generation()
        self._status_cache.pop(root, None)

    @staticmethod
    def _file_stat_is_current(path: Path, expected_stat: Any) -> bool:
        try:
            current_stat = path.stat()
        except OSError:
            return False
        return (
            current_stat.st_mtime_ns == expected_stat.st_mtime_ns
            and current_stat.st_size == expected_stat.st_size
        )

    def update_file(self, root: str, path: str, content_hash: str | None = None) -> dict[str, Any]:
        base = Path(canonical_root(root))
        target = (base / path).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError:
            return {"success": False, "error": "invalid path"}
        api, project_context = self._project_config_context(str(base))
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and not api.phase_is_allowed(settings, "call_graph"):
            self.prune(str(base), [])
            return {"success": True, "skipped": True, "path": path, "reason": "project phase disabled"}
        if api is not None and settings is not None:
            try:
                size_bytes = target.stat().st_size if target.is_file() else None
            except OSError:
                size_bytes = None
            if not api.path_is_allowed(
                str(base), target, settings, phase="call_graph", size_bytes=size_bytes,
            ):
                self._remove_indexed_paths(str(base), [path])
                return {"success": True, "skipped": True, "path": path, "reason": "project path excluded"}
        if not target.is_file():
            with self._lock, closing(self._connect()) as con:
                for t in ("files", "symbols", "refs", "edges"):
                    con.execute(f"DELETE FROM {t} WHERE root=? AND path=?", (str(base), path))
                con.commit()
            self._advance_query_cache_generation()
            self._status_cache.pop(str(base), None)
            return {"success": True, "deleted": True}

        try:
            target_stat = target.stat()
        except OSError:
            return {"success": False, "error": "file unavailable"}
        lang = self._language_for_path(path, settings)
        if target_stat.st_size > self.repo_tools.max_file_bytes:
            self._mark_file_unindexable(str(base), path, lang)
            return {"success": True, "skipped": True, "path": path, "reason": "file exceeds max indexable size"}

        # Unchanged size/mtime does not establish unchanged content. Reuse the
        # existing content-addressed parse only after the bounded snapshot read.
        try:
            digest, lines = self.repo_tools._read_snapshot(
                target, stat=target_stat, force=True, max_bytes=self.repo_tools.max_file_bytes,
            )
        except FileTooLargeError:
            self._mark_file_unindexable(str(base), path, lang)
            return {"success": True, "skipped": True, "path": path, "reason": "file exceeds max indexable size"}
        content_hash = digest
        stat_is_current = self._file_stat_is_current(target, target_stat)
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT content_hash,analyzer_version,language FROM files WHERE root=? AND path=?", (str(base), path)).fetchone()
            if row and row[0] == content_hash and str(row[1] or "") == _PARSER_ANALYZER_VERSION and str(row[2] or "") == lang:
                if stat_is_current:
                    con.execute(
                        "UPDATE files SET mtime_ns=?,size_bytes=? WHERE root=? AND path=?",
                        (target_stat.st_mtime_ns, target_stat.st_size, str(base), path),
                    )
                    con.commit()
                cached = self._parse_blob_get_with_report(content_hash, lang)
                return {
                    "success": True, "cached": True, "path": path,
                    "parse_outcome": dict(cached[1]) if cached is not None else {"status": "unknown", "parser": "unknown"},
                }

        parsed_with_report = self._parse_blob_get_with_report(content_hash, lang)
        parsed = parsed_with_report[0] if parsed_with_report is not None else None
        if parsed is None:
            text = "\n".join(lines)
            syms, refs, edges = self._parse_file_content(text, lang, source_key=self._tree_source_key(str(base), path))
            parse_outcome = dict(getattr(self._parse_diagnostic, "value", {}))
            self._parse_blob_put(content_hash, lang, syms, refs, edges, parse_outcome)
        else:
            syms, refs, edges = parsed
            parse_outcome = parsed_with_report[1]

        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT OR REPLACE INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(base), path, content_hash, _PARSER_ANALYZER_VERSION, lang, time.time(),
                    target_stat.st_mtime_ns if stat_is_current else None,
                    target_stat.st_size if stat_is_current else None,
                ),
            )
            metadata_update = {
                "symbols": self._sync_file_rows(con, "symbols", str(base), path, [
                    (x["name"], x["kind"], x["line"], x["end_line"], x.get("container", ""),
                     x.get("name_path", x["name"]), x.get("signature", ""), x.get("access", "public"),
                     x.get("docstring", "")) for x in syms]),
                "refs": self._sync_file_rows(con, "refs", str(base), path, [
                    (x["name"], x["line"], x.get("kind", "call")) for x in refs]),
                "edges": self._sync_file_rows(con, "edges", str(base), path, [
                    (x["src"], x["dst"], _edge_endpoint_name(x["src"]), _edge_endpoint_name(x["dst"]),
                     x.get("kind", "reference"), x["line"]) for x in edges]),
            }
            con.commit()

        self._advance_query_cache_generation()
        self._status_cache.pop(str(base), None)
        return {
            "success": True, "cached": False, "path": path,
            "symbols": len(syms), "refs": len(refs), "edges": len(edges),
            "parse_outcome": dict(parse_outcome),
            "metadata_update": metadata_update,
        }

    def update_files_batch(self, root: str, items: list[str] | list[tuple[str, str]]) -> dict[str, Any]:
        """Batch-process files with one read phase and one SQLite write transaction."""
        c_root = canonical_root(root)
        base = Path(c_root)
        normalized: list[tuple[str, str | None]] = []
        for item in items:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append((str(item[0]), str(item[1]) or None))
            else:
                normalized.append((str(item), None))
        if not normalized:
            return {"success": True, "files_processed": 0, "cached": 0, "symbols": 0, "refs": 0, "edges": 0}

        api, project_context = self._project_config_context(c_root)
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and not api.phase_is_allowed(settings, "call_graph"):
            self.prune(c_root, [])
            return {"success": True, "files_processed": 0, "cached": 0, "symbols": 0, "refs": 0, "edges": 0, "skipped": len(normalized)}

        with self._lock, closing(self._connect()) as con:
            existing = {
                str(row["path"]): (
                    str(row["content_hash"] or ""),
                    str(row["analyzer_version"] or ""),
                    str(row["language"] or ""),
                    row["mtime_ns"],
                    row["size_bytes"],
                )
                for row in con.execute(
                    "SELECT path,content_hash,analyzer_version,language,mtime_ns,size_bytes FROM files WHERE root=?",
                    (c_root,),
                ).fetchall()
            }

        candidates: list[tuple[str, str, str, list[str]]] = []
        file_stats: dict[str, Any] = {}
        cached = 0
        denied_paths: list[str] = []
        deleted_paths: list[tuple[str, str]] = []
        for path, supplied_hash in normalized:
            file_path = (base / path).resolve(strict=False)
            try:
                relative_path = file_path.relative_to(base)
            except ValueError:
                continue
            if is_root_archive_path(relative_path):
                denied_paths.append(path)
                continue
            if not file_path.is_file():
                deleted_paths.append((c_root, path))
                continue
            try:
                file_stat = file_path.stat()
            except OSError:
                continue
            if api is not None and settings is not None:
                if not api.path_is_allowed(
                    c_root, file_path, settings, phase="call_graph", size_bytes=file_stat.st_size,
                ):
                    denied_paths.append(path)
                    continue
            lang = self._language_for_path(path, settings)
            if file_stat.st_size > self.repo_tools.max_file_bytes:
                self._mark_file_unindexable(c_root, path, lang)
                continue
            file_stats[path] = file_stat
            try:
                digest, lines = self.repo_tools._read_snapshot(
                    file_path, stat=file_stat, force=True, max_bytes=self.repo_tools.max_file_bytes,
                )
            except FileTooLargeError:
                self._mark_file_unindexable(c_root, path, lang)
                continue
            except OSError:
                continue
            content_hash = digest
            if existing.get(path, ())[:3] == (content_hash, _PARSER_ANALYZER_VERSION, lang):
                cached += 1
                continue
            candidates.append((path, content_hash, lang, lines))

        self._remove_indexed_paths(c_root, denied_paths)

        blob_map: dict[tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]] = {}
        if candidates:
            pairs = list(dict.fromkeys((h, lang) for _, h, lang, _ in candidates))
            for content_hash, language in pairs:
                cached = self._parse_blob_l1.get(
                    f"{content_hash}:{_PARSER_ANALYZER_VERSION}:{language}"
                )
                if cached is None:
                    continue
                diagnostic = cached[3] if len(cached) >= 4 and isinstance(cached[3], dict) else {
                    "status": "unknown", "parser": "unknown", "fallback_used": False,
                }
                blob_map[(content_hash, language)] = (
                    list(cached[0]), list(cached[1]), list(cached[2]), dict(diagnostic),
                )
            missing_pairs = [pair for pair in pairs if pair not in blob_map]
            try:
                for batch in sqlite_batches(missing_pairs):
                    clauses = " OR ".join("(content_hash=? AND language=?)" for _ in batch)
                    params: list[Any] = []
                    for h, lang in batch:
                        params.extend([h, lang])
                    with self._lock, closing(self._connect()) as con:
                        rows = con.execute(f"SELECT content_hash,language,payload_json FROM parse_blobs WHERE analyzer_version=? AND ({clauses})", (_PARSER_ANALYZER_VERSION, *params)).fetchall()
                    for row in rows:
                        data = json.loads(str(row[2]))
                        if isinstance(data, dict):
                            diagnostic = data.get("parse_outcome")
                            if not isinstance(diagnostic, dict):
                                diagnostic = {"status": "unknown", "parser": "unknown", "fallback_used": False}
                            blob_map[(str(row[0]), str(row[1]))] = (list(data.get("symbols", [])), list(data.get("refs", [])), list(data.get("edges", [])), diagnostic)
            except Exception:
                pass

        files_to_insert: list[tuple[Any, ...]] = []
        syms_to_insert: list[tuple[Any, ...]] = []
        refs_to_insert: list[tuple[Any, ...]] = []
        edges_to_insert: list[tuple[Any, ...]] = []
        parse_blob_rows: list[tuple[Any, ...]] = []
        paths_to_clean: list[tuple[str, str]] = []
        now = time.time()
        def _parse_candidate(cand: tuple[str, str, str, list[str]]):
            path, content_hash, lang, lines = cand
            parsed = blob_map.get((content_hash, lang))
            if parsed is None:
                syms, refs, edges = self._parse_file_content("\n".join(lines), lang, source_key=self._tree_source_key(c_root, path))
                diagnostic = dict(getattr(self._parse_diagnostic, "value", {}))
                row_blob = (content_hash, _PARSER_ANALYZER_VERSION, lang, json_dumps({"symbols": syms, "refs": refs, "edges": edges, "parse_outcome": diagnostic}, ensure_ascii=False, separators=(",", ":")), now)
            else:
                syms, refs, edges, diagnostic = parsed
                row_blob = None
            return path, content_hash, lang, syms, refs, edges, row_blob

        # Tree-sitter parsers are shared per language and guarded by one lock.
        # Threading here queues parses behind that lock and adds scheduler cost;
        # the bounded batch SQL write is where this path gains throughput.
        parsed_candidates = [_parse_candidate(c) for c in candidates]

        for path, content_hash, lang, syms, refs, edges, row_blob in parsed_candidates:
            if row_blob is not None:
                parse_blob_rows.append(row_blob)
            paths_to_clean.append((c_root, path))
            file_stat = file_stats.get(path)
            stat_is_current = bool(
                file_stat is not None
                and self._file_stat_is_current((base / path).resolve(strict=False), file_stat)
            )
            files_to_insert.append((
                c_root, path, content_hash, _PARSER_ANALYZER_VERSION, lang, now,
                file_stat.st_mtime_ns if stat_is_current else None,
                file_stat.st_size if stat_is_current else None,
            ))
            syms_to_insert.extend((c_root, path, x["name"], x["kind"], x["line"], x["end_line"], x.get("container", ""), x.get("name_path", x["name"]), x.get("signature", ""), x.get("access", "public"), x.get("docstring", "")) for x in syms)
            refs_to_insert.extend((c_root, path, x["name"], x["line"], x.get("kind", "call")) for x in refs)
            edges_to_insert.extend(
                (
                    c_root, x["src"], x["dst"], _edge_endpoint_name(x["src"]),
                    _edge_endpoint_name(x["dst"]), x.get("kind", "reference"), path, x["line"],
                )
                for x in edges
            )

        single_delta = len(files_to_insert) == 1 and not deleted_paths
        metadata_update: dict[str, Any] = {}
        if files_to_insert or deleted_paths:
            with self._lock, closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if parse_blob_rows:
                    con.executemany("INSERT OR REPLACE INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) VALUES(?,?,?,?,?)", parse_blob_rows)
                _IDX_TABLES = frozenset({"symbols", "refs", "edges"})
                if deleted_paths:
                    con.executemany("DELETE FROM files WHERE root=? AND path=?", deleted_paths)
                    for table in ("symbols", "refs", "edges"):
                        assert table in _IDX_TABLES
                        con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", deleted_paths)  # noqa: S608
                if not single_delta:
                    for table in ("symbols", "refs", "edges"):
                        assert table in _IDX_TABLES
                        con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", paths_to_clean)
                con.executemany(
                    "INSERT OR REPLACE INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    files_to_insert,
                )
                if single_delta:
                    changed_path = str(files_to_insert[0][1])
                    metadata_update = {
                        "symbols": self._sync_file_rows(con, "symbols", c_root, changed_path,
                                                        [tuple(row[2:]) for row in syms_to_insert]),
                        "refs": self._sync_file_rows(con, "refs", c_root, changed_path,
                                                     [tuple(row[2:]) for row in refs_to_insert]),
                        "edges": self._sync_file_rows(con, "edges", c_root, changed_path,
                                                      [(row[1], row[2], row[3], row[4], row[5], row[7])
                                                       for row in edges_to_insert]),
                    }
                else:
                    con.executemany("INSERT OR REPLACE INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) VALUES(?,?,?,?,?,?,?,?,?,?,?)", syms_to_insert)
                    con.executemany("INSERT INTO refs(root,path,name,line,kind) VALUES(?,?,?,?,?)", refs_to_insert)
                    con.executemany(
                        "INSERT INTO edges(root,src,dst,src_name,dst_name,kind,path,line) VALUES(?,?,?,?,?,?,?,?)",
                        edges_to_insert,
                    )
                con.commit()
            self._advance_query_cache_generation()
        self._status_cache.pop(c_root, None)
        indexed_paths = [str(item[1]) for item in files_to_insert]
        return {
            "success": True, "files_processed": len(files_to_insert), "cached": cached,
            "symbols": len(syms_to_insert), "refs": len(refs_to_insert), "edges": len(edges_to_insert),
            "parse_blob_hits": len(candidates) - len(parse_blob_rows),
            "parse_outcomes": self._parse_outcomes_for_paths(c_root, indexed_paths),
            "metadata_update": metadata_update,
        }

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [t.lower() for t in tokenize_query_terms(query, min_len=2, max_terms=16)]

    def _candidate_freshness(self, root: str, paths: list[str], *, content_hash: bool = True) -> dict[str, Any]:
        unique_paths = list(dict.fromkeys(self._norm_rel(path) for path in paths if path))
        if not unique_paths:
            return {"status": "no_candidates", "scope": "returned_symbol_candidates", "checked_paths": 0, "stale_paths": [], "unknown_paths": [], "complete": False}
        resolved_root = canonical_root(root)
        try:
            with self._lock, closing(self._connect()) as con:
                rows = []
                con.execute("BEGIN")
                for batch in sqlite_batches(unique_paths):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(con.execute(
                        f"SELECT path,content_hash,mtime_ns,size_bytes FROM files WHERE root=? AND path IN ({placeholders})",
                        (resolved_root, *batch),
                    ).fetchall())
            file_hashes = {str(row["path"]): str(row["content_hash"] or "") for row in rows}
            file_stats = {str(row["path"]): (row["mtime_ns"], row["size_bytes"]) for row in rows}
        except sqlite3.DatabaseError:
            return {"status": "verification_failed", "scope": "returned_symbol_candidates", "checked_paths": 0, "stale_paths": [], "unknown_paths": unique_paths[:64], "complete": False}

        reader = getattr(self.repo_tools, "_read_snapshot", None)
        verified: list[str] = []
        stale: list[str] = []
        unknown: list[str] = []
        for rel_path in unique_paths:
            indexed_hash = file_hashes.get(rel_path)
            if not indexed_hash:
                unknown.append(rel_path)
                continue
            target = Path(resolved_root, rel_path).resolve(strict=False)
            try:
                target.relative_to(Path(resolved_root))
            except ValueError:
                unknown.append(rel_path)
                continue
            if not target.is_file():
                stale.append(rel_path)
                continue
            if not content_hash:
                try:
                    current_stat = target.stat()
                    indexed_stat = file_stats[rel_path]
                    if None in indexed_stat:
                        unknown.append(rel_path)
                    elif (current_stat.st_mtime_ns, current_stat.st_size) == indexed_stat:
                        verified.append(rel_path)
                    else:
                        stale.append(rel_path)
                except OSError:
                    unknown.append(rel_path)
                continue
            if not callable(reader):
                unknown.append(rel_path)
                continue
            try:
                current_hash, _lines = reader(target, force=True)
            except (OSError, ValueError):
                unknown.append(rel_path)
                continue
            (verified if str(current_hash) == indexed_hash else stale).append(rel_path)
        status = ("stale_candidates" if stale else
                  ("verified_current_candidates" if content_hash else "stat_current_candidates")
                  if len(verified) == len(unique_paths) else "verification_incomplete")
        return {
            "status": status,
            "scope": "returned_symbol_candidates",
            "checked_paths": len(verified) + len(stale),
            "verified_paths": verified[:64],
            "stale_paths": stale[:64],
            "unknown_paths": unknown[:64],
            "complete": False,
            "verification": "content_hash" if content_hash else "mtime_ns_and_size",
        }

    def _apply_query_freshness(self, result: dict[str, Any], *, verify_content: bool) -> dict[str, Any]:
        paths = list(dict.fromkeys(str(item["path"]) for item in result.get("symbols", []) if item.get("path")))
        root = str(result["root"])
        freshness = self._candidate_freshness(root, paths, content_hash=verify_content)
        status = freshness.get("status")
        current = status in {"verified_current_candidates", "stat_current_candidates"}
        result["freshness"] = freshness
        if status == "stale_candidates":
            result["stale"] = True
        elif current:
            result["stale"] = False
        else:
            # Unknown freshness is described by freshness.status/unknown_paths.
            # The optional public envelope flag is boolean, never JSON null.
            result.pop("stale", None)
        factor = 1.0 if status == "verified_current_candidates" else 0.5 if current else 0.0
        coverage = float(result.get("coverage", {}).get("query_term_coverage", 0.0))
        support = min(1.0, len(result.get("symbols", [])) / 3.0)
        confidence = round(0.65 * coverage + 0.20 * support + 0.15 * factor, 3) if paths else 0.0
        result["confidence"] = min(confidence, 0.90 if current else 0.50) if status != "verified_current_candidates" else confidence
        callback = getattr(self, "_reindex_callback", None)
        queued = 0
        if callable(callback):
            for path in freshness.get("stale_paths", []):
                key = stable_hash({"root": root, "path": path})
                if self._reindex_notifications.get(key) is not None:
                    continue
                self._reindex_notifications.set(key, True)
                try:
                    queued += int(bool(callback(str(Path(root, path)))))
                except Exception:
                    logging.getLogger(__name__).debug("stale candidate notification failed", exc_info=True)
        freshness["reindex_notifications_queued"] = queued
        return result


    def _parse_outcomes_for_paths(self, root: str, paths: list[str]) -> dict[str, Any]:
        unique_paths = list(dict.fromkeys(self._norm_rel(path) for path in paths if path))
        counts = {"syntax_error_files": 0, "fallback_files": 0, "unavailable_files": 0, "failed_files": 0, "unknown_files": 0}
        diagnostics: list[dict[str, Any]] = []
        if not unique_paths:
            return {"scope": "returned_symbol_candidates", "files_examined": 0, **counts, "diagnostics": [], "diagnostics_truncated": False, "complete": False}
        try:
            with self._lock, closing(self._connect()) as con:
                rows = []
                con.execute("BEGIN")
                for batch in sqlite_batches(unique_paths):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(con.execute(
                        f"SELECT f.path,f.language,p.payload_json FROM files f LEFT JOIN parse_blobs p "
                        f"ON p.content_hash=f.content_hash AND p.language=f.language AND p.analyzer_version=? "
                        f"WHERE f.root=? AND f.path IN ({placeholders})",
                        (_PARSER_ANALYZER_VERSION, canonical_root(root), *batch),
                    ).fetchall())
        except sqlite3.DatabaseError:
            return {"scope": "returned_symbol_candidates", "files_examined": 0, **counts, "unknown_files": len(unique_paths), "diagnostics": [], "diagnostics_truncated": False, "complete": False}
        for row in rows:
            diagnostic: Any = {}
            if row["payload_json"]:
                try:
                    payload = json.loads(str(row["payload_json"]))
                    diagnostic = payload.get("parse_outcome", {}) if isinstance(payload, dict) else {}
                except (TypeError, ValueError):
                    diagnostic = {}
            if not isinstance(diagnostic, dict) or not diagnostic:
                counts["unknown_files"] += 1
                diagnostics.append({"path": str(row["path"]), "language": str(row["language"] or "generic"), "status": "unknown"})
                continue
            state = str(diagnostic.get("status") or "unknown")
            if state == "syntax_error":
                counts["syntax_error_files"] += 1
            if bool(diagnostic.get("fallback_used")):
                counts["fallback_files"] += 1
            if str(diagnostic.get("fallback_reason") or "") == "parser_unavailable":
                counts["unavailable_files"] += 1
            if str(diagnostic.get("fallback_reason") or "") == "parser_error":
                counts["failed_files"] += 1
            if state != "ok":
                diagnostics.append({
                    "path": str(row["path"]), "language": str(row["language"] or "generic"),
                    "status": state, "fallback_used": bool(diagnostic.get("fallback_used")),
                    "fallback_reason": str(diagnostic.get("fallback_reason") or ""),
                    "syntax_error_count": int(diagnostic.get("syntax_error_count", 0) or 0),
                    "syntax_error_count_truncated": bool(diagnostic.get("syntax_error_count_truncated", False)),
                })
        return {
            "scope": "returned_symbol_candidates", "files_examined": len(rows), **counts,
            "diagnostics": diagnostics[:64], "diagnostics_truncated": len(diagnostics) > 64,
            "complete": len(rows) == len(unique_paths),
        }

    def query(
        self,
        root: str,
        query: str,
        limit: int = 24,
        offset: int = 0,
        *,
        verify_freshness: bool = False,
    ) -> dict[str, Any]:
        """Search the built-in symbol index without requiring an external model.

        The endpoint intentionally returns compact symbol metadata. Agents can follow
        with ``find_symbol``/``inspect_symbol`` when source bodies are actually needed.
        """
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {
                "success": False, "error": bounds_error,
                "status_code": 400,
                "limit": limit if isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_PAGE_SIZE else None,
                "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                "total_matches": 0, "has_more": False, "symbols": [],
            }
        limit = max(1, min(limit, int(self.config.get("code_index", {}).get("max_query_results", 30))))
        resolved_root = canonical_root(root)
        if not Path(resolved_root).is_dir():
            return {
                "success": False, "root": resolved_root, "error": "root directory does not exist",
                "stale_root": True, "confidence": 0.0,
                "total_matches": 0, "has_more": False, "limit": limit, "offset": offset,
                "coverage": {"query_term_count": 0, "matched_term_count": 0, "query_term_coverage": 0.0, "complete": False, "scope": "no_candidates"},
                "freshness": {"status": "stale_root", "scope": "repository", "checked_paths": 0, "stale_paths": [], "unknown_paths": [], "complete": False},
                "truncated": False,
                "truncation": {"returned_count": 0, "observed_match_count": 0, "candidate_cap_reached": False},
                "parse_outcomes": {"scope": "no_candidates", "files_examined": 0, "syntax_error_files": 0, "fallback_files": 0, "unavailable_files": 0, "failed_files": 0, "unknown_files": 0, "complete": False},
            }
        exact_identifier = query if query.isidentifier() and query.isascii() else None
        terms = self._query_terms(query)
        if not terms and exact_identifier is not None:
            terms = [exact_identifier.lower()]
        if not terms:
            return {
                "success": True, "root": resolved_root, "query": query, "terms": [],
                "matches_count": 0, "total_matches": 0, "has_more": False,
                "returned_count": 0, "symbols": [], "confidence": 0.0,
                "limit": limit, "offset": offset,
                "coverage": {"query_term_count": 0, "matched_term_count": 0, "query_term_coverage": 0.0, "complete": False, "scope": "indexed_symbol_candidates"},
                "freshness": {"status": "not_checked", "scope": "returned_symbol_candidates", "checked_paths": 0, "stale_paths": [], "unknown_paths": [], "complete": False},
                "truncated": False,
                "parse_outcomes": {"scope": "returned_symbol_candidates", "files_examined": 0, "unknown_files": 0, "complete": False},
            }
        cache_generation = self._cache_generation()
        cache_key = stable_hash({
            "root": resolved_root, "query": query, "terms": terms, "limit": limit, "offset": offset,
            "generation": cache_generation,
        })
        cached = None if verify_freshness else self._query_l1.get(cache_key)
        if isinstance(cached, dict):
            return self._apply_query_freshness(copy.deepcopy(cached), verify_content=False)

        def score_match(name: Any, name_path: Any, container: Any, path: Any) -> float:
            name_l = str(name or "").lower()
            name_path_l = str(name_path or "").lower()
            container_l = str(container or "").lower()
            path_l = str(path or "").lower()
            score = 0.0
            for term in terms:
                if name_l == term:
                    score += 8.0
                elif name_l.startswith(term):
                    score += 5.0
                elif term in name_l:
                    score += 3.0
                elif term in name_path_l or term in container_l:
                    score += 2.0
                elif exact_identifier is None and term in path_l:
                    score += 1.0
            return score

        score_sql = "hub_code_index_score(name,name_path,container,path)"
        ignored_paths = []
        for directory in sorted(getattr(self.repo_tools, "ignore_dirs", ())):
            name = str(directory).strip().strip("/\\").lower()
            if name and "/" not in name and "\\" not in name:
                ignored_paths.append(name)
        ignored_path_sql = " AND ".join(
            "instr('/' || lower(path) || '/', ?) = 0" for _ in ignored_paths
        )
        root_archive_sql = _root_archive_path_sql()
        filters_sql = (
            "root=? AND " + score_sql + " > 0"
            + " AND " + root_archive_sql
            + (" AND " + ignored_path_sql if ignored_path_sql else "")
        )
        args: list[Any] = [resolved_root, *(f"/{name}/" for name in ignored_paths)]
        count_sql = "SELECT COUNT(*) FROM symbols WHERE " + filters_sql
        sql = (
            "SELECT path,name,kind,line,end_line,container,name_path,signature,access,docstring,"
            + score_sql + " AS _score FROM symbols WHERE " + filters_sql
            + " ORDER BY _score DESC,path ASC,line ASC,name_path ASC LIMIT ? OFFSET ?"
        )
        with self._lock, closing(self._connect()) as con:
            con.create_function("hub_code_index_score", 4, score_match, deterministic=True)
            total_matches = int(con.execute(count_sql, args).fetchone()[0])
            rows = con.execute(sql, [*args, limit, offset]).fetchall()
        candidate_truncated = False
        candidate_limit = None

        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            name = str(row["name"])
            name_l = name.lower()
            name_path = str(row["name_path"] or "")
            haystack = " ".join((name_l, name_path.lower(), str(row["container"] or "").lower(), str(row["path"]).lower()))
            score = 0.0
            matched_terms: list[str] = []
            for term in terms:
                if name_l == term:
                    score += 8.0
                    matched_terms.append(term)
                elif name_l.startswith(term):
                    score += 5.0
                    matched_terms.append(term)
                elif term in name_l:
                    score += 3.0
                    matched_terms.append(term)
                elif term in haystack:
                    score += 1.0
                    matched_terms.append(term)
            item = {
                "name": name,
                "name_path": name_path,
                "kind": str(row["kind"]),
                "path": str(row["path"]),
                "line": int(row["line"]),
                "end_line": int(row["end_line"] or row["line"]),
                "container": str(row["container"] or ""),
                "signature": str(row["signature"] or ""),
                "access": str(row["access"] or "public"),
                "score": round(score, 2),
                "matched_terms": matched_terms,
            }
            ranked.append((score, item))
        symbols = [item for _, item in ranked]
        matched_terms = sorted({term for item in symbols for term in item["matched_terms"]})
        term_coverage = round(len(matched_terms) / max(1, len(terms)), 3)
        has_more = offset + len(symbols) < total_matches
        truncated = has_more
        candidate_paths = list(dict.fromkeys(str(item["path"]) for item in symbols if item.get("path")))
        freshness = {
            "status": "not_checked", "scope": "returned_symbol_candidates", "checked_paths": 0,
            "stale_paths": [], "unknown_paths": candidate_paths[:64], "complete": False,
        }
        parse_outcomes = self._parse_outcomes_for_paths(resolved_root, candidate_paths)
        out = {
            "success": True,
            "root": resolved_root,
            "query": query,
            "terms": terms,
            "matches_count": len(symbols),
            "total_matches": total_matches,
            "has_more": has_more,
            "limit": limit,
            "offset": offset,
            "observed_match_count": total_matches,
            "returned_count": len(symbols),
            "symbols": symbols,
            "confidence": 0.0,
            "confidence_basis": "returned_query_term_coverage_result_support_and_candidate_freshness",
            "coverage": {
                "query_term_count": len(terms),
                "matched_term_count": len(matched_terms),
                "matched_terms": matched_terms,
                "query_term_coverage": term_coverage,
                "candidate_match_count": total_matches,
                "returned_symbol_count": len(symbols),
                "complete": False,
                "scope": "indexed_symbol_candidates",
            },
            "freshness": freshness,
            "truncated": truncated,
            "truncation": {
                "result_limit": limit,
                "returned_count": len(symbols),
                "observed_match_count": total_matches,
                "candidate_cap": candidate_limit,
                "candidate_cap_reached": candidate_truncated,
            },
            "parse_outcomes": parse_outcomes,
        }
        self._apply_query_freshness(out, verify_content=verify_freshness)
        if not verify_freshness:
            self._query_l1.set(cache_key, out)
        return out

    def indexed_skeleton(self, root: str, path: str) -> dict[str, Any]:
        """Render an authorized, stat-current symbol outline without reading source."""
        if not Path(root).is_absolute() or not path:
            return {"success": False, "terminal": True, "retryable": False,
                    "error": "indexed skeleton requires an absolute root and file path"}
        base = Path(canonical_root(root))
        try:
            target = (base / path).resolve(strict=True)
            relative = target.relative_to(base).as_posix()
            before = target.stat()
            if not target.is_file():
                raise ValueError("not a regular file")
        except (OSError, ValueError, RuntimeError):
            return {"success": False, "terminal": True, "retryable": False, "error": "invalid source path"}
        api, project_context = self._project_config_context(str(base))
        settings = project_context.settings if project_context is not None else None
        if api is not None and settings is not None and (
            not api.phase_is_allowed(settings, "call_graph")
            or not api.path_is_allowed(str(base), target, settings, phase="call_graph", size_bytes=before.st_size)
        ):
            return {"success": False, "terminal": True, "retryable": False,
                    "error_code": "project_path_excluded", "error": "project policy excludes this indexed path"}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            metadata = con.execute(
                "SELECT mtime_ns,size_bytes,language FROM files WHERE root=? AND path=?", (str(base), relative),
            ).fetchone()
            if metadata is None or metadata[0] != before.st_mtime_ns or metadata[1] != before.st_size:
                return {"success": False, "stale": metadata is not None, "terminal": True, "retryable": False,
                        "error_code": "indexed_skeleton_unavailable", "error": "index this file or supply source text explicitly"}
            rows = con.execute(
                "SELECT name,kind,name_path,signature,line,end_line FROM symbols WHERE root=? AND path=? "
                "ORDER BY line,name LIMIT 2001", (str(base), relative),
            ).fetchall()
        if not self._file_stat_is_current(target, before):
            return {"success": False, "stale": True, "terminal": True, "retryable": False,
                    "error_code": "indexed_skeleton_changed", "error": "file changed during outline retrieval"}
        lines: list[str] = []
        used, truncated = 0, len(rows) > 2000
        for row in rows[:2000]:
            signature = str(row["signature"] or f"{row['kind']} {row['name']}").splitlines()[0]
            indent = "    " * min(8, str(row["name_path"] or "").count("/"))
            text = f"{indent}{signature}  # lines {row['line']}-{row['end_line']}"
            if used + len(text) + 1 > 64_000:
                truncated = True
                break
            lines.append(text)
            used += len(text) + 1
        skeleton = "\n".join(lines)
        return {"success": True, "path": relative, "source": "code_index", "language": metadata[2],
                "skeleton_code": skeleton, "skeleton_chars": len(skeleton), "source_size_bytes": before.st_size,
                "skeleton_format": "symbol_outline", "symbols_returned": len(lines), "truncated": truncated,
                "freshness_verification": "mtime_ns_and_size", "imports_included": False,
                "omissions": ["imports", "decorators", "docstrings", "bodies"]}

    def symbol_bounds_at(
        self, root: str, path: str, line: int, *, content_hash: str
    ) -> tuple[int, int] | None:
        """Return enclosing body bounds only for the caller's current source bytes."""
        with self._lock, closing(self._connect()) as con:
            row = con.execute(
                "SELECT s.line,s.end_line FROM symbols s JOIN files f "
                "ON f.root=s.root AND f.path=s.path "
                "WHERE s.root=? AND s.path=? AND f.content_hash=? "
                "AND s.kind IN ('class','function','method','constructor','enum','interface','struct','trait','impl') "
                "AND s.line<=? AND s.end_line>=? "
                "ORDER BY (s.end_line-s.line),s.line DESC LIMIT 1",
                (canonical_root(root), self._norm_rel(path), content_hash, line, line),
            ).fetchone()
        return (int(row[0]), int(row[1])) if row is not None else None

    def find_symbol(
        self,
        root: str,
        name_path_pattern: str,
        depth: int = 0,
        include_body: bool = False,
        include_info: bool = True,
        include_kinds: list[str] | None = None,
        exclude_kinds: list[str] | None = None,
        substring_matching: bool = False,
        relative_path: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        pat = name_path_pattern.strip()
        if not pat:
            return {"success": False, "error": "name_path_pattern required"}

        cache_generation = self._cache_generation()
        cache_key = stable_hash({
            "root": resolved_root,
            "pattern": pat,
            "depth": depth,
            "include_body": include_body,
            "include_info": include_info,
            "include_kinds": include_kinds,
            "exclude_kinds": exclude_kinds,
            "substring_matching": substring_matching,
            "relative_path": relative_path,
            "limit": limit,
            "generation": cache_generation,
        })
        cached = self._symbol_l1.get(cache_key)
        if isinstance(cached, dict):
            return copy.deepcopy(cached)

        where = ["root = ?", _root_archive_path_sql("path")]
        args: list[Any] = [resolved_root]

        if relative_path:
            norm_path = relative_path.replace("\\", "/").strip("/")
            if "." in Path(norm_path).name:
                where.append("path = ?")
                args.append(norm_path)
            else:
                where.append("path LIKE ?")
                args.append(f"{norm_path}/%")

        if include_kinds:
            where.append("kind IN (SELECT value FROM json_each(?))")
            args.append(json_dumps(list(include_kinds)))

        if exclude_kinds:
            where.append("kind NOT IN (SELECT value FROM json_each(?))")
            args.append(json_dumps(list(exclude_kinds)))

        if substring_matching:
            where.append("(name_path LIKE ? OR name LIKE ?)")
            args.extend([f"%{pat}%", f"%{pat}%"])
        elif "/" in pat:
            where.append("(name_path = ? OR name_path LIKE ?)")
            args.extend([pat, f"%/{pat}"])
        else:
            where.append("(lower(name) = lower(?) OR name_path LIKE ? OR lower(name) LIKE ?)")
            args.extend([pat, f"%/{pat}", f"%{pat.lower()}%"])

        sql = f"SELECT path, name, kind, line, end_line, container, name_path, signature, access, docstring FROM symbols WHERE {' AND '.join(where)} ORDER BY path, line LIMIT ?"
        args.append(limit)

        with self._lock, closing(self._connect()) as con:
            rows = con.execute(sql, args).fetchall()

        results: list[dict[str, Any]] = []
        base_path = Path(resolved_root)

        for r in rows:
            p, name, kind, line = str(r["path"]), str(r["name"]), str(r["kind"]), int(r["line"])
            end_line = int(r["end_line"] or r["line"])
            name_path = str(r["name_path"])
            container = str(r["container"] or "")
            sig = str(r["signature"] or "")
            doc = str(r["docstring"] or "")

            item: dict[str, Any] = {
                "name": name,
                "name_path": name_path,
                "kind": kind,
                "path": p,
                "line": line,
                "end_line": end_line,
                "container": container,
            }

            if include_info:
                item["signature"] = sig
                item["docstring"] = doc
                item["access"] = str(r["access"] or "public")

            if include_body:
                file_full = base_path / p
                if file_full.is_file():
                    try:
                        _digest, flines = self.repo_tools._read_snapshot(
                            file_full, max_bytes=self.repo_tools.max_file_bytes,
                        )
                        item["body"] = "\n".join(flines[max(0, line - 1):min(len(flines), end_line)])
                    except Exception:
                        item["body"] = ""

            if depth > 0 and kind in {"class", "interface", "struct"}:
                with self._lock, closing(self._connect()) as con:
                    child_rows = con.execute(
                        f"SELECT path, name, kind, line, end_line, name_path, signature FROM symbols WHERE root=? AND path=? AND container=? AND {_root_archive_path_sql('path')} LIMIT 50",
                        (resolved_root, p, name),
                    ).fetchall()
                    item["children"] = [
                        {
                            "name": str(cr["name"]),
                            "name_path": str(cr["name_path"]),
                            "kind": str(cr["kind"]),
                            "line": int(cr["line"]),
                            "end_line": int(cr["end_line"] or cr["line"]),
                            "signature": str(cr["signature"] or ""),
                        }
                        for cr in child_rows
                    ]

            results.append(item)

        result = {
            "success": True,
            "root": resolved_root,
            "pattern": pat,
            "matches_count": len(results),
            "symbols": results,
        }
        self._symbol_l1.set(cache_key, copy.deepcopy(result))
        return result

    def find_declaration(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        res = self.find_symbol(root, symbol_name, depth=0, include_body=True, include_info=True, relative_path=path, limit=5)
        symbols = res.get("symbols", [])
        if not symbols:
            return {"success": False, "error": f"Declaration of '{symbol_name}' not found"}
        return {"success": True, "declaration": symbols[0]}

    def find_implementations(
        self, root: str, symbol_name: str, path: str | None = None, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        if not isinstance(symbol_name, str) or not symbol_name.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol cannot be empty"}
        resolved_root = canonical_root(root)
        where = f"root=? AND {_root_archive_path_sql('path')} AND (lower(dst)=lower(?) OR dst LIKE ?) AND kind IN ('inherits', 'implements')"
        args: list[Any] = [resolved_root, symbol_name, f"%{symbol_name}%"]
        if path:
            where += " AND path=?"
            args.append(path.replace("\\", "/").strip("/"))
        try:
            with self._lock, closing(self._connect()) as con:
                deadline = time.monotonic() + 1.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                edges = con.execute(
                    f"SELECT src, dst, kind, path, line FROM edges WHERE {where} ORDER BY path, line, src, dst, kind LIMIT ? OFFSET ?",
                    (*args, limit + 1, offset),
                ).fetchall()
                con.set_progress_handler(None, 0)
        except sqlite3.DatabaseError as exc:
            busy = is_busy_error(exc)
            return {
                "success": False, "status_code": 503 if busy else 500,
                "terminal": not busy, "retryable": busy, "error": str(exc), "busy": busy,
                "implementations": [], "count": 0, "offset": offset, "limit": limit,
                "coverage": {"complete": False, "returned": 0, "offset": offset, "limit": limit, "scope": "indexed_edges"},
                "freshness": {"status": "not_checked"},
            }

        implementations: list[dict[str, Any]] = []
        has_more = len(edges) > limit
        for e in edges[:limit]:
            src_name = str(e["src"])
            p = str(e["path"])
            ln = int(e["line"])
            implementations.append({
                "implementer": src_name,
                "target": str(e["dst"]),
                "relationship": str(e["kind"]),
                "path": p,
                "line": ln,
            })

        result = {
            "success": True,
            "symbol": symbol_name,
            "implementations_count": len(implementations),
            "implementations": implementations,
            "count": len(implementations),
            "offset": offset,
            "limit": limit,
            "returned_count": len(implementations),
            "has_more": has_more,
            "truncated": has_more,
            "coverage": {"complete": offset == 0 and not has_more, "returned": len(implementations), "limit": limit, "offset": offset, "scope": "indexed_edges"},
            "freshness": {"status": "not_checked"},
        }
        if not has_more and (offset == 0 or implementations):
            result["total_matches"] = offset + len(implementations)
        if has_more:
            result["next_offset"] = offset + len(implementations)
        return result

    def find_referencing_symbols(self, root: str, symbol_name: str, path: str | None = None) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        where = f"root=? AND {_root_archive_path_sql('path')} AND (lower(name)=lower(?) OR name LIKE ?)"
        args: list[Any] = [resolved_root, symbol_name, f"%{symbol_name}%"]
        if path:
            where += " AND path=?"
            args.append(path.replace("\\", "/").strip("/"))
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT path, name, line, kind FROM refs WHERE {where} ORDER BY path, line LIMIT 100",
                tuple(args),
            ).fetchall()

        references = [
            {"path": str(r["path"]), "symbol": str(r["name"]), "line": int(r["line"]), "kind": str(r["kind"])}
            for r in rows
        ]

        return {
            "success": True,
            "symbol": symbol_name,
            "references_count": len(references),
            "references": references,
        }

    def get_symbols_overview(self, root: str, path: str, depth: int = 1) -> dict[str, Any]:
        resolved_root = canonical_root(root)
        norm_path = path.replace("\\", "/").strip("/")

        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT name, kind, line, end_line, container, name_path, signature, access FROM symbols WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line",
                (resolved_root, norm_path),
            ).fetchall()

        overview: list[dict[str, Any]] = []
        for r in rows:
            overview.append({
                "name": str(r["name"]),
                "kind": str(r["kind"]),
                "line": int(r["line"]),
                "end_line": int(r["end_line"] or r["line"]),
                "container": str(r["container"] or ""),
                "name_path": str(r["name_path"] or r["name"]),
                "signature": str(r["signature"] or ""),
                "access": str(r["access"] or "public"),
            })

        return {
            "success": True,
            "path": norm_path,
            "symbols_count": len(overview),
            "symbols": overview,
        }

    def get_diagnostics_for_file(self, root: str, path: str) -> dict[str, Any]:
        resolved_root = Path(canonical_root(root)).resolve()
        target = (resolved_root / path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return {"success": False, "error": f"path escapes root: {path}"}
        if not target.is_file():
            return {"success": False, "error": f"file not found: {path}"}

        errors: list[dict[str, Any]] = []
        lang = self._lang(path)

        if lang == "python":
            try:
                _digest, lines = self.repo_tools._read_snapshot(
                    target, max_bytes=self.repo_tools.max_file_bytes,
                )
                txt = "\n".join(lines)
                ast.parse(txt, filename=str(target))
            except FileTooLargeError:
                return {
                    "success": True,
                    "path": path,
                    "errors": [],
                    "skipped": True,
                    "reason": "file exceeds max indexable size",
                }
            except (SyntaxError, OSError) as e:
                errors.append({
                    "line": getattr(e, "lineno", 1) or 1,
                    "column": getattr(e, "offset", 1) or 1,
                    "severity": "ERROR",
                    "message": str(getattr(e, "msg", e)),
                    "source": "python-ast",
                })
        elif lang == "json":
            try:
                txt = target.read_text(encoding="utf-8", errors="replace")
                json.loads(txt)
            except (json.JSONDecodeError, OSError) as e:
                errors.append({
                    "line": getattr(e, "lineno", 1),
                    "column": getattr(e, "colno", 1),
                    "severity": "ERROR",
                    "message": str(getattr(e, "msg", e)),
                    "source": "json-parser",
                })

        return {
            "success": True,
            "path": path,
            "clean": len(errors) == 0,
            "diagnostics_count": len(errors),
            "diagnostics": errors,
        }

    @staticmethod
    def _norm_rel(path: str) -> str:
        return str(path or "").replace("\\", "/").strip("/")

    @staticmethod
    def _is_test_path(path: str) -> bool:
        low = "/" + str(path or "").replace("\\", "/").lower()
        name = Path(low).name
        stem = Path(low).stem
        return (
            "/test" in low or "/spec" in low or name.startswith("test_")
            or any(marker in stem for marker in ("_test", ".test", "_spec", ".spec"))
        )

    def file_summary(self, root: str, path: str, limit: int = 80) -> dict[str, Any]:
        """Return compact pre-indexed facts for one file without reopening source text."""
        resolved_root = canonical_root(root)
        norm_path = self._norm_rel(path)
        limit = max(1, min(int(limit), 250))
        try:
            with self._lock, closing(self._connect()) as con:
                file_row = con.execute(
                    f"SELECT content_hash,language,updated_at FROM files WHERE root=? AND path=? AND {_root_archive_path_sql('path')}",
                    (resolved_root, norm_path),
                ).fetchone()
                symbols = [dict(r) for r in con.execute(
                    f"SELECT name,kind,line,end_line,container,name_path,signature,access,docstring "
                    f"FROM symbols WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
                refs = [dict(r) for r in con.execute(
                    f"SELECT name,line,kind FROM refs WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
                edges = [dict(r) for r in con.execute(
                    f"SELECT src,dst,kind,line FROM edges WHERE root=? AND path=? AND {_root_archive_path_sql('path')} ORDER BY line LIMIT ?",
                    (resolved_root, norm_path, limit),
                ).fetchall()]
        except sqlite3.DatabaseError as exc:
            return {"success": False, "root": resolved_root, "path": norm_path, "error": str(exc), "busy": is_busy_error(exc)}
        if file_row is None:
            return {"success": False, "root": resolved_root, "path": norm_path, "indexed": False, "symbols": [], "references": [], "edges": []}
        return {
            "success": True,
            "root": resolved_root,
            "path": norm_path,
            "indexed": True,
            "content_hash": str(file_row["content_hash"] or ""),
            "language": str(file_row["language"] or "generic"),
            "updated_at": float(file_row["updated_at"] or 0.0),
            "symbols": symbols,
            "references": refs,
            "edges": edges,
        }

    def related_paths(self, root: str, query: str, limit: int = 30) -> list[str]:
        """Rank likely files entirely from the persistent code index.

        This is intentionally bounded and does not read repository files. It is used as
        a cheap candidate generator before lexical/RAG fallbacks.
        """
        resolved_root = canonical_root(root)
        terms = self._query_terms(query)
        if not terms:
            return []
        limit = max(1, min(int(limit), 100))
        scores: dict[str, float] = {}
        symbol_result = self.query(resolved_root, query, min(max(limit * 2, 20), 100))
        for item in symbol_result.get("symbols", []) if isinstance(symbol_result, dict) else []:
            path = self._norm_rel(str(item.get("path", "")))
            if path:
                scores[path] = scores.get(path, 0.0) + 8.0 + float(item.get("score", 0.0) or 0.0)

        clauses = " OR ".join("(lower(name) LIKE ? OR lower(path) LIKE ?)" for _ in terms)
        ref_args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            ref_args.extend([like, like])
        edge_clauses = " OR ".join("(lower(src) LIKE ? OR lower(dst) LIKE ? OR lower(path) LIKE ?)" for _ in terms)
        edge_args: list[Any] = [resolved_root]
        for term in terms:
            like = f"%{term}%"
            edge_args.extend([like, like, like])
        file_clauses = " OR ".join("lower(path) LIKE ?" for _ in terms)
        file_args: list[Any] = [resolved_root, *[f"%{term}%" for term in terms]]
        row_cap = max(80, limit * 12)
        try:
            with self._lock, closing(self._connect()) as con:
                for row in con.execute(
                    f"SELECT path,name,kind FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND ({clauses}) LIMIT ?",
                    (*ref_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + (4.0 if str(row["name"]).lower() in terms else 2.0)
                for row in con.execute(
                    f"SELECT path,src,dst,kind FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND ({edge_clauses}) LIMIT ?",
                    (*edge_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + (3.0 if str(row["kind"]) in {"imports", "inherits"} else 1.5)
                for row in con.execute(
                    f"SELECT path FROM files WHERE root=? AND {_root_archive_path_sql('path')} AND ({file_clauses}) LIMIT ?",
                    (*file_args, row_cap),
                ).fetchall():
                    path = self._norm_rel(str(row["path"]))
                    scores[path] = scores.get(path, 0.0) + 2.0
        except sqlite3.DatabaseError:
            pass
        return [path for path, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def prune(self, root: str, current_paths: list[str]) -> dict[str, Any]:
        """Remove stale per-workspace index rows in one short transaction."""
        resolved_root = canonical_root(root)
        current = {self._norm_rel(p) for p in current_paths if self._norm_rel(p)}
        try:
            with self._lock, closing(self._connect()) as con:
                indexed = {self._norm_rel(str(r[0])) for r in con.execute("SELECT path FROM files WHERE root=?", (resolved_root,)).fetchall()}
                stale = sorted(indexed - current)
                if not stale:
                    return {"success": True, "root": resolved_root, "pruned": 0}
                con.execute("BEGIN IMMEDIATE")
                pairs = [(resolved_root, path) for path in stale]
                for table in ("symbols", "refs", "edges", "files"):
                    con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", pairs)
                con.commit()
            self._advance_query_cache_generation()
            self._status_cache.pop(resolved_root, None)
            return {"success": True, "root": resolved_root, "pruned": len(stale), "paths": stale[:100]}
        except sqlite3.DatabaseError as exc:
            return {"success": False, "root": resolved_root, "pruned": 0, "error": str(exc), "busy": is_busy_error(exc)}

    def impact(self, root: str, changed_paths: list[str], max_symbols: int = 48, max_dependents: int = 30) -> dict[str, Any]:
        """Resolve changed symbols, dependents and likely tests from SQLite only."""
        resolved_root = canonical_root(root)
        changed = list(dict.fromkeys(self._norm_rel(p) for p in changed_paths if self._norm_rel(p)))
        max_symbols = max(1, min(int(max_symbols), 200))
        max_dependents = max(1, min(int(max_dependents), MAX_IMPACT_DEPENDENTS))
        if not changed:
            return {
                "success": True,
                "root": resolved_root,
                "changed_symbols": [],
                "likely_dependents": [],
                "suggested_tests": [],
                "confidence": 1.0,
                "coverage": {
                    "complete": True, "changed_files_count": 0, "indexed_changed_files": 0,
                    "dependent_candidate_count": 0, "dependent_count": 0,
                    "dependent_returned_count": 0, "dependents_truncated": False,
                },
                "freshness": {"status": "not_checked"},
                "truncated": False,
                "truncation": {"changed_symbols": False, "likely_dependents": False, "suggested_tests": False},
            }

        cache_generation = self._cache_generation()
        cache_key = stable_hash({
            "query": "impact",
            "root": resolved_root,
            "changed": changed,
            "max_symbols": max_symbols,
            "max_dependents": max_dependents,
            "generation": cache_generation,
        })
        cached = self._impact_result_l1.get(cache_key)
        if isinstance(cached, dict):
            return copy.deepcopy(cached)

        try:
            with self._lock, closing(self._connect()) as con:
                # Bound host parameters so large diffs remain safe on every supported SQLite build.
                indexed_rows: list[sqlite3.Row] = []
                symbol_rows: list[sqlite3.Row] = []
                symbols_truncated = False
                for chunk in sqlite_batches(changed):
                    placeholders = ",".join("?" for _ in chunk)
                    indexed_rows.extend(con.execute(
                        f"SELECT path FROM files WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders})",
                        (resolved_root, *chunk),
                    ).fetchall())
                    if len(symbol_rows) < max_symbols:
                        remaining = max_symbols - len(symbol_rows)
                        fetched_symbols = con.execute(
                            f"SELECT path,name,kind,line,name_path FROM symbols WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders}) ORDER BY path,line LIMIT ?",
                            (resolved_root, *chunk, remaining),
                        ).fetchall()
                        if len(fetched_symbols) == remaining:
                            has_more_symbols = con.execute(
                                f"SELECT 1 FROM symbols WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders}) ORDER BY path,line LIMIT 1 OFFSET ?",
                                (resolved_root, *chunk, remaining),
                            ).fetchone()
                            symbols_truncated = has_more_symbols is not None
                        symbol_rows.extend(fetched_symbols)
                    elif not symbols_truncated:
                        later_symbol = con.execute(
                            f"SELECT 1 FROM symbols WHERE root=? AND {_root_archive_path_sql('path')} AND path IN ({placeholders}) LIMIT 1",
                            (resolved_root, *chunk),
                        ).fetchone()
                        if later_symbol is not None:
                            symbols_truncated = True
                symbol_rows = symbol_rows[:max_symbols]
                changed_symbols = [
                    {"name": str(r["name"]), "name_path": str(r["name_path"] or r["name"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
                    for r in symbol_rows
                ]
                names = list(dict.fromkeys(str(r["name"]) for r in symbol_rows if str(r["name"])))
                dependent_scores: dict[str, dict[str, Any]] = {}
                dependent_source_truncated = False
                import_graph_truncated = False
                dependent_scan_limit = max(200, max_dependents * 20)
                if names:
                    name_placeholders = "SELECT value FROM json_each(?)"
                    name_params = (json_dumps(names),)
                    ref_rows = con.execute(
                        f"SELECT path,name,COUNT(*) AS mentions FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders}) GROUP BY path,name LIMIT ?",
                        (resolved_root, *name_params, dependent_scan_limit + 1),
                    ).fetchall()
                    if len(ref_rows) > dependent_scan_limit:
                        dependent_source_truncated = True
                    for r in ref_rows[:dependent_scan_limit]:
                        path = self._norm_rel(str(r["path"]))
                        if path in changed:
                            continue
                        item = dependent_scores.setdefault(path, {"path": path, "symbols": [], "mentions": 0})
                        name = str(r["name"])
                        if name not in item["symbols"] and len(item["symbols"]) < 8:
                            item["symbols"].append(name)
                        item["mentions"] += int(r["mentions"] or 0)
                    edge_rows = con.execute(
                        f"SELECT path,dst,kind FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders}) LIMIT ?",
                        (resolved_root, *name_params, dependent_scan_limit),
                    ).fetchall()
                    if len(edge_rows) == dependent_scan_limit:
                        has_more_edges = con.execute(
                            f"SELECT 1 FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders}) LIMIT 1 OFFSET ?",
                            (resolved_root, *name_params, dependent_scan_limit),
                        ).fetchone()
                        dependent_source_truncated = has_more_edges is not None
                    for r in edge_rows[:dependent_scan_limit]:
                        path = self._norm_rel(str(r["path"]))
                        if path in changed:
                            continue
                        item = dependent_scores.setdefault(path, {"path": path, "symbols": [], "mentions": 0})
                        dst = str(r["dst"])
                        if dst not in item["symbols"] and len(item["symbols"]) < 8:
                            item["symbols"].append(dst)
                        item["mentions"] += 2 if str(r["kind"]) in {"imports", "inherits"} else 1

                # Expand file-level import dependents transitively. Direct symbol
                # references alone miss tests of intermediate modules when a
                # shared module changes (shared -> core -> app -> tests).
                import_rows = con.execute(
                    f"SELECT path,dst FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND kind='imports' LIMIT ?",
                    (resolved_root, dependent_scan_limit + 1),
                ).fetchall()
                if len(import_rows) > dependent_scan_limit:
                    import_graph_truncated = True

                def module_aliases(value: str) -> set[str]:
                    normalized = str(value or "").replace("\\", "/").strip()
                    while normalized.startswith("./"):
                        normalized = normalized[2:]
                    normalized = normalized.lstrip(".")
                    suffixes = (".pyi", ".py", ".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs")
                    lowered = normalized.lower()
                    for suffix in suffixes:
                        if lowered.endswith(suffix):
                            normalized = normalized[:-len(suffix)]
                            break
                    normalized = normalized.strip("/")
                    if normalized.endswith("/__init__"):
                        normalized = normalized[:-len("/__init__")]
                    parts = [part for part in normalized.split("/") if part]
                    return {".".join(parts[index:]) for index in range(len(parts))}

                importers_by_module: dict[str, set[str]] = {}
                for import_row in import_rows[:dependent_scan_limit]:
                    importer_path = self._norm_rel(str(import_row["path"]))
                    for alias in module_aliases(str(import_row["dst"])):
                        importers_by_module.setdefault(alias, set()).add(importer_path)

                visited_paths = set(changed)
                frontier = list(changed)
                while frontier and len(visited_paths) <= dependent_scan_limit:
                    next_frontier: list[str] = []
                    for source_path in frontier:
                        for alias in module_aliases(source_path):
                            for importer_path in importers_by_module.get(alias, ()):
                                if importer_path in visited_paths:
                                    continue
                                visited_paths.add(importer_path)
                                next_frontier.append(importer_path)
                                item = dependent_scores.setdefault(
                                    importer_path, {"path": importer_path, "symbols": [], "mentions": 0}
                                )
                                item["mentions"] += 2
                    frontier = next_frontier
                if frontier:
                    import_graph_truncated = True

                dependent_candidate_count = len(dependent_scores)
                dependent_candidate_count_exact = (
                    not symbols_truncated and not dependent_source_truncated and not import_graph_truncated
                )
                if (
                    names and not symbols_truncated and dependent_source_truncated
                    and not import_graph_truncated and len(changed) <= 250
                ):
                    changed_placeholders = ",".join("?" for _ in changed)
                    path_generation = cache_generation
                    candidate_count_key = stable_hash({
                        "database": self._query_cache_generation_key,
                        "generation": path_generation,
                        "root": resolved_root,
                        "changed": sorted(set(changed)),
                        "names": sorted(set(names)),
                    })
                    cached_candidate_count = self._impact_candidate_count_l1.get(candidate_count_key)
                    if cached_candidate_count is not None:
                        dependent_candidate_count = int(cached_candidate_count)
                        dependent_candidate_count_exact = True
                    path_format_key = f"{self._query_cache_generation_key}:{path_generation}:{resolved_root}:{stable_hash(sorted(set(names)))}"
                    paths_are_canonical = (
                        self._impact_path_format_l1.get(path_format_key)
                        if cached_candidate_count is None else None
                    )
                    raw_candidate_count: int | None = None
                    if cached_candidate_count is None and paths_are_canonical is None:
                        raw_candidate_row = con.execute(
                            f"""
                            SELECT COUNT(*) AS candidate_count,
                                   MAX(CASE
                                       WHEN instr(path, char(92)) > 0
                                         OR substr(path, 1, 1) = '/'
                                         OR substr(path, -1, 1) = '/'
                                       THEN 1 ELSE 0
                                   END) AS has_noncanonical_path
                            FROM (
                                SELECT path FROM refs
                                WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders})
                                UNION
                                SELECT path FROM edges
                                WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders})
                            ) AS candidate_paths
                            WHERE path NOT IN ({changed_placeholders})
                            """,
                            (
                                resolved_root, *name_params,
                                resolved_root, *name_params,
                                *changed,
                            ),
                        ).fetchone()
                        if raw_candidate_row is not None:
                            raw_candidate_count = int(raw_candidate_row["candidate_count"] or 0)
                            paths_are_canonical = not bool(raw_candidate_row["has_noncanonical_path"])
                            self._impact_path_format_l1.set(path_format_key, paths_are_canonical)
                    if cached_candidate_count is None and paths_are_canonical is True:
                        if raw_candidate_count is None:
                            raw_candidate_row = con.execute(
                                f"""
                                SELECT COUNT(*) FROM (
                                    SELECT path FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders})
                                    UNION
                                    SELECT path FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders})
                                ) AS candidate_paths
                                WHERE path NOT IN ({changed_placeholders})
                                """,
                                (
                                    resolved_root, *name_params,
                                    resolved_root, *name_params,
                                    *changed,
                                ),
                            ).fetchone()
                            if raw_candidate_row is not None:
                                raw_candidate_count = int(raw_candidate_row[0])
                        if raw_candidate_count is not None:
                            dependent_candidate_count = raw_candidate_count
                            dependent_candidate_count_exact = True
                    elif cached_candidate_count is None and paths_are_canonical is False:
                        normalized_candidate_row = con.execute(
                            f"""
                            SELECT COUNT(*) FROM (
                                SELECT trim(replace(path, char(92), '/'), '/') AS normalized_path
                                FROM refs WHERE root=? AND {_root_archive_path_sql('path')} AND name IN ({name_placeholders})
                                UNION
                                SELECT trim(replace(path, char(92), '/'), '/') AS normalized_path
                                FROM edges WHERE root=? AND {_root_archive_path_sql('path')} AND dst IN ({name_placeholders})
                            )
                            WHERE normalized_path NOT IN ({changed_placeholders})
                            """,
                            (
                                resolved_root, *name_params,
                                resolved_root, *name_params,
                                *changed,
                            ),
                        ).fetchone()
                        if normalized_candidate_row is not None:
                            dependent_candidate_count = int(normalized_candidate_row[0])
                            dependent_candidate_count_exact = True
                    if cached_candidate_count is None and dependent_candidate_count_exact:
                        self._impact_candidate_count_l1.set(candidate_count_key, dependent_candidate_count)

                likely_dependents = sorted(dependent_scores.values(), key=lambda x: (-int(x["mentions"]), str(x["path"])))[:max_dependents]
                indexed_test_rows = con.execute(
                    f"SELECT path FROM files WHERE root=? AND {_root_archive_path_sql('path')} AND (lower(path) LIKE '%test%' OR lower(path) LIKE '%spec%') LIMIT 501",
                    (resolved_root,),
                ).fetchall()
                indexed_tests_truncated = len(indexed_test_rows) > 500
                indexed_tests = [self._norm_rel(str(r[0])) for r in indexed_test_rows[:500]]
        except sqlite3.DatabaseError as exc:
            return {
                "success": False,
                "root": resolved_root,
                "error": str(exc),
                "busy": is_busy_error(exc),
                "confidence": 0.0,
                "graph_complete": False,
                "changed_symbols": [],
                "likely_dependents": [],
                "suggested_tests": [],
                "coverage": {
                    "complete": False,
                    "changed_files_count": len(changed),
                    "indexed_changed_files": 0,
                    "dependent_candidate_count": 0,
                    "dependent_candidate_count_exact": False,
                    "dependent_count": None,
                    "dependent_returned_count": 0,
                    "dependents_truncated": None,
                },
                "freshness": {"status": "not_checked"},
                "truncated": False,
                "truncation": {"changed_symbols": False, "likely_dependents": False, "suggested_tests": False},
            }

        changed_stems = {Path(p).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "") for p in changed}
        symbol_names_l = [str(x["name"]).lower() for x in changed_symbols]
        test_scores: list[tuple[int, str]] = []
        for path in indexed_tests:
            stem = Path(path).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "")
            score = sum(3 for changed_stem in changed_stems if changed_stem and (changed_stem in stem or stem in changed_stem))
            score += sum(1 for name in symbol_names_l[:20] if name and name in path.lower())
            if score:
                test_scores.append((score, path))
        for item in likely_dependents:
            path = str(item["path"])
            if self._is_test_path(path):
                test_scores.append((max(1, int(item["mentions"])), path))
        sorted_test_scores = sorted(set(test_scores), key=lambda x: (-x[0], x[1]))
        suggested_tests_truncated = indexed_tests_truncated or len(sorted_test_scores) > 20
        suggested_tests = [{"path": path, "score": score} for score, path in sorted_test_scores[:20]]
        sorted_dependents = sorted(dependent_scores.values(), key=lambda x: (-int(x["mentions"]), str(x["path"])))
        dependents_truncated = (
            symbols_truncated or dependent_source_truncated or import_graph_truncated
            or len(sorted_dependents) > max_dependents
        )
        likely_dependents = sorted_dependents[:max_dependents]
        indexed_count = len(indexed_rows)
        changed_file_coverage = indexed_count / max(1, len(changed))
        confidence = round(min(0.98, 0.35 + 0.60 * changed_file_coverage + (0.03 if changed_symbols else 0.0)), 3)
        truncation = {
            "changed_symbols": symbols_truncated,
            "likely_dependents": dependents_truncated,
            "suggested_tests": suggested_tests_truncated,
        }
        truncated = any(truncation.values())
        result = {
            "success": True,
            "root": resolved_root,
            "changed_symbols": changed_symbols,
            "likely_dependents": likely_dependents,
            "suggested_tests": suggested_tests,
            "confidence": confidence,
            "indexed_changed_files": indexed_count,
            "changed_files_count": len(changed),
            "coverage": {
                "complete": indexed_count == len(changed) and not truncated,
                "changed_files_count": len(changed),
                "indexed_changed_files": indexed_count,
                "changed_file_ratio": round(changed_file_coverage, 3),
                "dependent_candidate_count": dependent_candidate_count,
                "dependent_candidate_count_exact": dependent_candidate_count_exact,
                "dependent_count": dependent_candidate_count if dependent_candidate_count_exact else None,
                "dependent_returned_count": len(likely_dependents),
                "dependents_truncated": dependents_truncated,
            },
            "freshness": {"status": "not_checked"},
            "truncated": truncated,
            "truncation": truncation,
            "graph_complete": False,
            "dependency_graph_complete": not truncated,
        }
        self._impact_result_l1.set(cache_key, result)
        return result

    def inspect_symbol(self, root: str, symbol_name: str) -> dict[str, Any]:
        decl = self.find_declaration(root, symbol_name)
        if decl.get("success"):
            d = decl["declaration"]
            return {
                "success": True,
                "root": canonical_root(root),
                "name": d["name"],
                "kind": d["kind"],
                "path": d["path"],
                "line": d["line"],
                "end_line": d["end_line"],
                "container": d.get("container", ""),
                "signature": d.get("signature", ""),
                "snippet": d.get("body", ""),
            }
        return {"success": False, "error": f"Symbol '{symbol_name}' not found"}

    def find_dead_code(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Detect unreferenced symbols using the precomputed symbols and refs tables."""
        resolved_root = canonical_root(root)
        try:
            with self._lock, closing(self._connect(register_archive_function=False)) as con:
                con.execute("CREATE TEMP TABLE dead_code_archive_paths(path TEXT PRIMARY KEY)")
                with closing(
                    con.execute(
                        "SELECT path FROM symbols WHERE root=? UNION SELECT path FROM refs WHERE root=?",
                        (resolved_root, resolved_root),
                    )
                ) as path_rows:
                    while path_batch := path_rows.fetchmany(250):
                        con.executemany(
                            "INSERT INTO dead_code_archive_paths(path) VALUES(?)",
                            (
                                (path,)
                                for row in path_batch
                                if is_root_archive_path(path := str(row[0]))
                            ),
                        )
                sql = """
                SELECT s.path, s.name, s.kind, s.line, s.end_line, s.container, s.name_path, s.access
                FROM symbols s
                LEFT JOIN refs r ON s.root = r.root AND s.name = r.name
                    AND NOT EXISTS (
                        SELECT 1 FROM dead_code_archive_paths archived WHERE archived.path = r.path
                    )
                WHERE s.root = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM dead_code_archive_paths archived WHERE archived.path = s.path
                  )
                  AND r.name IS NULL
                  AND s.name NOT IN (
                      'main', 'run', 'cli', 'app', 'handler', '__init__', '__str__', '__repr__',
                      'setUp', 'tearDown', 'setUpClass', 'tearDownClass', 'test'
                  )
                  AND NOT s.name LIKE 'test_%'
                  AND NOT s.path LIKE '%test%'
                ORDER BY s.path, s.line
                LIMIT ?
                """
                rows = con.execute(sql, (resolved_root, max(1, int(limit)))).fetchall()

            dead_symbols = []
            for r in rows:
                dead_symbols.append({
                    "file": r["path"],
                    "path": r["path"],
                    "name": r["name"],
                    "kind": r["kind"],
                    "line": r["line"],
                    "end_line": r["end_line"],
                    "container": r["container"] or "",
                    "name_path": r["name_path"] or r["name"],
                    "access": r["access"] or "public",
                    "reason": "no indexed references found",
                })
            return {
                "success": True,
                "candidate_count": len(dead_symbols),
                "dead_code": dead_symbols,
                "dead_symbols": dead_symbols,
                "indexed": True,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "candidate_count": 0, "dead_code": [], "dead_symbols": []}

    def status(self, root: str | None = None) -> dict[str, Any]:
        self._cache_generation()
        now = time.monotonic()
        key = str(root or "__all__")
        cached = self._status_cache.get(key)
        if cached and now - cached["time"] < 5.0:
            return dict(cached["data"])
        try:
            # Table names are compile-time constants; validate against explicit whitelist
            # before f-string interpolation as defence-in-depth.
            _ALLOWED_TABLES = {"files", "symbols", "refs", "edges"}
            # A fresh WAL reader sees committed counts without waiting for the
            # Python lock held by a large indexing transaction.
            with closing(self._connect()) as con:
                where = " WHERE root=?" if root else ""
                args = (canonical_root(root),) if root else ()
                vals = ({t: int(con.execute(f"SELECT COUNT(*) FROM {t}{where}", args).fetchone()[0])  # noqa: S608
                         for t in _ALLOWED_TABLES} if root else
                        global_row_counts(con, ("files", "symbols", "refs", "edges")))
            res = {"success": True, "healthy": True, **vals}
            self._status_cache[key] = {"time": now, "data": res}
            return res
        except sqlite3.DatabaseError as exc:
            return {"success": False, "healthy": False, "error": str(exc)}

    def find_callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find all call sites and references to a symbol across repository AST."""
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error, "callers": []}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol cannot be empty", "callers": []}
        resolved = canonical_root(root)
        sym = symbol.strip()
        result_limit = limit
        escaped_sym = _escape_like_literal(sym)
        try:
            with closing(self._connect()) as con:
                deadline = time.monotonic() + 1.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                con.execute("BEGIN")
                index_available = con.execute(
                    f"SELECT 1 FROM files WHERE root=? AND {_root_archive_path_sql('path')} LIMIT 1",
                    (resolved,),
                ).fetchone() is not None
                rows = con.execute(
                    f"""SELECT src, dst, kind, path, line FROM edges
                       WHERE root=? AND kind=? AND dst_name=?
                         AND {_root_archive_path_sql("path")}
                         AND (dst=? OR dst LIKE ? ESCAPE '!' OR dst LIKE ? ESCAPE '!')
                       ORDER BY path, line, src, dst, kind LIMIT ? OFFSET ?""",
                    (
                        resolved, "calls", _edge_endpoint_name(sym), sym,
                        f"%/{escaped_sym}", f"%::{escaped_sym}", result_limit + 1, offset,
                    ),
                ).fetchall()
                con.set_progress_handler(None, 0)
        except sqlite3.DatabaseError as exc:
            busy = is_busy_error(exc)
            return {
                "success": False,
                "status_code": 503 if busy else 500,
                "terminal": not busy,
                "retryable": busy,
                "symbol": sym,
                "callers": [],
                "count": 0,
                "root": resolved,
                "error": str(exc),
                "busy": busy,
                "truncated": False,
                "truncation": {"callers": False},
                "offset": offset,
                "limit": result_limit,
                "coverage": {"complete": False, "returned": 0, "limit": result_limit, "offset": offset},
                "freshness": {"status": "not_checked"},
                "index_available": None,
            }
        truncated = len(rows) > result_limit
        callers = [
            {"caller": str(r["src"]), "callee": str(r["dst"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
            for r in rows[:result_limit]
        ]
        result = {
            "success": True,
            "symbol": sym,
            "callers": callers,
            "count": len(callers),
            "root": resolved,
            "offset": offset,
            "limit": result_limit,
            "returned_count": len(callers),
            "has_more": truncated,
            "truncated": truncated,
            "truncation": {"callers": truncated},
            "coverage": {"complete": offset == 0 and not truncated, "returned": len(callers), "limit": result_limit, "offset": offset, "scope": "indexed_edges"},
            "freshness": {"status": "not_checked"},
            "index_available": index_available,
        }
        result["coverage"]["index_available"] = index_available
        if not truncated and (offset == 0 or callers):
            result["total_matches"] = offset + len(callers)
        if truncated:
            result["next_offset"] = offset + len(callers)
        return result

    def find_callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find all functions/methods called by a symbol."""
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error, "callees": []}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": "symbol cannot be empty", "callees": []}
        resolved = canonical_root(root)
        sym = symbol.strip()
        result_limit = limit
        escaped_sym = _escape_like_literal(sym)
        try:
            with closing(self._connect()) as con:
                deadline = time.monotonic() + 1.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                con.execute("BEGIN")
                index_available = con.execute(
                    f"SELECT 1 FROM files WHERE root=? AND {_root_archive_path_sql('path')} LIMIT 1",
                    (resolved,),
                ).fetchone() is not None
                rows = con.execute(
                    f"""SELECT src, dst, kind, path, line FROM edges
                       WHERE root=? AND kind=? AND src_name=?
                         AND {_root_archive_path_sql("path")}
                         AND (src=? OR src LIKE ? ESCAPE '!' OR src LIKE ? ESCAPE '!')
                       ORDER BY path, line, src, dst, kind LIMIT ? OFFSET ?""",
                    (
                        resolved, "calls", _edge_endpoint_name(sym), sym,
                        f"%/{escaped_sym}", f"%::{escaped_sym}", result_limit + 1, offset,
                    ),
                ).fetchall()
                con.set_progress_handler(None, 0)
        except sqlite3.DatabaseError as exc:
            busy = is_busy_error(exc)
            return {
                "success": False,
                "status_code": 503 if busy else 500,
                "terminal": not busy,
                "retryable": busy,
                "symbol": sym,
                "callees": [],
                "count": 0,
                "root": resolved,
                "error": str(exc),
                "busy": busy,
                "truncated": False,
                "truncation": {"callees": False},
                "offset": offset,
                "limit": result_limit,
                "coverage": {"complete": False, "returned": 0, "limit": result_limit, "offset": offset},
                "freshness": {"status": "not_checked"},
                "index_available": None,
            }
        truncated = len(rows) > result_limit
        callees = [
            {"caller": str(r["src"]), "callee": str(r["dst"]), "kind": str(r["kind"]), "path": str(r["path"]), "line": int(r["line"])}
            for r in rows[:result_limit]
        ]
        result = {
            "success": True,
            "symbol": sym,
            "callees": callees,
            "count": len(callees),
            "root": resolved,
            "offset": offset,
            "limit": result_limit,
            "returned_count": len(callees),
            "has_more": truncated,
            "truncated": truncated,
            "truncation": {"callees": truncated},
            "coverage": {"complete": offset == 0 and not truncated, "returned": len(callees), "limit": result_limit, "offset": offset, "scope": "indexed_edges"},
            "freshness": {"status": "not_checked"},
            "index_available": index_available,
        }
        result["coverage"]["index_available"] = index_available
        if not truncated and (offset == 0 or callees):
            result["total_matches"] = offset + len(callees)
        if truncated:
            result["next_offset"] = offset + len(callees)
        return result

    def python_module_import_graph(self, root: str) -> dict[str, Any]:
        """Return the fresh Python import edges already stored for one indexed root."""
        resolved_root = canonical_root(root)
        root_path = Path(resolved_root)
        if not root_path.is_dir():
            return {"success": False, "state": "unindexed", "error": f"directory not found: {root}"}

        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path, analyzer_version, mtime_ns, size_bytes FROM files WHERE root=? AND language='python' ORDER BY path",
                (resolved_root,),
            ).fetchall()
            if not rows:
                return {"success": False, "state": "unindexed", "error": "no indexed Python files"}

            stale_paths: list[str] = []
            for row in rows:
                relative = Path(str(row["path"]))
                candidate = (root_path / relative).resolve(strict=False)
                try:
                    candidate.relative_to(root_path)
                    current = candidate.stat()
                    fresh = (
                        str(row["analyzer_version"] or "") == _PARSER_ANALYZER_VERSION
                        and current.st_mtime_ns == row["mtime_ns"]
                        and current.st_size == row["size_bytes"]
                    )
                except (OSError, ValueError):
                    fresh = False
                if not fresh:
                    stale_paths.append(str(row["path"]))
            if stale_paths:
                return {
                    "success": False,
                    "state": "stale",
                    "error": "indexed Python files need reindexing",
                    "stale_paths": stale_paths[:20],
                }

            imports = con.execute(
                "SELECT e.path, e.dst FROM edges AS e JOIN files AS f ON f.root=e.root AND f.path=e.path "
                "WHERE e.root=? AND f.language='python' AND e.kind='imports' ORDER BY e.path, e.line, e.dst",
                (resolved_root,),
            ).fetchall()
        return {
            "success": True,
            "state": "indexed",
            "paths": [str(row["path"]) for row in rows],
            "imports": [{"path": str(row["path"]), "target": str(row["dst"] or "")} for row in imports],
        }
