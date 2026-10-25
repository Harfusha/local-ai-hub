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


def test_reuse_pointers_preserve_mutation_outcome_flags_for_all_profiles() -> None:
    for profile in ("compact", "minimal", "delta"):
        result = budget_response(
            {
                "success": False,
                "error": "checkpoint response budget rejected " * 500,
                "request_id": "req_0123456789ab",
                "mutation_applied": False,
                "operation_not_started": True,
            },
            max_tokens=256,
            profile=profile,
            reuse_key=f"checkpoint-error:{profile}",
            reuse_only=True,
        )

        assert json_tokens(result) <= 256
        assert result["mutation_applied"] is False
        assert result["operation_not_started"] is True
        assert result["request_id"] == "req_0123456789ab"
        assert result["reused"] is True


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


def test_budget_rejection_keeps_bounded_adaptive_context_identity_and_citation() -> None:
    pack = {
        "context_id": "ctx-123",
        "repo_revision": "rev-7",
        "evidence": [
            {
                "evidence_id": "E123",
                "path": "src/main.py",
                "start_line": 4,
                "end_line": 6,
                "source": "deterministic",
                "content": "private detail " * 500,
            }
            for _ in range(12)
        ],
        "warnings": [{"code": "scope_drift", "message": "large warning " * 500} for _ in range(12)],
    }

    result = budget_response(
        {"success": True, "adaptive_context_pack": pack},
        max_tokens=128,
        protected_keys=("success", "adaptive_context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["requested_tokens"] == 128
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    bounded = result["adaptive_context_pack"]
    assert bounded["context_id"] == "ctx-123"
    assert bounded["repo_revision"] == "rev-7"
    assert bounded["evidence"][0] == {
        "evidence_id": "E123",
        "path": "src/main.py",
        "start_line": 4,
        "end_line": 6,
        "source": "deterministic",
    }
    assert "content" not in repr(bounded)


def test_budget_rejection_keeps_bounded_legacy_context_pack_citation() -> None:
    result = budget_response(
        {
            "success": True,
            "context_pack": {
                "context_id": "legacy-ctx",
                "repo_revision": "rev-8",
                "evidence": [
                    {
                        "evidence_id": "E8",
                        "path": "src/legacy.py",
                        "start_line": 8,
                        "end_line": 9,
                        "source": "deterministic",
                        "content": "private detail " * 500,
                    }
                    for _ in range(10)
                ],
            },
        },
        max_tokens=128,
        protected_keys=("success", "context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["requested_tokens"] == 128
    assert result["response_budget"]["returned_tokens"] == json_tokens(result)
    assert result["context_pack"]["context_id"] == "legacy-ctx"
    assert result["context_pack"]["evidence"][0] == {
        "evidence_id": "E8",
        "path": "src/legacy.py",
        "start_line": 8,
        "end_line": 9,
        "source": "deterministic",
    }
    assert "content" not in repr(result["context_pack"])

def test_budget_rejection_uses_first_complete_citation() -> None:
    result = budget_response(
        {
            "success": True,
            "adaptive_context_pack": {
                "context_id": "ctx-123",
                "repo_revision": "rev-7",
                "evidence": [
                    {"evidence_id": "E-incomplete"},
                    {
                        "evidence_id": "E-complete",
                        "path": "src/later.py",
                        "start_line": 20,
                        "end_line": 24,
                        "source": "deterministic",
                        "content": "private detail " * 500,
                    },
                ],
            },
        },
        max_tokens=128,
        protected_keys=("success", "adaptive_context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["response_budget"]["original_tokens"] > 128
    assert result["adaptive_context_pack"]["evidence"][0] == {
        "evidence_id": "E-complete",
        "path": "src/later.py",
        "start_line": 20,
        "end_line": 24,
        "source": "deterministic",
    }


def test_budget_rejection_uses_later_complete_legacy_citation() -> None:
    result = budget_response(
        {
            "success": True,
            "context_pack": {
                "context_id": "legacy-ctx",
                "repo_revision": "rev-legacy",
                "evidence": [
                    {"evidence_id": "E-incomplete"},
                    {
                        "evidence_id": "E-legacy-complete",
                        "path": "src/legacy-later.py",
                        "start_line": 30,
                        "end_line": 35,
                        "source": "deterministic",
                        "content": "private detail " * 500,
                    },
                ],
            },
        },
        max_tokens=220,
        protected_keys=("success", "context_pack"),
    )

    assert json_tokens(result) <= 220
    assert result["response_budget"]["original_tokens"] > 220
    assert result["context_pack"]["evidence"][0] == {
        "evidence_id": "E-legacy-complete",
        "path": "src/legacy-later.py",
        "start_line": 30,
        "end_line": 35,
        "source": "deterministic",
    }


def test_budget_rejection_preserves_bounded_error_and_retryability() -> None:
    result = budget_response(
        {
            "success": False,
            "status_code": 503,
            "terminal": True,
            "retryable": True,
            "error": "context backend unavailable",
            "adaptive_context_pack": {
                "context_id": "ctx-error",
                "repo_revision": "rev-error",
                "evidence": [{
                    "evidence_id": "E-error",
                    "path": "src/context.py",
                    "start_line": 7,
                    "end_line": 9,
                    "source": "deterministic",
                    "content": "private backend detail " * 500,
                }],
            },
        },
        max_tokens=128,
        protected_keys=("success", "status_code", "terminal", "retryable", "error", "adaptive_context_pack"),
    )

    assert json_tokens(result) <= 128
    assert result["success"] is False
    assert result["status_code"] == 503
    assert result["terminal"] is True
    assert result["retryable"] is True
    assert result["error"] == "context backend unavailable"
    assert result["adaptive_context_pack"]["context_id"] == "ctx-error"
    assert "content" not in repr(result["adaptive_context_pack"])

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
        (mcp_server.local_ai_coord, "max_response_tokens"),
        (mcp_server.local_ai_artifact, "max_response_tokens"),
        (mcp_server.local_ai_work, "max_response_tokens"),
    )
    for callable_, name in typed_inputs:
        annotation = inspect.signature(callable_).parameters[name].annotation
        assert annotation is int or annotation == "int", (callable_.__name__, name, annotation)


def test_task_list_envelope_preserves_tasks_across_budget_matrix() -> None:
    task_item = {
        "task_id": "post-gemini-audit-20261025",
        "status": "planned",
        "owner": "codex",
        "created_at": 1792920456.9,
        "contract": {
            "goal": "Independently audit and finish Local AI Hub after Gemini, verify all eight Unreleased items.",
            "acceptance_criteria": [f"Criterion {i}: " + "x" * 200 for i in range(10)]
        },
        "checkpoint": {
            "phase": "perf_T1_committed",
            "next_action": "perf_T2",
            "state_data": {
                "memory_context": {"items": [{"id": f"item_{i}", "content": "c" * 200} for i in range(10)]}
            }
        }
    }
    source = {
        "success": True,
        "request_id": "req_00919ef2ad88",
        "tasks": [dict(task_item, task_id=f"task_{i}") for i in range(6)],
        "total_count": 6,
        "active_count": 2,
        "offset": 0,
        "limit": 100,
        "has_more": False,
    }

    # Verify each tier of the required matrix: 128, 512, 1200, 3500
    for cap in (128, 512, 1200, 3500):
        budgeted = budget_response(
            source,
            max_tokens=cap,
            profile="compact",
            protected_keys=("success", "request_id"),
        )
        assert json_tokens(budgeted) <= cap, f"Envelope at cap {cap} exceeded limit"
        assert budgeted["success"] is True
        assert budgeted["request_id"] == "req_00919ef2ad88"
        assert "tasks" in budgeted
        assert len(budgeted["tasks"]) >= 1, f"Expected at least 1 task at cap {cap}, got empty"
        assert budgeted["tasks"][0]["task_id"] == "task_0"
        assert budgeted["tasks"][0]["status"] == "planned"
        assert budgeted["total_count"] == 6
        assert budgeted["active_count"] == 2
        assert "response_budget" in budgeted
        assert budgeted["response_budget"]["returned_tokens"] <= cap


def test_empty_task_list_preserves_explicit_empty_list() -> None:
    source = {
        "success": True,
        "request_id": "req_empty",
        "tasks": [],
        "total_count": 0,
        "active_count": 0,
        "has_more": False,
    }
    for cap in (128, 512, 1200):
        budgeted = budget_response(
            source,
            max_tokens=cap,
            profile="compact",
            protected_keys=("success", "request_id"),
        )
        assert json_tokens(budgeted) <= cap
        assert budgeted["success"] is True
        assert budgeted["tasks"] == []
        assert budgeted["total_count"] == 0


def test_memory_find_records_preserved_across_budget_matrix() -> None:
    record = {
        "record_id": "rec_001",
        "scope": "repository",
        "key": "arch_pattern",
        "operation_class": "architecture",
        "value": "Modular pipeline with bounded MCP response envelope and memory adoption.",
        "summary": "Verified architectural convention for Local AI Hub.",
        "timestamp": 1792920456.0,
    }
    source = {
        "success": True,
        "request_id": "req_mem_find",
        "records": [dict(record, record_id=f"rec_{i}") for i in range(8)],
        "total_count": 8,
    }
    for cap in (128, 512, 1200, 3500):
        budgeted = budget_response(
            source,
            max_tokens=cap,
            profile="compact",
            protected_keys=("success", "request_id"),
        )
        assert json_tokens(budgeted) <= cap
        assert budgeted["success"] is True
        assert "records" in budgeted
        assert len(budgeted["records"]) >= 1
        assert budgeted["records"][0]["record_id"] == "rec_0"
