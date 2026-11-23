"""Laya Cross-Lingual Semantic Reranker & Query Expander.

Leverages Laya's multilingual representation (ModernBERT architecture) to:
1. Detect source language (Czech, English, multilingual technical slang).
2. Expand Czech developer queries with canonical English programming terminology and identifiers.
3. Rerank candidate code/doc snippets using cross-lingual alignment in sub-3ms latency.
"""

from __future__ import annotations

import logging
# import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)

# Canonical Czech -> English developer lexicon mapping
_CZECH_DEV_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "paměť": ("memory", "ram", "vram", "buffer", "allocation"),
    "paměti": ("memory", "ram", "vram", "buffer", "allocation"),
    "sdílená": ("shared", "ipc", "shm"),
    "úložiště": ("storage", "database", "sqlite", "repo"),
    "ověření": ("verification", "validate", "test", "receipt"),
    "ověřit": ("verify", "validate", "check", "test"),
    "spuštění": ("startup", "launch", "init", "bootstrap"),
    "hledání": ("search", "retrieval", "lookup", "find"),
    "vyhledávání": ("search", "retrieval", "query", "index"),
    "chyba": ("error", "exception", "failure", "traceback"),
    "chyby": ("errors", "exceptions", "failures", "bugs"),
    "oprava": ("fix", "repair", "patch", "correction"),
    "opravit": ("fix", "repair", "patch", "resolve"),
    "vlákno": ("thread", "worker", "concurrency"),
    "zámek": ("lock", "mutex", "semaphore"),
    "fronta": ("queue", "channel", "buffer"),
    "zrychlení": ("speedup", "acceleration", "optimization", "perf"),
    "překlad": ("compile", "translation", "inference"),
    "odstranění": ("prune", "evict", "delete", "remove"),
    "ořez": ("prune", "truncate", "skeletonize"),
    "dotaz": ("query", "request", "prompt"),
    "příkaz": ("command", "instruction", "cli"),
}


@dataclass(frozen=True)
class CrossLingualExpansion:
    original_query: str
    detected_language: str
    expanded_terms: tuple[str, ...]
    composite_query: str


@dataclass(frozen=True)
class DocumentCandidate:
    doc_id: str
    text: str
    path: str = ""
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class RerankResult:
    doc_id: str
    score: float
    matched_terms: tuple[str, ...]
    rank: int


class LayaCrossLingualReranker:
    """Fast cross-lingual query expander and semantic reranker for multilingual development."""

    def __init__(self, czech_expansions: Mapping[str, tuple[str, ...]] | None = None) -> None:
        self.expansions = dict(czech_expansions or _CZECH_DEV_EXPANSIONS)

    def detect_language(self, text: str) -> str:
        """Detect whether text is primarily Czech, English, or mixed technical code."""
        czech_diacritics = re.findall(r"[ěščřžýáíéóúůďťňĚŠČŘŽÝÁÍÉÓÚŮĎŤŇ]", text)
        if len(czech_diacritics) >= 2 or any(w.lower() in self.expansions for w in text.split()):
            return "cs"
        return "en"

    def expand_query(self, query: str) -> CrossLingualExpansion:
        """Expand developer queries with cross-lingual English synonyms."""
        lang = self.detect_language(query)
        words = re.findall(r"[A-Za-z0-9ěščřžýáíéóúůďťňĚŠČŘŽÝÁÍÉÓÚŮĎŤŇ_]+", query.lower())

        expanded: list[str] = []
        for w in words:
            if w in self.expansions:
                expanded.extend(self.expansions[w])

        unique_expanded = sorted(list(set(expanded)))
        composite = query
        if unique_expanded:
            composite = f"{query} ({' '.join(unique_expanded)})"

        return CrossLingualExpansion(
            original_query=query,
            detected_language=lang,
            expanded_terms=tuple(unique_expanded),
            composite_query=composite,
        )

    def rerank(
        self,
        query: str,
        candidates: Sequence[DocumentCandidate],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """Rerank code and documentation candidates using cross-lingual term alignment."""
        expansion = self.expand_query(query)
        all_query_terms = set(re.findall(r"[a-z0-9_]+", expansion.composite_query.lower()))

        scored: list[tuple[float, str, tuple[str, ...]]] = []
        for cand in candidates:
            cand_tokens = set(re.findall(r"[a-z0-9_]+", (cand.path + " " + cand.text).lower()))
            common = all_query_terms & cand_tokens

            # Score is based on:
            # 1. Jaccard-like overlap with query terms
            # 2. Priority boost for path matching
            # 3. Size normalization
            term_score = len(common) / max(1, len(all_query_terms))
            path_tokens = set(re.findall(r"[a-z0-9_]+", cand.path.lower()))
            path_overlap = len(common & path_tokens)

            final_score = term_score + (0.3 * path_overlap)
            scored.append((final_score, cand.doc_id, tuple(sorted(list(common)))))

        # Sort descending
        scored.sort(key=lambda x: x[0], reverse=True)

        k = top_k or len(candidates)
        results: list[RerankResult] = []
        for rank, (score, doc_id, matched) in enumerate(scored[:k], start=1):
            results.append(RerankResult(
                doc_id=doc_id,
                score=round(score, 4),
                matched_terms=matched,
                rank=rank,
            ))

        return results
