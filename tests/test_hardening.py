from __future__ import annotations

import json
import subprocess
from contextlib import closing

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def _config(tmp_path):
    return {
        "server": {"state_dir": str(tmp_path)},
        "features": {"rag": True},
        "models": {"embedding": "qwen3-embedding:0.6b", "embedding_backend": "auto"},
        "dependency_audit": {"osv_enabled": True, "osv_timeout_seconds": 1},
    }


def test_osv_audit_reports_live_advisory(tmp_path, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return json.dumps({"results": [{"vulns": [{"id": "OSV-1", "summary": "test advisory", "database_specific": {"severity": "HIGH"}}]}]}).encode()

    engine = DeterministicEngine(_config(tmp_path), None, None)
    root = tmp_path / "repo"
    root.mkdir()
    with closing(engine._connect()) as con:
        con.execute("INSERT INTO dependencies(root,source,name,version,scope) VALUES(?,?,?,?,?)", (str(root.resolve()), "requirements.txt", "requests", "2.0.0", ""))
        con.commit()
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())

    result = engine.audit_dependencies(str(root))

    assert result["advisory_data_current"] is True
    assert result["vulnerabilities"][0]["advisory"] == "OSV-1: test advisory"


def test_git_blob_hash_reuses_clean_tracked_content(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("value = 1\n", encoding="utf-8")
    for command in (["git", "init"], ["git", "add", "a.py"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)

    hashes = RepositoryTools(_config(tmp_path)).git_blob_hashes(str(root), ["a.py"])

    assert hashes["a.py"].startswith("git:")


def test_embedding_cache_stores_identity_and_dimension(tmp_path):
    class Cache:
        def __init__(self): self.writes = []
        def get(self, _key): return None
        def set(self, key, value): self.writes.append((key, value))

    model = EmbeddingModel(_config(tmp_path))
    cache = Cache()
    model.cache = cache
    model._encode_ollama = lambda texts: [[1.0, 2.0] for _ in texts]

    model.encode(["same text"])

    assert cache.writes[0][1]["identity"] == "ollama:qwen3-embedding:0.6b"
    assert cache.writes[0][1]["dimension"] == 2


def test_patch_validation_checks_explicit_git_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("actual\n", encoding="utf-8")
    for command in (["git", "init"], ["git", "add", "a.txt"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-missing\n+replacement\n"

    result = LocalAIServices.validate_patch(None, {"patch": patch, "root": str(root)}, "test")

    assert result["success"] is False
    assert result["applicability_checked"] is True
