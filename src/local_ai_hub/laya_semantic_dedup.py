"""Laya Semantic Deduplicator & Paraphrase Cache Indexer.

Indexes previously executed prompts and queries into an in-memory semantic space.
Enforces strict separation between semantic similarity hints and authentic replay admissibility:
- Thread-safe single-map storage with TTL, byte caps, and entry LRU eviction.
- Scope-isolated by repo_root, worktree_id, and revision.
- Rejection of mutation replay, negated polarity, word-order inversion, and mismatched numeric arguments.
"""

from __future__ import annotations

import collections
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Sequence

NEGATION_TERMS = frozenset({
    "not", "no", "never", "none", "neither", "nor", "without",
    "ne", "nikdy", "žádný", "zadny", "zakaž", "zakaz", "zakázat",
    "nepovol", "nepovolit", "disallow", "deny", "prohibit", "reject",
})


@dataclass(frozen=True)
class CacheEntry:
    entry_id: str
    prompt: str
    normalized_prompt: str
    vector: dict[str, float]
    tokens: tuple[str, ...]
    numbers: tuple[str, ...]
    negations: tuple[str, ...]
    payload: Any
    created_at: float
    last_accessed_at: float
    repo_root: str | None = None
    worktree_id: str | None = None
    revision: str | None = None
    operation: str | None = None
    is_mutation: bool = False
    ttl_seconds: float | None = None
    byte_size: int = 0


@dataclass(frozen=True)
class SemanticMatchResult:
    matched_id: str
    similarity: float
    cached_payload: Any
    matched_prompt: str
    is_hit: bool
    is_exact_match: bool = False
    is_replay_admissible: bool = False
    rejection_reason: str | None = None


class LayaSemanticDeduplicator:
    """Thread-safe semantic vector index with strict replay verification."""

    def __init__(
        self,
        default_threshold: float = 0.85,
        max_entries: int = 2000,
        max_bytes: int = 10 * 1024 * 1024,
        default_ttl_seconds: float | None = 3600.0,
    ) -> None:
        self.default_threshold = default_threshold
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1024, int(max_bytes))
        self.default_ttl_seconds = default_ttl_seconds
        self._lock = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._total_bytes = 0

    @staticmethod
    def _extract_tokens(text: str) -> list[str]:
        return re.findall(r"[A-Za-z0-9ěščřžýáíéóúůďťňĚŠČŘŽÝÁÍÉÓÚŮĎŤŇ_]+", text.lower())

    @staticmethod
    def _extract_numbers(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"\b\d+(?:\.\d+)?\b", text))

    @classmethod
    def _extract_negations(cls, tokens: Sequence[str]) -> tuple[str, ...]:
        return tuple(t for t in tokens if t in NEGATION_TERMS)

    def _text_to_vector(self, text: str) -> dict[str, float]:
        """Convert text into normalized term-frequency sparse vector."""
        tokens = self._extract_tokens(text)
        if not tokens:
            return {}

        counts = collections.Counter(tokens)
        norm = math.sqrt(sum(c * c for c in counts.values()))
        if norm < 1e-9:
            return {}

        return {tok: c / norm for tok, c in counts.items()}

    def _evict_lru_under_lock(self, required_bytes: int = 0) -> None:
        """Evict oldest entries when exceeding entry limit or byte limit."""
        while self._entries and (
            len(self._entries) >= self.max_entries
            or (self._total_bytes + required_bytes > self.max_bytes)
        ):
            # Find entry with oldest last_accessed_at
            oldest_id = min(self._entries, key=lambda k: self._entries[k].last_accessed_at)
            evicted = self._entries.pop(oldest_id)
            self._total_bytes = max(0, self._total_bytes - evicted.byte_size)

    def index_prompt(
        self,
        prompt_id: str,
        prompt_text: str,
        payload: Any,
        *,
        repo_root: str | None = None,
        worktree_id: str | None = None,
        revision: str | None = None,
        operation: str | None = None,
        is_mutation: bool = False,
        ttl_seconds: float | None = None,
    ) -> None:
        """Register a prompt and its verified response into thread-safe cache."""
        vec = self._text_to_vector(prompt_text)
        if not vec:
            return

        tokens = tuple(self._extract_tokens(prompt_text))
        numbers = self._extract_numbers(prompt_text)
        negations = self._extract_negations(tokens)
        normalized = " ".join(tokens)
        now = time.time()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds

        # Estimate byte size
        try:
            payload_str = json.dumps(payload, default=str)
        except Exception:
            payload_str = str(payload)
        approx_bytes = len(prompt_text.encode("utf-8")) + len(payload_str.encode("utf-8")) + 256

        with self._lock:
            # If updating existing entry, remove old size first
            if prompt_id in self._entries:
                old = self._entries.pop(prompt_id)
                self._total_bytes = max(0, self._total_bytes - old.byte_size)

            self._evict_lru_under_lock(required_bytes=approx_bytes)

            entry = CacheEntry(
                entry_id=prompt_id,
                prompt=prompt_text,
                normalized_prompt=normalized,
                vector=vec,
                tokens=tokens,
                numbers=numbers,
                negations=negations,
                payload=payload,
                created_at=now,
                last_accessed_at=now,
                repo_root=str(repo_root) if repo_root else None,
                worktree_id=str(worktree_id) if worktree_id else None,
                revision=str(revision) if revision else None,
                operation=str(operation) if operation else None,
                is_mutation=bool(is_mutation),
                ttl_seconds=effective_ttl,
                byte_size=approx_bytes,
            )
            self._entries[prompt_id] = entry
            self._total_bytes += approx_bytes

    def find_match(
        self,
        query_text: str,
        similarity_threshold: float | None = None,
        *,
        repo_root: str | None = None,
        worktree_id: str | None = None,
        revision: str | None = None,
        operation: str | None = None,
        allow_mutation: bool = False,
    ) -> SemanticMatchResult | None:
        """Find highest-similarity cached prompt and evaluate replay admissibility."""
        q_vec = self._text_to_vector(query_text)
        if not q_vec:
            return None

        q_tokens = tuple(self._extract_tokens(query_text))
        q_numbers = self._extract_numbers(query_text)
        q_negations = self._extract_negations(q_tokens)
        q_normalized = " ".join(q_tokens)
        now = time.time()
        threshold = similarity_threshold if similarity_threshold is not None else self.default_threshold

        with self._lock:
            if not self._entries:
                return None

            best_entry: CacheEntry | None = None
            best_sim = 0.0
            expired_ids: list[str] = []

            for pid, entry in list(self._entries.items()):
                # Check TTL expiration
                if entry.ttl_seconds and (now - entry.created_at > entry.ttl_seconds):
                    expired_ids.append(pid)
                    continue

                # Dot product of normalized vectors = cosine similarity
                sim = sum(val * entry.vector[term] for term, val in q_vec.items() if term in entry.vector)
                if sim > best_sim:
                    best_sim = sim
                    best_entry = entry

            # Purge expired entries
            for eid in expired_ids:
                exp = self._entries.pop(eid, None)
                if exp:
                    self._total_bytes = max(0, self._total_bytes - exp.byte_size)

            if not best_entry or best_sim < threshold:
                return None

            # Touch LRU access time
            updated_entry = CacheEntry(
                entry_id=best_entry.entry_id,
                prompt=best_entry.prompt,
                normalized_prompt=best_entry.normalized_prompt,
                vector=best_entry.vector,
                tokens=best_entry.tokens,
                numbers=best_entry.numbers,
                negations=best_entry.negations,
                payload=best_entry.payload,
                created_at=best_entry.created_at,
                last_accessed_at=now,
                repo_root=best_entry.repo_root,
                worktree_id=best_entry.worktree_id,
                revision=best_entry.revision,
                operation=best_entry.operation,
                is_mutation=best_entry.is_mutation,
                ttl_seconds=best_entry.ttl_seconds,
                byte_size=best_entry.byte_size,
            )
            self._entries[best_entry.entry_id] = updated_entry

            is_exact = (q_normalized == best_entry.normalized_prompt)
            is_admissible = True
            rejection_reason: str | None = None

            # Replay admissibility validation (LAH-012)
            if best_entry.is_mutation and not allow_mutation:
                is_admissible = False
                rejection_reason = "mutation_replay_prohibited"
            elif repo_root and best_entry.repo_root and repo_root != best_entry.repo_root:
                is_admissible = False
                rejection_reason = "repository_mismatch"
            elif worktree_id and best_entry.worktree_id and worktree_id != best_entry.worktree_id:
                is_admissible = False
                rejection_reason = "worktree_mismatch"
            elif revision and best_entry.revision and revision != best_entry.revision:
                is_admissible = False
                rejection_reason = "revision_mismatch"
            elif operation and best_entry.operation and operation != best_entry.operation:
                is_admissible = False
                rejection_reason = "operation_mismatch"
            elif q_numbers != best_entry.numbers:
                is_admissible = False
                rejection_reason = "numeric_argument_mismatch"
            elif q_negations != best_entry.negations:
                is_admissible = False
                rejection_reason = "negation_polarity_mismatch"
            elif q_tokens != best_entry.tokens:
                # Check for word-order inversions even if all tokens are identical
                if set(q_tokens) == set(best_entry.tokens):
                    is_admissible = False
                    rejection_reason = "word_order_mismatch"

            return SemanticMatchResult(
                matched_id=best_entry.entry_id,
                similarity=round(best_sim, 4),
                cached_payload=best_entry.payload,
                matched_prompt=best_entry.prompt,
                is_hit=True,
                is_exact_match=is_exact,
                is_replay_admissible=is_admissible,
                rejection_reason=rejection_reason,
            )
