from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

class PreprocessRegistryMixin:
    @staticmethod
    def _root(root: str) -> str:
        from . import preprocess as services_module
        return services_module.canonical_root(root)

    def _is_internal_root(self, resolved: str) -> bool:
        from . import preprocess as services_module
        if not bool(self.cfg.get("ignore_internal_install", True)):
            return False
        path = services_module.Path(resolved).resolve()
        # State directory contains runtime databases and cache - always internal
        try:
            state_p = self.state_dir.resolve()
            if path == state_p or path.is_relative_to(state_p):
                return True
        except (ValueError, AttributeError):
            try:
                path.relative_to(self.state_dir); return True
            except ValueError:
                pass
        try:
            install_p = self.install_root.resolve()
            # If the user is actively working on the local-ai-hub repo itself (it has .git or pyproject.toml)
            if (path == install_p or path.is_relative_to(install_p)) and ((install_p / ".git").exists() or (install_p / "pyproject.toml").exists()):
                return False
            if path == install_p or path.is_relative_to(install_p):
                return True
        except (ValueError, AttributeError):
            pass
        return False

    def _is_ephemeral_root(self, resolved: str) -> bool:
        """Reject obvious OS/temp/runtime directories from project registration."""
        from . import preprocess as services_module
        path = services_module.Path(resolved)
        low = str(path).replace("\\", "/").lower().rstrip("/")
        bad_suffixes = ("/windows/system32", "/windows/syswow64", "/windows", "/program files", "/program files (x86)")
        if any(low.endswith(x) for x in bad_suffixes):
            return True
        if self.reject_temp_projects:
            try:
                temp = services_module.Path(services_module.tempfile.gettempdir()).resolve()
            except (OSError, RuntimeError) as exc:
                services_module.logger.warning("temporary project boundary unavailable (%s)", type(exc).__name__)
                return True
            if path == temp or path.is_relative_to(temp):
                return True
        return False

    @staticmethod
    def _has_project_marker(path: Path) -> bool:
        markers = (
            ".git", "pyproject.toml", "package.json", "composer.json", "Cargo.toml", "go.mod",
            "pom.xml", "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile",
            "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
        )
        if any((path / name).exists() for name in markers):
            return True
        try:
            if any(path.glob("*.sln")) or any(path.glob("*.csproj")):
                return True
        except OSError:
            pass
        # Generic source repositories without a manifest are accepted when they
        # contain a small but real source tree; random cwd folders are not.
        source_exts = {".py", ".php", ".js", ".ts", ".tsx", ".jsx", ".cs", ".java", ".go", ".rs", ".cpp", ".c", ".h"}
        seen = 0
        try:
            for child in path.iterdir():
                if child.is_file() and child.suffix.lower() in source_exts:
                    seen += 1
                elif child.is_dir() and not child.name.startswith(".") and child.name.lower() not in {"node_modules", "vendor", "venv", ".venv", "build", "dist"}:
                    try:
                        for f in child.iterdir():
                            if f.is_file() and f.suffix.lower() in source_exts:
                                seen += 1
                                if seen >= 3:
                                    return True
                    except OSError:
                        pass
                if seen >= 3:
                    return True
        except OSError:
            return False
        return False

    def touch_if_registered(self, root: str) -> bool:
        """Refresh project LRU priority without turning reads into SQLite write storms.

        Foreground agents often issue bursts of repository operations. Persisting an
        LRU timestamp for every operation contends with preprocessing WAL writes and
        changes ``updated_at`` even though project content did not change. Touches are
        therefore debounced in memory and only ``last_requested_at`` is persisted.
        """
        from . import preprocess as services_module
        resolved = self._root(root)
        now = services_module.time.time()
        with self._touch_lock:
            last = self._last_touch.get(resolved, 0.0)
            if now - last < self._touch_debounce_seconds:
                return True
            self._last_touch[resolved] = now
        try:
            cur = self._write_retry(
                lambda con: con.execute(
                    "UPDATE projects SET last_requested_at=? WHERE root=?",
                    (now, resolved),
                ),
                actor_timeout=services_module._PROJECT_TOUCH_WRITE_TIMEOUT_SECONDS,
                best_effort=True,
            )
            return bool(getattr(cur, "rowcount", 0))
        except (services_module.sqlite3.Error, TimeoutError) as exc:
            services_module.logger.debug("preprocessor project touch failed error_type=%s", type(exc).__name__)
            return False

    def _project_config_watch_signature(self, root: Path) -> tuple[Any, ...]:
        def file_sig(p: Path) -> tuple[int, int] | None:
            try:
                st = p.stat()
                return (st.st_mtime_ns, st.st_size)
            except (OSError, RuntimeError):
                return None

        return (
            file_sig(root / ".local-ai.toml"),
            file_sig(root / ".local-ai.worktree.toml"),
            file_sig(root / ".git"),
        )

    def _get_cached_project_extensions(self, root: Path) -> set[str]:
        # Watcher roots are canonicalized at registration/event dispatch; avoid
        # another filesystem-resolving realpath call for every file event.
        from . import preprocess as services_module
        root_key = str(root)
        sig = self._project_config_watch_signature(root)
        with getattr(self, "_watch_cache_lock", services_module.threading.Lock()):
            if not hasattr(self, "_watch_extensions_cache"):
                self._watch_extensions_cache = {}
            cached = self._watch_extensions_cache.get(root_key)
            if cached is not None and cached[0] == sig:
                return cached[1]

        project_extensions: set[str] = set()
        _api, project_context = self._project_config_context(root_key)
        if project_context is not None:
            settings = project_context.settings
            project_extensions.update(
                str(value).lower() for value in getattr(settings, "text_extensions", ())
            )
            for override in getattr(settings, "language_overrides", {}).values():
                project_extensions.update(
                    str(value).lower() for value in override.get("text_extensions", ())
                )
            project_extensions.difference_update(
                str(value).lower() for value in getattr(settings, "binary_extensions", ())
            )

        with getattr(self, "_watch_cache_lock", services_module.threading.Lock()):
            self._watch_extensions_cache[root_key] = (sig, project_extensions)
        return project_extensions

    def _watch_relevant(self, root: Path, changed: Path) -> str | None:
        from . import preprocess as services_module
        if not root.is_dir():
            return None
        try:
            rel_path = changed.relative_to(root)
        except ValueError:
            return None
        if any(part.lower() in self.repo_tools.ignore_dirs for part in rel_path.parts[:-1]):
            return None
        name = rel_path.name.lower()
        if name in {".local-ai.toml", ".local-ai.worktree.toml"}:
            root_key = str(root.resolve(strict=False))
            with getattr(self, "_watch_cache_lock", services_module.threading.Lock()):
                if hasattr(self, "_watch_extensions_cache"):
                    self._watch_extensions_cache.pop(root_key, None)
            return str(rel_path).replace("\\", "/")
        suffix = rel_path.suffix.lower()
        if name in self.repo_tools.special_filenames or (
            self.repo_tools.extensions and suffix in self.repo_tools.extensions
        ):
            return str(rel_path).replace("\\", "/")
        project_extensions = self._get_cached_project_extensions(root)
        if (
            self.repo_tools.extensions
            and suffix not in self.repo_tools.extensions
            and suffix not in project_extensions
            and name not in self.repo_tools.special_filenames
        ):
            return None
        return str(rel_path).replace("\\", "/")

    def _dirty_paths_pending(self, root: str) -> bool:
        from . import preprocess as services_module
        lock = getattr(self, "_dirty_lock", None)
        with lock if lock is not None else services_module.nullcontext():
            return bool(getattr(self, "_dirty_paths", {}).get(root))

    def _consume_dirty_paths(self, root: str, limit: int = 1024) -> set[str]:
        limit = max(1, int(limit))
        with self._dirty_lock:
            pending = self._dirty_paths.get(root)
            if not pending:
                return set()
            if len(pending) <= limit:
                return self._dirty_paths.pop(root, set())
            batch = set(sorted(pending)[:limit])
            pending.difference_update(batch)
            return batch

    def _project_config_context(self, root: str) -> tuple[Any | None, Any | None]:
        """Resolve optional project policy lazily for the owning repository."""
        try:
            from importlib import import_module

            api = import_module("local_ai_hub.project_config")
        except ModuleNotFoundError as exc:
            if exc.name == "local_ai_hub.project_config":
                return None, None
            raise
        state_dir = self.config.get("server", {}).get("state_dir", "state")
        return api, api.resolve_project_context(root, state_dir)

    def _project_profile(self, root: str, profile: Any) -> Any:
        _api, context = self._project_config_context(root)
        if context is None or not isinstance(profile, dict):
            return profile
        profile = dict(profile)
        settings = context.settings
        for name in ("project_type", "solution_path"):
            value = getattr(settings, name, None)
            if value:
                profile[name] = value
        return profile

    def _add_project_text_extensions(self, root: str, files: dict[str, dict[str, Any]], api: Any | None, context: Any | None) -> None:
        from . import preprocess as services_module
        if api is None or context is None:
            return
        settings = context.settings
        extensions = {str(value).lower() for value in getattr(settings, "text_extensions", ())}
        for override in getattr(settings, "language_overrides", {}).values():
            extensions.update(str(value).lower() for value in override.get("text_extensions", ()))
        extensions.difference_update(str(value).lower() for value in getattr(settings, "binary_extensions", ()))
        extensions.difference_update(str(value).lower() for value in getattr(self.repo_tools, "extensions", ()))
        if not extensions:
            return
        base = services_module.Path(root)
        path_policy = services_module._resolve_preprocess_path_policy(api, root, settings)
        ignored = {str(value).lower() for value in getattr(self.repo_tools, "ignore_dirs", ())}
        may_descend = getattr(api, "may_descend", None)
        for current, directories, filenames in services_module.os.walk(base, followlinks=False):
            current_path = services_module.Path(current)
            retained = []
            for name in directories:
                child = current_path / name
                if name.lower() in ignored or (callable(may_descend) and not may_descend(
                    base, child, settings, phase="preprocess", hard_denied=False,
                )):
                    continue
                retained.append(name)
            directories[:] = retained
            for name in filenames:
                candidate = current_path / name
                if candidate.suffix.lower() not in extensions:
                    continue
                try:
                    stat = candidate.stat()
                    relative = candidate.relative_to(base).as_posix()
                except (OSError, ValueError):
                    continue
                if int(stat.st_size) > int(getattr(self.repo_tools, "max_file_bytes", stat.st_size)) or not self._project_path_allowed(
                    root, relative, settings, phase="preprocess", size_bytes=int(stat.st_size),
                    path_policy=path_policy,
                ):
                    continue
                files.setdefault(relative, {
                    "path": relative, "size": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns), "extension": candidate.suffix.lower(),
                })

    def fast_update_file(
        self,
        root: str,
        rel_path: str,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Sub-50ms instant fast-path for editor save events.

        Updates RAM ingest cache, file_refs hash/mtime, and deterministic AST facts
        immediately for a single file without resetting project phase to inventory
        nor running the full 13-phase cycle.
        """
        from . import preprocess as services_module
        import hashlib
        t0 = services_module.time.monotonic()
        resolved = self._root(root)
        if not isinstance(rel_path, str) or not rel_path or "\x00" in rel_path:
            return {"success": False, "error": "path must be a relative file inside root"}
        normalized_rel = rel_path.replace("\\", "/")
        raw_parts = normalized_rel.split("/")
        if (
            normalized_rel.startswith("/")
            or services_module.PureWindowsPath(normalized_rel).drive
            or any(part == ".." for part in raw_parts)
        ):
            return {"success": False, "error": "path must be a relative file inside root"}
        clean_rel = "/".join(part for part in raw_parts if part not in ("", "."))
        if not clean_rel:
            return {"success": False, "error": "path must identify a file inside root"}

        root_path = services_module.Path(resolved)
        full_path = root_path.joinpath(*clean_rel.split("/"))
        cursor = root_path
        for part in clean_rel.split("/"):
            cursor = cursor / part
            is_junction = getattr(services_module.os.path, "isjunction", lambda _path: False)(cursor)
            if cursor.is_symlink() or is_junction:
                return {"success": False, "error": "symlink or junction traversal is not allowed"}
        try:
            if not full_path.resolve(strict=False).is_relative_to(root_path):
                return {"success": False, "error": "path must stay inside root"}
        except (OSError, RuntimeError, ValueError):
            return {"success": False, "error": "path must stay inside root"}

        if content is not None:
            text = content
            stat_size = len(text.encode("utf-8"))
            stat_mtime = int(services_module.time.time() * 1e9)
        else:
            try:
                st = full_path.stat()
                stat_size = int(st.st_size)
                stat_mtime = int(st.st_mtime_ns)
                text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception as read_exc:
                return {"success": False, "error": str(read_exc)}

        new_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

        if hasattr(self, "ingest_cache") and self.ingest_cache is not None:
            self.ingest_cache.put(clean_rel, text, new_hash, root=resolved)

        now = services_module.time.time()
        def _update_db(con: sqlite3.Connection) -> None:
            gen_row = con.execute("SELECT generation FROM projects WHERE root=?", (resolved,)).fetchone()
            gen = int(gen_row[0]) if gen_row else 1
            con.execute(
                """INSERT INTO file_refs (root, path, size, mtime_ns, content_hash, needs_hash, generation, updated_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                   ON CONFLICT(root, path) DO UPDATE SET
                     size=excluded.size,
                     mtime_ns=excluded.mtime_ns,
                     content_hash=excluded.content_hash,
                     needs_hash=0,
                     generation=excluded.generation,
                     updated_at=excluded.updated_at""",
                (resolved, clean_rel, stat_size, stat_mtime, new_hash, gen, now),
            )
            con.execute(
                """INSERT OR REPLACE INTO source_index(root, path, content_hash, text, updated_at, text_origin)
                   VALUES(?, ?, ?, ?, ?, 'source')""",
                (resolved, clean_rel, new_hash, text, now),
            )
            try:
                self._delete_fts_rows(con, "root=? AND path=?", (resolved, clean_rel))
                self._insert_fts_rows(con, [(resolved, clean_rel, clean_rel + "\n" + text)])
            except services_module.sqlite3.OperationalError:
                if services_module.fts_layout(con) != services_module.LEGACY_FTS:
                    raise

        self._write_retry(_update_db)

        det_updated = False
        if self.deterministic is not None and hasattr(self.deterministic, "update_file"):
            try:
                det_res = self.deterministic.update_file(resolved, clean_rel, new_hash)
                det_updated = bool(det_res.get("success", False))
            except Exception as det_exc:
                services_module.logger.debug("Fast-path deterministic update failed: %s", det_exc)

        code_idx_updated = False
        if self.code_index is not None and hasattr(self.code_index, "update_file"):
            try:
                ci_res = self.code_index.update_file(resolved, clean_rel)
                code_idx_updated = bool(ci_res.get("success", False))
            except Exception:
                pass

        elapsed_ms = round((services_module.time.monotonic() - t0) * 1000, 2)
        return {
            "success": True,
            "root": resolved,
            "path": clean_rel,
            "content_hash": new_hash,
            "deterministic_updated": det_updated,
            "code_index_updated": code_idx_updated,
            "elapsed_ms": elapsed_ms,
        }

    def notify_path_changed(
        self, changed_path: str, *, fast_path: bool = False, root_hint: str | None = None,
    ) -> bool:
        """Coalesce watcher events and queue only the owning registered project."""
        from . import preprocess as services_module
        if not self._background_work_allowed():
            return False
        try:
            changed = services_module.Path(changed_path).resolve(strict=False)
        except Exception:
            return False
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                if root_hint is None:
                    rows = con.execute("SELECT root FROM projects WHERE paused=0").fetchall()
                else:
                    rows = con.execute(
                        "SELECT root FROM projects WHERE root=? AND paused=0", (root_hint,)
                    ).fetchall()
        except Exception:
            return False

        matched_roots: list[str] = []
        matched_pairs: list[tuple[str, str]] = []
        matched_any = False
        for row in rows:
            try:
                root_path = services_module.Path(str(row[0])).resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                # One unavailable registered root must not terminate the watchdog
                # dispatch thread or prevent events from reaching other projects.
                continue
            rel = self._watch_relevant(root_path, changed)
            if rel is None:
                continue
            root = str(root_path)
            matched_any = True
            matched_pairs.append((root, rel))
            with self._dirty_lock:
                paths = self._dirty_paths.setdefault(root, set())
                first = not paths
                paths.add(rel)
            if hasattr(self, "ingest_cache") and self.ingest_cache is not None:
                self.ingest_cache.invalidate(rel, root=root)
                self._watch_revisions[root] = self._watch_revisions.get(root, 0) + 1
            with self._hash_git_maps_lock:
                # A watcher event changes one file's Git blob identity. Keep the
                # rest of this generation's map warm; the next hash pass will
                # refresh only the changed path from the working tree.
                for key, git_hashes in self._hash_git_maps.items():
                    if key[0] == root:
                        git_hashes.pop(rel, None)
            if first:
                matched_roots.append(root)

        if fast_path:
            for r, rel in matched_pairs:
                try:
                    self.fast_update_file(r, rel)
                except Exception as fast_exc:
                    services_module.logger.debug("Fast path update error for %s: %s", rel, fast_exc)
            return bool(matched_pairs)

        for root in matched_roots:
            try:
                def _queue_changed(con: sqlite3.Connection, r: str = root) -> None:
                    con.execute(
                        "UPDATE projects SET status='queued',phase=CASE WHEN phase='complete' THEN 'inventory' ELSE phase END,next_check_at=0 WHERE root=?", (r,)
                    )
                    self._rebalance_processing_slots(con, preferred_root=r)
                self._write_retry(_queue_changed)
            except Exception:
                # The in-memory dirty set is retained. A periodic recheck remains the
                # correctness fallback if another process owns the WAL writer briefly.
                pass
        if matched_any:
            self._cpu_wakeup.set()
        return matched_any

    def cache_fingerprint(self, root: str) -> dict[str, Any] | None:
        """Return a zero-process watcher revision for any initialized project.

        The watcher revision changes immediately on relevant filesystem events, so
        foreground caches invalidate without waiting for preprocessing to finish and
        without spawning Git while a project is being incrementally refreshed.
        """
        from . import preprocess as services_module
        if not self._watcher_active:
            return None
        resolved = self._root(root)
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                row = con.execute("SELECT status,phase,generation,inventory_hash,structural_hash FROM projects WHERE root=? AND paused=0", (resolved,)).fetchone()
            if not row or not row["inventory_hash"]:
                return None
            with self._dirty_lock:
                watch_revision = int(self._watch_revisions.get(resolved, 0))
                dirty_paths = sorted(self._dirty_paths.get(resolved, set()))[:256]
                dirty_count = len(self._dirty_paths.get(resolved, set()))
            _api, project_context = self._project_config_context(resolved)
            config_digest = str(getattr(project_context, "config_digest", ""))
            fp = services_module.stable_hash({
                "root": resolved, "generation": int(row["generation"] or 0),
                "inventory": row["inventory_hash"], "structure": row["structural_hash"],
                "watch_revision": watch_revision, "project_config": config_digest,
            })
            return {
                "success": True, "root": resolved, "kind": "preprocessed-watcher",
                "fingerprint": fp, "dirty": dirty_count > 0, "changed_files": dirty_count,
                "changed_paths": dirty_paths, "status": str(row["status"]),
                "phase": str(row["phase"]), "project_config_digest": config_digest,
                "created_at": services_module.time.time(),
            }
        except (ImportError, OSError, OverflowError, services_module.sqlite3.Error, TypeError, ValueError) as exc:
            services_module.logger.debug("watcher cache fingerprint unavailable error_type=%s", type(exc).__name__)
            return None

    def indexed_paths(self, root: str) -> list[str]:
        """Return watcher-owned file paths without walking the working tree."""
        from . import preprocess as services_module
        resolved = self._root(root)
        with self._db_lock, services_module.closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path FROM file_refs WHERE root=? ORDER BY path",
                (resolved,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def context_revision(self, root: str) -> str:
        """Cheap revision for local-model answer caching and preprocessed context."""
        from . import preprocess as services_module
        resolved = self._root(root)
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                p = con.execute("SELECT generation,inventory_hash,structural_hash,status FROM projects WHERE root=?", (resolved,)).fetchone()
                project = con.execute("SELECT revision_hash FROM project_cards WHERE root=?", (resolved,)).fetchone()
                modules = [tuple(row) for row in con.execute(
                    "SELECT module,revision_hash,updated_at FROM module_cards WHERE root=? ORDER BY module",
                    (resolved,),
                )]
                cap = con.execute("SELECT MAX(updated_at) FROM task_capsules WHERE root=?", (resolved,)).fetchone()
            return services_module.stable_hash({
                "project": tuple(p) if p else None,
                "project_card": project[0] if project else None,
                "modules": modules,
                "capsules": cap[0] if cap else None,
            })
        except Exception:
            return "cold"

    def _related_worktrees(self, root: str) -> list[str]:
        from . import preprocess as services_module
        if not self.discover_worktrees:
            return []
        now = services_module.time.monotonic()
        with self._worktree_lock:
            cached = self._worktree_cache.get(root)
            if cached and now - cached[0] < self.worktree_discovery_ttl:
                return list(cached[1])
        try:
            roots = services_module.discover_worktree_roots(root)
        except Exception:
            roots = []
        related = [item for item in roots if item != root][:self.max_discovered_worktrees]
        with self._worktree_lock:
            if len(self._worktree_cache) > 256:
                oldest_roots = sorted(self._worktree_cache.keys(), key=lambda k: self._worktree_cache[k][0])[:128]
                for k in oldest_roots:
                    self._worktree_cache.pop(k, None)
            self._worktree_cache[root] = (now, related)
        return related

    def _register_discovered_worktrees(self, root: str) -> None:
        # A linked Git worktree can discover the same sibling set as its parent.
        # Never recurse from it; otherwise one explicit registration fans out into
        # every worktree and bloats all derived indexes.
        from . import preprocess as services_module
        git_marker = services_module.Path(root) / ".git"
        if git_marker.is_file():
            return
        siblings = self._related_worktrees(root)
        if not siblings:
            return
        now = services_module.time.time()

        def register_siblings(con: sqlite3.Connection) -> None:
            for sibling in siblings:
                if self._is_internal_root(sibling) or self._is_ephemeral_root(sibling):
                    continue
                workspace = self.rag.workspace_id(sibling)
                row = con.execute("SELECT root FROM projects WHERE root=?", (sibling,)).fetchone()
                if row is None:
                    con.execute(
                        """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sibling, workspace, "waiting", "inventory", 0, 0, now, now, 0, 0, 0, "worktree-discovery"),
                    )
                else:
                    con.execute(
                        "UPDATE projects SET workspace=?,paused=0,status='waiting',registration_source='worktree-discovery' WHERE root=?",
                        (workspace, sibling),
                    )

        try:
            self._write_retry(register_siblings)
        except Exception:
            # Discovery is an acceleration feature. A Git/SQLite failure must not
            # turn foreground project registration into a failure.
            pass

    def _seed_from_parent(self, root: str, parent_root: str) -> dict[str, int]:
        """Inherit precomputed caches from parent repository into a worktree."""
        from . import preprocess as services_module
        stats = {"file_refs": 0, "code_index": 0, "deterministic": 0}
        resolved = self._root(root)
        parent_resolved = self._root(parent_root)
        if not services_module.Path(resolved).is_dir() or not services_module.Path(parent_resolved).is_dir():
            return stats
        if resolved == parent_resolved:
            return stats

        now = services_module.time.time()
        base = services_module.Path(resolved)

        # 1. Seed file_refs & source_index from preprocess.sqlite3
        try:
            with services_module.closing(self._connect()) as con:
                p_rows = con.execute(
                    "SELECT path, size, content_hash FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>''",
                    (parent_resolved,),
                ).fetchall()
            try:
                clean_git_hashes = self.repo_tools.git_blob_map(resolved)
            except Exception:
                clean_git_hashes = {}

            candidates: list[tuple[str, str, int, int, tuple[int, ...]]] = []
            stale_candidates: list[tuple[str, str]] = []
            for row in p_rows:
                rel = str(row["path"]).replace("\\", "/")
                parent_hash = str(row["content_hash"] or "")
                child_file = (base / rel).resolve(strict=False)
                if not child_file.is_file():
                    continue
                try:
                    before = child_file.stat()
                    child_size = int(before.st_size)
                    if child_size != int(row["size"]):
                        stale_candidates.append((rel, parent_hash))
                        continue
                    if parent_hash.startswith("git:"):
                        child_hash = str(clean_git_hashes.get(rel) or "")
                    else:
                        child_hash = str(self.repo_tools._hash_file_only(child_file) or "")
                    after = child_file.stat()
                    identity_before = (
                        int(before.st_size), int(before.st_mtime_ns),
                        int(getattr(before, "st_ctime_ns", 0)), int(getattr(before, "st_ino", 0)),
                        int(getattr(before, "st_dev", 0)),
                    )
                    identity_after = (
                        int(after.st_size), int(after.st_mtime_ns),
                        int(getattr(after, "st_ctime_ns", 0)), int(getattr(after, "st_ino", 0)),
                        int(getattr(after, "st_dev", 0)),
                    )
                    if not child_hash or child_hash != parent_hash or identity_before != identity_after:
                        stale_candidates.append((rel, parent_hash))
                        continue
                    candidates.append((rel, parent_hash, child_size, int(after.st_mtime_ns), identity_after))
                except OSError:
                    stale_candidates.append((rel, parent_hash))

            verified_candidates = []
            for rel, parent_hash, size, mtime_ns, identity in candidates:
                child_file = (base / rel).resolve(strict=False)
                try:
                    st = child_file.stat()
                except OSError:
                    continue
                current_identity = (
                    int(st.st_size), int(st.st_mtime_ns),
                    int(getattr(st, "st_ctime_ns", 0)), int(getattr(st, "st_ino", 0)),
                    int(getattr(st, "st_dev", 0)),
                )
                if current_identity == identity:
                    verified_candidates.append((rel, parent_hash, size, mtime_ns))

            if verified_candidates or stale_candidates:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    with services_module.write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocessor derived refs"):
                        for rel, parent_hash in stale_candidates:
                            con.execute(
                                """UPDATE file_refs
                                   SET content_hash='',needs_hash=1,rag_hash=NULL,card_key=NULL,updated_at=?
                                   WHERE root=? AND path=? AND content_hash=? AND needs_hash=0
                                     AND EXISTS (
                                         SELECT 1 FROM file_refs p
                                         WHERE p.root=? AND p.path=? AND p.content_hash=? AND p.needs_hash=0
                                     )""",
                                (now, resolved, rel, parent_hash, parent_resolved, rel, parent_hash),
                            )
                            con.execute(
                                """DELETE FROM source_index
                                   WHERE root=? AND path=? AND content_hash=?
                                     AND EXISTS (
                                         SELECT 1 FROM file_refs p
                                         WHERE p.root=? AND p.path=? AND p.content_hash=? AND p.needs_hash=0
                                     )""",
                                (resolved, rel, parent_hash, parent_resolved, rel, parent_hash),
                            )
                        for rel, parent_hash, size, mtime_ns in verified_candidates:
                            parent = con.execute(
                                """SELECT card_key FROM file_refs
                                   WHERE root=? AND path=? AND content_hash=? AND size=? AND needs_hash=0""",
                                (parent_resolved, rel, parent_hash, size),
                            ).fetchone()
                            if parent is None:
                                continue
                            inserted = con.execute(
                                """INSERT OR IGNORE INTO file_refs(
                                    root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,
                                    last_accessed_at,generation,card_key,updated_at
                                ) VALUES(?,?,?,?,?,0,NULL,?,1,?,?)""",
                                (resolved, rel, parent_hash, size, mtime_ns, now, parent["card_key"], now),
                            )
                            if inserted.rowcount > 0:
                                stats["file_refs"] += 1
                            child = con.execute(
                                "SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?",
                                (resolved, rel),
                            ).fetchone()
                            if child is not None and str(child["content_hash"] or "") == parent_hash and int(child["needs_hash"] or 0) == 0:
                                con.execute(
                                    """INSERT OR IGNORE INTO source_index(root,path,content_hash,text,updated_at,text_origin)
                                       SELECT ?,path,content_hash,text,?,text_origin FROM source_index
                                       WHERE root=? AND path=? AND content_hash=? AND text_origin='source'""",
                                    (resolved, now, parent_resolved, rel, parent_hash),
                                )
        except (OSError, services_module.sqlite3.Error) as exc:
            services_module.logger.warning("worktree file cache seed skipped (%s)", type(exc).__name__)

        # 2. Seed deterministic.sqlite3 (test_source_links)
        if self.deterministic is not None:
            try:
                with services_module.closing(self.deterministic._connect()) as det_con:
                    det_con.execute(
                        """INSERT OR IGNORE INTO test_source_links(root, source_path, test_path, confidence, updated_at)
                           SELECT ?, source_path, test_path, confidence, ? FROM test_source_links WHERE root=?""",
                        (resolved, now, parent_resolved),
                    )
                    det_con.commit()
                    stats["deterministic"] = 1
            except (OSError, services_module.sqlite3.Error) as exc:
                services_module.logger.warning("worktree deterministic cache seed skipped (%s)", type(exc).__name__)

        # Code-index admission is demand-driven by actual source evidence in
        # _step_code_index. Cloning the parent's full per-root index here makes
        # every worktree multiply unrelated rows and overstates its coverage.
        # Shared content-addressed parse blobs remain available to later indexing.

        return stats

    def register(self, root: str, *, force: bool = False, source: str = "agent", is_worktree: bool = False, parent_root: str | None = None) -> dict[str, Any]:
        from . import preprocess as services_module
        if not self.enabled:
            return {"success": False, "enabled": False, "error": "preprocessing disabled", "terminal": True, "retryable": False}
        resolved = self._root(root)
        if not services_module.Path(resolved).is_dir():
            return {"success": False, "error": f"root directory does not exist: {resolved}", "terminal": True, "retryable": False}
        if self._is_internal_root(resolved):
            return {"success": True, "ignored": True, "reason": "internal Local AI install/state directory", "project": services_module.Path(resolved).name}
        if self._is_ephemeral_root(resolved):
            return {"success": True, "ignored": True, "reason": "ephemeral/system directory is not a stable project", "project": services_module.Path(resolved).name}
        if self.require_project_markers and not self._has_project_marker(services_module.Path(resolved)):
            return {"success": True, "ignored": True, "reason": "directory has no stable project marker/source tree", "project": services_module.Path(resolved).name}
        workspace = self.rag.workspace_id(resolved)
        now = services_module.time.time()
        if force:
            self._code_index_pruned_generations = {
                key for key in getattr(self, "_code_index_pruned_generations", set()) if key[0] != resolved
            }
            self._deterministic_pruned_generations = {
                key for key in getattr(self, "_deterministic_pruned_generations", set()) if key[0] != resolved
            }
        def _register_tx(con: sqlite3.Connection) -> None:
            row = con.execute("SELECT root,generation FROM projects WHERE root=?", (resolved,)).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (resolved, workspace, "queued", "inventory", 0, int(force), now, now, now, 0, now, str(source or "agent")[:32]),
                )
            elif force:
                con.execute(
                    "UPDATE projects SET status='queued', phase='inventory', paused=0, force_refresh=1, updated_at=?, last_requested_at=?, next_check_at=?, registration_source=? WHERE root=?",
                    (now, now, now, str(source or "agent")[:32], resolved),
                )
                # A forced rebuild must not expose old backend failures while the
                # refreshed Serena runs are still queued.
                con.execute("DELETE FROM external_index_state WHERE root=?", (resolved,))
            else:
                con.execute(
                    "UPDATE projects SET paused=0, status=CASE WHEN status IN ('paused','error','waiting') THEN 'queued' ELSE status END, last_requested_at=?, next_check_at=CASE WHEN status IN ('paused','error') THEN 0 ELSE next_check_at END, registration_source=? WHERE root=?",
                    (now, str(source or "agent")[:32], resolved),
                )
            self._rebalance_processing_slots(con, preferred_root=resolved)
        self._write_retry(_register_tx, actor_priority=0)
        if is_worktree or parent_root:
            p_root = parent_root or (self._related_worktrees(resolved)[0] if self._related_worktrees(resolved) else None)
            if p_root and p_root != resolved:
                self._seed_from_parent(resolved, p_root)
        self._register_discovered_worktrees(resolved)
        self._wake_all()
        return self.status(resolved)

    def refresh(self, root: str) -> dict[str, Any]:
        return self.register(root, force=True, source="agent")

    def pause(self, root: str | None = None) -> dict[str, Any]:
        from . import preprocess as services_module
        if root is None:
            self._paused.set()
            try: self.pause_marker.write_text(f"paused {services_module.time.time()}\n", encoding="utf-8")
            except OSError: pass
            def _pause_all(con: sqlite3.Connection) -> None:
                con.execute("UPDATE projects SET paused=1, status=CASE WHEN status='running' THEN 'paused' ELSE status END, updated_at=?", (services_module.time.time(),))
            self._write_retry(_pause_all, actor_priority=0)
            self._wake_all()
            return self.status()
        resolved = self._root(root)
        self._write_retry(
            lambda con: con.execute("UPDATE projects SET paused=1,status='paused',updated_at=? WHERE root=?", (services_module.time.time(), resolved)),
            actor_priority=0,
        )
        self._wake_all(); return self.status(resolved)

    def resume(self, root: str | None = None) -> dict[str, Any]:
        from . import preprocess as services_module
        if root is None:
            self._paused.clear()
            try: self.pause_marker.unlink(missing_ok=True)
            except OSError: pass
            def _resume_all(con: sqlite3.Connection) -> None:
                con.execute("UPDATE projects SET paused=0, status=CASE WHEN status='paused' THEN 'queued' ELSE status END, retry_after=0, next_check_at=?, updated_at=?", (services_module.time.time(), services_module.time.time()))
                self._rebalance_processing_slots(con)
            self._write_retry(_resume_all, actor_priority=0)
            self._wake_all()
            return self.status()
        resolved = self._root(root)
        def _resume_tx(con: sqlite3.Connection) -> None:
            con.execute("UPDATE projects SET paused=0,status='queued',retry_after=0,next_check_at=?,last_requested_at=? WHERE root=?", (services_module.time.time(),services_module.time.time(),resolved))
            self._rebalance_processing_slots(con, preferred_root=resolved)
        self._write_retry(_resume_tx, actor_priority=0)
        self._wake_all(); return self.status(resolved)

    def start_exclusive(self) -> dict[str, Any]:
        """Resume all registered projects and recheck completed inventories.

        This keeps content-addressed caches and leaves in-flight phases untouched.
        """
        from . import preprocess as services_module
        if not self.enabled:
            return {"success": False, "error": "preprocessing is disabled"}
        resumed = self.resume()
        if not isinstance(resumed, dict) or resumed.get("success") is not True:
            return resumed
        def requeue_completed(con: sqlite3.Connection) -> None:
            con.execute("UPDATE projects SET status='waiting',phase='inventory',next_check_at=0,updated_at=? "
                        "WHERE status='complete' AND phase='complete'", (services_module.time.time(),))
            self._rebalance_processing_slots(con)
        self._write_retry(requeue_completed)
        self._wake_all()
        return self.status()

    def cancel(self, root: str) -> dict[str, Any]:
        # Cancel means stop scheduling this project but keep all reusable derived cache.
        return self.pause(root)

    def _live_workspace_paths(self, workspace: str, excluding_root: str) -> set[str]:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            aliases = con.execute(
                "SELECT projects.root,file_refs.path FROM file_refs "
                "JOIN projects ON projects.root=file_refs.root "
                "WHERE projects.workspace=? AND projects.root<>?",
                (workspace, excluding_root),
            ).fetchall()
        return {
            str(alias["path"]).replace("\\", "/")
            for alias in aliases
            if services_module.Path(str(alias["root"])).is_dir()
        }

    def _purge_project_secondary_indexes(self, root: str, workspace: str | None) -> bool:
        """Purge only project-owned rows; callers retain registry ownership on failure."""
        from . import preprocess as services_module
        cascade_ok = True
        if self.code_index is not None:
            try:
                result = self.code_index.prune(root, [])
                if not isinstance(result, dict) or not result.get("success"):
                    cascade_ok = False
                    services_module.logger.warning(
                        "deleted-project code-index purge incomplete (%s)",
                        result.get("error", "unknown") if isinstance(result, dict) else "invalid result",
                    )
            except Exception as exc:
                cascade_ok = False
                services_module.logger.warning("deleted-project code-index purge incomplete (%s)", type(exc).__name__)
        if self.deterministic is not None:
            try:
                with services_module.closing(self.deterministic._connect()) as det_con:
                    det_con.execute("DELETE FROM files WHERE root=?", (root,))
                    det_con.execute("DELETE FROM facts WHERE root=?", (root,))
                    det_con.commit()
            except Exception as exc:
                cascade_ok = False
                services_module.logger.warning(
                    "deleted-project deterministic purge incomplete (%s: %s)",
                    type(exc).__name__, exc,
                )
        if self.rag is not None:
            try:
                rag_workspace = workspace
                if rag_workspace is None:
                    rag_workspace = str(self.rag.workspace_id(root))
                live_paths = self._live_workspace_paths(rag_workspace, root)
                self.rag.remove_project(
                    root, workspace=rag_workspace, preserve_paths=live_paths
                )
            except Exception as exc:
                cascade_ok = False
                services_module.logger.warning("deleted-project RAG purge incomplete (%s)", type(exc).__name__)
        return cascade_ok

    def _mark_project_cleanup_pending(self, root: str) -> None:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute(
                "UPDATE projects SET status='error',paused=1,retry_after=0,"
                "next_check_at=0,updated_at=? WHERE root=?",
                (services_module.time.time(), root),
            )
            con.commit()

    def unregister(self, root: str, purge_data: bool = False) -> dict[str, Any]:
        """Remove scheduler registration; optionally purge workspace derived data."""
        from . import preprocess as services_module
        resolved = self._root(root)
        if purge_data:
            with self._db_lock, services_module.closing(self._connect()) as con:
                row = con.execute(
                    "SELECT workspace FROM projects WHERE root=?", (resolved,)
                ).fetchone()
            workspace = str(row["workspace"]) if row is not None else None
            if not self._purge_project_secondary_indexes(resolved, workspace):
                self._mark_project_cleanup_pending(resolved)
                self._wake_all()
                return {
                    "success": False,
                    "removed": 0,
                    "project": services_module.Path(resolved).name,
                    "purged": False,
                }
            try:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    cur = con.execute("DELETE FROM projects WHERE root=?", (resolved,))
                    con.execute("DELETE FROM file_refs WHERE root=?", (resolved,))
                    con.execute("DELETE FROM source_index WHERE root=?", (resolved,))
                    self._delete_fts_rows(con, "root=?", (resolved,))
                    con.execute("DELETE FROM module_cards WHERE root=?", (resolved,))
                    con.execute("DELETE FROM project_cards WHERE root=?", (resolved,))
                    con.execute("DELETE FROM hot_query_state WHERE root=?", (resolved,))
                    con.commit()
            except Exception as exc:
                self._mark_project_cleanup_pending(resolved)
                services_module.logger.warning("worktree registry purge incomplete (%s)", type(exc).__name__)
                self._wake_all()
                return {
                    "success": False,
                    "removed": 0,
                    "project": services_module.Path(resolved).name,
                    "purged": False,
                }
            self._forget_project_runtime(resolved)
            self._wake_all()
            return {
                "success": True,
                "removed": int(cur.rowcount or 0),
                "project": services_module.Path(resolved).name,
                "purged": True,
            }

        with self._db_lock, services_module.closing(self._connect()) as con:
            cur = con.execute("DELETE FROM projects WHERE root=?", (resolved,))
            con.commit()
        self._forget_project_runtime(resolved)
        self._wake_all()
        return {"success": True, "removed": int(cur.rowcount or 0), "project": services_module.Path(resolved).name, "purged": False}

    def cleanup_deleted_projects(self) -> dict[str, Any]:
        """Scan all registered projects and remove projects whose root directory no longer exists on disk."""
        from . import preprocess as services_module
        pruned: list[str] = []
        with self._db_lock, services_module.closing(self._connect()) as con:
            rows = con.execute("SELECT root,workspace FROM projects").fetchall()
        failed: list[str] = []
        for row in rows:
            root = str(row["root"])
            workspace = str(row["workspace"])
            if services_module.Path(root).exists():
                continue

            cascade_ok = self._purge_project_secondary_indexes(root, workspace)
            if not cascade_ok:
                self._mark_project_cleanup_pending(root)
                failed.append(root)
                continue

            try:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    con.execute("DELETE FROM projects WHERE root=?", (root,))
                    con.execute("DELETE FROM file_refs WHERE root=?", (root,))
                    con.execute("DELETE FROM source_index WHERE root=?", (root,))
                    self._delete_fts_rows(con, "root=?", (root,))
                    con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                    con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                    con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                    con.commit()
                self._forget_project_runtime(root)
                pruned.append(root)
            except Exception as exc:
                self._mark_project_cleanup_pending(root)
                failed.append(root)
                services_module.logger.warning("deleted-project registry purge incomplete (%s)", type(exc).__name__)

        # Clean up any orphaned secondary rows whose project is no longer in the registry
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                con.execute("DELETE FROM file_refs WHERE root NOT IN (SELECT root FROM projects)")
                con.execute("DELETE FROM source_index WHERE root NOT IN (SELECT root FROM projects)")
                self._delete_fts_rows(con, "root NOT IN (SELECT root FROM projects)", ())
                con.execute("DELETE FROM module_cards WHERE root NOT IN (SELECT root FROM projects)")
                con.execute("DELETE FROM project_cards WHERE root NOT IN (SELECT root FROM projects)")
                con.execute("DELETE FROM hot_query_state WHERE root NOT IN (SELECT root FROM projects)")
                con.execute("DELETE FROM task_capsules WHERE root NOT IN (SELECT root FROM projects)")
                con.commit()
        except Exception as exc:
            services_module.logger.warning("orphaned secondary index purge incomplete (%s)", type(exc).__name__)

        self._vacuum_derived_databases()


        self._wake_all()
        return {
            "success": not failed,
            "pruned_count": len(pruned),
            "pruned_projects": pruned,
            "failed_count": len(failed),
            "failed_projects": failed,
            "message": (
                f"Successfully cleaned up {len(pruned)} missing worktree(s)/project(s)"
                if pruned
                else f"Cleanup incomplete for {len(failed)} missing project(s)"
                if failed
                else "No missing projects found (all active directories exist on disk)"
            ),
        }

    def _vacuum_derived_databases(self) -> None:
        """Reclaim a bounded batch of free pages from owned derived indexes."""
        from . import preprocess as services_module
        vacuum_paths = [self.db_path]
        for owner in (self.code_index, self.deterministic, self.rag):
            path = getattr(owner, "db_path", None) if owner is not None else None
            if path is not None:
                vacuum_paths.append(services_module.Path(path))
        for path in dict.fromkeys(vacuum_paths):
            setup = services_module.ensure_incremental_vacuum(path)
            result = services_module.incremental_vacuum(path) if setup.get("success") else setup
            if not result.get("success"):
                services_module.logger.warning(
                    "deleted-project database vacuum incomplete path=%s error_type=%s error=%s",
                    path,
                    result.get("error", "unknown"),
                    result.get("error_message", result.get("error", "unknown")),
                )

    def cleanup_orphaned_indexes(self, max_roots: int | None = None) -> dict[str, Any]:
        """Bounded idle cleanup for derived index roots no longer registered."""
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            active = {str(row[0]) for row in con.execute("SELECT root FROM projects").fetchall()}
        limit = max(1, int(max_roots or self.cfg.get("orphan_cleanup_roots_per_run", 4)))
        removed: dict[str, int] = {}
        stores = (
            (self.code_index, frozenset({"files", "symbols", "refs", "edges"})),
            (self.deterministic, frozenset({"files", "facts", "fact_fts", "dependencies", "scripts", "project_state", "query_cache"})),
        )
        for component, allowed_tables in stores:
            if component is None or not hasattr(component, "_connect"):
                continue
            try:
                lock = getattr(component, "_lock", services_module.nullcontext())
                with lock, services_module.closing(component._connect()) as con:
                    roots = [str(row[0]) for row in con.execute("SELECT DISTINCT root FROM files").fetchall()]
                    orphans = [root for root in roots if root not in active and not services_module.Path(root).exists()][:limit]
                    existing = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    for root in orphans:
                        for table in allowed_tables:
                            if table in existing:
                                # table is validated against frozenset — safe for f-string interpolation
                                con.execute(f"DELETE FROM {table} WHERE root=?", (root,))  # noqa: S608
                        removed[root] = removed.get(root, 0) + 1
                    if orphans:
                        con.commit()
            except (services_module.sqlite3.DatabaseError, OSError):
                continue
        return {"success": True, "removed_roots": sorted(removed), "removed_count": len(removed)}
