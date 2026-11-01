from types import SimpleNamespace

from local_ai_hub.services import LocalAIServices
from local_ai_hub.work_orchestrator import WorkOrchestrator, _work_edit_context


def _service():
    service = object.__new__(LocalAIServices)
    service.config = {"workflow": {"fast_repo_context_tokens": 2200}}
    service.router = SimpleNamespace(classify=lambda *_args: {"complexity": "simple"})
    service._hybrid_context = lambda root, task, **kwargs: {
        "success": True, "root": root, "context": "retrieved repository evidence",
        "evidence": [], "estimated_tokens": 7,
    }
    calls = []
    service.delegate = lambda payload, **kwargs: calls.append(payload) or {"success": True, "text": "ok"}
    return service, calls


def test_delegate_repo_preserves_work_context_and_retrieved_evidence():
    service, calls = _service()
    result = service.delegate_repo({"root": "C:/repo", "task": "make bounded patch",
                                    "context": "specific source and prior validation"})
    assert result["success"] is True
    assert "specific source and prior validation" in calls[0]["context"]
    assert "retrieved repository evidence" in calls[0]["context"]
    assert calls[0]["task"] == "make bounded patch"
    assert calls[0]["root"] == "C:/repo"


def test_delegate_repo_rejects_non_string_context_before_model_call():
    service, calls = _service()
    result = service.delegate_repo({"root": "C:/repo", "task": "change", "context": {"unexpected": 1}})
    assert result["success"] is False
    assert not calls


def test_work_ask_passes_bounded_evidence_through_delegate_repo():
    service, calls = _service()
    worker = object.__new__(WorkOrchestrator)
    worker.services = service
    evidence = "prefix-" + "x" * 15980 + "-suffix"
    result = worker._ask("C:/repo", "implement the task", evidence, 1200)
    assert result["success"] is True
    assert evidence in calls[0]["context"]
    assert "retrieved repository evidence" in calls[0]["context"]


def test_delegate_repo_without_supplied_context_keeps_existing_payload():
    service, calls = _service()
    result = service.delegate_repo({"root": "C:/repo", "task": "change"})
    assert result["success"] is True
    assert calls[0]["context"] == "retrieved repository evidence"


def test_isolated_work_context_reaches_model_prompt(tmp_path, monkeypatch):
    import json
    from local_ai_hub.app import LocalAIApp

    cfg = tmp_path / "isolated.toml"
    cfg.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(tmp_path)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(cfg))
    try:
        monkeypatch.setattr(app.services, "_hybrid_context", lambda root, task, **kwargs: {
            "success": True, "root": root, "context": "retrieved FACT-ALPHA", "evidence": [],
        })
        captured = []
        monkeypatch.setattr(app.services, "_generate", lambda model, prompt, system, *args, **kwargs:
                            captured.append((prompt, system)) or {"success": True, "text": "ok"})
        original_resolver = app.services._resolve_local_task_project
        resolved_roots = []
        def resolve(root):
            resolved_roots.append(root)
            return original_resolver(root)
        monkeypatch.setattr(app.services, "_resolve_local_task_project", resolve)
        result = app.work_orchestrator._ask(str(tmp_path), "implement bounded change", "work FACT-BETA", 500)
        assert result["success"] is True
        assert "work FACT-BETA" in captured[0][0]
        assert "retrieved FACT-ALPHA" in captured[0][0]
        assert resolved_roots == [str(tmp_path)]
    finally:
        app.close()


def test_bounded_edit_receives_prior_inspect_evidence(tmp_path):
    from test_work_orchestrator import FakeArtifacts, FakeLeases, FakeServices, config, init_repo, wait_terminal

    class Services(FakeServices):
        def deterministic_query(self, root, query, limit=24):
            return {"success": True, "facts": ["inspection FACT-ONE"]}

        def code_query(self, root, query, limit=20):
            return {"success": True, "symbols": ["inspection FACT-TWO"]}

        def fast_context(self, root, query, max_tokens):
            return {"success": True, "evidence": ["edit FACT-THREE"]}

        def delegate_repo(self, args, **kwargs):
            return super().delegate_repo(args)

        def second_opinion(self, args, **kwargs):
            return super().second_opinion(args)

    root = init_repo(tmp_path)
    services = Services("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n")
    wo = WorkOrchestrator(config(tmp_path), tmp_path / "state", services, None,
                          FakeLeases(), FakeArtifacts())
    try:
        submitted = wo.submit({
            "root": str(root), "task": "replace old with new", "mode": "bounded",
            "acceptance_criteria": ["a.txt contains new"], "allowed_paths": ["a.txt"],
            "approved_commands": ["git diff --check"], "budget": {"max_steps": 8, "max_seconds": 60},
            "permissions": {"edit": True, "tests": True, "build": True},
        })
        result = wait_terminal(wo, submitted["work_id"], timeout=20)
        assert result["status"] == "needs_agent", result
        context = services.delegate_requests[1]["context"]
        assert "inspection FACT-ONE" in context
        assert "inspection FACT-TWO" in context
        assert "edit FACT-THREE" in context
    finally:
        wo.close()


def test_edit_context_marks_stale_and_truncated_inspection_evidence():
    context = _work_edit_context(
        {"text": "fresh FAST" + "x" * 20000},
        [{"kind": "inspect", "success": True, "generation": 0,
          "task": "old inspection", "evidence": "old FACT" + "y" * 20000}],
        generation=1,
    )
    assert len(context) < 16000
    assert '"stale":true' in context
    assert "old FACT" in context and "fresh FAST" in context
    assert context.count("[truncated]") == 2
