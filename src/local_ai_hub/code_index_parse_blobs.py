from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from typing import Any


def load_parse_blobs(
    code_index: Any,
    pairs: Iterable[tuple[str, str]],
    analyzer_version: str,
    batch_values: Callable[[list[tuple[str, str]]], Iterable[Sequence[tuple[str, str]]]],
) -> dict[tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]]:
    """Load parser output from the process cache, then the shared SQLite cache."""
    blob_map: dict[
        tuple[str, str],
        tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]],
    ] = {}
    unique_pairs = list(dict.fromkeys(pairs))
    for content_hash, language in unique_pairs:
        cached = code_index._parse_blob_l1.get(f"{content_hash}:{analyzer_version}:{language}")
        if cached is not None:
            diagnostic = cached[3] if len(cached) >= 4 and isinstance(cached[3], dict) else {
                "status": "unknown", "parser": "unknown", "fallback_used": False,
            }
            blob_map[(content_hash, language)] = (
                list(cached[0]), list(cached[1]), list(cached[2]), dict(diagnostic),
            )

    missing_pairs = [pair for pair in unique_pairs if pair not in blob_map]
    if not missing_pairs:
        return blob_map

    try:
        for batch in batch_values(missing_pairs):
            clauses = " OR ".join("(content_hash=? AND language=?)" for _ in batch)
            params: list[Any] = []
            for content_hash, language in batch:
                params.extend([content_hash, language])
            with code_index._lock, closing(code_index._connect()) as connection:
                rows = connection.execute(
                    f"SELECT content_hash,language,payload_json FROM parse_blobs "
                    f"WHERE analyzer_version=? AND ({clauses})",
                    (analyzer_version, *params),
                ).fetchall()
            for row in rows:
                data = json.loads(str(row[2]))
                if isinstance(data, dict):
                    diagnostic = data.get("parse_outcome")
                    if not isinstance(diagnostic, dict):
                        diagnostic = {"status": "unknown", "parser": "unknown", "fallback_used": False}
                    blob_map[(str(row[0]), str(row[1]))] = (
                        list(data.get("symbols", [])),
                        list(data.get("refs", [])),
                        list(data.get("edges", [])),
                        diagnostic,
                    )
    except Exception:
        pass
    return blob_map
