from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def build_symbol_context(
    code_index: Any,
    root: str,
    query: str,
    terms: Iterable[str],
    max_chars: int,
    used_chars: int,
) -> tuple[str, bool]:
    """Render bounded hierarchical symbols, returning text and truncation state."""
    try:
        symbol_result = code_index.find_symbol(root, query, depth=1, include_info=True, limit=6)
        symbols = symbol_result.get("symbols", [])
        if not symbols:
            for term in terms:
                if term.isidentifier():
                    symbol_result = code_index.find_symbol(root, term, depth=1, include_info=True, limit=6)
                    symbols = symbol_result.get("symbols", [])
                    if symbols:
                        break
            if not symbols:
                query_result = code_index.query(root, query, limit=6)
                symbols = query_result.get("symbols", [])

        if not symbols:
            return "", False

        blocks = ["\nHIERARCHICAL SYMBOLS & SIGNATURES:"]
        for symbol in symbols:
            signature = symbol.get("signature") or f"{symbol.get('kind')} {symbol.get('name')}"
            blocks.append(
                f"- [{symbol.get('kind')}] {symbol.get('name_path')} "
                f"({symbol.get('path')}:{symbol.get('line')}) -> {signature}"
            )
            for child in symbol.get("children", [])[:4]:
                blocks.append(f"    * {child.get('signature') or child.get('name')} (L{child.get('line')})")

        rendered = "\n".join(blocks)
        if used_chars + 1 + len(rendered) <= max_chars:
            return rendered, False
        return "", True
    except Exception:
        return "", False
