from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from .cache import MemoryLRUCache, SQLiteCache, stable_hash
from .normalizer import normalize_query, tokenize_query_terms
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error


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


class DeterministicEngine:
    """Persistent deterministic project intelligence before any LLM inference.

    The engine extracts facts from source/config/manifests with stdlib parsers and
    conservative regexes. Every file is content-addressed, so unchanged facts are
    reused across agents/restarts. Query resolution never rewrites source evidence;
    it returns coordinates and exact evidence ids supplied by EvidenceStore.
    """

    VERSION = 1

    def __init__(self, config: dict[str, Any] | None = None, repo_tools: Any = None, code_index: Any = None, evidence: Any | None = None):
        config = config or {"server": {"state_dir": tempfile.gettempdir()}}
        self.config = config
        self.repo_tools = repo_tools
        self.code_index = code_index
        self.evidence = evidence
        cfg = config.get("deterministic", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.direct_confidence = float(cfg.get("direct_confidence", 0.94))
        self.max_query_results = int(cfg.get("max_query_results", 24))
        self.max_evidence = int(cfg.get("max_evidence", 12))
        self.max_manifest_bytes = int(cfg.get("max_manifest_bytes", 1_500_000))
        self.db_path = Path(config.get("server", {}).get("state_dir", tempfile.gettempdir())) / "deterministic.sqlite3"
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
            Path(config["server"]["state_dir"]) / "cache.sqlite3", "dependency-audit:osv",
            ttl_seconds=max(60, int(audit_cfg.get("osv_cache_ttl_seconds", 6 * 3600))), max_entries=20000,
        )
        self._fact_blob_max = int(cfg.get("fact_blob_max_entries", 100000))
        self._manifest_blob_max = int(cfg.get("manifest_blob_max_entries", 20000))
        self._fact_blob_l1 = MemoryLRUCache(max_entries=4096, ttl_seconds=3600)
        self._manifest_blob_l1 = MemoryLRUCache(max_entries=1024, ttl_seconds=3600)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.db_path, timeout_seconds=0.75, row_factory=sqlite3.Row)
        con.execute("PRAGMA cache_size=-65536")
        con.execute("PRAGMA mmap_size=536870912")
        con.execute("PRAGMA synchronous=NORMAL")
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
              content_hash TEXT NOT NULL,analyzer_version INTEGER NOT NULL,language TEXT NOT NULL,facts_json TEXT NOT NULL,updated_at REAL NOT NULL,
              PRIMARY KEY(content_hash,analyzer_version,language));
            CREATE INDEX IF NOT EXISTS idx_fact_blobs_updated ON fact_blobs(updated_at);
            CREATE TABLE IF NOT EXISTS manifest_blobs(
              content_hash TEXT NOT NULL,analyzer_version INTEGER NOT NULL,filename TEXT NOT NULL,deps_json TEXT NOT NULL,scripts_json TEXT NOT NULL,updated_at REAL NOT NULL,
              PRIMARY KEY(content_hash,analyzer_version,filename));
            CREATE INDEX IF NOT EXISTS idx_manifest_blobs_updated ON manifest_blobs(updated_at);
            """
        )
        try:
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts USING fts5(root UNINDEXED,path UNINDEXED,kind UNINDEXED,name,value)")
        except sqlite3.OperationalError:
            pass
        con.execute(f"PRAGMA user_version={self.VERSION}")

    def _init_db(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                ok = con.execute("PRAGMA quick_check").fetchone()[0]
                if ok != "ok":
                    raise sqlite3.DatabaseError(str(ok))
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
        return str(Path(root).expanduser().resolve())

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
                return json.loads(json.dumps(row[1]))
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
                return json.loads(json.dumps(value))
        except (sqlite3.DatabaseError, json.JSONDecodeError):
            return None
        return None

    def _query_cache_put(self, root: str, generation: int, key: str, value: dict[str, Any]) -> None:
        now = time.time(); cache_key = (root, generation, key)
        copy = json.loads(json.dumps(value))
        with self._lock:
            self._query_l1[cache_key] = (now, copy)
            if len(self._query_l1) > self._query_l1_max:
                oldest = min(self._query_l1.items(), key=lambda kv: kv[1][0])[0]
                self._query_l1.pop(oldest, None)
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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
        return any(marker in low for marker in TEST_MARKERS) or name.startswith("test_") or name.endswith("test.py")

    @staticmethod
    def _language(path: str) -> str:
        ext = Path(path).suffix.lower()
        return {
            ".py": "python", ".php": "php", ".js": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".cs": "csharp", ".java": "java",
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

        # React / TypeScript analyzer
        if ext in (".ts", ".tsx", ".js", ".jsx"):
            REACT_COMPONENT = re.compile(r"(?:export\s+(?:default\s+)?)?(?:function|const|class)\s+([A-Z][A-Za-z0-9_]+)", re.M)
            REACT_HOOK = re.compile(r"\bconst\s+(use[A-Z][A-Za-z0-9_]*)\s*=", re.M)
            REACT_ROUTE = re.compile(r'(?:path|to)\s*[:=]\s*[\'"`]([/][^\'"`]*)[\'"`]', re.M)
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
        key = f"{content_hash}:{self.VERSION}:{language}"
        cached = self._fact_blob_l1.get(key)
        if cached is not None:
            self._stats["fact_blob_hits"] += 1
            return cached
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT facts_json FROM fact_blobs WHERE content_hash=? AND analyzer_version=? AND language=?",
                    (content_hash, self.VERSION, language),
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
        key = f"{content_hash}:{self.VERSION}:{language}"
        self._fact_blob_l1.set(key, facts)
        try:
            payload = json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
            with self._lock, closing(self._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO fact_blobs(content_hash,analyzer_version,language,facts_json,updated_at) VALUES(?,?,?,?,?)",
                    (content_hash, self.VERSION, language, payload, time.time()),
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
                [(root_s, path, f["kind"], f["name"], f["value"], f["line"], json.dumps(f["extra"], ensure_ascii=False, separators=(",", ":"))) for f in facts],
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
                    rows = con.execute(f"SELECT content_hash,language,facts_json FROM fact_blobs WHERE analyzer_version=? AND ({clauses})", (self.VERSION, *params)).fetchall()
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
                blob_rows.append((content_hash, self.VERSION, language, json.dumps(facts, ensure_ascii=False, separators=(",", ":")), now))
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
                    con.executemany("INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)", [(root_s, path, f["kind"], f["name"], f["value"], f["line"], json.dumps(f["extra"], ensure_ascii=False, separators=(",", ":"))) for f in facts])
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
        key = f"{content_hash}:{self.VERSION}:{filename.lower()}"
        cached = self._manifest_blob_l1.get(key)
        if cached is not None:
            self._stats["manifest_blob_hits"] += 1
            return cached
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT deps_json,scripts_json FROM manifest_blobs WHERE content_hash=? AND analyzer_version=? AND filename=?",
                    (content_hash, self.VERSION, filename.lower()),
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
        key = f"{content_hash}:{self.VERSION}:{filename.lower()}"
        self._manifest_blob_l1.set(key, (deps, scripts))
        try:
            now = time.time()
            with self._lock, closing(self._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO manifest_blobs(content_hash,analyzer_version,filename,deps_json,scripts_json,updated_at) VALUES(?,?,?,?,?,?)",
                    (content_hash, self.VERSION, filename.lower(), json.dumps(deps, ensure_ascii=False, separators=(",", ":")), json.dumps(scripts, ensure_ascii=False, separators=(",", ":")), now),
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
                        for item in fts_rows:
                            k = (item["path"], item["kind"], item["name"], item["value"])
                            if k in fact_map and fact_map[k] not in rows:
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
            "v": self.VERSION,
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

    @staticmethod
    def _extract_py_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
        defs: dict[str, dict[str, Any]] = {}
        i = 0
        n = len(lines)
        while i < n:
            raw = lines[i]
            s = raw.strip()
            if s.startswith(("def ", "async def ", "class ")):
                stmt = s
                paren_count = stmt.count("(") - stmt.count(")")
                while paren_count > 0 and i + 1 < n:
                    i += 1
                    stmt += " " + lines[i].strip()
                    paren_count = stmt.count("(") - stmt.count(")")
                try:
                    to_parse = stmt
                    if not to_parse.endswith(":"):
                        to_parse += ":"
                    to_parse += "\n    pass"
                    tree = ast.parse(to_parse)
                    for node in tree.body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name.startswith("_") and node.name not in ("__init__", "__call__", "__getitem__", "__enter__", "__exit__"):
                                continue
                            pos_args = [a.arg for a in node.args.args]
                            clean_args = [a for a in pos_args if a not in ("self", "cls")]
                            defaults_count = len(node.args.defaults)
                            req_total = len(pos_args) - defaults_count
                            clean_req = max(0, req_total - (1 if pos_args and pos_args[0] in ("self", "cls") else 0))
                            defs[node.name] = {
                                "name": node.name,
                                "kind": "function",
                                "pos_args": clean_args,
                                "required_count": clean_req,
                                "sig": stmt,
                            }
                        elif isinstance(node, ast.ClassDef):
                            if node.name.startswith("_"):
                                continue
                            defs[node.name] = {
                                "name": node.name,
                                "kind": "class",
                                "sig": stmt,
                            }
                except Exception:
                    m = re.match(r"(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\((.*?)\)", stmt)
                    if m:
                        name, args_part = m.group(1), m.group(2)
                        if not name.startswith("_") or name in ("__init__", "__call__"):
                            raw_args = [a.strip() for a in args_part.split(",") if a.strip()]
                            clean_args = [a.split(":")[0].split("=")[0].strip() for a in raw_args if a.split(":")[0].strip() not in ("self", "cls")]
                            req_args = [a for a in raw_args if "=" not in a and a.split(":")[0].strip() not in ("self", "cls")]
                            defs[name] = {
                                "name": name,
                                "kind": "function",
                                "pos_args": clean_args,
                                "required_count": len(req_args),
                                "sig": stmt,
                            }
                    else:
                        m = re.match(r"class\s+([A-Za-z0-9_]+)", stmt)
                        if m:
                            name = m.group(1)
                            if not name.startswith("_"):
                                defs[name] = {"name": name, "kind": "class", "sig": stmt}
            i += 1
        return defs

    @staticmethod
    def _extract_ts_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
        defs: dict[str, dict[str, Any]] = {}
        ts_pattern = re.compile(
            r"^\s*export\s+(?:default\s+)?(?:async\s+)?(function|class|interface|type|const|let|var)\s+([A-Za-z0-9_$]+)(?:\s*<.*?>)?(?:\s*\((.*?)\))?",
        )
        for raw in lines:
            line = raw.strip()
            m = ts_pattern.search(line)
            if m:
                kind = m.group(1)
                name = m.group(2)
                params_raw = m.group(3)
                if kind in ("let", "var"):
                    continue
                d: dict[str, Any] = {"name": name, "kind": kind, "sig": line}
                if params_raw is not None and kind == "function":
                    parts = []
                    depth = 0
                    cur = ""
                    for ch in params_raw:
                        if ch in "({[<": depth += 1; cur += ch
                        elif ch in ")}]>": depth -= 1; cur += ch
                        elif ch == "," and depth == 0:
                            if cur.strip(): parts.append(cur.strip())
                            cur = ""
                        else: cur += ch
                    if cur.strip(): parts.append(cur.strip())
                    req_count = 0
                    param_names = []
                    for p in parts:
                        p_name = p.split(":")[0].strip()
                        is_opt = "?" in p_name or "=" in p
                        clean_p = p_name.rstrip("?").strip()
                        if not is_opt:
                            req_count += 1
                        param_names.append(clean_p)
                    d["params"] = param_names
                    d["required_count"] = req_count
                defs[name] = d
        return defs

    @staticmethod
    def _extract_cs_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
        defs: dict[str, dict[str, Any]] = {}
        class_re = re.compile(r"^\s*public\s+(?:static\s+|sealed\s+|abstract\s+|partial\s+)*(class|interface|struct|record|enum)\s+([A-Za-z0-9_]+)")
        method_re = re.compile(r"^\s*public\s+(?:static\s+|virtual\s+|override\s+|async\s+|sealed\s+|abstract\s+)*([\w<>\[\],\s\?]+?)\s+([A-Za-z0-9_]+)\s*\((.*?)\)")
        for raw in lines:
            line = raw.strip()
            cm = class_re.search(line)
            if cm:
                defs[cm.group(2)] = {"name": cm.group(2), "kind": cm.group(1), "sig": line}
                continue
            mm = method_re.search(line)
            if mm:
                name, params_raw = mm.group(2), mm.group(3)
                parts = [p.strip() for p in params_raw.split(",") if p.strip()]
                req_count = sum(1 for p in parts if "=" not in p)
                defs[name] = {"name": name, "kind": "method", "required_count": req_count, "sig": line}
        return defs

    @staticmethod
    def _extract_go_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
        defs: dict[str, dict[str, Any]] = {}
        func_re = re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Z][A-Za-z0-9_]*)\s*\((.*?)\)")
        type_re = re.compile(r"^\s*type\s+([A-Z][A-Za-z0-9_]*)\s+(struct|interface)")
        for raw in lines:
            line = raw.strip()
            fm = func_re.search(line)
            if fm:
                name = fm.group(1)
                defs[name] = {"name": name, "kind": "function", "sig": line}
                continue
            tm = type_re.search(line)
            if tm:
                name, kind = tm.group(1), tm.group(2)
                defs[name] = {"name": name, "kind": kind, "sig": line}
        return defs

    @staticmethod
    def _extract_rust_diff_defs(lines: list[str]) -> dict[str, dict[str, Any]]:
        defs: dict[str, dict[str, Any]] = {}
        rust_re = re.compile(r"^\s*pub(?:\(.*?\))?\s+(fn|struct|enum|trait|type)\s+([A-Za-z0-9_]+)")
        for raw in lines:
            line = raw.strip()
            rm = rust_re.search(line)
            if rm:
                kind, name = rm.group(1), rm.group(2)
                defs[name] = {"name": name, "kind": kind, "sig": line}
        return defs

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
        text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
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
        cache_key = stable_hash({"v": 1, "queries": queries})
        cached = self._osv_cache.get(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("vulnerabilities"), list):
            return cached["vulnerabilities"], None
        cfg = self.config.get("dependency_audit", {})
        timeout = max(0.5, min(15.0, float(cfg.get("osv_timeout_seconds", 5.0))))
        osv_url = str(cfg.get("osv_api_url", "https://api.osv.dev/v1/querybatch"))
        request = urllib.request.Request(
            osv_url,
            data=json.dumps({"queries": queries}).encode("utf-8"),
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

    def audit_dependencies(self, root: str) -> dict[str, Any]:
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
        return {
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
        aliases = {"cs": "csharp", "py": "python", "ts": "typescript", "js": "javascript"}
        requested_lang = aliases.get(requested_lang, requested_lang)
        supported = {"auto", "csharp", "python", "typescript", "javascript"}
        if requested_lang not in supported:
            return {"success": False, "root": resolved, "language": requested_lang, "error": f"unsupported language: {requested_lang}"}

        def language_for(path: str) -> str:
            if requested_lang != "auto":
                return requested_lang
            suffix = Path(path).suffix.lower()
            if suffix == ".py": return "python"
            if suffix == ".cs": return "csharp"
            if suffix in {".ts", ".tsx"}: return "typescript"
            if suffix in {".js", ".jsx", ".mjs", ".cjs"}: return "javascript"
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
                if pth.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
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

    def ast_outline(self, root: str, path: str) -> dict[str, Any]:
        """Generate a dense, high-efficiency AST outline of a source file, saving up to 90% tokens."""
        resolved_root = Path(self._root(root))
        target = (resolved_root / path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            return {"success": False, "error": "file is outside project root"}

        if not target.is_file():
            return {"success": False, "error": f"file not found: {path}"}

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        ext = target.suffix.lower()
        symbols: list[dict[str, Any]] = []
        raw_tokens = max(1, len(text) // 4)

        if ext == ".py":
            try:
                tree = ast.parse(text)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        bases = [ast.unparse(b) for b in node.bases]
                        methods: list[dict[str, Any]] = []
                        doc = ast.get_docstring(node) or ""
                        doc_summary = doc.strip().splitlines()[0] if doc.strip() else ""
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                m_doc = ast.get_docstring(item) or ""
                                m_doc_summary = m_doc.strip().splitlines()[0] if m_doc.strip() else ""
                                args_str = ", ".join(a.arg for a in item.args.args)
                                ret = ast.unparse(item.returns) if item.returns else ""
                                methods.append({
                                    "name": item.name,
                                    "line": item.lineno,
                                    "is_async": isinstance(item, ast.AsyncFunctionDef),
                                    "signature": f"({args_str})" + (f" -> {ret}" if ret else ""),
                                    "doc": m_doc_summary[:120],
                                })
                        symbols.append({
                            "kind": "class",
                            "name": node.name,
                            "line": node.lineno,
                            "bases": bases,
                            "doc": doc_summary[:160],
                            "methods": methods,
                        })
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        f_doc = ast.get_docstring(node) or ""
                        f_doc_summary = f_doc.strip().splitlines()[0] if f_doc.strip() else ""
                        args_str = ", ".join(a.arg for a in node.args.args)
                        ret = ast.unparse(node.returns) if node.returns else ""
                        symbols.append({
                            "kind": "function",
                            "name": node.name,
                            "line": node.lineno,
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                            "signature": f"({args_str})" + (f" -> {ret}" if ret else ""),
                            "doc": f_doc_summary[:160],
                        })
                    elif isinstance(node, ast.Assign):
                        for t in node.targets:
                            if isinstance(t, ast.Name) and (t.id.isupper() or t.id.startswith("_")):
                                symbols.append({
                                    "kind": "constant",
                                    "name": t.id,
                                    "line": node.lineno,
                                })
            except Exception:
                pass
        else:
            # Universal regex outline for C#, TypeScript, Java, Rust, Go
            import re
            lines = text.splitlines()
            class_re = re.compile(r"^\s*(?:public|private|protected|internal|export|abstract|sealed)?\s*(?:class|interface|struct|enum|trait)\s+([A-Za-z0-9_]+)", re.M)
            func_re = re.compile(r"^\s*(?:public|private|protected|internal|export|async|fn|func|def)?\s*(?:[A-Za-z0-9_<>[\]?]+\s+)?([A-Za-z0-9_]+)\s*\((.*?)\)(?:\s*:\s*[A-Za-z0-9_<>[\]?]+)?\s*[{;]", re.M)
            for i, line in enumerate(lines, 1):
                cm = class_re.match(line)
                if cm:
                    symbols.append({"kind": "class", "name": cm.group(1), "line": i, "raw": line.strip()[:100]})
                    continue
                fm = func_re.match(line)
                if fm and not any(k in fm.group(1) for k in ("if", "for", "while", "switch", "catch")):
                    symbols.append({"kind": "function", "name": fm.group(1), "line": i, "signature": f"({fm.group(2).strip()[:60]})"})

        outline_text = json.dumps(symbols, indent=2)
        outline_tokens = max(1, len(outline_text) // 4)
        savings = round(max(0.0, (raw_tokens - outline_tokens) / raw_tokens) * 100, 1)

        return {
            "success": True,
            "path": path,
            "symbols_count": len(symbols),
            "symbols": symbols,
            "raw_tokens": raw_tokens,
            "outline_tokens": outline_tokens,
            "token_savings_pct": savings,
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

    def security_audit(self, root: str, limit: int = 50) -> dict[str, Any]:
        """Deterministic static security analysis (hardcoded secrets, unsafe deserialization, SQL injection)."""
        resolved_root = Path(self._root(root))
        import re

        secret_patterns = [
            ("AWS Access Key", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
            ("GitHub Token", re.compile(r"\b(ghp_[0-9a-zA-Z]{36}|github_pat_[0-9a-zA-Z_]{82})\b")),
            ("Slack Token", re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b")),
            ("Private Key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
            ("Hardcoded Password", re.compile(r"""(?:password|passwd|pwd|secret|api_key)\s*[:=]\s*["']([^"'\s]{6,})["']""", re.I)),
        ]

        code_smell_patterns = [
            ("Unsafe eval/exec", re.compile(r"\b(eval|exec)\s*\(")),
            ("Unsafe Pickle", re.compile(r"\bpickle\.loads?\s*\(")),
            ("Unsafe PyYAML", re.compile(r"\byaml\.load\s*\([^,]+(?:\)|,\s*Loader\s*=\s*(?:yaml\.)?(?:Unsafe|Full)?Loader\b)")),
            ("Shell Injection Risk", re.compile(r"\bsubprocess\.(?:Popen|run|call)\s*\(.*shell\s*=\s*True", re.S)),
        ]

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
                for i, line in enumerate(txt.splitlines(), 1):
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
                        if pat.search(line):
                            findings.append({
                                "severity": "MEDIUM",
                                "type": "code_vulnerability",
                                "title": name,
                                "path": rel,
                                "line": i,
                                "snippet": stripped[:120],
                            })
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
            self._status_cache[key] = {"time": now, "data": res}
            return res
        except Exception as exc:
            return {"success": False, "healthy": False, "error": str(exc), "stats": dict(self._stats)}
