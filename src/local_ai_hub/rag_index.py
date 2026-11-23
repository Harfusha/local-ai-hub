from __future__ import annotations

from contextlib import closing
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from typing import Any
import uuid

from .cache import stable_hash
from .process_utils import canonical_root
from .rag_chunking import (
    _check_rag_publish_budget,
    _fragment_hash,
    _rag_source_still_current,
    _read_bounded_file,
    _serialize_embedding,
    _simhash,
)
from .rag_constants import (
    ProjectPolicySyncError,
    RAG_CHUNKER_VERSION,
    _INDEX_EMBED_BATCH_SIZE,
    _RAGSourceChangedBeforePublish,
)
from .scheduler import QueueFullError
from .sqlite_support import is_busy_error, retry_busy, write_transaction


RAGStore = None


class RAGIndexMixin:
    @staticmethod
    def _get_ts_language(language: str) -> Any:
        """Load a tree-sitter Language object for the given language identifier."""
        if os.name == "nt" and sys.version_info >= (3, 13):
            return None
        try:
            from tree_sitter import Language
            if language in ("python",):
                import tree_sitter_python as m; return Language(m.language())
            elif language in ("c_sharp",):
                import tree_sitter_c_sharp as m; return Language(m.language())
            elif language in ("typescript",):
                import tree_sitter_typescript as m; return Language(m.language_typescript())
            elif language in ("javascript",):
                import tree_sitter_javascript as m; return Language(m.language())
        except Exception:
            pass
        return None

    def _text_chunks(self, text: str, size: int, overlap: int) -> list[str]:
        """Paragraph/newline-aware overlap chunker (original logic)."""
        size = max(1, size)
        overlap = min(max(0, overlap), size // 3)
        if len(text) <= size:
            return [text] if text.strip() else []
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + size)
            piece = text[start:end]
            if end < len(text):
                split = max(piece.rfind("\n\n"), piece.rfind("\n"))
                if split > size // 2:
                    end = start + split
                    piece = text[start:end]
            if piece.strip():
                chunks.append(piece)
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return chunks

    @staticmethod
    def _workspace_embedding_space_key(workspace: str) -> str:
        return "workspace_embedding_space:" + stable_hash({"workspace": workspace})

    @staticmethod
    def _workspace_chunker_version_key(workspace: str) -> str:
        return "workspace_chunker_version:" + stable_hash({"workspace": workspace})

    def _stored_workspace_chunker_version(
        self, con: sqlite3.Connection, workspace: str,
    ) -> str | None:
        row = con.execute(
            "SELECT value FROM rag_meta WHERE key=?",
            (self._workspace_chunker_version_key(workspace),),
        ).fetchone()
        return str(row[0]) if row is not None and row[0] else None

    def _workspace_chunker_index_is_current(
        self, con: sqlite3.Connection, workspace: str,
    ) -> bool:
        stored = self._stored_workspace_chunker_version(con, workspace)
        if stored is not None:
            return stored == RAG_CHUNKER_VERSION
        has_files = con.execute(
            "SELECT 1 FROM files WHERE workspace=? LIMIT 1", (workspace,),
        ).fetchone()
        has_chunks = con.execute(
            "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,),
        ).fetchone()
        return has_files is None and has_chunks is None

    def _store_workspace_chunker_version(
        self, con: sqlite3.Connection, workspace: str,
    ) -> None:
        con.execute(
            "INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)",
            (self._workspace_chunker_version_key(workspace), RAG_CHUNKER_VERSION),
        )

    @staticmethod
    def _workspace_index_generation_key(workspace: str) -> str:
        return "workspace_index_generation:" + stable_hash({"workspace": workspace})

    @staticmethod
    def _workspace_publication_key(workspace: str) -> str:
        return "workspace_publication:" + stable_hash({"workspace": workspace})

    @staticmethod
    def _project_root_identity(root: str | Path) -> str:
        canonical = canonical_root(str(Path(root).resolve(strict=False)))
        return stable_hash({"root": canonical})

    @staticmethod
    def _workspace_root_identity_key(workspace: str) -> str:
        return "workspace_root_identity:" + stable_hash({"workspace": workspace})

    def _set_workspace_repository_id(self, workspace: str, repository_id: str) -> None:
        guard = getattr(self, "_workspace_locks_guard", None)
        if guard is None:
            guard = threading.Lock()
            self._workspace_locks_guard = guard
        cache = getattr(self, "_workspace_repository_ids", None)
        if cache is None:
            cache = {}
            self._workspace_repository_ids = cache
        with guard:
            if repository_id:
                cache[workspace] = repository_id
            else:
                cache.pop(workspace, None)

    def _get_workspace_repository_id(self, workspace: str) -> str:
        guard = getattr(self, "_workspace_locks_guard", None)
        cache = getattr(self, "_workspace_repository_ids", None)
        if guard is None or not isinstance(cache, dict):
            return ""
        with guard:
            value = cache.get(workspace, "")
        return value if isinstance(value, str) else ""

    def require_workspace_root(self, *, workspace: str, root: str) -> None:
        """Require an exact repository/workspace binding before workspace access.

        A legacy populated workspace without a recorded root is ambiguous. It is
        deliberately rejected for explicit offline rebuild rather than adopted
        based on whichever repository asks first.
        """
        if type(root) is not str or not root or root != root.strip() or "\x00" in root:
            raise ValueError("RAG root must be a canonical non-empty path string")
        try:
            resolved = Path(root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("RAG root must be an existing repository directory") from exc
        if (
            not resolved.is_dir()
            or Path(root).is_symlink()
            or os.path.normcase(str(Path(root).absolute())) != os.path.normcase(str(resolved))
        ):
            raise ValueError("RAG root must be a real canonical directory without symlink aliases")
        if (
            type(workspace) is not str
            or not workspace
            or workspace != workspace.strip()
            or any(character.isspace() for character in workspace)
            or "\x00" in workspace
            or len(workspace) > 256
        ):
            raise ValueError("RAG workspace must be a canonical bounded identifier")

        expected_identity = self._project_root_identity(resolved)
        root_key = self._workspace_root_identity_key(workspace)
        with closing(self._connect()) as con:
            bound = con.execute(
                "SELECT value FROM rag_meta WHERE key=?", (root_key,)
            ).fetchone()
            if bound is None:
                populated = con.execute(
                    "SELECT 1 FROM files WHERE workspace=? LIMIT 1", (workspace,)
                ).fetchone() or con.execute(
                    "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,)
                ).fetchone()
                if populated is not None:
                    raise ValueError(
                        "populated RAG workspace has no repository binding; explicit offline rebuild required"
                    )

        if bound is None:
            self._set_workspace_repository_id(workspace, "")
            return
        if str(bound[0]) != expected_identity:
            raise ValueError("RAG workspace is already bound to a different repository root")

        repository_id = ""
        try:
            project_context = self.project_context(resolved)
            candidate_id = getattr(project_context, "coordination_id", "")
            if (
                isinstance(candidate_id, str)
                and candidate_id
                and candidate_id == candidate_id.strip()
                and "\x00" not in candidate_id
            ):
                repository_id = candidate_id
        except Exception:
            repository_id = ""
        self._set_workspace_repository_id(workspace, repository_id)

    @staticmethod
    def _workspace_project_config_key(
        workspace: str, root_identity: str = ""
    ) -> str:
        return "workspace_project_config:" + stable_hash({
            "workspace": workspace, "root": root_identity,
        })

    @staticmethod
    def _workspace_read_uncertainty_key(workspace: str) -> str:
        return "workspace_read_uncertainty:" + stable_hash({"workspace": workspace})

    def _workspace_read_uncertain_paths(self, con: sqlite3.Connection, workspace: str) -> set[str]:
        key = self._workspace_read_uncertainty_key(workspace)
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
        if row is None or not row[0]:
            return set()
        try:
            value = json.loads(str(row[0]))
        except (TypeError, ValueError):
            return {"*"}
        if not isinstance(value, list):
            return {"*"}
        return {str(path).replace("\\", "/") for path in value if isinstance(path, str) and path.strip()}

    def _update_workspace_read_uncertainty(
        self, con: sqlite3.Connection, workspace: str,
        *, uncertain_paths: set[str] | None = None, clear_paths: set[str] | None = None,
        bump_generation: bool = True,
    ) -> bool:
        key = self._workspace_read_uncertainty_key(workspace)
        current = self._workspace_read_uncertain_paths(con, workspace)
        updated = current - {str(path).replace("\\", "/") for path in (clear_paths or set())}
        updated |= {str(path).replace("\\", "/") for path in (uncertain_paths or set())}
        if updated == current:
            return False
        if updated:
            con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (
                key, json.dumps(sorted(updated), separators=(",", ":")),
            ))
        else:
            con.execute("DELETE FROM rag_meta WHERE key=?", (key,))
        if bump_generation:
            self._bump_workspace_index_generation(con, workspace)
        return True

    def _publish_workspace_read_uncertainty(
        self, workspace: str, uncertain_paths: set[str]
    ) -> None:
        if not uncertain_paths:
            return

        def publish() -> None:
            with closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="RAG read uncertainty"
            ):
                changed = self._update_workspace_read_uncertainty(
                    con, workspace,
                    uncertain_paths=uncertain_paths,
                    bump_generation=False,
                )
                if changed:
                    self._bump_workspace_index_generation(con, workspace)

        retry_busy(
            publish,
            retries=self._sqlite_write_retries,
            base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
        )

    def _sync_workspace_project_policy_identity(
        self,
        root: str | Path,
        workspace: str,
        project_context: Any | None,
    ) -> int:
        """Bind policy state to one root and prune only paths conclusively rejected."""
        digest = getattr(project_context, "config_digest", None)
        root_path = Path(root).resolve(strict=False)
        root_identity = self._project_root_identity(root_path)
        context_root = getattr(project_context, "root", None)
        if context_root is not None and self._project_root_identity(context_root) != root_identity:
            raise ProjectPolicySyncError(
                "project policy context belongs to a different root",
                retryable=False,
            )
        key = self._workspace_project_config_key(workspace, root_identity)
        root_key = self._workspace_root_identity_key(workspace)
        if not isinstance(digest, str) or not digest:
            with closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="RAG project policy identity"
            ):
                bound = con.execute("SELECT value FROM rag_meta WHERE key=?", (root_key,)).fetchone()
                if bound is not None and str(bound[0]) != root_identity:
                    raise ProjectPolicySyncError(
                        "RAG workspace is already bound to a different project root",
                        retryable=False,
                    )
                if bound is None:
                    populated = con.execute(
                        "SELECT 1 FROM files WHERE workspace=? LIMIT 1", (workspace,)
                    ).fetchone() or con.execute(
                        "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,)
                    ).fetchone()
                    if populated is not None:
                        raise ProjectPolicySyncError(
                            "populated RAG workspace has no repository binding; explicit offline rebuild required",
                            retryable=False,
                        )
                    con.execute(
                        "INSERT INTO rag_meta(key,value) VALUES(?,?)", (root_key, root_identity)
                    )
            return 0
        with closing(self._connect()) as con:
            bound_root = con.execute("SELECT value FROM rag_meta WHERE key=?", (root_key,)).fetchone()
            if bound_root is not None and str(bound_root[0]) != root_identity:
                raise ProjectPolicySyncError(
                    "RAG workspace is already bound to a different project root",
                    retryable=False,
                )
            previous = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
            previous_digest = str(previous[0]) if previous is not None else None
            if previous_digest == digest and bound_root is not None:
                return 0
            rows = con.execute(
                "SELECT path FROM files WHERE workspace=?",
                (workspace,),
            ).fetchall()
            has_chunks = con.execute(
                "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,)
            ).fetchone()
            if bound_root is None and (rows or has_chunks is not None):
                raise ProjectPolicySyncError(
                    "populated RAG workspace has no repository binding; explicit offline rebuild required",
                    retryable=False,
                )

        cfg = self.config.get("rag", {})
        extensions = {str(ext).lower() for ext in cfg.get("extensions", [])}
        ignored = {str(name).lower() for name in cfg.get("ignore_dirs", [])}
        max_bytes = int(cfg.get("max_file_bytes", 2_000_000))
        settings = project_context.settings
        if settings.max_file_size_bytes is not None:
            max_bytes = min(max_bytes, int(settings.max_file_size_bytes))
        rag_enabled = self._project_phase_allowed(project_context, "rag")
        rejected: list[str] = []
        uncertain: set[str] = set()
        for row in rows:
            rel = str(row[0]).replace("\\", "/")
            try:
                candidate = (root_path / rel).resolve(strict=False)
                candidate.relative_to(root_path)
                stat = candidate.stat()
                if not candidate.is_file():
                    rejected.append(rel)
                    continue
                api = self.project_config_api()
                kind = api.custom_extension_kind(candidate.name, settings) if api is not None else None
                if (
                    not rag_enabled
                    or any(part.lower() in ignored for part in Path(rel).parts[:-1])
                    or (extensions and candidate.suffix.lower() not in extensions and kind != "text")
                    or int(stat.st_size) > max_bytes
                ):
                    rejected.append(rel)
                    continue
                allowed, kind = self._project_path_decision(
                    root_path, candidate, project_context, phase="rag",
                    size_bytes=int(stat.st_size),
                )
                if not allowed or kind == "binary":
                    rejected.append(rel)
            except ValueError:
                rejected.append(rel)
                continue
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
                    rejected.append(rel)
                    continue
                uncertain.add(rel)
            except RuntimeError:
                uncertain.add(rel)

        if uncertain:
            self._publish_workspace_read_uncertainty(workspace, uncertain)
            raise ProjectPolicySyncError(
                "project policy scan could not verify indexed paths; retry required",
                retryable=True,
            )

        def verify_current_context() -> None:
            current_context = self.project_context(root_path)
            current_digest = getattr(current_context, "config_digest", None)
            current_root = getattr(current_context, "root", None)
            if (
                current_digest != digest
                or (current_root is not None and self._project_root_identity(current_root) != root_identity)
            ):
                raise ProjectPolicySyncError(
                    "project policy changed during RAG policy synchronization",
                    retryable=True,
                )

        def persist_identity() -> int:
            # Project config reads stay outside the SQLite writer transaction.
            verify_current_context()
            with closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="RAG project policy sync"
            ):
                current_root = con.execute(
                    "SELECT value FROM rag_meta WHERE key=?", (root_key,)
                ).fetchone()
                if current_root is not None and str(current_root[0]) != root_identity:
                    raise ProjectPolicySyncError(
                        "RAG workspace was concurrently bound to a different project root",
                        retryable=False,
                    )
                current = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
                current_digest = str(current[0]) if current is not None else None
                if current_digest == digest and current_root is not None:
                    return 0
                if current_digest != previous_digest:
                    raise ProjectPolicySyncError(
                        "project policy identity changed during RAG policy synchronization",
                        retryable=True,
                    )
                if rejected:
                    pairs = [(workspace, rel) for rel in sorted(set(rejected))]
                    con.executemany(
                        "DELETE FROM chunks WHERE workspace=? AND path=?", pairs
                    )
                    con.executemany(
                        "DELETE FROM files WHERE workspace=? AND path=?", pairs
                    )
                    fts_exists = con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                    ).fetchone() is not None
                    if fts_exists:
                        con.executemany(
                            "DELETE FROM chunk_fts WHERE workspace=? AND path=?", pairs
                        )
                    self._update_workspace_read_uncertainty(
                        con, workspace, clear_paths=set(rejected), bump_generation=False
                    )
                con.execute(
                    "INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)",
                    (root_key, root_identity),
                )
                con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (key, digest))
                self._bump_workspace_index_generation(con, workspace)
            return len(set(rejected))

        return retry_busy(
            persist_identity,
            retries=5,
            base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
        )

    def _workspace_index_generation(self, con: sqlite3.Connection, workspace: str) -> int:
        key = self._workspace_index_generation_key(workspace)
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
        try:
            return max(0, int(row[0])) if row and row[0] is not None else 0
        except (TypeError, ValueError):
            return 0

    def _bump_workspace_index_generation(self, con: sqlite3.Connection, workspace: str) -> int:
        key = self._workspace_index_generation_key(workspace)
        generation = self._workspace_index_generation(con, workspace) + 1
        con.executemany(
            "INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)",
            [(key, str(generation)),
             (self._workspace_publication_key(workspace), f"{generation}:{uuid.uuid4().hex}")],
        )
        return generation

    def _workspace_publication(
        self, con: sqlite3.Connection, workspace: str, generation: int,
    ) -> str | None:
        row = con.execute(
            "SELECT value FROM rag_meta WHERE key=?", (self._workspace_publication_key(workspace),),
        ).fetchone()
        if not row or not isinstance(row[0], str):
            return None
        recorded_generation, _, nonce = row[0].partition(":")
        if recorded_generation != str(generation) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            return None
        return nonce

    def _stored_workspace_embedding_space(
        self, con: sqlite3.Connection, workspace: str
    ) -> str | None:
        key = self._workspace_embedding_space_key(workspace)
        row = con.execute("SELECT value FROM rag_meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row and row[0] else None

    @staticmethod
    def _workspace_has_vectors_in_space(con: sqlite3.Connection, workspace: str, space: str) -> bool:
        return con.execute(
            """SELECT 1 FROM chunks WHERE workspace=? AND embedding_space=?
               AND embedding IS NOT NULL AND length(embedding)>0 LIMIT 1""",
            (workspace, space),
        ).fetchone() is not None

    @staticmethod
    def _workspace_has_stale_vectors(con: sqlite3.Connection, workspace: str, space: str) -> bool:
        return con.execute(
            "SELECT 1 FROM chunks WHERE workspace=? AND COALESCE(embedding_space,'')<>? LIMIT 1",
            (workspace, space),
        ).fetchone() is not None

    @staticmethod
    def _workspace_reindex_target_key(workspace: str) -> str:
        return f"workspace_reindex_target:{workspace}"

    def _stored_workspace_reindex_target(
        self, con: sqlite3.Connection, workspace: str
    ) -> str | None:
        row = con.execute(
            "SELECT value FROM rag_meta WHERE key=?",
            (self._workspace_reindex_target_key(workspace),),
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    def _request_workspace_reindex(self, workspace: str, embedding_space: str) -> None:
        key = self._workspace_reindex_target_key(workspace)

        def persist() -> None:
            with closing(self._connect()) as con:
                if self._stored_workspace_reindex_target(con, workspace) == embedding_space:
                    return
                with write_transaction(con, max_duration_seconds=5.0, rollback_label="RAG embedding-space reindex request"):
                    if self._stored_workspace_reindex_target(con, workspace) != embedding_space:
                        con.execute(
                            "INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)",
                            (key, embedding_space),
                        )

        retry_busy(
            persist,
            retries=self._sqlite_write_retries,
            base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
        )

    def _store_workspace_embedding_space(
        self, con: sqlite3.Connection, workspace: str, embedding_space: str
    ) -> None:
        key = self._workspace_embedding_space_key(workspace)
        con.execute("INSERT OR REPLACE INTO rag_meta(key,value) VALUES(?,?)", (key, embedding_space))

    def _embedding_space_is_resolved(self, result: dict[str, Any] | None = None) -> bool:
        if isinstance(result, dict) and result.get("embedding_space_id"):
            return True
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return True
        if isinstance(result, dict) and result.get("success"):
            embeddings = result.get("embeddings")
            if isinstance(embeddings, (list, tuple)) and embeddings:
                return True
        embedder = getattr(self.services, "embeddings", None)
        if getattr(embedder, "_active_cache_identity", None):
            return True
        if callable(getattr(embedder, "embedding_space_id", None)):
            # The configured revision cannot attest the unloaded backend or its vector space.
            return False
        models = self.config.get("models", {})
        return bool(
            models.get("embedding_digest") or models.get("model_digest")
            or models.get("embedding_revision") or models.get("model_revision")
        )

    def _embedding_space_cache_identity_known(self) -> bool:
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return True
        embedder = getattr(self.services, "embeddings", None)
        return bool(getattr(embedder, "_active_cache_identity", None))

    def _embedding_dimension_cache_identity(self) -> dict[str, Any]:
        models = self.config.get("models", {})
        cpu_cfg = self.config.get("cpu_retrieval", {})

        def valid_dimension(value: Any) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

        dimensions: dict[str, Any] = {
            "configured_model": valid_dimension(models.get("embedding_dimension")),
            "configured_cpu": valid_dimension(cpu_cfg.get("embedding_dimension")),
        }
        for owner_name, owner in (
            ("services", self.services),
            ("embedder", getattr(self.services, "embeddings", None)),
        ):
            for attribute in ("_active_embedding_dimension", "embedding_dimension", "dimension"):
                dimension = valid_dimension(getattr(owner, attribute, None)) if owner is not None else None
                if dimension is not None:
                    dimensions[f"{owner_name}_{attribute}"] = dimension
        return dimensions

    def _embedding_space_id(self, result: dict[str, Any] | None = None) -> str:
        if isinstance(result, dict) and result.get("embedding_space_id"):
            return str(result["embedding_space_id"])
        service_space = getattr(self.services, "space_id", None)
        if service_space and not callable(service_space):
            return str(service_space)
        embedder = getattr(self.services, "embeddings", None)
        identity_factory = getattr(embedder, "embedding_space_id", None)
        if callable(identity_factory):
            return str(identity_factory())
        models = self.config.get("models", {})
        backend = str((result or {}).get("backend") or models.get("embedding_backend", "unknown"))
        model = str((result or {}).get("model") or models.get("embedding", "unknown"))
        result_dimension = (result or {}).get("embedding_dimension") or models.get("embedding_dimension")
        normalized = (result or {}).get("normalized", models.get("embedding_normalized"))
        if normalized is None and backend in {"sentence-transformers", "openvino"}:
            normalized = True
        elif normalized is None and backend == "ollama":
            normalized = False
        payload = {
            "backend": backend,
            "model": model,
            "digest": (result or {}).get("model_digest") or models.get("embedding_digest") or models.get("model_digest"),
            "revision": (result or {}).get("model_revision") or models.get("embedding_revision") or models.get("model_revision"),
            "device": (result or {}).get("device") or models.get("embedding_device"),
            "dimension": result_dimension,
            "normalized": normalized,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def index(
        self,
        root: str,
        *,
        workspace: str | None = None,
        should_yield: Any | None = None,
    ) -> dict[str, Any]:
        resolved_root = str(Path(root).resolve())
        resolved_workspace = workspace or self.workspace_id(resolved_root)
        flight_key = (resolved_root, resolved_workspace)
        with self._index_flights_lock:
            flight = self._index_flights.get(flight_key)
            if flight is None:
                flight = {"event": threading.Event(), "result": None}
                self._index_flights[flight_key] = flight
                owner = True
            else:
                owner = False

        if not owner:
            if not flight["event"].wait(self._index_wait_timeout_seconds):
                return {
                    "success": False,
                    "error": "timed out waiting for identical RAG indexing work",
                    "retryable": True,
                    "coalesced": True,
                }
            shared_result = flight.get("result")
            if isinstance(shared_result, dict):
                result = dict(shared_result)
                result["coalesced"] = True
                return result
            return {
                "success": False,
                "error": "identical RAG indexing work ended without a result",
                "retryable": True,
                "coalesced": True,
            }

        result: dict[str, Any] = {
            "success": False,
            "error": "RAG indexing cancelled before publish completed",
            "retryable": True,
        }
        try:
            with self._get_workspace_lock(resolved_workspace):
                result = self._index_locked(
                    resolved_root, resolved_workspace, should_yield=should_yield,
                )
        except Exception as exc:
            result = {
                "success": False, "error": str(exc),
                "retryable": bool(getattr(exc, "retryable", is_busy_error(exc))),
            }
        finally:
            flight["result"] = result
            flight["event"].set()
            with self._index_flights_lock:
                self._index_flights.pop(flight_key, None)
        return result

    def _index_locked(
        self, root: str, workspace: str | None = None, *,
        should_yield: Any | None = None,
        _space_override: str | None = None, _identity_retry: bool = False,
    ) -> dict[str, Any]:
        try:
            root_path = Path(root).resolve()
            root_available = root_path.exists() and root_path.is_dir()
        except OSError as exc:
            return {
                "success": False,
                "retryable": True,
                "error": f"unable to inspect root directory: {exc}",
            }
        if not root_available:
            return {
                "success": False,
                "retryable": True,
                "error": f"root directory is unavailable: {root_path}",
            }
        project_context = self.project_context(root_path)
        if not self._project_phase_allowed(project_context, "rag"):
            target_ws = workspace or self.workspace_id(str(root_path))
            removed = self.prune_missing(root_path, target_ws, [])
            return {
                "success": True, "workspace": target_ws,
                "skipped": True, "reason": "project phase disabled",
                "removed_paths": removed, "processed_paths": [],
            }
        workspace = workspace or self.workspace_id(str(root_path))
        self._sync_workspace_project_policy_identity(root_path, workspace, project_context)
        embedding_space = _space_override or self._embedding_space_id()

        with closing(self._connect()) as con:
            uncertain_retry_paths = self._workspace_read_uncertain_paths(con, workspace)
            old_files_rows = con.execute(
                "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
                (workspace,),
            ).fetchall()
            old_chunk_rows = con.execute(
                "SELECT path,chunk_no,content_hash,embedding_space FROM chunks WHERE workspace=?",
                (workspace,),
            ).fetchall()
            stored_chunker_version = self._stored_workspace_chunker_version(con, workspace)
        chunker_version_changed = stored_chunker_version != RAG_CHUNKER_VERSION
        old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_files_rows}
        # A surviving files row does not prove its searchable chunks survived.
        # Missing chunks must be repaired even when size, mtime and hash match.
        paths_with_chunks = {str(row[0]) for row in old_chunk_rows}
        persisted_spaces = {
            str(r[3]).strip()
            for r in old_chunk_rows
            if r[3] and str(r[3]).strip()
        }
        if _space_override is None and len(persisted_spaces) == 1 and (
            not getattr(self.services, "space_id", None)
            and not self.config.get("models", {}).get("embedding_digest")
            and not self.config.get("models", {}).get("embedding_revision")
        ):
            embedding_space = next(iter(persisted_spaces))
        embedding_space_changed = any(
            str(row[3] or "") != embedding_space for row in old_chunk_rows
        )

        current_meta: dict[str, tuple[Path, int, int]] = {}
        metadata_scanned = 0
        discovery_errors: set[str] = set()

        def report_progress(percent: float, stage: str) -> None:
            if _identity_retry:
                percent = 55.0 + min(100.0, max(0.0, percent)) * 0.4
                stage = f"identity retry: {stage}"
            try:
                from .async_jobs import report_job_progress
            except ImportError:
                return
            report_job_progress(percent, stage)

        report_progress(5.0, "scanning files")
        for path in self._iter_files(
            root_path, project_context,
            discovery_errors if embedding_space_changed else None,
        ):
            metadata_scanned += 1
            if metadata_scanned == 1 or metadata_scanned % 25 == 0:
                report_progress(5.0, f"scanning files ({metadata_scanned} found)")
            try:
                stat = path.stat()
                rel = str(path.relative_to(root_path)).replace("\\", "/")
                current_meta[rel] = (path, int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                rel = path.relative_to(root_path).as_posix()
                if rel in old_files:
                    discovery_errors.add(rel)
                continue

        report_progress(15.0, f"file discovery complete ({metadata_scanned} found)")
        current_paths = set(current_meta)
        old_paths = set(old_files)
        discovery_error_hides_old_file = any(
            not failed_path
            or rel == failed_path
            or rel.startswith(failed_path + "/")
            for failed_path in discovery_errors
            for rel in old_files
        )
        if embedding_space_changed and discovery_error_hides_old_file:
            return {
                "success": False,
                "retryable": True,
                "workspace": workspace,
                "error": "embedding-space reindex could not inspect previously indexed files",
            }
        deleted_paths = sorted(old_paths - current_paths)
        # A path that was physically missing during discovery must not be
        # silently pruned if it reappears while embeddings are computed.
        # Paths excluded by current project policy still need normal pruning.
        physically_absent_deletions = {
            rel for rel in deleted_paths if not (root_path / rel).exists()
        }
        unchanged_paths: list[str] = []
        changed_paths: list[str] = []
        rag_cfg = self.config.get("rag", {})
        max_file_bytes = max(0, int(rag_cfg.get("max_file_bytes", 2_000_000)))
        settings = project_context.settings if project_context is not None else None
        if settings is not None and settings.max_file_size_bytes is not None:
            max_file_bytes = min(max_file_bytes, int(settings.max_file_size_bytes))
        verified_raw_by_path: dict[str, bytes] = {}
        read_uncertain_paths: set[str] = set()
        skipped = 0
        read_files = 0
        total_metadata_files = max(1, len(current_meta))
        for file_index, (rel, (_path, mtime_ns, size)) in enumerate(current_meta.items(), 1):
            if file_index == 1 or file_index % 25 == 0 or file_index == len(current_meta):
                report_progress(
                    15.0 + 20.0 * file_index / total_metadata_files,
                    f"checking file metadata ({file_index}/{len(current_meta)})",
                )
            old = old_files.get(rel)
            if (
                old and old["mtime_ns"] == mtime_ns and old["size"] == size
                and rel not in uncertain_retry_paths and not embedding_space_changed
            ):
                # Stat metadata can be preserved across edits. Verify the
                # persisted content digest before trusting an indexed file.
                try:
                    raw = _read_bounded_file(_path, max_file_bytes, root=root_path)
                    if raw is None:
                        skipped += 1
                        read_uncertain_paths.add(rel)
                        unchanged_paths.append(rel)
                        continue
                    read_files += 1
                    file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                except Exception:
                    skipped += 1
                    read_uncertain_paths.add(rel)
                    unchanged_paths.append(rel)
                    continue
                if file_hash == old.get("content_hash"):
                    if rel not in paths_with_chunks and self._chunks(
                        raw.decode("utf-8", errors="replace").replace("\r\n", "\n"),
                        path=rel,
                    ):
                        # Lost-chunk recovery: an unchanged nonblank document
                        # with no persisted chunks is not a complete index.
                        changed_paths.append(rel)
                        verified_raw_by_path[rel] = raw
                    else:
                        # Whitespace-only documents legitimately have no chunks.
                        unchanged_paths.append(rel)
                else:
                    changed_paths.append(rel)
                    verified_raw_by_path[rel] = raw
            else:
                changed_paths.append(rel)
        if embedding_space_changed:
            unchanged_paths = []
            changed_paths = sorted(current_meta)
        elif chunker_version_changed:
            unchanged_paths = []
            changed_paths = sorted(current_meta)

        # Preserve vectors only for changed files whose chunk hashes may be
        # reused. Reading every embedding blob for an unchanged workspace made
        # a no-op index scale with the full vector table size.
        old_chunks: dict[tuple[str, int, str], Any] = {}
        if changed_paths and embedding_space:
            with closing(self._connect()) as con:
                for offset in range(0, len(changed_paths), 400):
                    batch_paths = changed_paths[offset:offset + 400]
                    placeholders = ",".join("?" for _ in batch_paths)
                    rows = con.execute(
                        "SELECT path,chunk_no,content_hash,embedding FROM chunks "
                        f"WHERE workspace=? AND embedding_space=? AND path IN ({placeholders})",
                        (workspace, embedding_space, *batch_paths),
                    ).fetchall()
                    for row in rows:
                        if row[3] is not None:
                            old_chunks[(str(row[0]), int(row[1]), str(row[2]))] = row[3]

        changed_records: list[dict[str, Any]] = []
        file_rows: list[tuple[str, int, int, str]] = []
        reused_chunks = 0
        changed_indices: list[int] = []
        dedup_near_duplicates = bool(rag_cfg.get("dedup_near_duplicates", True))
        max_hamming = int(rag_cfg.get("near_duplicate_max_hamming", 4))
        near_duplicates_skipped = 0

        total_changed_files = max(1, len(changed_paths))
        for file_index, rel in enumerate(changed_paths, 1):
            report_progress(
                35.0 + 15.0 * (file_index - 1) / total_changed_files,
                f"reading changed files ({file_index - 1}/{len(changed_paths)})",
            )
            path, mtime_ns, size = current_meta[rel]
            try:
                raw = verified_raw_by_path.pop(rel, None)
                if raw is None:
                    raw = _read_bounded_file(path, max_file_bytes, root=root_path)
                if raw is None:
                    skipped += 1
                    read_uncertain_paths.add(rel)
                    continue
                read_files += 1
                text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
                file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
            except Exception:
                skipped += 1
                read_uncertain_paths.add(rel)
                continue
            file_rows.append((rel, mtime_ns, size, file_hash))
            file_chunks = self._chunks(text, path=rel)
            seen_simhashes: list[int] = []
            chunk_seq = 0
            for chunk in file_chunks:
                if dedup_near_duplicates and len(chunk) > 80:
                    fp = _simhash(chunk)
                    if fp != 0 and any((fp ^ s_fp).bit_count() <= max_hamming for s_fp in seen_simhashes):
                        near_duplicates_skipped += 1
                        continue
                    if fp != 0:
                        seen_simhashes.append(fp)

                chunk_hash = _fragment_hash(chunk)
                record = {
                    "path": rel,
                    "chunk_no": chunk_seq,
                    "file_content_hash": file_hash,
                    "text": chunk,
                    "hash": chunk_hash,
                    "embedding": old_chunks.get((rel, chunk_seq, chunk_hash)),
                }
                record["embedding_space"] = embedding_space if record["embedding"] is not None else ""
                chunk_seq += 1
                idx = len(changed_records)
                changed_records.append(record)
                if record["embedding"] is None:
                    changed_indices.append(idx)
                else:
                    reused_chunks += 1

        report_progress(50.0, f"changed-file chunks prepared ({len(changed_paths)} files)")
        self._publish_workspace_read_uncertainty(workspace, read_uncertain_paths)
        if embedding_space_changed and any(p in old_files for p in read_uncertain_paths):
            return {
                "success": False,
                "retryable": True,
                "workspace": workspace,
                "error": "embedding-space reindex could not read previously indexed files",
            }

        if changed_indices and embedding_space:
            indices_by_file: dict[str, list[int]] = {}
            for idx, record in enumerate(changed_records):
                indices_by_file.setdefault(str(record["file_content_hash"]), []).append(idx)
            # Re-embed damaged same-workspace rows; use CAS for cross-workspace reuse.
            workspace_file_hashes = {
                str(old["content_hash"]) for old in old_files.values() if old.get("content_hash")
            }
            file_hashes = [
                file_hash for file_hash in indices_by_file
                if file_hash not in workspace_file_hashes
            ]
            cached_by_file: dict[str, dict[int, tuple[str, Any]]] = {}
            with closing(self._connect()) as con:
                for offset in range(0, len(file_hashes), 500):
                    batch_hashes = file_hashes[offset:offset + 500]
                    placeholders = ",".join("?" for _ in batch_hashes)
                    rows = con.execute(
                        "SELECT content_hash, chunk_index, chunk_text, embedding_blob "
                        "FROM content_rag_chunks WHERE embedding_space=? "
                        f"AND content_hash IN ({placeholders})",
                        (embedding_space, *batch_hashes),
                    ).fetchall()
                    for content_hash, chunk_index, chunk_text, embedding_blob in rows:
                        cached_by_file.setdefault(str(content_hash), {})[int(chunk_index)] = (
                            str(chunk_text), embedding_blob,
                        )

            reused_indices: set[int] = set()
            for content_hash, indices in indices_by_file.items():
                cached = cached_by_file.get(content_hash)
                if not cached:
                    continue
                expected = {int(changed_records[idx]["chunk_no"]): idx for idx in indices}
                if set(cached) != set(expected) or any(
                    cached[chunk_index][0] != str(changed_records[idx]["text"])
                    or not cached[chunk_index][1]
                    for chunk_index, idx in expected.items()
                ):
                    continue
                for chunk_index, idx in expected.items():
                    record = changed_records[idx]
                    if record["embedding"] is None:
                        record["embedding"] = cached[chunk_index][1]
                        record["embedding_space"] = embedding_space
                        reused_indices.add(idx)
            if reused_indices:
                changed_indices = [idx for idx in changed_indices if idx not in reused_indices]
                reused_chunks += len(reused_indices)

        if changed_indices:
            # Cross-workspace chunk reuse check
            pending_by_hash: dict[str, list[int]] = {}
            for idx in changed_indices:
                pending_by_hash.setdefault(str(changed_records[idx]["hash"]), []).append(idx)
            missing_hashes = list(pending_by_hash)
            global_chunks: dict[str, Any] = {}
            with closing(self._connect()) as con:
                for i in range(0, len(missing_hashes), 500):
                    batch_h = missing_hashes[i:i + 500]
                    placeholders = ",".join("?" for _ in batch_h)
                    rows = con.execute(
                        f"SELECT content_hash, embedding FROM chunks WHERE embedding_space=? AND embedding_space<>'' AND content_hash IN ({placeholders})",
                        (embedding_space, *batch_h),
                    ).fetchall()
                    for r in rows:
                        if r[0] and r[1] and str(r[0]) not in global_chunks:
                            global_chunks[str(r[0])] = r[1]

            if global_chunks:
                still_indices: list[int] = []
                for chash, indices in pending_by_hash.items():
                    if chash in global_chunks:
                        for idx in indices:
                            changed_records[idx]["embedding"] = global_chunks[chash]
                            changed_records[idx]["embedding_space"] = embedding_space
                        reused_chunks += len(indices)
                    else:
                        first_idx = indices[0]
                        still_indices.append(first_idx)
                changed_indices = still_indices
            else:
                changed_indices = [indices[0] for indices in pending_by_hash.values()]

        if changed_indices:
            observed_embedding_space: str | None = None
            total_embedding_chunks = len(changed_indices)
            completed_embeddings = 0
            for offset in range(0, len(changed_indices), _INDEX_EMBED_BATCH_SIZE):
                batch_indices = changed_indices[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                report_progress(
                    55.0 + 30.0 * offset / total_embedding_chunks,
                    f"embedding chunks ({offset}/{total_embedding_chunks})",
                )
                if callable(should_yield) and should_yield():
                    self._publish_workspace_read_uncertainty(workspace, read_uncertain_paths)
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": [], "embedded_chunks": completed_embeddings,
                        "reused_chunks": reused_chunks,
                    }
                batch_texts = [str(changed_records[idx]["text"]) for idx in batch_indices]
                try:
                    vectors_result = self.services.embed(batch_texts, priority=2, query=False)
                except (TimeoutError, QueueFullError) as exc:
                    return {"success": False, "retryable": True, "error": f"embedder busy or timed out: {exc}"}
                except Exception as exc:
                    return {"success": False, "retryable": False, "error": f"embedder failed: {exc}"}
                if not isinstance(vectors_result, dict) or not vectors_result.get("success"):
                    return vectors_result if isinstance(vectors_result, dict) else {"success": False, "error": "embed failed"}
                vectors = vectors_result.get("embeddings", [])
                if len(vectors) != len(batch_indices):
                    return {"success": False, "error": f"embedding count mismatch: {len(vectors)} != {len(batch_indices)}"}
                batch_space = self._embedding_space_id(vectors_result)
                if observed_embedding_space is not None and observed_embedding_space != batch_space:
                    return {"success": False, "error": "embedding identity changed during atomic index build", "retryable": True}
                observed_embedding_space = batch_space
                if batch_space != embedding_space:
                    if _identity_retry:
                        return {"success": False, "error": "embedding identity changed during atomic index retry", "retryable": True}
                    if old_chunk_rows or reused_chunks:
                        return self._index_locked(
                            str(root_path), workspace, should_yield=should_yield,
                            _space_override=batch_space, _identity_retry=True,
                        )
                    embedding_space = batch_space
                for idx, vector in zip(batch_indices, vectors):
                    embedding = _serialize_embedding(vector)
                    if embedding is None:
                        return {"success": False, "error": "embedding backend returned an invalid vector"}
                    for duplicate_idx in pending_by_hash[str(changed_records[idx]["hash"])]:
                        changed_records[duplicate_idx]["embedding"] = embedding
                        changed_records[duplicate_idx]["embedding_space"] = batch_space
                completed_embeddings = offset + len(batch_indices)
                report_progress(
                    55.0 + 30.0 * completed_embeddings / total_embedding_chunks,
                    f"embedding chunks ({completed_embeddings}/{total_embedding_chunks})",
                )
                if callable(should_yield) and should_yield():
                    self._publish_workspace_read_uncertainty(workspace, read_uncertain_paths)
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": [], "embedded_chunks": completed_embeddings,
                        "reused_chunks": reused_chunks,
                    }
        else:
            report_progress(85.0, "embedding complete (0 new chunks)")


        # Run this on every SQLite publish attempt, not once before its busy
        # retries: source bytes can change while waiting for the writer lock.
        def assert_current_sources() -> None:
            stale_sources = [
                rel for rel, mtime_ns, size, file_hash in file_rows
                if not _rag_source_still_current(
                    root_path, rel, expected_hash=file_hash,
                    expected_size=size, expected_mtime_ns=mtime_ns,
                    max_bytes=max_file_bytes,
                )
            ]
            for rel in physically_absent_deletions:
                try:
                    (root_path / rel).lstat()
                except FileNotFoundError:
                    continue
                except OSError:
                    # Uncertain existence cannot authorize an irreversible
                    # deletion of previously committed indexed chunks.
                    pass
                stale_sources.append(rel)
            if stale_sources:
                raise _RAGSourceChangedBeforePublish(sorted(set(stale_sources)))

        chunker_version_publishable = (
            not chunker_version_changed
            or (
                not discovery_errors and not read_uncertain_paths and skipped == 0
                and len(file_rows) == len(current_meta)
            )
        )

        # One transaction publishes all changed/deleted file state atomically.
        # The embed phase is intentionally outside this retry: a transient writer
        # must not cause expensive model work to run again.
        def publish() -> None:
            assert_current_sources()
            publish_budget_seconds = 120.0
            with self._get_workspace_lock(workspace,), closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=publish_budget_seconds, rollback_label="RAG index publish"
            ):
                publish_started = time.monotonic()
                fts_exists = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                ).fetchone()
                _check_rag_publish_budget(
                    started_at=publish_started, stage="inspect_fts", budget_seconds=publish_budget_seconds,
                )
                successfully_read_paths = {str(row[0]) for row in file_rows}
                publish_paths = deleted_paths + [rel for rel in changed_paths if rel in successfully_read_paths]
                del_paths = [(workspace, rel) for rel in publish_paths]
                if del_paths:
                    con.executemany("DELETE FROM chunks WHERE workspace=? AND path=?", del_paths)
                    con.executemany("DELETE FROM files WHERE workspace=? AND path=?", del_paths)
                    if fts_exists:
                        con.execute("CREATE TEMP TABLE rag_publish_paths(path TEXT PRIMARY KEY)")
                        con.executemany(
                            "INSERT OR IGNORE INTO rag_publish_paths(path) VALUES(?)",
                            ((path,) for _workspace, path in del_paths),
                        )
                        con.execute(
                            "DELETE FROM chunk_fts WHERE workspace=? AND path IN "
                            "(SELECT path FROM rag_publish_paths)",
                            (workspace,),
                        )
                _check_rag_publish_budget(
                    started_at=publish_started, stage="delete_old_rows", budget_seconds=publish_budget_seconds,
                )
                owner_root = str(root_path)
                owner_paths = [(workspace, owner_root, rel) for rel in publish_paths]
                if owner_paths:
                    con.executemany(
                        "DELETE FROM project_file_owners WHERE workspace=? AND root=? AND path=?",
                        owner_paths,
                    )
                _check_rag_publish_budget(
                    started_at=publish_started, stage="delete_root_owners", budget_seconds=publish_budget_seconds,
                )
                con.executemany(
                    "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
                    [
                        (workspace, r["path"], r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"])
                        for r in changed_records
                    ],
                )
                _check_rag_publish_budget(
                    started_at=publish_started, stage="insert_chunks", budget_seconds=publish_budget_seconds,
                )
                if fts_exists:
                    con.executemany(
                        "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
                        [
                            (workspace, record["path"], record["chunk_no"], record["text"])
                            for record in changed_records
                        ],
                    )
                _check_rag_publish_budget(
                    started_at=publish_started, stage="insert_fts", budget_seconds=publish_budget_seconds,
                )
                con.executemany(
                    "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
                    [(workspace, rel, mtime_ns, size, file_hash) for rel, mtime_ns, size, file_hash in file_rows],
                )
                _check_rag_publish_budget(
                    started_at=publish_started, stage="insert_files", budget_seconds=publish_budget_seconds,
                )
                for offset in range(0, len(publish_paths), 500):
                    batch_paths = publish_paths[offset:offset + 500]
                    placeholders = ",".join("?" for _ in batch_paths)
                    con.execute(
                        "INSERT OR REPLACE INTO content_rag_chunks "
                        "(content_hash,embedding_space,chunk_index,chunk_text,embedding_blob,created_at) "
                        "SELECT f.content_hash,c.embedding_space,c.chunk_no,c.text,c.embedding,? "
                        "FROM chunks c JOIN files f ON f.workspace=c.workspace AND f.path=c.path "
                        f"WHERE c.workspace=? AND c.path IN ({placeholders}) "
                        "AND c.embedding IS NOT NULL AND c.embedding_space<>''",
                        (time.time(), workspace, *batch_paths),
                    )
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="insert_content_cas", budget_seconds=publish_budget_seconds,
                    )
                con.executemany(
                    "INSERT OR IGNORE INTO project_file_owners(workspace,root,path) VALUES(?,?,?)",
                    [
                        (workspace, owner_root, rel)
                        for rel, _mtime_ns, _size, _file_hash in file_rows
                    ],
                )
                _check_rag_publish_budget(
                    started_at=publish_started, stage="insert_root_owners", budget_seconds=publish_budget_seconds,
                )
                self._store_workspace_embedding_space(con, workspace, embedding_space)
                if chunker_version_changed and chunker_version_publishable:
                    self._store_workspace_chunker_version(con, workspace)
                uncertainty_changed = self._update_workspace_read_uncertainty(
                    con, workspace,
                    uncertain_paths=read_uncertain_paths,
                    clear_paths=set(publish_paths),
                    bump_generation=False,
                )
                if publish_paths or uncertainty_changed:
                    self._bump_workspace_index_generation(con, workspace)
                _check_rag_publish_budget(
                    started_at=publish_started, stage="update_index_metadata", budget_seconds=publish_budget_seconds,
                )

        report_progress(90.0, "publishing index")
        try:
            retry_busy(
                publish,
                retries=self._sqlite_write_retries,
                base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
            )
        except _RAGSourceChangedBeforePublish as exc:
            return {
                "success": False, "retryable": True, "workspace": workspace,
                "error": "source_changed_before_publish",
                "stale_source_paths": exc.paths,
                "read_uncertain_paths": sorted(set(read_uncertain_paths) | set(exc.paths)),
            }

        with closing(self._connect()) as con:
            chunk_count = con.execute(
                "SELECT COUNT(*) FROM chunks WHERE workspace=?", (workspace,)
            ).fetchone()[0]
            file_count = con.execute(
                "SELECT COUNT(*) FROM files WHERE workspace=?", (workspace,)
            ).fetchone()[0]

        report_progress(95.0, "index published")
        return {
            "success": True,
            "workspace": workspace,
            "files_root": str(root_path),
            "files": int(file_count),
            "chunks": int(chunk_count),
            "metadata_scanned_files": metadata_scanned,
            "read_files": read_files,
            "unchanged_files": len(unchanged_paths),
            "changed_files": len(changed_paths),
            "deleted_files": len(deleted_paths),
            "embedded_chunks": len(changed_indices),
            "reused_chunks": reused_chunks,
            "skipped_files": skipped,
            "read_uncertain_paths": sorted(read_uncertain_paths),
            "near_duplicates_skipped": near_duplicates_skipped,
            "embedding_space_id": embedding_space,
            "reindex_required": bool(chunker_version_changed and not chunker_version_publishable),
        }

