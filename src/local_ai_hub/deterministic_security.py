from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any
import urllib.request

from . import __version__
from .cache import stable_hash
from .deterministic_constants import _GIT_INSIGHT_STREAM_LIMIT
from .git_history_search import search_git_history
from .hotspot_analysis import find_hotspots as _find_hotspots
from .json_utils import dumps as json_dumps
from .process_utils import clean_git_env, run_hidden
from .reparse_points import _is_symlink_or_reparse_point
from .sqlite_support import write_transaction


class DeterministicSecurityMixin:
    def precompute_dead_code(self, root: str, limit: int = 500) -> dict[str, Any]:
        """Precompute unreferenced symbols across the repository and persist them."""
        resolved = self._root(root)
        dead_info = self.detect_dead_code(resolved, limit=limit)
        items = dead_info.get("dead_symbols", [])
        now = time.time()
        with self._lock, closing(self._connect()) as con, write_transaction(
            con, max_duration_seconds=5.0, rollback_label="deterministic dead-code projection"
        ):
            con.execute("DELETE FROM unreferenced_symbols WHERE root=?", (resolved,))
            if items:
                con.executemany(
                    """INSERT OR REPLACE INTO unreferenced_symbols(root, path, name, kind, line, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [(resolved, str(i["path"]), str(i["name"]), str(i["kind"]), int(i.get("line", 0)), now) for i in items],
                )
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
        import subprocess
        import shutil
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
                rev1=rev1, rev2=rev2, path=path, include_snapshot_metadata=False,
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

