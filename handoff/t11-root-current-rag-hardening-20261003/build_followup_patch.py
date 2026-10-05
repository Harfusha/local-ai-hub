from __future__ import annotations

import difflib
import hashlib
from pathlib import Path


ROOT = Path(r"C:\Users\Adam\.local-ai-hub")
PACKET_DIR = Path(__file__).parent


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def update_rag(source: str) -> str:
    rag = source

    rag = replace_once(
        rag,
        "_INDEX_EMBED_BATCH_SIZE = 64\n",
        "_INDEX_EMBED_BATCH_SIZE = 64\n_VECTOR_BATCH_MEMORY_BUDGET_BYTES = 16 * 1024 * 1024\n_MAX_VECTOR_BATCH_SIZE = 8192\n",
        "bounded vector batch constants",
    )

    rag = replace_once(
        rag,
        "            previous = con.execute(\"SELECT value FROM rag_meta WHERE key='index_fingerprint'\").fetchone()\n",
        "            fts_exists = con.execute(\n                \"SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'\"\n            ).fetchone() is not None\n            previous = con.execute(\"SELECT value FROM rag_meta WHERE key='index_fingerprint'\").fetchone()\n",
        "fingerprint FTS presence",
    )
    rag = replace_once(
        rag,
        "                    con.execute(\"DELETE FROM chunks\")\n                    con.execute(\"DELETE FROM files\")\n",
        "                    con.execute(\"DELETE FROM chunks\")\n                    con.execute(\"DELETE FROM files\")\n                    if fts_exists:\n                        con.execute(\"DELETE FROM chunk_fts\")\n",
        "initial fingerprint FTS reset",
    )
    rag = replace_once(
        rag,
        "                con.execute(\"DELETE FROM chunks\")\n                con.execute(\"DELETE FROM files\")\n            con.execute(\"INSERT OR REPLACE INTO rag_meta(key,value) VALUES('index_fingerprint',?)\", (current,))\n",
        "                con.execute(\"DELETE FROM chunks\")\n                con.execute(\"DELETE FROM files\")\n                if fts_exists:\n                    con.execute(\"DELETE FROM chunk_fts\")\n            con.execute(\"INSERT OR REPLACE INTO rag_meta(key,value) VALUES('index_fingerprint',?)\", (current,))\n",
        "changed fingerprint FTS reset",
    )

    rag = replace_once(
        rag,
        "        embedding_space = _space_override or self._embedding_space_id()\n\n        with closing(self._connect()) as con:\n            uncertain_retry_paths = self._workspace_read_uncertain_paths(con, scope_key, workspace)\n",
        "        configured_space = _space_override or self._embedding_space_id()\n        identity_resolved = _space_override is not None or self._embedding_space_is_resolved()\n\n        with closing(self._connect()) as con:\n            stored_space = self._stored_workspace_embedding_space(con, scope_key, workspace)\n            uncertain_retry_paths = self._workspace_read_uncertain_paths(con, scope_key, workspace)\n",
        "configured and persisted embedding identity",
    )
    rag = replace_once(
        rag,
        "        old_files = {r[0]: {\"mtime_ns\": int(r[1]), \"size\": int(r[2]), \"content_hash\": r[3]} for r in old_files_rows}\n        old_chunks = {\n            (r[0], int(r[1]), r[2]): r[3]\n            for r in old_chunk_rows\n            if embedding_space and str(r[4] or \"\").strip() == embedding_space\n        }\n        embedding_space_changed = any(\n            str(row[4] or \"\") != embedding_space for row in old_chunk_rows\n        )\n",
        "        old_space_counts: dict[str, int] = {}\n        for row in old_chunk_rows:\n            old_space_counts[str(row[4] or \"\")] = old_space_counts.get(str(row[4] or \"\"), 0) + 1\n        if stored_space is None and old_space_counts:\n            stored_space = sorted(old_space_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]\n        embedding_space = configured_space if identity_resolved else (stored_space or configured_space)\n        old_files = {r[0]: {\"mtime_ns\": int(r[1]), \"size\": int(r[2]), \"content_hash\": r[3]} for r in old_files_rows}\n        old_chunks = {\n            (r[0], int(r[1]), r[2]): r[3]\n            for r in old_chunk_rows\n            if embedding_space and str(r[4] or \"\").strip() == embedding_space\n        }\n        embedding_space_changed = any(\n            str(row[4] or \"\") != embedding_space for row in old_chunk_rows\n        )\n",
        "reuse unresolved persisted embedding identity",
    )
    rag = replace_once(
        rag,
        '            "workspace": workspace,\n            "files_root": str(root_path),\n',
        '            "workspace": workspace,\n            "embedding_space_id": embedding_space,\n            "embedding_space_resolved": bool(identity_resolved or observed_embedding_space or stored_space),\n            "files_root": str(root_path),\n',
        "full index identity result",
    )

    rag = rag.replace(
        'text = raw.decode("utf-8", errors="replace")',
        'text = _canonical_fragment_text(raw.decode("utf-8", errors="replace"))',
    )
    if rag.count('text = _canonical_fragment_text(raw.decode("utf-8", errors="replace"))') != 3:
        raise RuntimeError("canonicalize all three indexing entrypoints")
    rag = replace_once(
        rag,
        "                        text = str(override)\n",
        "                        text = _canonical_fragment_text(str(override))\n",
        "canonicalize incremental content override",
    )

    rag = replace_once(
        rag,
        "            if not file_data and not deleted_unique:\n                if read_uncertain_paths:\n                    with closing(self._connect()) as con:\n                        con.execute(\"BEGIN IMMEDIATE\")\n                        self._update_workspace_read_uncertainty(\n                            con, scope_key, workspace, uncertain_paths=read_uncertain_paths,\n                        )\n                        con.commit()\n",
        "            if not file_data and not deleted_unique:\n                if read_uncertain_paths:\n                    self._publish_workspace_read_uncertainty(\n                        scope_key, workspace, read_uncertain_paths\n                    )\n",
        "retry uncertain-only publish",
    )

    rag = replace_once(
        rag,
        '        except Exception as exc:\n            result = {"success": False, "error": str(exc), "retryable": True}\n',
        '        except Exception as exc:\n            result = {\n                "success": False, "error": str(exc),\n                "retryable": bool(getattr(exc, "retryable", is_busy_error(exc))),\n            }\n',
        "index failure retryability",
    )

    rag = replace_once(
        rag,
        '        batch_size = min(2048, max(32, int(rag_cfg.get("search_batch_size", 512))))\n',
        '        configured_batch_size = max(32, int(rag_cfg.get("search_batch_size", 512)))\n        batch_size = min(2048, configured_batch_size)\n',
        "configured vector batch size",
    )
    rag = replace_once(
        rag,
        "            dimension = int(q.size)\n            q_norm = float(np.linalg.norm(q))\n",
        "            dimension = int(q.size)\n            memory_batch_limit = _VECTOR_BATCH_MEMORY_BUDGET_BYTES // max(16, dimension * 16)\n            batch_size = min(_MAX_VECTOR_BATCH_SIZE, memory_batch_limit, configured_batch_size)\n            q_norm = float(np.linalg.norm(q))\n",
        "memory-bounded vector batch size",
    )
    rag = replace_once(
        rag,
        "                    norms = np.linalg.norm(matrix, axis=1)\n                    scores = np.zeros(len(batch), dtype=np.float32)\n                    valid = np.isfinite(norms) & (norms > 1e-9)\n                    if q_norm > 1e-9 and valid.any():\n                        dot_scores = np.dot(matrix, q)\n                        scores[valid] = dot_scores[valid] / norms[valid]\n                    scores = np.where(np.isfinite(scores), scores, 0.0)\n",
        "                    norms = np.linalg.norm(matrix, axis=1)\n                    valid = np.isfinite(norms) & (norms > 1e-9)\n                    if q_norm > 1e-9 and valid.any():\n                        scores = np.dot(matrix, q)\n                        np.divide(scores, norms, out=scores, where=valid)\n                        scores[~valid] = 0.0\n                    else:\n                        scores = norms\n                        scores.fill(0.0)\n                    np.nan_to_num(scores, copy=False, nan=0.0, posinf=0.0, neginf=0.0)\n",
        "reuse vector norm buffer for scores",
    )

    return rag


def update_hybrid_test(source: str) -> str:
    return replace_once(
        source,
        "from contextlib import closing\n",
        "from contextlib import closing\nfrom pathlib import Path\n",
        "Path import for policy stat regressions",
    )


def update_fragment_test(source: str) -> str:
    return replace_once(source, "import io\n", "import io\nimport os\n", "os import for same-stat dirty path")


def update_ingestion_test(source: str) -> str:
    source = replace_once(
        source,
        '    assert requests[0][1] == {\n        "workspace": "specs",\n        "content": "Explicit content",\n        "title": "Explicit title",\n        "metadata": {"owner": "team"},\n    }\n    assert requests[1][1] == {\n        "workspace": "diagrams",\n        "image_path": str(tmp_path / "diagram.png"),\n        "caption": "Explicit caption",\n        "metadata": {"owner": "team"},\n    }\n',
        '    rag_requests = [\n        payload for path, payload in requests\n        if path in {"/api/rag/ingest_document", "/api/rag/ingest_diagram"}\n    ]\n    assert rag_requests == [\n        {\n            "workspace": "specs",\n            "content": "Explicit content",\n            "title": "Explicit title",\n            "metadata": {"owner": "team"},\n        },\n        {\n            "workspace": "diagrams",\n            "image_path": str(tmp_path / "diagram.png"),\n            "caption": "Explicit caption",\n            "metadata": {"owner": "team"},\n        },\n    ]\n',
        "filter MCP telemetry while asserting explicit ingest fields",
    )
    source = replace_once(
        source,
        '    assert calls == [\n        (\n            "/api/rag/ingest_document",\n',
        '    rag_calls = [\n        (path, payload) for path, payload in calls\n        if path in {"/api/rag/ingest_document", "/api/rag/ingest_diagram"}\n    ]\n    assert rag_calls == [\n        (\n            "/api/rag/ingest_document",\n',
        "filter telemetry in explicit-fields-only assertion",
    )
    return source


def build() -> tuple[dict[str, bytes], dict[str, bytes], str]:
    relpaths = {
        "src/local_ai_hub/rag.py": update_rag,
        "tests/test_t11_rag_ingestion_contract.py": update_ingestion_test,
    }
    preimages: dict[str, bytes] = {}
    postimages: dict[str, bytes] = {}
    diffs: list[str] = []
    for rel, transform in relpaths.items():
        path = ROOT / rel
        preimage = path.read_bytes()
        text = normalize(preimage.decode("utf-8"))
        updated = transform(text)
        newline = "\r\n" if b"\r\n" in preimage else "\n"
        postimage = updated.replace("\n", newline).encode("utf-8")
        preimages[rel] = preimage
        postimages[rel] = postimage
        diffs.append(
            "diff --git a/" + rel + " b/" + rel + "\n"
            + "".join(difflib.unified_diff(
                text.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile="a/" + rel,
                tofile="b/" + rel,
                n=3,
            ))
        )
    return preimages, postimages, "".join(diffs)


def main() -> None:
    preimages, postimages, diff = build()
    patch_path = PACKET_DIR / "t11-root-current-followup-20261005.patch"
    post_dir = PACKET_DIR / "followup-postimages-20261005"
    for rel, data in postimages.items():
        target = post_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    patch_path.write_text(diff, encoding="utf-8", newline="")
    for rel, data in preimages.items():
        print(f"pre:{rel}={hashlib.sha256(data).hexdigest().upper()}")
    for rel, data in postimages.items():
        print(f"post:{rel}={hashlib.sha256(data).hexdigest().upper()}")
    print(f"patch_sha256={hashlib.sha256(patch_path.read_bytes()).hexdigest().upper()}")
    print(f"patch_bytes={patch_path.stat().st_size}")
    print(f"patch_path={patch_path}")


if __name__ == "__main__":
    main()
