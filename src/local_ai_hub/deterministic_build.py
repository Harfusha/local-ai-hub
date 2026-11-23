from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time
from typing import Any

from . import __version__
from .cache import stable_hash
from .deterministic_exact_evidence import collect_exact_evidence
from .deterministic_intent_classification import classify_deterministic_intent
from .deterministic_slice_merging import merge_overlapping_source_slices
from .diagnostic_compression import compress_diagnostic_text
from .json_utils import dumps as json_dumps
from .manifest_discovery import select_manifest_files, walk_manifest_paths
from .manifest_dispatch import parse_manifest_dispatch
from .normalizer import tokenize_query_terms
from .query_intent_terms import filter_intent_noise
from .sqlite_support import write_transaction


class DeterministicBuildMixin:
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
            with self._lock, closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=1.0, rollback_label="deterministic manifest blob cache"
            ):
                con.execute(
                    "INSERT OR REPLACE INTO manifest_blobs(content_hash,analyzer_version,filename,deps_json,scripts_json,updated_at) VALUES(?,?,?,?,?,?)",
                    (content_hash, __version__, filename.lower(), json_dumps(deps, ensure_ascii=False, separators=(",", ":")), json_dumps(scripts, ensure_ascii=False, separators=(",", ":")), now),
                )
                count = int(con.execute("SELECT COUNT(*) FROM manifest_blobs").fetchone()[0])
                if count > self._manifest_blob_max:
                    con.execute("DELETE FROM manifest_blobs WHERE rowid IN (SELECT rowid FROM manifest_blobs ORDER BY updated_at ASC LIMIT ?)", (max(100, count - self._manifest_blob_max),))
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

        with self._lock, closing(self._connect()) as con, write_transaction(
            con, max_duration_seconds=5.0, rollback_label="deterministic manifest refresh"
        ):
            # Another thread may have completed the same refresh while we parsed.
            current = con.execute("SELECT manifest_hash FROM project_state WHERE root=?", (root_s,)).fetchone()
            if current and str(current[0]) == mh:
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

