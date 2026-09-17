from __future__ import annotations

from .json_utils import dumps as json_dumps

import ast
import json
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from . import __version__
from .cache import MemoryLRUCache, SQLiteCache, stable_hash
from .normalizer import tokenize_query_terms
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, quick_sanity_check
from .diff_parsers import (
    extract_cs_diff_defs,
    extract_go_diff_defs,
    extract_py_diff_defs,
    extract_rust_diff_defs,
    extract_ts_diff_defs,
)
from .process_utils import canonical_root, hidden_run_kwargs
from .state_paths import configured_state_dir


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
    ("Unsafe eval/exec", re.compile(r"\b(eval|exec)\s*\(")),
    ("Unsafe Pickle", re.compile(r"\bpickle\.loads?\s*\(")),
    ("Unsafe PyYAML", re.compile(r"\byaml\.load\s*\([^,]+(?:\)|,\s*Loader\s*=\s*(?:yaml\.)?(?:Unsafe|Full)?Loader\b)")),
    ("Shell Injection Risk", re.compile(r"\bsubprocess\.(?:Popen|run|call)\s*\(.*shell\s*=\s*True", re.S)),
]

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
            configured_state_dir(config) / "cache.sqlite3", "dependency-audit:osv",
            ttl_seconds=max(60, int(audit_cfg.get("osv_cache_ttl_seconds", 6 * 3600))), max_entries=20000,
        )
        self._fact_blob_max = int(cfg.get("fact_blob_max_entries", 100000))
        self._manifest_blob_max = int(cfg.get("manifest_blob_max_entries", 20000))
        self._fact_blob_l1 = MemoryLRUCache(max_entries=4096, ttl_seconds=3600)
        self._manifest_blob_l1 = MemoryLRUCache(max_entries=1024, ttl_seconds=3600)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=5.0, row_factory=sqlite3.Row)
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
            """
        )
        try:
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts USING fts5(root UNINDEXED,path UNINDEXED,kind UNINDEXED,name,value)")
        except sqlite3.OperationalError:
            pass
        
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
                try:
                    con.execute(
                        "DELETE FROM fact_fts WHERE root=? AND path IN (SELECT path FROM _deterministic_prune_paths)",
                        (root,),
                    )
                except sqlite3.OperationalError:
                    pass
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
                    except Exception:
                        pass
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
                    ("ci_stage", re.compile(r"^-?\s*stage\s*:\s*([^#]+)", re.I)),
                    ("ci_job", re.compile(r"^-?\s*job\s*:\s*([^#]+)", re.I)),
                    ("ci_action", re.compile(r"^-?\s*task\s*:\s*([^#]+)", re.I)),
                    ("ci_command", re.compile(r"^(?:script|bash|pwsh|powershell)\s*:\s*(.+)", re.I)),
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
                "terraform_resource": re.compile(r'^\s*resource\s+[\"\']([^\"\']+)[\"\']\s+[\"\']([^\"\']+)[\"\']'),
                "terraform_module": re.compile(r'^\s*module\s+[\"\']([^\"\']+)[\"\']'),
                "terraform_provider": re.compile(r'^\s*provider\s+[\"\']([^\"\']+)[\"\']'),
                "config_key": re.compile(r'^\s*variable\s+[\"\']([^\"\']+)[\"\']'),
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
                    ("proto_service", re.compile(r"^\s*service\s+([A-Za-z_]\w*)")),
                    ("proto_rpc", re.compile(r"^\s*rpc\s+([A-Za-z_]\w*)\s*\(")),
                    ("proto_message", re.compile(r"^\s*message\s+([A-Za-z_]\w*)")),
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
            except Exception:
                pass

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
            except Exception:
                pass

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
            UNITY_LIFECYCLES = re.compile(
                r"\b(Awake|Start|Update|FixedUpdate|LateUpdate|OnEnable|OnDisable|OnDestroy"
                r"|OnTriggerEnter|OnCollisionEnter|OnTriggerExit|OnCollisionExit"
                r"|OnApplicationPause|OnApplicationQuit)\s*\(", re.M
            )
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
            REACT_COMPONENT = re.compile(r"(?:export\s+(?:default\s+)?)?(?:function|const|class)\s+([A-Z][A-Za-z0-9_]+)", re.M)
            REACT_HOOK = re.compile(r"\bconst\s+(use[A-Z][A-Za-z0-9_]*)\s*=", re.M)
            REACT_ROUTE = re.compile(r'(?:path|to)\s*[:=]\s*[\'"`]([/][^\'"`]*)[\'"`]', re.M)
            TS_DECLARATION = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(interface|type|enum|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.M)
            NEXT_ROUTE_HANDLER = re.compile(r"^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(", re.M)
            NEST_DECORATOR = re.compile(r"^\s*@(Controller|Injectable|Get|Post|Put|Patch|Delete)\s*(?:\(\s*['\"]?([^'\")\s]*)['\"]?\s*\))?", re.M)
            TEST_SUITE_BLOCK = re.compile(r"^\s*(describe|it|test)\s*\(\s*['\"` ]([^'\"`]+)['\"` ]", re.M)
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
            FORM_TAG = re.compile(r"<form\b([^>]*)>", re.I)
            ACTION_ATTR = re.compile(r'\baction=["\']([^"\']+)["\']', re.I)
            METHOD_ATTR = re.compile(r'\bmethod=["\']([^"\']+)["\']', re.I)
            SCRIPT_SRC = re.compile(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', re.I)
            LINK_CSS = re.compile(r'<link\b[^>]*\bhref=["\']([^"\']+)["\']', re.I)
            ELEM_ID = re.compile(r'\bid=["\']([A-Za-z0-9_-]+)["\']', re.I)
            WEB_COMPONENT = re.compile(r'<([a-z0-9]+-[a-z0-9-]+)\b', re.I)
            BLADE_DIRECTIVE = re.compile(r'@(extends|include|section|yield|livewire|component)\s*\(\s*["\']([^"\']+)["\']', re.I)

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
            CSS_VAR = re.compile(r'--([A-Za-z0-9_-]+)\s*:\s*([^;]+);')
            KEYFRAMES = re.compile(r'@keyframes\s+([A-Za-z0-9_-]+)')
            MEDIA_QUERY = re.compile(r'@media\s+([^{]+)')
            CSS_CLASS = re.compile(r'^\s*(\.[A-Za-z0-9_-]+)\s*\{')

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
            PHP_DEF = re.compile(
                r"^\s*(?:(?:final|abstract|readonly)\s+)*(class|trait|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
                re.M,
            )
            PHP_FUNC = re.compile(
                r"^\s*(?:(?:public|protected|private|static|final|abstract)\s+)*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                re.M,
            )
            PHP_NS = re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_\\]*)", re.M)
            PHP_ROUTE_ATTR = re.compile(
                r"#\[(?:Route|Get|Post|Put|Patch|Delete)\s*(?:\(\s*['\"]([^'\"]+)['\"](?:[^)]*methods:\s*\[([^\]]+)\])?\s*\))?\]",
                re.M,
            )
            PHP_ATTR = re.compile(r"#\[([A-Za-z_][A-Za-z0-9_\\]*(?:\([^)]*\))?)\]", re.M)
            WP_HOOK = re.compile(
                r"\b(add_action|add_filter|do_action|apply_filters)\s*\(\s*['\"]([^'\"]+)['\"]",
                re.M,
            )
            LARAVEL_RESOURCE = re.compile(
                r"\bRoute::(?:apiResource|resource)\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z0-9_\\]+)",
                re.M,
            )
            # Laravel specifics
            ELOQUENT_TABLE = re.compile(r'protected\s+\$table\s*=\s*[\'"]([^\'"]+)[\'"]')
            ELOQUENT_FILLABLE = re.compile(r'protected\s+\$fillable\s*=\s*\[([^\]]+)\]')
            ELOQUENT_REL = re.compile(r'return\s+\$this->(belongsTo|hasMany|hasOne|belongsToMany|morphTo|morphMany)\s*\(\s*([A-Za-z0-9_:\\]+)', re.I)
            SCHEMA_CREATE = re.compile(r'Schema::create\s*\(\s*[\'"]([^\'"]+)[\'"]')
            MIGRATION_COL = re.compile(r'\$table->(string|integer|bigInteger|unsignedBigInteger|id|foreignId|boolean|text|longText|json|timestamp|date)\s*\(\s*(?:[\'"]([^\'"]+)[\'"])?')
            ARTISAN_CMD = re.compile(r'protected\s+\$signature\s*=\s*[\'"]([^\'"]+)[\'"]')
            FORM_REQ = re.compile(r'class\s+([A-Za-z0-9_]+)\s+extends\s+FormRequest\b')

            # CakePHP specifics
            CAKE_ROUTE = re.compile(r'\$(?:builder|routes)->connect\s*\(\s*[\'"]([^\'"]+)[\'"]')
            CAKE_RESOURCES = re.compile(r'\$(?:builder|routes)->resources\s*\(\s*[\'"]([^\'"]+)[\'"]')
            CAKE_TABLE = re.compile(r'class\s+([A-Za-z0-9_]+Table)\s+extends\s+Table\b')
            CAKE_ENTITY = re.compile(r'class\s+([A-Za-z0-9_]+)\s+extends\s+Entity\b')
            CAKE_ASSOC = re.compile(r'\$this->(hasMany|belongsTo|belongsToMany|hasOne)\s*\(\s*[\'"]([^\'"]+)[\'"]')
            CAKE_MIGRATION = re.compile(r'\$this->table\s*\(\s*[\'"]([^\'"]+)[\'"]')

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
            DECORATOR_RE = re.compile(r"^@([\w.]+)", re.M)
            ASYNC_DEF_RE = re.compile(r"\basync\s+def\s+(\w+)", re.M)
            DATACLASS_RE = re.compile(r"@dataclass", re.M)
            for m in DECORATOR_RE.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                facts.append(self._fact("python_decorator", m.group(1), m.group(0), line_no))
            for m in ASYNC_DEF_RE.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                facts.append(self._fact("async_function", m.group(1), m.group(0), line_no))
            if DATACLASS_RE.search(text):
                facts.append(self._fact("python_dataclass", "dataclass", path, 1))

        # ── Security / secret scanner ─────────────────────────────────────────────
        SECRET_RE = re.compile(
            r'(?i)(?:api[-_]?key|secret[-_]?key|access[-_]?token|password|passwd|auth[-_]?token|bearer)\s*[=:]\s*["\']([A-Za-z0-9+/\-_]{12,})["\']'
        )
        HARDCODED_IP = re.compile(r'\b(?:https?://)\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b')
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
            IMPORT_FROM = re.compile(r"^(?:from\s+([\w.]+)\s+import\s+([\w, ]+)|import\s+([\w.]+))", re.M)
            TESTED_CLASS = re.compile(r"class\s+Test(\w+)", re.M)
            PHP_TESTED_CLASS = re.compile(r"class\s+(\w+)Test\b", re.M)
            PHP_USE = re.compile(r"^\s*use\s+([A-Za-z_][A-Za-z0-9_\\]+);", re.M)
            JS_IMPORT = re.compile(r"import\s+(?:\{([^}]+)\}|(\w+))\s+from\s+['\"]([^'\"]+)['\"]", re.M)
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
                    re.compile(r"\b(?:CREATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|JOIN)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?[`\"\[]?([A-Za-z_][A-Za-z0-9_.$:-]*)", re.I),
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
            clauses = " OR ".join("(content_hash=? AND language=?)" for _ in pairs)
            params: list[Any] = []
            for h, lang in pairs:
                params.extend([h, lang])
            try:
                with self._lock, closing(self._connect()) as con:
                    rows = con.execute(f"SELECT content_hash,language,facts_json FROM fact_blobs WHERE analyzer_version=? AND ({clauses})", (__version__, *params)).fetchall()
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
                for path, content_hash, language, facts in parsed_rows:
                    con.execute("DELETE FROM facts WHERE root=? AND path=?", (root_s, path))
                    try:
                        con.execute("DELETE FROM fact_fts WHERE root=? AND path=?", (root_s, path))
                    except sqlite3.OperationalError:
                        pass
                    con.execute("INSERT OR REPLACE INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)", (root_s, path, content_hash, language, int(self._is_test(path)), now))
                    con.executemany("INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)", [(root_s, path, f["kind"], f["name"], f["value"], f["line"], json_dumps(f["extra"], ensure_ascii=False, separators=(",", ":"))) for f in facts])
                    try:
                        con.executemany("INSERT INTO fact_fts(root,path,kind,name,value) VALUES(?,?,?,?,?)", [(root_s, path, f["kind"], f["name"], f["value"]) for f in facts])
                    except sqlite3.OperationalError:
                        pass
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
                dep_re = re.compile(r"^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|kapt)\s*\(?[\"']([^\"']+)[\"']")
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
                gem_re = re.compile(r"^\s*gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?")
                for line in text.splitlines():
                    m = gem_re.match(line)
                    if m:
                        deps.append((m.group(1), m.group(2) or "", "gem"))
            elif name in {"makefile", "gnumakefile", "justfile"}:
                text = raw.decode("utf-8", errors="replace")
                target_re = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?:[^=]|$)") if name != "justfile" else re.compile(r"^([A-Za-z0-9_.-]+)\s*(?:[^:=]*)?:\s*$")
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
                        placeholders = ",".join("?" for _ in kinds)
                        clauses.append(f"kind IN ({placeholders})")
                        params.extend(kinds)
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
                placeholders = ",".join("?" for _ in kinds)
                clauses.append(f"kind IN ({placeholders})")
                params.extend(kinds)
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

    def _exact_evidence(self, root: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.evidence is None:
            return []
        base = Path(root).resolve()
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for row in rows:
            path = str(row.get("path", "")); line = max(1, int(row.get("line", 1) or 1))
            key = (path, line)
            if not path or key in seen:
                continue
            seen.add(key)
            target = (base / path).resolve(strict=False)
            try:
                target.relative_to(base)
                digest, lines = self.repo_tools._read_snapshot(target)
            except Exception:
                continue
            start = max(1, line - 2); end = min(len(lines), line + 2)
            text = "\n".join(f"{i}: {lines[i-1]}" for i in range(start, end + 1))
            item = {"path": path, "start_line": start, "end_line": end, "text": text, "file_sha256": digest, "deterministic": True}
            try:
                eid = self.evidence.put(str(base), item)
                item["evidence_id"] = eid
            except Exception:
                pass
            item.pop("text", None)  # progressive disclosure at the API boundary
            items.append(item)
            if len(items) >= self.max_evidence:
                break
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
            result["code_index"] = {k: graph.get(k) for k in ("symbols", "references", "edges", "confidence") if k in graph}

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
                placeholders = ",".join("?" for _ in paths)
                rows = con.execute(
                    f"SELECT path,kind,name,value,line FROM facts WHERE root=? AND path IN ({placeholders}) "
                    "AND kind IN ('entrypoint','entrypoint_file','route','test_file') ORDER BY path,line LIMIT 120",
                    (self._root(root), *paths),
                ).fetchall()
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
            "shell-exec": re.compile(r"\b(exec|system|shell_exec|subprocess|Process\.Start|Runtime\.getRuntime)\b", re.I),
            "dynamic-eval": re.compile(r"\b(eval|exec)\s*\(", re.I),
            "secret-like": re.compile(r"\b(password|secret|api[_-]?key|private[_-]?key|token)\b", re.I),
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
                                except Exception:
                                    pass
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
        result = self.query(root, query, limit=30)
        pieces = [
            "DETERMINISTIC FACTS:",
            self.render_answer(result, max_items=14),
        ]
        used = sum(len(x) for x in pieces)
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
                if used + len(block) > max_chars:
                    break
                pieces.append(block); used += len(block); raw_count += 1

        if self.code_index is not None and used < max_chars:
            try:
                sym_res = self.code_index.find_symbol(root, query, depth=1, include_info=True, limit=6)
                symbols = sym_res.get("symbols", [])
                if symbols:
                    sym_blocks = ["\nHIERARCHICAL SYMBOLS & SIGNATURES:"]
                    for s in symbols:
                        sig = s.get("signature") or f"{s.get('kind')} {s.get('name')}"
                        sym_blocks.append(f"- [{s.get('kind')}] {s.get('name_path')} ({s.get('path')}:{s.get('line')}) -> {sig}")
                        for ch in s.get("children", [])[:4]:
                            sym_blocks.append(f"    * {ch.get('signature') or ch.get('name')} (L{ch.get('line')})")
                    sym_text = "\n".join(sym_blocks)
                    if used + len(sym_text) <= max_chars:
                        pieces.append(sym_text)
            except Exception:
                pass

        context = "\n".join(pieces)[:max_chars]
        return {
            "success": True, "root": self._root(root), "query": query, "context": context,
            "evidence": result.get("evidence", []), "deterministic": result,
            "estimated_tokens": max(1, len(context) // 4), "semantic_used": False,
            "scanned_files": 0, "context_budget_chars": max_chars,
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

        for raw_root in roots:
            root = self._root(raw_root)
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
            except Exception:
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

        for route, route_roots in route_map.items():
            if len(route_roots) < 2:
                continue
            for i, r1 in enumerate(route_roots):
                for r2 in route_roots[i + 1:]:
                    edges.append({"from": r1, "to": r2, "type": "shared_route", "label": route})

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
                except Exception:
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
            except Exception:
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

        def language_for(path: str) -> str:
            if requested_lang != "auto":
                return requested_lang
            suffix = Path(path).suffix.lower()
            if suffix == ".py": return "python"
            if suffix == ".cs": return "csharp"
            if suffix == ".php": return "php"
            if suffix in {".ts", ".tsx", ".mts", ".cts"}: return "typescript"
            if suffix in {".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"}: return "javascript"
            return "auto"

        def import_for(symbol: str, container: str, path: str, lang: str) -> str:
            if lang == "csharp":
                namespace = container
                if not namespace:
                    try:
                        import re
                        text = (Path(resolved) / path).read_text(encoding="utf-8", errors="replace")[:100000]
                        match = re.search(r"(?m)^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.]*)", text)
                        if match:
                            namespace = match.group(1)
                    except OSError:
                        pass
                return f"using {namespace};" if namespace else ""
            if lang == "php":
                namespace = container
                if not namespace:
                    try:
                        import re
                        text = (Path(resolved) / path).read_text(encoding="utf-8", errors="replace")[:100000]
                        match = re.search(r"(?m)^\s*namespace\s+([A-Za-z_][A-Za-z0-9_\\]*)", text)
                        if match:
                            namespace = match.group(1).rstrip(";")
                    except OSError:
                        pass
                fqn = f"{namespace}\\{symbol}" if namespace else symbol
                return f"use {fqn};"
            if lang == "python":
                mod_path = Path(path.replace("\\", "/"))
                without_suffix = mod_path.with_suffix("") if mod_path.suffix else mod_path
                parts = list(without_suffix.parts)
                if parts and parts[-1] == "__init__":
                    parts.pop()
                module = ".".join(part for part in parts if part not in {".", ""})
                return f"from {module} import {symbol}" if module else f"import {symbol}"
            if lang in {"typescript", "javascript"}:
                normalized = path.replace("\\", "/")
                pth = Path(normalized)
                if pth.suffix.lower() in {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}:
                    normalized = str(pth.with_suffix("")).replace("\\", "/")
                if not normalized.startswith("."):
                    normalized = "./" + normalized
                return f"import {{ {symbol} }} from '{normalized}';"
            return ""

        resolved_imports: list[dict[str, Any]] = []
        missing: list[str] = []
        if self.code_index is not None:
            try:
                with self.code_index._lock, closing(self.code_index._connect()) as con:
                    for sym in unknown_symbols:
                        clean_sym = str(sym).strip()
                        if not clean_sym:
                            continue
                        row = con.execute(
                            "SELECT name, container, path, kind FROM symbols WHERE root=? AND (lower(name)=lower(?) OR name=?) ORDER BY path LIMIT 1",
                            (resolved, clean_sym, clean_sym),
                        ).fetchone()
                        if not row:
                            missing.append(clean_sym)
                            continue
                        s_name, container, path, kind = str(row[0]), str(row[1] or ""), str(row[2]), str(row[3])
                        lang = language_for(path)
                        resolved_imports.append({
                            "symbol": s_name,
                            "container": container,
                            "path": path,
                            "kind": kind,
                            "language": lang,
                            "import_statement": import_for(s_name, container, path, lang),
                        })
            except Exception as exc:
                return {"success": False, "root": resolved, "language": requested_lang, "error": str(exc), "error_type": type(exc).__name__}
        else:
            missing = [str(x).strip() for x in unknown_symbols if str(x).strip()]

        statements = [x["import_statement"] for x in resolved_imports if x.get("import_statement")]
        return {
            "success": True,
            "root": resolved,
            "language": requested_lang,
            "resolved_count": len(resolved_imports),
            "resolved_imports": resolved_imports,
            "import_statements": list(dict.fromkeys(statements)),
            "unresolved_symbols": missing,
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
        self,
        root: str,
        path: str | None = None,
        staged: bool = False,
        max_lines: int = 1000,
    ) -> dict[str, Any]:
        """Return structured git diff with parsed file hunks and statistics."""
        import subprocess, shutil
        from .process_utils import hidden_run_kwargs
        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"
        cmd = [git_exe, "-C", resolved, "diff"]
        if staged:
            cmd.append("--staged")
        if path:
            cmd.extend(["--", str(path)])

        try:
            res = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=5.0, check=False,
                encoding="utf-8", errors="replace",
                **hidden_run_kwargs(),
            )
            if res.returncode != 0:
                return {"success": False, "error": res.stderr.strip() or "git diff failed", "root": resolved}

            raw_diff = res.stdout
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
                    file_b = parts[-1].lstrip("b/") if len(parts) >= 4 else ""
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

            truncated = len(lines) > max_lines
            return {
                "success": True,
                "root": resolved,
                "staged": staged,
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
    ) -> dict[str, Any]:
        """Search git commit history by commit message and diff patch content."""
        import subprocess, shutil
        from .process_utils import hidden_run_kwargs
        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"
        clean_query = str(query or "").strip()
        if not clean_query:
            return {"success": False, "error": "query is required", "root": resolved}

        git_timeout = 15.0
        try:
            res_msg = None
            try:
                res_msg = subprocess.run(
                    [git_exe, "-C", resolved, "log", f"-n{max_commits}", f"--grep={clean_query}", "-i", "--format=%H|%an|%ad|%s", "--date=short"],
                    capture_output=True, text=True, timeout=git_timeout, check=False,
                    encoding="utf-8", errors="replace",
                    **hidden_run_kwargs(),
                )
            except subprocess.TimeoutExpired:
                res_msg = None

            res_code = None
            try:
                res_code = subprocess.run(
                    [git_exe, "-C", resolved, "log", f"-n{max_commits}", f"-S{clean_query}", "-i", "--format=%H|%an|%ad|%s", "--date=short"],
                    capture_output=True, text=True, timeout=git_timeout, check=False,
                    encoding="utf-8", errors="replace",
                    **hidden_run_kwargs(),
                )
            except subprocess.TimeoutExpired:
                res_code = None

            if res_msg is None and res_code is None:
                return {"success": False, "error": f"git log timed out after {git_timeout}s", "root": resolved}

            commits: dict[str, dict[str, Any]] = {}
            sources = []
            if res_msg is not None and getattr(res_msg, "stdout", None):
                sources.append((res_msg.stdout, "message"))
            if res_code is not None and getattr(res_code, "stdout", None):
                sources.append((res_code.stdout, "diff_content"))

            for out, match_type in sources:
                for line in out.splitlines():
                    parts = line.split("|", 3)
                    if len(parts) >= 4:
                        h, author, date, subj = parts[0], parts[1], parts[2], parts[3]
                        if h not in commits:
                            commits[h] = {
                                "commit": h[:10],
                                "full_hash": h,
                                "author": author,
                                "date": date,
                                "subject": subj,
                                "message": subj,
                                "match_type": match_type,
                            }
                        elif match_type not in commits[h]["match_type"]:
                            commits[h]["match_type"] += f", {match_type}"

            res_list = list(commits.values())[:max_commits]
            return {
                "success": True,
                "root": resolved,
                "query": clean_query,
                "count": len(res_list),
                "commits": res_list,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "root": resolved}

    def find_hotspots(
        self,
        root: str,
        days: int = 30,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Identify technical debt hotspots combining git change churn with cyclomatic complexity."""
        import subprocess, shutil, math
        from .process_utils import hidden_run_kwargs
        resolved = self._root(root)
        git_exe = shutil.which("git") or "git"

        churn_counts: dict[str, int] = defaultdict(int)
        try:
            res = subprocess.run(
                [git_exe, "-C", resolved, "log", f"--since={max(1, int(days))} days ago", "--name-only", "--format=", "--no-merges"],
                capture_output=True, text=True, timeout=5.0, check=False,
                encoding="utf-8", errors="replace",
                **hidden_run_kwargs(),
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    p = line.strip().replace("\\", "/")
                    if p and not any(p.startswith(d) for d in (".git", "vendor", "node_modules", "dist", "build")):
                        churn_counts[p] += 1
        except Exception:
            pass

        if not churn_counts:
            r_path = Path(resolved)
            for p in list(r_path.rglob("*.py"))[:30]:
                try:
                    rel = str(p.relative_to(r_path)).replace("\\", "/")
                    churn_counts[rel] = 1
                except Exception:
                    pass

        hotspots: list[dict[str, Any]] = []
        for file_rel, churn in sorted(churn_counts.items(), key=lambda x: x[1], reverse=True)[:limit * 2]:
            full_p = Path(resolved) / file_rel
            if not full_p.is_file():
                continue
            comp_score = 1
            loc = 0
            try:
                content = full_p.read_text(encoding="utf-8", errors="replace")
                loc = len(content.splitlines())
                if full_p.suffix == ".py":
                    tree = ast.parse(content, filename=file_rel)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.Match)):
                            comp_score += 1
                else:
                    comp_score = max(1, loc // 15)
            except Exception:
                comp_score = max(1, loc // 20)

            hotspot_index = round(float(churn) * math.log2(1.0 + float(comp_score)), 2)
            hotspots.append({
                "file": file_rel,
                "path": file_rel,
                "churn": churn,
                "churn_commits": churn,
                "complexity": comp_score,
                "lines_of_code": loc,
                "debt_score": hotspot_index,
                "hotspot_score": hotspot_index,
                "risk_level": "critical" if hotspot_index >= 50 else ("high" if hotspot_index >= 20 else "moderate"),
            })

        hotspots.sort(key=lambda x: x["hotspot_score"], reverse=True)
        hotspots = hotspots[:limit]
        return {
            "success": True,
            "root": resolved,
            "days": days,
            "count": len(hotspots),
            "hotspots": hotspots,
        }

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
            test_cases.append(f"""
def test_{sym}_regression_nominal():
    \"\"\"Verify nominal expected output for modified {sym}.\"\"\"
    # TODO: Verify expected inputs/outputs for {sym}
    pass

def test_{sym}_regression_edge_cases():
    \"\"\"Verify boundaries and error handling for modified {sym}.\"\"\"
    pass
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
        framework = "unknown"
        run_all_cmd = ""

        # Fast framework detection via files in root
        if (resolved_root / "pytest.ini").exists() or (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt", "requirements-core.txt")):
            framework = "pytest"
            run_all_cmd = "pytest"
        elif resolved_root.is_dir() and any((resolved_root / f).is_file() for f in os.listdir(root_str) if f.endswith((".sln", ".csproj"))):
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

        # Query indexed test files from database first (0.1 ms)
        try:
            with closing(self._connect()) as con:
                db_test_paths = [str(r[0]) for r in con.execute("SELECT path FROM files WHERE root=? AND is_test=1 LIMIT 100", (root_str,)).fetchall()]
        except Exception:
            db_test_paths = []

        if not db_test_paths:
            # Fallback to repo_tools iter_files which respects .gitignore and ignores Library/node_modules
            all_files = [str(p.relative_to(resolved_root)).replace("\\", "/") for p in self.repo_tools.iter_files(str(resolved_root))]
            for rel in all_files:
                f_lower = rel.lower()
                if f_lower.startswith("test_") or f_lower.endswith(("_test.py", "_test.go", ".spec.ts", ".spec.js", ".test.ts", ".test.js", "tests.cs", "test.cs")) or "tests/" in f_lower:
                    db_test_paths.append(rel)
                    if len(db_test_paths) >= 50:
                        break

        for rel in db_test_paths[:40]:
            f = resolved_root / rel
            cases: list[str] = []
            if f.is_file():
                try:
                    txt = f.read_text(encoding="utf-8", errors="replace")
                    if f.suffix == ".py":
                        for ln in txt.splitlines():
                            if ln.strip().startswith("def test_"):
                                cases.append(ln.strip().split("(")[0].replace("def ", "").strip())
                    elif f.suffix == ".cs":
                        import re
                        for m in re.finditer(r"\[(?:Test|UnityTest|Fact)\].*?void\s+([A-Za-z0-9_]+)", txt, re.S):
                            cases.append(m.group(1))
                except Exception:
                    pass

            run_file_cmd = f"pytest {rel}" if framework == "pytest" else (f"dotnet test --filter FullyQualifiedName~{f.stem}" if framework == "dotnet" else f"npm test {rel}")
            test_files.append({
                "path": rel,
                "cases_count": len(cases),
                "cases": cases[:15],
                "run_command": run_file_cmd,
            })

        return {
            "success": True,
            "framework": framework,
            "run_all_command": run_all_cmd,
            "test_files_count": len(test_files),
            "test_files": test_files,
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

        if self.code_index is not None:
            try:
                imp = self.code_index.impact(str(resolved_root), norm_changed)
                for st in imp.get("suggested_tests", []):
                    test_paths_set.add(st["path"].replace("\\", "/"))
            except Exception:
                pass

        matched_tests = sorted(test_paths_set)
        cmd = ""
        if matched_tests:
            if framework == "pytest":
                cmd = f"pytest {' '.join(matched_tests)}"
            elif framework == "dotnet":
                filters = " | ".join(f"FullyQualifiedName~{Path(t).stem}" for t in matched_tests)
                cmd = f"dotnet test --filter \"{filters}\""
            elif framework == "npm":
                cmd = f"npm test -- {' '.join(matched_tests)}"
            elif framework == "cargo":
                cmd = f"cargo test {' '.join(Path(t).stem for t in matched_tests)}"
            elif framework == "go":
                cmd = f"go test {' '.join(matched_tests)}"
            else:
                cmd = f"pytest {' '.join(matched_tests)}"

        return {
            "success": True,
            "framework": framework,
            "changed_files": norm_changed,
            "test_files": matched_tests,
            "suggested_command": cmd,
            "confidence": 0.95 if matched_tests else 0.5,
        }

    def repo_topology(self, root: str) -> dict[str, Any]:
        """Synthesize architectural layers, component topology, and central hub modules without LLM."""
        resolved_root = Path(self._root(root))
        root_str = str(resolved_root)
        
        all_files = [str(p.relative_to(resolved_root)).replace("\\", "/") for p in self.repo_tools.iter_files(root_str)]
        
        layers: dict[str, list[str]] = {
            "entrypoints": [],
            "presentation": [],
            "core_services": [],
            "domain_models": [],
            "infrastructure": [],
            "tests": [],
            "utilities": [],
        }

        import_graph: dict[str, set[str]] = defaultdict(set)
        in_degree: Counter[str] = Counter()

        for rel in all_files:
            rel_lower = rel.lower()
            name = Path(rel).name.lower()
            stem = Path(rel).stem.lower()

            if "test" in rel_lower or "spec" in rel_lower:
                layers["tests"].append(rel)
            elif name in {"main.py", "app.py", "cli.py", "index.ts", "index.js", "server.ts", "server.js", "main.go", "main.rs", "__main__.py"}:
                layers["entrypoints"].append(rel)
            elif any(m in rel_lower for m in ("route", "controller", "view", "endpoint", "http_", "mcp_", "api/", "api.")):
                layers["presentation"].append(rel)
            elif any(m in rel_lower for m in ("service", "orchestrat", "planner", "pipeline", "handler", "manager", "engine", "core")):
                layers["core_services"].append(rel)
            elif any(m in rel_lower for m in ("model", "schema", "entity", "type", "event", "state", "dataclass")):
                layers["domain_models"].append(rel)
            elif any(m in rel_lower for m in ("db", "storage", "repo", "dao", "client", "cache", "telemetry", "hardware", "sqlite")):
                layers["infrastructure"].append(rel)
            else:
                layers["utilities"].append(rel)

            if rel.endswith(".py"):
                fpath = resolved_root / rel
                try:
                    txt = fpath.read_text(encoding="utf-8", errors="replace")
                    for m in re.finditer(r"(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", txt):
                        target_mod = (m.group(1) or m.group(2)).split(".")[0]
                        if target_mod and target_mod != stem:
                            import_graph[rel].add(target_mod)
                            in_degree[target_mod] += 1
                except Exception:
                    pass

        top_hubs = [{"module": mod, "in_degree": count} for mod, count in in_degree.most_common(10)]

        has_cli = bool(layers["entrypoints"])
        has_api = bool(layers["presentation"])
        has_services = bool(layers["core_services"])
        
        if has_api and has_services:
            arch_pattern = "Layered Service / Web Application"
        elif has_cli and has_services:
            arch_pattern = "Modular CLI Application"
        elif has_services:
            arch_pattern = "Library / Application Engine"
        else:
            arch_pattern = "Package / Module Collection"

        lines = [
            f"# Architecture Topology: {resolved_root.name}",
            f"**Pattern**: {arch_pattern}",
            "",
            "## Architectural Layers",
        ]
        for layer_name, files in layers.items():
            if files:
                sample = ", ".join(files[:4]) + (f" (+{len(files)-4} more)" if len(files) > 4 else "")
                lines.append(f"- **{layer_name.replace('_', ' ').title()}** ({len(files)} files): `{sample}`")
        
        if top_hubs:
            hubs_str = ", ".join(f"`{h['module']}` ({h['in_degree']})" for h in top_hubs[:5])
            lines.append("")
            lines.append(f"## Key Hub Modules (Blast Radius): {hubs_str}")

        summary_md = "\n".join(lines)

        return {
            "success": True,
            "root": root_str,
            "architecture_pattern": arch_pattern,
            "layers": layers,
            "hub_modules": top_hubs,
            "summary_markdown": summary_md,
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
                fixture_lines = [
                    "@pytest.fixture",
                    f"def mock_{symbol}():",
                    f"    with unittest.mock.patch('{target_path.stem}.{symbol}') as m:",
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
                fixture_code = f"@pytest.fixture\ndef mock_{symbol.lower()}():\n    return {mock_code}"
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
        resolved_root = Path(self._root(root))
        secret_patterns = _SECURITY_AUDIT_SECRETS
        code_smell_patterns = _SECURITY_AUDIT_SMELLS

        findings: list[dict[str, Any]] = []
        candidate_files = self.repo_tools.iter_files(str(resolved_root))

        for f in candidate_files:
            if len(findings) >= limit:
                break
            if f.suffix.lower() not in {".py", ".ts", ".js", ".cs", ".go", ".rs", ".json", ".toml", ".yaml", ".yml", ".env"}:
                continue
            rel = str(f.relative_to(resolved_root)).replace("\\", "/")
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
                lines = txt.splitlines()
                for i, line in enumerate(lines, 1):
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
                                "snippet": stripped[:120],
                            })
                            break

                for name, pat in code_smell_patterns:
                    for m in pat.finditer(txt):
                        line_no = txt[:m.start()].count("\n") + 1
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
                                "snippet": matched_line[:120] or m.group(0)[:120],
                            })
                        if len(findings) >= limit:
                            break
            except Exception:
                pass

        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
        med_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")

        return {
            "success": True,
            "root": str(resolved_root),
            "findings_count": len(findings),
            "high_severity_count": high_count,
            "medium_severity_count": med_count,
            "is_clean": len(findings) == 0,
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
                "guidance": "Run `tsc --noEmit` via local_ai_command before creating diffs or handoffs.",
                "confidence": 0.85,
            })

        if has_ruff:
            rules.append({
                "rule_id": "rule_python_ruff",
                "title": "Run ruff format and lint",
                "context": "Python styling",
                "guidance": "Format with `local_ai_command(action='format')` before submitting PRs.",
                "confidence": 0.88,
            })

        return {
            "success": True,
            "root": str(resolved_root),
            "rule_count": len(rules),
            "rules": rules[:limit],
        }

    def code_invariants(self, root: str, path: str | None = None) -> dict[str, Any]:
        """Static AST checker for critical coding invariants (unclosed resources, unawaited coroutines, missing timeouts)."""
        resolved_root = Path(self._root(root))
        target_paths: list[Path] = []
        if path:
            candidate = (resolved_root / path).resolve(strict=False)
            if candidate.is_file():
                target_paths.append(candidate)
            else:
                return {"success": False, "error": f"path not found: {path}"}
        else:
            for dirpath, dirnames, filenames in os.walk(resolved_root):
                dirnames[:] = [d for d in dirnames if d not in {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}]
                for f in filenames:
                    if f.endswith(".py"):
                        target_paths.append(Path(dirpath) / f)
                        if len(target_paths) >= 150:
                            break
                if len(target_paths) >= 150:
                    break

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
                        if full_name in ("subprocess.run", "subprocess.Popen", "requests.get", "requests.post", "requests.put", "requests.delete", "urllib.request.urlopen"):
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

                if func_name == "open" and id(node) not in self.with_items:
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
            try:
                rel = str(p.relative_to(resolved_root)).replace("\\", "/")
                code = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(code, filename=rel)
                visitor = InvariantVisitor(rel)
                visitor.visit(tree)
            except Exception:
                continue

        return {
            "success": True,
            "root": str(resolved_root),
            "files_checked": len(target_paths),
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

        rows: list[dict[str, Any]] = []
        for i in range(1, n + 1):
            row: dict[str, Any] = {}
            for col, ctype in fields.items():
                if "uuid" in ctype or col.lower() in ("id", "guid"):
                    row[col] = f"{uuid.uuid4().hex[:12]}"
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
            import io, csv
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
            pass

        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw)
            if isinstance(data, dict) and "traceEvents" in data:
                events = data.get("traceEvents", [])
                durations: dict[str, float] = {}
                counts: dict[str, int] = {}
                for ev in events:
                    name = ev.get("name", "")
                    dur = float(ev.get("dur", 0))
                    if name and dur > 0:
                        durations[name] = durations.get(name, 0.0) + dur
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
            pass

        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].replace(".", "").isdigit():
                    entries.append({"summary": line.strip()})
                    if len(entries) >= limit:
                        break
            return {
                "success": True,
                "profile_path": str(p),
                "format": "text_profile",
                "top_functions": entries,
            }
        except Exception as exc:
            return {"success": False, "error": f"failed to parse profile: {exc}"}

    def find_callers(self, root: str, symbol: str, limit: int = 50) -> dict[str, Any]:
        """Find all call sites and references to a symbol across repository AST."""
        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}
        if not symbol or not symbol.strip():
            return {"success": False, "error": "symbol cannot be empty"}

        sym = symbol.strip()
        callers: list[dict[str, Any]] = []

        for p in p_root.rglob("*.py"):
            if not p.is_file() or any(part.startswith((".", "node_modules", "venv", ".git")) for part in p.parts):
                continue
            try:
                rel = str(p.relative_to(p_root)).replace("\\", "/")
                content = p.read_text(encoding="utf-8", errors="replace")
                if sym not in content:
                    continue
                tree = ast.parse(content, filename=str(p))
                lines = content.splitlines()

                class _CallerVisitor(ast.NodeVisitor):
                    def __init__(self):
                        self.scope_stack: list[str] = []

                    def visit_FunctionDef(self, node):
                        self.scope_stack.append(node.name)
                        self.generic_visit(node)
                        self.scope_stack.pop()

                    def visit_AsyncFunctionDef(self, node):
                        self.scope_stack.append(node.name)
                        self.generic_visit(node)
                        self.scope_stack.pop()

                    def visit_ClassDef(self, node):
                        self.scope_stack.append(node.name)
                        self.generic_visit(node)
                        self.scope_stack.pop()

                    def visit_Call(self, node):
                        matched = False
                        if isinstance(node.func, ast.Name) and node.func.id == sym:
                            matched = True
                        elif isinstance(node.func, ast.Attribute) and node.func.attr == sym:
                            matched = True
                        if matched:
                            enclosing = ".".join(self.scope_stack) if self.scope_stack else "<module>"
                            line_idx = max(0, node.lineno - 1)
                            snippet = lines[line_idx].strip() if line_idx < len(lines) else ""
                            callers.append({
                                "file": rel,
                                "line": node.lineno,
                                "col": node.col_offset,
                                "caller": enclosing,
                                "snippet": snippet[:160],
                            })
                        self.generic_visit(node)

                visitor = _CallerVisitor()
                visitor.visit(tree)
                if len(callers) >= limit:
                    break
            except Exception:
                continue

        return {
            "success": True,
            "symbol": sym,
            "caller_count": len(callers),
            "callers": callers[:limit],
        }

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

        FUNC_PAT = re.compile(
            r"^\s*(?:(?:pub(?:lic)?|priv(?:ate)?|prot(?:ected)?|internal|static|async|export|default|override|virtual|final)\s+)*"
            r"(?:(?:func|fn|function|def)\b|(?:[A-Za-z_$][\w.<>,\[\]]*\s+)+[A-Za-z_$][\w$]*\s*\()|"
            r"^\s*(?:func\s*\([^)]*\)\s*)?[A-Za-z_$][\w$]*\s*\([^)]*\)\s*(?:[^{;]*\{|=>)"
        )
        STRUCT_PAT = re.compile(r"^\s*(?:(?:pub(?:lic)?|export)\s+)*(?:struct|interface|enum|type|trait|class)\b")

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
        p_root = Path(self._root(root))
        if not p_root.is_dir():
            return {"success": False, "error": f"root not found: {root}"}

        def _shannon_entropy(s: str) -> float:
            if not s:
                return 0.0
            import math
            from collections import Counter
            counts = Counter(s)
            length = len(s)
            return -sum((cnt / length) * math.log2(cnt / length) for cnt in counts.values())

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
                "_spec.rb", ".spec.ts", ".spec.js"
            )
            return any(fname.endswith(sfx) for sfx in test_suffixes)

        def _is_placeholder(token: str) -> bool:
            t = token.upper()
            placeholders = (
                "EXAMPLE", "DUMMY", "SAMPLE", "PLACEHOLDER", "CHANGE_ME", "REPLACE_ME",
                "YOUR_KEY", "YOUR_API_KEY", "YOUR_SECRET", "MY_SECRET", "FAKETOKEN",
                "123456789", "ABCDEFGHIJKL"
            )
            return any(p in t for p in placeholders)

        patterns = _SECRET_SCAN_PATTERNS

        findings: list[dict[str, Any]] = []
        if path:
            scan_files = [p_root / path]
        else:
            scan_files = []
            for root_dir, dirs, files in os.walk(p_root):
                dirs[:] = [d for d in dirs if not any(d.startswith(prefix) for prefix in (".", "node_modules", "venv", "tool-envs", "state", "build", "dist"))]
                for f in files:
                    scan_files.append(Path(root_dir) / f)

        for p in scan_files:
            if not p.is_file():
                continue
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".exe", ".bin", ".whl", ".pyc", ".db", ".sqlite3", ".zip", ".tar", ".gz", ".lock", ".wasm"):
                continue
            try:
                rel = str(p.relative_to(p_root)).replace("\\", "/")
                is_test = _is_test_file(rel)
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                for line_no, line in enumerate(lines, 1):
                    stripped_line = line.strip()
                    if not stripped_line or stripped_line.startswith(("#", "//", "/*", "*")):
                        continue
                    for rule_name, label, pat, base_sev in patterns:
                        m = pat.search(line)
                        if not m:
                            continue
                        secret_token = m.group(1) if m.groups() else m.group(0)
                        entropy = _shannon_entropy(secret_token)
                        placeholder = _is_placeholder(secret_token)
                        if rule_name == "generic_secret_assignment" and entropy < 3.0 and not is_test:
                            continue

                        if len(secret_token) > 8:
                            masked_secret = f"{secret_token[:4]}***{secret_token[-4:]}"
                        else:
                            masked_secret = "***"

                        redacted_line = line.replace(secret_token, masked_secret).strip()[:140]
                        severity = "LOW" if (is_test or placeholder) else base_sev

                        findings.append({
                            "file": rel,
                            "line": line_no,
                            "rule": rule_name,
                            "description": label,
                            "secret_type": rule_name,
                            "severity": severity,
                            "is_test": is_test,
                            "is_placeholder": placeholder,
                            "entropy": round(entropy, 2),
                            "match": masked_secret,
                            "redacted_secret": masked_secret,
                            "redacted_snippet": redacted_line,
                        })
                        if len(findings) >= 100:
                            break
                    if len(findings) >= 100:
                        break
            except Exception:
                continue

        if scan_git_history and shutil.which("git"):
            try:
                proc = subprocess.run(
                    ["git", "-C", str(p_root), "log", "-p", f"-n{max(1, int(commit_depth))}"],
                    capture_output=True, text=True, check=False, timeout=15, **hidden_run_kwargs(),
                )
                if proc.returncode == 0:
                    current_commit = "HEAD"
                    current_file = "git-history"
                    for h_line in proc.stdout.splitlines():
                        if len(findings) >= 150:
                            break
                        if h_line.startswith("commit "):
                            parts = h_line.split()
                            if len(parts) >= 2:
                                current_commit = parts[1][:8]
                            continue
                        elif h_line.startswith("diff --git "):
                            parts = h_line.split()
                            if len(parts) >= 4:
                                current_file = parts[3].lstrip("b/")
                            continue
                        if not h_line.startswith("+") or h_line.startswith("+++"):
                            continue
                        raw_line = h_line[1:]
                        for rule_name, label, pattern, base_sev in patterns:
                            m = pattern.search(raw_line)
                            if not m:
                                continue
                            secret_token = m.group(1) if m.groups() else m.group(0)
                            entropy = _shannon_entropy(secret_token)
                            placeholder = _is_placeholder(secret_token)
                            if rule_name == "generic_secret_assignment" and entropy < 3.0:
                                continue
                            masked = f"{secret_token[:4]}***{secret_token[-4:]}" if len(secret_token) > 8 else "***"
                            findings.append({
                                "file": f"{current_file} (commit {current_commit})",
                                "line": 0,
                                "rule": rule_name,
                                "description": f"{label} (in git history commit {current_commit})",
                                "secret_type": rule_name,
                                "severity": "LOW" if placeholder else base_sev,
                                "is_test": _is_test_file(current_file),
                                "is_placeholder": placeholder,
                                "in_git_history": True,
                                "commit": current_commit,
                                "entropy": round(entropy, 2),
                                "match": masked,
                                "redacted_secret": masked,
                                "redacted_snippet": raw_line.replace(secret_token, masked).strip()[:140],
                            })
            except Exception:
                pass

        real_leaks = [f for f in findings if not f["is_test"] and not f["is_placeholder"]]
        test_fixtures = [f for f in findings if f["is_test"] or f["is_placeholder"]]

        return {
            "success": True,
            "leak_count": len(real_leaks),
            "real_leaks_count": len(real_leaks),
            "test_findings_count": len(test_fixtures),
            "secrets_count": len(findings),
            "scanned_git_history": bool(scan_git_history),
            "clean": len(real_leaks) == 0,
            "findings": findings[:100],
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
            with closing(sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)) as con:
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
            with self._lock, closing(self._connect()) as con:
                if root:
                    r = self._root(root); where = " WHERE root=?"; args = (r,)
                else:
                    where = ""; args = ()
                counts = {
                    "files": int(con.execute(f"SELECT COUNT(*) FROM files{where}", args).fetchone()[0]),
                    "facts": int(con.execute(f"SELECT COUNT(*) FROM facts{where}", args).fetchone()[0]),
                    "dependencies": int(con.execute(f"SELECT COUNT(*) FROM dependencies{where}", args).fetchone()[0]),
                    "scripts": int(con.execute(f"SELECT COUNT(*) FROM scripts{where}", args).fetchone()[0]),
                }
            res = {"success": True, "healthy": True, **counts, "stats": dict(self._stats)}
            if len(self._status_cache) > 64:
                oldest = sorted(self._status_cache.items(), key=lambda x: x[1].get("time", 0))[:32]
                for k, _ in oldest:
                    self._status_cache.pop(k, None)
            self._status_cache[key] = {"time": now, "data": res}
            return res
        except Exception as exc:
            return {"success": False, "healthy": False, "error": str(exc), "stats": dict(self._stats)}

    def find_circular_dependencies(self, root: str, language: str = "python") -> dict[str, Any]:
        """Detect circular module import cycles in Python and JS/TS codebases."""
        p_root = Path(root).expanduser().resolve(strict=False)
        if not p_root.is_dir():
            return {"success": False, "error": f"directory not found: {root}"}

        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
        mod_to_file: dict[str, Path] = {}
        file_to_mod: dict[Path, str] = {}
        
        py_files: list[Path] = []
        for p in p_root.rglob("*.py"):
            if any(part in skip_dirs for part in p.parts):
                continue
            py_files.append(p)

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

        for p in py_files:
            mod_name = file_to_mod.get(p)
            if not mod_name:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(p))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for known in _find_matches(alias.name):
                            if known != mod_name:
                                graph[mod_name].add(known)
                elif isinstance(node, ast.ImportFrom):
                    base = ""
                    if node.level and node.level > 0:
                        pkg_parts = mod_name.split(".")[:-1]
                        if node.level - 1 <= len(pkg_parts):
                            base_parts = pkg_parts[:len(pkg_parts) - (node.level - 1)]
                            if node.module:
                                base_parts.append(node.module)
                            base = ".".join(base_parts)
                    elif node.module:
                        base = node.module

                    for alias in node.names:
                        candidates = [f"{base}.{alias.name}" if base else alias.name]
                        if base:
                            candidates.append(base)
                        for target in candidates:
                            for known in _find_matches(target):
                                if known != mod_name:
                                    graph[mod_name].add(known)

        cycles: list[list[str]] = []
        visited: set[str] = set()
        stack: list[str] = []
        stack_set: set[str] = set()

        def dfs(curr: str):
            visited.add(curr)
            stack.append(curr)
            stack_set.add(curr)
            for nxt in sorted(graph.get(curr, [])):
                if nxt in stack_set:
                    idx = stack.index(nxt)
                    cycle = stack[idx:] + [nxt]
                    min_idx = cycle[:-1].index(min(cycle[:-1]))
                    canon = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                    if canon not in cycles:
                        cycles.append(canon)
                elif nxt not in visited:
                    dfs(nxt)
            stack.pop()
            stack_set.remove(curr)

        for node in sorted(graph.keys()):
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
        }

    def generate_types(self, root: str, file_path: str, write_stub: bool = False) -> dict[str, Any]:
        """Parse Python source file and generate PEP 484 .pyi type stub."""
        p_root = Path(root).expanduser().resolve(strict=False)
        target = Path(file_path)
        if not target.is_absolute():
            target = (p_root / target).resolve()
        if not target.is_file():
            return {"success": False, "error": f"file not found: {file_path}"}

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(target))
        except Exception as exc:
            return {"success": False, "error": f"failed to parse AST: {exc}"}

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
        stub_path = target.with_suffix(".pyi")
        if write_stub:
            from .process_utils import atomic_write_file
            atomic_write_file(stub_path, stub_content)

        return {
            "success": True,
            "source_file": str(target),
            "stub_file": str(stub_path) if write_stub else None,
            "stub_content": stub_content,
            "stub_lines": len(stub_lines),
        }

    def code_complexity(self, root: str, path: str | None = None, max_results: int = 20) -> dict[str, Any]:
        """Compute McCabe cyclomatic and cognitive complexity metrics per function/method."""
        p_root = Path(root).expanduser().resolve(strict=False)
        targets: list[Path] = []
        if path:
            p = Path(path)
            if not p.is_absolute():
                p = p_root / p
            if p.is_file():
                targets.append(p)
        else:
            skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}
            for p in p_root.rglob("*.py"):
                if not any(part in skip_dirs for part in p.parts):
                    targets.append(p)
                if len(targets) >= 50:
                    break

        results: list[dict[str, Any]] = []

        for p in targets:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=str(p))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_name = node.name
                    lineno = node.lineno
                    cyclomatic = 1
                    cognitive = 0

                    def walk_cognitive(curr_node: ast.AST, depth: int):
                        nonlocal cyclomatic, cognitive
                        for child in ast.iter_child_nodes(curr_node):
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

                            walk_cognitive(child, depth + (1 if inc_depth else 0))

                    walk_cognitive(node, 0)
                    risk = "high" if (cyclomatic >= 10 or cognitive >= 15) else "medium" if (cyclomatic >= 6 or cognitive >= 8) else "low"
                    results.append({
                        "name": fn_name,
                        "file": str(p.relative_to(p_root) if p.is_relative_to(p_root) else p),
                        "line": lineno,
                        "cyclomatic_complexity": cyclomatic,
                        "cognitive_complexity": cognitive,
                        "risk": risk,
                    })

        results.sort(key=lambda x: (-x["cognitive_complexity"], -x["cyclomatic_complexity"]))
        return {
            "success": True,
            "root": str(p_root),
            "files_analyzed": len(targets),
            "total_functions": len(results),
            "high_risk_count": sum(1 for r in results if r["risk"] == "high"),
            "functions": results[:max(1, min(int(max_results), 100))],
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

        express_pat = re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete|options|head)\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
        next_route_pat = re.compile(r"^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*\(", re.M)
        for p in list(p_root.rglob("*.js")) + list(p_root.rglob("*.ts")) + list(p_root.rglob("*.mjs")):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                for m in express_pat.finditer(text):
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
                if p.stem.lower() == "route":
                    for m in next_route_pat.finditer(text):
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

        php_route_pat = re.compile(r"\bRoute::(get|post|put|patch|delete|options|any)\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
        php_resource_pat = re.compile(r"\bRoute::(?:apiResource|resource)\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
        php_attr_route_pat = re.compile(r"#\[(?:Route|Get|Post|Put|Patch|Delete)\s*(?:\(\s*['\"]([^'\"]+)['\"](?:[^)]*methods:\s*\[([^\]]+)\])?\s*\))?\]", re.I)
        cake_route_pat = re.compile(r"\$(?:builder|routes)->connect\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
        cake_resource_pat = re.compile(r"\$(?:builder|routes)->resources\s*\(\s*['\"]([^'\"]+)['\"]", re.I)

        for p in list(p_root.rglob("*.php")) + list(p_root.rglob("*.ctp")):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                for m in php_route_pat.finditer(text):
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

        form_pat = re.compile(r"<form\b(?=[^>]*\baction=['\"]([^'\"]+)['\"])(?:[^>]*\bmethod=['\"]([A-Za-z]+)['\"])?", re.I)
        for p in list(p_root.rglob("*.html")) + list(p_root.rglob("*.htm")):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                for m in form_pat.finditer(text):
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
        """Detect drift between SQLite physical schema and declared models in source code."""
        p_root = Path(root).expanduser().resolve(strict=False)
        db_file: Path | None = None
        if db_path:
            p = Path(db_path)
            db_file = p if p.is_absolute() else (p_root / p)
        else:
            for cand in [p_root / "app.db", p_root / "data.db", p_root / ".local-ai-hub" / "agent_state.db"]:
                if cand.is_file():
                    db_file = cand
                    break

        if not db_file or not db_file.is_file():
            if not db_path:
                return {
                    "success": True,
                    "db_path": None,
                    "db_tables": [],
                    "code_models_found": [],
                    "drift_detected": False,
                    "in_sync": True,
                    "missing_tables_in_db": [],
                    "extra_tables_in_db": [],
                    "column_drifts": [],
                    "drift": {},
                    "status": "in_sync",
                    "message": "No SQLite database found at default paths",
                }
            return {"success": False, "error": f"SQLite database not found at {db_path}"}

        db_tables: dict[str, set[str]] = {}
        try:
            with closing(sqlite3.connect(db_file)) as con:
                tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
                for tbl in tables:
                    safe_tbl = tbl.replace('"', '""')
                    cols = {r[1] for r in con.execute(f'PRAGMA table_info("{safe_tbl}")').fetchall()}
                    db_tables[tbl] = cols
        except Exception as exc:
            return {"success": False, "error": f"failed to inspect SQLite schema: {exc}"}

        code_tables: dict[str, set[str]] = {}
        skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}
        for p in p_root.rglob("*.py"):
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
                for node in ast.walk(tree):
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
            except Exception:
                continue

        missing_in_db = [t for t in code_tables if t not in db_tables]
        extra_in_db = [t for t in db_tables if t not in code_tables and code_tables]
        column_drifts: list[dict[str, Any]] = []
        for t in code_tables:
            if t in db_tables:
                missing_cols = list(code_tables[t] - db_tables[t])
                extra_cols = list(db_tables[t] - code_tables[t]) if code_tables[t] else []
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
                "missing_in_db": list(code_tables.get(t, [])),
                "missing_in_code": [],
                "type_mismatches": {},
            }

        drift_detected = bool(missing_in_db or column_drifts)
        return {
            "success": True,
            "db_path": str(db_file),
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
        """Offline security audit scanning lockfiles for known vulnerabilities."""
        p_root = Path(root).expanduser().resolve(strict=False)
        target_lock: Path | None = None
        if lockfile_path:
            p = Path(lockfile_path)
            target_lock = p if p.is_absolute() else (p_root / p)
        else:
            candidates = ["poetry.lock", "requirements.txt", "package-lock.json", "composer.lock", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "uv.lock"]
            for c in candidates:
                cand = p_root / c
                if cand.is_file():
                    target_lock = cand
                    break

        if not target_lock or not target_lock.is_file():
            return {"success": False, "error": "no supported lockfile found in root"}

        KNOWN_CVES: list[dict[str, Any]] = [
            {"package": "requests", "max_version": "2.31.0", "cve": "CVE-2023-32681", "severity": "MEDIUM", "fix": ">=2.31.0"},
            {"package": "urllib3", "max_version": "2.0.7", "cve": "CVE-2023-45803", "severity": "HIGH", "fix": ">=2.0.7"},
            {"package": "pyyaml", "max_version": "5.4.0", "cve": "CVE-2020-14343", "severity": "CRITICAL", "fix": ">=5.4"},
            {"package": "jinja2", "max_version": "3.1.3", "cve": "CVE-2024-22195", "severity": "HIGH", "fix": ">=3.1.3"},
            {"package": "cryptography", "max_version": "41.0.6", "cve": "CVE-2023-49083", "severity": "HIGH", "fix": ">=41.0.6"},
            {"package": "lodash", "max_version": "4.17.21", "cve": "CVE-2021-23337", "severity": "HIGH", "fix": ">=4.17.21"},
            {"package": "jsonwebtoken", "max_version": "9.0.0", "cve": "CVE-2022-23529", "severity": "HIGH", "fix": ">=9.0.0"},
            {"package": "axios", "max_version": "1.7.4", "cve": "CVE-2024-39338", "severity": "MEDIUM", "fix": ">=1.7.4"},
            {"package": "guzzlehttp/guzzle", "max_version": "7.4.5", "cve": "CVE-2022-31090", "severity": "HIGH", "fix": ">=7.4.5"},
            {"package": "laravel/framework", "max_version": "9.1.8", "cve": "CVE-2022-40482", "severity": "HIGH", "fix": ">=9.1.8"},
        ]

        text = target_lock.read_text(encoding="utf-8", errors="replace")
        scanned_pkgs: dict[str, str] = {}

        if target_lock.name in {"requirements.txt"}:
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "==" in line:
                    parts = line.split("==")
                    scanned_pkgs[parts[0].strip().lower()] = parts[1].strip()
        elif target_lock.name in {"poetry.lock"}:
            curr_name = ""
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("name = "):
                    curr_name = line.split("=")[1].strip().strip('"').lower()
                elif line.startswith("version = ") and curr_name:
                    scanned_pkgs[curr_name] = line.split("=")[1].strip().strip('"')
                    curr_name = ""
        elif target_lock.name in {"package-lock.json"}:
            try:
                pkg_data = json.loads(text)
                deps = pkg_data.get("packages", pkg_data.get("dependencies", {}))
                for k, v in deps.items():
                    clean_name = k.replace("node_modules/", "").lower()
                    if isinstance(v, dict) and "version" in v:
                        scanned_pkgs[clean_name] = str(v["version"])
            except Exception:
                pass
        elif target_lock.name in {"composer.lock"}:
            try:
                comp_data = json.loads(text)
                for p_item in (comp_data.get("packages", []) or []) + (comp_data.get("packages-dev", []) or []):
                    if isinstance(p_item, dict) and "name" in p_item and "version" in p_item:
                        scanned_pkgs[str(p_item["name"]).lower()] = str(p_item["version"]).lstrip("v")
            except Exception:
                pass

        vulnerabilities: list[dict[str, Any]] = []
        for rule in KNOWN_CVES:
            pkg = rule["package"]
            if pkg in scanned_pkgs:
                inst = scanned_pkgs[pkg]
                def parse_v(v_str: str) -> tuple[int, ...]:
                    return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", v_str)[:3])
                if parse_v(inst) < parse_v(rule["max_version"]):
                    vulnerabilities.append({
                        "package": pkg,
                        "installed_version": inst,
                        "vulnerable_below": rule["max_version"],
                        "cve": rule["cve"],
                        "severity": rule["severity"],
                        "recommendation": f"Upgrade {pkg} to {rule['fix']}",
                    })

        return {
            "success": True,
            "lockfile": str(target_lock),
            "packages_scanned": len(scanned_pkgs),
            "vulnerabilities_found": len(vulnerabilities),
            "vulnerabilities": vulnerabilities,
            "status": "clean" if not vulnerabilities else "vulnerabilities_detected",
        }

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

        results: list[dict[str, Any]] = []
        ignore_dirs = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "dist", "build"}

        if path:
            candidate = root_path / path
            files_to_scan = [candidate] if candidate.is_file() else []
        else:
            files_to_scan = []
            for cur_root, dirs, filenames in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for f in filenames:
                    if f.endswith((".py", ".ts", ".js", ".go", ".rs", ".cs")):
                        files_to_scan.append(Path(cur_root) / f)
                        if len(files_to_scan) >= 400:
                            break
                if len(files_to_scan) >= 400:
                    break

        for fpath in files_to_scan:
            if len(results) >= max_results:
                break
            try:
                rel_p = str(fpath.relative_to(root_path)).replace("\\", "/")
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = content.splitlines()

            if fpath.suffix == ".py":
                try:
                    tree = ast.parse(content, filename=rel_p)
                    for node in ast.walk(tree):
                        if len(results) >= max_results:
                            break

                        if target_pattern in {"bare_except", "unhandled_exception", "missing_error_handling"}:
                            if isinstance(node, ast.Try):
                                for handler in node.handlers:
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
                except Exception:
                    pass

            if not results or fpath.suffix != ".py":
                for idx, line in enumerate(lines, 1):
                    if len(results) >= max_results:
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

        return {
            "success": True,
            "root": str(root_path),
            "pattern": pattern,
            "count": len(results),
            "matches": results,
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

        target_files = files or []
        if not target_files:
            found: list[str] = []
            for cur_root, _, filenames in os.walk(root_path):
                if any(p in cur_root for p in (".git", "node_modules", "__pycache__", ".venv")):
                    continue
                for f in filenames:
                    if f.endswith((".py", ".ts", ".js", ".json", ".md")):
                        p = Path(cur_root) / f
                        found.append(str(p.relative_to(root_path)).replace("\\", "/"))
                        if len(found) >= 15:
                            break
                if len(found) >= 15:
                    break
            target_files = found

        file_breakdown: list[dict[str, Any]] = []
        total_chars = 0
        total_tokens = 0
        all_compressible_regions: list[dict[str, Any]] = []

        for rel in target_files:
            fpath = root_path / rel
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            chars = len(content)
            tokens = int(chars / 3.8) + 1
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

    def skeletonize_code(
        self,
        code: str,
        target_symbols: list[str] | None = None,
        keep_imports: bool = True,
    ) -> dict[str, Any]:
        """Fold non-target function and method bodies into '...' to radically save prompt tokens while preserving AST outline."""
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

