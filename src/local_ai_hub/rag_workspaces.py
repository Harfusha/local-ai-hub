from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import re
import stat
import time
from typing import Any

from .json_utils import dumps as json_dumps
from .rag_chunking import _fragment_hash, _serialize_embedding
from .rag_constants import _INDEX_EMBED_BATCH_SIZE
from .sqlite_support import is_busy_error, retry_busy, write_transaction


RAGStore = None


class RAGWorkspaceMixin:
    def list_workspaces(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT workspace, COUNT(*), COUNT(DISTINCT path) FROM chunks GROUP BY workspace ORDER BY workspace",
            ).fetchall()
        return [{"workspace": r[0], "chunks": r[1], "files": r[2]} for r in rows]

    def workspace_stats(self, workspaces: list[str]) -> dict[str, dict[str, int]]:
        """Return persisted file and chunk coverage for the requested workspaces."""
        selected = list(dict.fromkeys(str(workspace) for workspace in workspaces if str(workspace)))
        counts: dict[str, dict[str, int]] = {}
        for offset in range(0, len(selected), 400):
            batch = selected[offset : offset + 400]
            placeholders = ",".join("?" for _ in batch)
            with closing(self._connect()) as con:
                rows = con.execute(
                    f"""SELECT workspace, 'files', COUNT(*), COUNT(DISTINCT path)
                        FROM files WHERE workspace IN ({placeholders}) GROUP BY workspace
                        UNION ALL
                        SELECT workspace, 'chunks', COUNT(*), COUNT(DISTINCT path)
                        FROM chunks WHERE workspace IN ({placeholders}) GROUP BY workspace""",
                    (*batch, *batch),
                ).fetchall()
            for row in rows:
                workspace = str(row[0])
                stats = counts.setdefault(workspace, {})
                if row[1] == "files":
                    stats["files"] = int(row[2])
                else:
                    stats["chunks"] = int(row[2])
                    stats["chunked_files"] = int(row[3])
            with closing(self._connect()) as con:
                for workspace in batch:
                    counts.setdefault(workspace, {})["index_generation"] = self._workspace_index_generation(
                        con, workspace
                    )
                    uncertain_paths = self._workspace_read_uncertain_paths(con, workspace)
                    if uncertain_paths:
                        counts[workspace]["read_uncertain_files"] = len(uncertain_paths)
        return counts

    def docset_index(self, name: str, *, root: str) -> dict[str, Any]:
        """Index an offline library or API documentation directory under a named docset workspace."""
        clean_name = str(name or "").strip().lower().replace(" ", "_")
        if not clean_name:
            return {"success": False, "error": "docset name is required"}
        return self.index(root, workspace=f"docset:{clean_name}")

    def docset_search(self, name: str, *, query: str, top_k: int = 8, use_reranker: bool = True) -> dict[str, Any]:
        """Search an indexed offline library or API docset."""
        clean_name = str(name or "").strip().lower().replace(" ", "_")
        if not clean_name:
            return {"success": False, "error": "docset name is required"}
        return self.search(query, workspace=f"docset:{clean_name}", top_k=top_k, use_reranker=use_reranker)

    def _prepare_ingest_workspace(self, *, root: str, workspace: str) -> tuple[Path, str]:
        if type(root) is not str or not root or root != root.strip() or "\x00" in root:
            raise ValueError("RAG ingestion requires a canonical repository root")
        try:
            root_path = Path(root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("RAG ingestion root must be an existing repository directory") from exc
        if (
            not root_path.is_dir()
            or Path(root).is_symlink()
            or os.path.normcase(str(Path(root).absolute())) != os.path.normcase(str(root_path))
        ):
            raise ValueError("RAG ingestion root must be a real canonical directory")
        self.require_workspace_root(workspace=workspace, root=str(root_path))
        return root_path, workspace

    def _publish_ingest_workspace_binding(self, root: Path, workspace: str) -> None:
        project_context = self.project_context(root)
        self._sync_workspace_project_policy_identity(root, workspace, project_context)

    @staticmethod
    def _confined_diagram_path(root: Path, image_path: str) -> Path:
        if type(image_path) is not str or not image_path or image_path != image_path.strip() or "\x00" in image_path:
            raise ValueError("diagram image_path must be a canonical non-empty path")
        candidate = Path(image_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = Path(os.path.abspath(candidate))
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("diagram image must be inside the authorized repository root") from exc
        if not relative.parts:
            raise ValueError("diagram image path must identify a file inside the repository root")
        current = root
        final_stat: os.stat_result | None = None
        for part in relative.parts:
            current = current / part
            try:
                final_stat = current.lstat()
            except OSError as exc:
                raise ValueError("diagram image must exist inside the repository root") from exc
            if stat.S_ISLNK(final_stat.st_mode) or bool(
                getattr(final_stat, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("diagram image paths cannot contain symlinks or reparse points")
        if final_stat is None or not stat.S_ISREG(final_stat.st_mode):
            raise ValueError("diagram image path must identify a regular file")
        return candidate

    @staticmethod
    def _safe_open_diagram(root: Path, path: Path) -> tuple[int, os.stat_result]:
        try:
            parts = path.relative_to(root).parts
        except ValueError as exc:
            raise ValueError("diagram image must be inside the authorized repository root") from exc
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError("diagram image path must identify a file inside the repository root")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if os.name == "nt":
            # Windows' os.open follows junctions. Validate the final name of the
            # opened handle before reading; a path-based recheck can race again.
            fd = os.open(path, flags)
        else:
            if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                    or not hasattr(os, "O_NONBLOCK") or os.open not in os.supports_dir_fd):
                raise ValueError("secure diagram path traversal is unavailable")
            directory_fd = os.open(root, flags | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in parts[:-1]:
                    next_fd = os.open(part, flags | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = next_fd
                # An attacker can replace the checked regular file with a FIFO;
                # do not block waiting for its writer before fstat rejects it.
                fd = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            finally:
                os.close(directory_fd)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400):
                raise ValueError("diagram image path must identify a regular file without symlinks or reparse points")
            if os.name == "nt":
                import ctypes
                import msvcrt
                from ctypes import wintypes

                get_final = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
                get_final.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
                get_final.restype = wintypes.DWORD
                buffer = ctypes.create_unicode_buffer(32768)
                length = get_final(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
                if not length or length >= len(buffer):
                    raise ValueError("cannot verify opened diagram path")
                actual = buffer.value
                if actual.startswith("\\\\?\\UNC\\"):
                    actual = "\\\\" + actual[8:]
                elif actual.startswith("\\\\?\\"):
                    actual = actual[4:]
                if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(os.path.normpath(str(path))):
                    raise ValueError("opened diagram path differs from authorized path")
            return fd, st
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    def ingest_document(
        self,
        *,
        root: str,
        workspace: str,
        content: str,
        title: str = "",
        metadata: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
        """Ingest raw document or specification content into a RAG workspace."""
        try:
            _root_path, clean_ws = self._prepare_ingest_workspace(
                root=root, workspace=workspace
            )
        except Exception as exc:
            return {"success": False, "workspace": workspace, "error": str(exc)}
        raw_text = str(content or "")
        rag_cfg = self.config.get("rag", {})
        max_bytes = max(0, int(rag_cfg.get("max_file_bytes", 2_000_000)))
        content_bytes = len(raw_text.encode("utf-8"))
        if content_bytes > max_bytes:
            return {
                "success": False,
                "error": "document content exceeds configured file size limit",
                "content_bytes": content_bytes,
                "max_file_bytes": max_bytes,
            }
        clean_text = raw_text.strip()
        if not clean_text:
            return {"success": False, "error": "content is required"}

        doc_metadata = metadata if isinstance(metadata, dict) else {}
        doc_title = str(title or "").strip() or str(doc_metadata.get("title") or "").strip() or f"doc_{_fragment_hash(clean_text)[:8]}"
        doc_path = f"doc:{doc_title}"

        index_parts = [f"Title: {doc_title}"]
        if doc_metadata:
            index_parts.append(f"Metadata: {json_dumps(doc_metadata, sort_keys=True, default=str)}")
        index_parts.append(f"Content:\n{clean_text}")
        indexed_bytes = sum(len(part.encode("utf-8")) for part in index_parts) + len(index_parts) - 1
        if indexed_bytes > max_bytes:
            return {
                "success": False,
                "error": "indexed document exceeds configured file size limit",
                "indexed_bytes": indexed_bytes,
                "max_file_bytes": max_bytes,
            }
        indexed_text = "\n".join(index_parts)

        raw_chunks = self._text_chunks(indexed_text, size=1000, overlap=100)
        if not raw_chunks:
            raw_chunks = [indexed_text[:1000]]

        records: list[dict[str, Any]] = []
        for i, ch_text in enumerate(raw_chunks):
            records.append({
                "chunk_no": i,
                "text": ch_text,
                "hash": _fragment_hash(ch_text),
                "embedding": None,
                "embedding_space": "",
            })

        try:
            self._publish_ingest_workspace_binding(_root_path, clean_ws)
        except Exception as exc:
            return {"success": False, "workspace": clean_ws, "error": str(exc)}

        if self.services is not None:
            for offset in range(0, len(records), _INDEX_EMBED_BATCH_SIZE):
                batch_records = records[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                try:
                    vec_res = self.services.embed(
                        [record["text"] for record in batch_records],
                        priority=2,
                        query=False,
                    )
                    if not isinstance(vec_res, dict) or not vec_res.get("success"):
                        break
                    vectors = vec_res.get("embeddings", [])
                    if len(vectors) > len(batch_records):
                        break
                    embedding_space = self._embedding_space_id(vec_res)
                    for record, vector in zip(batch_records, vectors):
                        embedding = _serialize_embedding(vector)
                        if embedding is not None:
                            record["embedding"] = embedding
                            record["embedding_space"] = embedding_space
                    if len(vectors) < len(batch_records):
                        break
                except Exception:
                    break

        for r in records:
            if r["embedding"] is None:
                r["embedding"] = ""

        def publish_document() -> None:
            with self._get_workspace_lock(clean_ws), closing(self._connect()) as con, write_transaction(
                con, max_duration_seconds=5.0, rollback_label="RAG document publish"
            ):
                con.execute("DELETE FROM chunks WHERE workspace=? AND path=?", (clean_ws, doc_path))
                con.execute("DELETE FROM files WHERE workspace=? AND path=?", (clean_ws, doc_path))
                fts_exists = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                ).fetchone()
                if fts_exists:
                    con.execute("DELETE FROM chunk_fts WHERE workspace=? AND path=?", (clean_ws, doc_path))

                now_ns = time.time_ns()
                con.execute(
                    "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
                    (clean_ws, doc_path, now_ns, len(indexed_text.encode("utf-8")), _fragment_hash(indexed_text)),
                )
                con.executemany(
                    "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
                    [(clean_ws, doc_path, r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"]) for r in records],
                )
                if fts_exists:
                    con.executemany(
                        "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
                        [(clean_ws, doc_path, r["chunk_no"], r["text"]) for r in records],
                    )

        try:
            retry_busy(
                publish_document,
                retries=self._sqlite_write_retries,
                base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
            )
        except Exception as exc:
            return {
                "success": False,
                "workspace": clean_ws,
                "document_title": doc_title,
                "error": "ingest_publish_failed",
                "detail": str(exc),
                "retryable": is_busy_error(exc),
            }

        embedded_chunks = sum(bool(r["embedding_space"]) for r in records)
        embedded = embedded_chunks == len(records)
        return {
            "success": True,
            "workspace": clean_ws,
            "document_title": doc_title,
            "chunks_ingested": len(records),
            "embedded": embedded,
            "embedded_chunks": embedded_chunks,
            "embedding_status": "embedded" if embedded else "degraded",
            "degraded": not embedded,
        }

    def ingest_diagram(
        self,
        *,
        root: str,
        workspace: str,
        image_path: str,
        caption: str = "",
        metadata: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
        """Ingest architectural diagram, flowchart, or visual asset into RAG workspace."""
        if metadata is not None and not isinstance(metadata, dict):
            return {"success": False, "error": "diagram metadata must be an object", "diagram_indexed": False}
        reserved = {"type", "format", "image_path", "root", "workspace", "source", "diagram_content_mode", "vision_or_ocr_used"}
        if reserved.intersection(metadata or {}):
            return {"success": False, "error": "diagram metadata contains reserved provenance keys", "diagram_indexed": False}
        try:
            root_path, clean_ws = self._prepare_ingest_workspace(
                root=root, workspace=workspace
            )
            p_img = self._confined_diagram_path(root_path, image_path)
        except Exception as exc:
            return {"success": False, "workspace": workspace, "error": str(exc)}

        suffix = p_img.suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp"):
            return {"success": False, "error": f"unsupported diagram format: {suffix}"}

        doc_title = f"diagram_{p_img.stem}_{_fragment_hash(str(p_img))[:16]}"

        diagram_text = ""
        svg_text_nodes: list[str] = []
        if suffix == ".svg":
            try:
                rag_cfg = self.config.get("rag", {})
                max_bytes = max(0, int(rag_cfg.get("max_file_bytes", 2_000_000)))
                fd, st = self._safe_open_diagram(root_path, p_img)
                try:
                    svg_file = open(fd, "rb")
                except BaseException:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
                with svg_file:
                    if int(st.st_size) > max_bytes:
                        return {
                            "success": False,
                            "error": "diagram exceeds configured file size limit",
                            "diagram_indexed": False,
                        }
                    raw_bytes = svg_file.read(max_bytes + 1)
                if len(raw_bytes) > max_bytes:
                    return {
                        "success": False,
                        "error": "diagram exceeds configured file size limit",
                        "diagram_indexed": False,
                    }
                raw_svg = raw_bytes.decode("utf-8", errors="replace")
                texts = re.findall(r"<text[^>]*>(.*?)</text>", raw_svg, re.DOTALL | re.I)
                svg_text_nodes = [t.strip() for t in texts if t.strip()]
                diagram_text = f"SVG Diagram: {p_img.name}\nCaption: {caption}\nText nodes:\n" + "\n".join(svg_text_nodes)
            except Exception as exc:
                return {
                    "success": False,
                    "error": str(exc) if "symlink" in str(exc).lower() or "regular file" in str(exc).lower() else "diagram could not be read",
                    "diagram_indexed": False,
                }
        else:
            try:
                fd, st = self._safe_open_diagram(root_path, p_img)
                os.close(fd)
                file_size_kb = round(st.st_size / 1024, 1)
            except Exception as exc:
                return {"success": False, "error": str(exc), "diagram_indexed": False}
            diagram_text = f"Architectural Diagram / Visual Asset: {p_img.name}\nFormat: {suffix.lstrip('.')}\nSize: {file_size_kb} KB\nCaption: {caption}\nFile path: {str(p_img)}"

        res = self.ingest_document(
            root=str(root_path),
            workspace=clean_ws,
            content=diagram_text,
            title=doc_title,
            metadata={"type": "diagram", "format": suffix, "image_path": str(p_img), **(metadata or {})},
        )
        if isinstance(res, dict):
            res["diagram_indexed"] = bool(res.get("success"))
            res["image_path"] = str(p_img)
            res["diagram_content_mode"] = "svg_text_nodes" if svg_text_nodes else "metadata_only"
            res["vision_or_ocr_used"] = False
        return res

