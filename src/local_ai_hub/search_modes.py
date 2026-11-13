"""Bounded, deterministic candidate fusion for repository search modes."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

SEARCH_MODES = ("lexical", "rag", "hybrid")
RRF_K = 60


def canonical_search_mode(value: Any) -> str | None:
    """Return one canonical public mode, rejecting coercions and aliases."""
    if type(value) is not str or value not in SEARCH_MODES:
        return None
    return value


def _is_version_or_number(token: str) -> bool:
    clean = token.strip(".,!?;()[]{}<>\"'`")
    return bool(re.match(r"^v?\d+(\.\d+)*[a-zA-Z0-9_-]*$", clean))


def _is_file_path(token: str) -> bool:
    clean = token.strip(".,!?;()[]{}<>\"'`")
    if "/" in clean or "\\" in clean:
        return True
    return bool(re.match(r"^[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]{1,8}$", clean))


def _is_code_symbol(token: str) -> bool:
    clean = token.strip(".,!?;()[]{}<>\"'`")
    if not clean or _is_version_or_number(clean) or _is_file_path(clean):
        return False
    if "_" in clean or "::" in clean:
        return True
    if any(op in clean for op in ("++", "#", "$", "->")):
        return True
    if re.search(r"[a-z][A-Z]", clean):
        return True
    return False


def _api_endpoint_token(token: str) -> str | None:
    candidate = token.strip(".,!?;()[]<>\"'`")
    if re.fullmatch(r"/(?:api|v1|mcp)(?:/[A-Za-z0-9_.{}-]+)+/?", candidate):
        return candidate
    return None


def classify_query(query: str) -> str:
    """Classify a search query into exact_symbol, file_path, natural_language, or mixed."""
    if type(query) is not str:
        return "natural_language"
    value = query.strip()
    if not value or len(value) > 256:
        return "natural_language"
    tokens = value.split()
    if not tokens:
        return "natural_language"

    if len(tokens) == 1:
        tok = tokens[0]
        if _is_file_path(tok):
            return "file_path"
        if _is_code_symbol(tok):
            return "exact_symbol"
        return "natural_language"

    has_symbols = False
    has_paths = False
    has_prose = False
    for tok in tokens:
        clean = tok.strip(".,!?;()[]{}<>\"'`")
        if not clean:
            continue
        if _is_code_symbol(clean):
            has_symbols = True
        elif _is_file_path(clean) or _is_version_or_number(clean):
            has_paths = True
        else:
            has_prose = True

    if (has_symbols or has_paths) and has_prose:
        return "mixed"
    if has_symbols and not has_prose:
        return "exact_symbol"
    if has_paths and not has_prose:
        return "file_path"
    return "natural_language"


def prefers_lexical_precision(query: str) -> bool:
    """Recognize symbol and explicit endpoint queries where exact hits must lead."""
    if type(query) is not str:
        return False
    value = query.strip()
    if not value or len(value) > 256:
        return False
    for raw_token in value.split():
        clean = raw_token.strip(".,!?;()[]{}<>\"'`")
        if _is_code_symbol(clean) or _api_endpoint_token(raw_token) is not None:
            return True
    return False


def lexical_precision_query(query: str) -> str:
    """Use a single embedded symbol or endpoint as the exact lexical anchor."""
    if type(query) is not str:
        return ""
    value = query.strip()
    if not value or len(value) > 256:
        return value
    anchors: list[str] = []
    for raw_token in value.split():
        token = raw_token.strip(".,!?;()[]{}<>\"'`")
        endpoint = _api_endpoint_token(raw_token)
        if endpoint is not None:
            anchors.append(endpoint)
        elif _is_code_symbol(token):
            anchors.append(token)
    unique_anchors = list(dict.fromkeys(anchors))
    return unique_anchors[0] if len(unique_anchors) == 1 else value


def default_search_mode(query: str) -> str:
    """Use lexical for explicit symbols or endpoints and hybrid otherwise."""
    return "lexical" if prefers_lexical_precision(query) else "hybrid"


def default_agent_search_mode(query: str) -> str:
    """Share the query-aware default with direct service callers."""
    return default_search_mode(query)


_SEMANTIC_QUERY_TERMS = {
    "jak": "how",
    "nainstalovat": "install",
    "instalace": "installation",
    "instalovat": "install",
    "nastavit": "configure",
    "nastavení": "configuration",
    "nastaveni": "configuration",
    "omezit": "limit",
    "omezení": "size limit",
    "omezeni": "size limit",
    "limit": "size",
    "offset": "pagination",
    "ověřuje": "valid",
    "overuje": "valid",
    "výsledků": "results",
    "vysledku": "results",
    "velikost": "size",
    "velikosti": "size",
    "preprocessing": "preprocess",
    "obnoví": "refresh",
    "obnovi": "refresh",
    "změně": "change",
    "zmene": "change",
    "soubor": "file",
    "soubory": "files",
    "souborů": "files",
    "souboru": "file",
    "hybridní": "hybrid",
    "hybridni": "hybrid",
    "označí": "indicate",
    "oznaci": "indicate",
    "nedostupný": "unavailable",
    "nedostupny": "unavailable",
    "hledání": "search",
    "hledani": "search",
    "vyhledávání": "search",
    "vyhledavani": "search",
    "kód": "code",
    "kod": "code",
    "indexu": "index",
    "index": "index",
}

_CZECH_SEMANTIC_MARKERS = {
    "jak", "nainstalovat", "instalace", "instalovat", "nastavit",
    "nastavení", "nastaveni", "omezit", "omezení", "omezeni",
    "ověřuje", "overuje", "výsledků", "vysledku",
    "velikost", "velikosti", "soubor", "soubory", "hledání", "hledani",
    "vyhledávání", "vyhledavani", "kód", "kod", "indexu",
}

_INSTALLATION_SEMANTIC_MARKERS = {
    "install", "installation", "installing", "setup", "bootstrap",
}

_ENGLISH_TO_CZECH_SEMANTIC_TERMS = {
    "configure": ("nastavit", "nastavení", "konfigurovat", "konfigurace"),
    "configuration": ("nastavení", "konfigurace"),
    "settings": ("nastavení",),
    "setup": ("nastavení", "instalace"),
    "install": ("instalace", "nainstalovat"),
    "installation": ("instalace", "nainstalovat"),
    "installing": ("instalace", "instalovat"),
    "bootstrap": ("instalace", "nastavení"),
}

_ENGLISH_TO_CZECH_LEXICAL_TERMS = {
    "configure": ("konfigurace", "nastavení"),
    "configuration": ("nastavení",),
    "settings": ("nastavení",),
    "setup": ("nastavení", "instalace"),
    "install": ("instalace",),
    "installation": ("instalace",),
    "installing": ("instalovat",),
    "bootstrap": ("instalace",),
}


def expand_lexical_fallback_query(query: str) -> tuple[str, bool]:
    """Add only direct bilingual terms to degraded lexical search."""
    if type(query) is not str or not query.strip():
        return query, False
    tokens = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    token_set = set(tokens)
    if _CZECH_SEMANTIC_MARKERS.intersection(token_set):
        terms = list(dict.fromkeys(
            _SEMANTIC_QUERY_TERMS[token] for token in tokens
            if token in _SEMANTIC_QUERY_TERMS
        ))
    else:
        terms = list(dict.fromkeys(
            term for token in tokens
            for term in _ENGLISH_TO_CZECH_LEXICAL_TERMS.get(token, ())
        ))
    if not terms:
        return query, False
    return f"{query.strip()} {' '.join(terms)}", True


def expand_semantic_query(query: str) -> tuple[str, bool]:
    """Append bounded related terms for common natural-language searches.

    Exact lexical search keeps the original query. Czech terms target the
    configured English embedding space, while a small English vocabulary adds
    common Czech equivalents for configuration and installation searches.
    """
    if type(query) is not str or not query.strip():
        return query, False
    tokens = re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
    token_set = set(tokens)
    if not _CZECH_SEMANTIC_MARKERS.intersection(token_set):
        expanded_terms: list[str] = []
        if _INSTALLATION_SEMANTIC_MARKERS.intersection(token_set):
            expanded_terms.extend(("install", "setup", "getting started", "bootstrap"))
        for token in tokens:
            expanded_terms.extend(_ENGLISH_TO_CZECH_SEMANTIC_TERMS.get(token, ()))
        expanded_terms = list(dict.fromkeys(expanded_terms))
        if not expanded_terms:
            return query, False
        return f"{query.strip()} {' '.join(expanded_terms)}", True
    translated = list(dict.fromkeys(
        _SEMANTIC_QUERY_TERMS[token] for token in tokens
        if token in _SEMANTIC_QUERY_TERMS
    ))
    if (
        _INSTALLATION_SEMANTIC_MARKERS.intersection(token_set)
        or {"install", "installation"}.intersection(translated)
    ):
        translated.extend(("install", "setup", "getting started", "bootstrap"))
        translated = list(dict.fromkeys(translated))
    has_index = bool({"index", "indexu"} & token_set)
    has_size_limit = bool({
        "limit", "omezit", "omezení", "omezeni",
        "velikost", "velikosti",
    } & token_set)
    if has_index and has_size_limit:
        return f"{query.strip()} code_index max_index_bytes eviction byte budget", True
    if not translated:
        return query, False
    return f"{query.strip()} {' '.join(translated)}", True


def _path_key(item: Mapping[str, Any], *, case_sensitive: bool = True) -> tuple[str, str] | None:
    path = item.get("path")
    if type(path) is not str or not path.strip():
        return None
    raw = path.replace("\\", "/")
    parts = PurePosixPath(raw).parts
    if (
        not raw
        or raw.startswith("/")
        or ".." in parts
        or (parts and ":" in parts[0])
        or "\x00" in raw
    ):
        return None
    display = str(PurePosixPath(raw))
    return (display if case_sensitive else display.casefold()), display


def deduplicate_search_files(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first ranked result per safe relative file path."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        identity = _path_key(row)
        if identity is None or identity[0] in seen:
            continue
        seen.add(identity[0])
        item = dict(row)
        item["path"] = identity[1]
        results.append(item)
    return results


def fuse_search_results(
    lexical: Sequence[Mapping[str, Any]],
    rag: Sequence[Mapping[str, Any]],
    *,
    limit: int,
    offset: int,
    rrf_k: int = RRF_K,
    lexical_first: bool = False,
    case_sensitive: bool = True,
    matches_per_file: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fuse per-file ranks while retaining bounded evidence from every chunk.

    Git-relative path identity is case-sensitive by default on every host;
    repositories with an explicit case-insensitive policy can opt in. File
    ranking remains bounded while distinct lexical and RAG matches are retained.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if type(rrf_k) is not int or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")
    if type(case_sensitive) is not bool or type(matches_per_file) is not int or matches_per_file < 1:
        raise ValueError("case_sensitive must be boolean and matches_per_file positive")

    merged: dict[str, dict[str, Any]] = {}
    for source, rows in (("lexical", lexical), ("rag", rag)):
        source_ranks: dict[str, int] = {}
        for rank, raw in enumerate(rows, start=1):
            if not isinstance(raw, Mapping):
                continue
            identity = _path_key(raw, case_sensitive=case_sensitive)
            if identity is None:
                continue
            key, display_path = identity
            source_rank = source_ranks.get(key)
            first_for_source = source_rank is None
            if first_for_source:
                source_rank = rank
                source_ranks[key] = source_rank
            entry = merged.get(key)
            if entry is None:
                entry = {
                    "path": display_path,
                    "sources": [],
                    "fusion_score": 0.0,
                    "source_breakdown": {},
                    "matches": [],
                }
                merged[key] = entry
            if source == "lexical":
                # Exact lexical coordinates and snippets remain authoritative.
                lexical_item = dict(raw)
                lexical_item.pop("sources", None)
                lexical_item.pop("fusion_score", None)
                entry.update(lexical_item)
                entry["path"] = display_path
            elif not entry.get("lexical_rank"):
                # RAG text is a candidate only; caller validates it against the
                # current source and path policy before fusion.
                for field, value in raw.items():
                    if field not in entry and field not in {"embedding", "raw_embedding"}:
                        entry[field] = value
            file_score = 1.0 / (rrf_k + source_rank)
            if first_for_source:
                entry[f"{source}_rank"] = source_rank
                entry["fusion_score"] += file_score
                entry["source_breakdown"][source] = {"rank": source_rank, "score": file_score}
                entry["sources"].append(source)

            match = {field: value for field, value in raw.items() if field not in {"embedding", "raw_embedding"}}
            match["path"] = display_path
            match["source"] = source
            match["source_rank"] = source_rank
            match["fusion_score"] = file_score
            content_hash = raw.get("content_hash")
            chunk_id = raw.get("chunk_id", raw.get("chunk_no", raw.get("start_line")))
            source_id = raw.get("source_id", display_path)
            match_identity = (str(source_id), str(chunk_id), str(content_hash)) if content_hash is not None and chunk_id is not None else None
            existing = next((candidate for candidate in entry["matches"]
                             if match_identity is not None and candidate.get("_identity") == match_identity), None)
            if existing is None:
                match["_identity"] = match_identity
                match["sources"] = [source]
                entry["matches"].append(match)
            elif source not in existing["sources"]:
                existing["sources"].append(source)
                existing["fusion_score"] += file_score

    for item in merged.values():
        matches = sorted(item["matches"], key=lambda match: (
            not (type(match.get("relevance")) in {int, float} and math.isfinite(match["relevance"])),
            -float(match["relevance"]) if type(match.get("relevance")) in {int, float} and math.isfinite(match["relevance"]) else 0.0,
            -float(match.get("fusion_score", 0.0)),
            "lexical" not in match.get("sources", []),
            int(match.get("source_rank", 0)),
            str(match.get("chunk_id", match.get("chunk_no", match.get("start_line", "")))),
        ))
        total_matches = len(matches)
        kept = matches[:matches_per_file]
        for match in kept:
            match.pop("_identity", None)
        item["matches"] = kept
        item["primary_match"] = kept[0] if kept else None
        item["alternative_matches"] = kept[1:]
        item["truncated"] = total_matches > len(kept)
        item["omitted_matches"] = total_matches - len(kept)

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            0 if lexical_first and item.get("lexical_rank") else 1,
            -float(item["fusion_score"]),
            str(item.get("path", "")) if case_sensitive else str(item.get("path", "")).casefold(),
            str(item.get("path", "")),
        ),
    )
    for item in ranked:
        item["fusion_score"] = round(float(item["fusion_score"]), 8)
        item["sources"] = [source for source in ("lexical", "rag") if source in item["sources"]]
        item["result_source"] = "hybrid"
        item["score"] = item["fusion_score"]
    page = ranked[offset : offset + limit]
    metadata = {
        "candidate_count": len(ranked),
        "candidate_count_exact": False,
        "count_exact": False,
        "total_matches": None,
        "offset": offset,
        "limit": limit,
        "has_more": True if offset + len(page) < len(ranked) else None,
        "next_offset": offset + len(page),
    }
    return page, metadata
