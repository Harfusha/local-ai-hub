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


def test_adaptive_context_uses_current_fast_fallback_after_stale_hybrid_result(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    received_budgets = []

    class Deterministic:
        def context_pack(self, root, query, *, max_chars, max_raw_evidence):
            received_budgets.append(max_chars)
            return {
                "success": True,
                "context": "current deterministic context",
                "evidence": [{"path": "current.py", "text": "current source"}],
            }

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"features": {"rag": False}, "deterministic": {}}
    service.deterministic = Deterministic()
    service.rag = None
    cache_keys = []

    def repo_cached(key, root, params, compute):
        cache_keys.append(key)
        if key == "hybrid-context":
            return {
                "success": False,
                "stale": True,
                "error": "context source evidence is stale or cannot be verified",
                "context": "",
                "evidence": [],
            }
        return compute()

    service._repo_cached = repo_cached
    service._hybrid_context_uncached = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("stale hybrid result must not be recomputed here")
    )

    result = service._hybrid_context(
        str(root),
        "inspect context cache",
        workspace=None,
        max_tokens=256,
        quality_first=True,
        context_identity={"project_config_digest": "fixture"},
    )

    assert result["success"] is True
    assert result["context"] == "current deterministic context"
    assert result["context_source"] == "deterministic-fast-fallback"
    assert result["degraded"] is True
    assert result["degraded_reason"] == "adaptive_stale_evidence"
    assert result["fallback_from"] == "adaptive-hybrid"
    assert result.get("stale") is not True
    assert received_budgets == [1024]
    assert cache_keys == ["hybrid-context", "fast-context"]


def test_adaptive_context_keeps_stale_error_when_fast_fallback_is_not_current(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    class Deterministic:
        def context_pack(self, root, query, *, max_chars, max_raw_evidence):
            return {"success": False, "stale": True, "context": "old", "evidence": []}

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"features": {"rag": False}, "deterministic": {}}
    service.deterministic = Deterministic()
    service.rag = None

    def repo_cached(key, root, params, compute):
        if key == "hybrid-context":
            return {
                "success": False,
                "stale": True,
                "error": "context source evidence is stale or cannot be verified",
                "context": "",
                "evidence": [],
            }
        return compute()

    service._repo_cached = repo_cached
    service._hybrid_context_uncached = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("stale hybrid result must not be recomputed here")
    )

    result = service._hybrid_context(
        str(root),
        "inspect context cache",
        workspace=None,
        max_tokens=256,
        quality_first=True,
        context_identity={"project_config_digest": "fixture"},
    )

    assert result["success"] is False
    assert result["stale"] is True
    assert result["context"] == ""


def test_adaptive_context_falls_back_when_backend_deadline_returns_empty_pack(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    class Deterministic:
        def context_pack(self, root, query, *, max_chars, max_raw_evidence):
            return {
                "success": True,
                "context": "current deterministic context",
                "evidence": [{"path": "current.py", "text": "current source"}],
            }

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"features": {"rag": False}, "deterministic": {}}
    service.deterministic = Deterministic()
    service.rag = None
    cache_keys = []

    def repo_cached(key, root, params, compute):
        cache_keys.append(key)
        if key == "hybrid-context":
            return {
                "success": True,
                "context": "",
                "evidence": [],
                "retrieval": {"backend_selection": {"decision": "deadline_exhausted"}},
            }
        return compute()

    service._repo_cached = repo_cached
    service._hybrid_context_uncached = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("cached deadline result must not be recomputed here")
    )

    result = service._hybrid_context(
        str(root),
        "inspect context cache",
        workspace=None,
        max_tokens=256,
        quality_first=True,
        context_identity={"project_config_digest": "fixture"},
    )

    assert result["success"] is True
    assert result["context"] == "current deterministic context"
    assert result["context_source"] == "deterministic-fast-fallback"
    assert result["degraded_reason"] == "adaptive_deadline_empty"
    assert cache_keys == ["hybrid-context", "fast-context"]


def test_adaptive_context_falls_back_when_optional_backends_return_no_evidence(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    class Deterministic:
        def context_pack(self, root, query, *, max_chars, max_raw_evidence):
            return {
                "success": True,
                "context": "current deterministic context",
                "evidence": [{"path": "current.py", "text": "current source"}],
            }

    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"features": {"rag": False}, "deterministic": {}}
    service.deterministic = Deterministic()
    service.rag = None

    def repo_cached(key, root, params, compute):
        if key == "hybrid-context":
            return {
                "success": True,
                "context": "",
                "evidence": [],
                "retrieval": {"backend_selection": {"decision": "optional_backends_selected"}},
            }
        return compute()

    service._repo_cached = repo_cached
    service._hybrid_context_uncached = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("cached empty result must not be recomputed here")
    )

    result = service._hybrid_context(
        str(root),
        "inspect context cache",
        workspace=None,
        max_tokens=256,
        quality_first=True,
        context_identity={"project_config_digest": "fixture"},
    )

    assert result["success"] is True
    assert result["context"] == "current deterministic context"
    assert result["context_source"] == "deterministic-fast-fallback"
    assert result["degraded_reason"] == "adaptive_optional_empty"
