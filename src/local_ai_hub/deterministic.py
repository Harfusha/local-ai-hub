from __future__ import annotations

from .json_utils import dumps as json_dumps

import ast
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
from concurrent.futures import ThreadPoolExecutor
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
from .state_paths import configured_state_dir


logger = logging.getLogger(__name__)

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
_SECRET_SCAN_MAX_ENTRIES = 20_000
_SECRET_SCAN_MAX_FILES = 1_000
_SECRET_SCAN_MAX_FILE_BYTES = 1_048_576
_SECRET_SCAN_MAX_TOTAL_BYTES = 16_777_216
_SECRET_SCAN_MAX_LINE_BYTES = 65_536
_SECRET_SCAN_MAX_SECONDS = 5.0
_SECRET_SCAN_MAX_FINDINGS = 100
_RELATION_SCAN_MAX_SECONDS = 3.0
_GIT_INSIGHT_DEADLINE_SECONDS = 8.0
_GIT_INSIGHT_STREAM_LIMIT = 1_048_576
_GIT_HISTORY_QUERY_MAX_CHARS = 512
_GIT_HISTORY_AUTHOR_MAX_CHARS = 256
_GIT_HISTORY_PATH_MAX_CHARS = 4096
_GIT_HISTORY_COMMIT_LIMIT = 100
_HOTSPOT_ALGORITHM = "git-recency-half-life-90d-v1"
_HOTSPOT_GIT_COMMIT_LIMIT = 5_000
_HOTSPOT_PATH_LIMIT = 10_000
_HOTSPOT_FILE_LIMIT = 100
_HOTSPOT_FILE_BYTES_LIMIT = 262_144
_HOTSPOT_TOTAL_BYTES_LIMIT = 4_194_304
_HOTSPOT_ANALYSIS_SECONDS = 8.0


def _git_history_timestamp(value: Any, field: str, *, upper_bound: bool) -> tuple[float | None, str | None]:
    if value in (None, ""):
        return None, None
    if not isinstance(value, str) or len(value) > 64 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field} must be an ISO date or RFC3339 timestamp")
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        parsed_date = _datetime_date.fromisoformat(raw)
        parsed = _datetime.combine(
            parsed_date,
            _datetime_time.max if upper_bound else _datetime_time.min,
            tzinfo=_datetime_timezone.utc,
        )
    else:
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            raw,
            flags=re.IGNORECASE,
        ):
            raise ValueError(f"{field} must be an RFC3339 timestamp with an explicit timezone")
        normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        parsed = _datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or "T" not in raw.upper():
            raise ValueError(f"{field} RFC3339 timestamp must include an explicit timezone")
        parsed = parsed.astimezone(_datetime_timezone.utc)
    timestamp = parsed.timestamp()
    return timestamp, parsed.isoformat().replace("+00:00", "Z")


def _git_history_pathspec(root: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > _GIT_HISTORY_PATH_MAX_CHARS:
        raise ValueError("path must be a bounded repository-relative literal path")
    normalized = value.replace("\\", "/")
    windows_path = PureWindowsPath(value)
    parts = PurePosixPath(normalized).parts
    if (
        not normalized
        or normalized.startswith("/")
        or windows_path.drive
        or windows_path.is_absolute()
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized)
        or any(part in {"..", ""} for part in parts)
    ):
        raise ValueError("path must stay inside the repository root")
    canonical_root = Path(root).resolve(strict=True)
    candidate = (canonical_root / Path(*parts)).resolve(strict=False)
    try:
        candidate.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError("path must stay inside the repository root") from exc
    pathspec = PurePosixPath(*parts).as_posix()
    return None if pathspec == "." else pathspec


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
    """Collect schema candidates without materializing unbounded directory listings."""
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "state", "artifacts"}
    canonical_root = root.resolve(strict=True)
    pending = [canonical_root]
    candidates: list[Path] = []
    visited_dirs = 0
    visited_entries = 0
    visited_canonical_dirs: set[Path] = set()
    while pending:
        current = pending.pop().resolve(strict=True)
        try:
            current.relative_to(canonical_root)
        except ValueError as exc:
            raise PermissionError("schema scan directory resolves outside the requested root") from exc
        if current in visited_canonical_dirs:
            continue
        visited_canonical_dirs.add(current)
        visited_dirs += 1
        if visited_dirs > _MAX_SCHEMA_SCAN_DIRS or time.monotonic() >= deadline:
            raise TimeoutError("schema scan exceeded its directory or time budget")
        with os.scandir(current) as entries:
            for entry in entries:
                visited_entries += 1
                if visited_entries > _MAX_SCHEMA_SCAN_ENTRIES or time.monotonic() >= deadline:
                    raise TimeoutError("schema scan exceeded its entry or time budget")
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if getattr(os.path, "isjunction", lambda _path: False)(entry.path):
                        resolved_child = Path(entry.path).resolve(strict=True)
                        try:
                            resolved_child.relative_to(canonical_root)
                        except ValueError as exc:
                            raise PermissionError(
                                "schema scan junction resolves outside the requested root"
                            ) from exc
                    if entry.name.lower() not in skip_dirs and not entry.name.startswith("."):
                        pending.append(Path(entry.path))
                        if len(pending) + visited_dirs > _MAX_SCHEMA_SCAN_DIRS:
                            raise TimeoutError("schema scan exceeded its directory budget")
                    continue
                if not entry.is_file(follow_symlinks=False) or not entry.name.lower().endswith(suffix):
                    continue
                candidate = current / entry.name
                if migrations_only and not any(
                    part.lower() in {"migration", "migrations"}
                    for part in candidate.parent.relative_to(root).parts
                ):
                    continue
                candidates.append(candidate)
                if len(candidates) > _MAX_SCHEMA_SCAN_FILES:
                    raise TimeoutError(f"schema scan exceeded {_MAX_SCHEMA_SCAN_FILES} files")
    return sorted(candidates)


_WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$:/-]{1,100}")
TEST_MARKERS = ("/test/", "/tests/", "/spec/", "/specs/", "_test.", ".test.", "_spec.", ".spec.")

ROUTE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("http", re.compile(r"\bRoute::(get|post|put|patch|delete|options|any)\s*\(\s*['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete|options|head|all)\s*\(\s*['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"@\w+\.(get|post|put|patch|delete|options|head)\s*\(\s*['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"@(?:GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping)\s*\(\s*(?:value\s*=\s*)?['\"]([^'\"]+)", re.I)),
    ("http", re.compile(r"\bMap(Get|Post|Put|Patch|Delete|Methods)\s*\(\s*['\"]([^'\"]+)", re.I)),
]
ENV_PATTERNS = [
    re.compile(r"\bos\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bos\.environ(?:\.get)?\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"\bos\.environ\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\b(?:env|getenv)\(\s*['\"]([A-Za-z_][A-Za-z0-9_.-]*)['\"]"),
    re.compile(r"\$_ENV\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]"),
    re.compile(r"Environment\.GetEnvironmentVariable\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
]
CONFIG_PATTERNS = [
    re.compile(r"\bconfig\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\bsettings?\[['\"]([^'\"]+)['\"]\]", re.I),
]
SQL_RE = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE)\b", re.I)
CONCURRENCY_RE = re.compile(r"\b(async|await|thread|mutex|lock|semaphore|queue|channel|goroutine|tokio|Task\.Run|parallel|concurrent|atomic)\b", re.I)
SECURITY_RE = re.compile(r"\b(auth|authentication|authorization|permission|role|token|jwt|oauth|csrf|xss|encrypt|decrypt|password|secret|credential|sanitize|escape)\b", re.I)
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s-]*(.*)", re.I)

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


def _python_shell_injection_lines(source: str) -> list[int]:
    tree = ast.parse(source)
    scope_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    parents: dict[ast.AST, ast.AST] = {}
    scopes: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, scope_types):
            scopes.append(node)
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    imports_by_scope: dict[ast.AST, dict[str, str]] = {}
    bindings_by_scope: dict[ast.AST, set[str]] = {}
    for scope in scopes:
        imported: dict[str, str] = {}
        bound: set[str] = set()

        def collect_bindings(node: ast.AST) -> None:
            if node is not scope and isinstance(node, scope_types):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bound.add(node.name)
                return
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                        local_name = alias.asname or alias.name.split(".", 1)[0]
                        imported[local_name] = "module"
                    else:
                        bound.add(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    if node.module == "subprocess" and alias.name in {"Popen", "run", "call"}:
                        imported[local_name] = alias.name
                    else:
                        bound.add(local_name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            for child in ast.iter_child_nodes(node):
                collect_bindings(child)

        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = scope.args
            bound.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        collect_bindings(scope)
        # A local assignment/parameter shadows an outer import throughout its scope.
        for name in bound:
            imported.pop(name, None)
        imports_by_scope[scope] = imported
        bindings_by_scope[scope] = bound

    def resolves_as(node: ast.AST, name: str, kind: str) -> bool:
        def enclosing_scope(current: ast.AST | None) -> ast.AST | None:
            while current is not None and not isinstance(current, (ast.Module, *scope_types)):
                current = parents.get(current)
            return current

        scope = enclosing_scope(node)
        while scope is not None:
            if imports_by_scope.get(scope, {}).get(name) == kind:
                return True
            if name in bindings_by_scope.get(scope, set()):
                return False
            parent_scope = enclosing_scope(parents.get(scope))
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and isinstance(parent_scope, ast.ClassDef):
                parent_scope = enclosing_scope(parents.get(parent_scope))
            scope = parent_scope
        return False

    def literal_dict_enables_shell(value: ast.AST) -> bool:
        found, enabled = literal_dict_shell_value(value)
        return found and enabled

    def literal_dict_shell_value(value: ast.AST) -> tuple[bool, bool]:
        if not isinstance(value, ast.Dict):
            return False, False
        found = False
        enabled = False
        for key, item in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and key.value == "shell":
                found = True
                enabled = not (isinstance(item, ast.Constant) and not bool(item.value))
            elif key is None:
                nested_found, nested_enabled = literal_dict_shell_value(item)
                if nested_found:
                    found = True
                    enabled = nested_enabled
        return found, enabled

    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        is_subprocess_call = (
            isinstance(function, ast.Attribute)
            and function.attr in {"Popen", "run", "call"}
            and isinstance(function.value, ast.Name)
            and resolves_as(node, function.value.id, "module")
        ) or (
            isinstance(function, ast.Name)
            and any(
                resolves_as(node, function.id, imported_name)
                for imported_name in {"Popen", "run", "call"}
            )
        )
        if not is_subprocess_call:
            continue
        keyword_shell = any(
            (
                keyword.arg == "shell"
                and not (
                    isinstance(keyword.value, ast.Constant)
                    and not bool(keyword.value.value)
                )
            )
            or (keyword.arg is None and literal_dict_enables_shell(keyword.value))
            for keyword in node.keywords
        )
        # Popen's eighth optional positional argument (index 8) is ``shell``.
        positional_shell = (
            (
                isinstance(function, ast.Attribute)
                and function.attr == "Popen"
                and isinstance(function.value, ast.Name)
                and resolves_as(node, function.value.id, "module")
                or isinstance(function, ast.Name)
                and resolves_as(node, function.id, "Popen")
            )
            and len(node.args) > 8
            and not (
                isinstance(node.args[8], ast.Constant)
                and not bool(node.args[8].value)
            )
        )
        if keyword_shell or positional_shell:
            lines.add(node.lineno)
    return sorted(lines)

_SECRET_SCAN_PATTERNS: list[tuple[str, str, re.Pattern[str], str]] = [
    ("openai_api_key", "OpenAI API Key", re.compile(r"(sk-(?:proj-|live-)?[A-Za-z0-9_-]{20,60})"), "CRITICAL"),
    ("anthropic_api_key", "Anthropic API Key", re.compile(r"(sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,80})"), "CRITICAL"),
    ("aws_access_key", "AWS Access Key ID", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "CRITICAL"),
    ("github_pat", "GitHub Personal Access Token", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36})\b"), "CRITICAL"),
    ("slack_token", "Slack Token", re.compile(r"(xox[baprs]-[0-9A-Za-z-]{20,72})"), "HIGH"),
    ("slack_webhook", "Slack Incoming Webhook", re.compile(r"(https:\/\/hooks\.slack\.com\/services\/T[0-9A-Z]+\/B[0-9A-Z]+\/[0-9A-Za-z]+)"), "HIGH"),
    ("google_api_key", "Google Cloud / API Key", re.compile(r"\b(AIza[0-9A-Za-z-_]{35})\b"), "CRITICAL"),
    ("stripe_secret_key", "Stripe Secret Key", re.compile(r"\b((?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,})\b"), "CRITICAL"),
    ("private_key", "Private Key Header", re.compile(r"(-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----)"), "CRITICAL"),
    ("db_connection_uri", "Database Connection URI with Password", re.compile(r"\b((?:postgres|postgresql|mysql|mongodb|redis):\/\/[a-zA-Z0-9_\-\.]+:[a-zA-Z0-9_\-\.@#$%^&*!]+@[a-zA-Z0-9_\-\.]+)"), "HIGH"),
    ("generic_secret_assignment", "Generic Hardcoded Secret", re.compile(r"(?:api_key|secret_key|auth_token|client_secret|access_token)\s*=\s*['\"]([A-Za-z0-9+/=_\-\.]{16,})['\"]", re.I), "HIGH"),
]


def _is_test_file(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").lower()
    parts = norm.split("/")
    test_dirs = {"test", "tests", "fixtures", "fixture", "mock", "mocks", "__tests__", "spec", "specs"}
    if any(p in test_dirs for p in parts[:-1]):
        return True
    fname = parts[-1]
    if fname.startswith(("test_", "mock_")):
        return True
    test_suffixes = (
        "_test.py", "_test.go", "_test.js", "_test.ts",
        ".test.js", ".test.ts", ".test.tsx", ".test.jsx",
        ".spec.js", ".spec.ts", ".spec.tsx", ".spec.jsx",
        "test.php", "spec.php", "_test.php", ".test.php", ".spec.php",
        ".test.mjs", ".spec.mjs", ".test.cjs", ".spec.cjs",
    )
    return any(fname.endswith(s) for s in test_suffixes)


_INFRA_RESOURCE = re.compile('^\\s*resource\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_MODULE = re.compile('^\\s*module\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_PROVIDER = re.compile('^\\s*provider\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_VARIABLE = re.compile('^\\s*variable\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_STAGE_I = re.compile('^-?\\s*stage\\s*:\\s*([^#]+)', re.I)
_INFRA_JOB_I = re.compile('^-?\\s*job\\s*:\\s*([^#]+)', re.I)
_INFRA_TASK_I = re.compile('^-?\\s*task\\s*:\\s*([^#]+)', re.I)
_INFRA_SCRIPT_I = re.compile('^(?:script|bash|pwsh|powershell)\\s*:\\s*(.+)', re.I)
_INFRA_SERVICE = re.compile('^\\s*service\\s+([A-Za-z_]\\w*)')
_INFRA_RPC = re.compile('^\\s*rpc\\s+([A-Za-z_]\\w*)\\s*\\(')
_INFRA_MESSAGE = re.compile('^\\s*message\\s+([A-Za-z_]\\w*)')
_SOURCE_SECRET_RE = re.compile('(?i)(?:api[-_]?key|secret[-_]?key|access[-_]?token|password|passwd|auth[-_]?token|bearer)\\s*[=:]\\s*["\\\']([A-Za-z0-9+/\\-_]{12,})["\\\']')
_SOURCE_HARDCODED_IP = re.compile('\\b(?:https?://)\\d{1,3}(?:\\.\\d{1,3}){3}(?::\\d+)?\\b')
_SOURCE_UNITY_LIFECYCLES = re.compile('\\b(Awake|Start|Update|FixedUpdate|LateUpdate|OnEnable|OnDisable|OnDestroy|OnTriggerEnter|OnCollisionEnter|OnTriggerExit|OnCollisionExit|OnApplicationPause|OnApplicationQuit)\\s*\\(', re.M)
_SOURCE_REACT_COMPONENT = re.compile('(?:export\\s+(?:default\\s+)?)?(?:function|const|class)\\s+([A-Z][A-Za-z0-9_]+)', re.M)
_SOURCE_REACT_HOOK = re.compile('\\bconst\\s+(use[A-Z][A-Za-z0-9_]*)\\s*=', re.M)
_SOURCE_REACT_ROUTE = re.compile('(?:path|to)\\s*[:=]\\s*[\\\'"`]([/][^\\\'"`]*)[\\\'"`]', re.M)
_SOURCE_TS_DECLARATION = re.compile('^\\s*(?:export\\s+)?(?:default\\s+)?(interface|type|enum|class)\\s+([A-Za-z_$][A-Za-z0-9_$]*)', re.M)
_SOURCE_NEXT_ROUTE_HANDLER = re.compile('^\\s*export\\s+(?:async\\s+)?function\\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\\s*\\(', re.M)
_SOURCE_NEST_DECORATOR = re.compile('^\\s*@(Controller|Injectable|Get|Post|Put|Patch|Delete)\\s*(?:\\(\\s*[\'\\"]?([^\'\\")\\s]*)[\'\\"]?\\s*\\))?', re.M)
_SOURCE_TEST_SUITE_BLOCK = re.compile('^\\s*(describe|it|test)\\s*\\(\\s*[\'\\"` ]([^\'\\"`]+)[\'\\"` ]', re.M)
_SOURCE_FORM_TAG = re.compile('<form\\b([^>]*)>', re.I)
_SOURCE_ACTION_ATTR = re.compile('\\baction=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_METHOD_ATTR = re.compile('\\bmethod=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_SCRIPT_SRC = re.compile('<script\\b[^>]*\\bsrc=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_LINK_CSS = re.compile('<link\\b[^>]*\\bhref=["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_ELEM_ID = re.compile('\\bid=["\\\']([A-Za-z0-9_-]+)["\\\']', re.I)
_SOURCE_WEB_COMPONENT = re.compile('<([a-z0-9]+-[a-z0-9-]+)\\b', re.I)
_SOURCE_BLADE_DIRECTIVE = re.compile('@(extends|include|section|yield|livewire|component)\\s*\\(\\s*["\\\']([^"\\\']+)["\\\']', re.I)
_SOURCE_CSS_VAR = re.compile('--([A-Za-z0-9_-]+)\\s*:\\s*([^;]+);')
_SOURCE_KEYFRAMES = re.compile('@keyframes\\s+([A-Za-z0-9_-]+)')
_SOURCE_MEDIA_QUERY = re.compile('@media\\s+([^{]+)')
_SOURCE_CSS_CLASS = re.compile('^\\s*(\\.[A-Za-z0-9_-]+)\\s*\\{')
_SOURCE_PHP_DEF = re.compile('^\\s*(?:(?:final|abstract|readonly)\\s+)*(class|trait|interface|enum)\\s+([A-Za-z_][A-Za-z0-9_]*)', re.M)
_SOURCE_PHP_FUNC = re.compile('^\\s*(?:(?:public|protected|private|static|final|abstract)\\s+)*function\\s+([A-Za-z_][A-Za-z0-9_]*)\\s*\\(', re.M)
_SOURCE_PHP_NS = re.compile('^\\s*namespace\\s+([A-Za-z_][A-Za-z0-9_\\\\]*)', re.M)
_SOURCE_PHP_ROUTE_ATTR = re.compile('#\\[(?:Route|Get|Post|Put|Patch|Delete)\\s*(?:\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"](?:[^)]*methods:\\s*\\[([^\\]]+)\\])?\\s*\\))?\\]', re.M)
_SOURCE_PHP_ATTR = re.compile('#\\[([A-Za-z_][A-Za-z0-9_\\\\]*(?:\\([^)]*\\))?)\\]', re.M)
_SOURCE_WP_HOOK = re.compile('\\b(add_action|add_filter|do_action|apply_filters)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.M)
_SOURCE_LARAVEL_RESOURCE = re.compile('\\bRoute::(?:apiResource|resource)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]\\s*,\\s*([A-Za-z0-9_\\\\]+)', re.M)
_SOURCE_ELOQUENT_TABLE = re.compile('protected\\s+\\$table\\s*=\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_ELOQUENT_FILLABLE = re.compile('protected\\s+\\$fillable\\s*=\\s*\\[([^\\]]+)\\]')
_SOURCE_ELOQUENT_REL = re.compile('return\\s+\\$this->(belongsTo|hasMany|hasOne|belongsToMany|morphTo|morphMany)\\s*\\(\\s*([A-Za-z0-9_:\\\\]+)', re.I)
_SOURCE_SCHEMA_CREATE = re.compile('Schema::create\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_MIGRATION_COL = re.compile('\\$table->(string|integer|bigInteger|unsignedBigInteger|id|foreignId|boolean|text|longText|json|timestamp|date)\\s*\\(\\s*(?:[\\\'"]([^\\\'"]+)[\\\'"])?')
_SOURCE_ARTISAN_CMD = re.compile('protected\\s+\\$signature\\s*=\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_FORM_REQ = re.compile('class\\s+([A-Za-z0-9_]+)\\s+extends\\s+FormRequest\\b')
_SOURCE_CAKE_ROUTE = re.compile('\\$(?:builder|routes)->connect\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_CAKE_RESOURCES = re.compile('\\$(?:builder|routes)->resources\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_CAKE_TABLE = re.compile('class\\s+([A-Za-z0-9_]+Table)\\s+extends\\s+Table\\b')
_SOURCE_CAKE_ENTITY = re.compile('class\\s+([A-Za-z0-9_]+)\\s+extends\\s+Entity\\b')
_SOURCE_CAKE_ASSOC = re.compile('\\$this->(hasMany|belongsTo|belongsToMany|hasOne)\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_CAKE_MIGRATION = re.compile('\\$this->table\\s*\\(\\s*[\\\'"]([^\\\'"]+)[\\\'"]')
_SOURCE_DECORATOR_RE = re.compile('^@([\\w.]+)', re.M)
_SOURCE_ASYNC_DEF_RE = re.compile('\\basync\\s+def\\s+(\\w+)', re.M)
_SOURCE_DATACLASS_RE = re.compile('@dataclass', re.M)
_SOURCE_IMPORT_FROM = re.compile('^(?:from\\s+([\\w.]+)\\s+import\\s+([\\w, ]+)|import\\s+([\\w.]+))', re.M)
_SOURCE_TESTED_CLASS = re.compile('class\\s+Test(\\w+)', re.M)
_SOURCE_PHP_TESTED_CLASS = re.compile('class\\s+(\\w+)Test\\b', re.M)
_SOURCE_PHP_USE = re.compile('^\\s*use\\s+([A-Za-z_][A-Za-z0-9_\\\\]+);', re.M)
_SOURCE_JS_IMPORT = re.compile('import\\s+(?:\\{([^}]+)\\}|(\\w+))\\s+from\\s+[\'\\"]([^\'\\"]+)[\'\\"]', re.M)
_SOURCE_TABLE_INSERT_I = re.compile('\\b(?:CREATE\\s+TABLE|ALTER\\s+TABLE|INSERT\\s+INTO|UPDATE|DELETE\\s+FROM|FROM|JOIN)\\s+(?:IF\\s+(?:NOT\\s+)?EXISTS\\s+)?[`\\"\\[]?([A-Za-z_][A-Za-z0-9_.$:-]*)', re.I)
_MANIFEST_IMPLEMENTATION = re.compile('^\\s*(implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|kapt)\\s*\\(?[\\"\']([^\\"\']+)[\\"\']')
_MANIFEST_IDENTIFIER = re.compile('^\\s*gem\\s+[\'\\"]([^\'\\"]+)[\'\\"](?:\\s*,\\s*[\'\\"]([^\'\\"]+)[\'\\"])?')
_MANIFEST_IDENTIFIER_REGEX = re.compile('^([A-Za-z0-9_.-]+)\\s*:(?:[^=]|$)')
_MANIFEST_IDENTIFIER_REGEX_PATTERN = re.compile('^([A-Za-z0-9_.-]+)\\s*(?:[^:=]*)?:\\s*$')
_DIFF_SHELL_I = re.compile('\\b(exec|system|shell_exec|subprocess|Process\\.Start|Runtime\\.getRuntime)\\b', re.I)
_DIFF_EVAL_I = re.compile('\\b(eval|exec)\\s*\\(', re.I)
_DIFF_SECRET_PASSWORD_I = re.compile('\\b(password|secret|api[_-]?key|private[_-]?key|token)\\b', re.I)
_BRACE_FUNCTION_EXPORT = re.compile('^\\s*(?:(?:pub(?:lic)?|priv(?:ate)?|prot(?:ected)?|internal|static|async|export|default|override|virtual|final)\\s+)*(?:(?:func|fn|function|def)\\b|(?:[A-Za-z_$][\\w.<>,\\[\\]]*\\s+)+[A-Za-z_$][\\w$]*\\s*\\()|^\\s*(?:func\\s*\\([^)]*\\)\\s*)?[A-Za-z_$][\\w$]*\\s*\\([^)]*\\)\\s*(?:[^{;]*\\{|=>)')
_BRACE_CLASS_INTERFACE = re.compile('^\\s*(?:(?:pub(?:lic)?|export)\\s+)*(?:struct|interface|enum|type|trait|class)\\b')
_API_EXPRESS_ROUTER_METHOD = re.compile('\\b(?:app|router)\\.(get|post|put|patch|delete|options|head)\\s*\\(', re.I)
_API_NEXT_ROUTE_HANDLER = re.compile('^\\s*export\\s+(?:async\\s+)?function\\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\\s*\\(', re.M)
_API_LARAVEL_ROUTE_METHOD = re.compile('\\bRoute::(get|post|put|patch|delete|options|any)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_LARAVEL_RESOURCE_ROUTE = re.compile('\\bRoute::(?:apiResource|resource)\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_ATTRIBUTE_ROUTE_DECLARATION = re.compile('#\\[(?:Route|Get|Post|Put|Patch|Delete)\\s*(?:\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"](?:[^)]*methods:\\s*\\[([^\\]]+)\\])?\\s*\\))?\\]', re.I)
_API_PHP_CONNECT_ROUTE = re.compile('\\$(?:builder|routes)->connect\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_PHP_RESOURCE_ROUTE = re.compile('\\$(?:builder|routes)->resources\\s*\\(\\s*[\'\\"]([^\'\\"]+)[\'\\"]', re.I)
_API_HTML_FORM_ENDPOINT = re.compile('<form\\b(?=[^>]*\\baction=[\'\\"]([^\'\\"]+)[\'\\"])(?:[^>]*\\bmethod=[\'\\"]([A-Za-z]+)[\'\\"])?', re.I)


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
        initialize_row_counts(con, ("files", "facts", "dependencies", "scripts"))
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
        out = out if out is not None else []
        if len(out) >= limit:
            return out
        if isinstance(value, dict):
            for key, child in value.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                out.append(name)
                DeterministicEngine._flatten_config(child, name, out, limit)
                if len(out) >= limit: break
        elif isinstance(value, list):
            for child in value[:8]:
                DeterministicEngine._flatten_config(child, prefix, out, limit)
                if len(out) >= limit: break
        return out

    def _extract_infra_facts(self, path: str, text: str) -> list[dict[str, Any]]:
        """Extract common infrastructure/build facts with zero model calls.

        Parsers are intentionally conservative: they expose coordinates/declared
        values, not behavioral interpretations. This makes the output suitable for
        direct evidence and safe cache reuse.
        """
        facts: list[dict[str, Any]] = []
        rel = path.replace("\\", "/")
        low = rel.lower(); name = Path(rel).name.lower()
        lines = text.splitlines()

        if name in {"dockerfile", "containerfile"} or name.startswith("dockerfile."):
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                m = re.match(r"(?i)^FROM\s+([^\s]+)(?:\s+AS\s+([^\s]+))?", stripped)
                if m:
                    facts.append(self._fact("container_base", m.group(1), m.group(1), line_no, stage=m.group(2) or ""))
                m = re.match(r"(?i)^EXPOSE\s+(.+)$", stripped)
                if m:
                    for port in m.group(1).split():
                        facts.append(self._fact("port", port, port, line_no, source="docker"))
                m = re.match(r"(?i)^(?:ENV|ARG)\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
                if m:
                    facts.append(self._fact("env", m.group(1), m.group(1), line_no, source="docker"))
                if re.match(r"(?i)^(?:ENTRYPOINT|CMD)\b", stripped):
                    facts.append(self._fact("entrypoint", "container", stripped[:300], line_no, source="docker"))
                if re.match(r"(?i)^HEALTHCHECK\b", stripped):
                    facts.append(self._fact("healthcheck", "container", stripped[:300], line_no, source="docker"))

        if name in {"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"}:
            in_services = False; service = ""; service_indent = -1
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
                if re.match(r"^services\s*:\s*$", stripped):
                    in_services = True; service = ""; service_indent = indent; continue
                if in_services and stripped and not line.startswith(" ") and not stripped.startswith("#"):
                    in_services = False; service = ""
                if in_services:
                    m = re.match(r"^\s+([A-Za-z0-9_.-]+)\s*:\s*$", line)
                    if m and indent == service_indent + 2:
                        service = m.group(1)
                        facts.append(self._fact("service", service, service, line_no, source="compose"))
                        continue
                    m = re.match(r"^\s*image\s*:\s*[\"']?([^\"'#\s]+)", stripped, re.I)
                    if m and service:
                        facts.append(self._fact("container_image", service, m.group(1), line_no, service=service))
                    m = re.search(r"[\"']?(\d{2,5})(?::(\d{2,5}))?(?:/(?:tcp|udp))?[\"']?", stripped)
                    if m and service and ("port" in stripped.lower() or stripped.startswith("-")):
                        facts.append(self._fact("port", service, m.group(0).strip("\"'"), line_no, service=service))
                    if stripped.lower().startswith("healthcheck:") and service:
                        facts.append(self._fact("healthcheck", service, service, line_no, source="compose"))

        if "/.github/workflows/" in f"/{low}" or low.startswith(".github/workflows/"):
            in_jobs = False; jobs_indent = -1
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
                if re.match(r"^jobs\s*:\s*$", stripped):
                    in_jobs = True; jobs_indent = indent; continue
                if in_jobs:
                    m = re.match(r"^\s+([A-Za-z0-9_.-]+)\s*:\s*$", line)
                    if m and indent == jobs_indent + 2:
                        facts.append(self._fact("ci_job", m.group(1), m.group(1), line_no, source="github-actions"))
                m = re.match(r"^uses\s*:\s*([^\s#]+)", stripped)
                if m:
                    facts.append(self._fact("ci_action", m.group(1), m.group(1), line_no, source="github-actions"))
                m = re.match(r"^run\s*:\s*(.+)$", stripped)
                if m:
                    facts.append(self._fact("ci_command", "run", m.group(1)[:300], line_no, source="github-actions"))

        if name in {".gitlab-ci.yml", ".gitlab-ci.yaml"}:
            reserved = {"stages", "variables", "default", "include", "workflow", "image", "services", "before_script", "after_script", "cache"}
            current_job = ""
            in_script = False
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
                top = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*$", stripped) if indent == 0 else None
                if top:
                    key = top.group(1); in_script = False
                    current_job = "" if key in reserved or key.startswith(".") else key
                    if current_job:
                        facts.append(self._fact("ci_job", current_job, current_job, line_no, source="gitlab-ci"))
                    continue
                if current_job and re.match(r"^script\s*:\s*$", stripped):
                    in_script = True; continue
                if current_job and in_script:
                    cmd = re.match(r"^-\s+(.+)$", stripped)
                    if cmd:
                        facts.append(self._fact("ci_command", current_job, cmd.group(1)[:300], line_no, source="gitlab-ci"))
                    elif stripped and not stripped.startswith("#") and indent <= 2:
                        in_script = False

        if name in {"azure-pipelines.yml", "azure-pipelines.yaml"}:
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                for kind, pattern in (
                    ("ci_stage", _INFRA_STAGE_I),
                    ("ci_job", _INFRA_JOB_I),
                    ("ci_action", _INFRA_TASK_I),
                    ("ci_command", _INFRA_SCRIPT_I),
                ):
                    m = pattern.search(stripped)
                    if m:
                        value = m.group(1).strip().strip("\"'")[:300]
                        facts.append(self._fact(kind, value, value, line_no, source="azure-pipelines"))

        if name.startswith(".env"):
            for line_no, line in enumerate(lines, 1):
                m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
                if m:
                    facts.append(self._fact("env", m.group(1), m.group(1), line_no, source="env-file"))

        if Path(rel).suffix.lower() in {".ini", ".cfg", ".properties"}:
            section = ""
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                sm = re.match(r"^\[([^]]+)\]$", stripped)
                if sm:
                    section = sm.group(1); continue
                km = re.match(r"^([A-Za-z0-9_.-]+)\s*[=:]", stripped)
                if km:
                    key = f"{section}.{km.group(1)}" if section else km.group(1)
                    facts.append(self._fact("config_key", key, key, line_no, source="ini-properties"))

        if Path(rel).suffix.lower() in {".tf", ".tfvars"}:
            patterns = {
                "terraform_resource": _INFRA_RESOURCE,
                "terraform_module": _INFRA_MODULE,
                "terraform_provider": _INFRA_PROVIDER,
                "config_key": _INFRA_VARIABLE,
            }
            for line_no, line in enumerate(lines, 1):
                for kind, pattern in patterns.items():
                    m = pattern.search(line)
                    if m:
                        value = ".".join(x for x in m.groups() if x)
                        facts.append(self._fact(kind, value, value, line_no, source="terraform"))

        if Path(rel).suffix.lower() == ".proto":
            for line_no, line in enumerate(lines, 1):
                for kind, pattern in (
                    ("proto_service", _INFRA_SERVICE),
                    ("proto_rpc", _INFRA_RPC),
                    ("proto_message", _INFRA_MESSAGE),
                ):
                    m = pattern.search(line)
                    if m:
                        facts.append(self._fact(kind, m.group(1), m.group(1), line_no, source="protobuf"))

        # Kubernetes YAML is declarative and can be represented losslessly enough for
        # discovery without embedding the whole manifest. Keep extraction conservative.
        if Path(rel).suffix.lower() in {".yaml", ".yml"} and re.search(r"(?m)^\s*apiVersion\s*:", text) and re.search(r"(?m)^\s*kind\s*:", text):
            kind = ""; resource_name = ""
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                m = re.match(r"^kind\s*:\s*([^#]+)", stripped, re.I)
                if m:
                    kind = m.group(1).strip().strip("\"'")
                    facts.append(self._fact("k8s_kind", kind, kind, line_no, source="kubernetes"))
                    continue
                # metadata.name is intentionally accepted only on a simple scalar line;
                # the exact evidence coordinate remains available if disambiguation is needed.
                m = re.match(r"^name\s*:\s*([A-Za-z0-9_.-]+)\s*$", stripped)
                if m and not resource_name:
                    resource_name = m.group(1)
                    facts.append(self._fact("k8s_resource", resource_name, kind or "resource", line_no, source="kubernetes", resource_kind=kind))
                m = re.match(r"^image\s*:\s*([^#\s]+)", stripped, re.I)
                if m:
                    facts.append(self._fact("container_image", resource_name or kind or "k8s", m.group(1).strip("\"'"), line_no, source="kubernetes"))
                m = re.match(r"^(?:containerPort|port|targetPort)\s*:\s*([0-9]{1,5})", stripped, re.I)
                if m:
                    facts.append(self._fact("port", resource_name or kind or "k8s", m.group(1), line_no, source="kubernetes"))

        # OpenAPI/Swagger paths are exact declared routes. YAML gets precise line
        # coordinates; JSON is supplemented below from parsed data when available.
        if Path(rel).suffix.lower() in {".yaml", ".yml"} and ("openapi:" in text[:5000].lower() or "swagger:" in text[:5000].lower() or "openapi" in name or "swagger" in name):
            current_path = ""
            path_indent = -1
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
                pm = re.match(r"^(/[^:]+)\s*:\s*$", stripped)
                if pm:
                    current_path = pm.group(1).strip(); path_indent = indent; continue
                mm = re.match(r"^(get|post|put|patch|delete|options|head|trace)\s*:\s*$", stripped, re.I)
                if current_path and mm and indent > path_indent:
                    method = mm.group(1).upper()
                    facts.append(self._fact("route", current_path, method, line_no, method=method, source="openapi"))
                elif current_path and stripped and indent <= path_indent and not stripped.startswith("#"):
                    current_path = ""

        if name == "package.json":
            try:
                pkg_data = json.loads(text)
                if isinstance(pkg_data, dict):
                    if "name" in pkg_data:
                        facts.append(self._fact("package_name", str(pkg_data["name"]), "npm", 1, source="package.json"))
                    for script_name, cmd in (pkg_data.get("scripts") or {}).items():
                        facts.append(self._fact("npm_script", str(script_name), str(cmd)[:300], 1, script=str(script_name), command=str(cmd)))
                    for dep_key, kind in (("dependencies", "prod"), ("devDependencies", "dev"), ("peerDependencies", "peer")):
                        for dep, ver in (pkg_data.get(dep_key) or {}).items():
                            facts.append(self._fact("dependency", str(dep), str(ver), 1, manager="npm", dep_kind=kind))
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as parse_exc:
                logger.debug("Npm package metadata skipped (%s)", type(parse_exc).__name__)

        if name == "composer.json":
            try:
                comp_data = json.loads(text)
                if isinstance(comp_data, dict):
                    if "name" in comp_data:
                        facts.append(self._fact("package_name", str(comp_data["name"]), "composer", 1, source="composer.json"))
                    for dep_key, kind in (("require", "prod"), ("require-dev", "dev")):
                        for dep, ver in (comp_data.get(dep_key) or {}).items():
                            facts.append(self._fact("dependency", str(dep), str(ver), 1, manager="composer", dep_kind=kind))
                    autoload = comp_data.get("autoload") or {}
                    if isinstance(autoload, dict):
                        for ns, target_dir in (autoload.get("psr-4") or {}).items():
                            facts.append(self._fact("psr4_autoload", str(ns).rstrip("\\"), str(target_dir), 1, namespace=str(ns), path=str(target_dir)))
                    autoload_dev = comp_data.get("autoload-dev") or {}
                    if isinstance(autoload_dev, dict):
                        for ns, target_dir in (autoload_dev.get("psr-4") or {}).items():
                            facts.append(self._fact("psr4_autoload", str(ns).rstrip("\\"), str(target_dir), 1, namespace=str(ns), path=str(target_dir), dev=True))
                    for script_name, cmd in (comp_data.get("scripts") or {}).items():
                        cmd_val = cmd if isinstance(cmd, str) else json_dumps(cmd)
                        facts.append(self._fact("composer_script", str(script_name), str(cmd_val)[:300], 1, script=str(script_name)))
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as parse_exc:
                logger.debug("Composer package metadata skipped (%s)", type(parse_exc).__name__)

        return facts

    def _extract_source_facts(self, path: str, text: str) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        lang = self._language(path)
        if lang == "python":
            try:
                ast.parse(text)
            except SyntaxError as exc:
                facts.append(self._fact("syntax_error", "python", str(exc.msg), int(exc.lineno or 1)))
            facts.extend(self._extract_python_ast(text))
        elif lang in {"json", "toml", "xml"}:
            try:
                if lang == "json": data = json.loads(text)
                elif lang == "toml": data = tomllib.loads(text)
                else:
                    root = ET.fromstring(text)
                    data = {"xml_tags": list(dict.fromkeys(node.tag.split("}")[-1] for node in root.iter()))[:200]}
                for key in self._flatten_config(data)[:200]:
                    facts.append(self._fact("config_key", key, key, 1))
                if lang == "json" and isinstance(data, dict) and ("openapi" in data or "swagger" in data) and isinstance(data.get("paths"), dict):
                    for route, operations in list(data.get("paths", {}).items())[:500]:
                        if not isinstance(operations, dict):
                            continue
                        for method in operations:
                            if str(method).lower() in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                                facts.append(self._fact("route", str(route), str(method).upper(), 1, method=str(method).upper(), source="openapi-json"))
            except Exception as exc:
                facts.append(self._fact("syntax_error", lang, str(exc)[:300], 1))

        # ── Language-specific analyzers ──────────────────────────────────────────
        ext = Path(path).suffix.lower()

        # Unity / C# analyzer
        if ext == ".cs":
            UNITY_LIFECYCLES = _SOURCE_UNITY_LIFECYCLES
            for line_no, line in enumerate(text.splitlines(), 1):
                m = UNITY_LIFECYCLES.search(line)
                if m:
                    facts.append(self._fact("unity_lifecycle", m.group(1), line.strip()[:200], line_no))
                if "[SerializeField]" in line or "[SerializeField(" in line:
                    facts.append(self._fact("unity_serialize_field", "SerializeField", line.strip()[:200], line_no))
                if "MonoBehaviour" in line:
                    facts.append(self._fact("unity_monobehaviour", "MonoBehaviour", line.strip()[:200], line_no))
                if "ScriptableObject" in line:
                    facts.append(self._fact("unity_scriptable_object", "ScriptableObject", line.strip()[:200], line_no))
                if "[CustomEditor(" in line:
                    facts.append(self._fact("unity_custom_editor", "CustomEditor", line.strip()[:200], line_no))

        # JavaScript / TypeScript / Vue / Svelte analyzer
        if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"):
            REACT_COMPONENT = _SOURCE_REACT_COMPONENT
            REACT_HOOK = _SOURCE_REACT_HOOK
            REACT_ROUTE = _SOURCE_REACT_ROUTE
            TS_DECLARATION = _SOURCE_TS_DECLARATION
            NEXT_ROUTE_HANDLER = _SOURCE_NEXT_ROUTE_HANDLER
            NEST_DECORATOR = _SOURCE_NEST_DECORATOR
            TEST_SUITE_BLOCK = _SOURCE_TEST_SUITE_BLOCK
            for line_no, line in enumerate(text.splitlines(), 1):
                cm = REACT_COMPONENT.search(line)
                if cm and ("React" in text or "jsx" in path or "tsx" in path or "useState" in text or "useEffect" in text):
                    facts.append(self._fact("react_component", cm.group(1), line.strip()[:200], line_no))
                hm = REACT_HOOK.search(line)
                if hm:
                    facts.append(self._fact("react_hook", hm.group(1), line.strip()[:200], line_no))
                rm = REACT_ROUTE.search(line)
                if rm:
                    facts.append(self._fact("route", rm.group(1), "ANY", line_no))
                tm = TS_DECLARATION.search(line)
                if tm:
                    kind = tm.group(1)
                    symbol_name = tm.group(2)
                    facts.append(self._fact(f"ts_{kind}", symbol_name, line.strip()[:200], line_no))
                nm = NEXT_ROUTE_HANDLER.search(line)
                if nm:
                    method = nm.group(1).upper()
                    route_path = "/" + Path(path.replace("\\", "/")).as_posix().lstrip("/")
                    facts.append(self._fact("route", route_path, method, line_no, method=method, source="next-route-handler"))
                nest_m = NEST_DECORATOR.search(line)
                if nest_m:
                    dec_type = nest_m.group(1)
                    dec_val = nest_m.group(2) or ""
                    if dec_type in {"Get", "Post", "Put", "Patch", "Delete"}:
                        facts.append(self._fact("route", dec_val or "/", dec_type.upper(), line_no, method=dec_type.upper(), source="nestjs"))
                    else:
                        facts.append(self._fact("nest_decorator", dec_type, dec_val, line_no))
                tbm = TEST_SUITE_BLOCK.search(line)
                if tbm:
                    block_type = tbm.group(1)
                    test_title = tbm.group(2)
                    facts.append(self._fact(f"test_{block_type}", test_title, line.strip()[:200], line_no))

        # HTML & template analyzer
        if ext in (".html", ".htm") or path.lower().endswith(".blade.php") or ext == ".ctp":
            FORM_TAG = _SOURCE_FORM_TAG
            ACTION_ATTR = _SOURCE_ACTION_ATTR
            METHOD_ATTR = _SOURCE_METHOD_ATTR
            SCRIPT_SRC = _SOURCE_SCRIPT_SRC
            LINK_CSS = _SOURCE_LINK_CSS
            ELEM_ID = _SOURCE_ELEM_ID
            WEB_COMPONENT = _SOURCE_WEB_COMPONENT
            BLADE_DIRECTIVE = _SOURCE_BLADE_DIRECTIVE

            for line_no, line in enumerate(text.splitlines(), 1):
                for fm in FORM_TAG.finditer(line):
                    attrs = fm.group(1)
                    am = ACTION_ATTR.search(attrs)
                    mm = METHOD_ATTR.search(attrs)
                    r_path = am.group(1) if am else "/"
                    m_method = (mm.group(1) if mm else "GET").upper()
                    facts.append(self._fact("html_form", r_path, m_method, line_no, method=m_method, action=r_path))
                    facts.append(self._fact("route", r_path, m_method, line_no, method=m_method, source="html-form"))
                sm = SCRIPT_SRC.search(line)
                if sm:
                    facts.append(self._fact("html_script", sm.group(1), sm.group(1), line_no))
                lm = LINK_CSS.search(line)
                if lm and ("stylesheet" in line.lower() or ".css" in lm.group(1).lower()):
                    facts.append(self._fact("html_stylesheet", lm.group(1), lm.group(1), line_no))
                for id_m in ELEM_ID.finditer(line):
                    facts.append(self._fact("html_id", id_m.group(1), id_m.group(1), line_no))
                for wc_m in WEB_COMPONENT.finditer(line):
                    facts.append(self._fact("web_component", wc_m.group(1), wc_m.group(1), line_no))
                for bm in BLADE_DIRECTIVE.finditer(line):
                    directive, arg = bm.group(1).lower(), bm.group(2)
                    facts.append(self._fact(f"blade_{directive}", arg, arg, line_no))

        # CSS / SCSS / LESS analyzer
        if ext in (".css", ".scss", ".sass", ".less"):
            CSS_VAR = _SOURCE_CSS_VAR
            KEYFRAMES = _SOURCE_KEYFRAMES
            MEDIA_QUERY = _SOURCE_MEDIA_QUERY
            CSS_CLASS = _SOURCE_CSS_CLASS

            for line_no, line in enumerate(text.splitlines(), 1):
                vm = CSS_VAR.search(line)
                if vm:
                    facts.append(self._fact("css_variable", f"--{vm.group(1)}", vm.group(2).strip(), line_no))
                km = KEYFRAMES.search(line)
                if km:
                    facts.append(self._fact("css_keyframes", km.group(1), km.group(1), line_no))
                mm = MEDIA_QUERY.search(line)
                if mm:
                    facts.append(self._fact("css_media_query", mm.group(1).strip()[:100], mm.group(1).strip()[:100], line_no))
                cm = CSS_CLASS.search(line)
                if cm:
                    facts.append(self._fact("css_class", cm.group(1), cm.group(1), line_no))

        # PHP & CakePHP analyzer
        if ext in (".php", ".ctp"):
            PHP_DEF = _SOURCE_PHP_DEF
            PHP_FUNC = _SOURCE_PHP_FUNC
            PHP_NS = _SOURCE_PHP_NS
            PHP_ROUTE_ATTR = _SOURCE_PHP_ROUTE_ATTR
            PHP_ATTR = _SOURCE_PHP_ATTR
            WP_HOOK = _SOURCE_WP_HOOK
            LARAVEL_RESOURCE = _SOURCE_LARAVEL_RESOURCE
            # Laravel specifics
            ELOQUENT_TABLE = _SOURCE_ELOQUENT_TABLE
            ELOQUENT_FILLABLE = _SOURCE_ELOQUENT_FILLABLE
            ELOQUENT_REL = _SOURCE_ELOQUENT_REL
            SCHEMA_CREATE = _SOURCE_SCHEMA_CREATE
            MIGRATION_COL = _SOURCE_MIGRATION_COL
            ARTISAN_CMD = _SOURCE_ARTISAN_CMD
            FORM_REQ = _SOURCE_FORM_REQ

            # CakePHP specifics
            CAKE_ROUTE = _SOURCE_CAKE_ROUTE
            CAKE_RESOURCES = _SOURCE_CAKE_RESOURCES
            CAKE_TABLE = _SOURCE_CAKE_TABLE
            CAKE_ENTITY = _SOURCE_CAKE_ENTITY
            CAKE_ASSOC = _SOURCE_CAKE_ASSOC
            CAKE_MIGRATION = _SOURCE_CAKE_MIGRATION

            current_ns = ""
            for line_no, line in enumerate(text.splitlines(), 1):
                ns_m = PHP_NS.search(line)
                if ns_m:
                    current_ns = ns_m.group(1).rstrip(";")
                    facts.append(self._fact("php_namespace", current_ns, current_ns, line_no))
                    continue

                def_m = PHP_DEF.search(line)
                if def_m:
                    kind = def_m.group(1)
                    name = def_m.group(2)
                    fqn = f"{current_ns}\\{name}" if current_ns else name
                    facts.append(self._fact(f"php_{kind}", name, fqn, line_no, namespace=current_ns, fqn=fqn))

                fn_m = PHP_FUNC.search(line)
                if fn_m:
                    fn_name = fn_m.group(1)
                    if fn_name.lower() not in {"__construct", "__destruct", "__get", "__set"}:
                        facts.append(self._fact("php_function", fn_name, line.strip()[:200], line_no))

                attr_m = PHP_ATTR.search(line)
                if attr_m:
                    attr_val = attr_m.group(1)
                    facts.append(self._fact("php_attribute", attr_val, attr_val, line_no))

                route_attr_m = PHP_ROUTE_ATTR.search(line)
                if route_attr_m:
                    route_path = route_attr_m.group(1) or "/"
                    methods_str = route_attr_m.group(2) or "ANY"
                    for method in methods_str.replace("'", "").replace('"', "").split(","):
                        m_clean = method.strip().upper() or "ANY"
                        facts.append(self._fact("route", route_path, m_clean, line_no, method=m_clean, source="php-attribute"))

                lr_m = LARAVEL_RESOURCE.search(line)
                if lr_m:
                    res_path = lr_m.group(1)
                    controller = lr_m.group(2)
                    facts.append(self._fact("route", f"/{res_path.lstrip('/')}", "RESOURCE", line_no, controller=controller, source="laravel-resource"))

                wp_m = WP_HOOK.search(line)
                if wp_m:
                    hook_kind = wp_m.group(1)
                    hook_name = wp_m.group(2)
                    facts.append(self._fact("wordpress_hook", hook_name, hook_kind, line_no, hook=hook_name, hook_type=hook_kind))

                # Laravel facts
                tbl_m = ELOQUENT_TABLE.search(line)
                if tbl_m:
                    facts.append(self._fact("eloquent_table", tbl_m.group(1), tbl_m.group(1), line_no))
                fill_m = ELOQUENT_FILLABLE.search(line)
                if fill_m:
                    cols = [c.strip().strip("'\"") for c in fill_m.group(1).split(",") if c.strip().strip("'\"")]
                    for col in cols:
                        facts.append(self._fact("eloquent_fillable", col, col, line_no))
                rel_m = ELOQUENT_REL.search(line)
                if rel_m:
                    facts.append(self._fact("eloquent_relation", rel_m.group(2).split("::")[0], rel_m.group(1), line_no, relation_type=rel_m.group(1)))
                sc_m = SCHEMA_CREATE.search(line)
                if sc_m:
                    facts.append(self._fact("db_table", sc_m.group(1), sc_m.group(1), line_no, source="laravel-migration"))
                col_m = MIGRATION_COL.search(line)
                if col_m:
                    c_type = col_m.group(1)
                    c_name = col_m.group(2) or c_type
                    facts.append(self._fact("db_column", c_name, c_type, line_no, col_type=c_type))
                art_m = ARTISAN_CMD.search(line)
                if art_m:
                    cmd_name = art_m.group(1).split()[0]
                    facts.append(self._fact("artisan_command", cmd_name, art_m.group(1), line_no))
                freq_m = FORM_REQ.search(line)
                if freq_m:
                    facts.append(self._fact("form_request", freq_m.group(1), freq_m.group(1), line_no))

                # CakePHP facts
                cr_m = CAKE_ROUTE.search(line)
                if cr_m:
                    facts.append(self._fact("route", cr_m.group(1), "ANY", line_no, source="cakephp"))
                cres_m = CAKE_RESOURCES.search(line)
                if cres_m:
                    facts.append(self._fact("route", f"/{cres_m.group(1).lstrip('/')}", "RESOURCE", line_no, source="cakephp-resource"))
                ctbl_m = CAKE_TABLE.search(line)
                if ctbl_m:
                    facts.append(self._fact("cake_table", ctbl_m.group(1), ctbl_m.group(1), line_no))
                cent_m = CAKE_ENTITY.search(line)
                if cent_m:
                    facts.append(self._fact("cake_entity", cent_m.group(1), cent_m.group(1), line_no))
                cassoc_m = CAKE_ASSOC.search(line)
                if cassoc_m:
                    facts.append(self._fact("cake_association", cassoc_m.group(2), cassoc_m.group(1), line_no, association_type=cassoc_m.group(1)))
                cmig_m = CAKE_MIGRATION.search(line)
                if cmig_m:
                    facts.append(self._fact("db_table", cmig_m.group(1), cmig_m.group(1), line_no, source="cakephp-migration"))

        # Python: decorators, dataclasses, async flows
        if ext == ".py":
            DECORATOR_RE = _SOURCE_DECORATOR_RE
            ASYNC_DEF_RE = _SOURCE_ASYNC_DEF_RE
            DATACLASS_RE = _SOURCE_DATACLASS_RE
            for m in DECORATOR_RE.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                facts.append(self._fact("python_decorator", m.group(1), m.group(0), line_no))
            for m in ASYNC_DEF_RE.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                facts.append(self._fact("async_function", m.group(1), m.group(0), line_no))
            if DATACLASS_RE.search(text):
                facts.append(self._fact("python_dataclass", "dataclass", path, 1))

        # ── Security / secret scanner ─────────────────────────────────────────────
        SECRET_RE = _SOURCE_SECRET_RE
        HARDCODED_IP = _SOURCE_HARDCODED_IP
        for line_no, line in enumerate(text.splitlines(), 1):
            sm = SECRET_RE.search(line)
            if sm:
                # Never store the actual secret value — only flag the location
                facts.append(self._fact("security_hardcoded_secret", "REDACTED", f"line {line_no}: potential secret detected", line_no))
            if HARDCODED_IP.search(line) and "127.0.0.1" not in line and "localhost" not in line:
                facts.append(self._fact("security_hardcoded_ip", "hardcoded_ip", line.strip()[:200], line_no))
            # Merge conflict markers
            if line.startswith("<<<<<<< ") or line.startswith(">>>>>>> ") or line == "=======":
                facts.append(self._fact("merge_conflict", "git_conflict_marker", line.strip()[:80], line_no))

        # ── Test-to-production mapping ────────────────────────────────────────────
        if self._is_test(path):
            # Extract names of classes/functions being tested from import statements and class names
            IMPORT_FROM = _SOURCE_IMPORT_FROM
            TESTED_CLASS = _SOURCE_TESTED_CLASS
            PHP_TESTED_CLASS = _SOURCE_PHP_TESTED_CLASS
            PHP_USE = _SOURCE_PHP_USE
            JS_IMPORT = _SOURCE_JS_IMPORT
            for m in IMPORT_FROM.finditer(text):
                module = m.group(1) or m.group(3) or ""
                if module and not module.startswith("test") and "mock" not in module.lower():
                    facts.append(self._fact("tests_module", module, path, 1))
                imported_symbols = m.group(2)
                if imported_symbols:
                    for sym in imported_symbols.split(","):
                        s = sym.strip()
                        if s and not s.startswith("test"):
                            facts.append(self._fact("tests_symbol", s, path, 1))
            for m in TESTED_CLASS.finditer(text):
                facts.append(self._fact("tests_class", m.group(1), path, 1))
            for m in PHP_TESTED_CLASS.finditer(text):
                facts.append(self._fact("tests_class", m.group(1), path, 1))
            for m in PHP_USE.finditer(text):
                use_target = m.group(1).split("\\")[-1]
                if use_target and not use_target.endswith("Test") and not use_target.startswith("Test"):
                    facts.append(self._fact("tests_symbol", use_target, path, 1))
            for m in JS_IMPORT.finditer(text):
                named = m.group(1)
                default_sym = m.group(2)
                import_src = m.group(3)
                if named:
                    for s in named.split(","):
                        clean_s = s.strip().split(" as ")[0].strip()
                        if clean_s and not clean_s.startswith("test"):
                            facts.append(self._fact("tests_symbol", clean_s, path, 1))
                if default_sym and not default_sym.startswith("test"):
                    facts.append(self._fact("tests_symbol", default_sym, path, 1))
                if import_src and not import_src.startswith("test"):
                    facts.append(self._fact("tests_module", import_src, path, 1))

        # ── General line-by-line patterns ────────────────────────────────────────
        for line_no, line in enumerate(text.splitlines(), 1):
            for _, pattern in ROUTE_PATTERNS:
                m = pattern.search(line)
                if not m:
                    continue
                groups = m.groups()
                method, route = "ANY", ""
                if len(groups) >= 2:
                    method, route = str(groups[0]).upper(), str(groups[1])
                elif groups:
                    route = str(groups[0])
                    decorator = m.group(0).lower()
                    method = next((x.upper() for x in ("get", "post", "put", "patch", "delete") if x in decorator), "ANY")
                facts.append(self._fact("route", route, method, line_no, method=method))
            for pattern in ENV_PATTERNS:
                for m in pattern.finditer(line):
                    facts.append(self._fact("env", m.group(1), m.group(1), line_no))
            for pattern in CONFIG_PATTERNS:
                for m in pattern.finditer(line):
                    facts.append(self._fact("config", m.group(1), m.group(1), line_no))
            todo = TODO_RE.search(line)
            if todo:
                facts.append(self._fact("todo", todo.group(1).upper(), todo.group(2).strip()[:300], line_no))
            if SQL_RE.search(line):
                facts.append(self._fact("database", "sql", line.strip()[:300], line_no))
                for pattern in (
                    _SOURCE_TABLE_INSERT_I,
                ):
                    for sm in pattern.finditer(line):
                        facts.append(self._fact("db_table", sm.group(1), sm.group(1), line_no, source="sql"))
            conc = CONCURRENCY_RE.search(line)
            if conc:
                facts.append(self._fact("concurrency", conc.group(1).lower(), line.strip()[:300], line_no))
            sec = SECURITY_RE.search(line)
            if sec:
                facts.append(self._fact("security", sec.group(1).lower(), line.strip()[:300], line_no))
        facts.extend(self._extract_infra_facts(path, text))
        if self._is_test(path):
            facts.append(self._fact("test_file", Path(path).name, path, 1))
        low_name = Path(path).name.lower()
        if low_name in {"main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts", "program.cs", "main.go", "main.rs"}:
            facts.append(self._fact("entrypoint_file", Path(path).name, path, 1))
        return facts


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
        candidates = paths or [str(p.relative_to(base)).replace("\\", "/") for p in self.repo_tools.iter_files(str(base))]
        if limit > 0:
            candidates = candidates[:limit]
        updated = cached = failed = 0
        for path in candidates:
            try:
                result = self.update_file(str(base), path)
                cached += int(bool(result.get("cached")))
                updated += int(bool(result.get("success")) and not result.get("cached"))
            except Exception:
                failed += 1
        self.prune(str(base), candidates if paths is None else [str(p.relative_to(base)).replace("\\", "/") for p in self.repo_tools.iter_files(str(base))])
        self.refresh_manifests(str(base))
        return {"success": True, "root": str(base), "updated": updated, "cached": cached, "failed": failed, "files": len(candidates)}

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
            if name in {"package.json", "composer.json"}:
                data = json.loads(raw.decode("utf-8", errors="replace"))
                if name == "package.json":
                    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                        obj = data.get(section, {}) if isinstance(data, dict) else {}
                        if isinstance(obj, dict):
                            deps.extend((str(k), str(v), section) for k, v in obj.items())
                    obj = data.get("scripts", {}) if isinstance(data, dict) else {}
                    if isinstance(obj, dict):
                        scripts.extend((str(k), str(v), self._purpose(str(k))) for k, v in obj.items())
                else:
                    for section in ("require", "require-dev"):
                        obj = data.get(section, {}) if isinstance(data, dict) else {}
                        if isinstance(obj, dict):
                            deps.extend((str(k), str(v), section) for k, v in obj.items())
                    obj = data.get("scripts", {}) if isinstance(data, dict) else {}
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            cmd = v if isinstance(v, str) else " && ".join(str(x) for x in v) if isinstance(v, list) else str(v)
                            scripts.append((str(k), cmd, self._purpose(str(k))))
            elif name in {"deno.json", "deno.jsonc"}:
                text = raw.decode("utf-8", errors="replace")
                if name.endswith(".jsonc"):
                    # Conservative JSONC cleanup sufficient for top-level imports/tasks.
                    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
                    text = re.sub(r"(^|\s)//.*$", r"\1", text, flags=re.M)
                    text = re.sub(r",\s*([}\]])", r"\1", text)
                data = json.loads(text)
                if isinstance(data, dict):
                    imports = data.get("imports", {})
                    if isinstance(imports, dict):
                        deps.extend((str(k), str(v), "deno-import") for k, v in imports.items())
                    tasks = data.get("tasks", {})
                    if isinstance(tasks, dict):
                        scripts.extend((str(k), str(v), self._purpose(str(k))) for k, v in tasks.items())
            elif name == "package-lock.json":
                data = json.loads(raw.decode("utf-8", errors="replace"))
                packages = data.get("packages", {}) if isinstance(data, dict) else {}
                if isinstance(packages, dict) and packages:
                    for key, meta in packages.items():
                        if not key.startswith("node_modules/") or not isinstance(meta, dict):
                            continue
                        pkg = key[len("node_modules/"):]
                        if pkg:
                            deps.append((pkg, str(meta.get("version", "")), "lock"))
                elif isinstance(data, dict) and isinstance(data.get("dependencies"), dict):
                    for pkg, meta in data["dependencies"].items():
                        version = str(meta.get("version", "")) if isinstance(meta, dict) else ""
                        deps.append((str(pkg), version, "lock"))
            elif name == "pnpm-lock.yaml":
                text = raw.decode("utf-8", errors="replace")
                # pnpm v6-v9 lock keys are deterministic enough to recover package + version
                # without a YAML dependency. We intentionally ignore peer suffix metadata.
                for line in text.splitlines():
                    m = re.match(r"^\s{2,}[\"']?/?((?:@[^/\s:]+/)?[^@:/\s\"']+)@([^:\s(\"']+)(?:\([^)]*\))?[\"']?\s*:\s*$", line)
                    if m:
                        deps.append((m.group(1), m.group(2), "lock"))
            elif name == "packages.lock.json":
                data = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    for tfm, items in data.get("dependencies", {}).items() if isinstance(data.get("dependencies", {}), dict) else []:
                        if not isinstance(items, dict): continue
                        for pkg, meta in items.items():
                            version = str(meta.get("resolved") or meta.get("requested") or "") if isinstance(meta, dict) else ""
                            deps.append((str(pkg), version, f"nuget-lock:{tfm}"))
            elif name in {"uv.lock"}:
                data = tomllib.loads(raw.decode("utf-8", errors="replace"))
                packages = data.get("package", []) if isinstance(data, dict) else []
                for meta in packages if isinstance(packages, list) else []:
                    if isinstance(meta, dict) and meta.get("name"):
                        deps.append((str(meta["name"]), str(meta.get("version", "")), "lock"))
            elif name == "global.json":
                data = json.loads(raw.decode("utf-8", errors="replace"))
                sdk = data.get("sdk", {}) if isinstance(data, dict) else {}
                if isinstance(sdk, dict) and sdk.get("version"):
                    deps.append(("dotnet-sdk", str(sdk.get("version")), "toolchain"))
            elif name == "composer.lock":
                data = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    for section in ("packages", "packages-dev"):
                        for meta in data.get(section, []) if isinstance(data.get(section, []), list) else []:
                            if isinstance(meta, dict) and meta.get("name"):
                                deps.append((str(meta["name"]), str(meta.get("version", "")), "lock-dev" if section.endswith("dev") else "lock"))
            elif name in {"poetry.lock", "cargo.lock"}:
                data = tomllib.loads(raw.decode("utf-8", errors="replace"))
                packages = data.get("package", []) if isinstance(data, dict) else []
                for meta in packages if isinstance(packages, list) else []:
                    if isinstance(meta, dict) and meta.get("name"):
                        deps.append((str(meta["name"]), str(meta.get("version", "")), "lock"))
            elif name == "go.sum":
                for line in raw.decode("utf-8", errors="replace").splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and not parts[1].endswith("/go.mod"):
                        deps.append((parts[0], parts[1], "sum"))
            elif name in {"yarn.lock", "gemfile.lock"}:
                text = raw.decode("utf-8", errors="replace")
                if name == "yarn.lock":
                    current: list[str] = []
                    for line in text.splitlines():
                        if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
                            current = [x.strip().strip('"\'') for x in line[:-1].split(",")]
                        elif current and line.strip().startswith("version "):
                            version = line.strip()[len("version "):].strip().strip('"\'')
                            for spec in current[:8]:
                                pkg = spec
                                if spec.startswith("@"):
                                    slash = spec.find("/")
                                    at = spec.find("@", slash + 1) if slash >= 0 else -1
                                    if at > 0: pkg = spec[:at]
                                elif "@" in spec:
                                    pkg = spec.split("@", 1)[0]
                                if pkg: deps.append((pkg, version, "lock"))
                            current = []
                else:
                    in_specs = False
                    for line in text.splitlines():
                        if line.strip() == "specs:":
                            in_specs = True; continue
                        if in_specs and line and not line.startswith(" "):
                            in_specs = False
                        if in_specs:
                            m = re.match(r"^\s{4}([^\s(]+)\s+\(([^)]+)\)", line)
                            if m: deps.append((m.group(1), m.group(2), "lock"))
            elif name in {"build.gradle", "build.gradle.kts"}:
                text = raw.decode("utf-8", errors="replace")
                dep_re = _MANIFEST_IMPLEMENTATION
                for line in text.splitlines():
                    m = dep_re.match(line)
                    if m:
                        coord = m.group(2); parts = coord.split(":")
                        pkg = ":".join(parts[:2]) if len(parts) >= 2 else coord
                        version = parts[2] if len(parts) >= 3 else ""
                        deps.append((pkg, version, m.group(1)))
            elif name in {"gradle/libs.versions.toml", "libs.versions.toml"}:
                data = tomllib.loads(raw.decode("utf-8", errors="replace"))
                versions = data.get("versions", {}) if isinstance(data, dict) else {}
                libraries = data.get("libraries", {}) if isinstance(data, dict) else {}
                if isinstance(libraries, dict):
                    for alias, meta in libraries.items():
                        if isinstance(meta, str):
                            deps.append((str(alias), meta, "gradle-catalog")); continue
                        if not isinstance(meta, dict): continue
                        module = str(meta.get("module") or "")
                        if not module and meta.get("group") and meta.get("name"):
                            module = f"{meta['group']}:{meta['name']}"
                        version = str(meta.get("version") or "")
                        ref = meta.get("version", {}).get("ref") if isinstance(meta.get("version"), dict) else meta.get("version.ref")
                        if ref and isinstance(versions, dict): version = str(versions.get(str(ref), ref))
                        if module: deps.append((module, version, "gradle-catalog"))
            elif name.startswith("requirements") and name.endswith((".txt", ".in")):
                text = raw.decode("utf-8", errors="replace")
                for line in text.splitlines():
                    item = line.strip()
                    if not item or item.startswith("#") or item.startswith(("-r ", "--requirement", "-c ", "--constraint")):
                        continue
                    item = item.split(" #", 1)[0].strip()
                    token = re.split(r"[<>=!~ ;\[]", item, maxsplit=1)[0].strip()
                    if token and not token.startswith(("git+", "http://", "https://", "-e")):
                        deps.append((token, item, "requirements"))
            elif name == "pipfile":
                data = tomllib.loads(raw.decode("utf-8", errors="replace"))
                for section in ("packages", "dev-packages"):
                    obj = data.get(section, {}) if isinstance(data, dict) else {}
                    if isinstance(obj, dict):
                        deps.extend((str(k), str(v), section) for k, v in obj.items())
                obj = data.get("scripts", {}) if isinstance(data, dict) else {}
                if isinstance(obj, dict):
                    scripts.extend((str(k), str(v), self._purpose(str(k))) for k, v in obj.items())
            elif name == "gemfile":
                text = raw.decode("utf-8", errors="replace")
                gem_re = _MANIFEST_IDENTIFIER
                for line in text.splitlines():
                    m = gem_re.match(line)
                    if m:
                        deps.append((m.group(1), m.group(2) or "", "gem"))
            elif name in {"makefile", "gnumakefile", "justfile"}:
                text = raw.decode("utf-8", errors="replace")
                target_re = _MANIFEST_IDENTIFIER_REGEX if name != "justfile" else _MANIFEST_IDENTIFIER_REGEX_PATTERN
                runner = "just" if name == "justfile" else "make"
                for line in text.splitlines():
                    m = target_re.match(line)
                    if m and not m.group(1).startswith("."):
                        target = m.group(1)
                        scripts.append((target, f"{runner} {target}", self._purpose(target)))
            elif name in {"pyproject.toml", "cargo.toml"}:
                data = tomllib.loads(raw.decode("utf-8", errors="replace"))
                if name == "pyproject.toml":
                    project = data.get("project", {}) if isinstance(data, dict) else {}
                    for item in project.get("dependencies", []) if isinstance(project, dict) else []:
                        token = re.split(r"[<>=!~ ;\[]", str(item), maxsplit=1)[0]
                        deps.append((token, str(item), "project"))
                    optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
                    if isinstance(optional, dict):
                        for group, items in optional.items():
                            for item in items if isinstance(items, list) else []:
                                token = re.split(r"[<>=!~ ;\[]", str(item), maxsplit=1)[0]
                                deps.append((token, str(item), f"optional:{group}"))
                    tool = data.get("tool", {}) if isinstance(data, dict) else {}
                    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
                    pobj = poetry.get("dependencies", {}) if isinstance(poetry, dict) else {}
                    if isinstance(pobj, dict):
                        deps.extend((str(k), str(v), "poetry") for k, v in pobj.items() if str(k).lower() != "python")
                    project_scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
                    if isinstance(project_scripts, dict):
                        scripts.extend((str(k), str(v), self._purpose(str(k))) for k, v in project_scripts.items())
                    poetry_scripts = poetry.get("scripts", {}) if isinstance(poetry, dict) else {}
                    if isinstance(poetry_scripts, dict):
                        scripts.extend((str(k), str(v), self._purpose(str(k))) for k, v in poetry_scripts.items())
                else:
                    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
                        obj = data.get(section, {}) if isinstance(data, dict) else {}
                        if isinstance(obj, dict):
                            deps.extend((str(k), str(v), section) for k, v in obj.items())
            elif name == "go.mod":
                text = raw.decode("utf-8", errors="replace")
                in_require = False
                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("require ("):
                        in_require = True; continue
                    if in_require and s == ")":
                        in_require = False; continue
                    if s.startswith("require "):
                        s = s[len("require "):].strip()
                    elif not in_require:
                        continue
                    parts = s.split()
                    if len(parts) >= 2:
                        deps.append((parts[0], parts[1], "require"))
            elif name == "go.work":
                text = raw.decode("utf-8", errors="replace")
                in_use = False
                for line in text.splitlines():
                    item = line.strip()
                    if item.startswith("use ("): in_use = True; continue
                    if in_use and item == ")": in_use = False; continue
                    if item.startswith("use "): item = item[4:].strip()
                    elif not in_use: continue
                    if item and not item.startswith("//"):
                        deps.append((item, "", "workspace-module"))
            elif path.suffix.lower() in {".csproj", ".fsproj", ".vbproj"} or name in {"directory.packages.props", "directory.build.props", "directory.build.targets"}:
                root = ET.fromstring(raw)
                for node in root.iter():
                    tag = node.tag.split("}")[-1]
                    if tag in {"PackageReference", "PackageVersion"}:
                        pkg = node.attrib.get("Include") or node.attrib.get("Update") or ""
                        version = node.attrib.get("Version") or next((c.text or "" for c in node if c.tag.split("}")[-1] == "Version"), "")
                        if pkg:
                            deps.append((pkg, version, tag))
            elif name == "pom.xml":
                root = ET.fromstring(raw)
                for dep in [x for x in root.iter() if x.tag.split("}")[-1] == "dependency"]:
                    vals = {c.tag.split("}")[-1]: (c.text or "").strip() for c in dep}
                    artifact = vals.get("artifactId", "")
                    group = vals.get("groupId", "")
                    if artifact:
                        deps.append((f"{group}:{artifact}" if group else artifact, vals.get("version", ""), vals.get("scope", "compile")))
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
        names = {
            "package.json", "package-lock.json", "pnpm-lock.yaml", "deno.json", "deno.jsonc",
            "composer.json", "composer.lock", "pyproject.toml", "poetry.lock", "uv.lock",
            "cargo.toml", "cargo.lock", "go.mod", "go.sum", "go.work", "pom.xml", "pipfile", "gemfile", "gemfile.lock",
            "yarn.lock", "build.gradle", "build.gradle.kts", "libs.versions.toml", "makefile", "gnumakefile", "justfile",
            "packages.lock.json", "global.json", "directory.packages.props", "directory.build.props", "directory.build.targets"
        }
        suffixes = {".csproj", ".fsproj", ".vbproj"}
        raw = self.repo_tools._git_files(base)
        if raw is None:
            raw = []
            max_files = int(getattr(self.repo_tools, "max_files", 8000))
            ignore = set(getattr(self.repo_tools, "ignore_dirs", set()))
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d not in ignore]
                for filename in filenames:
                    raw.append(Path(dirpath) / filename)
                    if len(raw) >= max_files:
                        break
                if len(raw) >= max_files:
                    break
        found: list[Path] = []
        for path in raw:
            low_name = path.name.lower()
            if low_name in names or (low_name.startswith("requirements") and low_name.endswith((".txt", ".in"))) or path.suffix.lower() in suffixes:
                try:
                    if path.stat().st_size <= self.max_manifest_bytes:
                        found.append(path)
                except OSError:
                    continue
        return sorted(found, key=lambda x: str(x).lower())

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
        low = query.lower()
        rules = [
            ("callers", ("caller", "callers", "called by", "who calls")),
            ("references", ("reference", "references", "usages", "used by")),
            ("routes", ("route", "routes", "endpoint", "api path", "controller")),
            ("commands", ("command", "commands", "build command", "test command", "lint command", "how to run", "build commands", "lint commands")),
            ("tests", ("test", "tests", "spec", "phpunit", "pytest", "jest", "vitest")),
            ("dependencies", ("dependency", "dependencies", "package", "packages", "composer", "npm", "cargo", "nuget")),
            ("infrastructure", ("docker", "container", "compose", "terraform", "kubernetes", "k8s", "helm", "deployment", "deploy", "github actions", "gitlab ci", "azure pipelines", "ci pipeline", "ci job", "ci jobs", "workflow", "port", "healthcheck", "protobuf", "grpc")),
            ("syntax", ("syntax", "parse error", "invalid json", "invalid toml", "invalid xml")),
            ("config", ("config", "configuration", "environment", " env ", "setting", "settings")),
            ("entrypoints", ("entrypoint", "entry point", "startup", "bootstrap", "main")),
            ("security", ("security", "auth", "authentication", "authorization", "permission", "jwt", "token")),
            ("concurrency", ("concurrency", "thread", "async", "queue", "lock", "race", "deadlock")),
            ("database", ("database", "sql", "query", "repository", "migration", "table")),
            ("todos", ("todo", "fixme", "hack", "xxx")),
            ("architecture", ("architecture", "structure", "modules", "components", "how project works")),
            ("symbols", ("symbol", "definition", "defined", "class", "function", "method")),
        ]
        for intent, needles in rules:
            if any(n in low for n in needles):
                return {"intent": intent, "confidence": 0.94}
        mutation = any(x in low for x in ("fix", "implement", "change", "modify", "refactor", "rewrite", "add", "remove", "patch", "update", "create", "delete"))
        if mutation:
            return {"intent": "implementation", "confidence": 0.88}
        return {"intent": "general", "confidence": 0.55}

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
        base = Path(root).resolve()
        validated: list[dict[str, Any]] = []
        for item in slices:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            start = item.get("start_line")
            end = item.get("end_line")
            digest = item.get("file_sha256")
            if (not isinstance(path, str) or not path
                    or not isinstance(start, int) or isinstance(start, bool) or start < 1
                    or not isinstance(end, int) or isinstance(end, bool) or end < start
                    or not isinstance(digest, str) or not digest):
                continue
            target = (base / path).resolve(strict=False)
            try:
                relative_path = target.relative_to(base).as_posix()
            except ValueError:
                continue
            validated.append({
                "path": relative_path,
                "start_line": start,
                "end_line": end,
                "file_sha256": digest,
                "symbol_complete": bool(item.get("symbol_complete", False)),
            })

        ordered = sorted(
            validated,
            key=lambda item: (
                item["path"], item["file_sha256"], item["start_line"], item["end_line"]
            ),
        )
        merged: list[dict[str, Any]] = []
        for current in ordered:
            previous = merged[-1] if merged else None
            if (previous is not None
                    and previous["path"] == current["path"]
                    and previous["file_sha256"] == current["file_sha256"]
                    and current["start_line"] <= previous["end_line"] + 2):
                previous["end_line"] = max(previous["end_line"], current["end_line"])
                previous["symbol_complete"] = (
                    previous["symbol_complete"] and current["symbol_complete"]
                )
            else:
                merged.append(dict(current))

        snapshots: dict[str, tuple[str, list[str]] | None] = {}
        result: list[dict[str, Any]] = []
        for item in merged:
            path = item["path"]
            if path not in snapshots:
                try:
                    snapshots[path] = self.repo_tools._read_snapshot(base / path)
                except OSError as read_exc:
                    logger.debug("Merged evidence source skipped (%s)", type(read_exc).__name__)
                    snapshots[path] = None
            snapshot = snapshots[path]
            if snapshot is None:
                continue
            digest, lines = snapshot
            start = item["start_line"]
            end = item["end_line"]
            if digest != item["file_sha256"] or not lines or end > len(lines):
                continue
            result.append({
                **item,
                "text": "\n".join(f"{line}: {lines[line - 1]}" for line in range(start, end + 1)),
                "deterministic": True,
            })
        return result

    def _exact_evidence(self, root: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.evidence is None or self.max_evidence <= 0:
            return []
        base = Path(root).resolve()
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        seen_ranges: set[tuple[str, int, int]] = set()
        snapshots: dict[str, tuple[str, list[str]] | None] = {}
        for row in rows:
            path = str(row.get("path", ""))
            if not path:
                continue
            line = max(1, int(row.get("line", 1) or 1))
            target = (base / path).resolve(strict=False)
            try:
                path = target.relative_to(base).as_posix()
            except ValueError:
                continue
            key = (path, line)
            if not path or key in seen:
                continue
            seen.add(key)
            if path not in snapshots:
                try:
                    snapshots[path] = self.repo_tools._read_snapshot(target)
                except OSError as read_exc:
                    logger.debug("Exact evidence source skipped (%s)", type(read_exc).__name__)
                    snapshots[path] = None
            snapshot = snapshots[path]
            if snapshot is None:
                continue
            digest, lines = snapshot
            if not lines or line > len(lines):
                continue
            start = max(1, line - 2)
            end = min(len(lines), line + 2)
            bounds = None
            bounds_reader = getattr(self.code_index, "symbol_bounds_at", None)
            if callable(bounds_reader):
                try:
                    bounds = bounds_reader(str(base), path, line, content_hash=digest)
                except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
                    bounds = None
            valid_bounds = (
                isinstance(bounds, tuple) and len(bounds) == 2
                and all(isinstance(value, int) and not isinstance(value, bool) for value in bounds)
            )
            if valid_bounds and 1 <= bounds[0] <= line <= bounds[1] <= len(lines):
                start, end = bounds
            else:
                bounds = None
            range_key = (path, start, end)
            if range_key in seen_ranges:
                continue
            seen_ranges.add(range_key)
            candidates.append({
                "path": path,
                "start_line": start,
                "end_line": end,
                "file_sha256": digest,
                "symbol_complete": bounds is not None,
            })
            if len(candidates) >= self.max_evidence:
                break

        items: list[dict[str, Any]] = []
        for item in self.merge_overlapping_slices(str(base), candidates):
            eid = self.evidence.put(str(base), item)
            if eid:
                item["evidence_id"] = eid
            item.pop("text", None)  # progressive disclosure at the API boundary
            items.append(item)
        return items

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
        intent_noise = {
            "routes": {"api", "route", "routes", "endpoint", "endpoints", "controller"},
            "tests": {"test", "tests", "spec", "specs", "phpunit", "pytest", "jest", "vitest"},
            "config": {"config", "configuration", "environment", "settings", "setting", "env"},
            "commands": {"command", "commands", "build", "lint", "test", "run", "validation"},
            "dependencies": {"dependency", "dependencies", "package", "packages", "composer", "npm", "cargo", "nuget"},
            "entrypoints": {"entrypoint", "entry", "point", "startup", "bootstrap", "main"},
            "syntax": {"syntax", "parse", "error", "invalid", "json", "toml", "xml"},
            "infrastructure": {"infrastructure", "docker", "container", "compose", "terraform", "kubernetes", "k8s", "helm", "deployment", "deploy", "ci", "pipeline", "job", "jobs", "workflow", "port", "ports", "healthcheck", "protobuf", "grpc"},
        }
        content_terms = [t for t in terms if t not in intent_noise.get(intent, set())]
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
        lines = text.splitlines()
        if not lines:
            return {"success": True, "text": "", "confidence": 1.0, "deterministic": True}
        budget_lines = max(12, int(target_tokens * 4 / 90))
        needles = ("error", "fatal", "exception", "traceback", "failed", "failure", "warning", "assert", "panic", "timeout", "segfault", "passed", "success")
        diagnostic = sum(1 for line in lines[:2000] if any(n in line.lower() for n in needles))
        repetitive = 1.0 - (len(set(lines[:5000])) / max(1, min(len(lines), 5000)))
        if diagnostic == 0 and repetitive < 0.18:
            return {"success": False, "confidence": 0.2, "reason": "narrative/non-diagnostic input"}
        selected: list[str] = []
        seen: Counter[str] = Counter()
        important_idx = [i for i, line in enumerate(lines) if any(n in line.lower() for n in needles)]
        indices: set[int] = set()
        for i in important_idx:
            indices.update(range(max(0, i - 1), min(len(lines), i + 2)))
        indices.update(range(min(6, len(lines))))
        indices.update(range(max(0, len(lines) - 6), len(lines)))
        for i in sorted(indices):
            line = lines[i]
            seen[line] += 1
            if seen[line] > 2:
                continue
            selected.append(f"{i+1}: {line}")
            if len(selected) >= budget_lines:
                break
        repeats = [(line, count) for line, count in Counter(lines).most_common(8) if count > 2]
        if repeats:
            selected.append("REPEATED: " + "; ".join(f"{count}x {line[:120]}" for line, count in repeats))
        confidence = min(0.98, 0.82 + min(0.12, diagnostic * 0.01) + min(0.04, repetitive * 0.08))
        return {"success": True, "text": "\n".join(selected), "confidence": round(confidence, 4), "deterministic": True, "original_lines": len(lines), "selected_lines": len(selected)}

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
        for item in ci.get("symbols", []) if isinstance(ci, dict) else []:
            name = str(item.get("name", ""))
            if name and name not in symbols and len(symbols) < 24:
                symbols.append(name)
        for item in ci.get("edges", []) if isinstance(ci, dict) else []:
            if str(item.get("kind")) == "imports":
                name = str(item.get("dst", ""))
                if name and name not in deps and len(deps) < 24:
                    deps.append(name)
        side_effects = []
        if kinds.get("database"): side_effects.append("database")
        if kinds.get("route"): side_effects.append("http-route")
        if kinds.get("env") or kinds.get("config"): side_effects.append("configuration")
        if kinds.get("concurrency"): side_effects.append("concurrency")
        if kinds.get("service") or kinds.get("container_base") or kinds.get("container_image"): side_effects.append("containers")
        if kinds.get("port"): side_effects.append("network-ports")
        if kinds.get("ci_job") or kinds.get("ci_action"): side_effects.append("ci")
        if kinds.get("terraform_resource") or kinds.get("terraform_module") or kinds.get("k8s_kind") or kinds.get("k8s_resource"): side_effects.append("infrastructure")
        if kinds.get("proto_service") or kinds.get("proto_rpc"): side_effects.append("rpc-api")
        risks = []
        if kinds.get("security"): risks.append("security-sensitive")
        if kinds.get("concurrency"): risks.append("concurrency-sensitive")
        if kinds.get("database") or kinds.get("db_table"): risks.append("data/persistence")
        if kinds.get("todo"): risks.append("todo/fixme")
        tests = [path] if is_test else []
        keywords = []
        call_names = [str(x.get("name", "")) for x in ci.get("references", [])[:20]] if isinstance(ci, dict) else []
        for group in (symbols, deps, call_names, kinds.get("route", []), kinds.get("env", []), kinds.get("config", []), kinds.get("service", []), kinds.get("terraform_resource", []), kinds.get("proto_service", [])):
            for item in group:
                for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", str(item)):
                    low = token.lower()
                    if low not in keywords:
                        keywords.append(low)
                    if len(keywords) >= 30: break
        name = Path(path).name
        purpose_bits = ["test" if is_test else "source", language]
        if kinds.get("route"): purpose_bits.append("HTTP routing")
        if kinds.get("entrypoint") or kinds.get("entrypoint_file"): purpose_bits.append("entry point")
        if kinds.get("database"): purpose_bits.append("data access")
        if kinds.get("config") or kinds.get("env"): purpose_bits.append("configuration")
        if kinds.get("service") or kinds.get("container_base"): purpose_bits.append("container infrastructure")
        if kinds.get("ci_job") or kinds.get("ci_action"): purpose_bits.append("CI workflow")
        if kinds.get("terraform_resource"): purpose_bits.append("infrastructure-as-code")
        if kinds.get("proto_service") or kinds.get("proto_rpc"): purpose_bits.append("RPC schema")
        purpose = f"{name}: " + ", ".join(purpose_bits)
        richness = len(symbols) * 2 + len(deps) + min(12, len(call_names)) + len(side_effects) * 2 + len(kinds.get("route", [])) * 2 + len(kinds.get("env", []))
        low_manifest = name.lower(); low_path = path.replace("\\", "/").lower()
        manifest_like = low_manifest in {
            "package.json", "package-lock.json", "composer.json", "composer.lock", "pyproject.toml", "poetry.lock",
            "cargo.toml", "cargo.lock", "go.mod", "go.sum", "pom.xml", "pipfile", "gemfile", "gemfile.lock", "yarn.lock",
            "build.gradle", "build.gradle.kts", "makefile", "gnumakefile", "justfile", "dockerfile", "containerfile",
            "compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml", ".env", ".env.example", ".env.sample"
        } or (low_manifest.startswith("requirements") and low_manifest.endswith(".txt")) or "/.github/workflows/" in f"/{low_path}" or Path(path).suffix.lower() in {".tf", ".tfvars", ".proto", ".ini", ".cfg", ".properties"}
        confidence = 0.97 if manifest_like else min(0.95, 0.64 + 0.035 * richness + (0.08 if is_test else 0.0))
        return {
            "success": True, "deterministic": True, "confidence": round(confidence, 4),
            "card": {
                "purpose": purpose, "symbols": symbols, "dependencies": deps, "side_effects": side_effects,
                "risks": risks, "tests": tests, "keywords": keywords,
            },
        }

    def module_card(self, root: str, module: str, file_cards: list[dict[str, Any]]) -> dict[str, Any]:
        """Synthesize a factual module card without an LLM.

        The input cards are already content-addressed. This reducer intentionally
        performs set/structure aggregation only; it does not infer behavioral claims.
        """
        paths = [str(x.get("path", "")) for x in file_cards if x.get("path")]
        dependencies: list[str] = []
        risks: list[str] = []
        validation: list[str] = []
        entry_points: list[str] = []
        side_effects: list[str] = []
        symbols = 0

        def add_unique(dst: list[str], value: Any, limit: int = 40) -> None:
            text = str(value).strip()
            if text and text not in dst and len(dst) < limit:
                dst.append(text)

        for item in file_cards:
            card = item.get("card", item) if isinstance(item, dict) else {}
            path = str(item.get("path", "")) if isinstance(item, dict) else ""
            syms = card.get("symbols", []) if isinstance(card, dict) else []
            symbols += len(syms or [])
            for dep in card.get("dependencies", []) if isinstance(card, dict) else []:
                add_unique(dependencies, dep)
            for risk in card.get("risks", []) if isinstance(card, dict) else []:
                add_unique(risks, risk)
            for test in card.get("tests", []) if isinstance(card, dict) else []:
                add_unique(validation, test)
            for side in card.get("side_effects", []) if isinstance(card, dict) else []:
                add_unique(side_effects, side)
            low = Path(path).name.lower()
            if low in {"main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts", "program.cs", "main.go", "main.rs"}:
                add_unique(entry_points, path)
            for symbol in syms or []:
                if str(symbol).lower() in {"main", "run", "app", "create_app", "startup", "program"}:
                    add_unique(entry_points, f"{path}::{symbol}")

        # Exact parser facts can add route/entrypoint/test coordinates without prose inference.
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
            for row in rows:
                kind = str(row["kind"])
                if kind in {"entrypoint", "entrypoint_file", "route"}:
                    add_unique(entry_points, f"{row['path']}:{row['line']} {row['name']}")
                elif kind == "test_file":
                    add_unique(validation, str(row["path"]))

        purpose_parts = [f"module {module}", f"{len(paths)} files"]
        if side_effects:
            purpose_parts.append("effects=" + ",".join(side_effects[:5]))
        invariants: list[str] = []
        # Only structural invariants are safe to state deterministically.
        if validation:
            invariants.append("validation files are mapped from indexed test paths")
        if entry_points:
            invariants.append("entry points are parser/index coordinates, not inferred behavior")
        richness = symbols + len(dependencies) + 2 * len(entry_points) + 2 * len(validation) + len(side_effects)
        confidence = (min(0.98, 0.82 + min(0.14, richness * 0.012) + (0.02 if len(paths) >= 2 else 0.0)) if paths else 0.4)
        card = {
            "purpose": "; ".join(purpose_parts),
            "entry_points": entry_points[:30],
            "dependencies": dependencies[:40],
            "invariants": invariants[:12],
            "risks": risks[:24],
            "validation": validation[:30],
        }
        return {"success": True, "deterministic": True, "confidence": round(confidence, 4), "card": card}

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

        def coords(result: dict[str, Any], limit: int = 20) -> list[str]:
            out: list[str] = []
            for f in result.get("facts", [])[:limit]:
                text = f"{f.get('path')}:{f.get('line')} {f.get('kind')}={f.get('name')}"
                if text not in out:
                    out.append(text)
            return out

        entry_points = coords(entry, 24)
        testing = [f"{x.get('name')} -> {x.get('command')}" for x in commands.get("scripts", []) if str(x.get("purpose", "")).lower() in {"tests", "test", "lint", "checks", "check", "type-check", "build"}][:30]
        configuration = coords(config, 28)
        data_flow = coords(database, 24)
        security_items = coords(security, 24)
        concurrency_items = coords(concurrency, 24)
        infrastructure_items = coords(infrastructure, 32)
        hot_paths = [str(x.get("module")) for x in modules[:20] if x.get("module")]
        if not hot_paths:
            hot_paths = [str(x[0]) for x in repo_map.get("top_paths", [])[:20] if isinstance(x, (list, tuple)) and x]

        langs = profile.get("languages", [])
        if isinstance(langs, dict):
            langs_text = ", ".join(str(k) for k in list(langs)[:10])
        elif isinstance(langs, list):
            langs_text = ", ".join(str(x.get("language", x)) if isinstance(x, dict) else str(x) for x in langs[:10])
        else:
            langs_text = str(langs or "")
        architecture = f"Deterministic project map: {repo_map.get('files', 0)} indexed source files"
        if langs_text:
            architecture += f"; languages: {langs_text}"
        if hot_paths:
            architecture += "; top modules: " + ", ".join(hot_paths[:10])

        risks: list[str] = []
        if security_items: risks.append("security-sensitive code present")
        if concurrency_items: risks.append("concurrency-sensitive code present")
        if data_flow: risks.append("database/persistence code present")
        if infrastructure_items: risks.append("deployment/infrastructure declarations present")
        syntax = self.query(root_s, "syntax parse error", limit=20)
        if syntax.get("facts"): risks.append(f"{len(syntax['facts'])} parser-detected syntax/config errors")

        evidence_count = sum(len(x) for x in (entry_points, configuration, data_flow, security_items, concurrency_items, infrastructure_items, testing))
        confidence = min(0.97, 0.78 + min(0.17, evidence_count * 0.003) + (0.02 if modules else 0.0))
        card = {
            "architecture": architecture,
            "entry_points": entry_points,
            "hot_paths": hot_paths[:20],
            "testing": testing,
            "configuration": configuration,
            "data_flow": data_flow,
            "security": security_items,
            "concurrency": concurrency_items,
            "infrastructure": infrastructure_items,
            "risks": risks,
        }
        return {"success": True, "deterministic": True, "confidence": round(confidence, 4), "card": card}

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

        breaking: list[dict[str, Any]] = []
        for name, old_d in old_defs.items():
            kind = old_d.get("kind", "symbol")
            if name not in new_defs:
                breaking.append({
                    "type": "removed_symbol",
                    "symbol": name,
                    "file": file_path,
                    "kind": kind,
                    "description": f"Public {kind} '{name}' was removed",
                })
            else:
                new_d = new_defs[name]
                if kind in ("function", "method") and new_d.get("kind") in ("function", "method"):
                    old_req = old_d.get("required_count", 0)
                    new_req = new_d.get("required_count", 0)
                    old_args = old_d.get("pos_args") or old_d.get("params") or []
                    new_args = new_d.get("pos_args") or new_d.get("params") or []
                    if new_req > old_req:
                        added_req = [a for a in new_args[:new_req] if a not in old_args[:old_req]]
                        detail = f": {', '.join(added_req)}" if added_req else ""
                        breaking.append({
                            "type": "signature_changed",
                            "symbol": name,
                            "file": file_path,
                            "kind": kind,
                            "description": f"Signature of {kind} '{name}' added required parameter(s){detail}",
                            "new_req": new_req,
                            "old_req": old_req,
                            "added_req": added_req,
                            "removed_args": [],
                        })
                    elif old_args and new_args:
                        removed_args = [a for a in old_args if a not in new_args]
                        if removed_args:
                            breaking.append({
                                "type": "signature_changed",
                                "symbol": name,
                                "file": file_path,
                                "kind": kind,
                                "description": f"Signature of {kind} '{name}' removed or renamed parameter(s): {', '.join(removed_args)}",
                                "new_req": new_req,
                                "old_req": old_req,
                                "added_req": [],
                                "removed_args": removed_args,
                            })
        return breaking

    def diff_facts(self, diff: str) -> dict[str, Any]:
        """Parse a unified diff into factual risk/validation metadata without an LLM."""
        files: list[str] = []
        added = deleted = hunks = 0
        added_lines: list[tuple[str, str]] = []
        file_diff_lines: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"added": [], "deleted": []})
        current = ""
        orig_file = ""
        for line in diff.splitlines():
            if line.startswith("--- a/"):
                orig_file = line[6:].strip()
                current = ""
            elif line.startswith("+++ b/"):
                current = line[6:].strip()
                if current and current not in files:
                    files.append(current)
            elif line.startswith("+++ /dev/null") and orig_file:
                current = orig_file
                if current and current not in files:
                    files.append(current)
            elif line.startswith("@@"):
                hunks += 1
            elif line.startswith("+") and not line.startswith("+++"):
                added += 1
                added_lines.append((current, line[1:]))
                if current:
                    file_diff_lines[current]["added"].append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                deleted += 1
                target = current or orig_file
                if target:
                    file_diff_lines[target]["deleted"].append(line[1:])

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
        root_path = Path(root).resolve()
        if diff is None:
            try:
                from .process_utils import hidden_run_kwargs
                cp = subprocess.run(
                    ["git", "diff", "HEAD"],
                    cwd=str(root_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                    timeout=15,
                    **hidden_run_kwargs(),
                )
                diff = cp.stdout or ""
            except Exception:
                diff = ""

        file_diff_lines: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"added": [], "deleted": []})
        current = orig_file = ""
        for line in diff.splitlines():
            if line.startswith("--- a/"):
                orig_file = line[6:].strip()
                current = ""
            elif line.startswith("+++ b/"):
                current = line[6:].strip()
            elif line.startswith("+++ /dev/null") and orig_file:
                current = orig_file
            elif line.startswith("+") and not line.startswith("+++"):
                if current:
                    file_diff_lines[current]["added"].append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                target = current or orig_file
                if target:
                    file_diff_lines[target]["deleted"].append(line[1:])

        breaking_changes: list[dict[str, Any]] = []
        for file_path, lines_dict in file_diff_lines.items():
            bcs = self._detect_breaking_changes(file_path, lines_dict["deleted"], lines_dict["added"])
            breaking_changes.extend(bcs)

        breaking_by_symbol = {b["symbol"]: b for b in breaking_changes}
        breaking_callers: list[dict[str, Any]] = []

        if breaking_by_symbol and root_path.is_dir():
            skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}
            for py_path in root_path.rglob("*.py"):
                if any(part in skip_dirs for part in py_path.parts):
                    continue
                try:
                    src = py_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if not any(sym in src for sym in breaking_by_symbol):
                    continue
                try:
                    tree = ast.parse(src)
                except Exception:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        callee = ""
                        if isinstance(node.func, ast.Name):
                            callee = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            callee = node.func.attr

                        if callee in breaking_by_symbol:
                            info = breaking_by_symbol[callee]
                            b_type = info.get("type")
                            reason = ""
                            if b_type == "removed_symbol":
                                reason = f"Call to removed symbol '{callee}'"
                            elif b_type == "signature_changed":
                                kw_names = {kw.arg for kw in node.keywords if kw.arg}
                                removed_args = info.get("removed_args", [])
                                removed_overlap = kw_names & set(removed_args)
                                if removed_overlap:
                                    reason = f"Call passes removed or renamed parameter(s): {', '.join(sorted(removed_overlap))}"
                                else:
                                    has_varargs = any(isinstance(a, ast.Starred) for a in node.args)
                                    has_kwargs = any(kw.arg is None for kw in node.keywords)
                                    new_req = info.get("new_req", 0)
                                    passed_args = len(node.args) + len(kw_names)
                                    if not (has_varargs or has_kwargs) and passed_args < new_req:
                                        reason = f"Missing required parameter(s): expected at least {new_req}, passed {passed_args}"

                            if reason:
                                try:
                                    rel_file = str(py_path.relative_to(root_path)).replace("\\", "/")
                                except Exception:
                                    rel_file = str(py_path).replace("\\", "/")
                                snippet = ""
                                try:
                                    snippet = ast.unparse(node)
                                except (ValueError, TypeError, RecursionError) as render_exc:
                                    logger.debug(
                                        "Caller snippet rendering skipped (%s)",
                                        type(render_exc).__name__,
                                    )
                                breaking_callers.append({
                                    "file": rel_file,
                                    "line": getattr(node, "lineno", 0),
                                    "callee": callee,
                                    "reason": reason,
                                    "snippet": snippet,
                                })

        impacted_files = sorted(list({c["file"] for c in breaking_callers}))
        return {
            "success": True,
            "modified_symbols": breaking_changes,
            "breaking_callers": breaking_callers,
            "impacted_files": impacted_files,
            "summary": f"Found {len(breaking_callers)} breaking call site(s) across {len(impacted_files)} file(s).",
        }

    def render_answer(self, result: dict[str, Any], max_items: int = 16) -> str:
        """Render a terse deterministic answer without invoking any model."""
        intent = str(result.get("intent", "general"))
        lines: list[str] = []
        if intent == "dependencies":
            for x in result.get("dependencies", [])[:max_items]:
                version = f" {x.get('version')}" if x.get("version") else ""
                lines.append(f"- {x.get('name')}{version} [{x.get('scope','')}] — {x.get('source','')}")
        elif intent == "commands":
            for x in result.get("scripts", [])[:max_items]:
                lines.append(f"- {x.get('purpose','script')}: {x.get('name')} → {x.get('command')}")
        elif intent == "tests":
            for p in result.get("test_candidates", [])[:max_items]:
                lines.append(f"- {p}")
            for x in result.get("facts", [])[:max_items-len(lines)]:
                if x.get("path") not in {p[2:] if p.startswith('- ') else p for p in lines}:
                    lines.append(f"- {x.get('path')}")
        elif intent in {"symbols", "callers", "references"}:
            graph = result.get("code_index", {}) if isinstance(result.get("code_index"), dict) else {}
            if intent == "callers":
                for x in graph.get("callers", [])[:max_items]:
                    lines.append(f"- {x.get('caller')} calls {x.get('callee')} — {x.get('path')}:{x.get('line')}")
            for x in graph.get("symbols", [])[:max_items]:
                lines.append(f"- definition {x.get('name')} — {x.get('path')}:{x.get('line')}")
            group = graph.get("references", []) if intent != "symbols" else []
            for x in group[:max(0, max_items-len(lines))]:
                lines.append(f"- reference {x.get('name')} — {x.get('path')}:{x.get('line')}")
            for x in graph.get("edges", [])[:max(0, max_items-len(lines))]:
                lines.append(f"- {x.get('src')} {x.get('kind')} {x.get('dst')} — {x.get('path')}:{x.get('line')}")
        else:
            for x in result.get("facts", [])[:max_items]:
                label = x.get("name") or x.get("kind")
                value = x.get("value")
                suffix = f" = {value}" if value and value != label else ""
                lines.append(f"- {x.get('kind')}: {label}{suffix} — {x.get('path')}:{x.get('line')}")
            if not lines:
                graph = result.get("code_index", {}) if isinstance(result.get("code_index"), dict) else {}
                for x in graph.get("symbols", [])[:max_items]:
                    lines.append(f"- definition {x.get('name')} — {x.get('path')}:{x.get('line')}")
        if not lines:
            return "No deterministic match found."
        return "\n".join(lines)

    def related_paths(self, root: str, query: str, limit: int = 24) -> list[str]:
        result = self.query(root, query, limit=max(limit, 24))
        scores: dict[str, int] = defaultdict(int)
        for item in result.get("facts", []):
            p = str(item.get("path", "")); scores[p] += 4
        graph = result.get("code_index", {}) if isinstance(result.get("code_index"), dict) else {}
        for group, weight in ((graph.get("symbols", []), 4), (graph.get("references", []), 2), (graph.get("edges", []), 1)):
            for item in group or []:
                p = str(item.get("path", "")); scores[p] += weight
        for p in result.get("test_candidates", []):
            scores[str(p)] += 3
        return [p for p, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit] if p]

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
            for ev in result.get("evidence", []):
                eid = str(ev.get("evidence_id", ""))
                if not eid or raw_count >= max_raw_evidence:
                    continue
                exact = self.evidence.get(eid, verify=True)
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

        if self.code_index is not None and used < max_chars:
            try:
                sym_res = self.code_index.find_symbol(root, query, depth=1, include_info=True, limit=6)
                symbols = sym_res.get("symbols", [])
                if not symbols:
                    for term in self._terms(query):
                        if term.isidentifier():
                            sym_res = self.code_index.find_symbol(root, term, depth=1, include_info=True, limit=6)
                            symbols = sym_res.get("symbols", [])
                            if symbols:
                                break
                    if not symbols:
                        q_res = self.code_index.query(root, query, limit=6)
                        symbols = q_res.get("symbols", [])
                if symbols:
                    sym_blocks = ["\nHIERARCHICAL SYMBOLS & SIGNATURES:"]
                    for s in symbols:
                        sig = s.get("signature") or f"{s.get('kind')} {s.get('name')}"
                        sym_blocks.append(f"- [{s.get('kind')}] {s.get('name_path')} ({s.get('path')}:{s.get('line')}) -> {sig}")
                        for ch in s.get("children", [])[:4]:
                            sym_blocks.append(f"    * {ch.get('signature') or ch.get('name')} (L{ch.get('line')})")
                    sym_text = "\n".join(sym_blocks)
                    if used + 1 + len(sym_text) <= max_chars:
                        pieces.append(sym_text)
                    else:
                        truncated = True
            except Exception:
                pass

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

        return {
            "success": True,
            "root": resolved,
            "dead_symbols_count": len(dead),
            "dead_symbols": dead,
        }

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

        if self.code_index is not None:
            try:
                with self.code_index._lock, closing(self.code_index._connect()) as con:
                    if not symbols_to_check:
                        sym_rows = con.execute(
                            "SELECT name FROM symbols WHERE root=? AND path=? AND kind IN ('class','function','method')",
                            (resolved, target_path),
                        ).fetchall()
                        symbols_to_check = [str(r[0]) for r in sym_rows]
                    
                    for sym in symbols_to_check:
                        edge_rows = con.execute(
                            "SELECT src, dst, path, line, kind FROM edges WHERE root=? AND dst=?",
                            (resolved, sym),
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
            except Exception:
                pass

        ext_files = [f for f in impacted_files if f != target_path]
        if len(ext_files) == 0:
            risk = "LOW"
        elif len(ext_files) <= 3:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

        impacted_tests = list(dict.fromkeys(impacted_tests))
        recommendations = []
        if impacted_tests:
            recommendations.append(f"Run {len(impacted_tests)} impacted test suite(s): {', '.join(impacted_tests[:3])}")
        if ext_files:
            recommendations.append(f"Verify {len(callers)} call site(s) across {len(ext_files)} external file(s)")
        else:
            recommendations.append("Local changes only; no external dependencies affected.")

        return {
            "success": True,
            "root": resolved,
            "target_file": target_path,
            "symbols_analyzed": symbols_to_check,
            "risk_level": risk,
            "impacted_files_count": len(ext_files),
            "impacted_files": sorted(ext_files),
            "callers_count": len(callers),
            "callers": callers[:30],
            "impacted_tests": impacted_tests,
            "recommendations": recommendations,
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

        def language_for_path(path: str) -> str:
            suffix = Path(path).suffix.lower()
            if suffix == ".py": return "python"
            if suffix == ".cs": return "csharp"
            if suffix == ".php": return "php"
            if suffix in {".ts", ".tsx", ".mts", ".cts"}: return "typescript"
            if suffix in {".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"}: return "javascript"
            return "auto"

        def import_for(symbol: str, container: str, path: str, lang: str, source: str) -> str:
            if lang == "csharp":
                namespace = container
                if not namespace:
                    match = re.search(r"(?m)^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.]*)", source)
                    namespace = match.group(1) if match else ""
                return f"using {namespace};" if namespace else ""
            if lang == "php":
                namespace = container
                if not namespace:
                    match = re.search(r"(?m)^\s*namespace\s+([A-Za-z_][A-Za-z0-9_\\]*)", source)
                    namespace = match.group(1) if match else ""
                fqn = f"{namespace}\\{symbol}" if namespace else symbol
                return f"use {fqn};"
            if lang == "python":
                mod_path = Path(path.replace("\\", "/"))
                without_suffix = mod_path.with_suffix("") if mod_path.suffix else mod_path
                parts = list(without_suffix.parts)
                if parts and parts[-1] == "__init__":
                    parts.pop()
                if any(not part.isidentifier() for part in parts if part not in {".", ""}):
                    return ""
                module = ".".join(part for part in parts if part not in {".", ""})
                return f"from {module} import {symbol}" if module else f"import {symbol}"
            if lang in {"typescript", "javascript"}:
                normalized = path.replace("\\", "/")
                pth = Path(normalized)
                if pth.suffix.lower() in {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}:
                    normalized = str(pth.with_suffix("")).replace("\\", "/")
                if not normalized.startswith("."):
                    normalized = "./" + normalized
                normalized = normalized.replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
                return f"import {{ {symbol} }} from '{normalized}';"
            return ""

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
                }
            
            lines = res.stdout.splitlines()
            branch = "unknown"
            modified: list[str] = []
            staged: list[str] = []
            untracked: list[str] = []
            
            if lines and lines[0].startswith("## "):
                branch = lines[0][3:].split("...")[0].strip()
                lines = lines[1:]
                
            for ln in lines:
                if len(ln) < 3:
                    continue
                x, y, path = ln[0], ln[1], ln[3:].strip()
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
        """Search bounded Git message and pickaxe history with explicit coverage."""
        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"
        if (
            not isinstance(query, str)
            or len(query) > _GIT_HISTORY_QUERY_MAX_CHARS
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in query)
        ):
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": "query must be a bounded literal string", "root": resolved}
        if isinstance(max_commits, bool) or not isinstance(max_commits, int) or not 1 <= max_commits <= _GIT_HISTORY_COMMIT_LIMIT:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": f"max_commits must be an integer from 1 to {_GIT_HISTORY_COMMIT_LIMIT}", "root": resolved}
        clean_query = query.strip()
        if author is not None and (
            not isinstance(author, str)
            or len(author) > _GIT_HISTORY_AUTHOR_MAX_CHARS
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in author)
        ):
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": "author must be a bounded string", "root": resolved}
        clean_author = author.strip() if isinstance(author, str) else ""
        try:
            since_epoch, since_normalized = _git_history_timestamp(since, "since", upper_bound=False)
            until_epoch, until_normalized = _git_history_timestamp(until, "until", upper_bound=True)
            pathspec = _git_history_pathspec(resolved, path)
        except (OSError, RuntimeError, TypeError, ValueError, OverflowError) as exc:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": str(exc), "root": resolved}
        if since_epoch is not None and until_epoch is not None and since_epoch > until_epoch:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False,
                    "error": "since must be earlier than or equal to until", "root": resolved}

        deadline = time.monotonic() + _GIT_INSIGHT_DEADLINE_SECONDS
        commits: dict[str, dict[str, Any]] = {}
        incomplete: set[str] = set()
        completed_searches = 0
        for match_type in ("message", "diff_content"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                incomplete.add("aggregate_deadline")
                break
            fmt = "%H%x00%an%x00%cI%x00%s%x00"
            argv = [
                git_exe, "-C", resolved, "--literal-pathspecs",
                "-c", "diff.external=", "-c", "core.pager=cat", "log",
                f"-n{max_commits + 1}", f"--format={fmt}", "-i", "--fixed-strings",
                "--no-ext-diff", "--no-textconv", "--no-renames",
            ]
            if not clean_query and match_type == "diff_content":
                continue
            if match_type == "message":
                if clean_query:
                    argv.append(f"--grep={clean_query}")
            else:
                argv.append(f"-S{clean_query}")
            if clean_author:
                argv.append(f"--author={clean_author}")
            if since_epoch is not None:
                argv.append(f"--since-as-filter=@{math.ceil(since_epoch)}")
            if until_epoch is not None:
                argv.append(f"--until=@{math.floor(until_epoch)}")
            argv.extend(("--end-of-options", "HEAD", "--"))
            if pathspec is not None:
                argv.append(pathspec)
            try:
                result = run_hidden(
                    argv,
                    cwd=resolved,
                    capture_output=True,
                    text=False,
                    stdin=subprocess.DEVNULL,
                    timeout=remaining,
                    max_output_bytes=_GIT_INSIGHT_STREAM_LIMIT,
                    env=clean_git_env(extra_env={
                        "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
                        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "diff.external",
                        "GIT_CONFIG_VALUE_0": "",
                    }),
                )
            except (ProcessCancelledError, ProcessCleanupUnverifiedError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
                incomplete.add(f"{match_type}_search_{type(exc).__name__}")
                continue
            if getattr(result, "returncode", 1) != 0:
                incomplete.add(f"{match_type}_search_failed")
                continue
            if getattr(result, "stdout_truncated", False) or getattr(result, "stderr_truncated", False):
                incomplete.add(f"{match_type}_output_truncated")
            raw_output = getattr(result, "stdout", b"")
            if not isinstance(raw_output, bytes):
                incomplete.add(f"{match_type}_malformed_output")
                continue
            fields = raw_output.split(b"\0")
            if fields and fields[-1] == b"":
                fields.pop()
            if fields and fields[-1] in {b"\n", b"\r\n"}:
                fields.pop()
            if len(fields) % 4:
                incomplete.add(f"{match_type}_malformed_output")
            for index in range(0, len(fields) - 3, 4):
                if time.monotonic() >= deadline:
                    incomplete.add("aggregate_deadline")
                    break
                try:
                    full_hash = fields[index].lstrip(b"\r\n").decode("ascii")
                    commit_author = fields[index + 1].decode("utf-8", "strict")
                    committed_at = fields[index + 2].decode("ascii", "strict")
                    subject = fields[index + 3].decode("utf-8", "strict").strip("\r\n")
                    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", full_hash):
                        raise ValueError("invalid commit hash")
                    committed_dt = _datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
                    if committed_dt.tzinfo is None:
                        raise ValueError("commit date has no timezone")
                    committed_timestamp = committed_dt.timestamp()
                    if since_epoch is not None and committed_timestamp < since_epoch:
                        continue
                    if until_epoch is not None and committed_timestamp > until_epoch:
                        continue
                except (UnicodeDecodeError, ValueError, OverflowError):
                    incomplete.add(f"{match_type}_malformed_output")
                    continue
                current = commits.get(full_hash)
                if current is None:
                    current = {
                        "commit": full_hash[:10],
                        "full_hash": full_hash,
                        "author": commit_author,
                        "date": committed_dt.date().isoformat(),
                        "subject": subject,
                        "message": subject,
                        "match_type": match_type,
                        "_committed_timestamp": committed_timestamp,
                        "_match_types": [match_type],
                    }
                    commits[full_hash] = current
                elif match_type not in current["_match_types"]:
                    current["_match_types"].append(match_type)
            if len(fields) >= 4 * (max_commits + 1):
                incomplete.add("commit_limit_reached")
            completed_searches += 1

        if completed_searches < 2 and time.monotonic() >= deadline:
            incomplete.add("aggregate_deadline")
        ordered = sorted(
            commits.values(),
            key=lambda item: (-float(item["_committed_timestamp"]), item["full_hash"]),
        )
        if len(ordered) > max_commits:
            incomplete.add("commit_limit_reached")
        res_list = ordered[:max_commits]
        for item in res_list:
            item["match_type"] = ", ".join(item.pop("_match_types"))
            item.pop("_committed_timestamp", None)
        return {
            "success": completed_searches > 0,
            "root": resolved,
            "query": clean_query,
            "author": clean_author or None,
            "since": since_normalized,
            "until": until_normalized,
            "path": pathspec,
            "max_commits": max_commits,
            "count": len(res_list),
            "commits": res_list,
            "complete": not incomplete,
            "incomplete_reasons": sorted(incomplete),
        }

    def find_hotspots(
        self,
        root: str,
        days: int = 30,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Rank Git-touched files by bounded recency-weighted churn and complexity."""
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
            return {"success": False, "error": "days must be an integer from 1 to 3650"}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return {"success": False, "error": "limit must be an integer from 1 to 50"}
        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"

        # The service-level repository cache keys this operation by the current
        # repository fingerprint. Do not consult the older root/days-only table:
        # it cannot detect changed HEADs or current-file contents.

        deadline = time.monotonic() + _HOTSPOT_ANALYSIS_SECONDS
        now = time.time()
        cutoff = int(now - days * 86_400)
        argv = [
            git_exe, "-C", resolved, "--literal-pathspecs", "-c", "core.pager=cat",
            "log", f"-n{_HOTSPOT_GIT_COMMIT_LIMIT + 1}", f"--since-as-filter=@{cutoff}",
            "--format=%x00LAH_HOTSPOT:%ct%x00", "--name-only", "-z", "--no-merges",
            "--no-renames", "--no-ext-diff", "--no-textconv", "--end-of-options", "HEAD", "--",
        ]
        incomplete: set[str] = set()
        churn_counts: dict[str, int] = defaultdict(int)
        weighted_counts: dict[str, float] = defaultdict(float)
        try:
            res = run_hidden(
                argv,
                cwd=resolved,
                capture_output=True,
                text=False,
                stdin=subprocess.DEVNULL,
                timeout=max(0.1, deadline - time.monotonic()),
                max_output_bytes=_GIT_INSIGHT_STREAM_LIMIT,
                env=clean_git_env(extra_env={
                    "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "diff.external",
                    "GIT_CONFIG_VALUE_0": "",
                }),
            )
            if getattr(res, "returncode", 1) != 0:
                incomplete.add("git_history_failed")
            if getattr(res, "stdout_truncated", False) or getattr(res, "stderr_truncated", False):
                incomplete.add("git_output_truncated")
            raw_output = getattr(res, "stdout", b"")
            if not isinstance(raw_output, bytes):
                incomplete.add("git_output_malformed")
                raw_output = b""
            segments = raw_output.split(b"\0LAH_HOTSPOT:")
            if segments and not segments[0].strip(b"\r\n"):
                segments = segments[1:]
            if len(segments) > _HOTSPOT_GIT_COMMIT_LIMIT:
                incomplete.add("commit_limit_reached")
            for segment in segments[:_HOTSPOT_GIT_COMMIT_LIMIT]:
                if time.monotonic() >= deadline:
                    incomplete.add("analysis_deadline")
                    break
                try:
                    # The explicit timestamp terminator is followed by Git's
                    # -z record terminator before its filename framing newline.
                    timestamp_raw, separator, files_raw = segment.partition(b"\0\0")
                    timestamp = int(timestamp_raw.strip())
                    if not separator or timestamp < cutoff:
                        raise ValueError("malformed commit record")
                    # Git inserts one formatting newline around each NUL-delimited
                    # name list. Remove only those framing bytes; preserve filename newlines.
                    if files_raw.startswith(b"\n"):
                        files_raw = files_raw[1:]
                    if files_raw.endswith(b"\n"):
                        files_raw = files_raw[:-1]
                    per_commit: set[str] = set()
                    for raw_path in files_raw.split(b"\0"):
                        if not raw_path:
                            continue
                        relative = raw_path.decode("utf-8", "strict").replace("\\", "/")
                        pure_path = PurePosixPath(relative)
                        if pure_path.is_absolute() or any(part in {"..", ""} for part in pure_path.parts):
                            incomplete.add("unsafe_git_path")
                            continue
                        if any(part.lower() in {".git", "vendor", "node_modules", "dist", "build"} for part in pure_path.parts):
                            continue
                        per_commit.add(pure_path.as_posix())
                    age_days = max(0.0, (now - float(timestamp)) / 86_400.0)
                    weight = 0.5 ** (age_days / 90.0)
                    for relative in per_commit:
                        if relative not in churn_counts and len(churn_counts) >= _HOTSPOT_PATH_LIMIT:
                            incomplete.add("path_limit_reached")
                            continue
                        churn_counts[relative] += 1
                        weighted_counts[relative] += weight
                except (UnicodeDecodeError, ValueError, OverflowError):
                    incomplete.add("git_output_malformed")
            if len(segments) > _HOTSPOT_GIT_COMMIT_LIMIT:
                incomplete.add("commit_limit_reached")
            if time.monotonic() >= deadline:
                incomplete.add("analysis_deadline")
        except (ProcessCancelledError, ProcessCleanupUnverifiedError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
            incomplete.add(f"git_history_{type(exc).__name__}")

        if not churn_counts and incomplete:
            return {
                "success": False,
                "root": resolved,
                "days": days,
                "count": 0,
                "hotspots": [],
                "algorithm": _HOTSPOT_ALGORITHM,
                "complete": False,
                "incomplete_reasons": sorted(incomplete),
                "recency_half_life_days": 90,
            }

        hotspots: list[dict[str, Any]] = []
        candidates = sorted(
            weighted_counts,
            key=lambda file_rel: (-weighted_counts[file_rel], file_rel),
        )
        if len(candidates) > _HOTSPOT_FILE_LIMIT:
            incomplete.add("file_limit_reached")
        total_bytes = 0
        reserved_bytes = 0
        analyzed_files = 0
        canonical_root = Path(resolved).resolve(strict=True)
        for file_rel in candidates[:_HOTSPOT_FILE_LIMIT]:
            if time.monotonic() >= deadline:
                incomplete.add("analysis_deadline")
                break
            full_p = Path(resolved) / file_rel
            fd = -1
            content_buffer = bytearray()
            try:
                current_component = canonical_root
                for part in PurePosixPath(file_rel).parts:
                    current_component = current_component / part
                    if _is_symlink_or_reparse_point(current_component):
                        raise ValueError("reparse_point")
                before = os.stat(full_p, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("not_regular")
                canonical_file = full_p.resolve(strict=True)
                canonical_file.relative_to(canonical_root)
                size = before.st_size
                if size > _HOTSPOT_FILE_BYTES_LIMIT:
                    incomplete.add("file_byte_limit_reached")
                    continue
                reservation = size + 1
                if reserved_bytes + reservation > _HOTSPOT_TOTAL_BYTES_LIMIT:
                    incomplete.add("aggregate_byte_limit_reached")
                    break
                reserved_bytes += reservation
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
                if getattr(os, "O_NOFOLLOW", 0):
                    flags |= os.O_NOFOLLOW
                fd = os.open(full_p, flags)
                opened = os.fstat(fd)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                ):
                    raise ValueError("file_identity_changed")
                opened_path = Path(full_p).resolve(strict=True)
                opened_path.relative_to(canonical_root)
                source = os.fdopen(fd, "rb", buffering=0)
                fd = -1
                deadline_expired_during_read = False
                with source:
                    remaining_read = reservation
                    while remaining_read:
                        if time.monotonic() >= deadline:
                            incomplete.add("analysis_deadline")
                            deadline_expired_during_read = True
                            break
                        chunk = source.read(min(65_536, remaining_read))
                        if not chunk:
                            break
                        content_buffer.extend(chunk)
                        total_bytes += len(chunk)
                        remaining_read -= len(chunk)
                    after = os.fstat(source.fileno())
                if deadline_expired_during_read:
                    continue
                current_path_stat = os.stat(full_p, follow_symlinks=False)
                current_path = full_p.resolve(strict=True)
                current_path.relative_to(canonical_root)
                before_state = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                opened_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                after_state = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                path_state = (
                    current_path_stat.st_dev, current_path_stat.st_ino, current_path_stat.st_size,
                    current_path_stat.st_mtime_ns, current_path_stat.st_ctime_ns,
                )
                # Windows path stat and handle stat expose different ctime
                # semantics. Compare each source with its own earlier sample.
                if (
                    before_state != path_state
                    or opened_state != after_state
                    or (current_path_stat.st_dev, current_path_stat.st_ino) != (after.st_dev, after.st_ino)
                    or current_path != canonical_file
                    or _is_symlink_or_reparse_point(full_p)
                ):
                    incomplete.add("file_changed_during_read")
                    continue
                content_bytes = bytes(content_buffer)
                if len(content_buffer) > size:
                    incomplete.add("file_grew_during_read")
                    continue
                content = content_bytes.decode("utf-8", "strict")
                analyzed_files += 1
            except UnicodeDecodeError:
                incomplete.add("file_decode_failed")
                continue
            except ValueError as exc:
                incomplete.add("reparse_point_skipped" if str(exc) == "reparse_point" else "file_identity_changed")
                continue
            except (OSError, RuntimeError):
                incomplete.add("current_file_unavailable")
                continue
            finally:
                if fd >= 0:
                    os.close(fd)
            comp_score = 1
            loc = 0
            if time.monotonic() >= deadline:
                incomplete.add("analysis_deadline")
                continue
            try:
                loc = len(content.splitlines())
                if full_p.suffix == ".py":
                    if time.monotonic() >= deadline:
                        incomplete.add("analysis_deadline")
                        continue
                    tree = ast.parse(content, filename=file_rel)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.Match)):
                            comp_score += 1
                else:
                    comp_score = max(1, loc // 15)
            except Exception:
                incomplete.add("complexity_parse_failed")
                comp_score = max(1, loc // 20)

            raw_churn = churn_counts[file_rel]
            recency_weighted_churn = round(weighted_counts[file_rel], 6)
            hotspot_index = round(recency_weighted_churn * math.log2(1.0 + float(comp_score)), 2)
            hotspots.append({
                "file": file_rel,
                "path": file_rel,
                "churn": raw_churn,
                "churn_commits": raw_churn,
                "recency_weighted_churn": recency_weighted_churn,
                "complexity": comp_score,
                "lines_of_code": loc,
                "debt_score": hotspot_index,
                "hotspot_score": hotspot_index,
                "risk_level": "critical" if hotspot_index >= 50 else ("high" if hotspot_index >= 20 else "moderate"),
            })

        hotspots.sort(key=lambda x: x["hotspot_score"], reverse=True)
        res_data = {
            "success": True,
            "root": resolved,
            "days": days,
            "algorithm": _HOTSPOT_ALGORITHM,
            "recency_half_life_days": 90,
            "recency_weighting": "sum(0.5 ** (commit_age_days / 90)) over commits in the requested day window",
            "complete": not incomplete,
            "incomplete_reasons": sorted(incomplete),
            "analysis": {
                "git_commits_scanned": min(len(segments) if "segments" in locals() else 0, _HOTSPOT_GIT_COMMIT_LIMIT),
                "files_seen": len(candidates),
                "files_analyzed": analyzed_files,
                "bytes_read": total_bytes,
                "bytes_reserved": reserved_bytes,
                "commit_limit": _HOTSPOT_GIT_COMMIT_LIMIT,
                "file_limit": _HOTSPOT_FILE_LIMIT,
                "per_file_bytes_limit": _HOTSPOT_FILE_BYTES_LIMIT,
                "aggregate_bytes_limit": _HOTSPOT_TOTAL_BYTES_LIMIT,
            },
            "count": len(hotspots),
            "hotspots": hotspots,
        }
        res_data["hotspots"] = hotspots[:limit]
        res_data["count"] = len(res_data["hotspots"])
        return res_data

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


    def test_matrix(self, root: str) -> dict[str, Any]:
        """Discover test frameworks, test files, and test mappings in the repository."""
        resolved_root = Path(self._root(root))
        root_str = str(resolved_root)
        test_files: list[dict[str, Any]] = []
        warnings: list[str] = []
        incomplete = False
        framework = "unknown"
        run_all_cmd = ""

        dotnet_project = False
        if resolved_root.is_dir():
            try:
                with os.scandir(root_str) as root_entries:
                    for index, entry in enumerate(root_entries):
                        if index >= 128:
                            incomplete = True
                            warnings.append("root_framework_scan_limit_reached")
                            break
                        if entry.name.endswith((".sln", ".csproj")) and entry.is_file(follow_symlinks=False):
                            dotnet_project = True
                            break
            except OSError:
                incomplete = True
                warnings.append("root_framework_scan_failed")

        # Fast framework detection via files in root
        if (resolved_root / "pytest.ini").exists() or (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt", "requirements-core.txt")):
            framework = "pytest"
            run_all_cmd = "python -m pytest"
        elif dotnet_project:
            framework = "dotnet"
            run_all_cmd = "dotnet test"
        elif (resolved_root / "package.json").exists():
            framework = "npm"
            run_all_cmd = "npm test"
        elif (resolved_root / "Cargo.toml").exists():
            framework = "cargo"
            run_all_cmd = "cargo test"
        elif (resolved_root / "go.mod").exists():
            framework = "go"
            run_all_cmd = "go test ./..."

        def is_test_source(rel_path: str) -> bool:
            """Recognize supported test naming conventions in the current tree."""
            normalized = rel_path.replace("\\", "/").lower()
            suffix = Path(normalized).suffix
            if suffix not in {".py", ".go", ".cs", ".ts", ".tsx", ".js", ".jsx", ".java", ".rs", ".cpp", ".cc", ".c"}:
                return False
            name = Path(normalized).name
            return (
                name.startswith("test_") or name.startswith("tests_") or
                name.endswith(("_test.py", "_test.go", ".spec.ts", ".spec.js", ".spec.tsx", ".spec.jsx", ".test.ts", ".test.js", ".test.tsx", ".test.jsx")) or
                any(part in {"test", "tests", "spec", "specs"} for part in Path(normalized).parts)
            )

        # Only current filesystem entries can back a matrix row. Keep directory
        # enumeration bounded; the durable index is deliberately not a source
        # of truth for test targets because it can lag deletions and renames.
        max_files = 2000
        max_targets = 40
        max_file_bytes = min(int(getattr(self.repo_tools, "max_file_bytes", 1_000_000)), 256_000)
        max_total_bytes = 2_000_000
        deadline = time.monotonic() + 2.0
        target_paths: list[tuple[str, Path, os.stat_result]] = []
        enumerated = 0
        try:
            for candidate, snapshot_stat in self.repo_tools._iter_files_with_stat(
                root_str, max_depth=25, max_files=max_files,
            ):
                if time.monotonic() >= deadline:
                    incomplete = True
                    warnings.append("test_file_enumeration_deadline_exceeded")
                    break
                enumerated += 1
                try:
                    rel = candidate.relative_to(resolved_root).as_posix()
                    if not is_test_source(rel):
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

        target_paths.sort(key=lambda item: item[0])
        if len(target_paths) > max_targets:
            incomplete = True
            warnings.append("test_file_result_limit_reached")
            target_paths = target_paths[:max_targets]

        def _extract_file_info(item: tuple[str, Path, os.stat_result]) -> dict[str, Any] | None:
            rel, f, before = item
            cases: list[str] = []
            suffix = f.suffix.lower()
            cases_scan_complete = suffix in {".py", ".cs"}
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
                if suffix == ".py":
                    for ln in txt.splitlines():
                        if time.monotonic() >= deadline:
                            cases_scan_complete = False
                            break
                        if ln.strip().startswith("def test_"):
                            cases.append(ln.strip().split("(")[0].replace("def ", "").strip())
                            if len(cases) > 15:
                                cases_scan_complete = False
                                break
                elif suffix == ".cs":
                    attribute_pending = 0
                    for line in txt.splitlines():
                        if time.monotonic() >= deadline:
                            cases_scan_complete = False
                            break
                        if re.search(r"\[(?:Test|UnityTest|Fact)\b", line):
                            attribute_pending = 20
                        if attribute_pending and (method := re.search(r"\bvoid\s+([A-Za-z0-9_]+)", line)):
                            cases.append(method.group(1))
                            attribute_pending = 0
                            if len(cases) > 15:
                                cases_scan_complete = False
                                break
                        elif attribute_pending:
                            attribute_pending -= 1
            except Exception as exc:
                return {"_omitted": type(exc).__name__}

            # Keep arguments structured. Display strings include only simple
            # shell tokens; paths needing quoting remain available as argv.
            suffix = f.suffix.lower()
            if suffix == ".py" and framework == "pytest":
                run_argv = ["python", "-m", "pytest", "--", rel]
            elif suffix == ".cs" and framework == "dotnet":
                run_argv = ["dotnet", "test", "--filter", f"FullyQualifiedName~{f.stem}"]
            elif suffix in {".js", ".jsx", ".ts", ".tsx"} and framework == "npm":
                run_argv = ["npm", "test", "--", rel]
            elif suffix == ".go" and framework == "go":
                run_argv = ["go", "test", f"./{str(Path(rel).parent).replace(chr(92), '/')}"]
            elif suffix == ".rs" and framework == "cargo":
                run_argv = ["cargo", "test"]
            else:
                run_argv = []
            safe_tokens = all(re.fullmatch(r"[A-Za-z0-9_./\\:-]+", arg) for arg in run_argv)
            run_file_cmd = " ".join(run_argv) if safe_tokens else ""
            return {
                "path": rel,
                "cases_count": len(cases),
                "cases": cases[:15],
                "run_command": run_file_cmd,
                "run_argv": run_argv,
                "content_sha256": digest,
                "cases_truncated": len(cases) > 15,
                "cases_scan_complete": cases_scan_complete,
                "case_detection": {
                    ".py": "python_test_function_name_heuristic",
                    ".cs": "csharp_test_attribute_method_heuristic",
                }.get(suffix, "not_implemented_for_language"),
            }

        selected: list[tuple[str, Path, os.stat_result]] = []
        remaining_bytes = max_total_bytes
        for item in target_paths:
            size = int(item[2].st_size)
            reservation = size + 1  # _read_snapshot's bounded growth lookahead
            if reservation > remaining_bytes:
                incomplete = True
                warnings.append("test_file_total_byte_limit_reached")
                break
            remaining_bytes -= reservation
            selected.append(item)
        if selected:
            with ThreadPoolExecutor(max_workers=min(8, len(selected))) as pool:
                for row in pool.map(_extract_file_info, selected):
                    if row is None or "_omitted" in row:
                        incomplete = True
                        warnings.append("test_file_read_failed")
                        continue
                    if row.get("cases_truncated"):
                        incomplete = True
                        warnings.append("test_case_result_limit_reached")
                    if not row.get("cases_scan_complete", True):
                        incomplete = True
                        warnings.append("test_case_scan_incomplete")
                    test_files.append(row)

        return {
            "success": True,
            "framework": framework,
            "run_all_command": run_all_cmd,
            "test_files_count": len(test_files),
            "test_files": test_files,
            "coverage": {
                "scan_complete": not incomplete,
                "scan_complete_within_scope": not incomplete,
                "scope": "current supported test files emitted by repo_tools iterator",
                "max_depth": 25,
                "max_files": 2000,
                "inventory_omissions_unknown": True,
                "warnings": sorted(set(warnings)),
            },
        }

    def affected_tests(self, root: str, changed_paths: list[str] | None = None, base: str = "HEAD") -> dict[str, Any]:
        """Map changed paths/symbols directly to affected test files and formulate targeted command."""
        matrix = self.test_matrix(root)
        framework = matrix.get("framework", "unknown")
        all_tests = matrix.get("test_files", [])
        
        resolved_root = Path(self._root(root))
        if changed_paths is None:
            changed_paths = []
            try:
                import subprocess
                from .process_utils import hidden_run_kwargs
                p = subprocess.run(["git", "status", "--porcelain"], cwd=str(resolved_root), capture_output=True, text=True, timeout=5, **hidden_run_kwargs())
                if p.returncode == 0:
                    for line in p.stdout.splitlines():
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) == 2:
                            changed_paths.append(parts[1].replace("\\", "/"))
            except Exception:
                pass

        norm_changed = [p.replace("\\", "/").lstrip("./") for p in changed_paths if p]
        if not norm_changed:
            return {
                "success": True,
                "framework": framework,
                "changed_files": [],
                "test_files": [],
                "suggested_command": "",
                "confidence": 1.0,
            }

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
            # that services inject. Build it lazily from RepositoryTools' bounded
            # inventory so dependency traversal still selects transitive tests.
            try:
                from .code_index import CodeIndex

                candidate_index = CodeIndex(self.config, self.repo_tools)
                candidate_paths = [
                    path.relative_to(resolved_root).as_posix()
                    for path in self.repo_tools.iter_files(str(resolved_root))
                ]
                indexed = candidate_index.update_files_batch(str(resolved_root), candidate_paths)
                if indexed.get("success"):
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
            "suggested_command": cmd,
            "confidence": 0.95 if matched_tests else 0.5,
            "selection_complete": graph_complete,
        }

    def repo_topology(self, root: str) -> dict[str, Any]:
        """Return a bounded local Python import graph and heuristic path labels."""
        import sys

        resolved_root = Path(self._root(root)).resolve()
        root_str = str(resolved_root)
        file_limit = 20_000
        per_file_limit = 256 * 1024
        total_bytes_limit = 8 * 1024 * 1024
        edge_limit = 5_000
        sample_limit = 100
        deadline = time.monotonic() + 3.0
        complete = True
        errors: list[str] = []
        excluded_dirs = sorted(getattr(self.repo_tools, "ignore_dirs", set()))
        excluded = {
            ".git", ".hg", ".svn", ".venv", "venv", ".tox", "node_modules",
            "__pycache__", "docs", "doc", "plans", "tests", "test", "fixtures",
            "fixture", "examples", "example", "archive", "archives", "artifacts",
            "handoff", "cache", "caches", "build", "dist", "target", "vendor",
            "generated",
        }

        source_roots: list[Path] = []
        src_root = resolved_root / "src"
        if src_root.is_dir():
            resolved_src = src_root.resolve()
            if _is_symlink_or_reparse_point(src_root) or not resolved_src.is_relative_to(resolved_root):
                complete = False
                errors.append("unsafe_path")
            else:
                source_roots.append(resolved_src)
        packages_root = resolved_root / "packages"
        if packages_root.is_dir():
            try:
                if _is_symlink_or_reparse_point(packages_root):
                    complete = False
                    errors.append("unsafe_path")
                else:
                    package_entries: list[Path] = []
                    for package in packages_root.iterdir():
                        if len(package_entries) >= file_limit or time.monotonic() >= deadline:
                            complete = False
                            errors.append("source_root_limit_or_deadline")
                            break
                        package_entries.append(package)
                    for package in sorted(package_entries):
                        if time.monotonic() >= deadline:
                            complete = False
                            errors.append("source_root_deadline")
                            break
                        package_src = package / "src"
                        if not package_src.is_dir():
                            continue
                        resolved_package_src = package_src.resolve()
                        if (
                            _is_symlink_or_reparse_point(package)
                            or _is_symlink_or_reparse_point(package_src)
                            or not resolved_package_src.is_relative_to(resolved_root)
                        ):
                            complete = False
                            errors.append("unsafe_path")
                            continue
                        source_roots.append(resolved_package_src)
            except OSError:
                complete = False
                errors.append("source_root_error")
        unsafe_source_root = "unsafe_path" in errors and not source_roots
        use_project_root = not source_roots and not unsafe_source_root
        inventory_roots = source_roots or ([resolved_root] if use_project_root else [])

        def eligible_rel(path: Path) -> str | None:
            try:
                rel = path.relative_to(resolved_root)
            except ValueError:
                return None
            if any(part.lower() in excluded for part in rel.parts[:-1]):
                return None
            if use_project_root or any(path.is_relative_to(base) for base in source_roots):
                return rel.as_posix()
            return None

        eligible: list[tuple[str, Path]] = []
        try:
            for inventory_root in inventory_roots:
                inventory_count = 0
                for candidate in self.repo_tools.iter_files(
                    str(inventory_root), max_files=file_limit + 1
                ):
                    if time.monotonic() >= deadline:
                        complete = False
                        errors.append("inventory_deadline")
                        break
                    inventory_count += 1
                    if inventory_count > file_limit:
                        complete = False
                        errors.append("inventory_limit")
                        break
                    rel = eligible_rel(candidate)
                    if rel is None or not rel.lower().endswith(".py"):
                        continue
                    if len(eligible) >= file_limit:
                        complete = False
                        errors.append("file_limit")
                        break
                    eligible.append((rel, candidate))
                if any(error in errors for error in ("inventory_deadline", "file_limit", "inventory_limit")):
                    break
        except Exception:
            complete = False
            errors.append("inventory_error")

        layers: dict[str, list[str]] = {
            name: []
            for name in (
                "entrypoints", "presentation", "core_services",
                "domain_models", "infrastructure", "utilities",
            )
        }
        module_paths: dict[str, list[str]] = defaultdict(list)
        path_modules: dict[str, str] = {}
        for rel, path in eligible:
            base = next(
                (source_root for source_root in source_roots if path.is_relative_to(source_root)),
                resolved_root,
            )
            module_parts = list(path.relative_to(base).with_suffix("").parts)
            if module_parts[-1] == "__init__":
                module_parts.pop()
            module = ".".join(module_parts)
            if module:
                module_paths[module].append(rel)
                path_modules[rel] = module

            lowered = rel.lower()
            name = path.name.lower()
            if name in {"main.py", "app.py", "cli.py", "__main__.py"}:
                layer = "entrypoints"
            elif any(token in lowered for token in ("route", "controller", "view", "endpoint", "http_", "mcp_", "api/", "api_")):
                layer = "presentation"
            elif any(token in lowered for token in ("service", "orchestrat", "planner", "pipeline", "handler", "manager", "engine", "core")):
                layer = "core_services"
            elif any(token in lowered for token in ("model", "schema", "entity", "types", "event", "state")):
                layer = "domain_models"
            elif any(token in lowered for token in ("db", "storage", "repo", "dao", "client", "cache", "telemetry", "hardware", "sqlite")):
                layer = "infrastructure"
            else:
                layer = "utilities"
            layers[layer].append(rel)

        local_top_levels = {module.partition(".")[0] for module in module_paths}

        def resolve_local(module: str) -> str | None:
            matches = module_paths.get(module, [])
            if len(matches) == 1:
                return matches[0]
            return "" if matches else None

        def has_unsafe_ancestor(path: Path) -> bool:
            current = resolved_root
            for part in path.relative_to(resolved_root).parts:
                current = current / part
                if _is_symlink_or_reparse_point(current):
                    return True
            return False

        edges: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        external: list[dict[str, Any]] = []
        stdlib_count = total_bytes = files_read = skipped = parse_errors = 0
        for file_index, (rel, path) in enumerate(eligible):
            if len(edges) + len(unresolved) + len(external) >= edge_limit:
                complete = False
                errors.append("edge_limit")
                skipped += len(eligible) - file_index
                break
            if time.monotonic() >= deadline or total_bytes >= total_bytes_limit:
                complete = False
                errors.append(
                    "analysis_deadline"
                    if time.monotonic() >= deadline
                    else "aggregate_byte_limit"
                )
                skipped += len(eligible) - file_index
                break
            try:
                if has_unsafe_ancestor(path) or not path.resolve().is_relative_to(resolved_root):
                    raise ValueError("unsafe_path")
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                    | getattr(os, "O_BINARY", 0)
                )
                fd = os.open(path, flags)
                try:
                    before = os.fstat(fd)
                    path_before = os.stat(path, follow_symlinks=False)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_size > per_file_limit
                        or (before.st_dev, before.st_ino) != (path_before.st_dev, path_before.st_ino)
                    ):
                        raise ValueError("unsafe_path")
                    remaining = min(per_file_limit, total_bytes_limit - total_bytes)
                    with os.fdopen(fd, "rb", closefd=False) as handle:
                        raw = handle.read(remaining + 1)
                    after = os.fstat(fd)
                    path_after = os.stat(path, follow_symlinks=False)
                    if (
                        len(raw) > remaining
                        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                        or (after.st_dev, after.st_ino) != (path_after.st_dev, path_after.st_ino)
                        or has_unsafe_ancestor(path)
                    ):
                        raise ValueError("file_changed_or_byte_limit")
                    total_bytes += len(raw)
                    files_read += 1
                    parsed = ast.parse(raw.decode("utf-8"), filename=rel)
                finally:
                    os.close(fd)
            except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
                complete = False
                skipped += 1
                parse_errors += 1
                errors.append(str(exc) if isinstance(exc, ValueError) else "read_or_parse_error")
                continue

            source_module = path_modules.get(rel)
            if not source_module:
                continue
            for node in ast.walk(parsed):
                if time.monotonic() >= deadline:
                    complete = False
                    errors.append("analysis_deadline")
                    break
                imports: list[tuple[str, int, bool]] = []
                if isinstance(node, ast.Import):
                    imports = [(alias.name, node.lineno, False) for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    package_parts = source_module.split(".")[:-1]
                    if Path(rel).name == "__init__.py":
                        package_parts = source_module.split(".")
                    if node.level > len(package_parts):
                        # An invalid relative level cannot become a root import.
                        imports = [("." * node.level + (node.module or ""), node.lineno, True)]
                    else:
                        prefix = package_parts[: len(package_parts) - node.level + 1] if node.level else []
                        if node.module:
                            prefix.extend(node.module.split("."))
                        base_module = ".".join(prefix)
                        base_matches = module_paths.get(base_module, [])
                        modules = [base_module] if base_matches else []
                        base_is_package = not base_matches or all(
                            Path(match).name == "__init__.py" for match in base_matches
                        )
                        if base_is_package:
                            for alias in node.names:
                                child = f"{base_module}.{alias.name}"
                                if alias.name != "*" and child in module_paths:
                                    modules.append(child)
                        if not modules:
                            modules = [base_module]
                        imports = [
                            (module, node.lineno, bool(node.level))
                            for module in dict.fromkeys(modules) if module
                        ]

                for imported, line, is_relative in imports:
                    target = resolve_local(imported)
                    if target == "":
                        unresolved.append({"source": rel, "module": imported, "line": line, "reason": "ambiguous_local_module"})
                    elif target:
                        edges.append({"source": rel, "target": target, "module": imported, "line": line})
                    elif is_relative:
                        unresolved.append({"source": rel, "module": imported, "line": line, "reason": "unresolved_relative_import"})
                    elif imported.partition(".")[0] in local_top_levels:
                        unresolved.append({"source": rel, "module": imported, "line": line, "reason": "unresolved_local_module"})
                    elif imported.split(".", 1)[0] in sys.stdlib_module_names:
                        stdlib_count += 1
                    else:
                        external.append({"source": rel, "module": imported, "line": line})
                    if len(edges) + len(unresolved) + len(external) >= edge_limit:
                        complete = False
                        errors.append("edge_limit")
                        break
                if len(edges) + len(unresolved) + len(external) >= edge_limit:
                    break

        hubs = [
            {"path": path, "in_degree": count}
            for path, count in Counter(
                target for _source, target in dict.fromkeys(
                    (edge["source"], edge["target"]) for edge in edges
                )
            ).most_common(10)
        ]
        has_api = bool(layers["presentation"])
        has_services = bool(layers["core_services"])
        has_cli = bool(layers["entrypoints"])
        if has_api and has_services:
            pattern = "Layered Service / Web Application"
        elif has_cli and has_services:
            pattern = "Modular CLI Application"
        elif has_services:
            pattern = "Library / Application Engine"
        else:
            pattern = "Package / Module Collection"
        graph_complete = complete and not unresolved and "edge_limit" not in errors
        graph = {
            "scope": "bounded Python AST imports resolved against unique local source modules",
            "nodes": len(path_modules), "edge_count": len(edges), "edges": edges[:sample_limit], "hub_paths": hubs,
            "unresolved_count": len(unresolved), "unresolved": unresolved[:sample_limit],
            "external_import_count": len(external), "external_imports": external[:sample_limit],
            "stdlib_import_count": stdlib_count, "complete": graph_complete,
            "truncated": any(len(items) > sample_limit for items in (edges, unresolved, external)),
        }
        lines = [
            f"# Architecture Topology: {resolved_root.name}",
            f"**Architecture hypothesis (heuristic)**: {pattern}",
            "", "## Heuristic path labels",
        ]
        for name, paths in layers.items():
            if paths:
                lines.append(f"- **{name.replace('_', ' ').title()}** ({len(paths)}): `{', '.join(paths[:4])}`")
        lines.extend(["", f"## Local Python import graph: {len(edges)} edges; complete={str(graph_complete).lower()}"])
        for edge in edges[:8]:
            lines.append(f"- `{edge['source']}:{edge['line']}` -> `{edge['target']}`")
        return {
            "success": True, "root": root_str,
            "architecture_pattern_hypothesis": pattern,
            "architecture_pattern_verified": False,
            "heuristic_layers": layers, "module_graph": graph,
            "summary_markdown": "\n".join(lines),
            "coverage": {
                "complete": complete,
                "inventory_scope": "eligible Python source under recognized roots; docs, plans, tests and fixtures excluded",
                "deadline_kind": "cooperative", "files_seen": len(eligible),
                "files_read": files_read, "files_skipped": skipped,
                "parse_errors": parse_errors, "bytes_read": total_bytes,
                "file_limit": file_limit, "per_file_bytes_limit": per_file_limit,
                "aggregate_bytes_limit": total_bytes_limit, "excluded_dirs": excluded_dirs,
                "errors": sorted(set(errors)), "module_graph_resolved": True,
                "module_graph_complete": graph_complete,
                "architecture_pattern_basis": "filename and path heuristics",
                "architecture_pattern_verified": False,
            },
            "import_scope": "Python AST imports resolved only against unique local modules in the bounded source inventory",
        }

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
        resolved_root = Path(self._root(root))
        secret_patterns = _SECURITY_AUDIT_SECRETS
        code_smell_patterns = _SECURITY_AUDIT_SMELLS

        findings: list[dict[str, Any]] = []
        candidate_files = self.repo_tools.iter_files(str(resolved_root))
        scanned_files = 0
        eligible_files = 0
        skipped_files = 0
        scan_complete = True
        limit_reached = False
        scanned_bytes = 0
        scan_errors: list[dict[str, str]] = []
        deadline = time.monotonic() + 30.0
        max_file_bytes = min(2_000_000, max(1, int(getattr(self.repo_tools, "max_file_bytes", 2_000_000))))
        stop_reason = ""


        for f in candidate_files:
            if len(findings) >= limit:
                limit_reached = True
                scan_complete = False
                stop_reason = "findings_limit"
                break
            if time.monotonic() >= deadline or scanned_bytes >= 32 * 1024 * 1024:
                scan_complete = False
                stop_reason = "time_or_byte_budget"
                break
            if f.suffix.lower() not in {".py", ".ts", ".js", ".cs", ".go", ".rs", ".json", ".toml", ".yaml", ".yml", ".env"}:
                skipped_files += 1
                continue
            eligible_files += 1
            rel = str(f.relative_to(resolved_root)).replace("\\", "/")
            try:
                target = f.resolve(strict=True)
                target.relative_to(resolved_root)
                import stat
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                descriptor = os.open(target, flags)
                try:
                    opened = os.fstat(descriptor)
                    if not stat.S_ISREG(opened.st_mode):
                        raise ValueError("security source is not a regular file")
                    source = os.fdopen(descriptor, "rb")
                    descriptor = -1
                    with source:
                        remaining_bytes = 32 * 1024 * 1024 - scanned_bytes
                        read_bound = min(max_file_bytes, remaining_bytes)
                        raw = source.read(read_bound + 1)
                        after_read = os.fstat(source.fileno())
                    target.resolve(strict=True).relative_to(resolved_root)
                    current = target.stat()
                    opened_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    after_state = (after_read.st_dev, after_read.st_ino, after_read.st_size, after_read.st_mtime_ns, after_read.st_ctime_ns)
                    if opened_state != after_state or (opened.st_dev, opened.st_ino, opened.st_size) != (current.st_dev, current.st_ino, current.st_size):
                        raise ValueError("security source changed during read")
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
                scanned_bytes += len(raw)
                if len(raw) > read_bound:
                    raise ValueError("security source exceeds file or aggregate byte bound")
                txt = raw.decode("utf-8", errors="replace")
                lines = txt.splitlines()
                scanned_files += 1
                for i, line in enumerate(lines, 1):
                    if len(findings) >= limit or (i % 1024 == 0 and time.monotonic() >= deadline):
                        scan_complete = False
                        limit_reached = len(findings) >= limit
                        stop_reason = "findings_limit" if limit_reached else "time_budget"
                        break
                    stripped = line.strip()
                    if stripped.startswith(("#", "//", "/*", "*")):
                        continue

                    for name, pat in secret_patterns:
                        if pat.search(line):
                            findings.append({
                                "severity": "HIGH",
                                "type": "secret_leak",
                                "title": name,
                                "path": rel,
                                "line": i,
                                "snippet": "[credential-like value omitted]",
                            })
                            break

                for name, pat in code_smell_patterns:
                    if len(findings) >= limit or time.monotonic() >= deadline:
                        scan_complete = False
                        limit_reached = len(findings) >= limit
                        stop_reason = "findings_limit" if limit_reached else "time_budget"
                        break
                    if name == "Shell Injection Risk":
                        if not rel.lower().endswith(".py"):
                            continue
                        try:
                            line_numbers = _python_shell_injection_lines(txt)
                        except (SyntaxError, ValueError):
                            scan_complete = False
                            if len(scan_errors) < 20:
                                scan_errors.append({"path": rel, "error_type": "ASTParseError"})
                            line_numbers = []
                    elif name == "Unsafe eval/exec" and rel.lower().endswith(".py"):
                        try:
                            parsed = ast.parse(txt)
                        except (SyntaxError, ValueError):
                            scan_complete = False
                            if len(scan_errors) < 20:
                                scan_errors.append({"path": rel, "error_type": "ASTParseError"})
                            line_numbers = []
                        else:
                            line_numbers = sorted(
                                {
                                    node.lineno
                                    for node in ast.walk(parsed)
                                    if isinstance(node, ast.Call)
                                    and (
                                        isinstance(node.func, ast.Name)
                                        and node.func.id in {"eval", "exec"}
                                        or isinstance(node.func, ast.Attribute)
                                        and node.func.attr in {"eval", "exec"}
                                        and isinstance(node.func.value, ast.Name)
                                        and node.func.value.id in {"builtins", "__builtins__"}
                                    )
                                }
                            )
                    else:
                        line_numbers = sorted(
                            {
                                txt[:match.start()].count("\n") + 1
                                for match in pat.finditer(txt)
                            }
                        )
                    for line_no in line_numbers:
                        matched_line = lines[line_no - 1].strip() if line_no <= len(lines) else ""
                        if matched_line.startswith(("#", "//", "/*", "*")):
                            continue
                        if not any(fd["path"] == rel and fd["line"] == line_no and fd["title"] == name for fd in findings):
                            findings.append({
                                "severity": "MEDIUM",
                                "type": "code_vulnerability",
                                "title": name,
                                "path": rel,
                                "line": line_no,
                                "snippet": matched_line[:120] or pat.pattern[:120],
                            })
                        if len(findings) >= limit:
                            limit_reached = True
                            scan_complete = False
                            stop_reason = "findings_limit"
                            break
            except Exception as exc:
                scan_complete = False
                skipped_files += 1
                if len(scan_errors) < 20:
                    scan_errors.append({
                        "path": rel,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:200],
                    })


        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
        med_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")
        test_findings = []
        for finding in findings:
            rel_path = str(finding.get("path", ""))
            is_test = rel_path.casefold().startswith("tests/") or Path(rel_path).name.casefold().startswith("test_")
            finding["is_test"] = is_test
            finding["classification"] = "untriaged"
            if is_test:
                test_findings.append(finding)
        untriaged_high = sum(
            1 for finding in findings
            if finding.get("severity") == "HIGH"
        )

        return {
            "success": True,
            "root": str(resolved_root),
            "findings_count": len(findings),
            "high_severity_count": high_count,
            "medium_severity_count": med_count,
            "untriaged_high_severity_count": untriaged_high,
            "test_findings_count": len(test_findings),
            "findings_present": bool(findings),
            "release_blocking_findings": untriaged_high,
            "triage_complete": not findings,
            "scanned_files": scanned_files,
            "eligible_files": eligible_files,
            "eligible_files_total": None,
            "skipped_files": skipped_files,
            "scanned_bytes": scanned_bytes,
            "scan_complete": scan_complete,
            "limit_reached": limit_reached,
            "stop_reason": stop_reason,
            "scan_errors": scan_errors,
            "coverage_scope": "project-filtered repository iterator; counts cover visited entries",
            "is_clean": not findings and scan_complete,
            "findings": findings[:limit],
        }

    def split_changes(self, root: str, changed_files: list[str] | None = None) -> dict[str, Any]:
        """Cluster modified repo files into atomic, cohesive commit or PR chunks."""
        resolved_root = Path(self._root(root))
        files = list(changed_files or [])
        if not files:
            try:
                cp = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(resolved_root),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.git_status_timeout,
                    **hidden_run_kwargs(),
                )
                if cp.returncode == 0:
                    for line in cp.stdout.splitlines():
                        parts = line.strip().split(maxsplit=1)
                        if len(parts) == 2:
                            files.append(parts[1].replace("\\", "/"))
            except Exception:
                pass

        if not files:
            return {"success": True, "clusters": [], "total_files": 0, "message": "No changed files detected"}

        categories: dict[str, list[str]] = {
            "docs": [],
            "config": [],
            "core": [],
            "api_or_services": [],
            "models_or_schemas": [],
            "tests": [],
            "other": [],
        }

        for f in files:
            norm = f.lower().replace("\\", "/")
            if norm.startswith("docs/") or norm.endswith((".md", ".rst", ".txt")):
                categories["docs"].append(f)
            elif norm.endswith((".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".lock")) or "config" in norm:
                categories["config"].append(f)
            elif "test" in norm or norm.startswith("tests/"):
                categories["tests"].append(f)
            elif any(k in norm for k in ("model", "schema", "entity", "dto")):
                categories["models_or_schemas"].append(f)
            elif any(k in norm for k in ("api", "service", "route", "controller", "endpoint")):
                categories["api_or_services"].append(f)
            elif any(k in norm for k in ("core", "engine", "util", "helper", "lib")):
                categories["core"].append(f)
            else:
                categories["other"].append(f)

        clusters = []
        cluster_id = 1
        order = ["models_or_schemas", "core", "api_or_services", "tests", "config", "docs", "other"]
        for cat in order:
            cat_files = categories[cat]
            if cat_files:
                clusters.append({
                    "cluster_id": cluster_id,
                    "name": cat.replace("_", " ").title(),
                    "category": cat,
                    "suggested_commit_message": f"feat({cat}): update {cat.replace('_', ' ')} components",
                    "files": sorted(cat_files),
                })
                cluster_id += 1

        return {
            "success": True,
            "root": str(resolved_root),
            "total_files": len(files),
            "cluster_count": len(clusters),
            "clusters": clusters,
        }

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
        resolved_root = Path(self._root(root))
        target_paths: list[Path] = []
        unsupported_files: list[dict[str, str]] = []
        parse_errors: list[dict[str, Any]] = []
        scan_errors: list[dict[str, Any]] = []
        read_errors: list[dict[str, Any]] = []
        if not resolved_root.is_dir():
            return {
                "success": False,
                "complete": False,
                "error": "root_not_directory",
                "root": str(resolved_root),
                "files_checked": 0,
                "supported_languages": ["python"],
                "parse_errors": [],
                "scan_errors": [],
                "read_errors": [],
                "unsupported_files": [],
                "truncated": False,
                "violation_count": 0,
                "violations": [],
            }
        if path:
            candidate = (resolved_root / path).resolve(strict=False)
            if candidate.is_file():
                if not candidate.is_relative_to(resolved_root):
                    return {
                        "success": False,
                        "complete": False,
                        "error": "path_outside_root",
                        "root": str(resolved_root),
                        "files_checked": 0,
                        "supported_languages": ["python"],
                        "parse_errors": [],
                        "scan_errors": [],
                        "read_errors": [],
                        "unsupported_files": [],
                        "truncated": False,
                        "violation_count": 0,
                        "violations": [],
                    }
                if candidate.suffix.lower() == ".py":
                    target_paths.append(candidate)
                else:
                    unsupported_files.append({
                        "path": str(candidate.relative_to(resolved_root)).replace("\\", "/"),
                        "language": candidate.suffix.lower().lstrip(".") or "unknown",
                        "reason": "unsupported_language",
                    })
            else:
                return {
                    "success": False,
                    "complete": False,
                    "error": f"path not found: {path}",
                    "root": str(resolved_root),
                    "files_checked": 0,
                    "supported_languages": ["python"],
                    "parse_errors": [],
                    "scan_errors": [],
                    "read_errors": [],
                    "unsupported_files": [],
                    "truncated": False,
                    "violation_count": 0,
                    "violations": [],
                }
        else:
            truncated = False
            def record_scan_error(exc: OSError) -> None:
                scan_errors.append({
                    "path": str(exc.filename or resolved_root),
                    "reason": type(exc).__name__,
                    "message": exc.strerror or str(exc),
                })

            ignored = {
                ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "tests", "tool-envs",
                *getattr(self.repo_tools, "ignore_dirs", set()),
            }
            for dirpath, dirnames, filenames in os.walk(resolved_root, onerror=record_scan_error):
                # Repository-wide audits should cover shipped runtime code, not
                # test setup commands or managed dependency environments. An
                # explicit path remains available for fixture-level checks.
                rel_dir = os.path.relpath(dirpath, resolved_root).replace("\\", "/")
                if rel_dir != "." and (is_root_archive_path(rel_dir) or any(part.startswith(".") for part in rel_dir.split("/"))):
                    dirnames[:] = []
                    continue
                dirnames[:] = [
                    d for d in dirnames
                    if d not in ignored
                    and not d.startswith(".")
                    and not is_root_archive_path(d if rel_dir == "." else f"{rel_dir}/{d}")
                ]
                for f in filenames:
                    rel_file = f if rel_dir == "." else f"{rel_dir}/{f}"
                    if is_root_archive_path(rel_file) or any(part.startswith(".") for part in rel_file.split("/")[:-1]):
                        continue
                    if f.endswith(".py"):
                        if len(target_paths) >= 150:
                            truncated = True
                            break
                        target_paths.append(Path(dirpath) / f)
                if truncated:
                    break

        if path:
            truncated = False

        violations: list[dict[str, Any]] = []

        class InvariantVisitor(ast.NodeVisitor):
            def __init__(self, rel_path: str):
                self.rel_path = rel_path
                self.with_items: set[int] = set()

            def visit_With(self, node: ast.With) -> None:
                for item in node.items:
                    if isinstance(item.context_expr, ast.Call):
                        self.with_items.add(id(item.context_expr))
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                    if isinstance(node.func.value, ast.Name):
                        full_name = f"{node.func.value.id}.{func_name}"
                        if full_name in ("subprocess.run", "requests.get", "requests.post", "requests.put", "requests.delete", "urllib.request.urlopen"):
                            has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
                            if not has_timeout:
                                violations.append({
                                    "path": self.rel_path,
                                    "line": node.lineno,
                                    "col": node.col_offset,
                                    "rule": "missing_timeout",
                                    "message": f"Call to '{full_name}' lacks explicit 'timeout' parameter",
                                    "severity": "high",
                                })

                # ``os.open`` is a descriptor-level API, not a file object that
                # needs a context manager.  ``subprocess.Popen`` likewise has
                # no timeout argument; callers must bound communicate/wait.
                if isinstance(node.func, ast.Name) and func_name == "open" and id(node) not in self.with_items:
                    violations.append({
                        "path": self.rel_path,
                        "line": node.lineno,
                        "col": node.col_offset,
                        "rule": "missing_with_open",
                        "message": "File 'open(...)' used without 'with' statement context manager",
                        "severity": "medium",
                    })

                self.generic_visit(node)

        for p in target_paths:
            rel = str(p.relative_to(resolved_root)).replace("\\", "/")
            try:
                code = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(code, filename=rel)
            except OSError as exc:
                read_errors.append({
                    "path": rel,
                    "reason": type(exc).__name__,
                    "message": str(exc),
                })
                continue
            except SyntaxError as exc:
                parse_errors.append({
                    "path": rel,
                    "reason": "syntax_error",
                    "line": exc.lineno,
                    "column": exc.offset,
                    "message": exc.msg,
                })
                continue
            visitor = InvariantVisitor(rel)
            visitor.visit(tree)

        complete = not parse_errors and not scan_errors and not read_errors and not unsupported_files and not truncated
        return {
            "success": complete,
            "complete": complete,
            "root": str(resolved_root),
            "files_checked": len(target_paths),
            "supported_languages": ["python"],
            "parse_errors": parse_errors,
            "scan_errors": scan_errors,
            "read_errors": read_errors,
            "unsupported_files": unsupported_files,
            "truncated": truncated,
            "violation_count": len(violations),
            "violations": violations[:100],
        }

    def generate_dataset(
        self,
        root: str,
        schema_or_model: dict[str, Any] | list[Any],
        count: int = 10,
        format: str = "json",
    ) -> dict[str, Any]:
        """Generate synthetic test datasets and seed data adhering to a field schema."""
        import uuid
        resolved_root = Path(self._root(root))
        n = max(1, min(int(count), 1000))
        fields: dict[str, str] = {}
        if isinstance(schema_or_model, dict):
            fields = {str(k): str(v).lower() for k, v in schema_or_model.items()}
        elif isinstance(schema_or_model, list):
            for item in schema_or_model:
                if isinstance(item, dict):
                    fields[str(item.get("name", "field"))] = str(item.get("type", "str")).lower()
                else:
                    fields[str(item)] = "str"
        else:
            fields = {"id": "uuid", "name": "str", "status": "str"}

        dataset_seed = repr(tuple(fields.items()))
        rows: list[dict[str, Any]] = []
        for i in range(1, n + 1):
            row: dict[str, Any] = {}
            for col, ctype in fields.items():
                if "uuid" in ctype or col.lower() in ("id", "guid"):
                    row[col] = uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{dataset_seed}:{col}:{i}",
                    ).hex[:12]
                elif "int" in ctype or col.lower() in ("age", "count", "seq", "index"):
                    row[col] = i * 10
                elif "float" in ctype or col.lower() in ("price", "amount", "score", "rate"):
                    row[col] = round(10.0 + (i * 3.5), 2)
                elif "bool" in ctype or col.lower() in ("active", "enabled", "valid", "is_admin"):
                    row[col] = (i % 2 == 0)
                elif "email" in ctype or "email" in col.lower():
                    row[col] = f"user_{i}@example.com"
                elif "date" in ctype or "time" in col.lower():
                    row[col] = f"2026-09-12T12:{i % 60:02d}:00Z"
                else:
                    row[col] = f"{col.capitalize()}_{i}"
            rows.append(row)

        fmt = format.lower()
        if fmt == "csv":
            import csv
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=list(fields.keys()))
            writer.writeheader()
            writer.writerows(rows)
            rendered = out.getvalue()
        elif fmt in ("sqlite", "sql"):
            lines = []
            table = "test_dataset"
            cols = ", ".join(f'"{c}"' for c in fields.keys())
            for r in rows:
                vals = ", ".join(f"'{v}'" if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else str(v) for v in r.values())
                lines.append(f"INSERT INTO {table} ({cols}) VALUES ({vals});")
            rendered = "\n".join(lines)
        else:
            rendered = json_dumps(rows, indent=2)

        return {
            "success": True,
            "root": str(resolved_root),
            "count": len(rows),
            "format": fmt,
            "fields": list(fields.keys()),
            "data": rendered,
            "rows": rows[:50],
        }

    def profile_digest(self, profile_path: str, top_n: int = 15) -> dict[str, Any]:
        """Digest a cProfile / pstats binary profile or flamegraph trace into top bottleneck functions."""
        p = Path(profile_path).expanduser().resolve(strict=False)
        if not p.exists():
            return {"success": False, "error": f"profile file not found: {profile_path}"}

        limit = max(1, min(int(top_n), 100))
        entries: list[dict[str, Any]] = []

        try:
            import pstats
            stats = pstats.Stats(str(p))
            stats.sort_stats("cumulative")
            sorted_items = sorted(stats.stats.items(), key=lambda kv: kv[1][3], reverse=True)
            for (fn_file, fn_line, fn_name), (cc, nc, tt, ct, _callers) in sorted_items[:limit]:
                entries.append({
                    "function": fn_name,
                    "filename": Path(fn_file).name,
                    "filepath": fn_file,
                    "line": fn_line,
                    "calls": nc,
                    "primitive_calls": cc,
                    "total_time_seconds": round(float(tt), 4),
                    "cumulative_time_seconds": round(float(ct), 4),
                    "time_per_call": round(float(ct) / max(1, nc), 6),
                })
            return {
                "success": True,
                "profile_path": str(p),
                "format": "cProfile_pstats",
                "total_functions_analyzed": len(stats.stats),
                "top_functions": entries,
            }
        except Exception:
            entries.clear()

        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw)
            if isinstance(data, dict) and "traceEvents" in data:
                events = data.get("traceEvents", [])
                if not isinstance(events, list):
                    return {
                        "success": False,
                        "error": "failed to parse profile: traceEvents must be a JSON array",
                    }
                durations: dict[str, float] = {}
                counts: dict[str, int] = {}
                for ev in events:
                    if not isinstance(ev, dict):
                        continue
                    name = ev.get("name", "")
                    raw_duration = ev.get("dur", 0)
                    if not isinstance(name, str) or not name.strip():
                        continue
                    if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
                        continue
                    duration = float(raw_duration)
                    if not math.isfinite(duration) or duration <= 0:
                        continue
                    total_duration = durations.get(name, 0.0) + duration
                    if not math.isfinite(total_duration):
                        continue
                    durations[name] = total_duration
                    counts[name] = counts.get(name, 0) + 1
                sorted_events = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)
                for name, total_dur in sorted_events[:limit]:
                    entries.append({
                        "function": name,
                        "cumulative_time_microseconds": round(total_dur, 2),
                        "calls": counts.get(name, 1),
                    })
                return {
                    "success": True,
                    "profile_path": str(p),
                    "format": "chrome_trace",
                    "top_functions": entries,
                }
        except Exception:
            entries.clear()

        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].replace(".", "").isdigit():
                    entries.append({"summary": line.strip()})
                    if len(entries) >= limit:
                        break
            if not entries:
                return {"success": False, "error": "failed to parse profile: no profile records found"}
            return {
                "success": True,
                "profile_path": str(p),
                "format": "text_profile",
                "top_functions": entries,
            }
        except Exception as exc:
            return {"success": False, "error": f"failed to parse profile: {exc}"}

    def _find_python_relations(
        self, root: str, symbol: str, limit: int, offset: int, direction: str,
    ) -> dict[str, Any]:
        bounds_error = pagination_bounds_error(limit, offset)
        if bounds_error:
            return {"success": False, "status_code": 400, "terminal": True, "retryable": False, "error": bounds_error}
        p_root = Path(self._root(root)).resolve()
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}", "terminal": True, "retryable": False}
        if not isinstance(symbol, str) or not symbol.strip():
            return {"success": False, "status_code": 400, "error": "symbol must be a non-empty string", "terminal": True, "retryable": False}

        sym = symbol.strip()
        if (direction == "callers" and ("::" in sym or "." in sym)) or (direction == "callees" and "." in sym):
            return {
                "success": False, "terminal": True, "retryable": False,
                "error": "deterministic Python relation fallback requires an unqualified symbol or canonical :: qualification",
                "coverage": {"complete": False, "scope": "python_ast", "resolution": "unsupported_qualification"},
            }
        result_key = "callers" if direction == "callers" else "callees"
        page: list[dict[str, Any]] = []
        relation_count = 0
        skipped_files = 0
        scanned_files = 0
        scanned_bytes = 0
        incomplete = False
        scan_stopped = False
        incomplete_reasons: set[str] = set()
        deadline = time.monotonic() + _RELATION_SCAN_MAX_SECONDS
        max_files = max(1, int(getattr(self.repo_tools, "python_fallback_max_files", 8000)))
        max_file_bytes = max(1, int(getattr(self.repo_tools, "max_file_bytes", 2_000_000)))
        max_total_bytes = min(64_000_000, max_file_bytes * min(max_files, 32))
        max_directories = min(10_000, max_files * 4)
        excluded = {str(value).lower() for value in getattr(self.repo_tools, "ignore_dirs", set())}
        excluded.update({".git", ".venv", "venv", "node_modules", "vendor", "build", "dist"})
        directories_seen = 0
        source_files_seen = 0
        unsupported_languages: set[str] = set()
        matching_definitions: set[str] = set()

        def walk_error(_error: OSError) -> None:
            nonlocal incomplete
            incomplete = True
            incomplete_reasons.add("directory_walk_error")

        def call_name(node: ast.AST) -> str | None:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return node.attr
            return None

        for directory, dirnames, filenames in os.walk(p_root, topdown=True, onerror=walk_error, followlinks=False):
            if time.monotonic() >= deadline:
                incomplete = True
                scan_stopped = True
                incomplete_reasons.add("time_budget_exhausted")
                break
            directories_seen += 1
            if directories_seen > max_directories:
                incomplete = True
                scan_stopped = True
                incomplete_reasons.add("directory_budget_exhausted")
                break
            kept_dirs = []
            for name in sorted(dirnames):
                if name.lower() in excluded or name.startswith("."):
                    continue
                directory_path = Path(directory) / name
                try:
                    if _is_symlink_or_reparse_point(directory_path):
                        incomplete = True
                        incomplete_reasons.add("reparse_point_skipped")
                        continue
                    directory_path.resolve().relative_to(p_root)
                    kept_dirs.append(name)
                except (OSError, ValueError):
                    incomplete = True
                    incomplete_reasons.add("directory_path_unverified")
            dirnames[:] = kept_dirs
            filenames.sort()
            for filename in filenames:
                if time.monotonic() >= deadline:
                    incomplete = True
                    scan_stopped = True
                    incomplete_reasons.add("time_budget_exhausted")
                    break
                path = Path(directory) / filename
                extension = path.suffix.lower()
                if extension == ".py":
                    pass
                elif extension in {".cs", ".go", ".java", ".js", ".jsx", ".ts", ".tsx", ".rs", ".php", ".rb", ".cpp", ".c", ".h", ".hpp", ".kt", ".swift"}:
                    unsupported_languages.add(extension.lstrip("."))
                    continue
                else:
                    continue
                relative = path.relative_to(p_root).as_posix()
                if is_root_archive_path(relative):
                    continue
                source_files_seen += 1
                if source_files_seen > max_files:
                    incomplete = True
                    scan_stopped = True
                    incomplete_reasons.add("file_budget_exhausted")
                    break
                try:
                    if _is_symlink_or_reparse_point(path):
                        skipped_files += 1
                        incomplete = True
                        incomplete_reasons.add("reparse_point_skipped")
                        continue
                    resolved_path = path.resolve(strict=True)
                    resolved_path.relative_to(p_root)
                    _digest, lines = self.repo_tools._read_snapshot(path, max_bytes=max_file_bytes)
                    content = "\n".join(lines)
                    current_bytes = len(content.encode("utf-8", errors="replace"))
                    if scanned_bytes + current_bytes > max_total_bytes:
                        incomplete = True
                        scan_stopped = True
                        incomplete_reasons.add("byte_budget_exhausted")
                        break
                    scanned_bytes += current_bytes
                    scanned_files += 1
                    tree = ast.parse(content, filename=str(path))
                except (OSError, SyntaxError, UnicodeError, RecursionError, ValueError):
                    skipped_files += 1
                    incomplete = True
                    incomplete_reasons.add("file_read_or_parse_error")
                    continue

                module_name = relative[:-3].replace("/", ".")
                if module_name.endswith(".__init__"):
                    module_name = module_name[:-9]
                module_identity = module_name.replace(".", "::")

                class _RelationVisitor(ast.NodeVisitor):
                    def __init__(self):
                        self.scope_stack: list[str] = []

                    def _visit_scope(self, node):
                        if time.monotonic() >= deadline:
                            nonlocal_incomplete[0] = True
                            return
                        self.scope_stack.append(node.name)
                        target_definition_name = sym.rsplit("::", 1)[-1]
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_definition_name:
                            matching_definitions.add("::".join([part for part in (module_identity, *self.scope_stack) if part]))
                        self.generic_visit(node)
                        self.scope_stack.pop()

                    visit_FunctionDef = _visit_scope
                    visit_AsyncFunctionDef = _visit_scope
                    visit_ClassDef = _visit_scope

                    def generic_visit(self, node):
                        if time.monotonic() >= deadline:
                            nonlocal_incomplete[0] = True
                            return
                        super().generic_visit(node)

                    def visit_Call(self, node):
                        nonlocal relation_count
                        if time.monotonic() >= deadline:
                            nonlocal_incomplete[0] = True
                            return
                        target = call_name(node.func)
                        scope = ".".join(self.scope_stack) if self.scope_stack else "<module>"
                        if direction == "callers":
                            matched = target == sym
                        else:
                            qualified_scope = "::".join([part for part in (module_identity, *self.scope_stack) if part])
                            if "::" in sym or "." in sym:
                                scope_matches = sym == qualified_scope
                            else:
                                scope_matches = bool(self.scope_stack and self.scope_stack[-1] == sym)
                            matched = bool(scope_matches and target)
                            if scope_matches and target is None:
                                nonlocal_incomplete[0] = True
                        if matched:
                            line_index = max(0, node.lineno - 1)
                            snippet = lines[line_index].strip() if line_index < len(lines) else ""
                            if direction == "callers":
                                item = {
                                    "file": relative, "line": node.lineno, "col": node.col_offset,
                                    "caller": scope, "callee": sym, "kind": "calls",
                                    "match_scope": "syntactic_name", "snippet": snippet[:160],
                                }
                            else:
                                item = {
                                    "file": relative, "line": node.lineno, "col": node.col_offset,
                                    "caller": scope, "callee": target, "kind": "calls",
                                    "match_scope": "syntactic_name", "snippet": snippet[:160],
                                }
                            if offset <= relation_count < offset + limit:
                                page.append(item)
                            relation_count += 1
                        self.generic_visit(node)

                nonlocal_incomplete = [False]
                visitor = _RelationVisitor()
                visitor.visit(tree)
                if nonlocal_incomplete[0]:
                    incomplete = True
                    scan_stopped = True
                    incomplete_reasons.add("time_budget_exhausted")
            if scan_stopped:
                break

        if unsupported_languages:
            incomplete = True
            incomplete_reasons.add("unsupported_languages_present")
        if direction == "callees":
            if "::" in sym:
                matching = {definition for definition in matching_definitions if definition == sym}
            else:
                matching = {definition for definition in matching_definitions if definition.endswith("::" + sym)}
            if len(matching) > 1:
                return {
                    "success": False, "status_code": 422, "terminal": True, "retryable": False,
                    "error": "deterministic callee fallback requires a uniquely qualified function symbol",
                    "symbol": sym, "callees": [], "count": 0, "offset": offset, "limit": limit,
                    "coverage": {"complete": False, "scan_complete": not incomplete, "scope": "python_ast", "resolution": "ambiguous_unqualified_definition"},
                }
            elif not matching:
                if incomplete:
                    return {
                        "success": False, "status_code": 503, "terminal": True, "retryable": False,
                        "error": "bounded deterministic scan could not resolve the requested Python function completely",
                        "symbol": sym, "callees": [], "count": 0, "offset": offset, "limit": limit,
                        "coverage": {
                            "complete": False, "scan_complete": False, "scope": "python_ast",
                            "resolution": "incomplete_scan", "incomplete_reasons": sorted(incomplete_reasons),
                        },
                    }
                return {
                    "success": False, "status_code": 422, "terminal": True, "retryable": False,
                    "error": "deterministic callee fallback could not resolve the requested Python function",
                    "symbol": sym, "callees": [], "count": 0, "offset": offset, "limit": limit,
                    "coverage": {"complete": False, "scan_complete": not incomplete, "scope": "python_ast", "resolution": "definition_not_found"},
                }

        count_key = "caller_count" if direction == "callers" else "callee_count"
        result: dict[str, Any] = {
            "success": True,
            "symbol": sym,
            result_key: page,
            count_key: len(page),
            "count": len(page),
            "returned_count": len(page),
            "offset": offset,
            "limit": limit,
            "truncated": incomplete,
            "coverage": {
                "complete": not incomplete and offset == 0 and len(page) == relation_count,
                "scan_complete": not incomplete,
                "scope": "python_ast",
                "resolution": "syntactic_name",
                "returned": len(page),
                "limit": limit,
                "offset": offset,
                "scanned_files": scanned_files,
                "skipped_files": skipped_files,
                "scanned_bytes": scanned_bytes,
                "incomplete_reasons": sorted(incomplete_reasons),
                "unsupported_languages": sorted(unsupported_languages),
            },
            "freshness": {"status": "not_checked"},
        }
        if not incomplete:
            result["total_matches"] = relation_count
            has_more = offset + len(page) < relation_count
            result["has_more"] = has_more
            result["truncated"] = has_more
            if has_more:
                result["next_offset"] = offset + len(page)
        return result

    def find_callers(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find Python call sites targeting a symbol, in stable bounded pages."""
        return self._find_python_relations(root, symbol, limit, offset, "callers")

    def find_callees(self, root: str, symbol: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Find Python calls made by a named function, in stable bounded pages."""
        return self._find_python_relations(root, symbol, limit, offset, "callees")

    def find_dead_code(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Detect potentially dead/uncalled functions and classes in repository."""
        if self.code_index is not None:
            try:
                st = self.code_index.status(root)
                if st.get("symbols", 0) > 0:
                    res = self.code_index.find_dead_code(root, limit=limit)
                    if res.get("success"):
                        return res
            except Exception:
                pass

        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}

        defs: dict[str, dict[str, Any]] = {}
        usages: set[str] = set()

        for p in p_root.rglob("*.py"):
            if not p.is_file():
                continue
            rel_parts = p.relative_to(p_root).parts
            if any(part.startswith((".", "node_modules", "venv", ".git", "test")) for part in rel_parts):
                continue
            rel = str(p.relative_to(p_root)).replace("\\", "/")
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(p))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_") and node.name not in ("main", "run", "cli", "app"):
                            defs[f"{rel}::{node.name}"] = {
                                "file": rel, "name": node.name, "line": node.lineno, "kind": "function"
                            }
                    elif isinstance(node, ast.ClassDef):
                        if not node.name.startswith("_"):
                            defs[f"{rel}::{node.name}"] = {
                                "file": rel, "name": node.name, "line": node.lineno, "kind": "class"
                            }
                    elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                        usages.add(node.id)
                    elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                        usages.add(node.attr)
            except Exception:
                continue

        dead_candidates: list[dict[str, Any]] = []
        for key, item in defs.items():
            if item["name"] not in usages:
                dead_candidates.append(item)
                if len(dead_candidates) >= limit:
                    break

        return {
            "success": True,
            "candidate_count": len(dead_candidates),
            "dead_code": dead_candidates,
            "dead_symbols": dead_candidates,
        }

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
        """Scan repository or specific file for leaked secrets, API keys, and credentials."""
        if scan_git_history and (
            not isinstance(commit_depth, int) or isinstance(commit_depth, bool)
            or not 1 <= commit_depth <= 100
        ):
            return {
                "success": False, "error": "commit_depth must be an integer from 1 to 100",
                "error_code": "invalid_commit_depth",
                "scan_complete": False, "clean": False, "scanned_git_history": False,
                "git_history_status": "invalid_commit_depth",
                "status_code": 400, "terminal": True, "retryable": False,
            }
        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}
        scan_root = p_root.resolve(strict=True)
        started = time.monotonic()
        deadline = started + _SECRET_SCAN_MAX_SECONDS
        history_pathspec: str | None = None
        if scan_git_history and path is not None:
            requested_history_path = Path(path)
            history_target = requested_history_path if requested_history_path.is_absolute() else scan_root / requested_history_path
            try:
                normalized_history_path = history_target.resolve(strict=False)
                history_pathspec = normalized_history_path.relative_to(scan_root).as_posix()
                if not history_pathspec or history_pathspec == ".":
                    raise ValueError
            except (OSError, ValueError):
                return {
                    "success": False, "error": "history path must resolve within scan root",
                    "error_code": "invalid_pathspec",
                    "scan_complete": False, "clean": False, "scanned_git_history": False,
                    "git_history_status": "invalid_pathspec",
                    "status_code": 400, "terminal": True, "retryable": False,
                }
        excluded = {".git", "node_modules", "venv", ".venv", "tool-envs", "state", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox"}
        binary_suffixes = {".png", ".jpg", ".jpeg", ".exe", ".bin", ".whl", ".pyc", ".db", ".sqlite3", ".zip", ".tar", ".gz", ".lock", ".wasm"}
        findings: list[dict[str, Any]] = []
        errors: list[str] = []
        skipped_files = 0
        visited_entries = 0
        visited_files = 0
        eligible_files = 0
        bytes_read = 0
        limits_hit: list[str] = []
        complete = True
        patterns = _SECRET_SCAN_PATTERNS
        placeholders = {"EXAMPLE", "DUMMY", "SAMPLE", "PLACEHOLDER", "CHANGE_ME", "REPLACE_ME", "YOUR_KEY", "YOUR_API_KEY", "YOUR_SECRET", "MY_SECRET", "FAKETOKEN", "123456789", "ABCDEFGHIJKL"}

        def _shannon_entropy(value: str) -> float:
            if not value:
                return 0.0
            counts = Counter(value)
            length = len(value)
            return -sum((count / length) * math.log2(count / length) for count in counts.values())

        def _placeholder(token: str) -> bool:
            return token.upper() in placeholders

        def _record_error(code: str) -> None:
            nonlocal complete
            complete = False
            if len(errors) < 20:
                errors.append(code)

        def _scan_line(
            raw_line: bytes, rel: str, line_no: int, *,
            source: str = "working_tree", git_commit: str | None = None,
            git_change: str | None = None,
        ) -> bool:
            nonlocal complete
            if len(findings) >= _SECRET_SCAN_MAX_FINDINGS:
                limits_hit.append("findings")
                complete = False
                return True
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            is_test = _is_test_file(rel)
            for rule_name, label, pattern, severity in patterns:
                for match in pattern.finditer(line):
                    token = match.group(1) if match.groups() else match.group(0)
                    entropy = _shannon_entropy(token)
                    masked = f"{token[:4]}***{token[-4:]}" if len(token) > 8 else "***"
                    findings.append({
                        "file": rel, "line": line_no, "rule": rule_name,
                        "description": label, "secret_type": rule_name,
                        "severity": severity, "is_test": is_test,
                        "is_placeholder": _placeholder(token),
                        "triage_status": "untriaged", "entropy": round(entropy, 2),
                        "match": masked, "redacted_secret": masked,
                        "redacted_snippet": "credential-like value omitted",
                        "source": source,
                        **({"git_commit": git_commit, "git_change": git_change} if git_commit else {}),
                    })
                    if len(findings) >= _SECRET_SCAN_MAX_FINDINGS:
                        limits_hit.append("findings")
                        complete = False
                        return True
            return False

        if path is not None:
            requested = Path(path)
            target = requested if requested.is_absolute() else scan_root / requested
            try:
                resolved = target.resolve(strict=True)
                resolved.relative_to(scan_root)
                if target.is_symlink() or not resolved.is_file():
                    raise ValueError
                scan_files = [resolved]
            except (OSError, ValueError):
                scan_files = []
                _record_error("requested_path_unreadable_or_outside_root")
        else:
            scan_files = []
            pending = [scan_root]
            while pending:
                if time.monotonic() >= deadline:
                    limits_hit.append("time")
                    complete = False
                    break
                current = pending.pop()
                try:
                    current.relative_to(scan_root)
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if time.monotonic() >= deadline:
                                limits_hit.append("time")
                                complete = False
                                pending.clear()
                                break
                            visited_entries += 1
                            if visited_entries > _SECRET_SCAN_MAX_ENTRIES:
                                limits_hit.append("visited_entries")
                                complete = False
                                pending.clear()
                                break
                            if entry.name in excluded:
                                skipped_files += 1
                                continue
                            if entry.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(entry.path):
                                skipped_files += 1
                                _record_error("linked_path_omitted")
                                continue
                            candidate = Path(entry.path)
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(candidate)
                            elif entry.is_file(follow_symlinks=False):
                                scan_files.append(candidate)
                except (OSError, PermissionError):
                    _record_error("directory_unreadable")

        for candidate in scan_files:
            if time.monotonic() >= deadline:
                limits_hit.append("time")
                complete = False
                break
            if visited_files >= _SECRET_SCAN_MAX_FILES:
                limits_hit.append("visited_files")
                complete = False
                break
            visited_files += 1
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(scan_root)
                if candidate.is_symlink() or not resolved.is_file():
                    skipped_files += 1
                    _record_error("file_changed_or_linked_during_scan")
                    continue
                rel = resolved.relative_to(scan_root).as_posix()
                if resolved.suffix.lower() in binary_suffixes:
                    skipped_files += 1
                    continue
                before = os.stat(candidate, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    skipped_files += 1
                    _record_error("non_regular_file_omitted")
                    continue
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
                if getattr(os, "O_NOFOLLOW", 0):
                    flags |= os.O_NOFOLLOW
                fd = os.open(candidate, flags)
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        skipped_files += 1
                        _record_error("file_identity_changed_or_non_regular")
                        continue
                    opened_path = candidate.resolve(strict=True)
                    opened_path.relative_to(scan_root)
                    path_stat = os.stat(candidate, follow_symlinks=False)
                    if (path_stat.st_dev, path_stat.st_ino) != (opened.st_dev, opened.st_ino):
                        skipped_files += 1
                        _record_error("file_path_changed_or_outside_root")
                        continue
                    source = os.fdopen(fd, "rb")
                    fd = -1
                finally:
                    if fd >= 0:
                        os.close(fd)
                eligible_files += 1
                with source:
                    file_bytes = 0
                    line_no = 0
                    while True:
                        if time.monotonic() >= deadline:
                            limits_hit.append("time")
                            complete = False
                            break
                        remaining = min(
                            _SECRET_SCAN_MAX_FILE_BYTES - file_bytes,
                            _SECRET_SCAN_MAX_TOTAL_BYTES - bytes_read,
                        )
                        if remaining <= 0:
                            limits_hit.append("file_bytes" if file_bytes >= _SECRET_SCAN_MAX_FILE_BYTES else "aggregate_bytes")
                            complete = False
                            break
                        raw_line = source.readline(min(_SECRET_SCAN_MAX_LINE_BYTES + 1, remaining))
                        if not raw_line:
                            break
                        file_bytes += len(raw_line)
                        bytes_read += len(raw_line)
                        line_no += 1
                        line_content = raw_line.rstrip(b"\r\n")
                        if len(line_content) > _SECRET_SCAN_MAX_LINE_BYTES:
                            _record_error("line_exceeds_scan_limit")
                            if not raw_line.endswith(b"\n"):
                                while True:
                                    drain_left = min(
                                        _SECRET_SCAN_MAX_FILE_BYTES - file_bytes,
                                        _SECRET_SCAN_MAX_TOTAL_BYTES - bytes_read,
                                    )
                                    if drain_left <= 0:
                                        limits_hit.append("file_bytes" if file_bytes >= _SECRET_SCAN_MAX_FILE_BYTES else "aggregate_bytes")
                                        complete = False
                                        break
                                    drained = source.readline(min(8192, drain_left))
                                    if not drained:
                                        break
                                    file_bytes += len(drained)
                                    bytes_read += len(drained)
                                    if drained.endswith(b"\n"):
                                        break
                                    if time.monotonic() >= deadline:
                                        limits_hit.append("time")
                                        complete = False
                                        break
                                if not complete and limits_hit:
                                    break
                            continue
                        _scan_line(line_content, rel, line_no)
                        if len(findings) >= _SECRET_SCAN_MAX_FINDINGS:
                            break
                    after = os.fstat(source.fileno())
                    opened_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                    after_state = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    if opened_state != after_state:
                        _record_error("file_changed_during_scan")
                    current_path = candidate.resolve(strict=True)
                    current_path.relative_to(scan_root)
                    current = os.stat(candidate, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
                        _record_error("file_path_changed_during_scan")
                    if after.st_size > _SECRET_SCAN_MAX_FILE_BYTES:
                        limits_hit.append("file_bytes")
                        complete = False
                    if not complete and limits_hit:
                        break
            except (OSError, UnicodeError, ValueError):
                _record_error("file_unreadable_or_outside_root")
            if not complete and limits_hit:
                break

        history_status = "not_requested"
        history_command_completed = False
        history_coverage: dict[str, Any] = {
            "scope": "not requested", "commits_scanned": 0, "bytes_read": 0,
            "max_commit_depth": 100, "max_bytes": _SECRET_SCAN_MAX_TOTAL_BYTES,
            "limitations": [],
        }
        if scan_git_history:
            history_coverage["scope"] = "changed text in the last requested commits reachable from HEAD; not the full historical tree"
            history_coverage["limitations"] = [
                "Only textual lines represented in ordinary patch hunks are scanned.",
                "Binary content, combined merge patches, and ambiguous paths are omitted and make coverage incomplete.",
                "History scanning covers at most the requested commit depth, not all refs or unreachable objects.",
                "Shallow-history boundaries and commits unreachable from HEAD may omit older or alternate history.",
            ]
            history_coverage["requested_commit_depth"] = commit_depth
            if len(findings) >= _SECRET_SCAN_MAX_FINDINGS:
                history_status = "finding_limit_reached"
                limits_hit.append("findings")
                complete = False
                _record_error("git_history_finding_limit_reached")
            else:
                remaining_time = deadline - time.monotonic()
                remaining_bytes = _SECRET_SCAN_MAX_TOTAL_BYTES - bytes_read
                if remaining_time <= 0:
                    history_status = "time_budget_exhausted"
                    limits_hit.append("time")
                    _record_error("git_history_not_scanned_within_budget")
                elif remaining_bytes < 2048:
                    history_status = "aggregate_byte_budget_exhausted"
                    limits_hit.append("aggregate_bytes")
                    _record_error("git_history_not_scanned_within_budget")
                else:
                    per_stream_limit = min(8 * 1024 * 1024, remaining_bytes // 2)
                    argv = [
                        "git", "--literal-pathspecs", "--no-pager", "-C", str(scan_root),
                        "-c", "core.quotePath=true", "-c", "color.ui=false",
                        "log", "--no-color", "--no-ext-diff", "--no-textconv",
                        "--no-renames", "--no-notes", "--no-decorate", "--no-show-signature",
                        "--src-prefix=a/", "--dst-prefix=b/", "--unified=3",
                        "--patch", "--max-count=" + str(commit_depth),
                        "--format=%x00LAH_SECRET_SCAN_COMMIT:%H PARENTS:%P%x00", "--end-of-options", "HEAD", "--",
                    ]
                    if history_pathspec is not None:
                        argv.append(history_pathspec)
                    try:
                        process_result = run_hidden(
                            argv, cwd=str(scan_root), capture_output=True, text=False,
                            stdin=subprocess.DEVNULL,
                            timeout=remaining_time, max_output_bytes=per_stream_limit,
                            env=clean_git_env(extra_env={
                                "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
                                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                            }),
                        )
                        stdout_ok = isinstance(process_result.stdout, bytes)
                        stderr_ok = isinstance(process_result.stderr, bytes)
                        stdout = process_result.stdout if stdout_ok else b""
                        stderr = process_result.stderr if stderr_ok else b""
                        history_coverage["bytes_read"] = len(stdout) + len(stderr)
                        history_coverage["discarded_output_bytes"] = int(
                            getattr(process_result, "discarded_output_bytes", 0) or 0
                        )
                        capture_bad = bool(
                            getattr(process_result, "stdout_truncated", False)
                            or getattr(process_result, "stderr_truncated", False)
                            or getattr(process_result, "output_capture_unconfirmed", False)
                            or getattr(process_result, "tree_termination_confirmed", True) is False
                            or getattr(process_result, "cleanup_confirmed", True) is False
                            or getattr(process_result, "discarded_output_bytes", 0)
                            or not stdout_ok or not stderr_ok
                            or len(stdout) + len(stderr) > remaining_bytes
                        )
                        if capture_bad:
                            history_status = "output_capture_incomplete"
                            limits_hit.append("history_output_bytes")
                            _record_error("git_history_capture_incomplete")
                        elif process_result.returncode != 0:
                            history_status = "command_failed"
                            _record_error("git_history_command_failed")
                        else:
                            history_command_completed = True
                            parsed = parse_git_patch_output(
                                stdout, deadline=deadline,
                                max_line_bytes=_SECRET_SCAN_MAX_LINE_BYTES,
                                finding_count=len(findings), max_findings=_SECRET_SCAN_MAX_FINDINGS,
                                scan_line=_scan_line,
                            )
                            history_coverage["commits_scanned"] = parsed["commits_scanned"]
                            for code in parsed["errors"]:
                                _record_error(code)
                            if "git_history_line_exceeds_limit" in parsed["errors"]:
                                limits_hit.append("history_line_bytes")
                            history_status = parsed["status"]
                            if parsed["findings_limit"]:
                                limits_hit.append("findings")
                            elif history_status == "scanned":
                                history_status = "scanned_bounded_history"
                            elif history_status == "time_budget_exhausted":
                                limits_hit.append("time")
                            if history_coverage["bytes_read"] + bytes_read > _SECRET_SCAN_MAX_TOTAL_BYTES:
                                history_status = "aggregate_byte_limit_reached"
                                limits_hit.append("aggregate_bytes")
                                _record_error("git_history_exceeded_aggregate_byte_budget")
                    except (ProcessCancelledError, ProcessCleanupUnverifiedError, subprocess.SubprocessError, OSError, ValueError):
                        history_status = "process_failed_or_cleanup_unverified"
                        _record_error("git_history_process_or_cleanup_unverified")
                    if history_status != "scanned_bounded_history":
                        complete = False
                    if time.monotonic() >= deadline:
                        limits_hit.append("time")
                        complete = False
        leak_count = len(findings)
        return {
            "success": True,
            "leak_count": leak_count,
            "real_leaks_count": leak_count,
            "test_findings_count": sum(1 for item in findings if item["is_test"] or item["is_placeholder"]),
            "secrets_count": leak_count,
            "scanned_git_history": history_command_completed,
            "git_history_status": history_status,
            "clean": complete and leak_count == 0,
            "scan_complete": complete,
            "coverage": {
                "coverage_scope": "requested file only" if path is not None else "repository files excluding listed generated and cache directories",
                "excluded_dirs": sorted(excluded),
                "visited_entries": visited_entries,
                "visited_files": visited_files,
                "eligible_files": eligible_files,
                "skipped_files": skipped_files,
                "bytes_read": bytes_read,
                "limits_hit": sorted(set(limits_hit)),
                "errors": errors,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "max_entries": _SECRET_SCAN_MAX_ENTRIES,
                "max_files": _SECRET_SCAN_MAX_FILES,
                "max_file_bytes": _SECRET_SCAN_MAX_FILE_BYTES,
                "max_total_bytes": _SECRET_SCAN_MAX_TOTAL_BYTES,
                "max_seconds": _SECRET_SCAN_MAX_SECONDS,
                "max_findings": _SECRET_SCAN_MAX_FINDINGS,
                "git_history": history_coverage,
            },
            "findings": findings,
        }

    def schema_inspect(self, root: str, db_path: str | None = None) -> dict[str, Any]:
        """Inspect SQLite database schema (tables, columns, indexes, foreign keys)."""
        p_root = Path(self._root(root))
        target_db: Path | None = None
        if db_path:
            p = Path(db_path)
            target_db = p if p.is_absolute() else p_root / p
        else:
            for ext in ("*.sqlite3", "*.db", "*.sqlite"):
                for cand in p_root.rglob(ext):
                    if not any(part.startswith((".", "node_modules", "venv")) for part in cand.parts):
                        target_db = cand
                        break
                if target_db:
                    break

        if not target_db or not target_db.is_file():
            return {"success": False, "error": f"no SQLite database found in root: {root}"}

        tables: dict[str, Any] = {}
        try:
            database_uri = f"{target_db.resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(database_uri, uri=True)) as con:
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
                "db_path": str(target_db.relative_to(p_root)).replace("\\", "/"),
                "table_count": len(tables),
                "tables": tables,
            }
        except Exception as exc:
            return {"success": False, "error": f"database inspection failed: {exc}"}

    def explain_query(self, root: str, query: str, db_path: str | None = None) -> dict[str, Any]:
        """Run EXPLAIN QUERY PLAN on an SQLite query to inspect execution strategy and indexes."""
        p_root = Path(self._root(root))
        target_db: Path | None = None
        if db_path:
            p = Path(db_path)
            target_db = p if p.is_absolute() else p_root / p
        else:
            for ext in ("*.sqlite3", "*.db", "*.sqlite"):
                for cand in p_root.rglob(ext):
                    if not any(part.startswith((".", "node_modules", "venv")) for part in cand.parts):
                        target_db = cand
                        break
                if target_db:
                    break

        if not target_db or not target_db.is_file():
            return {"success": False, "error": "no SQLite database found for query explain"}

        if not query or not query.strip():
            return {"success": False, "error": "query cannot be empty"}

        clean_query = query.strip()
        if not clean_query.lower().startswith("select"):
            return {"success": False, "error": "only SELECT queries are allowed for explain_query"}
        if ";" in clean_query.rstrip(";"):
            return {"success": False, "error": "multiple statements are not permitted"}

        try:
            with closing(sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)) as con:
                rows = con.execute(f"EXPLAIN QUERY PLAN {clean_query}").fetchall()
                plan_items = [{"id": r[0], "parent": r[1], "detail": r[3]} for r in rows]
                uses_index = any("USING INDEX" in item["detail"] or "USING COVERING INDEX" in item["detail"] for item in plan_items)
                full_scan = any("SCAN TABLE" in item["detail"] for item in plan_items)

            return {
                "success": True,
                "db_path": str(target_db.relative_to(p_root)).replace("\\", "/"),
                "query": clean_query,
                "uses_index": uses_index,
                "has_full_table_scan": full_scan,
                "plan": plan_items,
            }
        except Exception as exc:
            return {"success": False, "error": f"explain query failed: {exc}"}

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
        if type(max_depth) is not int or not 1 <= max_depth <= 256:
            raise ValueError("max_depth must be an integer between 1 and 256")
        if type(max_cycles) is not int or not 1 <= max_cycles <= 10000:
            raise ValueError("max_cycles must be an integer between 1 and 10000")
        p_root = Path(root).expanduser().resolve(strict=False)
        if not p_root.is_dir():
            return {"success": False, "error": f"directory not found: {root}"}

        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
        mod_to_file: dict[str, Path] = {}
        file_to_mod: dict[Path, str] = {}
        
        if self.code_index is None:
            return {"success": False, "error": "Python import index unavailable", "index_state": "unindexed"}
        graph_reader = getattr(self.code_index, "python_module_import_graph", None)
        if not callable(graph_reader):
            return {"success": False, "error": "Python import index API unavailable", "index_state": "unindexed"}
        indexed_graph = graph_reader(str(p_root))
        if not indexed_graph.get("success"):
            return {
                "success": False,
                "error": indexed_graph.get("error", "Python import index unavailable"),
                "index_state": indexed_graph.get("state", "unindexed"),
            }
        py_files = sorted(
            p_root / Path(relative)
            for relative in indexed_graph.get("paths", [])
            if not any(part in skip_dirs for part in Path(relative).parts)
        )

        for p in py_files:
            rel = p.relative_to(p_root)
            parts = list(rel.parts)
            if parts[-1].endswith(".py"):
                parts[-1] = parts[-1][:-3]
            if parts and parts[-1] == "__init__":
                parts.pop()
            if not parts:
                continue
            mod_name = ".".join(parts)
            mod_to_file[mod_name] = p
            file_to_mod[p] = mod_name

        if not file_to_mod:
            return {"success": False, "error": "no indexed Python modules", "index_state": "unindexed"}

        def _find_matches(target: str) -> list[str]:
            matches: list[str] = []
            cur = target
            while cur:
                if cur in mod_to_file:
                    matches.append(cur)
                if "." in cur:
                    cur = cur.rsplit(".", 1)[0]
                else:
                    break
            return matches

        graph: dict[str, set[str]] = {m: set() for m in mod_to_file}

        for edge in indexed_graph.get("imports", []):
            relative_path = Path(str(edge.get("path", "")))
            source_path = (p_root / relative_path).resolve(strict=False)
            mod_name = file_to_mod.get(source_path)
            if not mod_name:
                continue
            target = str(edge.get("target", ""))
            if not target:
                continue
            if target.startswith("."):
                level = len(target) - len(target.lstrip("."))
                package_parts = mod_name.split(".") if relative_path.name == "__init__.py" else mod_name.split(".")[:-1]
                if level - 1 > len(package_parts):
                    continue
                base_parts = package_parts[:len(package_parts) - (level - 1)]
                remainder = target[level:]
                target = ".".join([*base_parts, remainder] if remainder else base_parts)
            for known in _find_matches(target):
                if known != mod_name:
                    graph[mod_name].add(known)

        cycles: list[list[str]] = []
        seen_cycles: set[tuple[str, ...]] = set()
        visited: set[str] = set()
        stack: list[str] = []
        stack_set: set[str] = set()
        truncated = False
        cycle_limit_exceeded = False

        def dfs(curr: str):
            nonlocal truncated, cycle_limit_exceeded
            visited.add(curr)
            stack.append(curr)
            stack_set.add(curr)
            for nxt in sorted(graph.get(curr, [])):
                if cycle_limit_exceeded:
                    break
                if nxt in stack_set:
                    idx = stack.index(nxt)
                    cycle = stack[idx:] + [nxt]
                    min_idx = cycle[:-1].index(min(cycle[:-1]))
                    canon = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                    canon_key = tuple(canon)
                    if canon_key not in seen_cycles:
                        if len(cycles) >= max_cycles:
                            truncated = True
                            cycle_limit_exceeded = True
                            break
                        cycles.append(canon)
                        seen_cycles.add(canon_key)
                elif nxt not in visited:
                    if len(stack) >= max_depth:
                        truncated = True
                    else:
                        dfs(nxt)
            stack.pop()
            stack_set.remove(curr)

        for node in sorted(graph.keys()):
            if cycle_limit_exceeded:
                break
            if node not in visited:
                dfs(node)

        formatted_cycles = []
        for c in cycles:
            formatted_cycles.append({
                "cycle": c,
                "chain": " -> ".join(c),
                "length": len(c) - 1,
                "files": [str(mod_to_file.get(m, m)) for m in c[:-1]],
            })

        return {
            "success": True,
            "root": str(p_root),
            "modules_scanned": len(file_to_mod),
            "cycles_found": len(formatted_cycles),
            "cycles": formatted_cycles,
            "has_cycles": len(formatted_cycles) > 0,
            "truncated": truncated,
            "complete": not truncated,
        }

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
        """Compute McCabe cyclomatic and cognitive complexity metrics per function/method."""
        p_root = Path(root).expanduser().resolve(strict=False)
        if not p_root.is_dir():
            return {"success": False, "root": str(p_root), "error": "root directory does not exist"}
        max_entries = 20_000
        max_files = 50
        max_file_bytes = 1_048_576
        max_total_bytes = 16_777_216
        max_seconds = 5.0
        started = time.monotonic()
        deadline = started + max_seconds
        excluded_dirs = {
            ".git", ".venv", "venv", "node_modules", "__pycache__", "tool-envs",
            "state", "build", "dist", "archive", "archives", "history", "historical",
            "backup", "backups", "docs", "doc", "fixture", "fixtures", "vendor",
            "generated", "artifacts",
        }
        targets: list[tuple[int, str, Path]] = []
        errors: list[str] = []
        limits_hit: list[str] = []
        entries_visited = 0
        skipped_files = 0
        skipped_directories = 0
        eligible_files = 0
        total_bytes_read = 0
        complete = True

        def _incomplete(code: str) -> None:
            nonlocal complete
            complete = False
            if len(errors) < 20:
                errors.append(code)

        def _deadline_reached() -> bool:
            nonlocal complete
            if time.monotonic() < deadline:
                return False
            if "time" not in limits_hit:
                limits_hit.append("time")
            complete = False
            return True

        def _check_candidate_path(candidate: Path) -> Path:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(p_root)
            current = p_root
            for part in candidate.relative_to(p_root).parts:
                current = current / part
                if _is_symlink_or_reparse_point(current):
                    raise ValueError("symbol scan path contains a link")
            return resolved

        if path:
            p = Path(path)
            if not p.is_absolute():
                p = p_root / p
            try:
                resolved = _check_candidate_path(p)
                if not resolved.is_file():
                    raise ValueError("requested path is not a regular file")
                targets.append((0, resolved.relative_to(p_root).as_posix(), p))
                eligible_files = 1
            except (OSError, ValueError):
                skipped_files += 1
                _incomplete("requested_path_unreadable_or_outside_root")
        else:
            pending = [p_root]
            while pending:
                if time.monotonic() >= deadline:
                    limits_hit.append("time")
                    complete = False
                    break
                current = pending.pop()
                try:
                    current = _check_candidate_path(current)
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if time.monotonic() >= deadline:
                                limits_hit.append("time")
                                complete = False
                                pending.clear()
                                break
                            entries_visited += 1
                            if entries_visited > max_entries:
                                limits_hit.append("entries")
                                complete = False
                                pending.clear()
                                break
                            candidate = Path(entry.path)
                            if _is_symlink_or_reparse_point(candidate):
                                if entry.is_dir(follow_symlinks=False):
                                    skipped_directories += 1
                                else:
                                    skipped_files += 1
                                _incomplete("linked_path_omitted")
                                continue
                            rel = candidate.relative_to(p_root).as_posix()
                            if is_root_archive_path(rel):
                                if entry.is_dir(follow_symlinks=False):
                                    skipped_directories += 1
                                elif entry.name.lower().endswith(".py"):
                                    skipped_files += 1
                                continue
                            if entry.name.lower() in excluded_dirs:
                                if entry.is_dir(follow_symlinks=False):
                                    skipped_directories += 1
                                elif entry.name.lower().endswith(".py"):
                                    skipped_files += 1
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(candidate)
                                continue
                            if not entry.name.lower().endswith(".py"):
                                continue
                            if not include_tests and _is_test_file(rel):
                                skipped_files += 1
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                skipped_files += 1
                                _incomplete("non_regular_file_omitted")
                                continue
                            eligible_files += 1
                            parts = rel.split("/")
                            priority = 0 if parts[0].lower() == "src" else 1 if parts[0].lower() in {"app", "server", "lib", "libs", "packages", "tools"} else 2
                            targets.append((priority, rel.casefold(), candidate))
                except (OSError, ValueError):
                    _incomplete("directory_unreadable_or_outside_root")
            targets.sort(key=lambda item: (item[0], item[1], item[2].as_posix()))
            if len(targets) > max_files:
                skipped_files += len(targets) - max_files
                targets = targets[:max_files]
                limits_hit.append("files")
                complete = False

        results: list[dict[str, Any]] = []

        files_analyzed = 0
        parse_error_count = 0
        read_error_count = 0
        for _priority, _sort_path, p in targets:
            if time.monotonic() >= deadline:
                limits_hit.append("time")
                complete = False
                break
            try:
                resolved = _check_candidate_path(p)
                before = os.stat(p, follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    skipped_files += 1
                    _incomplete("non_regular_file_omitted")
                    continue
                remaining_bytes = max_total_bytes - total_bytes_read
                if before.st_size > max_file_bytes or before.st_size > remaining_bytes:
                    skipped_files += 1
                    limits_hit.append("file_bytes" if before.st_size > max_file_bytes else "total_bytes")
                    complete = False
                    continue
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
                if getattr(os, "O_NOFOLLOW", 0):
                    flags |= os.O_NOFOLLOW
                fd = os.open(p, flags)
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        skipped_files += 1
                        _incomplete("file_identity_changed_or_non_regular")
                        continue
                    source = os.fdopen(fd, "rb")
                    fd = -1
                finally:
                    if fd >= 0:
                        os.close(fd)
                with source:
                    read_limit = min(max_file_bytes, remaining_bytes)
                    raw_content = source.read(read_limit)
                    total_bytes_read += len(raw_content)
                    after = os.fstat(source.fileno())
                    current = os.stat(p, follow_symlinks=False)
                    current_path = _check_candidate_path(p)
                before_state = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                after_state = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                if before_state != after_state or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino) or current_path != resolved:
                    _incomplete("file_changed_during_scan")
                if after.st_size > max_file_bytes or after.st_size > read_limit:
                    limits_hit.append("file_bytes" if after.st_size > max_file_bytes else "total_bytes")
                    complete = False
                    skipped_files += 1
                    continue
                if len(raw_content) != after.st_size:
                    _incomplete("file_read_incomplete")
                    skipped_files += 1
                    continue
                content = raw_content.decode("utf-8", errors="replace")
            except Exception:
                skipped_files += 1
                read_error_count += 1
                _incomplete("file_parse_or_read_error")
                continue
            try:
                tree = ast.parse(content, filename=str(p))
            except Exception:
                skipped_files += 1
                parse_error_count += 1
                _incomplete("file_parse_error")
                continue
            files_analyzed += 1
            if _deadline_reached():
                break

            analysis_stopped = False
            for node in ast.walk(tree):
                if _deadline_reached():
                    analysis_stopped = True
                    break
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = node.name
                    lineno = node.lineno
                    cyclomatic = 1
                    cognitive = 0

                    def walk_cognitive(curr_node: ast.AST, depth: int) -> bool:
                        nonlocal cyclomatic, cognitive
                        if _deadline_reached():
                            return False
                        for child in ast.iter_child_nodes(curr_node):
                            if _deadline_reached():
                                return False
                            inc_depth = False
                            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                                cyclomatic += 1
                                cognitive += (1 + depth)
                                inc_depth = True
                            elif isinstance(child, ast.ExceptHandler):
                                cyclomatic += 1
                                cognitive += (1 + depth)
                                inc_depth = True
                            elif isinstance(child, (ast.With, ast.AsyncWith, ast.Assert)):
                                cyclomatic += 1
                            elif isinstance(child, ast.BoolOp):
                                cyclomatic += max(0, len(child.values) - 1)
                                cognitive += max(0, len(child.values) - 1)
                            elif isinstance(child, ast.comprehension):
                                cyclomatic += 1 + len(child.ifs)
                                cognitive += (1 + depth)

                            if not walk_cognitive(child, depth + (1 if inc_depth else 0)):
                                return False
                        return True

                    if not walk_cognitive(node, 0):
                        analysis_stopped = True
                        break
                    risk = "high" if (cyclomatic >= 10 or cognitive >= 15) else "medium" if (cyclomatic >= 6 or cognitive >= 8) else "low"
                    results.append({
                        "name": fn_name,
                        "file": p.relative_to(p_root).as_posix() if p.is_relative_to(p_root) else str(p),
                        "line": lineno,
                        "cyclomatic_complexity": cyclomatic,
                        "cognitive_complexity": cognitive,
                        "risk": risk,
                    })
            if analysis_stopped:
                break

        results.sort(key=lambda x: (-x["cognitive_complexity"], -x["cyclomatic_complexity"]))
        scope = (
            "explicit in-root file"
            if path
            else f"bounded source-first Python files; include_tests={bool(include_tests)}; excludes listed generated, archive, documentation, fixture and cache directories"
        )
        limits = {
            "max_entries": max_entries,
            "max_files": max_files,
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_seconds": max_seconds,
        }
        return {
            "success": True,
            "root": str(p_root),
            "files_analyzed": files_analyzed,
            "total_functions": len(results),
            "high_risk_count": sum(1 for r in results if r["risk"] == "high"),
            "include_tests": bool(include_tests),
            "functions": results[:max(1, min(int(max_results), 100))],
            "complete": complete,
            "scope": scope,
            "limits": limits,
            "eligible_files": eligible_files,
            "skipped_files": skipped_files,
            "skipped_directories": skipped_directories,
            "parse_error_count": parse_error_count,
            "read_error_count": read_error_count,
            "coverage": {
                "complete": complete,
                "scope": scope,
                "deadline_kind": "cooperative",
                "entries_visited": entries_visited,
                "eligible_files": eligible_files,
                "files_analyzed": files_analyzed,
                "skipped_files": skipped_files,
                "skipped_directories": skipped_directories,
                "parse_error_count": parse_error_count,
                "read_error_count": read_error_count,
                "bytes_read": total_bytes_read,
                "limits_hit": sorted(set(limits_hit)),
                "errors": errors,
                "excluded_dirs": sorted(excluded_dirs),
            },
        }

    def extract_api_spec(self, root: str, framework: str | None = None) -> dict[str, Any]:
        """Statically extract API routes and endpoints into OpenAPI 3.0 schema."""
        p_root = Path(root).expanduser().resolve(strict=False)
        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}
        endpoints: list[dict[str, Any]] = []

        # Check for static openapi.json / swagger.json in root
        for spec_name in ("openapi.json", "swagger.json", "openapi.yaml", "openapi.yml"):
            spec_file = p_root / spec_name
            if spec_file.is_file():
                try:
                    spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
                    paths_obj = spec_data.get("paths", {})
                    for p_str, methods_obj in paths_obj.items():
                        if isinstance(methods_obj, dict):
                            for m_str, m_meta in methods_obj.items():
                                if m_str.lower() in {"get", "post", "put", "delete", "patch"}:
                                    endpoints.append({
                                        "method": m_str.upper(),
                                        "path": p_str,
                                        "handler": m_meta.get("operationId", p_str) if isinstance(m_meta, dict) else p_str,
                                        "summary": m_meta.get("summary", "") if isinstance(m_meta, dict) else "",
                                        "description": m_meta.get("description", "") if isinstance(m_meta, dict) else "",
                                        "file": spec_name,
                                        "line": 1,
                                    })
                except Exception:
                    pass

        for p in p_root.rglob("*.py"):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(p))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        route_path = None
                        method = "GET"
                        if isinstance(dec, ast.Call):
                            func = dec.func
                            if isinstance(func, ast.Attribute) and func.attr.lower() in {"get", "post", "put", "delete", "patch", "options", "head"}:
                                method = func.attr.upper()
                                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                    route_path = dec.args[0].value
                            elif isinstance(func, ast.Attribute) and func.attr.lower() == "route":
                                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                    route_path = dec.args[0].value
                                for kw in dec.keywords:
                                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                                        m_list = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
                                        if m_list:
                                            method = m_list[0].upper()
                        if route_path:
                            doc = ast.get_docstring(node) or ""
                            endpoints.append({
                                "method": method,
                                "path": route_path,
                                "handler": node.name,
                                "summary": doc.splitlines()[0] if doc else node.name,
                                "description": doc,
                                "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                                "line": node.lineno,
                            })

        express_call_pat = _API_EXPRESS_ROUTER_METHOD
        next_route_pat = _API_NEXT_ROUTE_HANDLER
        for p in list(p_root.rglob("*.js")) + list(p_root.rglob("*.ts")) + list(p_root.rglob("*.mjs")):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                scan_source = _mask_non_code(text, "typescript" if p.suffix.lower() == ".ts" else "javascript")
                for m in express_call_pat.finditer(scan_source):
                    route_match = re.match(r"\s*(['\"])([^'\"\r\n]+)\1", text[m.end():])
                    if not route_match:
                        continue
                    method = m.group(1).upper()
                    r_path = route_match.group(2)
                    endpoints.append({
                        "method": method,
                        "path": r_path,
                        "handler": f"route_{method.lower()}",
                        "summary": f"{method} {r_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
                if p.stem.lower() == "route":
                    for m in next_route_pat.finditer(scan_source):
                        method = m.group(1).upper()
                        rel_p = p.relative_to(p_root) if p.is_relative_to(p_root) else p
                        r_path = "/" + "/".join(part for part in rel_p.parts[:-1] if part not in {"app", "src", "api"})
                        if not r_path or r_path == "/":
                            r_path = "/api"
                        endpoints.append({
                            "method": method,
                            "path": r_path,
                            "handler": f"next_{method.lower()}",
                            "summary": f"{method} {r_path}",
                            "description": "",
                            "file": str(rel_p),
                            "line": text[:m.start()].count("\n") + 1,
                        })
            except Exception:
                continue

        php_route_pat = _API_LARAVEL_ROUTE_METHOD
        php_resource_pat = _API_LARAVEL_RESOURCE_ROUTE
        php_attr_route_pat = _API_ATTRIBUTE_ROUTE_DECLARATION
        cake_route_pat = _API_PHP_CONNECT_ROUTE
        cake_resource_pat = _API_PHP_RESOURCE_ROUTE

        for p in list(p_root.rglob("*.php")) + list(p_root.rglob("*.ctp")):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                php_scan_source = _mask_non_code(text, "php")

                def is_php_code_match(match: re.Match[str]) -> bool:
                    return bool(re.match(
                        r"(?:Route::|#\[(?:Route|Get|Post|Put|Patch|Delete)\b|\$(?:builder|routes)->)",
                        php_scan_source[match.start():], re.I,
                    ))

                for m in php_route_pat.finditer(text):
                    if not is_php_code_match(m):
                        continue
                    method = m.group(1).upper()
                    r_path = m.group(2)
                    endpoints.append({
                        "method": method,
                        "path": r_path,
                        "handler": f"route_{method.lower()}",
                        "summary": f"{method} {r_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
                for m in php_resource_pat.finditer(text):
                    if not is_php_code_match(m):
                        continue
                    res_path = "/" + m.group(1).lstrip("/")
                    endpoints.append({
                        "method": "RESOURCE",
                        "path": res_path,
                        "handler": "resource_controller",
                        "summary": f"RESOURCE {res_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
                for m in php_attr_route_pat.finditer(text):
                    if not is_php_code_match(m):
                        continue
                    r_path = m.group(1) or "/"
                    methods_str = m.group(2) or "GET"
                    for method_raw in methods_str.replace("'", "").replace('"', "").split(","):
                        method = method_raw.strip().upper() or "GET"
                        endpoints.append({
                            "method": method,
                            "path": r_path,
                            "handler": f"route_{method.lower()}",
                            "summary": f"{method} {r_path}",
                            "description": "",
                            "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                            "line": text[:m.start()].count("\n") + 1,
                        })
                for m in cake_route_pat.finditer(text):
                    if not is_php_code_match(m):
                        continue
                    r_path = m.group(1)
                    endpoints.append({
                        "method": "ANY",
                        "path": r_path,
                        "handler": "cake_action",
                        "summary": f"CakePHP route {r_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
                for m in cake_resource_pat.finditer(text):
                    if not is_php_code_match(m):
                        continue
                    r_path = "/" + m.group(1).lstrip("/")
                    endpoints.append({
                        "method": "RESOURCE",
                        "path": r_path,
                        "handler": "cake_resource",
                        "summary": f"CakePHP resource {r_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
            except Exception:
                continue

        form_pat = _API_HTML_FORM_ENDPOINT
        for p in list(p_root.rglob("*.html")) + list(p_root.rglob("*.htm")):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                html_scan_source = re.sub(
                    r"<!--[\s\S]*?-->",
                    lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
                    text,
                )
                for m in form_pat.finditer(html_scan_source):
                    r_path = m.group(1)
                    method = (m.group(2) or "GET").upper()
                    endpoints.append({
                        "method": method,
                        "path": r_path,
                        "handler": "html_form",
                        "summary": f"HTML form {method} {r_path}",
                        "description": "",
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": text[:m.start()].count("\n") + 1,
                    })
            except Exception:
                continue

        openapi_paths: dict[str, Any] = {}
        for ep in endpoints:
            p_val = ep["path"]
            m_val = ep["method"].lower()
            if p_val not in openapi_paths:
                openapi_paths[p_val] = {}
            openapi_paths[p_val][m_val] = {
                "summary": ep.get("summary", ""),
                "description": ep.get("description", ""),
                "operationId": ep.get("handler", ""),
                "responses": {"200": {"description": "Success"}},
            }

        return {
            "success": True,
            "openapi": "3.0.0",
            "info": {"title": p_root.name, "version": "1.0.0"},
            "total_endpoints": len(endpoints),
            "paths": openapi_paths,
            "endpoints": endpoints,
        }

    def slice_dependency_graph(self, root: str, symbol: str, path: str | None = None, depth: int = 2) -> dict[str, Any]:
        """Extract a minimal AST dependency slice for a target symbol, saving context tokens."""
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
            if p.is_file():
                files_to_check.append(p)
        else:
            for p in p_root.rglob("*.py"):
                if not any(part in skip_dirs for part in p.parts):
                    files_to_check.append(p)

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
        """Detect drift between a live SQLite schema and SQL migrations or declared models."""
        p_root = Path(root).expanduser().resolve(strict=False)
        db_file: Path | None = None
        if db_path:
            p = Path(db_path).expanduser()
            db_file = p if p.is_absolute() else (p_root / p)
        else:
            for cand in [p_root / "app.db", p_root / "data.db", p_root / ".local-ai-hub" / "agent_state.db"]:
                if cand.is_file():
                    db_file = cand
                    break

        if not db_file or not db_file.is_file():
            if not db_path:
                return {
                    "success": False,
                    "db_path": None,
                    "db_tables": [],
                    "code_models_found": [],
                    "drift_detected": None,
                    "in_sync": None,
                    "missing_tables_in_db": [],
                    "extra_tables_in_db": [],
                    "column_drifts": [],
                    "drift": {},
                    "status": "database_missing",
                    "message": "No SQLite database found at default paths",
                    "error": "Cannot determine migration drift without a live SQLite database",
                }
            return {
                "success": False,
                "db_path": str(db_file or db_path),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_missing",
                "error": f"SQLite database not found at {db_path}",
            }

        try:
            db_file = db_file.expanduser().resolve(strict=True)
            db_file.relative_to(p_root)
            if db_file.stat().st_size > _MAX_SCHEMA_DB_BYTES:
                return {
                    "success": False,
                    "db_path": str(db_file),
                    "drift_detected": None,
                    "in_sync": None,
                    "status": "database_size_limit_exceeded",
                    "error": f"SQLite database exceeds {_MAX_SCHEMA_DB_BYTES} bytes",
                }
        except ValueError:
            return {
                "success": False,
                "db_path": str(db_path or db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_path_outside_root",
                "error": "SQLite database path must resolve inside the requested root",
            }
        except OSError as exc:
            return {
                "success": False,
                "db_path": str(db_path or db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_missing",
                "error": f"SQLite database not found: {exc}",
            }

        db_tables: dict[str, set[str]] = {}
        try:
            with closing(
                sqlite3.connect(
                    f"{db_file.as_uri()}?mode=ro",
                    uri=True,
                    timeout=_SCHEMA_DB_TIMEOUT_SECONDS,
                )
            ) as con:
                db_deadline = time.monotonic() + _MAX_SCHEMA_SCAN_SECONDS
                con.set_progress_handler(
                    lambda: int(time.monotonic() >= db_deadline), 1000
                )
                table_cursor = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                total_db_columns = 0
                for table_row in table_cursor:
                    if time.monotonic() >= db_deadline:
                        raise TimeoutError("SQLite schema inspection exceeded its time budget")
                    tbl = table_row[0]
                    if len(db_tables) >= _MAX_SCHEMA_DB_TABLES:
                        raise ValueError(
                            f"SQLite schema exceeds {_MAX_SCHEMA_DB_TABLES} tables"
                        )
                    safe_tbl = tbl.replace('"', '""')
                    cols: set[str] = set()
                    for column_row in con.execute(f'PRAGMA table_xinfo("{safe_tbl}")'):
                        if time.monotonic() >= db_deadline:
                            raise TimeoutError(
                                "SQLite schema inspection exceeded its time budget"
                            )
                        total_db_columns += 1
                        if total_db_columns > _MAX_SCHEMA_DB_COLUMNS:
                            raise ValueError(
                                f"SQLite schema exceeds {_MAX_SCHEMA_DB_COLUMNS} columns"
                            )
                        cols.add(column_row[1])
                    db_tables[tbl] = cols
        except Exception as exc:
            return {
                "success": False,
                "db_path": str(db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "database_inspection_failed",
                "error": f"failed to inspect SQLite schema: {exc}",
            }

        code_tables: dict[str, set[str]] = {}
        schema_source = "python_models"
        migration_files: list[Path] = []
        schema_scan_deadline = time.monotonic() + _MAX_SCHEMA_SCAN_SECONDS
        try:
            migration_files = _bounded_schema_files(
                p_root, suffix=".sql", deadline=schema_scan_deadline, migrations_only=True
            )
        except TimeoutError as exc:
            return {
                "success": False,
                "db_path": str(db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "schema_scan_budget_exceeded",
                "error": str(exc),
            }
        except OSError as exc:
            return {
                "success": False,
                "db_path": str(db_file),
                "drift_detected": None,
                "in_sync": None,
                "status": "schema_scan_failed",
                "error": f"migration directory scan failed: {exc}",
            }
        if migration_files:
            schema_source = "sql_migrations"
            migration_db = sqlite3.connect(":memory:")
            migration_db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_SCHEMA_FILE_BYTES)
            migration_db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, _MAX_SCHEMA_FILE_BYTES)

            def split_sql_statements(source: str) -> Iterator[str]:
                pending: list[str] = []
                quote: str | None = None
                line_comment = False
                block_comment = False
                index = 0
                while index < len(source):
                    char = source[index]
                    next_char = source[index + 1] if index + 1 < len(source) else ""
                    pending.append(char)
                    if line_comment:
                        if char in "\r\n":
                            line_comment = False
                    elif block_comment:
                        if char == "*" and next_char == "/":
                            pending.append(next_char)
                            index += 1
                            block_comment = False
                    elif quote is not None:
                        closing = "]" if quote == "[" else quote
                        if char == closing:
                            if next_char == closing and quote != "[":
                                pending.append(next_char)
                                index += 1
                            else:
                                quote = None
                    elif char in {"'", '"', "`", "["}:
                        quote = char
                    elif char == "-" and next_char == "-":
                        pending.append(next_char)
                        index += 1
                        line_comment = True
                    elif char == "/" and next_char == "*":
                        pending.append(next_char)
                        index += 1
                        block_comment = True
                    elif char == ";":
                        yield "".join(pending)
                        pending.clear()
                    index += 1
                if pending:
                    yield "".join(pending)

            try:
                migration_db.setlimit(
                    sqlite3.SQLITE_LIMIT_LENGTH, _MAX_SCHEMA_MIGRATION_DB_BYTES
                )
                page_size = int(migration_db.execute("PRAGMA page_size").fetchone()[0])
                max_pages = max(1, _MAX_SCHEMA_MIGRATION_DB_BYTES // page_size)
                migration_db.execute(f"PRAGMA max_page_count={max_pages}")
                migration_deadline = time.monotonic() + _MAX_SCHEMA_SCAN_SECONDS
                migration_db.set_progress_handler(
                    lambda: int(time.monotonic() >= migration_deadline), 1000
                )
                total_migration_bytes = 0
                migration_ddl_count = 0
                for migration_path in migration_files:
                    if time.monotonic() >= schema_scan_deadline:
                        return {
                            "success": False,
                            "db_path": str(db_file),
                            "drift_detected": None,
                            "in_sync": None,
                            "status": "schema_scan_budget_exceeded",
                            "error": "migration scan exceeded its time budget",
                        }
                    with migration_path.open("rb") as migration_stream:
                        raw_source = migration_stream.read(_MAX_SCHEMA_FILE_BYTES + 1)
                    total_migration_bytes += len(raw_source)
                    if (
                        len(raw_source) > _MAX_SCHEMA_FILE_BYTES
                        or total_migration_bytes > _MAX_SCHEMA_TOTAL_BYTES
                    ):
                        return {
                            "success": False,
                            "db_path": str(db_file),
                            "drift_detected": None,
                            "in_sync": None,
                            "status": "schema_scan_budget_exceeded",
                            "error": "migration SQL exceeds the bounded scan budget",
                        }
                    source = raw_source.decode("utf-8", errors="replace")

                    for statement in split_sql_statements(source):
                        if time.monotonic() >= migration_deadline:
                            raise TimeoutError("migration replay exceeded its time budget")
                        normalized = re.sub(r"(?m)^\s*--[^\n]*", "", statement)
                        normalized = re.sub(r"/\*.*?\*/", "", normalized, flags=re.DOTALL).strip()
                        if not re.match(r"^(?:CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b", normalized, re.IGNORECASE):
                            continue
                        try:
                            migration_db.execute(statement)
                            migration_ddl_count += 1
                        except sqlite3.Error as exc:
                            rel_path = migration_path.relative_to(p_root).as_posix()
                            return {
                                "success": False,
                                "drift_detected": None,
                                "in_sync": None,
                                "error": f"failed to apply schema DDL in {rel_path}: {exc}",
                            }
                if migration_ddl_count == 0:
                    return {
                        "success": False,
                        "drift_detected": None,
                        "in_sync": None,
                        "error": "no supported table schema DDL found in SQL migrations",
                    }
                tables = migration_db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                total_code_columns = 0
                for (table_name,) in tables:
                    if len(code_tables) >= _MAX_SCHEMA_DB_TABLES:
                        raise ValueError("migration schema table limit exceeded")
                    safe_table = str(table_name).replace('"', '""')
                    columns: set[str] = set()
                    for row in migration_db.execute(f'PRAGMA table_xinfo("{safe_table}")'):
                        total_code_columns += 1
                        if total_code_columns > _MAX_SCHEMA_DB_COLUMNS:
                            raise ValueError("migration schema column limit exceeded")
                        if time.monotonic() >= migration_deadline:
                            raise TimeoutError("migration schema inspection exceeded its time budget")
                        columns.add(row[1])
                    code_tables[str(table_name)] = columns
            except (OSError, sqlite3.Error, ValueError, TimeoutError) as exc:
                return {"success": False, "drift_detected": None, "in_sync": None,
                        "error": f"failed to read schema migrations: {exc}"}
            finally:
                migration_db.close()
        else:
            python_scan_deadline = time.monotonic() + _MAX_SCHEMA_SCAN_SECONDS
            try:
                python_files = _bounded_schema_files(
                    p_root, suffix=".py", deadline=python_scan_deadline
                )
            except TimeoutError as exc:
                return {
                    "success": False,
                    "db_path": str(db_file),
                    "drift_detected": None,
                    "in_sync": None,
                    "status": "schema_scan_budget_exceeded",
                    "error": str(exc),
                }
            except OSError as exc:
                return {
                    "success": False,
                    "db_path": str(db_file),
                    "drift_detected": None,
                    "in_sync": None,
                    "status": "schema_scan_failed",
                    "error": f"Python model directory scan failed: {exc}",
                }
            total_python_bytes = 0
            for p in python_files:
                if time.monotonic() >= python_scan_deadline:
                    return {
                        "success": False,
                        "db_path": str(db_file),
                        "drift_detected": None,
                        "in_sync": None,
                        "status": "schema_scan_budget_exceeded",
                        "error": "Python model scan exceeded its time budget",
                    }
                try:
                    with p.open("rb") as source_stream:
                        raw_source = source_stream.read(_MAX_SCHEMA_FILE_BYTES + 1)
                    total_python_bytes += len(raw_source)
                    if (
                        len(raw_source) > _MAX_SCHEMA_FILE_BYTES
                        or total_python_bytes > _MAX_SCHEMA_TOTAL_BYTES
                    ):
                        return {
                            "success": False,
                            "db_path": str(db_file),
                            "drift_detected": None,
                            "in_sync": None,
                            "status": "schema_scan_budget_exceeded",
                            "error": "Python model sources exceed the bounded scan budget",
                        }
                    tree = ast.parse(
                        raw_source.decode("utf-8", errors="replace"), filename=str(p)
                    )
                    for node_index, node in enumerate(ast.walk(tree)):
                        if node_index % 256 == 0 and time.monotonic() >= python_scan_deadline:
                            return {
                                "success": False,
                                "db_path": str(db_file),
                                "drift_detected": None,
                                "in_sync": None,
                                "status": "schema_scan_budget_exceeded",
                                "error": "Python model scan exceeded its time budget",
                            }
                        if isinstance(node, ast.ClassDef):
                            tbl_name = None
                            cols: set[str] = set()
                            for item in node.body:
                                if isinstance(item, ast.Assign):
                                    for target in item.targets:
                                        if isinstance(target, ast.Name) and target.id == "__tablename__" and isinstance(item.value, ast.Constant):
                                            tbl_name = str(item.value.value)
                                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                                    cols.add(item.target.id)
                            if tbl_name:
                                code_tables[tbl_name] = cols
                except Exception as exc:
                    rel_path = p.relative_to(p_root).as_posix()
                    return {
                        "success": False,
                        "db_path": str(db_file),
                        "drift_detected": None,
                        "in_sync": None,
                        "status": "schema_scan_failed",
                        "error": f"failed to inspect Python model source {rel_path}: {exc}",
                    }
                if time.monotonic() >= python_scan_deadline:
                    return {
                        "success": False,
                        "db_path": str(db_file),
                        "drift_detected": None,
                        "in_sync": None,
                        "status": "schema_scan_budget_exceeded",
                        "error": "Python model scan exceeded its time budget",
                    }

        if not code_tables:
            return {
                "success": False,
                "db_path": str(db_file),
                "schema_source": schema_source,
                "migration_files_found": [p.relative_to(p_root).as_posix() for p in migration_files],
                "db_tables": list(db_tables.keys()),
                "code_models_found": [],
                "drift_detected": None,
                "in_sync": None,
                "missing_tables_in_db": [],
                "extra_tables_in_db": [],
                "column_drifts": [],
                "drift": {},
                "status": "schema_source_unavailable",
                "error": "No SQL migration schema or declared Python model tables were found",
            }

        # SQLite identifier matching folds ASCII only; Unicode casefold would
        # incorrectly merge distinct non-ASCII names accepted by SQLite.
        ascii_lower = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
        db_names = {name.translate(ascii_lower): name for name in db_tables}
        code_names = {name.translate(ascii_lower): name for name in code_tables}
        missing_in_db = sorted(name for key, name in code_names.items() if key not in db_names)
        extra_in_db = sorted(name for key, name in db_names.items() if key not in code_names)
        column_drifts: list[dict[str, Any]] = []
        for key, t in sorted(code_names.items()):
            if key in db_names:
                declared = {column.translate(ascii_lower): column for column in code_tables[t]}
                actual = {column.translate(ascii_lower): column for column in db_tables[db_names[key]]}
                missing_cols = sorted(column for name, column in declared.items() if name not in actual)
                extra_cols = sorted(column for name, column in actual.items() if name not in declared) if declared else []
                if missing_cols or extra_cols:
                    column_drifts.append({
                        "table": t,
                        "missing_in_db": missing_cols,
                        "extra_in_db": extra_cols,
                    })

        drift_map: dict[str, Any] = {}
        for cd in column_drifts:
            drift_map[cd["table"]] = {
                "missing_in_db": cd["missing_in_db"],
                "missing_in_code": cd["extra_in_db"],
                "type_mismatches": {},
            }
        for t in missing_in_db:
            drift_map[t] = {
                "missing_in_db": sorted(code_tables.get(t, [])),
                "missing_in_code": [],
                "type_mismatches": {},
            }
        if schema_source == "sql_migrations":
            for t in extra_in_db:
                drift_map[t] = {
                    "missing_in_db": [],
                    "missing_in_code": sorted(db_tables.get(t, [])),
                    "type_mismatches": {},
                }

        drift_detected = bool(missing_in_db or column_drifts or (schema_source == "sql_migrations" and extra_in_db))
        return {
            "success": True,
            "db_path": str(db_file),
            "schema_source": schema_source,
            "migration_files_found": [p.relative_to(p_root).as_posix() for p in migration_files],
            "db_tables": list(db_tables.keys()),
            "code_models_found": list(code_tables.keys()),
            "drift_detected": drift_detected,
            "in_sync": not drift_detected,
            "missing_tables_in_db": missing_in_db,
            "extra_tables_in_db": extra_in_db,
            "column_drifts": column_drifts,
            "drift": drift_map,
            "status": "drift_detected" if drift_detected else "in_sync",
        }

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
        canon_root = canonical_root(root)
        root_path = Path(canon_root)
        if not root_path.is_dir():
            return {"success": False, "error": f"invalid root directory: {root}"}

        target_pattern = (pattern or "").strip().lower()
        if not target_pattern:
            return {"success": False, "error": "pattern is required"}

        output_limit = max(0, int(max_results))
        result_probe_limit = output_limit + 1
        file_limit = 400
        results: list[dict[str, Any]] = []
        read_errors = 0
        parse_errors = 0
        ignore_dirs = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}

        if path:
            candidate = root_path / path
            try:
                candidate.relative_to(root_path)
            except ValueError:
                files_to_scan = []
            else:
                files_to_scan = [candidate] if candidate.is_file() else []
        else:
            files_to_scan = []
            for cur_root, dirs, filenames in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for f in filenames:
                    if f.endswith((".py", ".ts", ".js", ".go", ".rs", ".cs")):
                        files_to_scan.append(Path(cur_root) / f)
                        if len(files_to_scan) > file_limit:
                            break
                if len(files_to_scan) > file_limit:
                    break
            file_limit_reached = len(files_to_scan) > file_limit
            files_to_scan = files_to_scan[:file_limit]
        if path:
            file_limit_reached = False

        files_scanned = 0
        for fpath in files_to_scan:
            if len(results) >= result_probe_limit:
                break
            files_scanned += 1
            try:
                rel_p = str(fpath.relative_to(root_path)).replace("\\", "/")
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                read_errors += 1
                continue

            lines = content.splitlines()
            file_result_start = len(results)
            parse_failed = False

            if fpath.suffix == ".py":
                try:
                    tree = ast.parse(content, filename=rel_p)
                    for node in ast.walk(tree):
                        if len(results) >= result_probe_limit:
                            break

                        if target_pattern in {"bare_except", "unhandled_exception", "missing_error_handling"}:
                            if isinstance(node, ast.Try):
                                for handler in node.handlers:
                                    if len(results) >= result_probe_limit:
                                        break
                                    if handler.type is None:
                                        snip = lines[handler.lineno - 1].strip() if handler.lineno <= len(lines) else ""
                                        results.append({
                                            "file": rel_p,
                                            "line": handler.lineno,
                                            "structure": "bare_except",
                                            "description": "Bare 'except:' catches all exceptions including SystemExit and KeyboardInterrupt",
                                            "snippet": snip,
                                        })
                                    elif isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}:
                                        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                                            snip = lines[handler.lineno - 1].strip() if handler.lineno <= len(lines) else ""
                                            results.append({
                                                "file": rel_p,
                                                "line": handler.lineno,
                                                "structure": "silent_except_pass",
                                                "description": "Silent 'except Exception: pass' swallows errors without logging",
                                                "snippet": snip,
                                            })

                        elif target_pattern in {"unclosed_resource", "open_without_with", "resource_leak"}:
                            if isinstance(node, ast.Assign):
                                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "open":
                                    snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                    results.append({
                                        "file": rel_p,
                                        "line": node.lineno,
                                        "structure": "open_without_with",
                                        "description": "File opened with direct assignment rather than 'with open(...)' context manager",
                                        "snippet": snip,
                                    })

                        elif target_pattern in {"async_without_await", "redundant_async"}:
                            if isinstance(node, ast.AsyncFunctionDef):
                                has_await = any(isinstance(child, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for child in ast.walk(node))
                                if not has_await:
                                    snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                    results.append({
                                        "file": rel_p,
                                        "line": node.lineno,
                                        "structure": "async_without_await",
                                        "description": f"Async function '{node.name}' contains no await, async with, or async for expressions",
                                        "snippet": snip,
                                    })

                        elif target_pattern.startswith("decorator:") or target_pattern.startswith("@"):
                            dec_target = target_pattern.split(":", 1)[-1].lstrip("@").strip()
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                for dec in node.decorator_list:
                                    dec_id = ""
                                    if isinstance(dec, ast.Name):
                                        dec_id = dec.id
                                    elif isinstance(dec, ast.Attribute):
                                        dec_id = dec.attr
                                    elif isinstance(dec, ast.Call):
                                        if isinstance(dec.func, ast.Name):
                                            dec_id = dec.func.id
                                        elif isinstance(dec.func, ast.Attribute):
                                            dec_id = dec.func.attr
                                    if dec_target.lower() in dec_id.lower():
                                        snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                        results.append({
                                            "file": rel_p,
                                            "line": node.lineno,
                                            "structure": f"decorator:{dec_id}",
                                            "symbol": node.name,
                                            "description": f"Function/class '{node.name}' has matching decorator @{dec_id}",
                                            "snippet": snip,
                                        })

                        elif target_pattern.startswith("subclass:") or target_pattern.startswith("inherit:"):
                            sub_target = target_pattern.split(":", 1)[1].strip()
                            if isinstance(node, ast.ClassDef):
                                for base in node.bases:
                                    base_id = ""
                                    if isinstance(base, ast.Name):
                                        base_id = base.id
                                    elif isinstance(base, ast.Attribute):
                                        base_id = base.attr
                                    if sub_target.lower() in base_id.lower():
                                        snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                        results.append({
                                            "file": rel_p,
                                            "line": node.lineno,
                                            "structure": f"subclass:{base_id}",
                                            "symbol": node.name,
                                            "description": f"Class '{node.name}' inherits from '{base_id}'",
                                            "snippet": snip,
                                        })

                        elif target_pattern.startswith("call:"):
                            fn_target = target_pattern.split(":", 1)[1].strip()
                            if isinstance(node, ast.Call):
                                call_id = ""
                                if isinstance(node.func, ast.Name):
                                    call_id = node.func.id
                                elif isinstance(node.func, ast.Attribute):
                                    call_id = node.func.attr
                                if fn_target.lower() in call_id.lower():
                                    snip = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                                    results.append({
                                        "file": rel_p,
                                        "line": node.lineno,
                                        "structure": f"call:{call_id}",
                                        "description": f"Call to '{call_id}'",
                                        "snippet": snip,
                                    })
                except SyntaxError:
                    parse_errors += 1
                    parse_failed = True

            if parse_failed or len(results) == file_result_start or fpath.suffix != ".py":
                for idx, line in enumerate(lines, 1):
                    if len(results) >= result_probe_limit:
                        break
                    raw_line = line.strip()
                    if not raw_line or raw_line.startswith(("//", "#", "/*", "*")):
                        continue
                    matched = False
                    desc = ""
                    struct_type = "text_pattern"

                    # Multi-language JS/TS patterns
                    if target_pattern in {"unhandled_promise", "catch_missing"} and ".then(" in raw_line and ".catch(" not in raw_line:
                        matched = True
                        struct_type = "unhandled_promise"
                        desc = "Promise .then() chained without .catch() handler"
                    elif target_pattern in {"empty_catch", "silent_catch"} and (
                        re.search(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}", raw_line)
                        or ("catch" in raw_line and "{" in raw_line and idx < len(lines) and lines[idx].strip() == "}")
                    ):
                        matched = True
                        struct_type = "empty_catch"
                        desc = "Empty catch block swallowing errors silently"
                    elif target_pattern in {"any_type", "ts_any"} and re.search(r":\s*any\b|\bas\s+any\b", raw_line):
                        matched = True
                        struct_type = "any_type"
                        desc = "TypeScript 'any' type bypasses static type verification"
                    elif target_pattern in {"react_hook", "hook"} and re.search(r"\buse[A-Z][a-zA-Z0-9_]*\s*\(", raw_line):
                        matched = True
                        struct_type = "react_hook"
                        desc = "React hook invocation"

                    # Go patterns
                    elif target_pattern in {"goroutine_leak", "goroutine"} and re.search(r"\bgo\s+(?:func|[a-zA-Z0-9_.]+\()", raw_line):
                        matched = True
                        struct_type = "goroutine"
                        desc = "Goroutine spawned without explicit lifecycle management"
                    elif target_pattern in {"error_ignored", "ignored_err"} and re.search(r"_,\s*err\s*:=|_\s*=\s*[a-zA-Z0-9_.]+\(", raw_line):
                        matched = True
                        struct_type = "error_ignored"
                        desc = "Error return value ignored or discarded with blank identifier"

                    # Rust patterns
                    elif target_pattern in {"unwrap_call", "unwrap"} and (".unwrap()" in raw_line or ".expect(" in raw_line):
                        matched = True
                        struct_type = "unwrap_call"
                        desc = "Potential panic via unchecked .unwrap() / .expect() call"
                    elif target_pattern in {"unsafe_block", "unsafe"} and re.search(r"\bunsafe\s*\{", raw_line):
                        matched = True
                        struct_type = "unsafe_block"
                        desc = "Unsafe Rust block bypassing memory safety guarantees"
                    elif target_pattern in {"todo_macro", "unimplemented"} and re.search(r"\b(?:todo!|unimplemented!)\(", raw_line):
                        matched = True
                        struct_type = "todo_macro"
                        desc = "Unfinished code via todo!() or unimplemented!() macro"

                    # Universal prefix queries: fn:name, class:name, struct:name, interface:name
                    elif target_pattern.startswith("fn:") or target_pattern.startswith("function:"):
                        fn_name = target_pattern.split(":", 1)[1].strip().lower()
                        if re.search(rf"\b(?:def|function|fn|func)\s+{re.escape(fn_name)}\b", raw_line, re.I):
                            matched = True
                            struct_type = f"function:{fn_name}"
                            desc = f"Function declaration matching '{fn_name}'"
                    elif target_pattern.startswith("class:") or target_pattern.startswith("struct:") or target_pattern.startswith("interface:"):
                        prefix, ent_name = target_pattern.split(":", 1)
                        if re.search(rf"\b(?:class|struct|interface|type)\s+{re.escape(ent_name.strip())}\b", raw_line, re.I):
                            matched = True
                            struct_type = f"{prefix}:{ent_name.strip()}"
                            desc = f"{prefix.capitalize()} declaration matching '{ent_name.strip()}'"

                    elif target_pattern in {"sql_injection"} and re.search(r"SELECT\s+.*\+\s*['\"]", raw_line, re.I):
                        matched = True
                        struct_type = "sql_injection"
                        desc = "Potential raw string concatenation in SQL statement"
                    elif target_pattern in raw_line.lower():
                        matched = True
                        desc = f"Pattern match for '{target_pattern}'"

                    if matched:
                        results.append({
                            "file": rel_p,
                            "line": idx,
                            "structure": struct_type,
                            "description": desc,
                            "snippet": raw_line[:120],
                        })

        returned_matches = results[:output_limit]
        truncation_reasons: list[str] = []
        if file_limit_reached:
            truncation_reasons.append("file_limit")
        if len(results) > output_limit:
            truncation_reasons.append("result_limit")
        if read_errors:
            truncation_reasons.append("read_errors")
        if parse_errors:
            truncation_reasons.append("parse_errors")
        return {
            "success": True,
            "root": str(root_path),
            "pattern": pattern,
            "count": len(returned_matches),
            "matches": returned_matches,
            "files_scanned": files_scanned,
            "truncated": bool(truncation_reasons),
            "truncation_reasons": truncation_reasons,
            "read_errors": read_errors,
            "parse_errors": parse_errors,
        }

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
                if p.suffix.lower() == ".py" and not _is_test_file(str(p)):
                    all_py_files.append(p)
                    if not entrypoints and fn.lower() in ("main.py", "app.py", "cli.py", "__main__.py", "server.py"):
                        ep_candidates.append(str(p.relative_to(root_path)).replace("\\", "/"))

        if not ep_candidates and all_py_files:
            ep_candidates.append(str(all_py_files[0].relative_to(root_path)).replace("\\", "/"))

        defs: dict[str, dict[str, Any]] = {}
        module_calls: dict[str, set[str]] = {}

        for p in all_py_files:
            rel = str(p.relative_to(root_path)).replace("\\", "/")
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

            file_calls: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    if not name.startswith("__"):
                        defs[name] = {"name": name, "file": rel, "line": node.lineno, "kind": type(node).__name__}
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        file_calls.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        file_calls.add(node.func.attr)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    file_calls.add(node.id)
            module_calls[rel] = file_calls

        reachable: set[str] = set()
        queue: list[str] = []

        for ep in ep_candidates:
            queue.extend(module_calls.get(ep, set()))

        visited_nodes: set[str] = set()
        while queue:
            sym = queue.pop(0)
            if sym in visited_nodes:
                continue
            visited_nodes.add(sym)
            if sym in defs:
                reachable.add(sym)
                sym_file = defs[sym]["file"]
                for neighbor in module_calls.get(sym_file, set()):
                    if neighbor not in visited_nodes and neighbor in defs:
                        queue.append(neighbor)

        unreachable = [info for name, info in defs.items() if name not in reachable]

        return {
            "success": True,
            "root": str(root_path),
            "entrypoints": ep_candidates,
            "total_symbols": len(defs),
            "reachable_symbols_count": len(reachable),
            "unreachable_symbols": unreachable[:limit],
            "dead_code_count": len(unreachable),
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
    ) -> dict[str, Any]:
        """Apply multiple surgical string replacements across one or more files atomically with rollback."""
        p_root = Path(self._root(root)).resolve()
        if not edits or not isinstance(edits, list):
            return {"success": False, "error": "edits must be a non-empty list of replacement operations"}

        # 1. Validate edit structures and resolve target files
        resolved_files: dict[str, Path] = {}
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
                if status.returncode == 0 and status.stdout.strip():
                    return {
                        "success": False,
                        "applied": False,
                        "error": f"refusing dirty target file: {p_str}",
                        "path": p_str,
                    }
            except (OSError, subprocess.SubprocessError):
                pass
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

        return {
            "success": True,
            "applied": True,
            "edits_count": len(edits),
            "modified_files": [str(p.relative_to(p_root)).replace("\\", "/") for p in file_contents],
        }

