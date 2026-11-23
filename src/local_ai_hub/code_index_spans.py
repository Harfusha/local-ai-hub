from __future__ import annotations

import re
from typing import Any

from .code_index_constants import TRAILING_CALL_AFTER_CLOSE

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

