from __future__ import annotations

from .app import (
    AgentScope as AgentScope,
    Any as Any,
    BundleValidationError as BundleValidationError,
    Mapping as Mapping,
    MemoryRecord as MemoryRecord,
    MemoryStatus as MemoryStatus,
    Path as Path,
    _DET_TABLES as _DET_TABLES,
    _PREPROCESS_TABLES as _PREPROCESS_TABLES,
    __version__ as __version__,
    _has_retired_bundle_tenant_field as _has_retired_bundle_tenant_field,
    _normalise_scope_root as _normalise_scope_root,
    io as io,
    json as json,
    json_dumps as json_dumps,
    resolve_project_context as resolve_project_context,
    sqlite3 as sqlite3,
    stat as stat,
    time as time,
    write_transaction as write_transaction,
    zipfile as zipfile,
)


LocalAIApp = None


class AppBundleMixin:
    def export_bundle(
        self,
        root: str = "",
        *,
        agent_state_record_ids: list[str] | None = None,
        agent_state_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> bytes:
        """Export portable precomputed project state into a bounded ZIP bundle."""
        import hashlib
        from contextlib import closing

        max_bundle, max_json, max_rows = self._bundle_limits()

        exported_agent_records: list[dict[str, Any]] = []
        if agent_state_record_ids is not None:
            for rid in agent_state_record_ids:
                rec = None
                if getattr(self, "agent_memory", None):
                    supplied_context = (agent_state_contexts or {}).get(rid, {})
                    if "tenant" in supplied_context:
                        raise BundleValidationError("agent memory context field 'tenant' is retired")
                    lookup_context = {
                        key: supplied_context[key]
                        for key in (
                            "scope", "scope_id", "root", "repository_id",
                            "task_id", "session_id", "clone_id", "worktree_id", "branch",
                        )
                        if key in supplied_context
                    }
                    lookup_context.setdefault("root", root or None)
                    scope_value = getattr(lookup_context.get("scope"), "value", lookup_context.get("scope"))
                    if scope_value == "repository" and not str(lookup_context.get("root") or "").strip():
                        raise BundleValidationError("repository memory requires provenance root")
                    if rid in (agent_state_contexts or {}):
                        rec = self.agent_memory.get(rid, **lookup_context)
                    else:
                        rec = self.agent_memory.get(rid, scope=AgentScope.GLOBAL)
                        if rec is None and root:
                            project = resolve_project_context(
                                root, Path(self.agent_state.db_path).parent
                            )
                            rec = self.agent_memory.get(
                                rid, scope=AgentScope.REPOSITORY,
                                root=root, repository_id=project.coordination_id,
                            )
                if rec is not None:
                    scope_val = getattr(rec.scope, "value", rec.scope)
                    status_val = getattr(rec.status, "value", rec.status)
                    if (scope_val == "global" or scope_val == AgentScope.GLOBAL) and status_val not in ("active", "confirmed", MemoryStatus.ACTIVE, MemoryStatus.CONFIRMED):
                        raise BundleValidationError(f"disallowed scope: unapproved global record {rid}")
                    record_data = rec.to_dict()
                    if _has_retired_bundle_tenant_field(record_data):
                        raise BundleValidationError(
                            f"memory record {rid} contains retired tenant provenance; offline conversion required"
                        )
                    exported_agent_records.append({"type": "memory", "data": record_data})
                else:
                    t = self.agent_tasks.get(rid) if getattr(self, "agent_tasks", None) else None
                    if t is not None:
                        exported_agent_records.append({"type": "task", "data": t.to_dict()})
                    else:
                        raise BundleValidationError(f"record {rid} not found")

            if not root:
                canonical = json_dumps(exported_agent_records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                bundle_data: dict[str, Any] = {
                    "format": "local-ai-hub-agent-state-bundle",
                    "version": __version__,
                    "exported_at": time.time(),
                    "records_sha256": hashlib.sha256(canonical).hexdigest(),
                    "records": exported_agent_records,
                }
                raw_json = json_dumps(bundle_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if len(raw_json) > max_json:
                    raise ValueError(f"bundle.json exceeds configured limit ({max_json} bytes)")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    info = zipfile.ZipInfo("bundle.json")
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o600 << 16
                    zf.writestr(info, raw_json)
                result = buf.getvalue()
                if len(result) > max_bundle:
                    raise ValueError(f"bundle exceeds configured compressed limit ({max_bundle} bytes)")
                return result

        root_obj = Path(root).expanduser().resolve()
        if not root_obj.is_dir():
            raise ValueError(f"root directory does not exist: {root_obj}")
        root_path = str(root_obj).replace("\\", "/")
        for item in exported_agent_records:
            if item.get("type") != "memory":
                continue
            record_data = item.get("data") or {}
            if record_data.get("scope") != "repository":
                continue
            provenance = record_data.get("provenance")
            source_root = provenance.get("root") if isinstance(provenance, dict) else None
            if not source_root:
                raise BundleValidationError(
                    f"repository memory record {record_data.get('record_id', '')} requires provenance root"
                )
            if source_root and _normalise_scope_root(str(source_root)) != _normalise_scope_root(root_path):
                raise BundleValidationError(
                    f"repository root mismatch for agent memory record {record_data.get('record_id', '')}"
                )
        workspace = self.rag.workspace_id(root_path)
        tables: dict[str, list[dict[str, Any]]] = {}

        def checked(name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if len(rows) > max_rows:
                raise ValueError(f"bundle table {name} exceeds configured row limit ({max_rows})")
            return rows

        with closing(self.preprocessor._connect()) as con:
            con.row_factory = sqlite3.Row
            tables["projects"] = checked("projects", [dict(r) for r in con.execute("SELECT * FROM projects WHERE root=?", (root_path,)).fetchall()])
            tables["file_refs"] = checked("file_refs", [dict(r) for r in con.execute("SELECT * FROM file_refs WHERE root=?", (root_path,)).fetchall()])
            tables["content_cards"] = checked("content_cards", [
                dict(r) for r in con.execute(
                    "SELECT * FROM content_cards WHERE card_key IN (SELECT card_key FROM file_refs WHERE root=? AND card_key IS NOT NULL)",
                    (root_path,),
                ).fetchall()
            ])
            tables["module_cards"] = checked("module_cards", [dict(r) for r in con.execute("SELECT * FROM module_cards WHERE root=?", (root_path,)).fetchall()])
            tables["project_cards"] = checked("project_cards", [dict(r) for r in con.execute("SELECT * FROM project_cards WHERE root=?", (root_path,)).fetchall()])
            tables["external_index_state"] = checked("external_index_state", [dict(r) for r in con.execute("SELECT * FROM external_index_state WHERE root=?", (root_path,)).fetchall()])

        if self.deterministic is not None:
            with closing(self.deterministic._connect()) as con:
                con.row_factory = sqlite3.Row
                tables["deterministic_files"] = checked("deterministic_files", [dict(r) for r in con.execute("SELECT * FROM files WHERE root=?", (root_path,)).fetchall()])
                tables["deterministic_facts"] = checked("deterministic_facts", [dict(r) for r in con.execute("SELECT * FROM facts WHERE root=?", (root_path,)).fetchall()])
                tables["dependencies"] = checked("dependencies", [dict(r) for r in con.execute("SELECT * FROM dependencies WHERE root=?", (root_path,)).fetchall()])
                tables["scripts"] = checked("scripts", [dict(r) for r in con.execute("SELECT * FROM scripts WHERE root=?", (root_path,)).fetchall()])

        if self.rag is not None:
            with closing(self.rag._connect()) as con:
                con.row_factory = sqlite3.Row
                tables["rag_files"] = checked("rag_files", [dict(r) for r in con.execute("SELECT * FROM files WHERE workspace=?", (workspace,)).fetchall()])
                tables["rag_chunks"] = checked("rag_chunks", [dict(r) for r in con.execute("SELECT * FROM chunks WHERE workspace=?", (workspace,)).fetchall()])
                tables["rag_project_file_owners"] = checked(
                    "rag_project_file_owners",
                    [dict(r) for r in con.execute(
                        "SELECT * FROM project_file_owners WHERE workspace=? AND root=?",
                        (workspace, root_path),
                    ).fetchall()],
                )

        encoded_tables = self._bundle_encode(tables)
        canonical = json_dumps(encoded_tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        bundle_data: dict[str, Any] = {
            "format": "local-ai-hub-project-bundle",
            "version": __version__,
            "root": root_path,
            "workspace": workspace,
            "exported_at": time.time(),
            "tables_sha256": hashlib.sha256(canonical).hexdigest(),
            "tables": encoded_tables,
        }
        if exported_agent_records:
            bundle_data["agent_state_records"] = exported_agent_records
            agent_records_canonical = json_dumps(
                exported_agent_records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            bundle_data["agent_state_records_sha256"] = hashlib.sha256(agent_records_canonical).hexdigest()
            all_state_canonical = json_dumps(
                {"agent_state_records": exported_agent_records, "tables": encoded_tables},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            bundle_data["tables_sha256"] = hashlib.sha256(all_state_canonical).hexdigest()
        raw_json = json_dumps(bundle_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw_json) > max_json:
            raise ValueError(f"bundle.json exceeds configured limit ({max_json} bytes)")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            info = zipfile.ZipInfo("bundle.json")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zf.writestr(info, raw_json)
        result = buf.getvalue()
        if len(result) > max_bundle:
            raise ValueError(f"bundle exceeds configured compressed limit ({max_bundle} bytes)")
        return result

    def import_bundle(self, bundle_bytes: bytes, target_root: str | None = None) -> dict[str, Any]:
        """Validate and restore a project bundle without extracting archive paths."""
        import hashlib
        import hmac
        import os
        import tempfile
        from contextlib import closing, contextmanager

        max_bundle, max_json, max_rows = self._bundle_limits()
        if not isinstance(bundle_bytes, (bytes, bytearray)) or not bundle_bytes:
            return {"success": False, "error": "bundle is empty"}
        if len(bundle_bytes) > max_bundle:
            return {"success": False, "error": f"bundle exceeds configured limit ({max_bundle} bytes)"}
        raw_bundle = bytes(bundle_bytes)
        bundle_sha256 = hashlib.sha256(raw_bundle).hexdigest()

        def sync_directory(path: Path) -> None:
            if os.name == "nt":
                return
            directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

        def atomic_write(path: Path, value: bytes) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
                    temp_path = Path(stream.name)
                    stream.write(value)
                    stream.flush()
                    os.fsync(stream.fileno())
                if os.name == "nt":
                    import ctypes

                    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
                    move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
                    move_file_ex.restype = ctypes.c_int
                    if not move_file_ex(str(temp_path), str(path), 0x1 | 0x8):
                        raise ctypes.WinError(ctypes.get_last_error())
                else:
                    os.replace(temp_path, path)
                    sync_directory(path.parent)
            except Exception:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
                raise

        def create_import_intent(root_path: str | None) -> dict[str, Any]:
            normalized_root = str(Path(root_path).resolve(strict=False)).replace("\\", "/") if root_path else None
            import_id = hashlib.sha256(f"{bundle_sha256}\0{normalized_root or ''}".encode("utf-8")).hexdigest()
            journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
            payload_path = journal_dir / f"{import_id}.bundle"
            journal_path = journal_dir / f"{import_id}.json"
            if journal_dir.is_symlink():
                raise OSError("bundle import journal directory cannot be a symlink")
            missing_directories: list[Path] = []
            directory = journal_dir
            while not directory.exists():
                if directory.is_symlink():
                    raise OSError("bundle import journal path cannot be a symlink")
                missing_directories.append(directory)
                parent = directory.parent
                if parent == directory:
                    break
                directory = parent
            journal_dir.mkdir(parents=True, exist_ok=True)
            for created_directory in reversed(missing_directories):
                sync_directory(created_directory.parent)
            if journal_path.exists():
                if journal_path.is_symlink() or not journal_path.is_file():
                    raise OSError("bundle import journal is not a regular file")
                if journal_path.stat().st_size > 16_384:
                    raise OSError("existing bundle import journal exceeds its metadata limit")
                manifest = json.loads(journal_path.read_text(encoding="utf-8"))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("import_id") != import_id
                    or manifest.get("bundle_sha256") != bundle_sha256
                    or manifest.get("target_root") != normalized_root
                    or manifest.get("schema_version") != 1
                    or manifest.get("status") not in {"staging", "incomplete", "complete"}
                    or not isinstance(manifest.get("completed_phases"), list)
                ):
                    raise OSError("existing bundle import journal does not match this payload")
                if payload_path.is_symlink() or not payload_path.is_file():
                    raise OSError("existing bundle import staged payload is unavailable")
                if payload_path.stat().st_size > max_bundle:
                    raise OSError("existing bundle import staged payload exceeds the configured limit")
                if hashlib.sha256(payload_path.read_bytes()).hexdigest() != bundle_sha256:
                    raise OSError("existing bundle import staged payload failed its integrity check")
                return manifest
            manifest = {
                "schema_version": 1,
                "import_id": import_id,
                "bundle_sha256": bundle_sha256,
                "target_root": normalized_root,
                "status": "staging",
                "completed_phases": [],
                "updated_at": time.time(),
            }
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            atomic_write(payload_path, raw_bundle)
            manifest["status"] = "incomplete"
            manifest["updated_at"] = time.time()
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            return manifest

        def staging_failure(root_path: str | None, exc: Exception) -> dict[str, Any]:
            recovery_pending = False
            try:
                normalized_root = str(Path(root_path).resolve(strict=False)).replace("\\", "/") if root_path else None
                import_id = hashlib.sha256(f"{bundle_sha256}\0{normalized_root or ''}".encode("utf-8")).hexdigest()
                journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
                if journal_dir.is_symlink():
                    recovery_pending = True
                elif journal_dir.is_dir():
                    journal_path = journal_dir / f"{import_id}.json"
                    payload_path = journal_dir / f"{import_id}.bundle"
                    recovery_pending = any(
                        path.exists() or path.is_symlink()
                        for path in (journal_path, payload_path)
                    )
            except Exception:
                recovery_pending = True
            return {
                "success": False,
                "status": "incomplete" if recovery_pending else "not_started",
                "degraded": recovery_pending,
                "recovery_pending": recovery_pending,
                "error": f"bundle import could not be staged: {type(exc).__name__}: {exc}",
            }

        def mark_import_phase(manifest: dict[str, Any], phase: str) -> None:
            phases = manifest.setdefault("completed_phases", [])
            if phase not in phases:
                phases.append(phase)
            manifest["status"] = "incomplete"
            manifest["updated_at"] = time.time()
            journal_path = Path(self.config["server"]["state_dir"]) / "bundle-imports" / f"{manifest['import_id']}.json"
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))

        def finish_import_intent(manifest: dict[str, Any]) -> bool:
            manifest["status"] = "complete"
            manifest["updated_at"] = time.time()
            journal_dir = Path(self.config["server"]["state_dir"]) / "bundle-imports"
            journal_path = journal_dir / f"{manifest['import_id']}.json"
            payload_path = journal_dir / f"{manifest['import_id']}.bundle"
            atomic_write(journal_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            try:
                payload_path.unlink(missing_ok=True)
                journal_path.unlink(missing_ok=True)
            except OSError:
                return True
            return False

        def incomplete_result(manifest: dict[str, Any], exc: Exception) -> dict[str, Any]:
            return {
                "success": False,
                "status": "incomplete",
                "degraded": True,
                "recovery_pending": True,
                "import_id": str(manifest.get("import_id", "")),
                "error": f"bundle import incomplete; recovery is pending: {type(exc).__name__}: {exc}",
            }

        @contextmanager
        def capture_import_phase(manifest: dict[str, Any], phase: str, errors: list[Exception]):
            try:
                yield
            except Exception as exc:
                errors.append(exc)
            else:
                try:
                    mark_import_phase(manifest, phase)
                except Exception as exc:
                    errors.append(exc)
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bundle), "r") as zf:
                infos = zf.infolist()
                if len(infos) != 1 or infos[0].filename != "bundle.json":
                    return {"success": False, "error": "bundle must contain exactly one bundle.json member"}
                info = infos[0]
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(mode)
                if stat.S_ISLNK(mode):
                    return {"success": False, "error": "bundle.json symlink members are not allowed"}
                if file_type not in {0, stat.S_IFREG}:
                    return {"success": False, "error": "bundle.json must be a regular file"}
                if info.is_dir() or info.file_size > max_json:
                    return {"success": False, "error": f"bundle.json exceeds configured limit ({max_json} bytes)"}
                raw = zf.read(info)
                if len(raw) != info.file_size:
                    return {"success": False, "error": "bundle.json size mismatch"}
                data = json.loads(raw.decode("utf-8"))
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            return {"success": False, "error": f"invalid bundle zip: {exc}"}

        if not isinstance(data, dict):
            return {"success": False, "error": "bundle root must be an object"}

        if _has_retired_bundle_tenant_field(data):
            return {"success": False, "error": "bundle contains retired tenant fields; offline conversion required"}

        version = str(data.get("version", ""))
        if version != __version__:
            return {"success": False, "error": f"bundle version must match Local AI Hub {__version__}"}

        bundle_format = str(data.get("format", ""))

        def prepare_agent_memory_records(
            records: Any,
            target_root_path: str | None = None,
            source_root_path: str | None = None,
        ) -> tuple[list[MemoryRecord] | None, str | None]:
            if not isinstance(records, list):
                return None, "bundle records are missing"
            prepared_records: list[MemoryRecord] = []
            for item in records:
                if not isinstance(item, dict):
                    return None, "invalid agent-state bundle record"
                rtype = item.get("type")
                rdata = item.get("data", {})
                if not isinstance(rdata, dict):
                    return None, "invalid agent-state bundle payload"
                if rtype == "memory" and getattr(self, "agent_memory", None):
                    try:
                        record_data = dict(rdata)
                        if set(record_data) != set(MemoryRecord.__dataclass_fields__):
                            return None, "memory record must use the complete current schema"
                        if not isinstance(record_data["record_id"], str) or not record_data["record_id"].strip():
                            return None, "memory record_id is required"
                        if not isinstance(record_data["scope"], str):
                            return None, "memory scope must be a canonical string"
                        scope_value = AgentScope.parse(record_data["scope"]).value
                        provenance = record_data["provenance"]
                        if not isinstance(provenance, dict):
                            return None, "memory provenance must be an object"
                        if scope_value == "repository":
                            source_root = provenance.get("root") if isinstance(provenance, dict) else None
                            if not source_root:
                                return None, "repository memory provenance root is required for import"
                            if not isinstance(provenance.get("repository_id"), str) or not provenance["repository_id"].strip():
                                return None, "repository memory requires repository_id"
                            if target_root_path:
                                if not source_root_path:
                                    return None, "project bundle root is required for repository memory import"
                                if _normalise_scope_root(str(source_root)) != _normalise_scope_root(source_root_path):
                                    return None, "repository memory provenance does not match bundle root"
                                imported_root = target_root_path
                                project = resolve_project_context(
                                    target_root_path, Path(self.agent_state.db_path).parent
                                )
                                if not project.coordination_id:
                                    return None, "target repository identity is unavailable"
                            else:
                                imported_root = str(
                                    Path(str(source_root)).expanduser().resolve(strict=False)
                                ).replace("\\", "/")
                            rebased_provenance = dict(provenance)
                            rebased_provenance.setdefault("source_root", str(source_root))
                            rebased_provenance["root"] = imported_root
                            if target_root_path:
                                rebased_provenance["repository_id"] = project.coordination_id
                            record_data["provenance"] = rebased_provenance
                        rec = MemoryRecord.from_dict(record_data)
                    except (KeyError, OSError, TypeError, ValueError):
                        return None, "invalid agent-state bundle memory record"
                    prepared_records.append(rec)
            return prepared_records, None

        def restore_agent_memory_records(
            records: list[MemoryRecord],
            manifest: dict[str, Any],
        ) -> None:
            for record_index, rec in enumerate(records):
                self.agent_memory.record(
                    rec,
                    actor="bundle_import",
                    idempotency_key=f"bundle-import:{manifest['import_id']}:memory:{record_index}",
                )

        if bundle_format == "local-ai-hub-agent-state-bundle":
            records = data.get("records", [])
            if not isinstance(records, list):
                return {"success": False, "error": "bundle records are missing"}
            canonical = json_dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            expected = str(data.get("records_sha256", ""))
            if not expected or not hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), expected):
                return {"success": False, "error": "bundle integrity check failed"}
            prepared_records, error = prepare_agent_memory_records(records)
            if error:
                return {"success": False, "error": error}
            try:
                manifest: dict[str, Any] | None = None
                manifest = create_import_intent(None)
                restore_agent_memory_records(prepared_records or [], manifest)
                mark_import_phase(manifest, "agent_memory")
                cleanup_pending = finish_import_intent(manifest)
            except Exception as exc:
                if manifest is None:
                    return staging_failure(None, exc)
                return incomplete_result(manifest, exc)
            return {
                "success": True,
                "status": "complete",
                "recovery_pending": False,
                "cleanup_pending": cleanup_pending,
                "import_id": manifest["import_id"],
                "version": __version__,
                "restored_records": len(prepared_records or []),
            }

        if bundle_format != "local-ai-hub-project-bundle":
            return {"success": False, "error": "invalid Local AI Hub bundle marker"}

        encoded_tables: Any = data.get("tables")
        if not isinstance(encoded_tables, dict):
            return {"success": False, "error": "bundle tables are missing"}
        has_agent_records = "agent_state_records" in data
        has_agent_records_hash = "agent_state_records_sha256" in data
        if has_agent_records != has_agent_records_hash:
            return {"success": False, "error": "bundle integrity check failed"}
        canonical = json_dumps(encoded_tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = str(data.get("tables_sha256", ""))
        table_hash_valid = bool(expected) and hmac.compare_digest(hashlib.sha256(canonical).hexdigest(), expected)
        if has_agent_records:
            agent_records = data.get("agent_state_records")
            if not isinstance(agent_records, list):
                return {"success": False, "error": "invalid agent-state bundle records"}
            agent_records_canonical = json_dumps(
                agent_records,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            agent_records_expected = str(data.get("agent_state_records_sha256", ""))
            if not agent_records_expected or not hmac.compare_digest(
                hashlib.sha256(agent_records_canonical).hexdigest(), agent_records_expected
            ):
                return {"success": False, "error": "bundle integrity check failed"}
            all_state_canonical = json_dumps(
                {"agent_state_records": agent_records, "tables": encoded_tables},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            table_hash_valid = table_hash_valid or hmac.compare_digest(
                hashlib.sha256(all_state_canonical).hexdigest(), expected
            )
        if not table_hash_valid:
            return {"success": False, "error": "bundle integrity check failed"}
        try:
            tables = self._bundle_decode(encoded_tables)
        except Exception as exc:
            return {"success": False, "error": f"invalid encoded bundle value: {exc}"}

        allowed_tables = {
            "projects", "file_refs", "content_cards", "module_cards", "project_cards", "external_index_state",
            "deterministic_files", "deterministic_facts", "dependencies", "scripts", "rag_files", "rag_chunks",
            "rag_project_file_owners",
        }
        for name, tbl_rows in tables.items():
            if name not in allowed_tables:
                continue
            if not isinstance(tbl_rows, list) or len(tbl_rows) > max_rows or any(not isinstance(row, dict) for row in tbl_rows):
                return {"success": False, "error": f"invalid or oversized bundle table: {name}"}
        if any(
            "embedding" in row
            and row["embedding"] is not None
            and not isinstance(row["embedding"], (str, bytes, bytearray, memoryview))
            for row in tables.get("rag_chunks", [])
        ):
            return {"success": False, "error": "invalid RAG chunk embedding"}

        rag_file_fields = {"workspace", "path", "mtime_ns", "size", "content_hash"}
        rag_chunk_fields = {
            "workspace", "path", "chunk_no", "content_hash", "text", "embedding", "embedding_space",
        }
        rag_owner_fields = {"workspace", "root", "path"}
        if self.rag is not None and not {"rag_files", "rag_chunks", "rag_project_file_owners"} <= set(tables):
            return {"success": False, "error": "bundle is missing required RAG tables"}
        if any(set(row) != rag_file_fields for row in tables.get("rag_files", [])):
            return {"success": False, "error": "incompatible RAG file schema; offline conversion required"}
        if any(set(row) != rag_chunk_fields for row in tables.get("rag_chunks", [])):
            return {"success": False, "error": "incompatible RAG chunk schema; offline conversion required"}
        if any(set(row) != rag_owner_fields for row in tables.get("rag_project_file_owners", [])):
            return {"success": False, "error": "incompatible RAG project ownership schema; offline conversion required"}

        orig_root = str(data.get("root", ""))
        source_workspace = str(data.get("workspace", ""))
        if not orig_root or source_workspace != self.rag.workspace_id(orig_root):
            return {"success": False, "error": "bundle workspace does not match its source root"}
        if any(
            row["workspace"] != source_workspace
            for row in (
                *tables.get("rag_files", []),
                *tables.get("rag_chunks", []),
                *tables.get("rag_project_file_owners", []),
            )
        ):
            return {"success": False, "error": "RAG rows do not match the bundle workspace"}
        if any(
            row["root"] != orig_root
            for row in tables.get("rag_project_file_owners", [])
        ):
            return {"success": False, "error": "RAG project ownership does not match the bundle root"}
        root = str(target_root or orig_root)
        root_obj = Path(root).expanduser().resolve(strict=False) if root else None
        if root_obj is None or not root_obj.is_dir():
            return {"success": False, "error": "target repository root does not exist"}
        root_path = str(root_obj).replace("\\", "/")
        workspace = self.rag.workspace_id(root_path)
        prepared_project_agent_records: list[MemoryRecord] = []
        if has_agent_records:
            prepared, error = prepare_agent_memory_records(
                data.get("agent_state_records"), root_path, str(data.get("root", ""))
            )
            if error:
                return {"success": False, "error": error}
            prepared_project_agent_records = prepared or []
        if self.rag is not None:
            try:
                self.rag._validate_existing_database(
                    self.rag.db_path, self.rag.index_fingerprint
                )
            except (RuntimeError, sqlite3.DatabaseError) as exc:
                return {
                    "success": False,
                    "error": f"RAG database cannot accept bundle import: {exc}",
                }
        now = time.time()

        def rows(name: str) -> list[dict[str, Any]]:
            value = tables.get(name, [])
            return value if isinstance(value, list) else []

        def _str(d: dict[str, Any], key: str, default: str = "") -> str:
            """Type-safe string extraction — prevents empty-path bugs from malformed bundles."""
            v = d.get(key, default)
            return str(v) if v is not None else default

        def _int(d: dict[str, Any], key: str, default: int = 0) -> int:
            """Type-safe int extraction with graceful fallback."""
            try:
                return int(d.get(key) or default)
            except (TypeError, ValueError):
                return default

        try:
            manifest = create_import_intent(root_path)
        except Exception as exc:
            return staging_failure(root_path, exc)
        phase_errors: list[Exception] = []

        # Restore root-scoped preprocessor state transactionally. Derived content
        # cards are content-addressed and therefore safe to upsert globally.
        with capture_import_phase(manifest, "preprocessor", phase_errors), self.preprocessor._db_lock, closing(self.preprocessor._connect()) as con, write_transaction(
            con, max_duration_seconds=5.0, rollback_label="bundle import"
        ):
            for table in ("file_refs", "module_cards", "project_cards", "external_index_state"):
                assert table in _PREPROCESS_TABLES, f"unexpected table name: {table}"  # defence-in-depth
                con.execute(f"DELETE FROM {table} WHERE root=?", (root_path,))  # noqa: S608
            con.execute("DELETE FROM projects WHERE root=?", (root_path,))
            project = rows("projects")[0] if rows("projects") else {}
            con.execute(
                """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,inventory_hash,structural_hash,registered_at,updated_at,last_complete_at,next_check_at,retry_after,last_error,stats_json,paused,last_requested_at,registration_source)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (root_path, workspace, "complete", "complete", int(project.get("generation", 1) or 1), 0,
                 project.get("inventory_hash"), project.get("structural_hash"), now, now, now, 0, 0, None,
                 str(project.get("stats_json", "{}") or "{}"), 0, now, "bundle-import"),
            )
            for f in rows("file_refs"):
                con.execute(
                    """INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,last_accessed_at,generation,card_key,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (root_path, str(f.get("path", "")), str(f.get("content_hash", "")), int(f.get("size", 0) or 0),
                     int(f.get("mtime_ns", 0) or 0), 0, f.get("rag_hash"), now, int(f.get("generation", 1) or 1), f.get("card_key"), now),
                )
            for c in rows("content_cards"):
                con.execute(
                    """INSERT OR REPLACE INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (str(c.get("card_key", "")), str(c.get("content_hash", "")), str(c.get("model", "")),
                     str(c.get("analyzer_version", "")), str(c.get("card_json", "{}")), float(c.get("created_at", now) or now), now, int(c.get("hits", 0) or 0)),
                )
            for m in rows("module_cards"):
                con.execute("INSERT INTO module_cards(root,module,revision_hash,card_json,updated_at) VALUES(?,?,?,?,?)",
                            (root_path, str(m.get("module", "")), str(m.get("revision_hash", "")), str(m.get("card_json", "{}")), now))
            for item in rows("project_cards")[:1]:
                con.execute("INSERT INTO project_cards(root,revision_hash,card_json,updated_at) VALUES(?,?,?,?)",
                            (root_path, str(item.get("revision_hash", "")), str(item.get("card_json", "{}")), now))
            for item in rows("external_index_state"):
                con.execute("INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                            (root_path, str(item.get("backend", "")), str(item.get("revision_hash", "")), str(item.get("status", "complete")), now, item.get("error")))
        if phase_errors:
            return incomplete_result(manifest, phase_errors[0])

        if self.deterministic is not None:
            with capture_import_phase(manifest, "deterministic", phase_errors), self.deterministic._lock, closing(self.deterministic._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="bundle import"
            ):
                for table in ("files", "facts", "dependencies", "scripts", "project_state", "query_cache"):
                    assert table in _DET_TABLES, f"unexpected table name: {table}"  # defence-in-depth
                    con.execute(f"DELETE FROM {table} WHERE root=?", (root_path,))  # noqa: S608
                for f in rows("deterministic_files"):
                    con.execute(
                        "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
                        (root_path, str(f.get("path", "")), str(f.get("content_hash", "")), str(f.get("language", "")), int(f.get("is_test", 0) or 0), now),
                    )
                for ft in rows("deterministic_facts"):
                    extra = ft.get("extra_json")
                    if extra is None:
                        extra = json_dumps({k: ft[k] for k in ("method", "source", "confidence") if k in ft}, separators=(",", ":"))
                    elif not isinstance(extra, str):
                        extra = json_dumps(extra, ensure_ascii=False, separators=(",", ":"))
                    con.execute(
                        "INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)",
                        (root_path, str(ft.get("path", "")), str(ft.get("kind", "")), str(ft.get("name", "")), str(ft.get("value", "")), int(ft.get("line", 0) or 0), str(extra or "{}")),
                    )
                for d in rows("dependencies"):
                    con.execute("INSERT OR REPLACE INTO dependencies(root,source,name,version,scope) VALUES(?,?,?,?,?)",
                                (root_path, str(d.get("source", "")), str(d.get("name", "")), str(d.get("version", "")), str(d.get("scope", ""))))
                for item in rows("scripts"):
                    con.execute("INSERT OR REPLACE INTO scripts(root,source,name,command,purpose) VALUES(?,?,?,?,?)",
                                (root_path, str(item.get("source", "")), str(item.get("name", "")), str(item.get("command", "")), str(item.get("purpose", ""))))
            if phase_errors:
                return incomplete_result(manifest, phase_errors[0])
        else:
            mark_import_phase(manifest, "deterministic")

        if self.rag is not None:
            with capture_import_phase(manifest, "rag", phase_errors), self.rag._index_lock, closing(self.rag._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="bundle import"
            ):
                has_fts = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                ).fetchone() is not None
                if has_fts:
                    con.execute("DELETE FROM chunk_fts WHERE workspace=?", (workspace,))
                con.execute("DELETE FROM chunks WHERE workspace=?", (workspace,))
                con.execute("DELETE FROM files WHERE workspace=?", (workspace,))
                con.execute(
                    "DELETE FROM project_file_owners WHERE workspace=? AND root=?",
                    (workspace, root_path),
                )
                for f in rows("rag_files"):
                    con.execute("INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
                                (workspace, str(f.get("path", "")), int(f.get("mtime_ns", 0) or 0), int(f.get("size", 0) or 0), str(f.get("content_hash", ""))))
                for c in rows("rag_chunks"):
                    con.execute("INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
                                (workspace, str(c.get("path", "")), int(c.get("chunk_no", 0) or 0), str(c.get("content_hash", "")), str(c.get("text", "")), c.get("embedding", ""), str(c.get("embedding_space", ""))))
                    if has_fts:
                        con.execute(
                            "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
                            (workspace, str(c.get("path", "")), int(c.get("chunk_no", 0) or 0), str(c.get("text", ""))),
                        )
                for owner in rows("rag_project_file_owners"):
                    con.execute(
                        "INSERT INTO project_file_owners(workspace,root,path) VALUES(?,?,?)",
                        (workspace, root_path, str(owner.get("path", ""))),
                    )
                self.rag._bump_workspace_index_generation(con, workspace)
            if phase_errors:
                return incomplete_result(manifest, phase_errors[0])
        else:
            mark_import_phase(manifest, "rag")

        with capture_import_phase(manifest, "agent_memory", phase_errors):
            for record_index, rec in enumerate(prepared_project_agent_records):
                self.agent_memory.record(
                    rec,
                    actor="bundle_import",
                    idempotency_key=f"bundle-import:{manifest['import_id']}:memory:{record_index}",
                )
        if phase_errors:
            return incomplete_result(manifest, phase_errors[0])
        restored_agent_records = len(prepared_project_agent_records)

        try:
            cleanup_pending = finish_import_intent(manifest)
        except Exception as exc:
            return incomplete_result(manifest, exc)

        return {
            "success": True,
            "status": "complete",
            "recovery_pending": False,
            "cleanup_pending": cleanup_pending,
            "import_id": manifest["import_id"],
            "version": __version__,
            "root": root_path,
            "workspace": workspace,
            "files_imported": len(rows("file_refs")),
            "cards_imported": len(rows("content_cards")),
            "rag_chunks_imported": len(rows("rag_chunks")),
            "agent_state_records_imported": restored_agent_records,
        }

