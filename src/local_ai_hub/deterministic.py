from __future__ import annotations

import sys
import types

# Keep module globals patchable while engine methods live in mixins.
# ruff: noqa: F401


from .json_utils import dumps as json_dumps
from .diagnostic_compression import compress_diagnostic_text
from .deterministic_answer_rendering import render_deterministic_answer
from .related_path_ranking import rank_related_paths
from .file_card_summary import build_file_card
from .module_card_summary import build_module_card_summary
from .project_card_summary import build_project_card_summary
from .config_flattening import flatten_config_values
from .manifest_discovery import select_manifest_files, walk_manifest_paths
from .manifest_dispatch import parse_manifest_dispatch
from .deterministic_intent_classification import classify_deterministic_intent
from .call_graph_diff import analyze_call_graph_diff
from .deterministic_slice_merging import merge_overlapping_source_slices
from .structural_search import search_structurally
from .infra_facts import extract_infra_facts
from .breaking_change_detection import compare_api_definitions
from .unified_diff_parser import parse_unified_diff
from .python_shell_injection import _python_shell_injection_lines
from .python_relations import find_python_relations
from .secret_scan_config import (
    _SECRET_SCAN_MAX_ENTRIES,
    _SECRET_SCAN_MAX_FILES,
    _SECRET_SCAN_MAX_FILE_BYTES,
    _SECRET_SCAN_MAX_TOTAL_BYTES,
    _SECRET_SCAN_MAX_LINE_BYTES,
    _SECRET_SCAN_MAX_SECONDS,
    _SECRET_SCAN_MAX_FINDINGS,
    _SECRET_SCAN_PATTERNS,
)
from .secret_scanning import scan_secrets
from .migration_drift import detect_migration_drift
from .complexity_analysis import compute_code_complexity
from .security_audit import run_security_audit
from .split_changes import run_split_changes
from .dataset_generation import build_dataset
from .profile_digest import build_profile_digest
from .code_invariants import run_code_invariants
from .dead_code_detection import find_dead_code
from .deterministic_exact_evidence import collect_exact_evidence
from .circular_dependency_analysis import find_circular_dependencies as find_indexed_circular_dependencies
from .schema_file_scanning import scan_schema_files
from .git_history_search import search_git_history, _git_history_timestamp, _git_history_pathspec
from .query_intent_terms import filter_intent_noise
from .batch_replace_dirty_hunks import parse_dirty_hunks
from .deterministic_symbol_context import build_symbol_context

import ast
import hashlib
import io
import json
import logging
import keyword
import math
import os
import re
import sqlite3
import shutil
import stat
import subprocess
import threading
import time
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from . import __version__
from .cache import MemoryLRUCache, SQLiteCache, stable_hash
from .normalizer import tokenize_query_terms
from .sqlite_support import (
    SQLiteChangeObserver, connect_sqlite, initialize_wal, is_busy_error,
    quick_sanity_check, sqlite_batches, write_transaction,
)
from .sqlite_counts import global_row_counts, initialize_row_counts
from .diff_parsers import (
    extract_cs_diff_defs,
    extract_go_diff_defs,
    extract_py_diff_defs,
    extract_rust_diff_defs,
    extract_ts_diff_defs,
)
from .search_pagination import pagination_bounds_error
from .source_outline import ast_outline as _source_ast_outline, fold_brace_blocks as _fold_brace_blocks
from .process_utils import (
    ProcessCleanupUnverifiedError, canonical_root,
    clean_git_env, hidden_run_kwargs, run_hidden,
)
from .repo_tools import is_root_archive_path
from .deterministic_test_paths import (
    build_test_file_result, build_test_matrix_response, collect_test_matrix_rows,
    extract_test_case_names,
    is_test_file as _is_test_file, is_test_matrix_source, run_test_matrix_workers,
    select_test_matrix_targets,
)
from .test_matrix_commands import build_test_file_command
from .topology_summary import build_topology_summary_markdown
from .topology_labels import classify_topology_layer
from .test_framework_selection import detect_test_framework, select_test_framework
from .state_paths import configured_state_dir


logger = logging.getLogger(__name__)


from .reparse_points import (
    _is_directory_reparse_point as _is_directory_reparse_point,
    _is_symlink_or_reparse_point as _is_symlink_or_reparse_point,
)


_MAX_SCHEMA_SCAN_DIRS = 10_000
from .deterministic_constants import (
    _GIT_INSIGHT_DEADLINE_SECONDS as _GIT_INSIGHT_DEADLINE_SECONDS,
    _GIT_INSIGHT_STREAM_LIMIT as _GIT_INSIGHT_STREAM_LIMIT,
    _MAX_SCHEMA_DB_BYTES as _MAX_SCHEMA_DB_BYTES,
    _MAX_SCHEMA_DB_COLUMNS as _MAX_SCHEMA_DB_COLUMNS,
    _MAX_SCHEMA_DB_TABLES as _MAX_SCHEMA_DB_TABLES,
    _MAX_SCHEMA_FILE_BYTES as _MAX_SCHEMA_FILE_BYTES,
    _MAX_SCHEMA_MIGRATION_DB_BYTES as _MAX_SCHEMA_MIGRATION_DB_BYTES,
    _MAX_SCHEMA_SCAN_DIRS as _MAX_SCHEMA_SCAN_DIRS,
    _MAX_SCHEMA_SCAN_ENTRIES as _MAX_SCHEMA_SCAN_ENTRIES,
    _MAX_SCHEMA_SCAN_FILES as _MAX_SCHEMA_SCAN_FILES,
    _MAX_SCHEMA_SCAN_SECONDS as _MAX_SCHEMA_SCAN_SECONDS,
    _MAX_SCHEMA_TOTAL_BYTES as _MAX_SCHEMA_TOTAL_BYTES,
    _SCHEMA_DB_TIMEOUT_SECONDS as _SCHEMA_DB_TIMEOUT_SECONDS,
    _SQLITE_DISCOVERY_MAX_ENTRIES as _SQLITE_DISCOVERY_MAX_ENTRIES,
    _SQLITE_DISCOVERY_MAX_SECONDS as _SQLITE_DISCOVERY_MAX_SECONDS,
    TEST_MARKERS as TEST_MARKERS,
)
from .diff_regexes import (
    _DIFF_EVAL_I as _DIFF_EVAL_I,
    _DIFF_SECRET_PASSWORD_I as _DIFF_SECRET_PASSWORD_I,
    _DIFF_SHELL_I as _DIFF_SHELL_I,
)
from .source_facts import (
    CONCURRENCY_RE,
    SECURITY_RE,
    SQL_RE,
    extract_source_facts as _extract_source_facts,
)

from .api_spec_extraction import (
    extract_api_spec as _extract_api_spec,
)
from .repo_topology import repo_topology as _repo_topology

from .hotspot_analysis import (
    find_hotspots as _find_hotspots,
)





from .schema_file_bounds import _bounded_schema_files as _bounded_schema_files


_WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$:/-]{1,100}")


from .security_audit_patterns import (
    _SECURITY_AUDIT_SECRETS as _SECURITY_AUDIT_SECRETS,
    _SECURITY_AUDIT_SMELLS as _SECURITY_AUDIT_SMELLS,
    _pattern_match_lines as _pattern_match_lines,
    _yaml_load_match_lines as _yaml_load_match_lines,
)


_BRACE_FUNCTION_EXPORT = re.compile('^\\s*(?:(?:pub(?:lic)?|priv(?:ate)?|prot(?:ected)?|internal|static|async|export|default|override|virtual|final)\\s+)*(?:(?:func|fn|function|def)\\b|(?:[A-Za-z_$][\\w.<>,\\[\\]]*\\s+)+[A-Za-z_$][\\w$]*\\s*\\()|^\\s*(?:func\\s*\\([^)]*\\)\\s*)?[A-Za-z_$][\\w$]*\\s*\\([^)]*\\)\\s*(?:[^{;]*\\{|=>)')
_BRACE_CLASS_INTERFACE = re.compile('^\\s*(?:(?:pub(?:lic)?|export)\\s+)*(?:struct|interface|enum|type|trait|class)\\b')


from . import deterministic_index as _deterministic_index
from .deterministic_index import DeterministicIndexMixin
from . import deterministic_build as _deterministic_build
from .deterministic_build import DeterministicBuildMixin
from . import deterministic_analysis as _deterministic_analysis
from .deterministic_analysis import DeterministicAnalysisMixin
from . import deterministic_security as _deterministic_security
from .deterministic_security import DeterministicSecurityMixin
from . import deterministic_tests as _deterministic_tests
from .deterministic_tests import DeterministicTestMixin
from . import deterministic_editing as _deterministic_editing
from .deterministic_editing import DeterministicEditingMixin
from . import deterministic_search as _deterministic_search
from .deterministic_search import DeterministicSearchMixin

class DeterministicEngine(DeterministicIndexMixin, DeterministicBuildMixin, DeterministicAnalysisMixin, DeterministicSecurityMixin, DeterministicTestMixin, DeterministicEditingMixin, DeterministicSearchMixin):
    """Persistent deterministic project intelligence before any LLM inference.

    The engine extracts facts from source/config/manifests with stdlib parsers and
    conservative regexes. Every file is content-addressed, so unchanged facts are
    reused across agents/restarts. Query resolution never rewrites source evidence;
    it returns coordinates and exact evidence ids supplied by EvidenceStore.
    """



















































    _extract_py_diff_defs = staticmethod(extract_py_diff_defs)
    _extract_ts_diff_defs = staticmethod(extract_ts_diff_defs)
    _extract_cs_diff_defs = staticmethod(extract_cs_diff_defs)
    _extract_go_diff_defs = staticmethod(extract_go_diff_defs)
    _extract_rust_diff_defs = staticmethod(extract_rust_diff_defs)















    KNOWN_CVE_SIGNATURES = {
        "newtonsoft.json": ("13.0.1", "CVE-2024-21907 (Improper Handling of Highly Nested Data)"),
        "log4net": ("2.0.10", "CVE-2018-1285 (XML External Entity Injection)"),
        "protobuf": ("3.15.0", "CVE-2021-22569 (Denial of Service in parser)"),
        "urllib3": ("2.0.7", "CVE-2023-45803 (Request body leak on redirect)"),
        "requests": ("2.31.0", "CVE-2023-32681 (Proxy Authorization Header Leak)"),
        "cryptography": ("41.0.6", "CVE-2023-49083 (NULL-dereference in PKCS7)"),
        "flask": ("2.2.5", "CVE-2023-30861 (Cookie session disclose)"),
        "django": ("4.2.11", "CVE-2024-27351 (ReDoS in EmailValidator)"),
        "lodash": ("4.17.21", "CVE-2021-23337 (Command Injection via template)"),
        "axios": ("1.6.0", "CVE-2023-45857 (Cross-Site Request Forgery)"),
        "fastapi": ("0.100.0", "CVE-2024-24762 (ReDoS in form-data parser)"),
    }


























































class _DeterministicModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (_deterministic_index, _deterministic_build, _deterministic_analysis, _deterministic_security, _deterministic_tests, _deterministic_editing, _deterministic_search):
            if hasattr(module, name):
                setattr(module, name, value)

sys.modules[__name__].__class__ = _DeterministicModuleProxy


__all__ = [
    'Any',
    'CONCURRENCY_RE',
    'Counter',
    'DeterministicAnalysisMixin',
    'DeterministicBuildMixin',
    'DeterministicEditingMixin',
    'DeterministicEngine',
    'DeterministicIndexMixin',
    'DeterministicSearchMixin',
    'DeterministicSecurityMixin',
    'DeterministicTestMixin',
    'ET',
    'MemoryLRUCache',
    'Path',
    'ProcessCleanupUnverifiedError',
    'PurePosixPath',
    'PureWindowsPath',
    'SECURITY_RE',
    'SQL_RE',
    'SQLiteCache',
    'SQLiteChangeObserver',
    'TEST_MARKERS',
    '_BRACE_CLASS_INTERFACE',
    '_BRACE_FUNCTION_EXPORT',
    '_DIFF_EVAL_I',
    '_DIFF_SECRET_PASSWORD_I',
    '_DIFF_SHELL_I',
    '_DeterministicModuleProxy',
    '_GIT_INSIGHT_DEADLINE_SECONDS',
    '_GIT_INSIGHT_STREAM_LIMIT',
    '_MAX_SCHEMA_DB_BYTES',
    '_MAX_SCHEMA_DB_COLUMNS',
    '_MAX_SCHEMA_DB_TABLES',
    '_MAX_SCHEMA_FILE_BYTES',
    '_MAX_SCHEMA_MIGRATION_DB_BYTES',
    '_MAX_SCHEMA_SCAN_DIRS',
    '_MAX_SCHEMA_SCAN_ENTRIES',
    '_MAX_SCHEMA_SCAN_FILES',
    '_MAX_SCHEMA_SCAN_SECONDS',
    '_MAX_SCHEMA_TOTAL_BYTES',
    '_SCHEMA_DB_TIMEOUT_SECONDS',
    '_SECRET_SCAN_MAX_ENTRIES',
    '_SECRET_SCAN_MAX_FILES',
    '_SECRET_SCAN_MAX_FILE_BYTES',
    '_SECRET_SCAN_MAX_FINDINGS',
    '_SECRET_SCAN_MAX_LINE_BYTES',
    '_SECRET_SCAN_MAX_SECONDS',
    '_SECRET_SCAN_MAX_TOTAL_BYTES',
    '_SECRET_SCAN_PATTERNS',
    '_SECURITY_AUDIT_SECRETS',
    '_SECURITY_AUDIT_SMELLS',
    '_SQLITE_DISCOVERY_MAX_ENTRIES',
    '_SQLITE_DISCOVERY_MAX_SECONDS',
    '_WORD',
    '__version__',
    '_bounded_schema_files',
    '_deterministic_analysis',
    '_deterministic_build',
    '_deterministic_editing',
    '_deterministic_index',
    '_deterministic_search',
    '_deterministic_security',
    '_deterministic_tests',
    '_extract_api_spec',
    '_extract_source_facts',
    '_find_hotspots',
    '_fold_brace_blocks',
    '_git_history_pathspec',
    '_git_history_timestamp',
    '_is_directory_reparse_point',
    '_is_symlink_or_reparse_point',
    '_is_test_file',
    '_pattern_match_lines',
    '_python_shell_injection_lines',
    '_repo_topology',
    '_source_ast_outline',
    '_yaml_load_match_lines',
    'analyze_call_graph_diff',
    'annotations',
    'ast',
    'build_dataset',
    'build_file_card',
    'build_module_card_summary',
    'build_profile_digest',
    'build_project_card_summary',
    'build_symbol_context',
    'build_test_file_command',
    'build_test_file_result',
    'build_test_matrix_response',
    'build_topology_summary_markdown',
    'canonical_root',
    'classify_deterministic_intent',
    'classify_topology_layer',
    'clean_git_env',
    'closing',
    'collect_exact_evidence',
    'collect_test_matrix_rows',
    'compare_api_definitions',
    'compress_diagnostic_text',
    'compute_code_complexity',
    'configured_state_dir',
    'connect_sqlite',
    'defaultdict',
    'detect_migration_drift',
    'detect_test_framework',
    'extract_cs_diff_defs',
    'extract_go_diff_defs',
    'extract_infra_facts',
    'extract_py_diff_defs',
    'extract_rust_diff_defs',
    'extract_test_case_names',
    'extract_ts_diff_defs',
    'filter_intent_noise',
    'find_dead_code',
    'find_indexed_circular_dependencies',
    'find_python_relations',
    'flatten_config_values',
    'global_row_counts',
    'hashlib',
    'hidden_run_kwargs',
    'initialize_row_counts',
    'initialize_wal',
    'io',
    'is_busy_error',
    'is_root_archive_path',
    'is_test_matrix_source',
    'json',
    'json_dumps',
    'keyword',
    'logger',
    'logging',
    'math',
    'merge_overlapping_source_slices',
    'os',
    'pagination_bounds_error',
    'parse_dirty_hunks',
    'parse_manifest_dispatch',
    'parse_unified_diff',
    'quick_sanity_check',
    'rank_related_paths',
    're',
    'render_deterministic_answer',
    'run_code_invariants',
    'run_hidden',
    'run_security_audit',
    'run_split_changes',
    'run_test_matrix_workers',
    'scan_schema_files',
    'scan_secrets',
    'search_git_history',
    'search_structurally',
    'select_manifest_files',
    'select_test_framework',
    'select_test_matrix_targets',
    'shutil',
    'sqlite3',
    'sqlite_batches',
    'stable_hash',
    'stat',
    'subprocess',
    'sys',
    'threading',
    'time',
    'tokenize_query_terms',
    'tomllib',
    'types',
    'walk_manifest_paths',
    'write_transaction',
]
