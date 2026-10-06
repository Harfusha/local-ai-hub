from __future__ import annotations

from hashlib import sha256

from local_ai_hub.response_budget import budget_response
from local_ai_hub.token_accounting import json_tokens


def _large_result() -> dict[str, object]:
    return {
        "success": True,
        "status": "ok",
        "summary": "Decision-grade summary",
        "artifact_id": "artifact-123",
        "evidence_ids": ["E1", "E2"],
        "changed_paths": ["src/a.py"],
        "text": "line\n" * 500,
        "results": [{"path": f"src/{i}.py", "text": "detail " * 80} for i in range(40)],
        "evidence": [{"path": f"src/{i}.py", "text": "evidence " * 80} for i in range(30)],
    }


class _LegacyEvidenceStore:
    """Root-compatible evidence API predating validate_current()."""

    root = "repo"
    path = "source.py"
    file_sha256 = "a" * 64
    start_line = 1
    end_line = 1
    text = "current source"

    @staticmethod
    def _id(root: str, path: str, file_hash: str, start: int, end: int, text: str) -> str:
        raw = f"{root}\0{path}\0{file_hash}\0{start}\0{end}\0{text}".encode("utf-8", errors="replace")
        return "E" + sha256(raw).hexdigest()[:20]

    def __init__(self) -> None:
        self.stale = False
        self.evidence_id = self._id(
            self.root, self.path, self.file_sha256, self.start_line, self.end_line, self.text
        )

    def get(self, evidence_id: str, *, verify: bool = True) -> dict[str, object]:
        assert verify is True
        return {
            "success": evidence_id == self.evidence_id,
            "evidence_id": evidence_id,
            "root": self.root,
            "path": self.path,
            "file_sha256": self.file_sha256,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text,
            "stale": self.stale,
        }


def test_budget_response_supports_legacy_evidence_store_and_rejects_stale_ids() -> None:
    store = _LegacyEvidenceStore()
    metadata = {"baseline_tokens_est": 1000, "baseline_evidence_id": store.evidence_id}
    value = {"success": True, "payload": "x" * 1000}

    current = budget_response(value, max_tokens=512, evidence_store=store, token_metadata=metadata)
    assert current["token_efficiency"]["baseline_evidence_id"] == store.evidence_id

    store.stale = True
    stale = budget_response(value, max_tokens=512, evidence_store=store, token_metadata=metadata)
    assert "baseline_evidence_id" not in stale["token_efficiency"]
    assert "token_savings_delta_est" not in stale["token_efficiency"]


def test_budget_response_applies_aggregate_limit_and_preserves_decision_fields() -> None:
    result = budget_response(_large_result(), max_tokens=260, profile="compact")

    assert json_tokens(result) <= 260
    assert result["success"] is True
    assert result["status"] == "ok"
    assert result["summary"] == "Decision-grade summary"
    assert result["artifact_id"] == "artifact-123"
    assert result["evidence_ids"] == ["E1", "E2"]
    assert result["response_budget"]["truncated"] is True
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["response_budget"]["unit"] == "estimated_tokens"


def test_budget_response_does_not_change_small_values() -> None:
    value = {"success": True, "summary": "small", "evidence_ids": ["E1"]}

    assert budget_response(value, max_tokens=300) == value


def test_budget_response_refreshes_stale_count_in_existing_envelope() -> None:
    value = {
        "success": True,
        "summary": "already compact",
        "response_budget": {
            "requested_tokens": 256,
            "original_tokens": 900,
            "returned_tokens": 1,
            "truncated": True,
            "unit": "estimated_tokens",
        },
    }

    result = budget_response(value, max_tokens=256)

    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["response_budget"]["unit"] == "estimated_tokens"
    assert value["response_budget"]["returned_tokens"] == 1


def test_budget_response_can_return_reuse_envelope() -> None:
    result = budget_response(
        _large_result(),
        max_tokens=260,
        profile="minimal",
        reuse_key="repo:search:abc",
        reuse_only=True,
    )

    assert json_tokens(result) <= 260
    assert result["reuse_key"] == "repo:search:abc"
    assert result["reused"] is True
    assert result["artifact_id"] == "artifact-123"
    assert "results" not in result
    assert "evidence" not in result
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["response_budget"]["unit"] == "estimated_tokens"


def test_budget_rejection_reports_exact_final_token_count() -> None:
    result = budget_response(
        {
            "success": False,
            "error": "route failed " * 1000,
            "evidence_ids": [f"E{index:020X}" for index in range(32)],
            "payload": "x" * 4000,
        },
        max_tokens=128,
        protected_keys=("error", "evidence_ids"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["response_budget"]["unit"] == "estimated_tokens"


def test_budget_response_preserves_bounded_task_context_contract() -> None:
    result = budget_response(
        {
            "success": True,
            "complete": True,
            "partial": False,
            "etag": "etag-1",
            "context_id": "taskctx-1",
            "evidence_ids": ["E1"],
            "task_context": {
                "success": True,
                "complete": True,
                "partial": False,
                "task_id": "task-1",
                "context_id": "taskctx-1",
                "etag": "etag-1",
                "text": "authoritative task facts\n" * 800,
                "source_layers": ["agent_state", "repository"],
                "next_action": "use_compiled_context",
            },
            "text": "authoritative task facts\n" * 800,
        },
        max_tokens=320,
        profile="compact",
        protected_keys=(
            "success", "complete", "partial", "task_context", "context_id", "etag",
            "evidence_ids", "next_action",
        ),
    )

    assert json_tokens(result) <= 320
    assert result["task_context"]["context_id"] == "taskctx-1"
    assert result["task_context"]["etag"] == "etag-1"
    assert result["evidence_ids"] == ["E1"]


def test_budget_response_keeps_guarded_repository_context_pointer() -> None:
    result = budget_response(
        {
            "success": True,
            "context": "deterministic repository facts",
            "context_pack": {"contract": {"goal": "inspect logs"}, "evidence": [{"evidence_id": "E1"}]},
            "context_id": "ctx-1",
            "evidence_ids": ["E1"],
        },
        max_tokens=220,
        profile="compact",
        protected_keys=("success", "context", "context_pack", "context_id", "evidence_ids"),
    )

    assert json_tokens(result) <= 220
    assert result["context_id"] == "ctx-1"
    assert result["context"]
    assert result["context_pack"]


def test_context_budget_inputs_keep_integer_annotations() -> None:
    import inspect

    from local_ai_hub import mcp_server
    from local_ai_hub.agent_context import ContextRequest

    typed_inputs = (
        (ContextRequest, "token_budget"),
        (budget_response, "max_tokens"),
        (mcp_server.local_ai_status, "max_response_tokens"),
        (mcp_server.local_ai_task, "max_response_tokens"),
        (mcp_server.local_ai_repo, "max_response_tokens"),
        (mcp_server.local_ai_rag, "max_response_tokens"),
        (mcp_server.local_ai_command, "max_response_tokens"),
        (mcp_server.local_ai_coord, "max_response_tokens"),
        (mcp_server.local_ai_artifact, "max_response_tokens"),
        (mcp_server.local_ai_work, "max_response_tokens"),
    )
    for callable_, name in typed_inputs:
        annotation = inspect.signature(callable_).parameters[name].annotation
        assert annotation is int or annotation == "int", (callable_.__name__, name, annotation)
