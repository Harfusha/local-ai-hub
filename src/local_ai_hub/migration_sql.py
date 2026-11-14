from __future__ import annotations

from typing import Iterator


def split_sql_statements(source: str) -> Iterator[str]:
                pending: list[str] = []
                quote: str | None = None
                line_comment = False
                block_comment = False
                index = 0
                while index < len(source):
                    char = source[index]
                    next_char = source[index + 1] if index + 1 < len(source) else ""
                    pending.append(char)
                    if line_comment:
                        if char in "\r\n":
                            line_comment = False
                    elif block_comment:
                        if char == "*" and next_char == "/":
                            pending.append(next_char)
                            index += 1
                            block_comment = False
                    elif quote is not None:
                        closing = "]" if quote == "[" else quote
                        if char == closing:
                            if next_char == closing and quote != "[":
                                pending.append(next_char)
                                index += 1
                            else:
                                quote = None
                    elif char in {"'", '"', "`", "["}:
                        quote = char
                    elif char == "-" and next_char == "-":
                        pending.append(next_char)
                        index += 1
                        line_comment = True
                    elif char == "/" and next_char == "*":
                        pending.append(next_char)
                        index += 1
                        block_comment = True
                    elif char == ";":
                        yield "".join(pending)
                        pending.clear()
                    index += 1
                if pending:
                    yield "".join(pending)
