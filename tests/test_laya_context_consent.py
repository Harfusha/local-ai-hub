from __future__ import annotations

import threading
from concurrent.futures import Future
from types import SimpleNamespace

from local_ai_hub.app import LocalAIApp, _redact_laya_training_text
from local_ai_hub.laya_decisions import DecisionResult, DecisionStatus


def test_laya_training_text_redacts_common_credentials():
    value = (
        "Authorization: Bearer bearer-secret "
        "https://user:url-secret@example.test/path "
        "sk-proj-abcdefghijklmnopqrstuvwxyz123456 "
        "-----BEGIN PRIVATE KEY-----\nprivate-secret\n-----END PRIVATE KEY-----"
    )

    redacted = _redact_laya_training_text(value)

    for secret in ("bearer-secret", "url-secret", "sk-proj-", "private-secret"):
        assert secret not in redacted
    assert redacted.count("[REDACTED]") == 4




def test_evaluate_context_source_keeps_memory_ids_out_of_model_input(tmp_path, monkeypatch):
    from local_ai_hub import project_config

    app = LocalAIApp.__new__(LocalAIApp)
    app.config = {
        "laya": {"runtime": {"checkpoint_path": "pinned.gguf", "revision": "rev-1", "expected_sha256": {"pinned.gguf": "a" * 64}, "allow_cpu": False}},
        "server": {"state_dir": str(tmp_path / "state")},
    }
    task = SimpleNamespace(context={"session_id": "session-1"})
    app.agent_tasks = object()
    app.agent_memory = object()
    app.evidence = object()
    observed = {}
    app.laya_candidates = SimpleNamespace(
        _find_task=lambda *_args: task,
        _session_for_task=lambda value: value.context["session_id"],
        _candidate_input=lambda candidate: candidate,
        _validate_context_source_evidence=lambda candidate, **kwargs: observed.update(
            candidate=candidate, validation=kwargs,
        ),
        capture_runtime_outcome=lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        project_config,
        "resolve_project_context",
        lambda *_args: SimpleNamespace(coordination_id="repo-coordination-id"),
    )

    class Adapter:
        def evaluate_context_source(self, request, evidence, **_kwargs):
            observed["model_input"] = evidence.model_input()
            return SimpleNamespace(
                decision=DecisionResult(
                    request=request,
                    success=True,
                    status=DecisionStatus.SUCCESS,
                    suggestion=request.options[0],
                    reason_codes=(),
                ),
                runtime=None,
                capture_status="skipped",
            )

    app._get_laya_runtime_adapter = lambda *_args, **_kwargs: Adapter()
    app._record_laya_runtime_decision = lambda *_args: None
    app.laya_lifecycle = object()

    result = app.evaluate_laya_context_source(
        {
            "action": "evaluate_context_source",
            "task_id": "task-1",
            "session_id": "session-1",
            "evidence": {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "rag", "memory"],
                "freshness_codes": ["current", "current", "current"],
                "coverage_codes": ["partial", "partial", "partial"],
                "evidence_ids": ["ev-indexed", "ev-rag", "ev-memory"],
                "source_record_ids": [None, None, "mem-task"],
                "training_content": {"task_input": "Find missing evidence."},
            },
        },
        root=str(tmp_path), )

    assert result["success"] is True
    assert observed["candidate"]["source_record_ids"] == [None, None, "mem-task"]
    assert "source_record_ids" not in observed["candidate"]["state"]
    assert "source_record_ids" not in observed["model_input"]
    assert observed["validation"]["memory_store"] is app.agent_memory
    assert observed["validation"]["task_id"] == "task-1"
    assert observed["validation"]["session_id"] == "session-1"
    assert observed["validation"]["coordination_id"] == "repo-coordination-id"
