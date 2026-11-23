from __future__ import annotations

import re
import time
from typing import Any

from .normalizer import normalize_query
from .rag_constants import _INSTALL_INTENT_RE, _INSTALL_SEMANTIC_TERMS


def _semantic_embedding_query(query: str) -> str:
    """Add bounded cross-language aliases for clear installation intent only."""
    clean_query = normalize_query(query)
    if not clean_query or not _INSTALL_INTENT_RE.search(clean_query):
        return clean_query

    words = set(re.findall(r"[^\W_]+", clean_query.casefold()))
    has_english_install = any(word.startswith("install") for word in words)
    terms = tuple(
        term
        for term in _INSTALL_SEMANTIC_TERMS
        if not (
            (term in {"install", "installation"} and has_english_install)
            or all(part in words for part in term.split())
        )
    )
    if not terms:
        return clean_query
    return f"{clean_query} {' '.join(terms)}"


def _search_limit_reached(deadline: float | None, cancel_event: Any | None) -> bool:
    return (deadline is not None and time.perf_counter() >= deadline) or (
        cancel_event is not None and cancel_event.is_set()
    )
