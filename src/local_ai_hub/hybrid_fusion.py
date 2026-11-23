"""Tri-Hybrid Retrieval Fusion Engine (BM25, Dense RAG, and AST Symbol Graph).

Fuses independent lexical, dense embedding, and AST dependency graph rankings
using Reciprocal Rank Fusion (RRF) with dynamic intent-aware weight adaptation.
Eliminates retrieval blind spots by balancing exact symbol matches with conceptual semantic search.
"""

from __future__ import annotations

import collections
# import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class FusedSearchResult:
    """Consolidated search outcome after tri-hybrid rank fusion."""

    doc_id: str
    composite_score: float
    rank: int
    lexical_rank: int | None
    dense_rank: int | None
    ast_rank: int | None
    contributing_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["contributing_sources"] = list(self.contributing_sources)
        return d


_CODE_PATTERN = re.compile(r"([A-Z][a-z0-9]+[A-Z][a-z0-9]+|[a-z0-9]+_[a-z0-9_]+|\b(?:def|class|fn|func|import|return)\b|\.[a-zA-Z]{1,4}\b|::|->)")


def classify_query_intent(query: str) -> dict[str, float]:
    """Determine dynamic source weights based on lexical code density vs natural language."""
    matches = len(_CODE_PATTERN.findall(query))
    words = query.strip().split()
    total_words = max(1, len(words))

    code_ratio = matches / total_words

    if code_ratio > 0.3 or any(w.endswith((".py", ".ts", ".js", ".rs", ".go", "()")) for w in words):
        # Code-heavy query: prioritize exact lexical and AST symbol graph
        return {"lexical": 1.4, "ast": 1.5, "dense": 0.6}
    elif any(q in query.lower() for q in ("how", "why", "explain", "architecture", "overview", "what does")):
        # Conceptual query: prioritize dense embedding semantics
        return {"lexical": 0.7, "ast": 0.8, "dense": 1.6}
    else:
        # Balanced hybrid
        return {"lexical": 1.0, "ast": 1.0, "dense": 1.0}


def reciprocal_rank_fusion(
    lexical_ranking: Sequence[str],
    dense_ranking: Sequence[str],
    ast_ranking: Sequence[str],
    k: int = 60,
    weights: Mapping[str, float] | None = None,
    limit: int = 20,
) -> list[FusedSearchResult]:
    """Fuse 3 ranked lists of document identifiers using weighted RRF."""
    w = dict(weights or {"lexical": 1.0, "ast": 1.0, "dense": 1.0})
    w_lex = float(w.get("lexical", 1.0))
    w_dense = float(w.get("dense", 1.0))
    w_ast = float(w.get("ast", 1.0))

    lex_ranks = {doc: idx + 1 for idx, doc in enumerate(lexical_ranking)}
    dense_ranks = {doc: idx + 1 for idx, doc in enumerate(dense_ranking)}
    ast_ranks = {doc: idx + 1 for idx, doc in enumerate(ast_ranking)}

    all_docs = set(lex_ranks.keys()) | set(dense_ranks.keys()) | set(ast_ranks.keys())
    scores: dict[str, float] = collections.defaultdict(float)
    sources: dict[str, list[str]] = collections.defaultdict(list)

    for doc in all_docs:
        score = 0.0
        if doc in lex_ranks:
            score += w_lex * (1.0 / (k + lex_ranks[doc]))
            sources[doc].append("lexical")
        if doc in dense_ranks:
            score += w_dense * (1.0 / (k + dense_ranks[doc]))
            sources[doc].append("dense")
        if doc in ast_ranks:
            score += w_ast * (1.0 / (k + ast_ranks[doc]))
            sources[doc].append("ast")
        scores[doc] = score

    sorted_docs = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    results: list[FusedSearchResult] = []
    for rank_idx, (doc, sc) in enumerate(sorted_docs[:limit]):
        results.append(FusedSearchResult(
            doc_id=doc,
            composite_score=sc,
            rank=rank_idx + 1,
            lexical_rank=lex_ranks.get(doc),
            dense_rank=dense_ranks.get(doc),
            ast_rank=ast_ranks.get(doc),
            contributing_sources=tuple(sources[doc]),
        ))

    return results
