from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path, PureWindowsPath
import re
import subprocess
import threading
import time
from typing import Any

from .budget import chars_for_tokens, estimate_tokens
from .process_utils import hidden_run_kwargs, popen_managed
from .repo_tools_constants import (
    _IMPACT_RIPGREP_TIMEOUT_SECONDS,
    _IMPACT_SCAN_MAX_FILES,
    _IMPACT_SCAN_TIMEOUT_SECONDS,
    _SYMBOL_PATTERNS,
)


RepositoryTools = None


class RepoToolsContextMixin:
    def verify_evidence(self, root: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        base = self._root(root)
        checked: list[dict[str, Any]] = []
        stale = 0
        for item in evidence[:200]:
            rel = str(item.get("path", ""))
            expected = str(item.get("file_sha256", ""))
            candidate = (base / rel).resolve(strict=False)
            try:
                candidate.relative_to(base)
            except ValueError:
                checked.append({"path": rel, "status": "invalid-path"}); stale += 1; continue
            if not candidate.is_file():
                checked.append({"path": rel, "status": "missing"}); stale += 1; continue
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            status = "current" if expected and actual == expected else "stale"
            if status != "current":
                stale += 1
            checked.append({"path": rel, "status": status, "expected_sha256": expected or None, "actual_sha256": actual})
        return {"success": True, "root": str(base), "stale": stale > 0, "stale_count": stale, "checked": checked}

    def git_diff(self, root: str, base: str = "HEAD", staged: bool = False, max_tokens: int = 10000,
                 *, rev1: str | None = None, rev2: str | None = None, path: str | None = None,
                 include_snapshot_metadata: bool = True) -> dict[str, Any]:
        repo = self._root(root)
        revision_mode = rev1 is not None or rev2 is not None
        if revision_mode and (staged or rev1 is None or rev2 is None):
            return {"success": False, "error": "rev1 and rev2 must be supplied together and cannot be combined with staged",
                    "terminal": True, "retryable": False}
        if path is not None and (not isinstance(path, str) or "\0" in path or len(path) > 4096):
            return {"success": False, "error": "invalid diff path", "terminal": True, "retryable": False}
        pinned: list[str] = []
        try:
            probe = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True,
                timeout=3, check=False, encoding="utf-8", errors="replace", **hidden_run_kwargs(),
            )
        except Exception as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
            return {"success": False, "error": "git diff requires a Git repository", "terminal": True, "retryable": False}
        if revision_mode:
            for revision in (rev1, rev2):
                if not isinstance(revision, str) or not revision.strip() or len(revision) > 512 or revision.startswith("-") or "\0" in revision:
                    return {"success": False, "error": "invalid commit revision", "status_code": 400, "terminal": True, "retryable": False}
                try:
                    resolved = subprocess.run(
                        ["git", "-C", str(repo), "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"],
                        capture_output=True, text=True, timeout=3, check=False,
                        encoding="utf-8", errors="replace", **hidden_run_kwargs(),
                    )
                except Exception as exc:
                    return {"success": False, "error": f"revision resolution failed: {type(exc).__name__}", "terminal": True, "retryable": False}
                commit = resolved.stdout.strip()
                if resolved.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit):
                    return {"success": False, "error": "revision does not resolve to one commit", "status_code": 400, "terminal": True, "retryable": False}
                pinned.append(commit)
        selectors: list[str] = []
        if staged:
            selectors.append("--cached")
        elif revision_mode:
            selectors.append("...".join(pinned))
        elif base:
            if not isinstance(base, str) or base.startswith("-") or "\0" in base or len(base) > 1024:
                return {"success": False, "error": "invalid diff base", "terminal": True, "retryable": False}
            selectors.append(base)
        pathspec = ["--", ":(literal)" + path] if path else ["--"]
        cmd = ["git", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv", "--unified=3", *selectors, *pathspec]
        budget_chars = max(1, chars_for_tokens(max_tokens))
        def bounded_process(command: list[str], retain_limit: int, on_stdout_chunk: Any = None, digest_output: bool = False) -> dict[str, Any]:
            retained = bytearray()
            stderr_retained = bytearray()
            digest = hashlib.sha256() if digest_output else None
            total = 0
            stream_errors: list[str] = []

            def drain(stream: Any, output: bytearray, digest_value: Any = None, stream_name: str = "stdout") -> None:
                nonlocal total
                try:
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            return
                        if digest_value is not None:
                            digest_value.update(chunk)
                            total += len(chunk)
                        if on_stdout_chunk is not None and output is retained:
                            try:
                                on_stdout_chunk(chunk)
                            except Exception:
                                pass
                        remaining = max(0, retain_limit - len(output))
                        if remaining:
                            output.extend(chunk[:remaining])
                except Exception as exc:
                    if len(stream_errors) < 2:
                        detail = str(exc).replace("\r", " ").replace("\n", " ")[:200]
                        stream_errors.append(f"{stream_name}: {type(exc).__name__}: {detail}")
                    return

            process = None
            try:
                process = popen_managed(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_run_kwargs())
                stdout_thread = threading.Thread(target=drain, args=(process.stdout, retained, digest, "stdout"), daemon=True)
                stderr_thread = threading.Thread(target=drain, args=(process.stderr, stderr_retained, None, "stderr"), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
                try:
                    returncode = process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    stdout_thread.join(timeout=5)
                    stderr_thread.join(timeout=5)
                    return {"returncode": None, "error": "git diff timed out", "retryable": True}
                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)
                if stdout_thread.is_alive() or stderr_thread.is_alive():
                    stream_errors.append("reader thread did not drain before timeout")
                if stream_errors:
                    return {
                        "returncode": None,
                        "error": "git diff stream read failed: " + "; ".join(stream_errors[:2]),
                        "retryable": True,
                    }
                return {
                    "returncode": returncode,
                    "stdout": bytes(retained),
                    "stderr": bytes(stderr_retained),
                    "total": total,
                    "sha256": digest.hexdigest() if digest is not None else "",
                }
            except Exception as exc:
                return {"returncode": None, "error": str(exc), "retryable": True}
            finally:
                if process is not None:
                    for stream in (process.stdout, process.stderr):
                        try:
                            stream.close()
                        except Exception:
                            pass

        content_result = bounded_process(cmd, budget_chars, digest_output=True)
        if content_result.get("returncode") is None:
            return {"success": False, "error": content_result.get("error", "git diff failed"), "retryable": content_result.get("retryable", False)}
        stderr_text = bytes(content_result.get("stderr", b"")).decode("utf-8", errors="replace").strip()
        if content_result["returncode"] != 0:
            return {"success": False, "error": stderr_text or "git diff failed"}
        stdout_retained = bytes(content_result.get("stdout", b""))
        stdout_total = int(content_result.get("total", len(stdout_retained)))
        text = stdout_retained.decode("utf-8", errors="replace")
        truncated = stdout_total > len(stdout_retained) or len(text) > budget_chars
        if len(text) > budget_chars:
            text = text[:budget_chars]
            truncated = True
        if truncated:
            text += "\n\n[... additional diff sections omitted to fit local review budget ...]\n"
        changed: list[str] = []
        can_reuse_diff_paths = not truncated
        retained_stdout = stdout_retained.decode("utf-8", errors="replace")
        for line in retained_stdout.splitlines():
            if not line.startswith("diff --git "):
                continue
            if not line.startswith("diff --git a/"):
                can_reuse_diff_paths = False
                continue
            match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            if match:
                old_path, new_path = match.groups()
                if old_path != new_path or not re.fullmatch(r"[A-Za-z0-9_./@+-]+", new_path):
                    can_reuse_diff_paths = False
                changed.append(new_path)
            else:
                can_reuse_diff_paths = False
        if can_reuse_diff_paths:
            path_names = list(dict.fromkeys(changed))
        else:
            path_names: list[str] = []
            path_pending = bytearray()
            path_capture_error = ""

            def collect_path_chunk(chunk: bytes) -> None:
                nonlocal path_capture_error
                if path_capture_error:
                    return
                if len(path_names) >= 4096:
                    path_capture_error = "path count cap reached"
                    return
                data = bytes(path_pending) + chunk
                pieces = data.split(b"\0")
                tail = pieces.pop()
                if len(tail) > 4096:
                    path_capture_error = "path byte cap reached"
                    return
                path_pending.clear()
                path_pending.extend(tail)
                for piece in pieces:
                    if not piece:
                        continue
                    if len(piece) > 4096:
                        path_capture_error = "path byte cap reached"
                        return
                    if len(path_names) >= 4096:
                        path_capture_error = "path count cap reached"
                        return
                    path_names.append(piece.decode("utf-8", errors="replace"))

            path_cmd = ["git", "-C", str(repo), "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", *selectors, *pathspec]
            path_result = bounded_process(path_cmd, 0, on_stdout_chunk=collect_path_chunk)
            if path_capture_error:
                return {
                    "success": False,
                    "error": f"git diff path capture failed: {path_capture_error}",
                    "terminal": False,
                    "retryable": True,
                    "paths_complete": False,
                }
            if path_result.get("returncode") is None or path_result.get("returncode") != 0:
                path_error = bytes(path_result.get("stderr", b"")).decode("utf-8", errors="replace").strip()
                return {
                    "success": False,
                    "error": f"git diff path capture failed: {path_error or path_result.get('error', 'non-zero exit')}",
                    "terminal": False,
                    "retryable": bool(path_result.get("retryable", True)),
                    "paths_complete": False,
                }
            if path_pending and len(path_names) < 4096:
                path_names.append(bytes(path_pending)[:4096].decode("utf-8", errors="replace"))
        snapshot = self.git_snapshot(str(repo)) if include_snapshot_metadata else None
        changed_files = list(dict.fromkeys(path_names + changed))
        changed_paths = (
            changed_files
            if revision_mode or path or snapshot is None
            else list(dict.fromkeys(changed_files + list(snapshot.changed_paths)))
        )
        untracked: list[str] = []
        if snapshot is not None and not staged and not revision_mode:
            path_filter = path.replace("\\", "/").rstrip("/") if path else ""
            untracked = sorted(
                item for item, state in snapshot.status.items()
                if state == "untracked" and (not path_filter or item == path_filter or item.startswith(path_filter + "/"))
            )
        return {
            "success": True, "root": str(repo), "diff": text, "changed_files": changed_files,
            "changed_paths": changed_paths, "revision": snapshot.revision if snapshot else None,
            "untracked_files_excluded": untracked[:100],
            "untracked_inventory_complete": bool(snapshot is not None and not snapshot.degraded and len(untracked) <= 100),
            "repository_revision": snapshot.repository_revision if snapshot else None,
            "estimated_tokens": estimate_tokens(text),
            "original_estimated_tokens": max(estimate_tokens(text), (stdout_total + 3) // 4),
            "truncated": truncated, "diff_sha256": content_result["sha256"],
            "paths_complete": True,
            "comparison": "merge_base" if revision_mode else "index" if staged else "working_tree",
            "rev1": rev1, "rev2": rev2,
            "resolved_rev1": pinned[0] if pinned else None,
            "resolved_rev2": pinned[1] if pinned else None,
        }

    def impact_analysis(
        self,
        root: str,
        base: str = "HEAD",
        staged: bool = False,
        max_symbols: int = 48,
        max_dependents: int = 30,
        *,
        diff_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cheap generic change-impact/test targeting without invoking an LLM.

        This is deliberately heuristic. Serena remains the preferred source
        for exact symbol relationships; this fallback is available everywhere and is
        useful before spending cloud context.
        """
        repo = self._root(root)
        diff = diff_result if isinstance(diff_result, dict) else self.git_diff(
            str(repo), base=base, staged=staged, max_tokens=2500
        )
        if not diff.get("success"):
            return diff
        changed_files = [str(x) for x in diff.get("changed_files", [])]
        if not changed_files:
            return {
                "success": True, "root": str(repo), "changed_files": [],
                "changed_symbols": [], "likely_dependents": [], "suggested_tests": [],
                "risk": {"score": 0, "level": "low", "reasons": ["no changed files"]},
            }

        changed_symbols: list[dict[str, Any]] = []
        changed_set = set(changed_files)
        for rel in changed_files:
            path = (repo / rel).resolve(strict=False)
            try:
                path.relative_to(repo)
            except ValueError:
                continue
            if not path.is_file() or len(changed_symbols) >= max_symbols:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line_no, line in enumerate(lines, 1):
                for pattern in _SYMBOL_PATTERNS:
                    match = pattern.match(line)
                    if match:
                        name = match.group(1)
                        if len(name) >= 3 and not any(x["name"] == name for x in changed_symbols):
                            changed_symbols.append({"name": name, "path": rel, "line": line_no})
                        break
                if len(changed_symbols) >= max_symbols:
                    break

        symbol_names = [x["name"] for x in changed_symbols]
        dependents: list[dict[str, Any]] = []
        test_candidates: list[dict[str, Any]] = []
        changed_stems = {Path(x).stem.lower().replace("test_", "").replace("_test", "") for x in changed_files}

        # Local AI deterministic fast path: let ripgrep reduce the dependent candidate
        # set before opening files. Exact counts are still verified against our own
        # decoded snapshots, so rg is only an accelerator and never a source of truth.
        dependent_candidates: set[str] | None = None
        if self._rg and symbol_names:
            cmd = [self._rg, "--files-with-matches", "--fixed-strings"]
            for name in symbol_names[:32]:
                cmd.extend(["-e", name])
            cmd.append(str(repo))
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=min(float(self.ripgrep_timeout), _IMPACT_RIPGREP_TIMEOUT_SECONDS), check=False, encoding="utf-8", errors="replace", **hidden_run_kwargs())
                if proc.returncode in {0, 1}:
                    dependent_candidates = set()
                    for raw in proc.stdout.splitlines():
                        try:
                            rel = str(Path(raw).resolve(strict=False).relative_to(repo)).replace("\\", "/")
                        except Exception:
                            continue
                        dependent_candidates.add(rel)
            except Exception:
                dependent_candidates = None

        scan_complete = True
        scan_truncated_reason: str | None = None
        files_scanned = 0
        scan_deadline = time.monotonic() + _IMPACT_SCAN_TIMEOUT_SECONDS
        inventory_status: dict[str, Any] = {
            "complete": True, "reasons": [], "examples": {},
            "examples_truncated": False, "excluded_link_paths": 0,
        }
        for path, _snapshot_stat in self._iter_files_with_stat(
            str(repo),
            max_depth=25,
            max_files=_IMPACT_SCAN_MAX_FILES + 1,
            inventory_status=inventory_status,
            inventory_deadline=scan_deadline,
        ):
            if files_scanned >= _IMPACT_SCAN_MAX_FILES:
                scan_complete = False
                scan_truncated_reason = "file_limit"
                break
            if time.monotonic() >= scan_deadline:
                scan_complete = False
                scan_truncated_reason = "deadline"
                break
            files_scanned += 1
            rel = str(path.relative_to(repo)).replace("\\", "/")
            low_rel = rel.lower()
            is_test = (
                "/test" in f"/{low_rel}" or "/spec" in f"/{low_rel}"
                or Path(low_rel).name.startswith("test_")
                or any(marker in Path(low_rel).stem for marker in ("_test", ".test", "_spec", ".spec"))
            )
            stem = Path(low_rel).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "")
            if is_test:
                score = sum(3 for changed in changed_stems if changed and (changed in stem or stem in changed))
                score += sum(1 for name in symbol_names[:20] if name.lower() in low_rel)
                if score:
                    test_candidates.append({"path": rel, "score": score})
            if rel in changed_set or not symbol_names:
                continue
            if dependent_candidates is not None and rel not in dependent_candidates:
                continue
            try:
                _digest, snapshot_lines = self._read_snapshot(path)
                text = "\n".join(snapshot_lines)
            except Exception:
                continue
            matched = []
            mentions = 0
            for name in symbol_names:
                count = text.count(name)
                if count:
                    matched.append(name)
                    mentions += min(count, 8)
            if matched:
                dependents.append({"path": rel, "symbols": matched[:8], "mentions": mentions})

        if not inventory_status.get("complete", True):
            scan_complete = False
            inventory_reasons = inventory_status.get("reasons", [])
            if "time_limit" in inventory_reasons:
                scan_truncated_reason = "deadline"
            elif "file_limit" in inventory_reasons:
                scan_truncated_reason = "file_limit"
            else:
                scan_truncated_reason = "inventory"

        dependents.sort(key=lambda x: (-x["mentions"], x["path"]))
        test_candidates.sort(key=lambda x: (-x["score"], x["path"]))
        dependents = dependents[:max(1, int(max_dependents))]
        suggested_tests = test_candidates[:20]

        score = 0
        reasons: list[str] = []
        if len(changed_files) >= 6:
            score += 2; reasons.append("multi-file change")
        if len(changed_files) >= 15:
            score += 2; reasons.append("large change surface")
        risky_terms = {"auth", "security", "migration", "schema", "database", "transaction", "concurrency", "thread", "lock", "payment", "permission", "crypto"}
        if any(any(term in rel.lower() for term in risky_terms) for rel in changed_files):
            score += 2; reasons.append("sensitive subsystem path")
        if len(dependents) >= 10:
            score += 1; reasons.append("many likely dependents")
        if not suggested_tests and any(Path(x).suffix.lower() in self.extensions for x in changed_files):
            score += 1; reasons.append("no likely tests found")
        if diff.get("truncated"):
            score += 1; reasons.append("diff exceeded local impact budget")
        if not scan_complete:
            score += 1; reasons.append("impact scan incomplete")
        level = "high" if score >= 5 else "medium" if score >= 2 else "low"
        if not reasons:
            reasons.append("small localized change")

        return {
            "success": True, "root": str(repo), "changed_files": changed_files,
            "changed_symbols": changed_symbols, "likely_dependents": dependents,
            "suggested_tests": suggested_tests,
            "risk": {"score": score, "level": level, "reasons": reasons},
            "diff_sha256": diff.get("diff_sha256"),
            "analysis_coverage": {
                "complete": scan_complete,
                "files_scanned": files_scanned,
                "limit": _IMPACT_SCAN_MAX_FILES,
                "truncated_reason": scan_truncated_reason,
            },
            "note": "Heuristic fallback; use Serena for exact symbol relationships when available.",
        }

    @staticmethod
    def _path_control_matches(path: str, prefixes: tuple[str, ...]) -> bool:
        normalized = path.replace("\\", "/").strip("/").casefold()
        basename = normalized.rsplit("/", 1)[-1]
        for prefix in prefixes:
            pattern = prefix.replace("\\", "/").strip("/").casefold()
            if not pattern:
                continue
            if any(char in pattern for char in "*?["):
                if fnmatch.fnmatchcase(normalized, pattern) or fnmatch.fnmatchcase(basename, pattern):
                    return True
            elif normalized == pattern or normalized.startswith(pattern + "/"):
                return True
        return False

    def _validated_context_path(
        self, base: Path, value: Any, field: str, *, reject_symlink: bool = True
    ) -> tuple[str, Path]:
        if not isinstance(value, str):
            raise ValueError(f"{field} paths must be strings")
        raw = value.strip().replace("\\", "/")
        windows_path = PureWindowsPath(value.strip())
        project_rooted = raw.startswith("/") and not raw.startswith("//")
        if project_rooted:
            raw = raw[1:]
        if (
            not raw or len(raw) > 240 or not raw.isprintable() or raw.startswith("/")
            or (windows_path.is_absolute() and not project_rooted) or windows_path.drive
            or any(part == ".." for part in raw.split("/"))
        ):
            raise ValueError(f"{field} paths must be repository-relative")
        parts = [part for part in raw.split("/") if part not in {"", "."}]
        if not parts:
            raise ValueError(f"{field} paths must name a repository path")
        relative = "/".join(parts)
        candidate = base.joinpath(*parts)
        if reject_symlink:
            current = base
            for part in parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError(f"{field} paths cannot traverse symlinks")
        try:
            candidate.resolve(strict=False).relative_to(base)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{field} paths must remain inside the repository root") from exc
        return relative, candidate

