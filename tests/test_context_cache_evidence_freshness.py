import hashlib
from pathlib import Path

from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.services import LocalAIServices


def _item(root: Path, store: EvidenceStore):
    path = root / "marker.txt"
    text = path.read_text(encoding="utf-8")
    evidence = {"path": "marker.txt", "text": text, "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "start_line": 1, "end_line": 1}
    return {"success": True, "context": text, "evidence": store.put_many(str(root), [evidence])}


def _service(tmp_path, cached):
    service = LocalAIServices.__new__(LocalAIServices)
    service._touch_project = lambda root: None
    service._repo_cache_state = lambda root: {"fingerprint": "stable", "kind": "fixture"}
    service.evidence_store = EvidenceStore(tmp_path / "state")

    class Flight:
        def get_or_compute(self, key, compute):
            return cached(), True, False

    service.repo_flight = Flight()
    return service


def test_changed_cached_evidence_recomputes_current_context(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    marker = root / "marker.txt"
    marker.write_text("old\n", encoding="utf-8")
    cached = []
    service = _service(tmp_path, lambda: cached[0])
    cached.append(_item(root, service.evidence_store))
    marker.write_text("new\n", encoding="utf-8")
    result = service._repo_cached("hybrid-context", str(root), {}, lambda: _item(root, service.evidence_store))
    assert result["success"] is True
    assert result["context"] == "new\n"
    assert result["cache_hit"] is False
    assert result["evidence"][0]["file_sha256"] == hashlib.sha256(marker.read_bytes()).hexdigest()


def test_still_stale_recomputation_does_not_return_old_context(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    marker = root / "marker.txt"
    marker.write_text("old\n", encoding="utf-8")
    cached = []
    service = _service(tmp_path, lambda: cached[0])
    cached.append(_item(root, service.evidence_store))
    marker.write_text("new\n", encoding="utf-8")
    result = service._repo_cached("hybrid-context", str(root), {}, lambda: cached[0])
    assert result["success"] is False
    assert result["stale"] is True
    assert "old" not in result.get("context", "")


def test_current_evidence_reuses_cache_without_recomputation(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "marker.txt").write_text("current\n", encoding="utf-8")
    cached = []
    service = _service(tmp_path, lambda: cached[0])
    cached.append(_item(root, service.evidence_store))
    result = service._repo_cached("hybrid-context", str(root), {}, lambda: (_ for _ in ()).throw(AssertionError("unneeded recomputation")))
    assert result["success"] is True
    assert result["cache_hit"] is True
