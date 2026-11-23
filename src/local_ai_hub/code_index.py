from __future__ import annotations

# Keep module globals patchable while index methods live in mixins.
# ruff: noqa: F401

from pathlib import Path
import sys
import threading
import types
from typing import Any

from .cache import MemoryLRUCache
from .code_index_candidate_parse import parse_index_candidate
from .code_index_constants import (
    ARROW_DEF,
    GENERIC_DEF,
    GO_METHOD,
    IDENT,
    IMPORT,
    INLINE_ARROW_DEF,
    JS_METHOD,
    MAX_IMPACT_DEPENDENTS,
    TRAILING_CALL_AFTER_CLOSE,
    TYPED_METHOD,
    _CONTROL_NAMES,
    _DECLARATION_CALL_PATTERNS,
    _PARSER_ANALYZER_VERSION,
    _declaration_call_spans,
)
from .code_index_locks import (
    _CODE_INDEX_INIT_LOCKS_GUARD,
    _CODE_INDEX_WRITE_LOCKS_GUARD,
    _advance_query_cache_generation,
    _code_index_initialization_lock,
    _code_index_write_lock,
    _query_cache_generation,
)
from .code_index_parse_blobs import load_parse_blobs
from .code_index_scoring import (
    _CallablePathPolicy,
    _code_index_candidate_score,
    _escape_like_literal,
    _resolve_code_index_path_policy,
    _root_archive_path_sql,
)
from .code_index_spans import (
    _arrow_body_close_position,
    _arrow_body_column,
    _arrow_expression_end_line,
    _call_edge_source,
    _callable_block_close_position,
    _callable_line_body_bounds,
    _callable_needs_close_position,
    _edge_endpoint_name,
    _expression_body_bounds,
    _find_interpolation_close,
    _interpolated_code_spans,
    _interpolated_literal_end,
    _javascript_regex_can_start,
    _javascript_regex_end,
    _mask_non_code,
    _matching_brace_close_position,
    _quoted_literal_end,
)
from .process_utils import canonical_root
from .sqlite_counts import global_row_counts, initialize_row_counts
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    incremental_vacuum,
    initialize_wal,
    is_busy_error,
    quick_sanity_check,
    sqlite_batches,
    SQLiteChangeObserver,
    write_transaction,
)

from . import code_index_files as _code_index_files
from .code_index_files import CodeIndexFileMixin
from . import code_index_query as _code_index_query
from .code_index_query import CodeIndexQueryMixin
from . import code_index_symbols as _code_index_symbols
from .code_index_symbols import CodeIndexSymbolMixin
from . import code_index_maintenance as _code_index_maintenance
from .code_index_maintenance import CodeIndexMaintenanceMixin
from . import code_index_impact as _code_index_impact
from .code_index_impact import CodeIndexImpactMixin
from . import code_index_navigation as _code_index_navigation
from .code_index_navigation import CodeIndexNavigationMixin


class CodeIndex(
    CodeIndexFileMixin,
    CodeIndexQueryMixin,
    CodeIndexSymbolMixin,
    CodeIndexMaintenanceMixin,
    CodeIndexImpactMixin,
    CodeIndexNavigationMixin,
):
    def __init__(self, config: dict[str, Any], repo_tools: Any, *, read_only: bool = False):
        if type(read_only) is not bool:
            raise TypeError("read_only must be a boolean")
        self.config = config
        self.repo_tools = repo_tools
        self.db_path = Path(config["server"]["state_dir"]) / "code-index.sqlite3"
        self._read_only = read_only
        self.parse_blob_max = int(config.get("code_index", {}).get("parse_blob_max_entries", 100000))
        self.max_index_bytes = max(1, int(config.get("code_index", {}).get("max_index_bytes", 512 * 1024 * 1024)))
        self._lock = threading.RLock()
        self._write_lock = _code_index_write_lock(self.db_path)
        if read_only:
            if self.db_path.is_symlink() or not self.db_path.is_file():
                raise FileNotFoundError("read-only code-index database is missing or unsafe")
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._status_cache: dict[str, Any] = {}
        self._rev_cache = {}
        self._rev_lock = threading.Lock()
        self._parse_blob_l1 = MemoryLRUCache(max_entries=4096, ttl_seconds=3600)
        self._parse_diagnostic = threading.local()
        self._query_l1 = MemoryLRUCache(max_entries=2048, ttl_seconds=1800)
        self._symbol_l1 = MemoryLRUCache(max_entries=2048, ttl_seconds=1800)
        self._impact_result_l1 = MemoryLRUCache(max_entries=512, ttl_seconds=1800)
        self._impact_path_format_l1 = MemoryLRUCache(max_entries=256, ttl_seconds=1800)
        self._impact_candidate_count_l1 = MemoryLRUCache(max_entries=256, ttl_seconds=1800)
        self._query_cache_generation_key = str(self.db_path.resolve())
        if not read_only:
            self._init_db()
        self._cache_observer = None if read_only else SQLiteChangeObserver(self.db_path)
        self._cache_guard = threading.RLock()
        self._observed_data_version: int | None = None
        self._reindex_callback: Any = None
        self._reindex_notifications = MemoryLRUCache(max_entries=512, ttl_seconds=30)
        self._active_roots_provider: Any = None

    def set_reindex_callback(self, callback: Any) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("reindex callback must be callable or None")
        self._reindex_callback = callback

    def set_active_roots_provider(self, callback: Any) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("active roots provider must be callable or None")
        self._active_roots_provider = callback


for _code_index_module in (
    _code_index_files,
    _code_index_query,
    _code_index_symbols,
    _code_index_maintenance,
    _code_index_impact,
    _code_index_navigation,
):
    _code_index_module.CodeIndex = CodeIndex


class _CodeIndexModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (
            _code_index_files,
            _code_index_query,
            _code_index_symbols,
            _code_index_maintenance,
            _code_index_impact,
            _code_index_navigation,
        ):
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _CodeIndexModuleProxy


__all__ = [
    'ARROW_DEF',
    'Any',
    'CodeIndex',
    'CodeIndexFileMixin',
    'CodeIndexImpactMixin',
    'CodeIndexMaintenanceMixin',
    'CodeIndexNavigationMixin',
    'CodeIndexQueryMixin',
    'CodeIndexSymbolMixin',
    'GENERIC_DEF',
    'GO_METHOD',
    'IDENT',
    'IMPORT',
    'INLINE_ARROW_DEF',
    'JS_METHOD',
    'MAX_IMPACT_DEPENDENTS',
    'MemoryLRUCache',
    'Path',
    'SQLiteChangeObserver',
    'TRAILING_CALL_AFTER_CLOSE',
    'TYPED_METHOD',
    '_CODE_INDEX_INIT_LOCKS_GUARD',
    '_CODE_INDEX_WRITE_LOCKS_GUARD',
    '_CONTROL_NAMES',
    '_CallablePathPolicy',
    '_CodeIndexModuleProxy',
    '_DECLARATION_CALL_PATTERNS',
    '_PARSER_ANALYZER_VERSION',
    '_advance_query_cache_generation',
    '_arrow_body_close_position',
    '_arrow_body_column',
    '_arrow_expression_end_line',
    '_call_edge_source',
    '_callable_block_close_position',
    '_callable_line_body_bounds',
    '_callable_needs_close_position',
    '_code_index_candidate_score',
    '_code_index_files',
    '_code_index_impact',
    '_code_index_initialization_lock',
    '_code_index_maintenance',
    '_code_index_navigation',
    '_code_index_query',
    '_code_index_symbols',
    '_code_index_write_lock',
    '_declaration_call_spans',
    '_edge_endpoint_name',
    '_escape_like_literal',
    '_expression_body_bounds',
    '_find_interpolation_close',
    '_interpolated_code_spans',
    '_interpolated_literal_end',
    '_javascript_regex_can_start',
    '_javascript_regex_end',
    '_mask_non_code',
    '_matching_brace_close_position',
    '_query_cache_generation',
    '_quoted_literal_end',
    '_resolve_code_index_path_policy',
    '_root_archive_path_sql',
    'annotations',
    'canonical_root',
    'connect_sqlite',
    'ensure_incremental_vacuum',
    'global_row_counts',
    'incremental_vacuum',
    'initialize_row_counts',
    'initialize_wal',
    'is_busy_error',
    'load_parse_blobs',
    'parse_index_candidate',
    'quick_sanity_check',
    'sqlite_batches',
    'sys',
    'threading',
    'types',
    'write_transaction',
]
