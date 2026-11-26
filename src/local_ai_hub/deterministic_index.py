from __future__ import annotations

import ast
from collections import Counter, defaultdict
from contextlib import closing
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

from . import __version__
from .cache import MemoryLRUCache, SQLiteCache
from .config_flattening import flatten_config_values
from .deterministic_constants import TEST_MARKERS
from .infra_facts import extract_infra_facts
from .json_utils import dumps as json_dumps
from .process_utils import canonical_root
from .source_facts import extract_source_facts as _extract_source_facts
from .sqlite_counts import initialize_row_counts
from .sqlite_support import (
    SQLiteChangeObserver,
    connect_sqlite,
    initialize_wal,
    is_busy_error,
    quick_sanity_check,
    sqlite_batches,
    write_transaction,
)
from .state_paths import configured_state_dir

logger = logging.getLogger(__name__)


class DeterministicIndexMixin:
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
        self._change_summary_cache = SQLiteCache(
            configured_state_dir(config) / "cache.sqlite", "git-change:hunk-summary-v2",
            ttl_seconds=7 * 86400, max_entries=4096, busy_timeout_seconds=0.05, busy_retries=1,
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
        with self._lock, closing(self._connect()) as con, write_transaction(
            con, max_duration_seconds=5.0, rollback_label="deterministic test source links"
        ):
            con.executemany(
                "INSERT OR REPLACE INTO test_source_links(root, source_path, test_path, confidence, updated_at) VALUES(?, ?, ?, ?, ?)",
                [(resolved, src.replace("\\", "/"), test.replace("\\", "/"), float(conf), now) for src, test, conf in links],
            )

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
                with write_transaction(
                    con, max_duration_seconds=1.0, rollback_label="deterministic query cache"
                ):
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
        with self._lock, closing(self._connect()) as con, write_transaction(
            con, max_duration_seconds=5.0, rollback_label="deterministic prune"
        ):
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
            with self._lock, closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=1.0, rollback_label="deterministic fact blob cache"
            ):
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
            with self._lock, closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=2.0, rollback_label="deterministic remove file"
            ):
                existed = con.execute("SELECT 1 FROM files WHERE root=? AND path=?", (root_s, path)).fetchone() is not None
                con.execute("DELETE FROM files WHERE root=? AND path=?", (root_s, path))
                con.execute("DELETE FROM facts WHERE root=? AND path=?", (root_s, path))
                try:
                    con.execute("DELETE FROM fact_fts WHERE root=? AND path=?", (root_s, path))
                except sqlite3.OperationalError:
                    pass
                if existed:
                    self._bump_generation(con, root_s)
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
        with self._lock, closing(self._connect()) as con, write_transaction(
            con, max_duration_seconds=5.0, rollback_label="deterministic update file"
        ):
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
        paths = list(dict.fromkeys(path for path, _ in normalized))
        existing: dict[str, str] = {}
        with self._lock, closing(self._connect()) as con:
            con.execute("BEGIN")
            for batch in sqlite_batches(paths):
                placeholders = ",".join("?" for _ in batch)
                existing.update(con.execute(
                    f"SELECT path,content_hash FROM files WHERE root=? AND path IN ({placeholders})",
                    (root_s, *batch),
                ).fetchall())

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
            with self._lock, closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="deterministic batch update"
            ):
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
            self._stats["files_parsed"] += len(parsed_rows)
            self._stats["facts_extracted"] += sum(len(x[3]) for x in parsed_rows)
            self._stats["fact_blob_misses"] += len(blob_rows)
        return {"success": True, "updated": len(parsed_rows), "cached": cached, "failed": failed, "fact_blob_hits": len(parsed_rows)-len(blob_rows)}

