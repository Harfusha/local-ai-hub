from __future__ import annotations

from typing import Any


class PreprocessInventoryMixin:
    def _step_incremental_inventory(self, row: dict[str, Any], dirty_paths: set[str]) -> bool:
        """Apply watcher-confirmed path changes without rescanning the repository."""
        from . import preprocess as services_module
        root = str(row["root"])
        base = services_module.Path(root)
        settings = self._project_settings(root)
        now = services_module.time.time()
        paths = sorted(set(str(x).replace("\\", "/") for x in dirty_paths if x))
        if not paths:
            return False
        path_policy = services_module.ProjectPathPolicy(root, settings)
        if any(services_module.Path(rel).name in {".local-ai.toml", ".local-ai.worktree.toml"} for rel in paths):
            # Policy changes can affect paths outside the dirty batch. Recompute full inventory.
            return False
        placeholders = ",".join("?" for _ in paths)
        with self._db_lock, services_module.closing(self._connect()) as con:
            old_rows = con.execute(
                f"SELECT path,content_hash,size,mtime_ns,card_key,rag_hash FROM file_refs WHERE root=? AND path IN ({placeholders})",
                (root, *paths),
            ).fetchall()
        old = {str(r["path"]): r for r in old_rows}

        manifest_names = {
            "package.json", "deno.json", "deno.jsonc", "pyproject.toml", "composer.json", "composer.lock", "package-lock.json", "pnpm-lock.yaml",
            "yarn.lock", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "go.work", "pom.xml", "build.gradle", "build.gradle.kts",
            "requirements.txt", "Pipfile", "poetry.lock", "uv.lock", "Gemfile", "Gemfile.lock", "packages.lock.json", "global.json",
            "Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props", "libs.versions.toml",
        }
        present: dict[str, tuple[int, int]] = {}
        deleted: set[str] = set()
        topology_changed = False
        for rel in paths:
            target = (base / rel).resolve(strict=False)
            try:
                target.relative_to(base)
            except ValueError:
                continue
            if target.is_file():
                try:
                    stat = target.stat()
                except OSError:
                    continue
                size, mtime_ns = int(stat.st_size), int(stat.st_mtime_ns)
                if size > int(getattr(self.repo_tools, "max_file_bytes", size)) or not self._project_path_allowed(
                    root, rel, settings, phase="preprocess", size_bytes=size,
                    path_policy=path_policy,
                ):
                    if rel in old:
                        deleted.add(rel)
                        topology_changed = True
                    continue
                present[rel] = (size, mtime_ns)
                topology_changed = topology_changed or rel not in old
            elif rel in old:
                deleted.add(rel)
                topology_changed = True

        if not present and not deleted:
            # Editors can emit transient create/delete events before the file is visible.
            # Keep the full periodic inventory as the fallback instead of spinning.
            return False

        # A watcher event is only a candidate change. Mutagen and some editors can
        # rewrite timestamps/metadata while preserving bytes, so verify content for
        # the coalesced batch before invalidating indexes or bumping generation.
        # Hash only those paths; building a full Git snapshot defeats incremental work.
        def _content_identity(rel: str) -> tuple[str, bool]:
            try:
                path = services_module.Path(root) / rel
                invalidate = getattr(self.repo_tools, "invalidate_snapshot", None)
                if callable(invalidate):
                    invalidate(path)
                digest = str(self.repo_tools._hash_file_only(path) or "")
            except Exception:
                digest = ""
            return digest, bool(digest)

        content_hashes: dict[str, str] = {}
        hash_ok: set[str] = set()
        for rel in sorted(present):
            digest, ok = _content_identity(rel)
            if ok:
                content_hashes[rel] = digest
                hash_ok.add(rel)

        content_changed = set(deleted)
        for rel in present:
            existing = old.get(rel)
            old_hash = str(existing["content_hash"] or "") if existing else ""
            if existing is None or rel not in hash_ok or content_hashes[rel] != old_hash:
                content_changed.add(rel)

        manifest_changed = any(services_module.Path(path).name in manifest_names for path in content_changed)
        changed_count = len(content_changed)
        major = topology_changed or manifest_changed or changed_count >= int(self.cfg.get("major_change_files", 60))
        if changed_count and not topology_changed:
            changed_ratio = changed_count / max(1, len(old))
            ratio_min_files = max(2, int(self.cfg.get("major_change_ratio_min_files", 12)))
            major = major or (changed_count >= ratio_min_files and changed_ratio >= float(self.cfg.get("major_change_ratio", 0.15)))
        generation = int(row.get("generation", 0)) + (1 if major else 0)

        def _apply(con: services_module.sqlite3.Connection) -> None:
            for rel in deleted:
                con.execute("DELETE FROM file_refs WHERE root=? AND path=?", (root, rel))
                con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, rel))
                self._delete_fts_rows(con, "root=? AND path=?", (root, rel))
            for rel in content_changed.difference(deleted):
                con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, rel))
                self._delete_fts_rows(con, "root=? AND path=?", (root, rel))
            for rel, (size, mtime_ns) in present.items():
                existing = old.get(rel)
                old_hash = str(existing["content_hash"] or "") if existing else ""
                old_rag_hash = str(existing["rag_hash"] or "") if existing else ""
                old_card = existing["card_key"] if existing else None
                digest = content_hashes.get(rel)
                content_same = bool(existing is not None and digest and digest == old_hash)
                stored_hash = digest or old_hash
                needs_hash = int(not digest)
                stored_card = old_card if content_same else None
                stored_rag_hash = old_rag_hash if content_same else None
                con.execute(
                    """INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root,path) DO UPDATE SET
                       content_hash=excluded.content_hash,size=excluded.size,mtime_ns=excluded.mtime_ns,
                       needs_hash=excluded.needs_hash,rag_hash=excluded.rag_hash,generation=excluded.generation,
                       card_key=excluded.card_key,updated_at=excluded.updated_at""",
                    (root, rel, stored_hash, size, mtime_ns, needs_hash, stored_rag_hash, generation, stored_card, now),
                )
            # Keep project-wide derived caches intact. Per-path source rows above
            # are invalidated precisely; a broad change must never clear every
            # module/project cache in one operation.
        self._write_retry(_apply)

        structural_hash = row.get("structural_hash")
        if topology_changed:
            with self._db_lock, services_module.closing(self._connect()) as con:
                all_paths = [str(r[0]) for r in con.execute("SELECT path FROM file_refs WHERE root=? ORDER BY path", (root,)).fetchall()]
            structural_hash = services_module.stable_hash({
                "structure": [(path, services_module.Path(path).suffix.lower()) for path in all_paths],
                "models": {k: self.config.get("models", {}).get(k) for k in ("fast_code", "heavy_code", "reasoning")},
                "analyzer": services_module.PREPROCESS_ANALYZER_VERSION,
                "project_config": getattr(self._project_config_context(root)[1], "config_digest", ""),
            })
        inventory_hash = services_module.stable_hash({"previous": row.get("inventory_hash"), "dirty": sorted(content_changed)})
        if not content_changed:
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(
                root, phase="complete", status="complete", force_refresh=0,
                next_check_at=now + interval, last_error=None, retry_after=0,
                inventory_hash=row.get("inventory_hash"), structural_hash=structural_hash,
                stats_json=services_module.json_dumps({
                    "changed_files": 0, "changed_paths": [], "major_change": False,
                    "incremental_watcher": True, "ignored_metadata_events": len(paths),
                }),
            )
            with self._stats_lock:
                self._stats["watcher_noop_events"] = self._stats.get("watcher_noop_events", 0) + len(paths)
                self._stats["watcher_incremental_runs"] = self._stats.get("watcher_incremental_runs", 0) + 1
                self._stats["watcher_incremental_files"] = self._stats.get("watcher_incremental_files", 0) + len(paths)
            return True
        self._set_project(
            root, phase="hash", status="running", generation=generation, force_refresh=0,
            inventory_hash=inventory_hash, structural_hash=structural_hash,
            last_error=None, retry_after=0,
            stats_json=services_module.json_dumps({
                "changed_files": len(content_changed), "changed_paths": sorted(content_changed)[:256], "major_change": major,
                "incremental_watcher": True,
            }),
        )
        if major:
            with self._stats_lock:
                self._stats["major_invalidations"] += 1
        with self._stats_lock:
            self._stats["watcher_incremental_runs"] = self._stats.get("watcher_incremental_runs", 0) + 1
            self._stats["watcher_incremental_files"] = self._stats.get("watcher_incremental_files", 0) + len(content_changed)
        return True

    def _step_inventory(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        _api, project_context = self._project_config_context(root)
        settings = project_context.settings if project_context is not None else services_module.resolve_project_config(root).settings
        config_digest = str(getattr(project_context, "config_digest", ""))
        if not services_module.Path(root).exists():
            self.unregister(root, purge_data=True)
            return True
        dirty_paths = self._consume_dirty_paths(root)
        if (dirty_paths and row.get("last_complete_at") and not bool(row.get("force_refresh"))
                and not self._pending_stub_cards(root)):
            if self._step_incremental_inventory(row, dirty_paths):
                return True
        # Metadata-only inventory: do not read/hash every file in one uninterruptible
        # pass. Content hashes are filled by the next checkpointed phase.
        inventory = self.repo_tools.file_inventory(root, include_hashes=False)
        if not inventory.get("success"):
            if not services_module.Path(root).exists():
                self.unregister(root, purge_data=True)
                return True
            raise RuntimeError(str(inventory.get("error", "inventory failed")))
        if self._yield():
            return False
        policy_api, project_context = self._project_config_context(root)
        inventory_files = {str(item["path"]): item for item in inventory.get("files", []) if item.get("path")}
        self._add_project_text_extensions(root, inventory_files, policy_api, project_context)
        new_files: dict[str, dict[str, services_module.Any]] = {}
        for item in inventory_files.values():
            relative = str(item.get("path") or "")
            if not relative:
                continue
            try:
                size = int(item.get("size", 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if self._project_path_allowed(
                root, relative, settings, phase="preprocess", size_bytes=size
            ):
                new_files[relative] = item
        new_files.update(self._forced_preprocess_files(root, settings))
        with self._db_lock, services_module.closing(self._connect()) as con:
            old_rows = con.execute(
                "SELECT path,content_hash,size,mtime_ns,card_key,rag_hash FROM file_refs WHERE root=?", (root,)
            ).fetchall()
            old = {r["path"]: r for r in old_rows}
        changed = {
            path for path, item in new_files.items()
            if path not in old or int(old[path]["size"] or 0) != int(item.get("size", 0))
            or int(old[path]["mtime_ns"] or 0) != int(item.get("mtime_ns", 0))
        }
        deleted = set(old) - set(new_files)
        changed.update(deleted)
        changed_ratio = len(changed) / max(1, max(len(old), len(new_files)))
        # Timestamp-only changes still need a content hash, but are not evidence
        # of a broad content change. Keep them out of the project-wide invalidation
        # threshold; _step_hash decides whether each candidate's content changed.
        major_changed = {
            path for path, item in new_files.items()
            if path not in old
            or int(old[path]["size"] or 0) != int(item.get("size", 0))
        }
        major_changed.update(deleted)
        major_changed_ratio = len(major_changed) / max(1, max(len(old), len(new_files)))
        manifest_names = {
            "package.json", "deno.json", "deno.jsonc", "pyproject.toml", "composer.json", "composer.lock", "package-lock.json", "pnpm-lock.yaml",
            "yarn.lock", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "go.work", "pom.xml", "build.gradle", "build.gradle.kts",
            "requirements.txt", "Pipfile", "poetry.lock", "uv.lock", "Gemfile", "Gemfile.lock", "packages.lock.json", "global.json",
            "Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props", "libs.versions.toml",
        }
        manifest_changed = any(services_module.Path(path).name in manifest_names for path in major_changed)
        # Structural identity is intentionally deterministic/cheap and independent
        # of local LLM output. Content-sensitive manifests are re-hashed next.
        structure = [(p, services_module.Path(p).suffix.lower()) for p, x in sorted(new_files.items())]
        structural_hash = services_module.stable_hash({
            "structure": structure,
            "models": {k: self.config.get("models", {}).get(k) for k in ("fast_code", "heavy_code", "reasoning")},
            "analyzer": services_module.PREPROCESS_ANALYZER_VERSION,
            "project_config": config_digest,
            "project_type": getattr(settings, "project_type", None),
            "solution_path": getattr(settings, "solution_path", None),
            "language_overrides": getattr(settings, "language_overrides", {}),
        })
        force = bool(row.get("force_refresh"))
        now = services_module.time.time()
        if (
            not changed
            and not force
            and row.get("last_complete_at")
            and row.get("structural_hash") == structural_hash
        ):
            rag_allowed = self._project_phase_allowed(root, "rag")
            with self._db_lock, services_module.closing(self._connect()) as con:
                uncarded = con.execute("SELECT COUNT(*) FROM file_refs WHERE root=? AND card_key IS NULL", (root,)).fetchone()[0]
                unragged = (
                    con.execute("SELECT COUNT(*) FROM file_refs WHERE root=? AND (rag_hash IS NULL OR rag_hash<>content_hash)", (root,)).fetchone()[0]
                    if rag_allowed
                    else 0
                )
            pending_stubs = self._pending_stub_cards(root)
            if uncarded == 0 and unragged == 0 and pending_stubs == 0:
                # Matching source hashes can still have vectors in the old embedding space.
                if rag_allowed and self._rag_reindex_paths(root, str(row["workspace"]), limit=1):
                    self._set_project(root, phase="rag", force_refresh=0)
                    return True
                self._set_project(root, phase="complete", status="complete", force_refresh=0, next_check_at=now + float(self.cfg.get("auto_recheck_seconds", 1800)), updated_at=now)
                return True

        ratio_min_files = max(2, int(self.cfg.get("major_change_ratio_min_files", 12)))
        major = force or row.get("structural_hash") not in {None, structural_hash} or manifest_changed \
            or len(major_changed) >= int(self.cfg.get("major_change_files", 60)) \
            or (len(major_changed) >= ratio_min_files and major_changed_ratio >= float(self.cfg.get("major_change_ratio", 0.15)))
        generation = int(row.get("generation", 0)) + (1 if major else 0)
        with self._db_lock, services_module.closing(self._connect()) as con:
            for path in deleted:
                con.execute("DELETE FROM file_refs WHERE root=? AND path=?", (root, path))
                con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, path))
                self._delete_fts_rows(con, "root=? AND path=?", (root, path))
            for path, item in new_files.items():
                existing = old.get(path)
                stat_changed = force or path in changed
                old_hash = str(existing["content_hash"] or "") if existing else ""
                old_rag_hash = str(existing["rag_hash"] or "") if existing else ""
                old_card = existing["card_key"] if existing else None
                # Lexical indexing reads working-tree bytes and uses SHA-256.
                # Git blob IDs use a different hash domain (and may apply clean
                # filters), so they cannot serve as content identities here.
                seeded_hash = old_hash
                needs_hash = int(stat_changed or not old_hash or old_hash.startswith("git:"))
                con.execute(
                    """INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root,path) DO UPDATE SET
                       content_hash=excluded.content_hash,size=excluded.size,mtime_ns=excluded.mtime_ns,
                       needs_hash=excluded.needs_hash,rag_hash=excluded.rag_hash,generation=excluded.generation,
                       card_key=excluded.card_key,updated_at=excluded.updated_at""",
                    (
                        root, path, seeded_hash, int(item.get("size", 0)), int(item.get("mtime_ns", 0)), needs_hash,
                        old_rag_hash, generation, old_card, now,
                    ),
                )
            # Keep project-wide derived caches intact. Per-path content changes
            # are handled by the hash/index phases; never clear every project
            # cache because an inventory crosses the major-change threshold.
            con.commit()
        self._link_content_reuse(root)
        if major:
            with self._stats_lock:
                self._stats["major_invalidations"] += 1
        inventory_hash = services_module.stable_hash([(p, int(x.get("size", 0)), int(x.get("mtime_ns", 0))) for p, x in sorted(new_files.items())])
        self._set_project(
            root, phase="hash", status="running", generation=generation, force_refresh=int(force),
            inventory_hash=inventory_hash, structural_hash=structural_hash,
            last_error=None, retry_after=0,
            stats_json=services_module.json_dumps({"changed_files": len(changed), "changed_paths": sorted(changed)[:256], "changed_ratio": round(changed_ratio, 4), "major_change": major, "incremental_watcher": False}),
        )
        return True

