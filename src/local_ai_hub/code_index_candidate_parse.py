from __future__ import annotations

from typing import Any

from .json_utils import dumps as json_dumps


def parse_index_candidate(
    code_index: Any,
    candidate: tuple[str, str, str, list[str]],
    blob_map: dict[tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]],
    root: str,
    now: float,
    analyzer_version: str,
) -> tuple[str, str, str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], tuple[Any, ...] | None]:
    """Parse one changed file or reuse its cached parser output."""
    path, content_hash, language, lines = candidate
    parsed = blob_map.get((content_hash, language))
    if parsed is None:
        symbols, refs, edges = code_index._parse_file_content(
            "\n".join(lines), language, source_key=code_index._tree_source_key(root, path),
        )
        diagnostic = dict(getattr(code_index._parse_diagnostic, "value", {}))
        row_blob = (
            content_hash,
            analyzer_version,
            language,
            json_dumps(
                {"symbols": symbols, "refs": refs, "edges": edges, "parse_outcome": diagnostic},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            now,
        )
    else:
        symbols, refs, edges, _ = parsed
        row_blob = None
    return path, content_hash, language, symbols, refs, edges, row_blob
