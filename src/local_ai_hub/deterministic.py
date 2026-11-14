from __future__ import annotations

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
from .python_relations import _RELATION_SCAN_MAX_SECONDS, find_python_relations
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
import sys
import threading
import time
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date as _datetime_date, datetime as _datetime, time as _datetime_time, timezone as _datetime_timezone
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterator

from . import __version__
from .cache import MemoryLRUCache, SQLiteCache, stable_hash
from .code_index import _mask_non_code
from .normalizer import tokenize_query_terms
from .sqlite_support import (
    SQLiteChangeObserver, connect_sqlite, initialize_wal, is_busy_error,
    quick_sanity_check, sqlite_batches,
)
from .sqlite_counts import global_row_counts, initialize_row_counts
from .diff_parsers import (
    extract_cs_diff_defs,
    extract_go_diff_defs,
    extract_py_diff_defs,
    extract_rust_diff_defs,
    extract_ts_diff_defs,
)
from .secret_history import parse_git_patch_output
from .search_pagination import pagination_bounds_error
from .process_utils import (
    ProcessCancelledError, ProcessCleanupUnverifiedError, canonical_root,
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
from .api_spec_document import build_api_spec_document
from .topology_summary import build_topology_summary_markdown
from .topology_labels import classify_topology_layer
from .test_framework_selection import detect_test_framework, select_test_framework
from .state_paths import configured_state_dir


logger = logging.getLogger(__name__)


def _is_directory_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            return True
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if getattr(metadata, "st_file_attributes", 0) & reparse_point:
            return True
        is_junction = getattr(path, "is_junction", None)
        return callable(is_junction) and is_junction()
    except OSError:
        return True


_MAX_SCHEMA_SCAN_DIRS = 10_000
_MAX_SCHEMA_SCAN_FILES = 512
_MAX_SCHEMA_SCAN_ENTRIES = 50_000
_MAX_SCHEMA_DB_TABLES = 4_096
_MAX_SCHEMA_DB_COLUMNS = 65_536
_MAX_SCHEMA_DB_BYTES = 268_435_456
_MAX_SCHEMA_MIGRATION_DB_BYTES = 8_388_608
_MAX_SCHEMA_FILE_BYTES = 1_048_576
_MAX_SCHEMA_TOTAL_BYTES = 16_777_216
_MAX_SCHEMA_SCAN_SECONDS = 3.0
_SCHEMA_DB_TIMEOUT_SECONDS = 1.0

_GIT_INSIGHT_STREAM_LIMIT = 1_048_576
from .source_facts import (
    CONCURRENCY_RE,
    CONFIG_PATTERNS,
    ENV_PATTERNS,
    ROUTE_PATTERNS,
    SECURITY_RE,
    SQL_RE,
    TODO_RE,
    _SOURCE_ACTION_ATTR,
    _SOURCE_ARTISAN_CMD,
    _SOURCE_ASYNC_DEF_RE,
    _SOURCE_BLADE_DIRECTIVE,
    _SOURCE_CAKE_ASSOC,
    _SOURCE_CAKE_ENTITY,
    _SOURCE_CAKE_MIGRATION,
    _SOURCE_CAKE_RESOURCES,
    _SOURCE_CAKE_ROUTE,
    _SOURCE_CAKE_TABLE,
    _SOURCE_CSS_CLASS,
    _SOURCE_CSS_VAR,
    _SOURCE_DATACLASS_RE,
    _SOURCE_DECORATOR_RE,
    _SOURCE_ELEM_ID,
    _SOURCE_ELOQUENT_FILLABLE,
    _SOURCE_ELOQUENT_REL,
    _SOURCE_ELOQUENT_TABLE,
    _SOURCE_FORM_REQ,
    _SOURCE_FORM_TAG,
    _SOURCE_HARDCODED_IP,
    _SOURCE_IMPORT_FROM,
    _SOURCE_JS_IMPORT,
    _SOURCE_KEYFRAMES,
    _SOURCE_LARAVEL_RESOURCE,
    _SOURCE_LINK_CSS,
    _SOURCE_MEDIA_QUERY,
    _SOURCE_METHOD_ATTR,
    _SOURCE_MIGRATION_COL,
    _SOURCE_NEST_DECORATOR,
    _SOURCE_NEXT_ROUTE_HANDLER,
    _SOURCE_PHP_ATTR,
    _SOURCE_PHP_DEF,
    _SOURCE_PHP_FUNC,
    _SOURCE_PHP_NS,
    _SOURCE_PHP_ROUTE_ATTR,
    _SOURCE_PHP_TESTED_CLASS,
    _SOURCE_PHP_USE,
    _SOURCE_REACT_COMPONENT,
    _SOURCE_REACT_HOOK,
    _SOURCE_REACT_ROUTE,
    _SOURCE_SCHEMA_CREATE,
    _SOURCE_SCRIPT_SRC,
    _SOURCE_SECRET_RE,
    _SOURCE_TABLE_INSERT_I,
    _SOURCE_TESTED_CLASS,
    _SOURCE_TEST_SUITE_BLOCK,
    _SOURCE_TS_DECLARATION,
    _SOURCE_UNITY_LIFECYCLES,
    _SOURCE_WEB_COMPONENT,
    _SOURCE_WP_HOOK,
    extract_source_facts as _extract_source_facts,
)

from .api_spec_extraction import (
    _API_ATTRIBUTE_ROUTE_DECLARATION,
    _API_EXPRESS_ROUTER_METHOD,
    _API_HTML_FORM_ENDPOINT,
    _API_LARAVEL_RESOURCE_ROUTE,
    _API_LARAVEL_ROUTE_METHOD,
    _API_NEXT_ROUTE_HANDLER,
    _API_PHP_CONNECT_ROUTE,
    _API_PHP_RESOURCE_ROUTE,
    extract_api_spec as _extract_api_spec,
)
from .repo_topology import repo_topology as _repo_topology

from .hotspot_analysis import (
    _HOTSPOT_ALGORITHM,
    _HOTSPOT_ANALYSIS_SECONDS,
    _HOTSPOT_FILE_BYTES_LIMIT,
    _HOTSPOT_FILE_LIMIT,
    _HOTSPOT_GIT_COMMIT_LIMIT,
    _HOTSPOT_PATH_LIMIT,
    _HOTSPOT_TOTAL_BYTES_LIMIT,
    find_hotspots as _find_hotspots,
)


def _is_symlink_or_reparse_point(path: Path) -> bool:
    info = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = int(getattr(info, "st_file_attributes", 0) or 0)
    is_junction = getattr(os.path, "isjunction", None)
    return (
        stat.S_ISLNK(info.st_mode)
        or bool(attributes & reparse_flag)
        or (callable(is_junction) and is_junction(path))
    )


def _bounded_schema_files(
    root: Path,
    *,
    suffix: str,
    deadline: float,
    migrations_only: bool = False,
) -> list[Path]:
    return scan_schema_files(
        root,
        suffix=suffix,
        deadline=deadline,
        migrations_only=migrations_only,
        max_dirs=_MAX_SCHEMA_SCAN_DIRS,
        max_entries=_MAX_SCHEMA_SCAN_ENTRIES,
        max_files=_MAX_SCHEMA_SCAN_FILES,
    )


_WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$:/-]{1,100}")
TEST_MARKERS = ("/test/", "/tests/", "/spec/", "/specs/", "_test.", ".test.", "_spec.", ".spec.")


_SECURITY_AUDIT_SECRETS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("GitHub Token", re.compile(r"\b(ghp_[0-9a-zA-Z]{36}|github_pat_[0-9a-zA-Z_]{82})\b")),
    ("Slack Token", re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b")),
    ("Private Key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Hardcoded Password", re.compile(r"""(?:password|passwd|pwd|secret|api_key)\s*[:=]\s*["']([^"'\s]{6,})["']""", re.I)),
]

_SECURITY_AUDIT_SMELLS: list[tuple[str, re.Pattern[str]]] = [
    ("Unsafe eval/exec", re.compile(r"(?<![.\w])(eval|exec)\s*\(")),
    ("Unsafe Pickle", re.compile(r"\bpickle\.loads?\s*\(")),
    ("Unsafe PyYAML", re.compile(r"\byaml\.load\s*\([^,]+(?:\)|,\s*Loader\s*=\s*(?:yaml\.)?(?:Unsafe|Full)?Loader\b)")),
    ("Shell Injection Risk", re.compile(r"\bsubprocess\.(?:Popen|run|call)\s*\(.*shell\s*=\s*True", re.S)),
]


def _pattern_match_lines(text: str, pattern: re.Pattern[str]) -> list[int]:
    """Map regex matches to lines with one cumulative scan, not repeated prefixes."""
    line_number = 1
    previous_start = 0
    matched_lines: set[int] = set()
    for match in pattern.finditer(text):
        line_number += text.count("\n", previous_start, match.start())
        matched_lines.add(line_number)
        previous_start = match.start()
    return sorted(matched_lines)


_YAML_LOAD_START = re.compile(r"\byaml\.load\s*\(")
_YAML_LOADER_SUFFIX = re.compile(r",\s*Loader\s*=\s*(?:yaml\.)?(?:Unsafe|Full)?Loader\b")


def _yaml_load_match_lines(text: str) -> list[int]:
    """Match the PyYAML audit rule without rescanning an unterminated suffix."""
    cursor = 0
    segment_end = -1
    last_close = -1
    loader_end = None
    line_number = 1
    previous_start = 0
    matched_lines: set[int] = set()
    for match in _YAML_LOAD_START.finditer(text):
        start, content_start = match.start(), match.end()
        if start < cursor:
            continue
        if start >= segment_end:
            comma = text.find(",", content_start)
            segment_end = comma if comma >= 0 else len(text) + 1
            last_close = text.rfind(")", content_start, comma if comma >= 0 else len(text))
            suffix = _YAML_LOADER_SUFFIX.match(text, comma) if comma >= 0 else None
            loader_end = suffix.end() if suffix else None
        if loader_end is not None and segment_end > content_start:
            cursor = loader_end
        elif last_close > content_start:
            cursor = last_close + 1
        else:
            continue
        line_number += text.count("\n", previous_start, start)
        matched_lines.add(line_number)
        previous_start = start
    return sorted(matched_lines)






_DIFF_SHELL_I = re.compile('\\b(exec|system|shell_exec|subprocess|Process\\.Start|Runtime\\.getRuntime)\\b', re.I)
_DIFF_EVAL_I = re.compile('\\b(eval|exec)\\s*\\(', re.I)
_DIFF_SECRET_PASSWORD_I = re.compile('\\b(password|secret|api[_-]?key|private[_-]?key|token)\\b', re.I)
_BRACE_FUNCTION_EXPORT = re.compile('^\\s*(?:(?:pub(?:lic)?|priv(?:ate)?|prot(?:ected)?|internal|static|async|export|default|override|virtual|final)\\s+)*(?:(?:func|fn|function|def)\\b|(?:[A-Za-z_$][\\w.<>,\\[\\]]*\\s+)+[A-Za-z_$][\\w$]*\\s*\\()|^\\s*(?:func\\s*\\([^)]*\\)\\s*)?[A-Za-z_$][\\w$]*\\s*\\([^)]*\\)\\s*(?:[^{;]*\\{|=>)')
_BRACE_CLASS_INTERFACE = re.compile('^\\s*(?:(?:pub(?:lic)?|export)\\s+)*(?:struct|interface|enum|type|trait|class)\\b')


class DeterministicEngine:
    """Persistent deterministic project intelligence before any LLM inference.

    The engine extracts facts from source/config/manifests with stdlib parsers and
    conservative regexes. Every file is content-addressed, so unchanged facts are
    reused across agents/restarts. Query resolution never rewrites source evidence;
    it returns coordinates and exact evidence ids supplied by EvidenceStore.
    """

    def __init__(self, config: dict[str, Any] | None = None, repo_tools: Any = None, code_index: Any = None, evidence: Any | None = None):
        config = config or {}
        self.config = config
        if repo_tools is None:
            from .repo_tools import RepositoryTools
            repo_tools = RepositoryTools(config)
        self.repo_tools = repo_tools
        self.code_index = code_index
        self.evidence = evidence
        cfg = config.get("deterministic", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.direct_confidence = float(cfg.get("direct_confidence", 0.94))
        self.max_query_results = int(cfg.get("max_query_results", 24))
        self.max_evidence = int(cfg.get("max_evidence", 12))
        self.max_manifest_bytes = int(cfg.get("max_manifest_bytes", 1_500_000))
        workspace_cache = config.get("workspace_cache", {})
        self.git_status_timeout = max(0.5, float(workspace_cache.get("git_status_timeout_seconds", 2.5)))
        self.db_path = configured_state_dir(config) / "deterministic.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._stats = Counter()
        self._query_l1: dict[tuple[str, int, str], tuple[float, dict[str, Any]]] = {}
        self._query_l1_max = int(cfg.get("query_cache_l1_entries", 512))
        self._query_l1_ttl = float(cfg.get("query_cache_l1_ttl_seconds", 300))
        self._query_l2_ttl = float(cfg.get("query_cache_l2_ttl_seconds", 86400))
        self._query_l2_max_per_root = int(cfg.get("query_cache_l2_max_entries_per_root", 4000))
        audit_cfg = config.get("dependency_audit", {})
        self._osv_cache = SQLiteCache(
            configured_state_dir(config) / "cache.sqlite", "dependency-audit:osv",
            ttl_seconds=max(60, int(audit_cfg.get("osv_cache_ttl_seconds", 6 * 3600))), max_entries=20000,
        )
        self._fact_blob_max = int(cfg.get("fact_blob_max_entries", 100000))
        self._manifest_blob_max = int(cfg.get("manifest_blob_max_entries", 20000))
        self._fact_blob_l1 = MemoryLRUCache(max_entries=4096, ttl_seconds=3600)
        self._manifest_blob_l1 = MemoryLRUCache(max_entries=1024, ttl_seconds=3600)
        self._init_db()
        self._cache_observer = SQLiteChangeObserver(self.db_path)
        self._observed_data_version: int | None = None

    def close(self) -> None:
        observer = getattr(self, "_cache_observer", None)
        if observer is not None:
            observer.close()

    def _refresh_external_caches(self) -> bool:
        with self._lock:
            version = self._cache_observer.version()
            if version is None or version != self._observed_data_version:
                self._query_l1.clear()
                self._fact_blob_l1.clear()
                self._manifest_blob_l1.clear()
            self._observed_data_version = version
            return version is not None

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=5.0, row_factory=sqlite3.Row)
        try:
            con.execute("PRAGMA recursive_triggers=ON")
        except Exception:
            con.close()
            raise
        try:
            con.execute("PRAGMA cache_size=-16000")
            con.execute("PRAGMA mmap_size=134217728")
        except sqlite3.OperationalError:
            pass
        return con

    def _schema(self, con: sqlite3.Connection) -> None:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS files(
              root TEXT NOT NULL,path TEXT NOT NULL,content_hash TEXT NOT NULL,language TEXT NOT NULL,
              is_test INTEGER NOT NULL DEFAULT 0,updated_at REAL NOT NULL,PRIMARY KEY(root,path));
            CREATE TABLE IF NOT EXISTS facts(
              root TEXT NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,value TEXT NOT NULL,
              line INTEGER NOT NULL DEFAULT 0,extra_json TEXT NOT NULL DEFAULT '{}');
            CREATE INDEX IF NOT EXISTS idx_facts_root_kind_name ON facts(root,kind,name);
            CREATE INDEX IF NOT EXISTS idx_facts_root_name_kind ON facts(root,name,kind);
            CREATE INDEX IF NOT EXISTS idx_facts_root_path ON facts(root,path);
            CREATE TABLE IF NOT EXISTS dependencies(
              root TEXT NOT NULL,source TEXT NOT NULL,name TEXT NOT NULL,version TEXT NOT NULL DEFAULT '',scope TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(root,source,name,scope));
            CREATE INDEX IF NOT EXISTS idx_dependencies_root_name ON dependencies(root,name);
            CREATE INDEX IF NOT EXISTS idx_dependencies_root_name_lc ON dependencies(root,lower(name));
            CREATE TABLE IF NOT EXISTS scripts(
              root TEXT NOT NULL,source TEXT NOT NULL,name TEXT NOT NULL,command TEXT NOT NULL,purpose TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(root,source,name));
            CREATE INDEX IF NOT EXISTS idx_scripts_root_name_lc ON scripts(root,lower(name));
            CREATE TABLE IF NOT EXISTS project_state(
              root TEXT PRIMARY KEY,manifest_hash TEXT NOT NULL DEFAULT '',generation INTEGER NOT NULL DEFAULT 0,updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS query_cache(
              root TEXT NOT NULL,generation INTEGER NOT NULL,query_key TEXT NOT NULL,result_json TEXT NOT NULL,updated_at REAL NOT NULL,
              PRIMARY KEY(root,generation,query_key));
            CREATE INDEX IF NOT EXISTS idx_query_cache_updated ON query_cache(updated_at);
            CREATE TABLE IF NOT EXISTS fact_blobs(
              content_hash TEXT NOT NULL,analyzer_version TEXT NOT NULL,language TEXT NOT NULL,facts_json TEXT NOT NULL,updated_at REAL NOT NULL,
              PRIMARY KEY(content_hash,analyzer_version,language));
            CREATE INDEX IF NOT EXISTS idx_fact_blobs_updated ON fact_blobs(updated_at);
            CREATE TABLE IF NOT EXISTS manifest_blobs(
              content_hash TEXT NOT NULL,analyzer_version TEXT NOT NULL,filename TEXT NOT NULL,deps_json TEXT NOT NULL,scripts_json TEXT NOT NULL,updated_at REAL NOT NULL,
              PRIMARY KEY(content_hash,analyzer_version,filename));
            CREATE INDEX IF NOT EXISTS idx_manifest_blobs_updated ON manifest_blobs(updated_at);

            CREATE TABLE IF NOT EXISTS unreferenced_symbols(
              root TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL,
              kind TEXT NOT NULL, line INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
              PRIMARY KEY(root, path, name));
            CREATE INDEX IF NOT EXISTS idx_unref_sym_root ON unreferenced_symbols(root);

            CREATE TABLE IF NOT EXISTS test_source_links(
              root TEXT NOT NULL, source_path TEXT NOT NULL, test_path TEXT NOT NULL,
              confidence REAL NOT NULL DEFAULT 1.0, updated_at REAL NOT NULL,
              PRIMARY KEY(root, source_path, test_path));
            CREATE INDEX IF NOT EXISTS idx_test_source_links_src ON test_source_links(root, source_path);
            CREATE INDEX IF NOT EXISTS idx_test_source_links_test ON test_source_links(root, test_path);

            """
        )
        try:
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts USING fts5(root UNINDEXED,path UNINDEXED,kind UNINDEXED,name,value)")
        except sqlite3.OperationalError:
            pass
        con.execute("CREATE TABLE IF NOT EXISTS _det_batch_active(root TEXT PRIMARY KEY)")
        initialize_row_counts(con, ("files", "facts", "dependencies", "scripts", "unreferenced_symbols"))
        # Source writes from any SQLite connection must invalidate both cache tiers,
        # including raw external writes that do not call _bump_generation().
        had_invalidation_triggers = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='det_cache_facts_update' AND sql LIKE '%_det_batch_active%'"
        ).fetchone() is not None
        if not had_invalidation_triggers:
            for table in ("files", "facts", "dependencies", "scripts", "test_source_links"):
                for event in ("INSERT", "UPDATE", "DELETE"):
                    con.execute(f"DROP TRIGGER IF EXISTS det_cache_{table}_{event.lower()}")
        for table in ("files", "facts", "dependencies", "scripts", "test_source_links"):
            for event in ("INSERT", "UPDATE", "DELETE"):
                references = ("OLD", "NEW") if event == "UPDATE" else (("OLD",) if event == "DELETE" else ("NEW",))
                statements = []
                for reference in references:
                    guard = " WHERE OLD.root<>NEW.root" if event == "UPDATE" and reference == "OLD" else " WHERE 1"
                    statements.append(
                        "INSERT INTO project_state(root,manifest_hash,generation,updated_at) "
                        f"SELECT {reference}.root,'',1,CAST(strftime('%s','now') AS REAL){guard} "
                        "ON CONFLICT(root) DO UPDATE SET generation=project_state.generation+1,updated_at=excluded.updated_at; "
                        f"DELETE FROM query_cache WHERE root={reference}.root;"
                    )
                ref_root = "OLD.root" if event == "DELETE" else "NEW.root"
                con.execute(
                    f"CREATE TRIGGER IF NOT EXISTS det_cache_{table}_{event.lower()} AFTER {event} ON {table} "
                    f"WHEN (SELECT 1 FROM _det_batch_active WHERE root = {ref_root}) IS NULL "
                    "BEGIN " + " ".join(statements) + " END"
                )
        if not had_invalidation_triggers:
            con.execute("DELETE FROM query_cache")

    def record_test_source_links(self, root: str, links: list[tuple[str, str, float]]) -> None:
        if not links:
            return
        resolved = str(self._root(root))
        now = time.time()
        with self._lock, closing(self._connect()) as con:
            con.executemany(
                "INSERT OR REPLACE INTO test_source_links(root, source_path, test_path, confidence, updated_at) VALUES(?, ?, ?, ?, ?)",
                [(resolved, src.replace("\\", "/"), test.replace("\\", "/"), float(conf), now) for src, test, conf in links],
            )
            con.commit()

    def get_test_source_links(self, root: str, source_paths: list[str]) -> list[str]:
        if not source_paths:
            return []
        resolved = str(self._root(root))
        norm_sources = [p.replace("\\", "/").lstrip("./") for p in source_paths if p]
        if not norm_sources:
            return []
        matches: dict[str, None] = {}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            for batch in sqlite_batches(list(dict.fromkeys(norm_sources))):
                placeholders = ",".join("?" for _ in batch)
                basenames = [Path(path).name for path in batch]
                rows = con.execute(
                    f"SELECT DISTINCT test_path FROM test_source_links WHERE root=? AND (source_path IN ({placeholders}) OR source_path IN ({placeholders}))",
                    (resolved, *batch, *basenames),
                ).fetchall()
                for row in rows:
                    matches[str(row[0])] = None
        return sorted(matches)

    def precompute_test_mappings(self, root: str) -> int:
        """Scan repository files and precompute bidirectional source-to-test links into SQLite."""
        resolved = str(self._root(root))
        try:
            inv = self.repo_tools.file_inventory(resolved, include_hashes=False)
            files = [str(x["path"]).replace("\\", "/") for x in inv.get("files", [])]
        except Exception:
            return 0
        if not files:
            return 0

        test_files: list[str] = []
        source_by_stem: dict[str, list[str]] = defaultdict(list)
        for p in files:
            p_lower = p.lower()
            stem = Path(p).stem.lower()
            if any(marker in p_lower for marker in ("/test/", "/tests/", "_test.", ".test.", "_spec.", ".spec.", "test_")) or stem.endswith("tests") or stem.endswith("test"):
                test_files.append(p)
            else:
                source_by_stem[stem].append(p)

        links: list[tuple[str, str, float]] = []
        for t in test_files:
            t_stem = Path(t).stem.lower()
            clean_stem = re.sub(r"^(test_|tests_)|(_test|_tests|\.test|\.spec|tests|test)$", "", t_stem)
            if not clean_stem:
                continue
            candidates = source_by_stem.get(clean_stem, [])
            for c in candidates:
                links.append((c, t, 1.0))
                links.append((Path(c).name, t, 0.95))

        self.record_test_source_links(resolved, links)
        return len(links)

    def _init_db(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                if not quick_sanity_check(con):
                    raise sqlite3.DatabaseError("deterministic sanity check failed")
                self._schema(con)
                con.commit()
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            stamp = int(time.time())
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.db_path) + suffix)
                    if side.exists():
                        side.unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                self._schema(con)
                con.commit()

    @staticmethod
    def _root(root: str) -> str:
        return canonical_root(root)

    def _generation(self, root: str, con: sqlite3.Connection | None = None) -> int:
        root_s = self._root(root)
        owns = con is None
        db = con or self._connect()
        try:
            row = db.execute("SELECT generation FROM project_state WHERE root=?", (root_s,)).fetchone()
            return int(row[0]) if row else 0
        finally:
            if owns:
                db.close()

    def _bump_generation(self, con: sqlite3.Connection, root: str) -> int:
        root_s = self._root(root)
        now = time.time()
        con.execute(
            "INSERT INTO project_state(root,manifest_hash,generation,updated_at) VALUES(?,?,1,?) "
            "ON CONFLICT(root) DO UPDATE SET generation=project_state.generation+1,updated_at=excluded.updated_at",
            (root_s, "", now),
        )
        row = con.execute("SELECT generation FROM project_state WHERE root=?", (root_s,)).fetchone()
        generation = int(row[0]) if row else 1
        # Keep only the current generation; these rows are cheap to regenerate and
        # retaining stale generations only grows the DB.
        con.execute("DELETE FROM query_cache WHERE root=? AND generation<>?", (root_s, generation))
        con.execute("DELETE FROM unreferenced_symbols WHERE root=?", (root_s,))
        for key in [k for k in self._query_l1 if k[0] == root_s]:
            self._query_l1.pop(key, None)
        self._stats["query_invalidations"] += 1
        return generation

    def _query_cache_get(self, root: str, generation: int, key: str) -> dict[str, Any] | None:
        if not self._refresh_external_caches():
            return None
        now = time.time(); cache_key = (root, generation, key)
        with self._lock:
            row = self._query_l1.get(cache_key)
            if row and now - row[0] <= self._query_l1_ttl:
                self._stats["query_l1_hits"] += 1
                return json.loads(json_dumps(row[1]))
            if row:
                self._query_l1.pop(cache_key, None)
        try:
            with self._lock, closing(self._connect()) as con:
                dbrow = con.execute(
                    "SELECT result_json,updated_at FROM query_cache WHERE root=? AND generation=? AND query_key=?",
                    (root, generation, key),
                ).fetchone()
            if dbrow and now - float(dbrow[1]) <= self._query_l2_ttl:
                value = json.loads(str(dbrow[0]))
                self._stats["query_l2_hits"] += 1
                with self._lock:
                    self._query_l1[cache_key] = (now, value)
                    if len(self._query_l1) > self._query_l1_max:
                        oldest = min(self._query_l1.items(), key=lambda kv: kv[1][0])[0]
                        self._query_l1.pop(oldest, None)
                return json.loads(json_dumps(value))
        except (sqlite3.DatabaseError, json.JSONDecodeError):
            return None
        return None

    def _query_cache_put(self, root: str, generation: int, key: str, value: dict[str, Any]) -> None:
        now = time.time(); cache_key = (root, generation, key)
        copy = json.loads(json_dumps(value))
        with self._lock:
            self._query_l1[cache_key] = (now, copy)
            if len(self._query_l1) > self._query_l1_max:
                oldest = min(self._query_l1.items(), key=lambda kv: kv[1][0])[0]
                self._query_l1.pop(oldest, None)
        try:
            payload = json_dumps(value, ensure_ascii=False, separators=(",", ":"))
            with self._lock, closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if self._generation(root, con) != generation:
                    self._query_l1.pop(cache_key, None)
                    return
                con.execute(
                    "INSERT OR REPLACE INTO query_cache(root,generation,query_key,result_json,updated_at) VALUES(?,?,?,?,?)",
                    (root, generation, key, payload, now),
                )
                con.execute("DELETE FROM query_cache WHERE updated_at<?", (now - self._query_l2_ttl,))
                count = int(con.execute("SELECT COUNT(*) FROM query_cache WHERE root=? AND generation=?", (root, generation)).fetchone()[0])
                if count > self._query_l2_max_per_root:
                    con.execute(
                        "DELETE FROM query_cache WHERE rowid IN (SELECT rowid FROM query_cache WHERE root=? AND generation=? ORDER BY updated_at ASC LIMIT ?)",
                        (root, generation, count - self._query_l2_max_per_root),
                    )
                con.commit()
                # Cache-only commits do not change source generations. Acknowledge
                # ours so the next read can reuse L1; concurrent source commits are
                # still fenced by their transactional project generation.
                self._observed_data_version = self._cache_observer.version()
        except (sqlite3.DatabaseError, TypeError, ValueError):
            pass

    @staticmethod
    def _is_test(path: str) -> bool:
        low = "/" + path.replace("\\", "/").lower()
        name = Path(low).name
        return (
            any(marker in low for marker in TEST_MARKERS)
            or name.startswith("test_")
            or name.endswith((
                "test.py", "test.php", "spec.php", "test.ts", "spec.ts",
                "test.js", "spec.js", "test.tsx", "spec.tsx", "test.jsx", "spec.jsx",
                "test.mjs", "spec.mjs", "test.cjs", "spec.cjs",
            ))
        )

    @staticmethod
    def _language(path: str) -> str:
        low = path.replace("\\", "/").lower()
        if low.endswith(".blade.php"):
            return "blade"
        ext = Path(path).suffix.lower()
        return {
            ".py": "python", ".php": "php", ".ctp": "cakephp",
            ".js": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".mjs": "javascript", ".cjs": "javascript",
            ".mts": "typescript", ".cts": "typescript", ".vue": "vue", ".svelte": "svelte",
            ".html": "html", ".htm": "html",
            ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
            ".cs": "csharp", ".java": "java",
            ".go": "go", ".rs": "rust", ".json": "json", ".toml": "toml", ".xml": "xml",
            ".yaml": "yaml", ".yml": "yaml", ".sql": "sql", ".sh": "shell", ".ps1": "powershell",
            ".tf": "terraform", ".tfvars": "terraform", ".proto": "protobuf", ".ini": "config", ".cfg": "config",
            ".properties": "config", ".gradle": "gradle", ".kts": "kotlin",
        }.get(ext, "generic")

    def needs_update(self, root: str, path: str, content_hash: str) -> bool:
        root = self._root(root)
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT content_hash FROM files WHERE root=? AND path=?", (root, path)).fetchone()
            return row is None or str(row[0]) != str(content_hash)
        except sqlite3.DatabaseError:
            return True

    def prune(self, root: str, valid_paths: list[str]) -> int:
        root = self._root(root)
        valid = set(valid_paths)
        with self._lock, closing(self._connect()) as con:
            existing = [str(r[0]) for r in con.execute("SELECT path FROM files WHERE root=?", (root,)).fetchall()]
            stale = [path for path in existing if path not in valid]
            deleted = len(stale)
            if stale:
                con.execute("CREATE TEMP TABLE _deterministic_prune_paths(path TEXT PRIMARY KEY)")
                con.executemany(
                    "INSERT INTO _deterministic_prune_paths(path) VALUES(?)",
                    ((path,) for path in stale),
                )
                con.execute(
                    "DELETE FROM files WHERE root=? AND path IN (SELECT path FROM _deterministic_prune_paths)",
                    (root,),
                )
                con.execute(
                    "DELETE FROM facts WHERE root=? AND path IN (SELECT path FROM _deterministic_prune_paths)",
                    (root,),
                )
                has_fact_fts = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fact_fts'"
                ).fetchone()
                if has_fact_fts:
                    con.execute(
                        "DELETE FROM fact_fts WHERE root=? AND path IN (SELECT path FROM _deterministic_prune_paths)",
                        (root,),
                    )
            if deleted:
                self._bump_generation(con, root)
            con.commit()
        return deleted

    @staticmethod
    def _fact(kind: str, name: str, value: str, line: int = 0, **extra: Any) -> dict[str, Any]:
        return {"kind": kind, "name": name, "value": value, "line": int(line), "extra": extra}

    def _extract_python_ast(self, text: str) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return facts
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators = []
                for d in node.decorator_list:
                    try:
                        decorators.append(ast.unparse(d))
                    except (ValueError, TypeError, RecursionError) as unparse_exc:
                        logger.debug("Python decorator rendering skipped (%s)", type(unparse_exc).__name__)
                facts.append(self._fact("function", node.name, node.name, getattr(node, "lineno", 0), decorators=decorators, async_=isinstance(node, ast.AsyncFunctionDef)))
                if node.name in {"main", "cli", "run", "app", "create_app"}:
                    facts.append(self._fact("entrypoint", node.name, node.name, getattr(node, "lineno", 0)))
            elif isinstance(node, ast.ClassDef):
                facts.append(self._fact("class", node.name, node.name, getattr(node, "lineno", 0)))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    facts.append(self._fact("import", alias.name, alias.name, getattr(node, "lineno", 0)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                facts.append(self._fact("import", module, module, getattr(node, "lineno", 0)))
        return facts

    @staticmethod
    def _flatten_config(value: Any, prefix: str = "", out: list[str] | None = None, limit: int = 200) -> list[str]:
        return flatten_config_values(value, prefix, out, limit)

    def _extract_infra_facts(self, path: str, text: str) -> list[dict[str, Any]]:
        return extract_infra_facts(
            path,
            text,
            fact=self._fact,
            json_dumps=json_dumps,
            logger=logger,
        )

    def _extract_source_facts(self, path: str, text: str) -> list[dict[str, Any]]:
        return _extract_source_facts(
            path,
            text,
            language=self._language,
            fact=self._fact,
            flatten_config=self._flatten_config,
            extract_python_ast=self._extract_python_ast,
            extract_infra_facts=self._extract_infra_facts,
            is_test=self._is_test,
        )


    def _fact_blob_get(self, content_hash: str, language: str) -> list[dict[str, Any]] | None:
        key = f"{content_hash}:{__version__}:{language}"
        cached = self._fact_blob_l1.get(key)
        if cached is not None:
            self._stats["fact_blob_hits"] += 1
            return cached
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT facts_json FROM fact_blobs WHERE content_hash=? AND analyzer_version=? AND language=?",
                    (content_hash, __version__, language),
                ).fetchone()
            if row:
                value = json.loads(str(row[0]))
                if isinstance(value, list):
                    self._stats["fact_blob_hits"] += 1
                    self._fact_blob_l1.set(key, value)
                    return value
        except (sqlite3.DatabaseError, json.JSONDecodeError):
            pass
        self._stats["fact_blob_misses"] += 1
        return None

    def _fact_blob_put(self, content_hash: str, language: str, facts: list[dict[str, Any]]) -> None:
        key = f"{content_hash}:{__version__}:{language}"
        self._fact_blob_l1.set(key, facts)
        try:
            payload = json_dumps(facts, ensure_ascii=False, separators=(",", ":"))
            with self._lock, closing(self._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO fact_blobs(content_hash,analyzer_version,language,facts_json,updated_at) VALUES(?,?,?,?,?)",
                    (content_hash, __version__, language, payload, time.time()),
                )
                count = int(con.execute("SELECT COUNT(*) FROM fact_blobs").fetchone()[0])
                if count > self._fact_blob_max:
                    con.execute(
                        "DELETE FROM fact_blobs WHERE rowid IN (SELECT rowid FROM fact_blobs ORDER BY updated_at ASC LIMIT ?)",
                        (max(100, count - self._fact_blob_max),),
                    )
                con.commit()
        except (sqlite3.DatabaseError, TypeError, ValueError):
            pass

    def update_file(self, root: str, path: str, content_hash: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "deterministic engine disabled"}
        base = Path(root).expanduser().resolve()
        target = (base / path).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError:
            return {"success": False, "error": "invalid path"}
        root_s = str(base)
        if not target.is_file():
            with self._lock, closing(self._connect()) as con:
                existed = con.execute("SELECT 1 FROM files WHERE root=? AND path=?", (root_s, path)).fetchone() is not None
                con.execute("DELETE FROM files WHERE root=? AND path=?", (root_s, path))
                con.execute("DELETE FROM facts WHERE root=? AND path=?", (root_s, path))
                try:
                    con.execute("DELETE FROM fact_fts WHERE root=? AND path=?", (root_s, path))
                except sqlite3.OperationalError:
                    pass
                if existed:
                    self._bump_generation(con, root_s)
                con.commit()
            return {"success": True, "deleted": True}
        digest, lines = self.repo_tools._read_snapshot(target)
        content_hash = content_hash or digest
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT content_hash FROM files WHERE root=? AND path=?", (root_s, path)).fetchone()
            if row and str(row[0]) == str(content_hash):
                self._stats["file_cache_hits"] += 1
                return {"success": True, "cached": True, "path": path}
        language = self._language(path)
        facts = self._fact_blob_get(content_hash, language)
        if facts is None:
            text = "\n".join(lines)
            facts = self._extract_source_facts(path, text)
            self._fact_blob_put(content_hash, language, facts)
        now = time.time()
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM facts WHERE root=? AND path=?", (root_s, path))
            try:
                con.execute("DELETE FROM fact_fts WHERE root=? AND path=?", (root_s, path))
            except sqlite3.OperationalError:
                pass
            con.execute(
                "INSERT OR REPLACE INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
                (root_s, path, content_hash, language, int(self._is_test(path)), now),
            )
            con.executemany(
                "INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)",
                [(root_s, path, f["kind"], f["name"], f["value"], f["line"], json_dumps(f["extra"], ensure_ascii=False, separators=(",", ":"))) for f in facts],
            )
            try:
                con.executemany(
                    "INSERT INTO fact_fts(root,path,kind,name,value) VALUES(?,?,?,?,?)",
                    [(root_s, path, f["kind"], f["name"], f["value"]) for f in facts],
                )
            except sqlite3.OperationalError:
                pass
            self._bump_generation(con, root_s)
            con.commit()
        self._stats["files_parsed"] += 1
        self._stats["facts_extracted"] += len(facts)
        return {"success": True, "cached": False, "path": path, "facts": len(facts)}

    def update_files_batch(self, root: str, items: list[str] | list[tuple[str, str]]) -> dict[str, Any]:
        """Update many deterministic files with one blob read and one generation bump."""
        if not self.enabled:
            return {"success": False, "error": "deterministic engine disabled"}
        base = Path(root).expanduser().resolve()
        root_s = str(base)
        normalized: list[tuple[str, str | None]] = []
        for item in items:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                normalized.append((str(item[0]), str(item[1]) or None))
            else:
                normalized.append((str(item), None))
        if not normalized:
            return {"success": True, "updated": 0, "cached": 0, "failed": 0}
        with self._lock, closing(self._connect()) as con:
            existing = dict(con.execute("SELECT path,content_hash FROM files WHERE root=?", (root_s,)).fetchall())

        candidates: list[tuple[str, str, str, list[str]]] = []
        cached = failed = 0
        for path, supplied_hash in normalized:
            target = (base / path).resolve(strict=False)
            try:
                target.relative_to(base)
            except ValueError:
                failed += 1; continue
            if not target.is_file():
                failed += 1; continue
            language = self._language(path)
            if supplied_hash:
                if existing.get(path) == supplied_hash:
                    cached += 1
                    continue
                # Clean worktrees can reuse extracted facts by content identity
                # without reopening the same source bytes.
                if self._fact_blob_get(supplied_hash, language) is not None:
                    candidates.append((path, supplied_hash, language, []))
                    continue
            try:
                digest, lines = self.repo_tools._read_snapshot(target)
            except Exception:
                failed += 1; continue
            content_hash = supplied_hash or digest
            if existing.get(path) == content_hash:
                cached += 1; continue
            candidates.append((path, content_hash, language, lines))

        blob_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        if candidates:
            pairs = list(dict.fromkeys((h, lang) for _, h, lang, _ in candidates))
            try:
                with self._lock, closing(self._connect()) as con:
                    rows = []
                    con.execute("BEGIN")
                    for batch in sqlite_batches(pairs):
                        clauses = " OR ".join("(content_hash=? AND language=?)" for _ in batch)
                        params = [value for pair in batch for value in pair]
                        rows.extend(con.execute(
                            f"SELECT content_hash,language,facts_json FROM fact_blobs WHERE analyzer_version=? AND ({clauses})",
                            (__version__, *params),
                        ).fetchall())
                for row in rows:
                    value = json.loads(str(row[2]))
                    if isinstance(value, list):
                        blob_map[(str(row[0]), str(row[1]))] = value
            except Exception:
                blob_map = {}

        parsed_rows: list[tuple[str, str, str, list[dict[str, Any]]]] = []
        blob_rows: list[tuple[Any, ...]] = []
        now = time.time()
        for path, content_hash, language, lines in candidates:
            facts = blob_map.get((content_hash, language))
            if facts is None:
                facts = self._extract_source_facts(path, "\n".join(lines))
                blob_rows.append((content_hash, __version__, language, json_dumps(facts, ensure_ascii=False, separators=(",", ":")), now))
            else:
                self._stats["fact_blob_hits"] += 1
            parsed_rows.append((path, content_hash, language, facts))

        if parsed_rows:
            with self._lock, closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                if blob_rows:
                    con.executemany("INSERT OR REPLACE INTO fact_blobs(content_hash,analyzer_version,language,facts_json,updated_at) VALUES(?,?,?,?,?)", blob_rows)
                # FTS root/path filters scan its unindexed columns. Scope one
                # scan to this batch instead of scanning once per parsed file.
                fts_by_path = {}
                for path, _, _, facts in parsed_rows:
                    # Repeated paths originally delete/reinsert their FTS rows.
                    # Keep last-occurrence order for bounded BM25 tie candidates.
                    fts_by_path.pop(path, None)
                    fts_by_path[path] = facts
                con.execute("CREATE TEMP TABLE _deterministic_batch_paths(path TEXT PRIMARY KEY)")
                con.execute("INSERT OR REPLACE INTO _det_batch_active(root) VALUES(?)", (root_s,))
                con.executemany(
                    "INSERT INTO _deterministic_batch_paths(path) VALUES(?)",
                    ((path,) for path in fts_by_path),
                )
                try:
                    con.execute(
                        "DELETE FROM fact_fts WHERE root=? AND path IN (SELECT path FROM _deterministic_batch_paths)",
                        (root_s,),
                    )
                except sqlite3.OperationalError:
                    pass
                for path, content_hash, language, facts in parsed_rows:
                    con.execute("DELETE FROM facts WHERE root=? AND path=?", (root_s, path))
                    con.execute("INSERT OR REPLACE INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)", (root_s, path, content_hash, language, int(self._is_test(path)), now))
                    con.executemany("INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)", [(root_s, path, f["kind"], f["name"], f["value"], f["line"], json_dumps(f["extra"], ensure_ascii=False, separators=(",", ":"))) for f in facts])
                for path, facts in fts_by_path.items():
                    try:
                        con.executemany("INSERT INTO fact_fts(root,path,kind,name,value) VALUES(?,?,?,?,?)", [(root_s, path, f["kind"], f["name"], f["value"]) for f in facts])
                    except sqlite3.OperationalError:
                        pass
                con.execute("DELETE FROM _det_batch_active WHERE root=?", (root_s,))
                self._bump_generation(con, root_s)
                con.commit()
            self._stats["files_parsed"] += len(parsed_rows)
            self._stats["facts_extracted"] += sum(len(x[3]) for x in parsed_rows)
            self._stats["fact_blob_misses"] += len(blob_rows)
        return {"success": True, "updated": len(parsed_rows), "cached": cached, "failed": failed, "fact_blob_hits": len(parsed_rows)-len(blob_rows)}

    def build(self, root: str, paths: list[str] | None = None, limit: int = 0) -> dict[str, Any]:
        base = Path(root).expanduser().resolve()
        root_s = str(base)
        if paths is None:
            return {
                "success": False, "root": root_s, "updated": 0, "cached": 0,
                "failed": 0, "files": 0, "remaining": 0,
                "coverage_complete": False, "reason": "explicit_paths_required",
            }
        requested = list(dict.fromkeys(str(path) for path in paths if isinstance(path, str) and path))
        if not requested:
            return {
                "success": True, "root": root_s, "updated": 0, "cached": 0,
                "failed": 0, "files": 0, "remaining": 0, "coverage_complete": True,
            }
        if type(limit) is not int or limit < 0:
            return {
                "success": False, "root": root_s, "updated": 0, "cached": 0,
                "failed": len(requested), "files": 0, "remaining": len(requested),
                "coverage_complete": False, "reason": "invalid_limit",
            }
        configured_limit = max(
            1, int(self.config.get("preprocessing", {}).get("deterministic_files_per_step", 256))
        )
        batch_limit = min(limit, configured_limit) if limit else configured_limit
        candidates = requested[:batch_limit]
        updated = cached = failed = 0
        for path in candidates:
            try:
                result = self.update_file(str(base), path)
                cached += int(bool(result.get("cached")))
                updated += int(bool(result.get("success")) and not result.get("cached"))
                failed += int(result.get("success") is not True)
            except Exception:
                failed += 1
        remaining = max(0, len(requested) - len(candidates))
        coverage_complete = remaining == 0 and failed == 0
        return {
            "success": failed == 0, "root": root_s, "updated": updated, "cached": cached,
            "failed": failed, "files": len(candidates), "remaining": remaining,
            "coverage_complete": coverage_complete,
        }

    @staticmethod
    def _purpose(script: str) -> str:
        low = script.lower()
        if "test" in low:
            return "tests"
        if any(x in low for x in ("lint", "eslint", "ruff", "phpstan", "mypy", "check")):
            return "validation"
        if any(x in low for x in ("build", "compile")):
            return "build"
        if any(x in low for x in ("start", "serve", "dev", "run")):
            return "run"
        return "script"

    def _manifest_blob_get(self, content_hash: str, filename: str) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]] | None:
        key = f"{content_hash}:{__version__}:{filename.lower()}"
        cached = self._manifest_blob_l1.get(key)
        if cached is not None:
            self._stats["manifest_blob_hits"] += 1
            return cached
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT deps_json,scripts_json FROM manifest_blobs WHERE content_hash=? AND analyzer_version=? AND filename=?",
                    (content_hash, __version__, filename.lower()),
                ).fetchone()
            if row:
                deps = [tuple(x) for x in json.loads(str(row[0]))]
                scripts = [tuple(x) for x in json.loads(str(row[1]))]
                self._stats["manifest_blob_hits"] += 1
                res = (deps, scripts)
                self._manifest_blob_l1.set(key, res)
                return res
        except (sqlite3.DatabaseError, json.JSONDecodeError, TypeError):
            pass
        self._stats["manifest_blob_misses"] += 1
        return None

    def _manifest_blob_put(self, content_hash: str, filename: str, deps: list[tuple[str, str, str]], scripts: list[tuple[str, str, str]]) -> None:
        key = f"{content_hash}:{__version__}:{filename.lower()}"
        self._manifest_blob_l1.set(key, (deps, scripts))
        try:
            now = time.time()
            with self._lock, closing(self._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO manifest_blobs(content_hash,analyzer_version,filename,deps_json,scripts_json,updated_at) VALUES(?,?,?,?,?,?)",
                    (content_hash, __version__, filename.lower(), json_dumps(deps, ensure_ascii=False, separators=(",", ":")), json_dumps(scripts, ensure_ascii=False, separators=(",", ":")), now),
                )
                count = int(con.execute("SELECT COUNT(*) FROM manifest_blobs").fetchone()[0])
                if count > self._manifest_blob_max:
                    con.execute("DELETE FROM manifest_blobs WHERE rowid IN (SELECT rowid FROM manifest_blobs ORDER BY updated_at ASC LIMIT ?)", (max(100, count - self._manifest_blob_max),))
                con.commit()
        except (sqlite3.DatabaseError, TypeError, ValueError):
            pass

    def _parse_manifest(self, path: Path, rel: str, content_hash: str | None = None) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
        deps: list[tuple[str, str, str]] = []
        scripts: list[tuple[str, str, str]] = []
        name = path.name.lower()
        try:
            if path.stat().st_size > self.max_manifest_bytes:
                return deps, scripts
            if content_hash:
                cached = self._manifest_blob_get(content_hash, name)
                if cached is not None:
                    return cached
            _digest, snapshot_lines = self.repo_tools._read_snapshot(path)
            raw = "\n".join(snapshot_lines).encode("utf-8")
            deps, scripts = parse_manifest_dispatch(name, path.suffix.lower(), raw, self._purpose)
        except Exception:
            self._stats["manifest_parse_errors"] += 1
        if content_hash:
            self._manifest_blob_put(content_hash, name, deps, scripts)
        return deps, scripts

    def _manifest_files(self, root_s: str) -> list[Path]:
        """Enumerate manifests independently from RAG/source extension filters.

        Files such as go.mod and *.csproj must be discoverable even when they are
        intentionally excluded from semantic indexing. Git is preferred because it
        already applies ignore rules; the os.walk fallback keeps the same ignore/max
        limits as RepositoryTools.
        """
        base = Path(root_s)
        raw = self.repo_tools._git_files(base)
        if raw is None:
            raw = walk_manifest_paths(
                base,
                max_files=int(getattr(self.repo_tools, "max_files", 8000)),
                ignore_dirs=set(getattr(self.repo_tools, "ignore_dirs", set())),
            )
        return select_manifest_files(raw, max_bytes=self.max_manifest_bytes)

    def refresh_manifests(self, root: str) -> dict[str, Any]:
        root_s = self._root(root)
        base = Path(root_s)
        manifests = self._manifest_files(root_s)
        manifest_state = []
        manifest_hashes: dict[str, str] = {}
        for p in manifests:
            try:
                digest, _ = self.repo_tools._read_snapshot(p)
                rel = str(p.relative_to(base)).replace("\\", "/")
                manifest_state.append((rel, digest)); manifest_hashes[rel] = digest
            except Exception:
                continue
        mh = stable_hash(manifest_state)
        with self._lock, closing(self._connect()) as con:
            row = con.execute("SELECT manifest_hash FROM project_state WHERE root=?", (root_s,)).fetchone()
        if row and str(row[0]) == mh:
            self._stats["manifest_cache_hits"] += 1
            return {"success": True, "cached": True, "manifests": len(manifests)}

        # Parse/content-cache outside the project write transaction. This avoids a
        # second connection contending on our own SQLite writer and keeps the lock
        # window tiny for foreground deterministic queries.
        dep_rows = []
        script_rows = []
        for path in manifests:
            rel = str(path.relative_to(base)).replace("\\", "/")
            deps, scripts = self._parse_manifest(path, rel, manifest_hashes.get(rel))
            dep_rows.extend((root_s, rel, n, v, scope) for n, v, scope in deps)
            script_rows.extend((root_s, rel, n, command, purpose) for n, command, purpose in scripts)

        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            # Another thread may have completed the same refresh while we parsed.
            current = con.execute("SELECT manifest_hash FROM project_state WHERE root=?", (root_s,)).fetchone()
            if current and str(current[0]) == mh:
                con.rollback()
                self._stats["manifest_cache_hits"] += 1
                return {"success": True, "cached": True, "manifests": len(manifests)}
            con.execute("DELETE FROM dependencies WHERE root=?", (root_s,))
            con.execute("DELETE FROM scripts WHERE root=?", (root_s,))
            con.executemany("INSERT OR REPLACE INTO dependencies(root,source,name,version,scope) VALUES(?,?,?,?,?)", dep_rows)
            con.executemany("INSERT OR REPLACE INTO scripts(root,source,name,command,purpose) VALUES(?,?,?,?,?)", script_rows)
            con.execute(
                "INSERT INTO project_state(root,manifest_hash,generation,updated_at) VALUES(?,?,0,?) "
                "ON CONFLICT(root) DO UPDATE SET manifest_hash=excluded.manifest_hash,updated_at=excluded.updated_at",
                (root_s, mh, time.time()),
            )
            self._bump_generation(con, root_s)
            con.commit()
        self._stats["manifest_refreshes"] += 1
        return {"success": True, "cached": False, "manifests": len(manifests), "dependencies": len(dep_rows), "scripts": len(script_rows)}

    @staticmethod
    def _terms(query: str) -> list[str]:
        return [t.lower() for t in tokenize_query_terms(query, min_len=2, max_terms=16)]

    @staticmethod
    def classify_intent(query: str) -> dict[str, Any]:
        return classify_deterministic_intent(query)

    def _facts(self, root: str, *, kinds: list[str] | None = None, terms: list[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        root_s = self._root(root)
        limit = max(1, min(int(limit or self.max_query_results), 100))
        terms = [t.lower() for t in terms or [] if t]
        rows: list[dict[str, Any]] = []
        # FTS is the preferred deterministic candidate engine on large repos. It is
        # optional because some minimal SQLite builds omit FTS5; the indexed normal
        # table path below remains a correctness-equivalent fallback.
        if terms:
            expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms[:12])
            try:
                with self._lock, closing(self._connect()) as con:
                    clauses = ["root=?", "fact_fts MATCH ?"]
                    params: list[Any] = [root_s, expression]
                    if kinds:
                        clauses.append("kind IN (SELECT value FROM json_each(?))")
                        params.append(json_dumps(list(kinds)))
                    params.append(min(5000, max(300, limit * 30)))
                    fts_rows = con.execute(
                        "SELECT path,kind,name,value FROM fact_fts WHERE " + " AND ".join(clauses) + " ORDER BY bm25(fact_fts) LIMIT ?",
                        tuple(params),
                    ).fetchall()
                    # Recover exact line/extra metadata from the canonical facts table via batch query.
                    if fts_rows:
                        path_set = list({r["path"] for r in fts_rows})
                        fact_map: dict[tuple[str, str, str, str], dict[str, Any]] = {}
                        for chunk_start in range(0, len(path_set), 50):
                            chunk_paths = path_set[chunk_start:chunk_start + 50]
                            q_marks = ",".join("?" for _ in chunk_paths)
                            f_rows = con.execute(
                                f"SELECT path,kind,name,value,line,extra_json FROM facts WHERE root=? AND path IN ({q_marks})",
                                [root_s] + chunk_paths,
                            ).fetchall()
                            for r in f_rows:
                                fact_map[(r["path"], r["kind"], r["name"], r["value"])] = dict(r)
                        seen_keys: set[tuple[str, str, str, str]] = set()
                        for item in fts_rows:
                            k = (item["path"], item["kind"], item["name"], item["value"])
                            if k in fact_map and k not in seen_keys:
                                seen_keys.add(k)
                                rows.append(fact_map[k])
                self._stats["fact_fts_hits"] += 1
            except sqlite3.OperationalError:
                rows = []
                self._stats["fact_fts_fallbacks"] += 1
        if not rows:
            clauses = ["root=?"]
            params = [root_s]
            if kinds:
                clauses.append("kind IN (SELECT value FROM json_each(?))")
                params.append(json_dumps(list(kinds)))
            if terms:
                blob = "lower(path || ' ' || kind || ' ' || name || ' ' || value)"
                clauses.append("(" + " OR ".join(f"instr({blob}, ?) > 0" for _ in terms) + ")")
                params.extend(terms)
                candidate_limit = min(5000, max(300, limit * 30))
            else:
                candidate_limit = limit
            sql = "SELECT path,kind,name,value,line,extra_json FROM facts WHERE " + " AND ".join(clauses) + " ORDER BY path,line LIMIT ?"
            params.append(candidate_limit)
            with self._lock, closing(self._connect()) as con:
                rows = [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]
        scored = []
        for row in rows:
            blob_text = f"{row['path']} {row['kind']} {row['name']} {row['value']}".lower()
            score = sum(3 if t == str(row["name"]).lower() else 1 for t in terms if t in blob_text)
            if terms and not score:
                continue
            try:
                row["extra"] = json.loads(row.pop("extra_json") or "{}")
            except Exception:
                row["extra"] = {}; row.pop("extra_json", None)
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["path"], int(item[1]["line"])))
        return [row for _, row in scored[:limit]]

    def merge_overlapping_slices(
        self, root: str, slices: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Merge nearby source ranges and re-read exact text from the current snapshot."""
        return merge_overlapping_source_slices(self.repo_tools, root, slices)

    def _exact_evidence(self, root: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return collect_exact_evidence(self, root, rows)

    def query(self, root: str, query: str, limit: int | None = None) -> dict[str, Any]:
        root_s = self._root(root)
        if not self.enabled:
            return {"success": False, "error": "deterministic engine disabled", "confidence": 0.0}
        self._stats["queries"] += 1
        generation = self._generation(root_s)
        intent_info = self.classify_intent(query)
        intent = str(intent_info["intent"])
        terms = self._terms(query)
        # Deterministic resolution depends on intent + normalized terms, not prose
        # word order. Canonical keys make paraphrases such as "show auth routes" and
        # "routes for auth" reuse the same resolver result without semantic/LLM work.
        query_key = stable_hash({
            "v": __version__,
            "intent": intent,
            "terms": sorted(set(terms)),
            "limit": int(limit or self.max_query_results),
        })
        cached = self._query_cache_get(root_s, generation, query_key)
        if cached is not None:
            cached["query_cache_hit"] = True
            return cached
        content_terms = filter_intent_noise(intent, terms)
        result: dict[str, Any] = {"success": True, "root": root_s, "intent": intent, "terms": terms}
        rows: list[dict[str, Any]] = []
        graph: dict[str, Any] = {}

        if intent in {"symbols", "callers", "references", "tests", "implementation", "general"}:
            try:
                graph = self.code_index.query(root_s, query, limit or 24)
            except Exception:
                graph = {"success": False, "confidence": 0.0}
            if intent == "callers" and graph.get("symbols") and callable(getattr(self.code_index, "find_callers", None)):
                query_folded = query.casefold()
                direct_symbols = [
                    item for item in graph["symbols"]
                    if re.search(rf"(?<!\w){re.escape(str(item.get('name') or '').casefold())}(?!\w)", query_folded)
                    if item.get("name")
                ]
                target = (direct_symbols or graph["symbols"])[0]
                caller_result = self.code_index.find_callers(root_s, str(target["name"]), limit or 24)
                graph = {
                    **graph,
                    "caller_symbol": str(target["name"]),
                    "callers": caller_result.get("callers", []),
                    "callers_coverage": caller_result.get("coverage", {}),
                    "callers_success": bool(caller_result.get("success")),
                }
            result["code_index"] = {k: graph.get(k) for k in ("symbols", "references", "edges", "confidence") if k in graph}
            if intent == "callers" and "callers" in graph:
                result["code_index"].update({
                    key: graph[key]
                    for key in ("caller_symbol", "callers", "callers_coverage", "callers_success")
                })

        kind_map = {
            "routes": ["route"], "tests": ["test_file"], "syntax": ["syntax_error"], "config": ["env", "config", "config_key"],
            "entrypoints": ["entrypoint", "entrypoint_file"], "infrastructure": ["container_base", "container_image", "service", "port", "healthcheck", "ci_job", "ci_action", "ci_command", "terraform_resource", "terraform_module", "terraform_provider", "proto_service", "proto_rpc", "proto_message", "k8s_kind", "k8s_resource"], "security": ["security"],
            "concurrency": ["concurrency"], "database": ["database", "db_table"], "todos": ["todo"],
        }
        if intent in kind_map:
            rows = self._facts(root_s, kinds=kind_map[intent], terms=content_terms, limit=limit)
            result["facts"] = rows
        elif intent == "architecture":
            rows = self._facts(root_s, kinds=["entrypoint", "entrypoint_file", "route", "database", "config", "service", "port", "ci_job", "terraform_resource", "proto_service"], terms=[], limit=limit or 40)
            result["facts"] = rows
        elif intent == "dependencies":
            max_rows = max(1, int(limit or self.max_query_results))
            clauses = ["root=?"]; params: list[Any] = [root_s]
            if content_terms:
                blob = "lower(source || ' ' || name || ' ' || scope)"
                clauses.append("(" + " OR ".join(f"instr({blob}, ?) > 0" for _ in content_terms) + ")"); params.extend(content_terms)
            params.append(max_rows)
            with self._lock, closing(self._connect()) as con:
                deps = [dict(r) for r in con.execute("SELECT source,name,version,scope FROM dependencies WHERE " + " AND ".join(clauses) + " ORDER BY name LIMIT ?", tuple(params)).fetchall()]
            result["dependencies"] = deps
        elif intent == "commands":
            max_rows = max(1, int(limit or self.max_query_results))
            clauses = ["root=?"]; params = [root_s]
            if content_terms:
                blob = "lower(source || ' ' || name || ' ' || command || ' ' || purpose)"
                clauses.append("(" + " OR ".join(f"instr({blob}, ?) > 0" for _ in content_terms) + ")"); params.extend(content_terms)
            params.append(max_rows)
            with self._lock, closing(self._connect()) as con:
                scripts = [dict(r) for r in con.execute("SELECT source,name,command,purpose FROM scripts WHERE " + " AND ".join(clauses) + " ORDER BY purpose,name LIMIT ?", tuple(params)).fetchall()]
            result["scripts"] = scripts

        if intent == "tests" and content_terms:
            # Deterministic symbol/reference -> test mapping. Prefer indexed usages,
            # then filename/path proximity. No source scan or LLM is required.
            scored_map: dict[str, int] = defaultdict(int)
            for group, weight in ((graph.get("symbols", []), 5), (graph.get("references", []), 4), (graph.get("edges", []), 2)):
                for item in group or []:
                    path = str(item.get("path", ""))
                    if path and self._is_test(path):
                        scored_map[path] += weight
            with self._lock, closing(self._connect()) as con:
                test_paths = [str(r[0]) for r in con.execute("SELECT path FROM files WHERE root=? AND is_test=1 ORDER BY path LIMIT 1000", (root_s,)).fetchall()]
            for path in test_paths:
                low = path.lower(); stem = Path(low).stem
                scored_map[path] += sum(3 if t in stem else 1 for t in content_terms if t in low)
            result["test_candidates"] = [p for p, score in sorted(scored_map.items(), key=lambda x: (-x[1], x[0])) if score > 0][:16]

        evidence_rows = rows
        if not evidence_rows and graph:
            evidence_rows = []
            for group in (graph.get("symbols", []), graph.get("references", []), graph.get("edges", [])):
                for item in group:
                    if item.get("path") and item.get("line"):
                        evidence_rows.append({"path": item["path"], "line": item["line"]})
        result["evidence"] = self._exact_evidence(root_s, evidence_rows)

        count = len(rows) + len(result.get("dependencies", [])) + len(result.get("scripts", []))
        graph_conf = float(graph.get("confidence", 0.0) or 0.0) if isinstance(graph, dict) else 0.0
        base = float(intent_info.get("confidence", 0.5))
        if intent in {"dependencies", "commands"}:
            confidence = 0.99 if count else 0.72
        elif intent in kind_map or intent == "architecture":
            confidence = min(0.99, base + min(0.05, count * 0.01)) if count else min(base, 0.7)
            if intent == "tests" and result.get("test_candidates"):
                confidence = max(confidence, min(0.99, 0.92 + 0.01 * len(result["test_candidates"])))
        elif graph:
            confidence = max(base * 0.75, graph_conf)
        else:
            confidence = base * 0.7
        requires_synthesis = intent in {"implementation", "general", "architecture", "security", "concurrency", "database"}
        direct = confidence >= self.direct_confidence and not requires_synthesis
        result.update({
            "confidence": round(confidence, 4), "direct_answer": bool(direct),
            "requires_synthesis": bool(requires_synthesis), "deterministic": True,
        })
        self._stats["direct_answers"] += int(direct)
        result["generation"] = generation
        self._query_cache_put(root_s, generation, query_key, result)
        return result

    def compress_text(self, text: str, target_tokens: int = 650) -> dict[str, Any]:
        """Cheap deterministic compression for logs/repetitive diagnostics.

        It only claims a high confidence when selection rules are strong; callers
        should fall back to a local model for narrative/general prose.
        """
        return compress_diagnostic_text(text, target_tokens)

    def lexical_projection(self, root: str, path: str, max_chars: int = 12000) -> str | None:
        """Return a compact deterministic FTS representation for declarative files.

        Large lockfiles/configs should not be copied verbatim into the lexical DB when
        their useful semantics are already represented by exact parsers. Returning
        None means source text should remain the lexical representation.
        """
        if self.semantic_needed(root, path):
            return None
        root_s = self._root(root)
        lines = [f"PATH {path}"]
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT kind,name,value,line FROM facts WHERE root=? AND path=? ORDER BY kind,line LIMIT 400",
                (root_s, path),
            ).fetchall()
            deps = con.execute(
                "SELECT name,version,scope FROM dependencies WHERE root=? AND source=? ORDER BY name LIMIT 400",
                (root_s, path),
            ).fetchall()
            scripts = con.execute(
                "SELECT name,command,purpose FROM scripts WHERE root=? AND source=? ORDER BY name LIMIT 120",
                (root_s, path),
            ).fetchall()
        for row in rows:
            lines.append(f"FACT {row['kind']} {row['name']} {row['value']} line={row['line']}")
        for row in deps:
            lines.append(f"DEPENDENCY {row['name']} {row['version']} scope={row['scope']}")
        for row in scripts:
            lines.append(f"SCRIPT {row['name']} purpose={row['purpose']} command={row['command']}")
        return "\n".join(lines)[:max_chars]

    def optimize(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                con.execute("PRAGMA optimize")
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.DatabaseError:
            pass

    def get_centrality_ranks(self, root: str) -> dict[str, float]:
        """Compute normalized in-degree centrality score [0.0, 1.0] for source files."""
        root_s = str(root)
        with closing(self._connect()) as con:
            files = [
                str(r[0])
                for r in con.execute(
                    "SELECT path FROM files WHERE root=? AND is_test=0", (root_s,)
                ).fetchall()
            ]
            if not files:
                return {}
            import_rows = con.execute(
                "SELECT path, name, value FROM facts WHERE root=? AND kind='import'", (root_s,)
            ).fetchall()

        in_degrees: dict[str, int] = {f: 0 for f in files}
        stem_to_paths: dict[str, list[str]] = {}
        for f in files:
            stem = PurePosixPath(f).stem.lower()
            stem_to_paths.setdefault(stem, []).append(f)

        STD_MODULES = {
            "os", "sys", "re", "json", "time", "math", "typing", "pathlib", "logging",
            "collections", "io", "subprocess", "threading", "datetime", "functools",
            "itertools", "unittest", "pytest", "asyncio", "http", "socket", "urllib",
            "copy", "shutil", "tempfile", "traceback", "gc", "stat", "uuid", "hashlib",
            "base64", "contextlib", "abc", "react", "express", "lodash", "axios", "fs",
            "path", "events", "util", "crypto", "stream", "buffer",
        }
        seen_edges: set[tuple[str, str]] = set()
        for row in import_rows:
            importing_path = str(row[0])
            name = str(row[1] or row[2] or "").lower().replace("\\", "/")
            parts = name.split(".")
            for part in parts:
                if part in STD_MODULES:
                    continue
                for candidate in stem_to_paths.get(part, []):
                    edge = (importing_path, candidate)
                    if candidate != importing_path and edge not in seen_edges:
                        seen_edges.add(edge)
                        in_degrees[candidate] = in_degrees.get(candidate, 0) + 1

        max_deg = max(in_degrees.values()) if in_degrees else 0
        if max_deg <= 0:
            return {f: 0.0 for f in files}
        return {f: round(deg / max_deg, 4) for f, deg in in_degrees.items()}

    def semantic_needed(self, root: str, path: str) -> bool:
        """Return whether semantic RAG is worth indexing this path.

        Declarative files that are already losslessly represented by deterministic
        parsers are intentionally excluded from background embeddings. Exact source,
        manifest facts and FTS remain available, so this is a latency/CPU optimization
        rather than a correctness dependency. Source code always remains semantic.
        """
        rel = str(path).replace("\\", "/")
        name = Path(rel).name.lower()
        suffix = Path(rel).suffix.lower()
        lower = rel.lower()
        known = {
            "package.json", "package-lock.json", "pnpm-lock.yaml", "deno.json", "deno.jsonc", "composer.json", "composer.lock",
            "pyproject.toml", "poetry.lock", "uv.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum", "go.work",
            "pom.xml", "build.gradle", "build.gradle.kts", "libs.versions.toml", "pipfile", "gemfile", "gemfile.lock",
            "yarn.lock", "packages.lock.json", "global.json", "directory.packages.props", "directory.build.props", "directory.build.targets",
            "makefile", "gnumakefile", "justfile",
            "dockerfile", "containerfile", "docker-compose.yml", "docker-compose.yaml",
            "compose.yml", "compose.yaml", ".gitlab-ci.yml", ".gitlab-ci.yaml",
            "azure-pipelines.yml", "azure-pipelines.yaml",
        }
        data_suffixes = {
            ".json", ".jsonc", ".geojson", ".yaml", ".yml", ".xml", ".csv", ".tsv",
            ".toml", ".ini", ".cfg", ".properties", ".proto", ".graphql", ".gql",
            ".svg", ".map", ".meta", ".asset", ".prefab", ".mat", ".unity",
            ".csproj", ".fsproj", ".vbproj", ".sln", ".lock", ".sum", ".env",
            ".tf", ".tfvars",
        }
        if suffix in data_suffixes or name in known or (name.startswith("requirements") and name.endswith((".txt", ".in"))):
            return False
        # Configuration templates, samples, and env files
        if name.startswith(".env") or name.endswith((".example", ".sample", ".template", ".defaults")):
            return False
        # Minified code and bundles (dense, low semantic value, huge CPU drain)
        if name.endswith((".min.js", ".min.mjs", ".min.css", ".bundle.js", ".bundle.css", ".chunk.js", ".chunk.css")):
            return False
        # Legal and license boilerplates
        if name in {"license", "license.txt", "license.md", "licence", "licence.txt", "licence.md", "copying", "notice", "notice.txt", "patents"} or name.startswith(("license.", "licence.")):
            return False
        # Changelogs and release notes
        if name in {"changelog", "changelog.md", "changelog.txt", "changes", "changes.md", "history", "history.md", "releasenotes", "releasenotes.md"}:
            return False
        # Test snapshots and raw logs
        if suffix in {".snap", ".snapshot", ".log", ".patch", ".diff"}:
            return False
        # Test fixture directories, mock data, and test snapshots
        parts = set(Path(lower).parts)
        if parts & {"fixtures", "__fixtures__", "testdata", "snapshots", "__snapshots__", "mocks", "__mocks__"}:
            return False
        if "/.github/workflows/" in "/" + lower or "/artifacts/" in "/" + lower or "/candidates/" in "/" + lower:
            return False
        return True


    def file_card(self, root: str, path: str) -> dict[str, Any]:
        """Build a reusable semantic-ish card using only parsed deterministic facts."""
        root_s = self._root(root)
        with self._lock, closing(self._connect()) as con:
            rows = [dict(r) for r in con.execute(
                "SELECT kind,name,value,line,extra_json FROM facts WHERE root=? AND path=? ORDER BY line,kind", (root_s, path)
            ).fetchall()]
            file_row = con.execute("SELECT language,is_test FROM files WHERE root=? AND path=?", (root_s, path)).fetchone()
        kinds: dict[str, list[str]] = defaultdict(list)
        for r in rows:
            value = str(r.get("name") or r.get("value") or "")
            if value and value not in kinds[str(r.get("kind"))]:
                kinds[str(r.get("kind"))].append(value)
        language = str(file_row["language"]) if file_row else self._language(path)
        is_test = bool(file_row["is_test"]) if file_row else self._is_test(path)
        symbols = (kinds.get("class", []) + kinds.get("function", []))[:24]
        deps = kinds.get("import", [])[:24]
        for group in ("container_base", "container_image", "ci_action", "terraform_provider"):
            for item in kinds.get(group, []):
                if item not in deps and len(deps) < 24:
                    deps.append(item)
        ci = {}
        if self.code_index is not None and hasattr(self.code_index, "file_summary"):
            try:
                ci = self.code_index.file_summary(root_s, path, 80)
            except Exception:
                ci = {}
        return build_file_card(path, language, is_test, kinds, symbols, deps, ci)

    def module_card(self, root: str, module: str, file_cards: list[dict[str, Any]]) -> dict[str, Any]:
        """Synthesize a factual module card without an LLM.

        The input cards are already content-addressed. This reducer intentionally
        performs set/structure aggregation only; it does not infer behavioral claims.
        """
        paths = [str(x.get("path", "")) for x in file_cards if x.get("path")]
        # Exact parser facts can add route/entrypoint/test coordinates without prose inference.
        rows = []
        if paths:
            with self._lock, closing(self._connect()) as con:
                rows = []
                con.execute("BEGIN")
                for batch in sqlite_batches(sorted(set(paths))):
                    placeholders = ",".join("?" for _ in batch)
                    rows.extend(con.execute(
                        f"SELECT path,kind,name,value,line FROM facts WHERE root=? AND path IN ({placeholders}) "
                        "AND kind IN ('entrypoint','entrypoint_file','route','test_file') ORDER BY path,line LIMIT ?",
                        (self._root(root), *batch, 120 - len(rows)),
                    ).fetchall())
                    if len(rows) >= 120:
                        break
        return build_module_card_summary(module, file_cards, paths, rows)

    def project_card(self, root: str, profile: dict[str, Any] | None = None, repo_map: dict[str, Any] | None = None,
                     modules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Build a project navigation card entirely from deterministic state."""
        root_s = self._root(root)
        profile = profile or {}
        repo_map = repo_map or {}
        modules = modules or []

        entry = self.query(root_s, "entrypoint startup bootstrap main", limit=30)
        config = self.query(root_s, "configuration environment settings", limit=35)
        security = self.query(root_s, "security authentication authorization token", limit=30)
        concurrency = self.query(root_s, "concurrency async threads locks queues", limit=30)
        database = self.query(root_s, "database sql persistence", limit=30)
        infrastructure = self.query(root_s, "docker compose terraform deployment ci workflow ports protobuf", limit=40)
        commands = self.query(root_s, "test lint build commands", limit=30)
        syntax = self.query(root_s, "syntax parse error", limit=20)
        return build_project_card_summary(
            profile, repo_map, modules, entry, config, security, concurrency,
            database, infrastructure, commands, syntax,
        )

    _extract_py_diff_defs = staticmethod(extract_py_diff_defs)
    _extract_ts_diff_defs = staticmethod(extract_ts_diff_defs)
    _extract_cs_diff_defs = staticmethod(extract_cs_diff_defs)
    _extract_go_diff_defs = staticmethod(extract_go_diff_defs)
    _extract_rust_diff_defs = staticmethod(extract_rust_diff_defs)

    def _detect_breaking_changes(self, file_path: str, deleted_lines: list[str], added_lines: list[str]) -> list[dict[str, Any]]:
        if self._is_test(file_path):
            return []
        lang = self._language(file_path)
        if lang == "python":
            old_defs = self._extract_py_diff_defs(deleted_lines)
            new_defs = self._extract_py_diff_defs(added_lines)
        elif lang in ("typescript", "javascript"):
            old_defs = self._extract_ts_diff_defs(deleted_lines)
            new_defs = self._extract_ts_diff_defs(added_lines)
        elif lang in ("csharp", "java"):
            old_defs = self._extract_cs_diff_defs(deleted_lines)
            new_defs = self._extract_cs_diff_defs(added_lines)
        elif lang == "go":
            old_defs = self._extract_go_diff_defs(deleted_lines)
            new_defs = self._extract_go_diff_defs(added_lines)
        elif lang == "rust":
            old_defs = self._extract_rust_diff_defs(deleted_lines)
            new_defs = self._extract_rust_diff_defs(added_lines)
        else:
            return []

        return compare_api_definitions(file_path, old_defs, new_defs)

    def diff_facts(self, diff: str) -> dict[str, Any]:
        """Parse a unified diff into factual risk/validation metadata without an LLM."""
        parsed_diff = parse_unified_diff(diff)
        files = parsed_diff.files
        added = parsed_diff.additions
        deleted = parsed_diff.deletions
        hunks = parsed_diff.hunks
        added_lines = parsed_diff.added_lines
        file_diff_lines = parsed_diff.file_diff_lines

        breaking_changes: list[dict[str, Any]] = []
        for file_path, lines_dict in file_diff_lines.items():
            bcs = self._detect_breaking_changes(file_path, lines_dict["deleted"], lines_dict["added"])
            breaking_changes.extend(bcs)
            if len(breaking_changes) >= 50:
                breaking_changes = breaking_changes[:50]
                break

        test_files = [p for p in files if self._is_test(p)]
        manifests = [p for p in files if Path(p).name.lower() in {"package.json","composer.json","pyproject.toml","cargo.toml","go.mod","pom.xml"} or Path(p).suffix.lower() in {".csproj",".fsproj",".vbproj"}]
        signals: Counter[str] = Counter()
        signal_patterns = {
            "security": SECURITY_RE, "database": SQL_RE, "concurrency": CONCURRENCY_RE,
            "shell-exec": _DIFF_SHELL_I,
            "dynamic-eval": _DIFF_EVAL_I,
            "secret-like": _DIFF_SECRET_PASSWORD_I,
        }
        for _path, text in added_lines:
            for name, pattern in signal_patterns.items():
                if pattern.search(text):
                    signals[name] += 1
        if breaking_changes:
            signals["breaking-change"] = len(breaking_changes)
        docs_only = bool(files) and all(Path(p).suffix.lower() in {".md", ".rst", ".txt", ".adoc"} for p in files)
        tests_only = bool(files) and len(test_files) == len(files)
        score = min(100, len(files) * 3 + hunks * 2 + len(manifests) * 12 + signals.get("security",0) * 4 + signals.get("database",0) * 3 + signals.get("concurrency",0) * 4 + signals.get("shell-exec",0) * 8 + signals.get("dynamic-eval",0) * 10)
        if docs_only or tests_only:
            score = max(0, score - 12)
        if breaking_changes:
            score = min(100, max(50, score + len(breaking_changes) * 15))
            level = "high"
        else:
            level = "high" if score >= 45 else "medium" if score >= 18 else "low"
        return {
            "deterministic": True, "files": files, "file_count": len(files), "hunks": hunks,
            "additions": added, "deletions": deleted, "test_files": test_files, "manifest_files": manifests,
            "docs_only": docs_only, "tests_only": tests_only, "risk_signals": dict(signals),
            "breaking_changes": breaking_changes,
            "risk_score": score, "risk_level": level,
        }

    def call_graph_diff(self, root: str | Path, diff: str | None = None) -> dict[str, Any]:
        """Analyze breaking function/class signature changes against all call sites in the repository."""
        return analyze_call_graph_diff(root, diff, self._detect_breaking_changes)

    def render_answer(self, result: dict[str, Any], max_items: int = 16) -> str:
        """Render a terse deterministic answer without invoking any model."""
        return render_deterministic_answer(result, max_items)

    def related_paths(self, root: str, query: str, limit: int = 24) -> list[str]:
        result = self.query(root, query, limit=max(limit, 24))
        return rank_related_paths(result, limit)

    def context_pack(self, root: str, query: str, max_chars: int = 5200, max_raw_evidence: int = 5) -> dict[str, Any]:
        """Build a tiny deterministic context pack with only selected exact evidence.

        This is the preferred seed for tool-aware local models. It avoids RAG and
        embeddings when parsers already provide enough coverage.
        """
        max_chars = max(0, int(max_chars))
        result = self.query(root, query, limit=30)
        pieces = [
            "DETERMINISTIC FACTS:",
            self.render_answer(result, max_items=14),
        ]
        initial = "\n".join(pieces)
        truncated = len(initial) > max_chars
        pieces = [initial[:max_chars]]
        used = len(pieces[0])
        omitted_evidence: list[dict[str, Any]] = []
        raw_count = 0
        if self.evidence is not None:
            evidence_items = [
                (ev, str(ev.get("evidence_id", "")))
                for ev in result.get("evidence", [])
                if isinstance(ev, dict) and str(ev.get("evidence_id", ""))
            ] if max_raw_evidence > 0 else []
            get_many = getattr(self.evidence, "get_many", None)
            for offset in range(0, len(evidence_items), max(1, max_raw_evidence)):
                evidence_batch = evidence_items[offset:offset + max(1, max_raw_evidence)]
                if callable(get_many):
                    exact_items = get_many([eid for _ev, eid in evidence_batch], verify=True)
                else:
                    exact_items = [self.evidence.get(eid, verify=True) for _ev, eid in evidence_batch]
                for (_ev, eid), exact in zip(evidence_batch, exact_items):
                    if raw_count >= max_raw_evidence:
                        break
                    if not exact.get("success", True) or exact.get("stale"):
                        continue
                    text = str(exact.get("text", ""))
                    block = f"\n--- {eid} {exact.get('path')}:{exact.get('start_line')}-{exact.get('end_line')} ---\n{text}"
                    if used + 1 + len(block) > max_chars:
                        truncated = True
                        omitted_evidence.append({"evidence_id": eid, "path": exact.get("path"),
                                                 "start_line": exact.get("start_line"), "end_line": exact.get("end_line"),
                                                 "reason": "complete_source_exceeds_context_budget"})
                        continue
                    pieces.append(block); used += 1 + len(block); raw_count += 1
                if raw_count >= max_raw_evidence:
                    break

        if self.code_index is not None and used < max_chars:
            try:
                sym_text, symbol_truncated = build_symbol_context(
                    self.code_index, root, query, self._terms(query), max_chars, used
                )
            except Exception:
                sym_text, symbol_truncated = "", False
            if sym_text:
                pieces.append(sym_text)
            truncated = truncated or symbol_truncated

        context = "\n".join(pieces)
        return {
            "success": True, "root": self._root(root), "query": query, "context": context,
            "evidence": result.get("evidence", []), "deterministic": result,
            "estimated_tokens": max(1, len(context) // 4), "semantic_used": False,
            "scanned_files": 0, "context_budget_chars": max_chars,
            "truncated": truncated, "omitted_evidence": omitted_evidence,
        }

    def compact_context(self, root: str, query: str, max_chars: int = 2800) -> str:
        result = self.query(root, query, limit=20)
        compact = {
            "intent": result.get("intent"), "confidence": result.get("confidence"),
            "direct_answer": result.get("direct_answer"), "requires_synthesis": result.get("requires_synthesis"),
            "facts": result.get("facts", [])[:12], "dependencies": result.get("dependencies", [])[:16],
            "scripts": result.get("scripts", [])[:12], "test_candidates": result.get("test_candidates", [])[:10],
            "code_index": result.get("code_index", {}), "evidence": result.get("evidence", [])[:10],
        }
        text = json_dumps(compact, ensure_ascii=False, separators=(",", ":"))
        return text[:max_chars]

    def cross_project_graph(self, roots: list[str]) -> dict[str, Any]:
        """Build a dependency graph linking multiple projects by shared packages, routes, and types.

        Returns a graph with nodes (projects) and edges (shared dependencies/routes).
        This allows the agent to understand inter-project dependencies in a monorepo or
        multi-service architecture.
        """
        nodes: dict[str, dict[str, Any]] = {}
        # Map: package_name -> list of roots that use it
        package_map: dict[str, list[str]] = defaultdict(list)
        # Map: route -> list of roots that define/use it
        route_map: dict[str, list[str]] = defaultdict(list)

        unique_roots: list[tuple[str, str]] = []
        seen_roots: set[str] = set()
        for raw_root in roots:
            root = self._root(raw_root)
            if root in seen_roots:
                continue
            seen_roots.add(root)
            unique_roots.append((raw_root, root))

        for raw_root, root in unique_roots:
            node: dict[str, Any] = {"root": raw_root, "packages": [], "routes": [], "entrypoints": []}
            try:
                with self._lock, closing(self._connect()) as con:
                    # Collect all dependencies for this project
                    deps = con.execute(
                        "SELECT DISTINCT name FROM dependencies WHERE root=? ORDER BY name LIMIT 500",
                        (root,),
                    ).fetchall()
                    for d in deps:
                        pkg = str(d[0])
                        node["packages"].append(pkg)
                        package_map[pkg].append(raw_root)
                    # Collect routes
                    routes = con.execute(
                        "SELECT DISTINCT value FROM facts WHERE root=? AND kind='route' LIMIT 200",
                        (root,),
                    ).fetchall()
                    for r in routes:
                        rt = str(r[0])
                        node["routes"].append(rt)
                        route_map[rt].append(raw_root)
                    # Collect entrypoints
                    eps = con.execute(
                        "SELECT DISTINCT value FROM facts WHERE root=? AND kind='entrypoint_file' LIMIT 20",
                        (root,),
                    ).fetchall()
                    node["entrypoints"] = [str(e[0]) for e in eps]
            except (OSError, sqlite3.Error):
                pass
            nodes[raw_root] = node

        # Build edges from shared packages/routes
        edges: list[dict[str, Any]] = []
        seen_edges: set[frozenset[str]] = set()
        for pkg, pkg_roots in package_map.items():
            if len(pkg_roots) < 2:
                continue
            for i, r1 in enumerate(pkg_roots):
                for r2 in pkg_roots[i + 1:]:
                    key = frozenset({r1, r2})
                    if key not in seen_edges:
                        seen_edges.add(key)
                        edges.append({"from": r1, "to": r2, "type": "shared_package", "label": pkg})
                    else:
                        # Add to existing edge's labels
                        for e in edges:
                            if frozenset({e["from"], e["to"]}) == key:
                                e.setdefault("labels", [e["label"]]).append(pkg)
                                break

        seen_route_edges: set[frozenset[str]] = set()
        for route, route_roots in route_map.items():
            if len(route_roots) < 2:
                continue
            for i, r1 in enumerate(route_roots):
                for r2 in route_roots[i + 1:]:
                    key = frozenset({r1, r2})
                    if key not in seen_route_edges:
                        seen_route_edges.add(key)
                        edges.append({"from": r1, "to": r2, "type": "shared_route", "label": route})
                    else:
                        for edge in edges:
                            if edge.get("type") == "shared_route" and frozenset({edge["from"], edge["to"]}) == key:
                                edge.setdefault("labels", [edge["label"]]).append(route)
                                break

        return {
            "success": True,
            "nodes": list(nodes.values()),
            "edges": edges,
            "projects": len(nodes),
            "shared_packages": len([p for p, rs in package_map.items() if len(rs) >= 2]),
            "shared_routes": len([r for r, rs in route_map.items() if len(rs) >= 2]),
        }

    def cross_repo_symbol_find(self, roots: list[str], query: str, limit: int = 50) -> dict[str, Any]:
        """Find symbols matching query across multiple repository roots."""
        matches: list[dict[str, Any]] = []
        clean_query = query.strip()
        if not clean_query:
            return {"success": True, "symbols": [], "total": 0}

        for raw_root in roots:
            resolved = self._root(raw_root)
            if self.code_index is not None:
                try:
                    with self.code_index._lock, closing(self.code_index._connect()) as con:
                        rows = con.execute(
                            "SELECT name, kind, path, line, end_line FROM symbols "
                            "WHERE root=? AND (name LIKE ? OR lower(name)=lower(?)) LIMIT ?",
                            (resolved, f"%{clean_query}%", clean_query, limit),
                        ).fetchall()
                        for r in rows:
                            matches.append({
                                "repo": raw_root,
                                "name": str(r[0]),
                                "kind": str(r[1]),
                                "path": str(r[2]),
                                "line": int(r[3]),
                                "end_line": int(r[4] or r[3]),
                            })
                except (OSError, sqlite3.Error):
                    pass
            try:
                with self._lock, closing(self._connect()) as con:
                    f_rows = con.execute(
                        "SELECT name, kind, path, line, value FROM facts "
                        "WHERE root=? AND (name LIKE ? OR value LIKE ?) LIMIT ?",
                        (resolved, f"%{clean_query}%", f"%{clean_query}%", limit),
                    ).fetchall()
                    for fr in f_rows:
                        matches.append({
                            "repo": raw_root,
                            "name": str(fr[0] or fr[4]),
                            "kind": str(fr[1]),
                            "path": str(fr[2] or ""),
                            "line": int(fr[3] or 1),
                            "detail": str(fr[4] or ""),
                        })
            except (OSError, sqlite3.Error):
                pass

        seen: set[tuple[str, str, str, int]] = set()
        deduped: list[dict[str, Any]] = []
        for m in matches:
            k = (m["repo"], m["name"], m["path"], m.get("line", 0))
            if k not in seen:
                seen.add(k)
                deduped.append(m)

        return {
            "success": True,
            "query": clean_query,
            "total": len(deduped),
            "symbols": deduped[:limit],
            "repos": list({m["repo"] for m in deduped}),
        }

    def cross_project_impact(self, symbol: str, roots: list[str], origin_root: str | None = None) -> dict[str, Any]:
        """Compute blast radius and cross-boundary references of a symbol across multiple projects.

        Helps coordinate cross-repo refactors (e.g. backend API -> Unity client -> Web frontend).
        """
        clean_symbol = symbol.strip()
        if not clean_symbol or not roots:
            return {"success": False, "error": "symbol and roots are required"}

        declared_repos: list[str] = []
        references_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
        declarations: list[dict[str, Any]] = []

        for raw_root in roots:
            resolved = self._root(raw_root)
            if self.code_index is not None:
                try:
                    with self.code_index._lock, closing(self.code_index._connect()) as con:
                        syms = con.execute(
                            "SELECT name, kind, path, line FROM symbols WHERE root=? AND (name=? OR lower(name)=lower(?))",
                            (resolved, clean_symbol, clean_symbol),
                        ).fetchall()
                        for s in syms:
                            declarations.append({
                                "repo": raw_root, "name": str(s[0]), "kind": str(s[1]),
                                "path": str(s[2]), "line": int(s[3]),
                            })
                            if raw_root not in declared_repos:
                                declared_repos.append(raw_root)

                        refs = con.execute(
                            "SELECT DISTINCT path, line FROM refs WHERE root=? AND (name=? OR lower(name)=lower(?)) LIMIT 100",
                            (resolved, clean_symbol, clean_symbol),
                        ).fetchall()
                        for rf in refs:
                            references_by_repo[raw_root].append({
                                "path": str(rf[0]), "line": int(rf[1]),
                            })
                except Exception:
                    pass

            try:
                with self._lock, closing(self._connect()) as con:
                    f_rows = con.execute(
                        "SELECT kind, path, line, value FROM facts WHERE root=? AND (name=? OR value=?)",
                        (resolved, clean_symbol, clean_symbol),
                    ).fetchall()
                    for fr in f_rows:
                        declarations.append({
                            "repo": raw_root, "name": clean_symbol, "kind": str(fr[0]),
                            "path": str(fr[1] or ""), "line": int(fr[2] or 1), "value": str(fr[3]),
                        })
                        if raw_root not in declared_repos:
                            declared_repos.append(raw_root)
            except Exception:
                pass

        detected_origin = origin_root or (declared_repos[0] if declared_repos else roots[0])
        impacted_repos = [r for r in roots if r != detected_origin and references_by_repo.get(r)]
        total_cross_refs = sum(len(references_by_repo.get(r, [])) for r in impacted_repos)

        if not impacted_repos:
            risk = "low"
        elif len(impacted_repos) == 1 and total_cross_refs <= 3:
            risk = "medium"
        elif len(impacted_repos) >= 2 or total_cross_refs > 10:
            risk = "critical"
        else:
            risk = "high"

        suggested_order = [detected_origin] + impacted_repos

        return {
            "success": True,
            "symbol": clean_symbol,
            "origin_repo": detected_origin,
            "declared_in": declared_repos,
            "declarations": declarations,
            "impacted_repos": impacted_repos,
            "cross_boundary_references_count": total_cross_refs,
            "references_by_repo": {r: references_by_repo[r] for r in impacted_repos},
            "risk_score": risk,
            "suggested_order_of_edits": suggested_order,
        }

    def symbol_callgraph(self, root: str, symbol_name: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Compute caller/callee callgraph for a specific symbol or top symbols in the project."""
        resolved = self._root(root)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()

        def add_node(name: str, kind: str, path: str = "") -> None:
            if name not in seen_nodes:
                seen_nodes.add(name)
                nodes.append({"id": name, "label": name, "kind": kind, "path": path})

        if self.code_index is not None:
            try:
                with self.code_index._lock, closing(self.code_index._connect()) as con:
                    if symbol_name:
                        sym_rows = con.execute(
                            "SELECT name,kind,path,line,end_line FROM symbols WHERE root=? AND (name=? OR lower(name)=lower(?)) LIMIT ?",
                            (resolved, symbol_name, symbol_name, limit),
                        ).fetchall()
                    else:
                        sym_rows = con.execute(
                            "SELECT name,kind,path,line,end_line FROM symbols WHERE root=? AND kind IN ('function','method','class') LIMIT ?",
                            (resolved, limit),
                        ).fetchall()

                    for row in sym_rows:
                        name, kind, path, line, end_line = str(row[0]), str(row[1]), str(row[2]), int(row[3]), int(row[4] or row[3])
                        add_node(name, kind, path)

                        # Find callers: references outside this symbol's line range
                        caller_rows = con.execute(
                            "SELECT DISTINCT path, line FROM refs WHERE root=? AND name=? AND (path<>? OR line < ? OR line > ?) LIMIT 15",
                            (resolved, name, path, line, end_line),
                        ).fetchall()
                        for c in caller_rows:
                            cpath, cline = str(c[0]), int(c[1])
                            caller_id = f"{Path(cpath).stem}:{cline}"
                            add_node(caller_id, "caller_site", cpath)
                            edges.append({"from": caller_id, "to": name, "type": "calls"})

                        # Find callees: symbols referenced within this symbol's line range
                        callee_rows = con.execute(
                            "SELECT DISTINCT name FROM refs WHERE root=? AND path=? AND line >= ? AND line <= ? AND name<>? LIMIT 15",
                            (resolved, path, line, end_line, name),
                        ).fetchall()
                        for cl in callee_rows:
                            cl_name = str(cl[0])
                            add_node(cl_name, "callee_symbol", path)
                            edges.append({"from": name, "to": cl_name, "type": "calls"})
            except Exception as exc:
                return {"success": False, "error": str(exc), "nodes": [], "edges": []}

        return {
            "success": True,
            "root": resolved,
            "symbol": symbol_name,
            "nodes": nodes,
            "edges": edges,
        }

    def detect_dead_code(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Detect symbols (functions, methods, private classes) with zero incoming references."""
        resolved = self._root(root)
        dead: list[dict[str, Any]] = []

        EXCLUDED_NAMES = {
            "main", "init", "run", "setup", "teardown", "__init__",
            "Awake", "Start", "Update", "FixedUpdate", "LateUpdate", "OnEnable", "OnDisable", "OnDestroy",
            "OnTriggerEnter", "OnCollisionEnter", "OnGUI", "Reset",
        }

        if self.code_index is not None:
            try:
                with self.code_index._lock, closing(self.code_index._connect()) as con:
                    rows = con.execute(
                        """SELECT s.name, s.kind, s.path, s.line, s.container
                           FROM symbols s
                           WHERE s.root=?
                             AND s.kind IN ('function','method','class')
                             AND s.path NOT LIKE '%/test/%'
                             AND s.path NOT LIKE '%/tests/%'
                             AND s.path NOT LIKE '%_test.%'
                             AND s.path NOT LIKE '%.test.%'
                           ORDER BY s.path, s.line""",
                        (resolved,),
                    ).fetchall()

                    for row in rows:
                        name, kind, path, line, container = str(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4] or "")
                        if name in EXCLUDED_NAMES or name.startswith("test_") or name.startswith("On"):
                            continue
                        if Path(path).name.lower() in ("main.py", "app.py", "index.ts", "index.js", "program.cs"):
                            continue

                        ref_count = con.execute(
                            "SELECT COUNT(*) FROM refs WHERE root=? AND name=? AND (path<>? OR line<>?)",
                            (resolved, name, path, line),
                        ).fetchone()[0]

                        if int(ref_count) == 0:
                            dead.append({
                                "name": name,
                                "kind": kind,
                                "path": path,
                                "line": line,
                                "container": container,
                                "reason": "0 references found across repository",
                            })
                            if len(dead) >= limit:
                                break
            except Exception as exc:
                return {"success": False, "error": str(exc), "dead_symbols": []}

        if not dead and self.code_index is None:
            try:
                with self._lock, closing(self._connect()) as con:
                    rows = con.execute(
                        """SELECT name, kind, path, line
                           FROM facts
                           WHERE root=? AND kind IN ('function', 'class')
                             AND path NOT LIKE '%/test/%' AND path NOT LIKE '%/tests/%'
                             AND path NOT LIKE '%_test.%' AND path NOT LIKE '%.test.%'
                           ORDER BY path, line""",
                        (resolved,),
                    ).fetchall()
                    for r in rows:
                        s_name, s_kind, s_path, s_line = str(r[0]), str(r[1]), str(r[2]), int(r[3])
                        if s_name in EXCLUDED_NAMES or s_name.startswith("test_") or s_name.startswith("On"):
                            continue
                        if Path(s_path).name.lower() in ("main.py", "app.py", "index.ts", "index.js", "program.cs"):
                            continue
                        count = con.execute(
                            "SELECT COUNT(*) FROM facts WHERE root=? AND (name=? OR value=?) AND path<>?",
                            (resolved, s_name, s_name, s_path),
                        ).fetchone()[0]
                        if count == 0:
                            dead.append({
                                "name": s_name,
                                "kind": s_kind,
                                "path": s_path,
                                "line": s_line,
                                "container": "",
                                "reason": "0 references found in deterministic facts",
                            })
                            if len(dead) >= limit:
                                break
            except Exception:
                pass

        return {
            "success": True,
            "root": resolved,
            "dead_symbols_count": len(dead),
            "dead_symbols": dead,
        }

    def precompute_dead_code(self, root: str, limit: int = 500) -> dict[str, Any]:
        """Precompute unreferenced symbols across the repository and persist them."""
        resolved = self._root(root)
        dead_info = self.detect_dead_code(resolved, limit=limit)
        items = dead_info.get("dead_symbols", [])
        now = time.time()
        with self._lock, closing(self._connect()) as con:
            con.execute("DELETE FROM unreferenced_symbols WHERE root=?", (resolved,))
            if items:
                con.executemany(
                    """INSERT OR REPLACE INTO unreferenced_symbols(root, path, name, kind, line, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [(resolved, str(i["path"]), str(i["name"]), str(i["kind"]), int(i.get("line", 0)), now) for i in items],
                )
            con.commit()
        return {"success": True, "root": resolved, "count": len(items), "symbols": items}

    def get_unreferenced_symbols(self, root: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve precomputed unreferenced symbols instantly from cache."""
        resolved = self._root(root)
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                """SELECT path, name, kind, line, updated_at
                   FROM unreferenced_symbols
                   WHERE root=?
                   ORDER BY path, line
                   LIMIT ?""",
                (resolved, limit),
            ).fetchall()
        return [
            {
                "path": str(r[0]),
                "name": str(r[1]),
                "kind": str(r[2]),
                "line": int(r[3]),
                "updated_at": float(r[4]),
                "reason": "0 references found across repository (precomputed)",
            }
            for r in rows
        ]

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

    @staticmethod
    def _osv_ecosystem(source: str) -> str | None:
        path = source.lower().replace("\\", "/")
        if any(name in path for name in ("requirements", "pyproject.toml", "pipfile", "poetry.lock", "uv.lock")):
            return "PyPI"
        if any(name in path for name in ("package.json", "package-lock", "pnpm-lock", "yarn.lock")):
            return "npm"
        if "cargo" in path:
            return "crates.io"
        if "composer" in path:
            return "Packagist"
        if path.endswith((".csproj", ".fsproj", "packages.lock.json")):
            return "NuGet"
        if path.endswith(("go.mod", "go.sum")):
            return "Go"
        return None

    def _osv_audit(self, dependencies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
        queries: list[dict[str, Any]] = []
        mapped: list[dict[str, Any]] = []
        for dependency in dependencies:
            ecosystem = self._osv_ecosystem(str(dependency.get("manifest", "")))
            version = str(dependency.get("version", "")).strip()
            if ecosystem is None or not version or version == "*":
                continue
            queries.append({"package": {"name": str(dependency["package"]), "ecosystem": ecosystem}, "version": version})
            mapped.append(dependency)
        if not queries:
            return [], None
        cache_key = stable_hash({"app_version": __version__, "queries": queries})
        cached = self._osv_cache.get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("vulnerabilities"), list):
            return cached["vulnerabilities"], None
        cfg = self.config.get("dependency_audit", {})
        timeout = max(0.5, min(15.0, float(cfg.get("osv_timeout_seconds", 5.0))))
        osv_url = str(cfg.get("osv_api_url", "https://api.osv.dev/api/querybatch"))
        request = urllib.request.Request(
            osv_url,
            data=json_dumps({"queries": queries}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Local-AI-Hub/1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return [], f"OSV query failed: {type(exc).__name__}"
        results = payload.get("results", []) if isinstance(payload, dict) else []
        vulnerabilities: list[dict[str, Any]] = []
        for dependency, result in zip(mapped, results):
            if not isinstance(result, dict):
                continue
            for vulnerability in result.get("vulns", []):
                if not isinstance(vulnerability, dict):
                    continue
                database = vulnerability.get("database_specific", {})
                severity = str(database.get("severity", "UNKNOWN") if isinstance(database, dict) else "UNKNOWN").upper()
                advisory_id = str(vulnerability.get("id", "OSV"))
                summary = str(vulnerability.get("summary", "advisory available")).strip()
                vulnerabilities.append({
                    "package": dependency["package"], "installed_version": dependency["version"], "fixed_version": "",
                    "manifest_path": dependency["manifest"], "advisory": f"{advisory_id}: {summary}", "severity": severity,
                })
        self._osv_cache.set(cache_key, {"vulnerabilities": vulnerabilities})
        return vulnerabilities, None

    def audit_dependencies(self, root: str, remediate: bool = False) -> dict[str, Any]:
        """Audit project dependencies for known vulnerabilities and security advisories."""
        resolved = self._root(root)
        fallback_vulns: list[dict[str, Any]] = []
        deps_list: list[dict[str, Any]] = []

        try:
            with self._lock, closing(self._connect()) as con:
                rows = con.execute(
                    "SELECT DISTINCT name, version, source FROM dependencies WHERE root=?",
                    (resolved,),
                ).fetchall()
                for row in rows:
                    pkg, ver, manifest = str(row[0]), str(row[1] or ""), str(row[2] or "")
                    deps_list.append({"package": pkg, "version": ver, "manifest": manifest})
                    pkg_lower = pkg.lower()
                    if pkg_lower in self.KNOWN_CVE_SIGNATURES:
                        min_safe_ver, cve_desc = self.KNOWN_CVE_SIGNATURES[pkg_lower]
                        def _ver_tuple(v: str) -> tuple[int, ...]:
                            nums = re.findall(r"\d+", v)
                            return tuple(int(x) for x in nums) if nums else (0,)
                        if ver and ver != "*" and _ver_tuple(ver) < _ver_tuple(min_safe_ver):
                            fallback_vulns.append({
                                "package": pkg,
                                "installed_version": ver,
                                "fixed_version": min_safe_ver,
                                "manifest_path": manifest,
                                "advisory": cve_desc,
                                "severity": "HIGH" if "injection" in cve_desc.lower() or "leak" in cve_desc.lower() else "MEDIUM",
                            })
        except Exception as exc:
            return {"success": False, "error": str(exc), "vulnerabilities": []}

        cfg = self.config.get("dependency_audit", {})
        osv_enabled = bool(cfg.get("osv_enabled", True))
        osv_vulns, osv_error = self._osv_audit(deps_list) if osv_enabled else ([], "OSV disabled")
        osv_current = osv_enabled and osv_error is None
        vulns = osv_vulns if osv_current else fallback_vulns
        security_score = "A" if osv_current and not vulns else ("UNKNOWN" if not vulns else ("B" if len(vulns) <= 2 else "C"))

        remediations: list[dict[str, Any]] = []
        for v in vulns:
            pkg = v.get("package", "")
            fixed_ver = v.get("fixed_version") or "latest"
            manifest = v.get("manifest_path", "")
            if "pyproject" in manifest or "requirements" in manifest:
                cmd = f"pip install --upgrade '{pkg}>={fixed_ver}'"
            elif "package.json" in manifest:
                cmd = f"npm install '{pkg}@{fixed_ver}'"
            elif "composer" in manifest.lower():
                cmd = f"composer require '{pkg}:^{fixed_ver}'"
            elif "cargo" in manifest.lower():
                cmd = f"cargo update -p {pkg} --precise {fixed_ver}"
            else:
                cmd = f"upgrade {pkg} to >={fixed_ver}"
            rem_item = {"package": pkg, "recommended_version": fixed_ver, "fix_command": cmd}
            v["remediation"] = rem_item
            remediations.append(rem_item)

        res: dict[str, Any] = {
            "success": True,
            "root": resolved,
            "total_dependencies": len(deps_list),
            "vulnerability_count": len(vulns),
            "security_score": security_score,
            "audit_coverage": "osv_live" if osv_current else "limited_static_signatures",
            "advisory_data_current": osv_current,
            "advisory_error": osv_error,
            "vulnerabilities": vulns,
        }
        if remediate or remediations:
            res["remediations"] = remediations
        return res

    def refactor_impact(self, root: str, target_file: str, target_symbol: str | None = None) -> dict[str, Any]:
        """Compute the ripple effect and refactoring impact matrix across callers, dependents and tests."""
        resolved = self._root(root)
        target_path = target_file.replace("\\", "/").lstrip("./")
        
        impacted_files: set[str] = set()
        callers: list[dict[str, Any]] = []
        impacted_tests: list[str] = []
        symbols_to_check: list[str] = [target_symbol] if target_symbol else []

        def failure(error: str, *, index_available: bool) -> dict[str, Any]:
            return {
                "success": False,
                "error": error,
                "root": resolved,
                "target_file": target_path,
                "symbols_analyzed": symbols_to_check,
                "risk_level": "UNKNOWN",
                "impacted_files_count": 0,
                "impacted_files": [],
                "callers_count": 0,
                "callers": [],
                "impacted_tests": [],
                "recommendations": [],
                "index_available": index_available,
                "freshness": {"status": "not_checked"},
                "coverage": {
                    "complete": False,
                    "reason": "index_query_failed" if index_available else "index_unavailable",
                },
            }

        if self.code_index is None:
            return failure("code index unavailable", index_available=False)

        try:
            with self.code_index._lock, closing(self.code_index._connect()) as con:
                if not symbols_to_check:
                    sym_rows = con.execute(
                        "SELECT name FROM symbols WHERE root=? AND path=? AND kind IN ('class','function','method')",
                        (resolved, target_path),
                    ).fetchall()
                    symbols_to_check = [str(r[0]) for r in sym_rows]

                for sym in symbols_to_check:
                    symbol_name = sym.replace("\\", "/").rsplit("/", 1)[-1].rsplit("::", 1)[-1].rsplit(".", 1)[-1]
                    edge_rows = con.execute(
                        "SELECT src, dst, path, line, kind FROM edges "
                        "WHERE root=? AND (dst=? OR (kind='calls' AND dst_name=?))",
                        (resolved, sym, symbol_name),
                    ).fetchall()
                    for r in edge_rows:
                        caller_path = str(r[2])
                        impacted_files.add(caller_path)
                        callers.append({
                            "caller_symbol": str(r[0]),
                            "target_symbol": str(r[1]),
                            "path": caller_path,
                            "line": int(r[3]),
                            "kind": str(r[4]),
                        })
                        if "/test" in caller_path.lower() or "test_" in caller_path.lower() or ".test." in caller_path.lower():
                            impacted_tests.append(caller_path)

                    ref_rows = con.execute(
                        "SELECT path, line, kind FROM refs WHERE root=? AND name=? AND path<>?",
                        (resolved, sym, target_path),
                    ).fetchall()
                    for r in ref_rows:
                        rp = str(r[0])
                        impacted_files.add(rp)
                        if "/test" in rp.lower() or "test_" in rp.lower() or ".test." in rp.lower():
                            impacted_tests.append(rp)
        except Exception as exc:
            return failure(f"code index query failed: {exc}", index_available=True)

        ext_files = [f for f in impacted_files if f != target_path]
        if len(ext_files) == 0:
            observed_risk = "LOW"
        elif len(ext_files) <= 3:
            observed_risk = "MEDIUM"
        else:
            observed_risk = "HIGH"

        impacted_tests = list(dict.fromkeys(impacted_tests))
        recommendations = []
        if impacted_tests:
            recommendations.append(f"Run {len(impacted_tests)} impacted test suite(s): {', '.join(impacted_tests[:3])}")
        if ext_files:
            recommendations.append(f"Verify {len(callers)} call site(s) across {len(ext_files)} external file(s)")
        else:
            recommendations.append(
                "Index freshness is unverified; confirm callers and external dependencies before concluding impact is local."
            )

        return {
            "success": True,
            "root": resolved,
            "target_file": target_path,
            "symbols_analyzed": symbols_to_check,
            "risk_level": "UNKNOWN",
            "observed_risk_level": observed_risk,
            "impacted_files_count": len(ext_files),
            "impacted_files": sorted(ext_files),
            "callers_count": len(callers),
            "callers": callers[:30],
            "impacted_tests": impacted_tests,
            "recommendations": recommendations,
            "index_available": True,
            "freshness": {"status": "not_checked"},
            "coverage": {
                "complete": False,
                "reason": "index_freshness_not_checked",
                "returned_callers": min(len(callers), 30),
                "callers_truncated": len(callers) > 30,
            },
        }

    def resolve_imports(self, root: str, unknown_symbols: list[str], language: str = "auto") -> dict[str, Any]:
        """Resolve likely import statements for symbols already present in the code index.

        ``language=auto`` infers syntax from each declaration file, allowing one compact
        endpoint to work across mixed-language repositories without client-side guesses.
        """
        resolved = self._root(root)
        requested_lang = (language or "auto").strip().lower()
        aliases = {"cs": "csharp", "py": "python", "ts": "typescript", "js": "javascript", "php": "php"}
        requested_lang = aliases.get(requested_lang, requested_lang)
        supported = {"auto", "csharp", "python", "typescript", "javascript", "php"}
        if requested_lang not in supported:
            return {"success": False, "root": resolved, "language": requested_lang, "error": f"unsupported language: {requested_lang}"}

        from .import_statements import import_for, language_for_path

        if not isinstance(unknown_symbols, list) or len(unknown_symbols) > 64 or any(
            not isinstance(symbol, str) or len(symbol) > 512 or "\0" in symbol for symbol in unknown_symbols
        ):
            return {"success": False, "root": resolved, "error": "symbols must be at most 64 strings of at most 512 characters"}
        from .static_exports import named_export_status
        resolved_imports: list[dict[str, Any]] = []
        missing: list[str] = []
        rejected: list[dict[str, str]] = []
        snapshots: dict[str, tuple[str, str] | None] = {}
        snapshot_bytes = 0
        settings = None
        if self.code_index is not None:
            try:
                _api, context = self.code_index._project_config_context(resolved)
                settings = context.settings if context is not None else None
                for clean_sym in dict.fromkeys(symbol.strip() for symbol in unknown_symbols if symbol.strip()):
                    # Snapshot rows while holding the index lock, never source I/O or parsing.
                    with self.code_index._lock, closing(self.code_index._connect()) as con:
                        rows = con.execute(
                            "SELECT s.name,s.container,s.path,s.kind,s.access,f.content_hash FROM symbols s "
                            "JOIN files f ON f.root=s.root AND f.path=s.path "
                            "WHERE s.root=? AND s.name=? ORDER BY s.path,s.line LIMIT 17",
                            (resolved, clean_sym),
                        ).fetchall()
                    accepted = False
                    if len(rows) > 16:
                        rejected.append({"symbol": clean_sym, "path": "", "reason": "candidate_limit"})
                    for row in rows[:16]:
                        name, container, path, kind, access, indexed_hash = (
                            str(value or "") for value in row
                        )
                        lang = language_for_path(path)
                        if requested_lang != "auto" and language_for_path(path) != requested_lang:
                            continue
                        if path not in snapshots:
                            snapshots[path] = None
                            target = Path(resolved) / path
                            try:
                                target.resolve(strict=True).relative_to(Path(resolved))
                                if not self.repo_tools._project_file_allowed(Path(resolved), target, settings):
                                    raise ValueError("path not allowed")
                                size = target.stat().st_size
                                if snapshot_bytes + size > 4_000_000:
                                    rejected.append({"symbol": clean_sym, "path": path, "reason": "export_snapshot_budget"})
                                    continue
                                digest, lines = self.repo_tools._read_snapshot(target, force=True)
                                text = "\n".join(lines)
                                snapshot_bytes += len(text.encode("utf-8", errors="replace"))
                                snapshots[path] = (str(digest), text)
                            except (OSError, ValueError):
                                pass
                        snapshot = snapshots[path]
                        if snapshot is None:
                            valid, reason = False, "export_source_unavailable"
                        elif not indexed_hash or snapshot[0] != indexed_hash:
                            valid, reason = False, "stale_indexed_declaration"
                        else:
                            valid, reason = named_export_status(snapshot[1], lang, name,
                                                               container=container, kind=kind, access=access)
                        if not valid:
                            rejected.append({"symbol": clean_sym, "path": path, "reason": reason})
                            continue
                        statement = import_for(name, container, path, lang, snapshot[1])
                        if not statement:
                            rejected.append({"symbol": clean_sym, "path": path, "reason": "import_syntax_unavailable"})
                            continue
                        resolved_imports.append({
                            "symbol": name, "container": container, "path": path, "kind": kind,
                            "language": lang, "import_statement": statement,
                            "export_validation": reason, "content_hash": snapshot[0],
                        })
                        accepted = True
                        break
                    if not accepted:
                        missing.append(clean_sym)
            except Exception as exc:
                return {"success": False, "root": resolved, "language": requested_lang, "error": str(exc), "error_type": type(exc).__name__}
        else:
            missing = [symbol.strip() for symbol in unknown_symbols if symbol.strip()]

        statements = [x["import_statement"] for x in resolved_imports if x.get("import_statement")]
        return {
            "success": True,
            "root": resolved,
            "language": requested_lang,
            "resolved_count": len(resolved_imports),
            "resolved_imports": resolved_imports,
            "import_statements": list(dict.fromkeys(statements)),
            "unresolved_symbols": missing,
            "rejected_candidates": rejected[:128],
            "rejected_candidates_truncated": len(rejected) > 128,
            "validation": "static_named_exports_of_current_indexed_candidates",
            "complete": not missing and len(rejected) <= 128,
        }

    def git_status(self, root: str) -> dict[str, Any]:
        """Return git branch, modified files and repository status without shell popups."""
        import subprocess, shutil
        from .process_utils import hidden_run_kwargs
        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"
        try:
            res = subprocess.run(
                [git_exe, "-C", resolved, "status", "--porcelain=v1", "-b"],
                capture_output=True, text=True, timeout=3.0, check=False,
                encoding="utf-8", errors="replace",
                **hidden_run_kwargs(),
            )
            if res.returncode != 0:
                return {
                    "success": True,
                    "is_git": False,
                    "root": resolved,
                    "branch": "none",
                    "modified_count": 0,
                    "modified": [],
                    "staged_count": 0,
                    "staged": [],
                    "untracked_count": 0,
                    "untracked": [],
                    "conflict_count": 0,
                    "conflicts": [],
                }
            
            lines = res.stdout.splitlines()
            branch = "unknown"
            modified: list[str] = []
            staged: list[str] = []
            untracked: list[str] = []
            conflicts: list[str] = []
            
            if lines and lines[0].startswith("## "):
                branch = lines[0][3:].split("...")[0].strip()
                lines = lines[1:]
                
            for ln in lines:
                if len(ln) < 3:
                    continue
                x, y, path = ln[0], ln[1], ln[3:].strip()
                if (x, y) in {
                    ("D", "D"), ("A", "U"), ("U", "D"),
                    ("U", "A"), ("D", "U"), ("A", "A"), ("U", "U"),
                }:
                    conflicts.append(path)
                if x in ("M", "A", "D", "R"):
                    staged.append(path)
                if y in ("M", "D"):
                    modified.append(path)
                if x == "?" and y == "?":
                    untracked.append(path)
                    
            return {
                "success": True,
                "is_git": True,
                "root": resolved,
                "branch": branch,
                "modified_count": len(modified),
                "modified": modified,
                "staged_count": len(staged),
                "staged": staged,
                "untracked_count": len(untracked),
                "untracked": untracked,
                "conflict_count": len(conflicts),
                "conflicts": conflicts,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "is_git": False}

    def git_diff(
        self, root: str, path: str | None = None, staged: bool = False,
        max_lines: int = 1000, *, rev1: str | None = None, rev2: str | None = None,
    ) -> dict[str, Any]:
        """Return structured, bounded Git diff, optionally between pinned revisions."""
        resolved = self._root(root)
        if isinstance(max_lines, bool) or not isinstance(max_lines, int) or not 1 <= max_lines <= 10000:
            return {"success": False, "error": "max_lines must be between 1 and 10000", "root": resolved}
        try:
            result = self.repo_tools.git_diff(
                resolved, base="", staged=staged, max_tokens=min(24000, max(1024, max_lines * 32)),
                rev1=rev1, rev2=rev2, path=path,
            )
            if not result.get("success"):
                return result
            raw_diff = str(result.get("diff", ""))
            lines = raw_diff.splitlines()
            files_changed: list[dict[str, Any]] = []
            cur_file: dict[str, Any] | None = None
            additions = 0
            deletions = 0

            for line in lines[:max_lines]:
                if line.startswith("diff --git "):
                    if cur_file:
                        files_changed.append(cur_file)
                    parts = line.split(" ")
                    file_b = parts[-1].removeprefix("b/") if len(parts) >= 4 else ""
                    cur_file = {"file": file_b, "additions": 0, "deletions": 0, "hunks": []}
                elif cur_file is not None:
                    if line.startswith("@@"):
                        cur_file["hunks"].append(line)
                    elif line.startswith("+") and not line.startswith("+++"):
                        cur_file["additions"] += 1
                        additions += 1
                    elif line.startswith("-") and not line.startswith("---"):
                        cur_file["deletions"] += 1
                        deletions += 1

            if cur_file:
                files_changed.append(cur_file)

            truncated = bool(result.get("truncated")) or len(lines) > max_lines
            return {
                "success": True,
                "root": resolved,
                "staged": staged,
                "comparison": result.get("comparison"),
                "rev1": result.get("rev1"), "rev2": result.get("rev2"),
                "resolved_rev1": result.get("resolved_rev1"), "resolved_rev2": result.get("resolved_rev2"),
                "diff_sha256": result.get("diff_sha256"),
                "changed_files": result.get("changed_files", []),
                "paths_complete": bool(result.get("paths_complete")),
                "stats_complete": not truncated,
                "files_count": len(files_changed),
                "total_additions": additions,
                "total_deletions": deletions,
                "stats": {
                    "insertions": additions,
                    "deletions": deletions,
                    "files_changed": len(files_changed),
                },
                "files": files_changed,
                "diff": "\n".join(lines[:max_lines]),
                "raw_diff": "\n".join(lines[:max_lines]),
                "truncated": truncated,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "root": resolved}

    def git_history_search(
        self,
        root: str,
        query: str,
        max_commits: int = 20,
        *,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        return search_git_history(
            root,
            query,
            max_commits,
            author=author,
            since=since,
            until=until,
            path=path,
            root_resolver=self._root,
            git_executable_fn=shutil.which,
            run_hidden_fn=run_hidden,
            clean_git_env_fn=clean_git_env,
        )

    def find_hotspots(
        self,
        root: str,
        days: int = 30,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Rank Git-touched files by bounded recency-weighted churn and complexity."""
        return _find_hotspots(
            root,
            days,
            limit,
            root_resolver=self._root,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
            git_insight_stream_limit=_GIT_INSIGHT_STREAM_LIMIT,
            run_hidden_fn=run_hidden,
            clean_git_env_fn=clean_git_env,
        )

    def generate_tests_for_diff(
        self,
        root: str,
        diff: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Generate targeted regression test skeleton from git diff changes."""
        resolved = self._root(root)
        if not diff:
            diff_res = self.git_diff(resolved, path=path)
            diff = diff_res.get("diff", "")

        if not diff or not diff.strip():
            return {
                "success": False,
                "error": "No diff content provided or found in repository",
                "root": resolved,
            }

        modified_targets: list[dict[str, Any]] = []
        cur_file = ""
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                cur_file = line[6:].strip()
            elif line.startswith("@@") and cur_file:
                hunk_match = re.search(r"@@.*?@@\s*(.*)", line)
                if hunk_match:
                    signature = hunk_match.group(1).strip()
                    fn_match = re.search(r"(?:def|function|class|async\s+def|func)\s+([A-Za-z0-9_]+)", signature)
                    symbol = fn_match.group(1) if fn_match else ""
                    if symbol:
                        modified_targets.append({
                            "file": cur_file,
                            "signature": signature,
                            "symbol": symbol,
                        })
            elif (line.startswith("+") or line.startswith("-")) and cur_file and not (line.startswith("+++") or line.startswith("---")):
                fn_match = re.search(r"(?:def|function|class|async\s+def|func)\s+([A-Za-z0-9_]+)", line)
                if fn_match:
                    symbol = fn_match.group(1)
                    modified_targets.append({
                        "file": cur_file,
                        "signature": line.lstrip("+- ").strip(),
                        "symbol": symbol,
                    })

        test_cases: list[str] = ['import pytest\n']
        seen_symbols = set()
        for item in modified_targets:
            sym = item.get("symbol")
            if not sym or sym in seen_symbols:
                continue
            seen_symbols.add(sym)
            pending_reason = (
                "Replace generated placeholder with behavior-based assertions "
                f"for {sym}."
            )
            test_cases.append(f"""
@pytest.mark.skip(reason={json.dumps(pending_reason, separators=(',', ':'))})
def test_{sym}_regression_nominal():
    \"\"\"Verify nominal expected output for modified {sym}.\"\"\"
    raise NotImplementedError({json.dumps(pending_reason, separators=(',', ':'))})

@pytest.mark.skip(reason={json.dumps(pending_reason, separators=(',', ':'))})
def test_{sym}_regression_edge_cases():
    \"\"\"Verify boundaries and error handling for modified {sym}.\"\"\"
    raise NotImplementedError({json.dumps(pending_reason, separators=(',', ':'))})
""")

        test_code = "\n".join(test_cases)
        target_mods = list({str(t.get("file", "")).replace(".py", "").replace("/", ".").replace("\\", ".") for t in modified_targets if t.get("file")})
        return {
            "success": True,
            "root": resolved,
            "targets_count": len(seen_symbols),
            "modified_targets": modified_targets,
            "target_modules": target_mods,
            "generated_test_code": test_code,
            "test_skeleton": test_code,
            "complete": False,
            "requires_review": bool(seen_symbols),
        }

    def cross_repo_contract(
        self,
        backend_root: str,
        frontend_root: str,
    ) -> dict[str, Any]:
        """Validate API contract alignment between backend routes and frontend API callers."""
        b_root = canonical_root(backend_root)
        f_root = canonical_root(frontend_root)

        backend_spec = self.extract_api_spec(b_root)
        backend_endpoints = backend_spec.get("endpoints", [])
        backend_routes: dict[tuple[str, str], dict[str, Any]] = {}
        for ep in backend_endpoints:
            m = str(ep.get("method", "GET")).upper()
            p = str(ep.get("path", "")).strip()
            norm_p = re.sub(r"\{[a-zA-Z0-9_]+\}", ":param", p)
            norm_p = re.sub(r"<[a-zA-Z0-9_:]+>", ":param", norm_p)
            backend_routes[(m, norm_p)] = ep

        frontend_calls: list[dict[str, Any]] = []
        f_path = Path(f_root)
        if f_path.is_dir():
            for p in f_path.rglob("*"):
                if p.suffix in (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".py") and not any(d in p.parts for d in ("node_modules", ".git", "dist", "build")):
                    try:
                        content = p.read_text(encoding="utf-8", errors="replace")
                        rel = str(p.relative_to(f_path)).replace("\\", "/")
                        for line_no, line in enumerate(content.splitlines(), 1):
                            m_call = re.findall(r"(?:fetch|axios\.(get|post|put|delete|patch)|apiFetch|get|post)\s*\(\s*['\"`](/api/[^'\"`]+)['\"`]", line)
                            for item in m_call:
                                if isinstance(item, tuple):
                                    http_m = (item[0] or "GET").upper()
                                    path_c = item[1]
                                else:
                                    http_m = "GET"
                                    path_c = item
                                norm_c = re.sub(r"/\$\{[^}]+\}", "/:param", path_c)
                                norm_c = re.sub(r"/[0-9]+", "/:param", norm_c)
                                frontend_calls.append({
                                    "method": http_m,
                                    "path": path_c,
                                    "normalized_path": norm_c,
                                    "file": rel,
                                    "line": line_no,
                                })
                    except Exception:
                        pass

        matched_routes: list[dict[str, Any]] = []
        missing_backend_routes: list[dict[str, Any]] = []
        for call in frontend_calls:
            k = (call["method"], call["normalized_path"])
            found = backend_routes.get(k)
            if not found:
                alt_methods = [b_ep for (b_m, b_p), b_ep in backend_routes.items() if b_p == call["normalized_path"]]
                if alt_methods:
                    missing_backend_routes.append({**call, "issue": f"Method mismatch: frontend uses {call['method']} but backend expects {alt_methods[0].get('method')}"})
                else:
                    missing_backend_routes.append({**call, "issue": "Endpoint not defined on backend"})
            else:
                matched_routes.append({**call, "backend_handler": found.get("handler")})

        unused_backend: list[dict[str, Any]] = []
        f_norm_paths = {c["normalized_path"] for c in frontend_calls}
        for (b_m, b_p), ep in backend_routes.items():
            if b_p not in f_norm_paths:
                unused_backend.append(ep)

        return {
            "success": True,
            "backend_root": b_root,
            "frontend_root": f_root,
            "backend_endpoints_count": len(backend_routes),
            "frontend_calls_count": len(frontend_calls),
            "matched_contracts_count": len(matched_routes),
            "violations_count": len(missing_backend_routes),
            "violations": missing_backend_routes,
            "unmatched_frontend_calls": [v["path"] for v in missing_backend_routes],
            "matched": matched_routes,
            "matched_endpoints": [m["path"] for m in matched_routes],
            "unused_backend_endpoints": unused_backend,
            "uncalled_backend_endpoints": [u.get("path") for u in unused_backend],
        }

    def synthesize_commit(
        self,
        root: str,
        message_hint: str = "",
        *,
        task_id: str = "",
        tasks: list[dict[str, Any]] | None = None,
        receipts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Analyze local git diff and synthesize a clean Conventional Commit message."""
        import subprocess, shutil
        from .process_utils import hidden_run_kwargs

        task_list = list(tasks or [])
        receipt_list = list(receipts or [])
        primary_goal = ""
        for t in task_list:
            g = str(t.get("goal") or (t.get("contract", {}) if isinstance(t.get("contract"), dict) else {}).get("goal", "")).strip()
            if g:
                primary_goal = g
                break

        effective_hint = message_hint or primary_goal

        def _format_body_sections(file_lines: list[str]) -> tuple[str, str]:
            sections: list[str] = []
            if file_lines:
                sections.append("\n".join(file_lines))
            if task_list:
                t_lines = ["Tasks:"]
                for t in task_list[:5]:
                    tid = t.get("task_id", "")
                    g = str(t.get("goal") or (t.get("contract", {}) if isinstance(t.get("contract"), dict) else {}).get("goal", "")).strip()
                    if tid and g:
                        t_lines.append(f"- [{tid}]: {g}")
                    elif g:
                        t_lines.append(f"- {g}")
                if len(t_lines) > 1:
                    sections.append("\n".join(t_lines))
            if receipt_list:
                r_lines = ["Verified Criteria:"]
                for r in receipt_list[:10]:
                    crit = r.get("criterion", "")
                    ev_id = r.get("evidence_id", "")
                    suffix = f" (evidence: {ev_id})" if ev_id else ""
                    r_lines.append(f"- [x] {crit}{suffix}")
                if len(r_lines) > 1:
                    sections.append("\n".join(r_lines))
            body_text = "\n\n".join(sections)
            return body_text, sections[0] if sections else ""

        st = self.git_status(root)
        if not st.get("is_git"):
            header = f"feat(core): {effective_hint or 'update repository files'}"
            body_text, _ = _format_body_sections(["- modified repository files"])
            return {
                "success": True,
                "branch": "main (non-git)",
                "primary_scope": "core",
                "type": "feat",
                "header": header,
                "body": body_text,
                "commit_message": f"{header}\n\n{body_text}",
                "stat_summary": "Non-git directory",
                "tasks": task_list,
                "receipts": receipt_list,
            }

        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"
        try:
            diff_res = subprocess.run(
                [git_exe, "-C", resolved, "diff", "HEAD", "--stat"],
                capture_output=True, text=True, timeout=3.0, check=False,
                encoding="utf-8", errors="replace",
                **hidden_run_kwargs(),
            )
            stat_summary = diff_res.stdout.strip()
        except Exception:
            stat_summary = ""

        mod_files = st.get("modified", []) + st.get("staged", [])
        if not mod_files:
            return {"success": True, "commit_message": "chore: no modified files detected", "summary": "Working tree clean"}

        # Determine primary scope
        scopes = []
        for f in mod_files:
            parts = f.replace("\\", "/").split("/")
            if len(parts) > 1:
                scopes.append(parts[0] if parts[0] not in ("src", "lib") else parts[1] if len(parts) > 2 else parts[0])
            else:
                scopes.append(parts[0])
        primary_scope = max(set(scopes), key=scopes.count) if scopes else "core"

        # Determine conventional type
        any_test = any("test" in f.lower() for f in mod_files)
        any_doc = any(f.endswith(".md") or "doc" in f.lower() for f in mod_files)
        any_src = any(f.endswith((".py", ".cs", ".ts", ".js", ".go", ".rs")) for f in mod_files)

        c_type = "feat" if any_src else "test" if any_test else "docs" if any_doc else "refactor"
        if effective_hint:
            header = f"{c_type}({primary_scope}): {effective_hint}"
        else:
            header = f"{c_type}({primary_scope}): update {len(mod_files)} component(s)"

        body_lines = [f"- update `{f}`" for f in mod_files[:10]]
        if len(mod_files) > 10:
            body_lines.append(f"- and {len(mod_files) - 10} other file(s)")

        body_text, _ = _format_body_sections(body_lines)
        full_message = f"{header}\n\n{body_text}"
        return {
            "success": True,
            "branch": st.get("branch"),
            "primary_scope": primary_scope,
            "type": c_type,
            "header": header,
            "body": body_text,
            "commit_message": full_message,
            "stat_summary": stat_summary,
            "tasks": task_list,
            "receipts": receipt_list,
        }


    @staticmethod
    def _detect_test_framework(resolved_root: Path) -> tuple[str, str, bool, list[str]]:
        return detect_test_framework(resolved_root)

    def test_matrix(self, root: str) -> dict[str, Any]:
        """Discover test frameworks, test files, and test mappings in the repository."""
        resolved_root = Path(self._root(root))
        root_str = str(resolved_root)
        test_files: list[dict[str, Any]] = []
        framework, run_all_cmd, incomplete, warnings = self._detect_test_framework(resolved_root)

        # Only current filesystem entries can back a matrix row. Keep directory
        # enumeration bounded; the durable index is deliberately not a source
        # of truth for test targets because it can lag deletions and renames.
        max_depth = 25
        max_files = 2000
        max_targets = 40
        max_file_bytes = min(int(getattr(self.repo_tools, "max_file_bytes", 1_000_000)), 256_000)
        max_total_bytes = 2_000_000
        deadline = time.monotonic() + 5.0
        target_paths: list[tuple[str, Path, os.stat_result]] = []
        enumerated = 0
        try:
            for candidate, snapshot_stat in self.repo_tools._iter_files_with_stat(
                root_str, max_depth=max_depth, max_files=max_files,
            ):
                if time.monotonic() >= deadline:
                    incomplete = True
                    warnings.append("test_file_enumeration_deadline_exceeded")
                    break
                enumerated += 1
                try:
                    rel = candidate.relative_to(resolved_root).as_posix()
                    if not is_test_matrix_source(rel):
                        continue
                    lst = candidate.lstat()
                    if stat.S_ISLNK(lst.st_mode) or (getattr(lst, "st_file_attributes", 0) & 0x400):
                        incomplete = True
                        warnings.append("test_file_reparse_point_skipped")
                        continue
                    current_stat = candidate.stat()
                    candidate.resolve(strict=True).relative_to(resolved_root)
                    if not stat.S_ISREG(current_stat.st_mode) or current_stat.st_size > max_file_bytes:
                        incomplete = True
                        warnings.append("test_file_invalid_or_too_large_skipped")
                        continue
                    if (current_stat.st_dev, current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (
                        snapshot_stat.st_dev, snapshot_stat.st_ino, snapshot_stat.st_size, snapshot_stat.st_mtime_ns,
                    ):
                        incomplete = True
                        warnings.append("test_file_changed_during_enumeration")
                        continue
                    target_paths.append((rel, candidate, current_stat))
                except (OSError, ValueError):
                    incomplete = True
                    warnings.append("test_file_unavailable_or_outside_root")
            if enumerated >= max_files:
                incomplete = True
                warnings.append("test_file_enumeration_limit_reached")
        except Exception:
            incomplete = True
            warnings.append("test_file_enumeration_failed")

        selected, selection_incomplete, selection_warnings = select_test_matrix_targets(
            target_paths,
            max_targets=max_targets,
            max_total_bytes=max_total_bytes,
        )
        incomplete = incomplete or selection_incomplete
        warnings.extend(selection_warnings)

        def _extract_file_info(item: tuple[str, Path, os.stat_result]) -> dict[str, Any] | None:
            rel, f, before = item
            suffix = f.suffix.lower()
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError("test matrix read deadline exceeded")
                # Match the read ceiling to the prevalidated size. The snapshot
                # helper reads max_bytes + 1 for growth detection, so aggregate
                # selection reserves that lookahead byte before dispatch.
                digest, lines = self.repo_tools._read_snapshot(f, stat=before, max_bytes=int(before.st_size))
                txt = "\n".join(lines)
                lstat_after = f.lstat()
                after = f.stat()
                if stat.S_ISLNK(lstat_after.st_mode) or (getattr(lstat_after, "st_file_attributes", 0) & 0x400):
                    raise OSError("file became a reparse point during bounded read")
                f.resolve(strict=True).relative_to(resolved_root)
                if not stat.S_ISREG(after.st_mode) or (
                    before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                    raise OSError("file changed during bounded read")
                cases, cases_scan_complete = extract_test_case_names(
                    txt, suffix, should_continue=lambda: time.monotonic() < deadline,
                )
            except Exception as exc:
                return {"_omitted": type(exc).__name__}

            # Keep arguments structured. Display strings include only simple
            # shell tokens; paths needing quoting remain available as argv.
            run_argv, run_file_cmd = build_test_file_command(f, rel, framework)
            return build_test_file_result(
                rel, digest, cases, cases_scan_complete, suffix,
                run_argv, run_file_cmd,
            )

        if selected:
            worker_rows = run_test_matrix_workers(_extract_file_info, selected)
            rows, rows_incomplete, row_warnings = collect_test_matrix_rows(worker_rows)
            test_files.extend(rows)
            incomplete = incomplete or rows_incomplete
            warnings.extend(row_warnings)

        return build_test_matrix_response(
            framework,
            run_all_cmd,
            test_files,
            incomplete,
            warnings,
            max_depth=max_depth,
            max_files=max_files,
        )

    def affected_tests(self, root: str, changed_paths: list[str] | None = None, base: str = "HEAD") -> dict[str, Any]:
        """Map changed paths/symbols directly to affected test files and formulate targeted command."""
        resolved_root = Path(self._root(root))
        if changed_paths is None:
            changed_paths = []
            import subprocess
            try:
                from .process_utils import hidden_run_kwargs
                p = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "."], cwd=str(resolved_root), capture_output=True, timeout=5, **hidden_run_kwargs())
                if p.returncode != 0:
                    return {"success": False, "error": "Unable to determine changed paths from git status",
                            "error_code": "git_status_failed", "exit_code": p.returncode,
                            "terminal": True, "retryable": False}
                if not isinstance(p.stdout, bytes):
                    return {"success": False, "error": "Git status returned malformed path records",
                            "error_code": "git_status_malformed", "terminal": True, "retryable": False}
                from .git_status_paths import parse_porcelain_status_paths
                parsed_paths = parse_porcelain_status_paths(p.stdout)
                if parsed_paths is None:
                    return {"success": False, "error": "Git status returned malformed path records",
                            "error_code": "git_status_malformed", "terminal": True, "retryable": False}
                changed_paths.extend(parsed_paths)
                if changed_paths:
                    prefix_result = subprocess.run(["git", "rev-parse", "--show-prefix"], cwd=str(resolved_root), capture_output=True, timeout=5, **hidden_run_kwargs())
                    if (prefix_result.returncode != 0 or not isinstance(prefix_result.stdout, bytes)
                            or not prefix_result.stdout.endswith(b"\n")):
                        return {"success": False, "error": "Unable to determine repository path prefix",
                                "error_code": "git_prefix_failed", "terminal": True, "retryable": False}
                    prefix = os.fsdecode(prefix_result.stdout[:-1])
                    if prefix and not prefix.endswith("/"):
                        return {"success": False, "error": "Git returned malformed path prefix",
                                "error_code": "git_prefix_failed", "terminal": True, "retryable": False}
                    if prefix:
                        changed_paths = [path[len(prefix):] for path in changed_paths if path.startswith(prefix)]
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Git status timed out while determining changed paths",
                        "error_code": "git_status_timeout", "timed_out": True,
                        "terminal": False, "retryable": True}
            except Exception as exc:
                return {"success": False, "error": "Git status unavailable while determining changed paths",
                        "error_code": "git_status_unavailable", "error_type": type(exc).__name__,
                        "terminal": True, "retryable": False}

        def normalize_changed_path(value: str) -> str:
            normalized = value.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            return normalized

        norm_changed = [normalize_changed_path(p) for p in changed_paths if p]
        if not norm_changed:
            framework, _, _, _ = self._detect_test_framework(resolved_root)
            return {
                "success": True,
                "framework": framework,
                "changed_files": [],
                "test_files": [],
                "suggested_command": "",
                "confidence": 1.0,
            }

        matrix = self.test_matrix(root)
        framework = matrix.get("framework", "unknown")
        all_tests = matrix.get("test_files", [])

        test_paths_set: set[str] = set()
        graph_complete = False
        for t_linked in self.get_test_source_links(str(resolved_root), norm_changed):
            test_paths_set.add(t_linked)
        for p in norm_changed:
            p_lower = p.lower()
            if "test" in p_lower or "spec" in p_lower:
                test_paths_set.add(p)

        stems = {Path(p).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace(".spec", "") for p in norm_changed}
        for t in all_tests:
            t_path = t["path"].replace("\\", "/")
            t_stem = Path(t_path).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace(".spec", "")
            for s in stems:
                if s and (s == t_stem or s in t_stem or t_stem in s):
                    test_paths_set.add(t_path)

        code_index = self.code_index
        if code_index is None:
            # Direct DeterministicEngine callers may not receive the shared index
            # that services inject. Open the existing index lazily; preprocessing
            # owns demand-based admission and this query must not index the project.
            try:
                from .code_index import CodeIndex

                candidate_index = CodeIndex(self.config, self.repo_tools)
                self.code_index = candidate_index
                code_index = candidate_index
            except Exception:
                code_index = None
        if code_index is not None:
            try:
                imp = code_index.impact(str(resolved_root), norm_changed)
                if not isinstance(imp, dict) or not isinstance(imp.get("suggested_tests", []), list):
                    raise ValueError("code index returned malformed impact data")
                suggested_tests = imp.get("suggested_tests", [])
                if any(not isinstance(st, dict) or not isinstance(st.get("path"), str) for st in suggested_tests):
                    raise ValueError("code index returned malformed test paths")
                # Preserve conservative completeness until dependency coverage is verified.
                graph_complete = imp.get("success") is True and imp.get("graph_complete") is True
                for st in suggested_tests:
                    test_paths_set.add(st["path"].replace("\\", "/"))
            except Exception:
                graph_complete = False

        from .test_selection import affected_test_command, compatible_tests
        matched_tests, incompatible_tests = compatible_tests(sorted(test_paths_set), framework)
        cmd = affected_test_command(matched_tests, framework)

        return {
            "success": True,
            "framework": framework,
            "changed_files": norm_changed,
            "test_files": matched_tests,
            "excluded_incompatible_tests": incompatible_tests,
            "requires_multiple_runners": bool(incompatible_tests),
            "suggested_command": cmd,
            "confidence": 0.95 if matched_tests and graph_complete and not incompatible_tests else 0.5,
            "selection_complete": graph_complete and not incompatible_tests,
        }

    def repo_topology(self, root: str) -> dict[str, Any]:
        """Return a bounded local Python import graph and heuristic path labels."""
        return _repo_topology(
            root,
            root_resolver=self._root,
            repo_tools=self.repo_tools,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
            classify_layer=classify_topology_layer,
            build_summary=build_topology_summary_markdown,
        )

    def ast_rename(self, root: str, target_file: str, old_symbol: str, new_symbol: str, apply_changes: bool = False) -> dict[str, Any]:
        """Mechanically rename a symbol across the target file and its callers using AST / pattern replacement."""
        if not old_symbol or not new_symbol or old_symbol == new_symbol:
            return {"success": False, "error": "Invalid old or new symbol"}
        
        resolved_root = Path(self._root(root))
        affected_files: set[str] = set()
        if target_file and target_file not in (".", "*", "repo", "all"):
            norm_target = target_file.replace("\\", "/").lstrip("./")
            target_path = resolved_root / norm_target
            if not target_path.is_file():
                return {"success": False, "error": f"Target file not found: {norm_target}"}
            affected_files.add(norm_target)

        code_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".go", ".rs", ".java", ".cpp", ".c", ".h", ".hpp", ".rb", ".php"}
        all_code_files = [
            str(p.relative_to(resolved_root)).replace("\\", "/")
            for p in self.repo_tools.iter_files(str(resolved_root))
            if p.suffix.lower() in code_exts
        ]
        sym_pattern = re.compile(rf"\b{re.escape(old_symbol)}\b")
        
        for rel in all_code_files:
            fpath = resolved_root / rel
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                if sym_pattern.search(content):
                    affected_files.add(rel)
            except Exception:
                pass

        diffs: dict[str, str] = {}
        modified_contents: dict[str, str] = {}

        for rel in affected_files:
            fpath = resolved_root / rel
            try:
                old_txt = fpath.read_text(encoding="utf-8", errors="replace")
                new_txt = sym_pattern.sub(new_symbol, old_txt)
                if new_txt != old_txt:
                    modified_contents[rel] = new_txt
                    import difflib
                    diff_lines = list(difflib.unified_diff(
                        old_txt.splitlines(keepends=True),
                        new_txt.splitlines(keepends=True),
                        fromfile=rel,
                        tofile=rel,
                    ))
                    diffs[rel] = "".join(diff_lines)
            except Exception as e:
                return {"success": False, "error": f"Error processing {rel}: {e}"}

        if apply_changes:
            originals = {rel: (resolved_root / rel).read_text(encoding="utf-8", errors="replace") for rel in modified_contents}
            for rel, new_txt in modified_contents.items():
                (resolved_root / rel).write_text(new_txt, encoding="utf-8")

            import py_compile
            for rel in modified_contents:
                if rel.endswith(".py"):
                    try:
                        py_compile.compile(str(resolved_root / rel), doraise=True)
                    except py_compile.PyCompileError as syn_err:
                        for r_rel, orig_txt in originals.items():
                            (resolved_root / r_rel).write_text(orig_txt, encoding="utf-8")
                        return {
                            "success": False,
                            "applied": False,
                            "rolled_back": True,
                            "error": f"Syntax error in {rel} after rename: {syn_err.msg}",
                        }

        return {
            "success": True,
            "old_symbol": old_symbol,
            "new_symbol": new_symbol,
            "applied": apply_changes,
            "affected_files": sorted(modified_contents.keys()),
            "diffs": diffs,
        }

    def generate_mocks(self, root: str, target_file: str, symbol: str) -> dict[str, Any]:
        """Generate mock/stub objects and test fixtures for a target class, interface, or function."""
        if not symbol:
            return {"success": False, "error": "Symbol must not be empty"}

        resolved_root = Path(self._root(root))
        norm_target = target_file.replace("\\", "/").lstrip("./")
        target_path = resolved_root / norm_target
        if not target_path.is_file():
            return {"success": False, "error": f"Target file not found: {norm_target}"}

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"success": False, "error": f"Failed to read target file: {e}"}

        ext = target_path.suffix.lower()
        if ext == ".py" and (not symbol.isidentifier() or keyword.iskeyword(symbol)):
            return {
                "success": False,
                "error": "Python mock symbols must be valid identifiers",
            }
        if ext == ".py":
            import ast
            try:
                tree = ast.parse(content, filename=norm_target)
            except Exception:
                tree = None

            found_node = None
            if tree:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                        found_node = node
                        break

            if found_node and isinstance(found_node, ast.ClassDef):
                methods = [
                    m.name for m in found_node.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("__")
                ]
                mock_lines = [
                    f"class Mock{symbol}:",
                    f'    """Mock implementation of {symbol}."""',
                    "    def __init__(self, **kwargs):",
                    "        for k, v in kwargs.items():",
                    "            setattr(self, k, v)",
                ]
                for m in methods:
                    mock_lines.append(f"    def {m}(self, *args, **kwargs):")
                    mock_lines.append(f"        return MagicMock(name='{symbol}.{m}')")
                if not methods:
                    mock_lines.append("    pass")

                fixture_lines = [
                    "@pytest.fixture",
                    f"def mock_{symbol.lower()}():",
                    f"    return Mock{symbol}()",
                    "",
                    "@pytest.fixture",
                    f"def autospec_{symbol.lower()}():",
                    f"    return unittest.mock.create_autospec({symbol}, instance=True)",
                ]
                return {
                    "success": True,
                    "file": norm_target,
                    "symbol": symbol,
                    "kind": "class",
                    "language": "python",
                    "methods": methods,
                    "mock_code": "\n".join(mock_lines),
                    "fixture_code": "\n".join(fixture_lines),
                }
            elif found_node and isinstance(found_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                module_name = norm_target.rsplit(".", 1)[0].replace("/", ".")
                if module_name.endswith(".__init__"):
                    module_name = module_name[:-len(".__init__")]
                fixture_lines = [
                    "@pytest.fixture",
                    f"def mock_{symbol}():",
                    f"    with unittest.mock.patch('{module_name}.{symbol}') as m:",
                    "        yield m",
                ]
                return {
                    "success": True,
                    "file": norm_target,
                    "symbol": symbol,
                    "kind": "function",
                    "language": "python",
                    "mock_code": f"mock_{symbol} = unittest.mock.MagicMock(name='{symbol}')",
                    "fixture_code": "\n".join(fixture_lines),
                }
            else:
                mock_code = f"mock_{symbol} = unittest.mock.MagicMock(name='{symbol}')"
                fixture_code = (
                    "@pytest.fixture\n"
                    f"def mock_{symbol.lower()}():\n"
                    f"    return unittest.mock.MagicMock(name={symbol!r})"
                )
                return {
                    "success": True,
                    "file": norm_target,
                    "symbol": symbol,
                    "kind": "generic",
                    "language": "python",
                    "mock_code": mock_code,
                    "fixture_code": fixture_code,
                }
        elif ext in {".ts", ".tsx", ".js", ".jsx"}:
            mock_code = f"export const mock{symbol} = {{\n  // stub methods for {symbol}\n}};"
            fixture_code = f"jest.mock('./{target_path.stem}', () => ({{\n  {symbol}: jest.fn().mockImplementation(() => mock{symbol}),\n}}));"
            return {
                "success": True,
                "file": norm_target,
                "symbol": symbol,
                "kind": "generic",
                "language": "typescript" if ext in {".ts", ".tsx"} else "javascript",
                "mock_code": mock_code,
                "fixture_code": fixture_code,
            }
        else:
            return {
                "success": True,
                "file": norm_target,
                "symbol": symbol,
                "kind": "generic",
                "language": ext.lstrip("."),
                "mock_code": f"// Mock implementation for {symbol}",
                "fixture_code": f"// Test fixture for {symbol}",
            }

    def security_audit(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Deterministic static security analysis (hardcoded secrets, unsafe deserialization, SQL injection)."""
        if type(limit) is not int or not 1 <= limit <= 100000:
            return {"success": False, "error": "limit must be an integer from 1 through 100000", "terminal": True, "retryable": False}
        return run_security_audit(
            self,
            root,
            limit,
            secret_patterns=_SECURITY_AUDIT_SECRETS,
            code_smell_patterns=_SECURITY_AUDIT_SMELLS,
            python_shell_injection_lines=_python_shell_injection_lines,
            yaml_load_match_lines=_yaml_load_match_lines,
            pattern_match_lines=_pattern_match_lines,
            path_type=Path,
            ast_module=ast,
            os_module=os,
            time_module=time,
        )

    def split_changes(self, root: str, changed_files: list[str] | None = None) -> dict[str, Any]:
        """Cluster modified repo files into atomic, cohesive commit or PR chunks."""
        return run_split_changes(
            self,
            root,
            changed_files,
            path_type=Path,
            subprocess_module=subprocess,
            hidden_run_kwargs_fn=hidden_run_kwargs,
        )

    def synthesize_rules(self, root: str, limit: int = 10) -> dict[str, Any]:
        """Synthesize proactive coding and architecture rules from repository conventions."""
        resolved_root = Path(self._root(root))
        rules: list[dict[str, Any]] = []

        has_ruff = (resolved_root / "pyproject.toml").exists() or (resolved_root / "ruff.toml").exists()
        has_ts = (resolved_root / "tsconfig.json").exists()

        rules.append({
            "rule_id": "rule_bounded_execution",
            "title": "Always bound subprocesses and execution timeouts",
            "context": "System stability",
            "guidance": "Always specify bounded timeouts and use hidden_run_kwargs on Windows to avoid process orphans and GUI popups.",
            "confidence": 0.95,
        })

        rules.append({
            "rule_id": "rule_deterministic_first",
            "title": "Query deterministic indexes before neural models",
            "context": "Token & context efficiency",
            "guidance": "Use deterministic symbol index, ast refactoring, and code search before invoking local or cloud LLMs.",
            "confidence": 0.90,
        })

        if has_ts:
            rules.append({
                "rule_id": "rule_typescript_strict",
                "title": "TypeScript typecheck before committing",
                "context": "Type safety",
                "guidance": "Run `tsc --noEmit` with the agent host's native command tool before creating diffs or handoffs.",
                "confidence": 0.85,
            })

        if has_ruff:
            rules.append({
                "rule_id": "rule_python_ruff",
                "title": "Run ruff format and lint",
                "context": "Python styling",
                "guidance": "Run ruff format and lint with the agent host's native command tool before submitting PRs.",
                "confidence": 0.88,
            })

        return {
            "success": True,
            "root": str(resolved_root),
            "rule_count": len(rules),
            "rules": rules[:limit],
        }

    def code_invariants(self, root: str, path: str | None = None) -> dict[str, Any]:
        """Check Python source invariants; report unsupported files and syntax errors."""
        return run_code_invariants(
            self,
            root,
            path,
            path_type=Path,
            ast_module=ast,
            os_module=os,
            is_root_archive_path_fn=is_root_archive_path,
        )

    def generate_dataset(
        self,
        root: str,
        schema_or_model: dict[str, Any] | list[Any],
        count: int = 10,
        format: str = "json",
    ) -> dict[str, Any]:
        """Generate synthetic test datasets and seed data adhering to a field schema."""
        return build_dataset(
            self,
            root,
            schema_or_model,
            count,
            format,
            path_type=Path,
            json_dumps=json_dumps,
            io_module=io,
        )

    def profile_digest(self, profile_path: str, top_n: int = 15) -> dict[str, Any]:
        """Digest a cProfile / pstats binary profile or flamegraph trace into top bottleneck functions."""
        return build_profile_digest(
            profile_path,
            top_n,
            path_type=Path,
            json_module=json,
            math_module=math,
        )

    def _find_python_relations(
        self, root: str, symbol: str, limit: int, offset: int, direction: str,
    ) -> dict[str, Any]:
        return find_python_relations(
            self, root, symbol, limit, offset, direction, _is_symlink_or_reparse_point,
        )

    def find_callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find Python call sites targeting a symbol, in stable bounded pages."""
        return self._find_python_relations(root, symbol, limit, offset, "callers")

    def find_callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find Python calls made by a named function, in stable bounded pages."""
        return self._find_python_relations(root, symbol, limit, offset, "callees")

    def find_dead_code(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Detect potentially dead/uncalled functions and classes in repository."""
        return find_dead_code(
            self,
            root,
            limit,
            path_type=Path,
            os_module=os,
            ast_module=ast,
        )

    @staticmethod
    def fold_brace_blocks(code: str, target_symbols: set[str] | None = None) -> str:
        """Fold function/method bodies in brace-based languages (Go, Rust, TS, JS, C#, Java)."""
        lines = code.splitlines()
        out: list[str] = []
        targets = target_symbols or set()

        in_func = False
        func_brace_depth = 0
        current_brace_depth = 0

        FUNC_PAT = _BRACE_FUNCTION_EXPORT
        STRUCT_PAT = _BRACE_CLASS_INTERFACE

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("//", "#", "/*", "*")):
                if not in_func:
                    out.append(line)
                continue

            if not in_func:
                if FUNC_PAT.search(line) and not STRUCT_PAT.search(line) and ("{" in line or "=>" in line):
                    is_target = any(sym in line for sym in targets) if targets else False
                    if not is_target and "{" in line:
                        in_func = True
                        func_brace_depth = current_brace_depth
                        idx = line.find("{")
                        out.append(line[:idx + 1])
                        out.append("    /* ... */")
                        current_brace_depth += line.count("{") - line.count("}")
                        if current_brace_depth <= func_brace_depth:
                            in_func = False
                            out.append("}")
                        continue

                out.append(line)
                current_brace_depth += line.count("{") - line.count("}")
            else:
                current_brace_depth += line.count("{") - line.count("}")
                if current_brace_depth <= func_brace_depth:
                    in_func = False
                    indent = " " * (len(line) - len(line.lstrip()))
                    out.append(f"{indent}}}")

        return "\n".join(out)

    def ast_outline(self, root: str, path: str) -> dict[str, Any]:
        """Generate a token-compact structural interface outline collapsing function/method bodies."""
        p_root = Path(self._root(root)).resolve()
        target = Path(path)
        if not target.is_absolute():
            target = p_root / target
        target = target.resolve()
        if not target.is_relative_to(p_root):
            return {"success": False, "error": "file is outside project root"}
        if not target.is_file():
            return {"success": False, "error": f"file not found: {path}"}

        content = target.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(content, filename=str(target))

            class _BodyEllipsisTransformer(ast.NodeTransformer):
                def visit_FunctionDef(self, node):
                    doc = ast.get_docstring(node)
                    new_body: list[ast.stmt] = []
                    if doc:
                        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                    node.body = new_body
                    return self.generic_visit(node)

                def visit_AsyncFunctionDef(self, node):
                    doc = ast.get_docstring(node)
                    new_body: list[ast.stmt] = []
                    if doc:
                        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                    node.body = new_body
                    return self.generic_visit(node)

            transformer = _BodyEllipsisTransformer()
            new_tree = transformer.visit(tree)
            ast.fix_missing_locations(new_tree)
            outlined = ast.unparse(new_tree)
            char_savings = max(0, len(content) - len(outlined))
            token_savings_pct = round((char_savings / max(1, len(content))) * 100, 1)

            return {
                "success": True,
                "path": str(target.relative_to(p_root)).replace("\\", "/"),
                "outline": outlined,
                "original_chars": len(content),
                "outline_chars": len(outlined),
                "reduction_pct": token_savings_pct,
            }
        except Exception:
            if "{" in content and "}" in content:
                outlined = self.fold_brace_blocks(content)
                char_savings = max(0, len(content) - len(outlined))
                token_savings_pct = round((char_savings / max(1, len(content))) * 100, 1)
                return {
                    "success": True,
                    "path": str(target.relative_to(p_root)).replace("\\", "/"),
                    "outline": outlined,
                    "original_chars": len(content),
                    "outline_chars": len(outlined),
                    "reduction_pct": token_savings_pct,
                    "polyglot": True,
                }
            out_lines = []
            for line in content.splitlines():
                if re.match(r"^\s*(?:def|class|async def|public|private|function|fn|func|interface|struct)\b", line):
                    out_lines.append(line)
            outline_txt = "\n".join(out_lines)
            return {
                "success": True,
                "path": str(target.relative_to(p_root)).replace("\\", "/"),
                "outline": outline_txt or content[:1000],
                "fallback": True,
            }

    def secret_scan(
        self,
        root: str,
        path: str | None = None,
        *,
        scan_git_history: bool = False,
        commit_depth: int = 20,
    ) -> dict[str, Any]:
        return scan_secrets(
            self,
            root,
            path,
            scan_git_history=scan_git_history,
            commit_depth=commit_depth,
            max_entries=_SECRET_SCAN_MAX_ENTRIES,
            max_files=_SECRET_SCAN_MAX_FILES,
            max_file_bytes=_SECRET_SCAN_MAX_FILE_BYTES,
            max_total_bytes=_SECRET_SCAN_MAX_TOTAL_BYTES,
            max_line_bytes=_SECRET_SCAN_MAX_LINE_BYTES,
            max_seconds=_SECRET_SCAN_MAX_SECONDS,
            max_findings=_SECRET_SCAN_MAX_FINDINGS,
            patterns=_SECRET_SCAN_PATTERNS,
            run_hidden_callable=run_hidden,
        )


    @staticmethod
    def _find_sqlite_database(p_root: Path) -> Path | None:
        """Find a SQLite file without traversing generated or environment trees."""
        ignored_dirs = {"node_modules", "venv", "tool-envs", "site-packages", ".venv"}
        sqlite_suffixes = {".sqlite3", ".db", ".sqlite"}
        for current, dirnames, filenames in os.walk(p_root, topdown=True, followlinks=False):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for dirname in dirnames:
                if dirname.startswith(".") or dirname.lower() in ignored_dirs:
                    continue
                child = current_path / dirname
                if _is_directory_reparse_point(child):
                    continue
                kept_dirs.append(dirname)
            dirnames[:] = sorted(kept_dirs)
            for filename in sorted(filenames):
                if Path(filename).suffix.lower() in sqlite_suffixes:
                    return current_path / filename
        return None

    def schema_inspect(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        """Inspect SQLite database schema (tables, columns, indexes, foreign keys)."""
        p_root = Path(self._root(root))
        target_db: Path | None = None
        if db_path:
            p = Path(db_path)
            target_db = p if p.is_absolute() else p_root / p
        else:
            target_db = self._find_sqlite_database(p_root)

        if not target_db or not target_db.is_file():
            return {"success": False, "status_code": 404, "error": f"no SQLite database found in root: {root}"}

        try:
            resolved_db = target_db.resolve(strict=True)
            relative_db = resolved_db.relative_to(p_root)
        except (OSError, ValueError) as exc:
            return {"success": False, "status_code": 400, "error": f"database path is outside root or unavailable: {exc}"}

        tables: dict[str, Any] = {}
        try:
            database_uri = f"{resolved_db.as_uri()}?mode=ro"
            with closing(connect_sqlite(database_uri, uri=True, timeout_seconds=5.0, read_only=True)) as con:
                tbl_rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                for (tbl_name,) in tbl_rows:
                    safe_tbl = tbl_name.replace('"', '""')
                    cols = con.execute(f'PRAGMA table_info("{safe_tbl}")').fetchall()
                    indexes = con.execute(f'PRAGMA index_list("{safe_tbl}")').fetchall()
                    fks = con.execute(f'PRAGMA foreign_key_list("{safe_tbl}")').fetchall()
                    tables[tbl_name] = {
                        "columns": [{"name": c[1], "type": c[2], "notnull": bool(c[3]), "pk": bool(c[5])} for c in cols],
                        "indexes": [idx[1] for idx in indexes],
                        "foreign_keys": [{"to_table": fk[2], "from_col": fk[3], "to_col": fk[4]} for fk in fks],
                    }
            return {
                "success": True,
                "db_path": str(relative_db).replace("\\", "/"),
                "table_count": len(tables),
                "tables": tables,
            }
        except Exception as exc:
            return {"success": False, "status_code": 500, "error": f"database inspection failed: {exc}"}

    def explain_query(self, root: str, query: str, db_path: str | None = None) -> dict[str, Any]:
        """Run EXPLAIN QUERY PLAN on an SQLite query to inspect execution strategy and indexes."""
        p_root = Path(self._root(root))
        target_db: Path | None = None
        if db_path:
            p = Path(db_path)
            target_db = p if p.is_absolute() else p_root / p
        else:
            target_db = self._find_sqlite_database(p_root)

        if not target_db or not target_db.is_file():
            return {"success": False, "status_code": 404, "error": "no SQLite database found for query explain"}

        if not query or not query.strip():
            return {"success": False, "status_code": 400, "error": "query cannot be empty"}

        clean_query = query.strip()
        if not clean_query.lower().startswith("select"):
            return {"success": False, "status_code": 400, "error": "only SELECT queries are allowed for explain_query"}
        if ";" in clean_query.rstrip(";"):
            return {"success": False, "status_code": 400, "error": "multiple statements are not permitted"}

        try:
            resolved_db = target_db.resolve(strict=True)
            relative_db = resolved_db.relative_to(p_root)
            with closing(connect_sqlite(resolved_db, timeout_seconds=5.0, read_only=True)) as con:
                rows = con.execute(f"EXPLAIN QUERY PLAN {clean_query}").fetchall()
                plan_items = [{"id": r[0], "parent": r[1], "detail": r[3]} for r in rows]
                uses_index = any("USING INDEX" in item["detail"] or "USING COVERING INDEX" in item["detail"] for item in plan_items)
                full_scan = any("SCAN TABLE" in item["detail"] for item in plan_items)

            return {
                "success": True,
                "db_path": str(relative_db).replace("\\", "/"),
                "query": clean_query,
                "uses_index": uses_index,
                "has_full_table_scan": full_scan,
                "plan": plan_items,
            }
        except Exception as exc:
            return {"success": False, "status_code": 500, "error": f"explain query failed: {exc}"}

    def env_compat(self, root: str) -> dict[str, Any]:
        """Analyze project manifests for OS, runtime, and build-tool dependencies."""
        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}

        current_os = os.name
        results: dict[str, Any] = {
            "os": "windows" if current_os == "nt" else "posix",
            "python_version": sys.version.split()[0],
            "detected_manifests": [],
            "warnings": [],
            "toolchain_requirements": [],
        }

        pyproj = p_root / "pyproject.toml"
        if pyproj.is_file():
            results["detected_manifests"].append("pyproject.toml")
            content = pyproj.read_text(encoding="utf-8", errors="replace")
            if "maturin" in content or "setuptools-rust" in content:
                results["toolchain_requirements"].append("Rust compiler (cargo)")
            if "pybind11" in content or "cython" in content:
                results["toolchain_requirements"].append("C/C++ compiler toolchain (MSVC on Windows / GCC on Linux)")

        pkg_json = p_root / "package.json"
        if pkg_json.is_file():
            results["detected_manifests"].append("package.json")
            content = pkg_json.read_text(encoding="utf-8", errors="replace")
            if "node-gyp" in content:
                results["toolchain_requirements"].append("python + visual studio build tools (node-gyp)")

        cargo_toml = p_root / "Cargo.toml"
        if cargo_toml.is_file():
            results["detected_manifests"].append("Cargo.toml")
            if not shutil.which("cargo"):
                results["warnings"].append("Cargo.toml found but 'cargo' binary is not on system PATH")

        reqs = p_root / "requirements.txt"
        if reqs.is_file():
            results["detected_manifests"].append("requirements.txt")

        return {
            "success": True,
            **results,
            "python": results["python_version"],
            "dependencies": results["detected_manifests"],
            "ready": len(results["warnings"]) == 0,
        }

    def status(self, root: str | None = None) -> dict[str, Any]:
        now = time.monotonic()
        key = str(root or "__all__")
        if not hasattr(self, "_status_cache"):
            self._status_cache = {}
        cached = self._status_cache.get(key)
        if cached and now - cached["time"] < 5.0:
            return dict(cached["data"])
        try:
            # SQLite's WAL snapshot, rather than the index writer's Python lock,
            # isolates this read of committed metadata.
            with closing(self._connect()) as con:
                if root:
                    r = self._root(root); where = " WHERE root=?"; args = (r,)
                else:
                    where = ""; args = ()
                counts = {
                    "files": int(con.execute(f"SELECT COUNT(*) FROM files{where}", args).fetchone()[0]),
                    "facts": int(con.execute(f"SELECT COUNT(*) FROM facts{where}", args).fetchone()[0]),
                    "dependencies": int(con.execute(f"SELECT COUNT(*) FROM dependencies{where}", args).fetchone()[0]),
                    "scripts": int(con.execute(f"SELECT COUNT(*) FROM scripts{where}", args).fetchone()[0]),
                } if root else global_row_counts(con, ("files", "facts", "dependencies", "scripts"))
            res = {"success": True, "healthy": True, **counts, "stats": dict(self._stats)}
            if len(self._status_cache) > 64:
                oldest = sorted(self._status_cache.items(), key=lambda x: x[1].get("time", 0))[:32]
                for k, _ in oldest:
                    self._status_cache.pop(k, None)
            self._status_cache[key] = {"time": now, "data": res}
            return res
        except Exception as exc:
            return {"success": False, "healthy": False, "error": str(exc), "stats": dict(self._stats)}

    def find_circular_dependencies(
        self,
        root: str,
        language: str = "python",
        max_depth: int = 15,
        max_cycles: int = 50,
    ) -> dict[str, Any]:
        """Detect circular module import cycles in Python and JS/TS codebases."""
        return find_indexed_circular_dependencies(
            root, language, max_depth, max_cycles, self.code_index
        )

    def generate_types(self, root: str, file_path: str) -> dict[str, Any]:
        """Generate PEP 484 stub text without writing files."""
        max_source_bytes = 1_048_576
        try:
            p_root = Path(root).expanduser().resolve(strict=True)
            if not p_root.is_dir():
                raise ValueError("repository root is not a directory")
            target = Path(file_path).expanduser()
            if not target.is_absolute():
                target = p_root / target
            target = target.resolve(strict=True)
            try:
                target.relative_to(p_root)
            except ValueError:
                return {
                    "success": False,
                    "error": f"file is outside repository root: {file_path}",
                    "terminal": True,
                    "retryable": False,
                }
            if not target.is_file():
                return {
                    "success": False,
                    "error": f"file not found: {file_path}",
                    "terminal": True,
                    "retryable": False,
                }
            if target.stat().st_size > max_source_bytes:
                return {
                    "success": False,
                    "error": f"source file exceeds {max_source_bytes} byte limit",
                    "terminal": True,
                    "retryable": False,
                }
            with target.open("rb") as source_file:
                source_bytes = source_file.read(max_source_bytes + 1)
            if len(source_bytes) > max_source_bytes:
                return {
                    "success": False,
                    "error": f"source file exceeds {max_source_bytes} byte limit",
                    "terminal": True,
                    "retryable": False,
                }
            content = source_bytes.decode("utf-8", errors="replace")
            tree = ast.parse(content, filename=str(target))
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "success": False,
                "error": f"failed to resolve source file: {exc}",
                "terminal": True,
                "retryable": False,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": f"failed to parse AST: {exc}",
                "terminal": True,
                "retryable": False,
            }

        stub_lines = ["from __future__ import annotations", "from typing import Any, Optional, Union, List, Dict, Tuple, Callable", ""]
        
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                args = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
                ret = f" -> {ast.unparse(node.returns)}" if hasattr(ast, "unparse") and node.returns else " -> Any"
                stub_lines.append(f"{prefix}def {node.name}({args}){ret}: ...")
                stub_lines.append("")
            elif isinstance(node, ast.ClassDef):
                bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if hasattr(ast, "unparse") and node.bases else ""
                stub_lines.append(f"class {node.name}{bases}:")
                has_methods = False
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        has_methods = True
                        prefix = "    async " if isinstance(item, ast.AsyncFunctionDef) else "    "
                        args = ast.unparse(item.args) if hasattr(ast, "unparse") else "..."
                        ret = f" -> {ast.unparse(item.returns)}" if hasattr(ast, "unparse") and item.returns else " -> Any"
                        stub_lines.append(f"{prefix}def {item.name}({args}){ret}: ...")
                if not has_methods:
                    stub_lines.append("    ...")
                stub_lines.append("")

        stub_content = "\n".join(stub_lines).strip() + "\n"

        return {
            "success": True,
            "source_file": str(target),
            "stub_file": None,
            "stub_content": stub_content,
            "stub_lines": len(stub_lines),
        }

    def code_complexity(
        self, root: str, path: str | None = None, max_results: int = 20, include_tests: bool = False
    ) -> dict[str, Any]:
        return compute_code_complexity(
            root,
            path,
            max_results,
            include_tests,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
            is_test_file=_is_test_file,
            is_root_archive_path=is_root_archive_path,
        )


    def extract_api_spec(self, root: str, framework: str | None = None) -> dict[str, Any]:
        return _extract_api_spec(
            root,
            framework,
            repo_tools=getattr(self, "repo_tools", None),
        )

    def slice_dependency_graph(self, root: str, symbol: str, path: str | None = None, depth: int = 2) -> dict[str, Any]:
        """Extract a minimal AST dependency slice for a target symbol, saving context tokens."""
        if not isinstance(symbol, str) or not symbol.isidentifier() or keyword.iskeyword(symbol):
            return {"success": False, "status_code": 400, "error": "symbol must be a valid Python identifier"}
        p_root = Path(root).expanduser().resolve(strict=False)
        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}

        target_file: Path | None = None
        target_node: ast.AST | None = None
        file_lines: list[str] = []

        files_to_check: list[Path] = []
        if path:
            p = Path(path)
            if not p.is_absolute():
                p = p_root / p
            try:
                p = p.resolve(strict=False)
                p.relative_to(p_root)
            except (OSError, RuntimeError, ValueError):
                return {"success": False, "status_code": 400, "error": "path must resolve inside the repository root"}
            if p.is_file():
                files_to_check.append(p)
        else:
            for current_root, directories, filenames in os.walk(p_root):
                directories[:] = sorted(directory for directory in directories if directory not in skip_dirs)
                files_to_check.extend(
                    Path(current_root) / filename
                    for filename in sorted(filenames)
                    if filename.lower().endswith(".py")
                )

        for p in files_to_check:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(p))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                        target_file = p
                        target_node = node
                        file_lines = content.splitlines()
                        break
            except Exception:
                continue
            if target_node:
                break

        if not target_node or not target_file:
            return {"success": False, "error": f"symbol '{symbol}' not found"}

        referenced_names: set[str] = set()
        for sub in ast.walk(target_node):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name):
                    referenced_names.add(sub.func.id)
                elif isinstance(sub.func, ast.Attribute):
                    referenced_names.add(sub.func.attr)

        snippets: list[str] = []
        target_code = "\n".join(file_lines[target_node.lineno - 1: getattr(target_node, "end_lineno", target_node.lineno + 10)])
        snippets.append(f"# === Target Symbol: {symbol} ({target_file.name}:{target_node.lineno}) ===\n{target_code}")

        found_deps: list[str] = []
        for dep_name in sorted(referenced_names):
            if dep_name == symbol or len(dep_name) <= 2:
                continue
            for p in [target_file] + files_to_check[:10]:
                try:
                    c = p.read_text(encoding="utf-8", errors="replace")
                    t = ast.parse(c, filename=str(p))
                    for n in ast.walk(t):
                        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == dep_name:
                            lines = c.splitlines()
                            dep_code = "\n".join(lines[n.lineno - 1: getattr(n, "end_lineno", n.lineno + 15)])
                            snippets.append(f"# --- Dependency: {dep_name} ({p.name}:{n.lineno}) ---\n{dep_code}")
                            found_deps.append(dep_name)
                            break
                except Exception:
                    continue
                if dep_name in found_deps:
                    break

        sliced_code = "\n\n".join(snippets)
        total_original_chars = sum(len(f.read_text(encoding="utf-8", errors="replace")) for f in [target_file])
        token_savings = max(0.0, round((1.0 - (len(sliced_code) / max(1, total_original_chars))) * 100, 1))

        return {
            "success": True,
            "symbol": symbol,
            "file": str(target_file.relative_to(p_root) if target_file.is_relative_to(p_root) else target_file),
            "line": target_node.lineno,
            "dependencies_found": found_deps,
            "sliced_code": sliced_code,
            "slice_chars": len(sliced_code),
            "token_savings_percent": token_savings,
        }

    def migration_drift(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        return detect_migration_drift(
            root,
            db_path,
            bounded_schema_files=_bounded_schema_files,
            connect_sqlite_fn=connect_sqlite,
            max_schema_db_bytes=_MAX_SCHEMA_DB_BYTES,
            schema_db_timeout_seconds=_SCHEMA_DB_TIMEOUT_SECONDS,
            max_schema_scan_seconds=_MAX_SCHEMA_SCAN_SECONDS,
            max_schema_db_tables=_MAX_SCHEMA_DB_TABLES,
            max_schema_db_columns=_MAX_SCHEMA_DB_COLUMNS,
            max_schema_migration_db_bytes=_MAX_SCHEMA_MIGRATION_DB_BYTES,
            max_schema_file_bytes=_MAX_SCHEMA_FILE_BYTES,
            max_schema_total_bytes=_MAX_SCHEMA_TOTAL_BYTES,
        )


    def package_audit(self, root: str, lockfile_path: str | None = None) -> dict[str, Any]:
        from .dependency_audit import MAX_MANIFEST_BYTES, audit_manifest
        try:
            lexical_root = Path(root).expanduser()
            if not lexical_root.is_absolute():
                raise ValueError("repository root must be absolute")
            p_root = lexical_root.resolve(strict=True)
            if not p_root.is_dir():
                raise ValueError("repository root must be a directory")
            target = None
            if lockfile_path:
                candidate = Path(lockfile_path)
                target = candidate if candidate.is_absolute() else p_root / candidate
            else:
                for name in ("poetry.lock", "requirements.txt", "package-lock.json", "composer.lock", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "uv.lock", "pyproject.toml"):
                    candidate = p_root / name
                    if candidate.exists() or candidate.is_symlink():
                        target = candidate
                        break
            if target is None:
                raise ValueError("no supported dependency manifest or lockfile found in root")
            relative = target.relative_to(p_root)
            if ".." in relative.parts:
                raise PermissionError("manifest must stay inside repository root")
            cursor = p_root
            for part in relative.parts:
                cursor = cursor / part
                if _is_symlink_or_reparse_point(cursor):
                    raise PermissionError("manifest cannot traverse symlinks or reparse points")
            target = target.resolve(strict=True)
            target.relative_to(p_root)
            before = target.stat(follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MANIFEST_BYTES:
                raise ValueError("manifest must be a regular file within the byte limit")
            descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or not stat.S_ISREG(opened.st_mode):
                    raise PermissionError("manifest changed during authorization")
                data = stream.read(MAX_MANIFEST_BYTES + 1)
            if len(data) > MAX_MANIFEST_BYTES:
                raise ValueError("manifest exceeded byte limit")
            return audit_manifest(target, data.decode("utf-8"))
        except (OSError, RuntimeError, ValueError, UnicodeError):
            return {"success": False, "status": "invalid", "parse_complete": False,
                    "advisory_complete": False, "error": "manifest unavailable or outside permitted repository input",
                    "terminal": True, "retryable": False}

    def structural_search(
        self,
        root: str,
        pattern: str,
        path: str | None = None,
        max_results: int = 30,
    ) -> dict[str, Any]:
        """Syntax-aware structural code search across Python and multi-language repositories."""
        return search_structurally(
            root,
            pattern,
            path=path,
            max_results=max_results,
            is_symlink_or_reparse_point=_is_symlink_or_reparse_point,
        )

    def context_budget(
        self,
        root: str,
        files: list[str] | None = None,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Calculates token load per file and recommends surgical slices to fit within context budget."""
        canon_root = canonical_root(root)
        root_path = Path(canon_root)
        if not root_path.is_dir():
            return {"success": False, "error": f"invalid root directory: {root}"}

        from .code_tokens import count_code_tokens
        from .project_config import resolve_project_context
        settings = resolve_project_context(canon_root, configured_state_dir(self.config, create=False)).settings
        target_files = list(dict.fromkeys(files or []))
        if not target_files:
            target_files = [path.relative_to(root_path).as_posix()
                            for path in self.repo_tools.iter_files(canon_root, max_files=15)]
        omitted_files: list[dict[str, str]] = []
        bytes_read = 0
        all_exact = True
        if len(target_files) > 64:
            omitted_files.append({"path": "", "reason": "file_count_limit"})
        target_files = target_files[:64]

        file_breakdown: list[dict[str, Any]] = []
        total_chars = 0
        total_tokens = 0
        all_compressible_regions: list[dict[str, Any]] = []

        for rel in target_files:
            fpath = root_path / rel
            try:
                fpath.resolve(strict=True).relative_to(root_path)
                if not self.repo_tools._project_file_allowed(root_path, fpath, settings):
                    raise ValueError("path policy")
                limit = min(2_000_000, self.repo_tools.max_file_bytes, 8_000_000 - bytes_read)
                with fpath.open("rb") as handle:
                    raw = handle.read(max(0, limit) + 1)
                if len(raw) > limit:
                    raise ValueError("source budget")
                bytes_read += len(raw)
                content = raw.decode("utf-8", errors="replace")
            except (OSError, ValueError):
                omitted_files.append({"path": str(rel)[:240], "reason": "source_unavailable_or_outside_budget"})
                continue

            chars = len(content)
            token_count = count_code_tokens(content)
            tokens = int(token_count["tokens"])
            all_exact = all_exact and bool(token_count["exact"])
            total_chars += chars
            total_tokens += tokens

            lines = content.splitlines()
            compressible: list[dict[str, Any]] = []

            in_docstring = False
            doc_start = 0
            for idx, line in enumerate(lines, 1):
                s = line.strip()
                if '"""' in s or "'''" in s:
                    if not in_docstring:
                        in_docstring = True
                        doc_start = idx
                    else:
                        in_docstring = False
                        if idx - doc_start > 3:
                            compressible.append({
                                "file": rel,
                                "type": "docstring",
                                "start_line": doc_start,
                                "end_line": idx,
                                "tokens_saved": int((idx - doc_start) * 8),
                            })
                elif s.startswith("import ") or s.startswith("from "):
                    compressible.append({
                        "file": rel,
                        "type": "import_block",
                        "start_line": idx,
                        "end_line": idx,
                        "tokens_saved": 5,
                    })

            all_compressible_regions.extend(compressible[:5])

            file_breakdown.append({
                "path": rel,
                "lines": len(lines),
                "chars": chars,
                "est_tokens": tokens,
                "token_count_provenance": token_count,
                "compressible_regions_count": len(compressible),
            })

        exceeded = total_tokens > max_tokens
        recommended_slices: list[dict[str, Any]] = []
        if exceeded and file_breakdown:
            token_budget_per_file = max(100, int(max_tokens / len(file_breakdown)))
            for fb in file_breakdown:
                allowed_lines = min(fb["lines"], int(token_budget_per_file / 6))
                recommended_slices.append({
                    "path": fb["path"],
                    "slice": f"L1-L{allowed_lines}",
                    "est_slice_tokens": min(fb["est_tokens"], token_budget_per_file),
                })

        return {
            "success": True,
            "root": str(root_path),
            "max_tokens": max_tokens,
            "total_files": len(file_breakdown),
            "total_tokens": total_tokens,
            "token_count_provenance": {"encoding": "o200k_base", "exact": all_exact,
                                       "scope": "sum_of_decoded_file_counts"},
            "omitted_files": omitted_files,
            "complete": not omitted_files,
            "slice_recommendations_estimated": True,
            "budget_exceeded": exceeded,
            "file_breakdown": file_breakdown,
            "compressible_regions": all_compressible_regions[:15],
            "recommended_slices": recommended_slices,
            "compression_achievable_ratio": round(min(0.8, 1.0 - (max_tokens / max(1, total_tokens))), 2) if exceeded else 0.0,
        }

    def reachability_dead_code(
        self,
        root: str,
        entrypoints: list[str] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Perform whole-repository call-graph reachability analysis from entry points to identify globally unused code."""
        root_path = Path(root).expanduser().resolve(strict=False)
        if not root_path.is_dir():
            return {"success": False, "error": f"Root directory does not exist: {root_path}"}

        ep_candidates = list(entrypoints or [])
        all_py_files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "node_modules", "venv", "__pycache__", "build", "dist"))]
            for fn in filenames:
                p = Path(dirpath) / fn
                relative_path = p.relative_to(root_path)
                if p.suffix.lower() == ".py" and not _is_test_file(relative_path.as_posix()):
                    all_py_files.append(p)
                    if not entrypoints and fn.lower() in ("main.py", "app.py", "cli.py", "__main__.py", "server.py"):
                        ep_candidates.append(relative_path.as_posix())

        if not ep_candidates and all_py_files:
            ep_candidates.append(str(all_py_files[0].relative_to(root_path)).replace("\\", "/"))

        defs: dict[str, dict[str, Any]] = {}
        defs_by_name: dict[str, list[str]] = {}
        module_calls: dict[str, set[str]] = {}
        parse_errors: list[str] = []

        for p in all_py_files:
            rel = str(p.relative_to(root_path)).replace("\\", "/")
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                parse_errors.append(rel)
                continue

            file_calls: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    if not name.startswith("__"):
                        symbol_id = f"{rel}:{node.lineno}:{name}"
                        defs[symbol_id] = {"name": name, "file": rel, "line": node.lineno, "kind": type(node).__name__}
                        defs_by_name.setdefault(name, []).append(symbol_id)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        file_calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        file_calls.add(node.func.attr)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    file_calls.add(node.id)
            module_calls[rel] = file_calls

        from .reachability_analysis import analyze_reachability
        ambiguous_names, reachable, ambiguous_symbols, unreachable = analyze_reachability(
            defs, defs_by_name, module_calls, ep_candidates
        )
        warnings = []
        if ambiguous_names:
            warnings.append("Duplicate symbol names make reachability ambiguous; affected symbols were excluded from reachable and dead-code counts.")
        if parse_errors:
            warnings.append("Some Python files could not be parsed; reachability results may be incomplete.")
        truncated = len(unreachable) > limit or len(ambiguous_symbols) > limit

        return {
            "success": True,
            "complete": not ambiguous_names and not parse_errors,
            "root": str(root_path),
            "entrypoints": ep_candidates,
            "total_symbols": len(defs),
            "reachable_symbols_count": len(reachable),
            "ambiguous_symbols_count": len(ambiguous_symbols),
            "ambiguous_symbols": ambiguous_symbols[:limit],
            "unreachable_symbols_count": len(unreachable),
            "unreachable_symbols": unreachable[:limit],
            "dead_code_count": len(unreachable),
            "truncated": truncated,
            "warnings": warnings,
        }

    def ast_mutation_test(
        self,
        root: str,
        target_file: str,
        diff: str | None = None,
    ) -> dict[str, Any]:
        """Generate syntax-aware AST mutation candidates to measure regression test coverage and test suite strength."""
        root_path = Path(root).expanduser().resolve(strict=False)
        p = (root_path / target_file) if not Path(target_file).is_absolute() else Path(target_file)
        if not p.is_file():
            return {"success": False, "error": f"File not found: {p}"}

        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)
        except Exception as exc:
            return {"success": False, "error": f"AST parse failed: {exc}"}

        mutants: list[dict[str, Any]] = []
        mutant_id = 1

        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    orig_op = type(op).__name__
                    repl_op = "NotEq" if orig_op == "Eq" else ("Eq" if orig_op == "NotEq" else ("GtE" if orig_op == "Lt" else "Lt"))
                    mutants.append({
                        "id": f"MUT_{mutant_id:03d}",
                        "type": "comparison_boundary",
                        "line": getattr(node, "lineno", 0),
                        "original": orig_op,
                        "mutant": repl_op,
                        "description": f"Invert {orig_op} comparison to {repl_op} at L{getattr(node, 'lineno', 0)}",
                    })
                    mutant_id += 1
            elif isinstance(node, ast.BinOp):
                orig_op = type(node.op).__name__
                if orig_op in ("Add", "Sub"):
                    repl_op = "Sub" if orig_op == "Add" else "Add"
                    mutants.append({
                        "id": f"MUT_{mutant_id:03d}",
                        "type": "arithmetic_inversion",
                        "line": getattr(node, "lineno", 0),
                        "original": orig_op,
                        "mutant": repl_op,
                        "description": f"Swap arithmetic {orig_op} to {repl_op} at L{getattr(node, 'lineno', 0)}",
                    })
                    mutant_id += 1
            elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
                mutants.append({
                    "id": f"MUT_{mutant_id:03d}",
                    "type": "boolean_flip",
                    "line": getattr(node, "lineno", 0),
                    "original": str(node.value),
                    "mutant": str(not node.value),
                    "description": f"Flip boolean constant {node.value} to {not node.value} at L{getattr(node, 'lineno', 0)}",
                })
                mutant_id += 1

        return {
            "success": True,
            "target_file": str(p.relative_to(root_path) if p.is_relative_to(root_path) else p),
            "mutants_count": len(mutants),
            "mutants": mutants[:50],
            "vulnerability_index": round(min(1.0, len(mutants) / 20.0), 2),
        }

    def generate_type_stubs(
        self,
        root: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Generate clean .pyi or .d.ts type interface stubs from source AST."""
        root_path = Path(root).expanduser().resolve(strict=False)
        p = (root_path / file_path) if not Path(file_path).is_absolute() else Path(file_path)
        if not p.is_file():
            return {"success": False, "error": f"File not found: {p}"}

        content = p.read_text(encoding="utf-8", errors="ignore")
        if p.suffix.lower() == ".py":
            try:
                tree = ast.parse(content)
            except Exception as exc:
                return {"success": False, "error": f"Failed to parse python AST: {exc}"}

            stubs: list[str] = ["from __future__ import annotations", "from typing import Any, Optional, Union, Callable\n"]
            count = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    stubs.append(ast.unparse(node))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    count += 1
                    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                    args_str = ast.unparse(node.args)
                    ret_str = f" -> {ast.unparse(node.returns)}" if node.returns else " -> Any"
                    stubs.append(f"{prefix} {node.name}({args_str}){ret_str}: ...")
                elif isinstance(node, ast.ClassDef):
                    count += 1
                    bases = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
                    stubs.append(f"class {node.name}{bases}:")
                    methods_found = False
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods_found = True
                            count += 1
                            prefix = "async def" if isinstance(item, ast.AsyncFunctionDef) else "def"
                            args_str = ast.unparse(item.args)
                            ret_str = f" -> {ast.unparse(item.returns)}" if item.returns else " -> Any"
                            stubs.append(f"    {prefix} {item.name}({args_str}){ret_str}: ...")
                    if not methods_found:
                        stubs.append("    ...")

            stub_content = "\n".join(stubs) + "\n"
            return {
                "success": True,
                "file": file_path,
                "stub_type": "pyi",
                "symbols_annotated": count,
                "stub_content": stub_content,
            }
        else:
            lines = content.splitlines()
            declarations: list[str] = []
            for line in lines:
                s = line.strip()
                if s.startswith(("export function ", "export class ", "export interface ", "export type ")):
                    declarations.append(s.rstrip("{").strip() + ";")
            return {
                "success": True,
                "file": file_path,
                "stub_type": "d.ts",
                "symbols_annotated": len(declarations),
                "stub_content": "\n".join(declarations) + "\n",
            }

    @staticmethod
    def ast_diff(old_code: str, new_code: str) -> dict[str, Any]:
        """Classify bounded Python structural changes without executing source."""
        from .ast_diff import ast_diff

        return ast_diff(old_code, new_code)

    def skeletonize_code(
        self,
        code: str = "",
        target_symbols: list[str] | None = None,
        keep_imports: bool = True,
        *,
        root: str = "",
        path: str = "",
    ) -> dict[str, Any]:
        """Fold non-target function and method bodies into '...' to radically save prompt tokens while preserving AST outline."""
        if path and not code:
            indexed = getattr(self.code_index, "indexed_skeleton", None)
            if not callable(indexed) or target_symbols:
                return {"success": False, "terminal": True, "retryable": False,
                        "error_code": "indexed_skeleton_unavailable",
                        "error": "indexed outline requires an active index and no retained target bodies; otherwise supply source text"}
            return indexed(root, path)
        try:
            tree = ast.parse(code)
        except Exception:
            if "{" in code and "}" in code:
                skeleton = self.fold_brace_blocks(code, set(target_symbols or []))
                orig_len = len(code)
                skel_len = len(skeleton)
                ratio = round((orig_len - skel_len) / max(1, orig_len), 3)
                return {
                    "success": True,
                    "original_chars": orig_len,
                    "skeleton_chars": skel_len,
                    "savings_ratio": max(0.0, ratio),
                    "skeleton_code": skeleton,
                    "polyglot": True,
                }
            return {"success": True, "skeleton_code": code, "original_chars": len(code), "skeleton_chars": len(code), "savings_ratio": 0.0}

        targets = set(target_symbols or [])

        class _SkeletonTransformer(ast.NodeTransformer):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                self.generic_visit(node)
                if not targets or node.name not in targets:
                    doc = ast.get_docstring(node)
                    new_body: list[ast.stmt] = []
                    if doc:
                        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                    node.body = new_body
                return node

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
                self.generic_visit(node)
                if not targets or node.name not in targets:
                    doc = ast.get_docstring(node)
                    new_body: list[ast.stmt] = []
                    if doc:
                        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
                    new_body.append(ast.Expr(value=ast.Constant(value=Ellipsis)))
                    node.body = new_body
                return node

        transformer = _SkeletonTransformer()
        transformed = transformer.visit(tree)
        ast.fix_missing_locations(transformed)

        try:
            skeleton = ast.unparse(transformed)
        except Exception:
            skeleton = code

        orig_len = len(code)
        skel_len = len(skeleton)
        ratio = round((orig_len - skel_len) / max(1, orig_len), 3)

        return {
            "success": True,
            "original_chars": orig_len,
            "skeleton_chars": skel_len,
            "savings_ratio": max(0.0, ratio),
            "skeleton_code": skeleton,
        }

    def batch_replace(
        self,
        root: str,
        edits: list[dict[str, Any]],
        dry_run: bool = False,
        *,
        owned_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Apply multiple surgical string replacements across one or more files atomically with rollback."""
        p_root = Path(self._root(root)).resolve()
        if not edits or not isinstance(edits, list):
            return {"success": False, "error": "edits must be a non-empty list of replacement operations"}

        owned_scopes: list[Path] = []
        for owned_path in owned_paths or []:
            if not isinstance(owned_path, str) or not owned_path or owned_path != owned_path.strip() or "\x00" in owned_path:
                return {"success": False, "applied": False, "error": "invalid verified lease path"}
            scope = (p_root / owned_path).resolve()
            if not scope.is_relative_to(p_root):
                return {"success": False, "applied": False, "error": "verified lease path escapes project root"}
            owned_scopes.append(scope)

        def covered_by_verified_lease(target_path: Path) -> bool:
            for scope in owned_scopes:
                try:
                    target_path.relative_to(scope)
                    return True
                except ValueError:
                    continue
            return False

        # 1. Validate edit structures, resolve target files, and capture dirty hunks.
        resolved_files: dict[str, Path] = {}
        dirty_hunks: dict[Path, list[tuple[int, int]] | None] = {}
        for idx, edit in enumerate(edits):
            if not isinstance(edit, dict):
                return {"success": False, "error": f"edit #{idx} is not an object"}
            p_str = edit.get("path") or edit.get("file")
            old_str = edit.get("old") or edit.get("target") or edit.get("target_content")
            new_str = edit.get("new") if "new" in edit else (edit.get("replacement") or edit.get("replacement_content"))
            if not p_str or old_str is None or new_str is None:
                return {"success": False, "error": f"edit #{idx} missing path, old, or new"}
            
            p_candidate = (p_root / p_str).resolve()
            if not p_candidate.is_relative_to(p_root):
                return {"success": False, "error": f"path '{p_str}' escapes project root"}
            if not p_candidate.is_file():
                return {"success": False, "error": f"file not found: {p_str}"}
            rel_candidate = str(p_candidate.relative_to(p_root)).replace("\\", "/")
            try:
                status = subprocess.run(
                    ["git", "-C", str(p_root), "status", "--porcelain", "--", rel_candidate],
                    capture_output=True, check=False, timeout=5, **hidden_run_kwargs(),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return {"success": False, "applied": False, "error": f"unable to inspect Git status for {p_str}: {exc}", "path": p_str}
            if status.returncode == 0 and status.stdout.strip():
                if status.stdout.lstrip().startswith(b"??"):
                    dirty_hunks[p_candidate] = [(1, 2**31 - 1)]
                else:
                    try:
                        diff = subprocess.run(
                            ["git", "-C", str(p_root), "diff", "--no-ext-diff", "--unified=0", "HEAD", "--", rel_candidate],
                            capture_output=True, check=False, timeout=5, **hidden_run_kwargs(),
                        )
                    except (OSError, subprocess.SubprocessError) as exc:
                        return {"success": False, "applied": False, "error": f"unable to inspect Git diff for {p_str}: {exc}", "path": p_str}
                    if diff.returncode != 0:
                        return {"success": False, "applied": False, "error": f"Git diff failed for {p_str}: {diff.stderr.decode('utf-8', errors='replace')[:300]}", "path": p_str}
                    dirty_hunks[p_candidate] = parse_dirty_hunks(diff.stdout)
            elif status.returncode != 0:
                stderr = status.stderr.decode("utf-8", errors="replace")
                if "not a git repository" not in stderr.lower():
                    return {"success": False, "applied": False, "error": f"Git status failed for {p_str}: {stderr[:300]}", "path": p_str}
            resolved_files[p_str] = p_candidate

        # 2. Read and backup all target files in memory
        backups: dict[Path, str] = {}
        file_contents: dict[Path, str] = {}
        for rel_path, fpath in resolved_files.items():
            if fpath not in backups:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                backups[fpath] = content
                file_contents[fpath] = content

        # 3. Apply edits in-memory and verify uniqueness
        for idx, edit in enumerate(edits):
            p_str = edit.get("path") or edit.get("file")
            old_str = edit.get("old") or edit.get("target") or edit.get("target_content")
            new_str = edit.get("new") if "new" in edit else (edit.get("replacement") or edit.get("replacement_content"))
            fpath = resolved_files[p_str]
            current_text = file_contents[fpath]

            expected_sha = edit.get("expected_sha256") or edit.get("expected_sha")
            if expected_sha:
                cur_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
                if cur_sha.lower() != str(expected_sha).lower():
                    return {
                        "success": False,
                        "applied": False,
                        "error": f"CAS conflict for {p_str}: expected sha256 {str(expected_sha)[:12]}, file has {cur_sha[:12]}",
                        "conflict": True,
                        "current_sha256": cur_sha,
                        "path": p_str,
                    }

            count = current_text.count(old_str)
            if count == 0:
                return {
                    "success": False,
                    "applied": False,
                    "error": f"edit #{idx}: target text not found in {p_str}",
                    "path": p_str,
                }
            if count > 1:
                return {
                    "success": False,
                    "applied": False,
                    "error": f"edit #{idx}: target text found multiple times ({count}) in {p_str}. Must be unique.",
                    "path": p_str,
                }
            hunks = dirty_hunks.get(fpath)
            if hunks is not None:
                first_line = current_text.count("\n", 0, current_text.find(old_str)) + 1
                end_offset = current_text.find(old_str) + len(old_str)
                last_line = first_line + current_text.count("\n", current_text.find(old_str), end_offset)
                if any(first_line <= dirty_end and last_line >= dirty_start for dirty_start, dirty_end in hunks):
                    if not covered_by_verified_lease(fpath):
                        return {
                            "success": False,
                            "applied": False,
                            "error": f"refusing replacement overlapping unowned dirty hunk: {p_str}",
                            "path": p_str,
                        }
            file_contents[fpath] = current_text.replace(old_str, new_str, 1)

        # 4. Syntax preflight on modified Python files
        for fpath, new_text in file_contents.items():
            if fpath.suffix == ".py":
                try:
                    compile(new_text, str(fpath), "exec")
                except SyntaxError as syn_err:
                    rel = str(fpath.relative_to(p_root)).replace("\\", "/")
                    return {
                        "success": False,
                        "applied": False,
                        "error": f"Syntax error in {rel} after replacement: {syn_err.msg}",
                        "path": rel,
                    }

        if dry_run:
            return {
                "success": True,
                "applied": False,
                "dry_run": True,
                "edits_count": len(edits),
                "modified_files": [str(p.relative_to(p_root)).replace("\\", "/") for p in file_contents],
            }

        # 5. Commit writes atomically
        written_files: list[Path] = []
        try:
            for fpath, new_text in file_contents.items():
                fpath.write_text(new_text, encoding="utf-8")
                written_files.append(fpath)
        except Exception as exc:
            for written in written_files:
                written.write_text(backups[written], encoding="utf-8")
            return {"success": False, "applied": False, "error": f"Failed during disk write, rolled back: {exc}"}

        new_hashes = {
            str(p.relative_to(p_root)).replace("\\", "/"): hashlib.sha256(txt.encode("utf-8")).hexdigest()
            for p, txt in file_contents.items()
        }
        return {
            "success": True,
            "applied": True,
            "edits_count": len(edits),
            "modified_files": [str(p.relative_to(p_root)).replace("\\", "/") for p in file_contents],
            "sha256": new_hashes,
        }

