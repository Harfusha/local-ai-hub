from __future__ import annotations

# Keep module globals patchable while store methods live in mixins.
# ruff: noqa: F401

import importlib
import os
import sys
import time
import types
from typing import Any

from .cache import SingleFlightCache, SQLiteCache, TieredCache, stable_hash
from .process_utils import canonical_root, canonical_workspace_id
from .rag_centroids import (
    _CENTROID_BUILD_LOCK,
    _CENTROID_CACHE_LOCK,
    _centroid_cache_get,
    _centroid_cache_put,
    _centroid_threshold_reached,
    _decode_centroid_vector,
    _fine_cosine_scores,
)
from .rag_chunking import (
    _canonical_fragment_text,
    _check_rag_publish_budget,
    _fragment_hash,
    _python_ast_chunks,
    _rag_source_still_current,
    _read_bounded_file,
    _regex_ast_chunks,
    _reverse_text_order,
    _serialize_embedding,
    _simhash,
    _simhash_shingle_hash,
)
from .rag_constants import (
    ProjectPolicySyncError,
    RAG_CHUNKER_VERSION,
    RAG_INDEX_COMPAT_VERSION,
    _CENTROID_COUNT,
    _CENTROID_ENTRY_MAX_BYTES,
    _CENTROID_FILTER_ENABLED,
    _CENTROID_FILTER_MIN_CHUNKS,
    _CENTROID_ITERATIONS,
    _CENTROID_PROBES,
    _CENTROID_SAMPLE_SIZE,
    _INDEX_EMBED_BATCH_SIZE,
    _INSTALL_INTENT_RE,
    _INSTALL_SEMANTIC_TERMS,
    _MAX_RERANK_CANDIDATES,
    _RAGSourceChangedBeforePublish,
    _REGEX_AST_BUDGET_SECONDS,
    _REGEX_AST_MAX_BLOCK_DEPTH,
    _REGEX_AST_MAX_BLOCKS,
    _REGEX_AST_MAX_SOURCE_CHARS,
    _RUST_LIFETIME_RE,
)
from .rag_search_helpers import (
    _search_limit_reached,
    _semantic_embedding_query,
)
from .scheduler import QueueFullError
from .search_modes import search_execution_stopped
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    initialize_wal,
    is_busy_error,
    retry_busy,
    sqlite_batches,
    write_transaction,
)

from . import rag_constants as _rag_constants
from . import rag_centroids as _rag_centroids
from . import rag_chunking as _rag_chunking
from . import rag_search_helpers as _rag_search_helpers
from . import rag_storage as _rag_storage
from .rag_storage import RAGStorageMixin
from . import rag_index as _rag_index
from .rag_index import RAGIndexMixin
from . import rag_maintenance as _rag_maintenance
from .rag_maintenance import RAGMaintenanceMixin
from . import rag_search as _rag_search
from .rag_search import RAGSearchMixin
from . import rag_retrieval as _rag_retrieval
from .rag_retrieval import RAGRetrievalMixin
from . import rag_workspaces as _rag_workspaces
from .rag_workspaces import RAGWorkspaceMixin


class RAGStore(
    RAGStorageMixin,
    RAGIndexMixin,
    RAGMaintenanceMixin,
    RAGSearchMixin,
    RAGRetrievalMixin,
    RAGWorkspaceMixin,
):
    """Persistent semantic index with file-level incremental updates.

    Local AI keeps a metadata manifest so unchanged files are not reopened/chunked during
    re-index. Changed files are updated transactionally while searches keep seeing
    the previous committed snapshot until the new one is ready.
    """


for _rag_module in (
    _rag_storage,
    _rag_index,
    _rag_maintenance,
    _rag_search,
    _rag_retrieval,
    _rag_workspaces,
):
    _rag_module.RAGStore = RAGStore


class _RAGModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (
            _rag_constants,
            _rag_centroids,
            _rag_chunking,
            _rag_search_helpers,
            _rag_storage,
            _rag_index,
            _rag_maintenance,
            _rag_search,
            _rag_retrieval,
            _rag_workspaces,
        ):
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _RAGModuleProxy


__all__ = [
    'Any',
    'ProjectPolicySyncError',
    'QueueFullError',
    'RAGIndexMixin',
    'RAGMaintenanceMixin',
    'RAGRetrievalMixin',
    'RAGSearchMixin',
    'RAGStorageMixin',
    'RAGStore',
    'RAGWorkspaceMixin',
    'RAG_CHUNKER_VERSION',
    'RAG_INDEX_COMPAT_VERSION',
    'SQLiteCache',
    'SingleFlightCache',
    'TieredCache',
    '_CENTROID_BUILD_LOCK',
    '_CENTROID_CACHE_LOCK',
    '_CENTROID_COUNT',
    '_CENTROID_ENTRY_MAX_BYTES',
    '_CENTROID_FILTER_ENABLED',
    '_CENTROID_FILTER_MIN_CHUNKS',
    '_CENTROID_ITERATIONS',
    '_CENTROID_PROBES',
    '_CENTROID_SAMPLE_SIZE',
    '_INDEX_EMBED_BATCH_SIZE',
    '_INSTALL_INTENT_RE',
    '_INSTALL_SEMANTIC_TERMS',
    '_MAX_RERANK_CANDIDATES',
    '_RAGModuleProxy',
    '_RAGSourceChangedBeforePublish',
    '_REGEX_AST_BUDGET_SECONDS',
    '_REGEX_AST_MAX_BLOCKS',
    '_REGEX_AST_MAX_BLOCK_DEPTH',
    '_REGEX_AST_MAX_SOURCE_CHARS',
    '_RUST_LIFETIME_RE',
    '_canonical_fragment_text',
    '_centroid_cache_get',
    '_centroid_cache_put',
    '_centroid_threshold_reached',
    '_check_rag_publish_budget',
    '_decode_centroid_vector',
    '_fine_cosine_scores',
    '_fragment_hash',
    '_python_ast_chunks',
    '_rag_centroids',
    '_rag_chunking',
    '_rag_constants',
    '_rag_index',
    '_rag_maintenance',
    '_rag_retrieval',
    '_rag_search',
    '_rag_search_helpers',
    '_rag_source_still_current',
    '_rag_storage',
    '_rag_workspaces',
    '_read_bounded_file',
    '_regex_ast_chunks',
    '_reverse_text_order',
    '_search_limit_reached',
    '_semantic_embedding_query',
    '_serialize_embedding',
    '_simhash',
    '_simhash_shingle_hash',
    'annotations',
    'canonical_root',
    'canonical_workspace_id',
    'connect_sqlite',
    'ensure_incremental_vacuum',
    'importlib',
    'initialize_wal',
    'is_busy_error',
    'os',
    'retry_busy',
    'search_execution_stopped',
    'sqlite_batches',
    'stable_hash',
    'sys',
    'time',
    'types',
    'write_transaction',
]
