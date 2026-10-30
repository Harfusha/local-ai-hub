"""Build and verify a nonempty RAG upgrade in case-096's disposable sandbox.

Run ``seed`` with the old sandbox venv, then ``upgrade`` with the candidate venv.
This creates fixture observations only; it does not create Agent OS receipts.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

from local_ai_hub import __version__
from local_ai_hub.config import load_config
from local_ai_hub.rag import RAGStore


SPACE_ID = "case-096-deterministic-fixture-embedding-v1"
WORKSPACE_ID = "case-096-nonempty-rag"
SOURCE_NAME = "rag-source.md"
SOURCE_TEXT = (
    "Local AI Hub case 096 nonempty RAG fixture. "
    "This isolated source proves a real file and chunk were indexed before upgrade. "
    "The test embedding is deterministic fixture data and says nothing about model quality.\n"
) * 8


class FixtureEmbeddings:
    space_id = SPACE_ID

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str], **kwargs: object) -> dict:
        if set(kwargs) - {"priority", "query", "background"}:
            raise TypeError("unexpected fixture embedding option")
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([
                digest[index % len(digest)] / 127.5 - 1.0
                for index in range(self.dimension)
            ])
        return {
            "success": True,
            "embeddings": vectors,
            "embedding_space_id": SPACE_ID,
            "embedding_dimension": self.dimension,
            "backend": "fixture",
            "model": "deterministic-nonsemantic",
            "normalized": False,
        }


def _sandbox(raw: str) -> Path:
    root = Path(raw).resolve(strict=True)
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or Path.home()).resolve()
    if root == temp or not root.is_relative_to(temp):
        raise ValueError("sandbox must be a disposable child of the system temp directory")
    if not (root / "wheel_manifest.json").is_file():
        raise ValueError("sandbox must come from prepare_wheels.py")
    return root


def _child(root: Path, name: str) -> Path:
    path = root / name
    if path.is_symlink():
        raise ValueError(f"sandbox child cannot be a symlink: {name}")
    if path.exists() and path.resolve().parent != root:
        raise ValueError(f"sandbox child escaped its root: {name}")
    return path


def _dimension(config: dict) -> int:
    models = config.get("models", {})
    cpu = config.get("cpu_retrieval", {})
    value = models.get("embedding_dimension") or cpu.get("embedding_dimension") or 384
    dimension = int(value)
    if not 1 <= dimension <= 8192:
        raise ValueError("fixture embedding dimension is outside the supported bound")
    return dimension


def _config(state: Path) -> dict:
    config = load_config()
    config["server"]["state_dir"] = str(state)
    return config


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rag_snapshot(state: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("rag.sqlite3", "rag.sqlite3-wal", "rag.sqlite3-shm"):
        path = state / name
        if path.is_symlink():
            raise ValueError(f"RAG database component cannot be a symlink: {name}")
        if path.is_file():
            result[name] = _sha256(path)
    if "rag.sqlite3" not in result:
        raise RuntimeError("RAG database is missing")
    return result


def _verify_index(state: Path, source: Path, fingerprint: str) -> dict:
    db = state / "rag.sqlite3"
    uri = db.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2.0)) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        rows = con.execute(
            "SELECT workspace,path,content_hash FROM files ORDER BY workspace,path"
        ).fetchall()
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        owners = con.execute("SELECT COUNT(*) FROM project_file_owners").fetchone()[0]
        stored = con.execute(
            "SELECT value FROM rag_meta WHERE key='index_fingerprint'"
        ).fetchone()
    expected_source_hash = hashlib.sha1(source.read_bytes()).hexdigest()
    if (
        integrity != "ok"
        or len(rows) != 1
        or rows[0][0] != WORKSPACE_ID
        or rows[0][1] != SOURCE_NAME
        or rows[0][2] != expected_source_hash
        or chunks < 1
        or owners != 1
        or stored is None
        or stored[0] != fingerprint
    ):
        raise RuntimeError("rebuilt RAG index did not pass content and integrity checks")
    return {
        "integrity": integrity,
        "files": len(rows),
        "chunks": chunks,
        "owners": owners,
        "content_sha1": expected_source_hash,
        "fingerprint": stored[0],
    }


def seed(raw_root: str) -> None:
    root = _sandbox(raw_root)
    if Path(sys.prefix).resolve() != _child(root, "before-venv").resolve():
        raise RuntimeError("seed must use the old-version sandbox venv")
    workspace = _child(root, "workspace")
    state = _child(root, "state")
    manifest_path = _child(root, "nonempty-rag-seed-manifest.json")
    if workspace.exists() or state.exists() or manifest_path.exists():
        raise FileExistsError("nonempty RAG seed refuses to overwrite an existing sandbox")
    workspace.mkdir()
    state.mkdir()
    source = workspace / SOURCE_NAME
    with source.open("x", encoding="utf-8", newline="\n") as output:
        output.write(SOURCE_TEXT)
    config = _config(state)
    store = RAGStore(config, services=FixtureEmbeddings(_dimension(config)))
    result = store.index_paths_step(
        str(workspace), workspace=WORKSPACE_ID, paths=[SOURCE_NAME]
    )
    if result.get("success") is not True or int(result.get("embedded_chunks", 0)) < 1:
        raise RuntimeError(f"old-version RAG seed failed: {result}")
    verified = _verify_index(state, source, store.index_fingerprint)
    manifest = {
        "schema_version": 1,
        "fixture": "case-096-nonempty-rag",
        "package_version": __version__,
        "workspace": str(workspace),
        "state": str(state),
        "source": SOURCE_NAME,
        "source_sha256": _sha256(source),
        "index": verified,
        "rag_files": _rag_snapshot(state),
        "runtime_acceptance": False,
        "synthetic_receipt": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)


def _wait_for_mismatch(root: Path, state: Path) -> tuple[str, bool, bool]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    token = "case096-" + hashlib.sha256(os.urandom(32)).hexdigest()
    config_path = root / f"mismatch-{port}.toml"
    supervisor_output = root / f"mismatch-{port}.log"
    if config_path.exists() or supervisor_output.exists():
        raise FileExistsError("mismatch startup evidence already exists")
    with config_path.open("x", encoding="utf-8") as output:
        output.write(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        f"port = {port}\n"
        f"state_dir = {json.dumps(str(state))}\n"
        "auto_start_ollama = false\n"
        "[security]\n"
        f"api_token = {json.dumps(token)}\n"
        "[ollama]\nenabled = false\n"
        "[llama_cpp]\nenabled = false\n"
        "[code_intelligence]\nenabled = false\nserena_enabled = false\n"
        "preprocess_serena = false\n[headless]\nmanage_ollama = false\n"
        "[resilience]\nwatchdog_enabled = false\n"
        f"[setup]\ninstall_dir = {json.dumps(str(root / 'install'))}\n",
        )
    from local_ai_hub.process_utils import popen_managed, terminate_tree

    stderr_log = state / "logs" / "hub_stderr.log"
    prior_size = stderr_log.stat().st_size if stderr_log.is_file() else 0
    with supervisor_output.open("xb") as log:
        process = popen_managed(
            [sys.executable, "-m", "local_ai_hub.supervisor", "--config", str(config_path)],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        found = False
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if stderr_log.exists():
                    size = stderr_log.stat().st_size
                    start = prior_size if size >= prior_size else 0
                    with stderr_log.open("rb") as source_log:
                        source_log.seek(max(start, size - 32768))
                        if b"RAG database has fingerprint mismatch" in source_log.read():
                            found = True
                            break
                if process.poll() is not None:
                    break
                time.sleep(0.2)
        finally:
            terminated = terminate_tree(process.pid, process_handle=process, grace_seconds=3)
    return str(stderr_log), found, bool(terminated)


def upgrade(raw_root: str, expected_version: str) -> None:
    root = _sandbox(raw_root)
    if Path(sys.prefix).resolve() != _child(root, "venv").resolve():
        raise RuntimeError("upgrade must use the candidate sandbox venv")
    if __version__ != expected_version:
        raise RuntimeError(f"candidate version mismatch: {__version__} != {expected_version}")
    manifest_path = _child(root, "nonempty-rag-seed-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package_version") == __version__:
        raise RuntimeError("old and candidate package versions must differ")
    workspace = _child(root, "workspace")
    state = _child(root, "state")
    rebuilt = _child(root, "state-rebuilt")
    archive = _child(root, "state-before-offline-rebuild")
    source = workspace / SOURCE_NAME
    if not source.is_file() or _sha256(source) != manifest.get("source_sha256"):
        raise RuntimeError("authorized sandbox source changed after old-version indexing")
    before = _rag_snapshot(state)
    if before != manifest.get("rag_files"):
        raise RuntimeError("old RAG DB or sidecar changed after seed evidence was recorded")

    log_path, mismatch_seen, process_tree_terminated = _wait_for_mismatch(root, state)
    after_rejection = _rag_snapshot(state)
    if not mismatch_seen or not process_tree_terminated or after_rejection != before:
        raise RuntimeError("candidate startup did not fail closed with byte-preserved RAG state")
    if rebuilt.exists() or archive.exists():
        raise FileExistsError("offline rebuild refuses pre-existing output directories")

    rebuilt.mkdir()
    config = _config(rebuilt)
    store = RAGStore(config, services=FixtureEmbeddings(_dimension(config)))
    result = store.index_paths_step(
        str(workspace), workspace=WORKSPACE_ID, paths=[SOURCE_NAME]
    )
    if result.get("success") is not True or int(result.get("embedded_chunks", 0)) < 1:
        raise RuntimeError(f"explicit candidate rebuild failed: {result}")
    rebuilt_index = _verify_index(rebuilt, source, store.index_fingerprint)
    if rebuilt_index["fingerprint"] == manifest["index"]["fingerprint"]:
        raise RuntimeError("old and candidate RAG fingerprints unexpectedly match")

    state.rename(archive)
    try:
        rebuilt.rename(state)
    except Exception:
        archive.rename(state)
        raise
    if _rag_snapshot(archive) != before:
        raise RuntimeError("archived pre-upgrade RAG bytes changed during rebuild")
    final_index = _verify_index(state, source, store.index_fingerprint)
    evidence = {
        "schema_version": 1,
        "fixture": "case-096-nonempty-rag-upgrade",
        "before_version": manifest["package_version"],
        "candidate_version": __version__,
        "old_fingerprint": manifest["index"]["fingerprint"],
        "candidate_fingerprint": final_index["fingerprint"],
        "startup_rejection": "RAG database has fingerprint mismatch",
        "rejection_log": str(Path(log_path).relative_to(root)),
        "pre_rejection_rag_files": before,
        "post_rejection_rag_files": after_rejection,
        "archived_rag_files": _rag_snapshot(archive),
        "rebuilt_index": final_index,
        "runtime_acceptance": False,
        "synthetic_receipt": False,
    }
    output = _child(root, "nonempty-rag-upgrade-observation.json")
    if output.exists():
        raise FileExistsError("upgrade observation already exists")
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(evidence, indent=2) + "\n")
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("sandbox")
    upgrade_parser = sub.add_parser("upgrade")
    upgrade_parser.add_argument("sandbox")
    upgrade_parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    if args.action == "seed":
        seed(args.sandbox)
    else:
        upgrade(args.sandbox, args.expected_version)


if __name__ == "__main__":
    main()
