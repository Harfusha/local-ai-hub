from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any

from .breaking_change_detection import compare_api_definitions
from .call_graph_diff import analyze_call_graph_diff
from .deterministic_answer_rendering import render_deterministic_answer
from .deterministic_symbol_context import build_symbol_context
from .diff_regexes import (
    _DIFF_EVAL_I,
    _DIFF_SECRET_PASSWORD_I,
    _DIFF_SHELL_I,
)
from .file_card_summary import build_file_card
from .json_utils import dumps as json_dumps
from .module_card_summary import build_module_card_summary
from .project_card_summary import build_project_card_summary
from .related_path_ranking import rank_related_paths
from .source_facts import (
    CONCURRENCY_RE,
    SECURITY_RE,
    SQL_RE,
)
from .sqlite_support import sqlite_batches
from .unified_diff_parser import parse_unified_diff


class DeterministicAnalysisMixin:
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

