from __future__ import annotations

import re


class ProjectPolicySyncError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class _RAGSourceChangedBeforePublish(RuntimeError):
    """Source revision invalidated while a background publish was pending."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__("source_changed_before_publish")
        self.paths = sorted(set(paths))


_MAX_RERANK_CANDIDATES = 512
_INDEX_EMBED_BATCH_SIZE = 64

# Stable compatibility identity for the current RAG index contract.
RAG_INDEX_COMPAT_VERSION = "6.0.0"

_INSTALL_INTENT_RE = re.compile(
    r"(?<!\w)(?:install(?:ation|ing)?|setup|set\s+up|bootstrap|getting\s+started|"
    r"instal\w*|nainstal\w*|zprovozn\w*)(?!\w)",
    re.IGNORECASE,
)
_INSTALL_SEMANTIC_TERMS = ("install", "installation", "setup", "bootstrap", "getting started")

# Increment when chunk boundaries or chunk extraction semantics change.
RAG_CHUNKER_VERSION = "python-ast-contiguous-gaps-v3"

_CENTROID_FILTER_ENABLED = False
_CENTROID_FILTER_MIN_CHUNKS = 10_000
_CENTROID_COUNT = 64
_CENTROID_SAMPLE_SIZE = 512
_CENTROID_ITERATIONS = 8
_CENTROID_PROBES = 4
_CENTROID_CACHE_MAX_ENTRIES = 8
_CENTROID_CACHE_MAX_BYTES = 64 * 1024 * 1024
_CENTROID_ENTRY_MAX_BYTES = 16 * 1024 * 1024

_REGEX_AST_MAX_SOURCE_CHARS = 2_000_000
_REGEX_AST_BUDGET_SECONDS = 0.5
_REGEX_AST_MAX_BLOCK_DEPTH = 4096
_REGEX_AST_MAX_BLOCKS = 4096
_RUST_LIFETIME_RE = re.compile(r"'[A-Za-z_][A-Za-z0-9_]*")
