from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.config import load_config
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_memory import MemoryKind, MemoryStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.agent_consistency import (
    AgentConsistencyGuard,
    AdaptiveContextPack,
    ConsistencyRequest,
    ContractMapping,
    GuardWarning,
    ReuseCandidate,
)
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.telemetry import TelemetryStore


def _cfg(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n'
        '[hardware]\nprofile="cpu"\n',
        encoding="utf-8",
    )
    return load_config(str(path))


def _request(repo: Path, **changes) -> ConsistencyRequest:
    values = {
        "root": str(repo),
        "task_id": "task-consistency",
        "query": "add a user endpoint and frontend client",
        "phase": "edit",
        "focus": ("reuse", "contract"),
        "workspace": "test",
        "preload_profile": "default",
        "token_budget": 1200,
        "changed_paths": (),
        "base": "HEAD",
        "staged": False,
        "tenant": "repo",
        "override_reason": "",
        "approval": "",
    }
    values.update(changes)
    return ConsistencyRequest(**values)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    (repo / "frontend").mkdir()
    (repo / "tests").mkdir()
    (repo / "backend" / "users.py").write_text(
        "class UserService:\n"
        "    def get_user(self, user_id: str) -> dict:\n"
        "        return {'id': user_id, 'name': 'Ada'}\n\n"
        "class ApiError:\n"
        "    code = 'USER_NOT_FOUND'\n",
        encoding="utf-8",
    )
    (repo / "backend" / "new_endpoint.py").write_text(
        "class UserEndpoint:\n"
        "    def get_user(self, user_id: str) -> dict:\n"
        "        return {'id': user_id}\n",
        encoding="utf-8",
    )
    (repo / "frontend" / "users.ts").write_text(
        "export type User = { id: string; name: string };\n"
        "export async function getUser(userId: string): Promise<User> {\n"
        "  return api.get(`/users/${userId}`);\n"
        "}\n"
        "function renderError(error: ApiError) {}\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_users.py").write_text(
        "def test_get_user():\n    assert UserService().get_user('1')['id'] == '1'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "initial"],
        check=True,
    )
    return repo


def _guard(repository: Path) -> AgentConsistencyGuard:
    return AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)))


def test_contract_preserves_non_goals_constraints_and_scope(repository: Path):
    source = GoalContract(
        goal="add a user endpoint",
        acceptance_criteria=("returns a user",),
        scope="task",
        non_goals=("no database migration",),
        constraints=("reuse UserService", "keep API backward compatible"),
    )
    guard = AgentConsistencyGuard(
        RepositoryTools(_cfg(repository.parent)),
        task_store=SimpleNamespace(get=lambda _task_id: SimpleNamespace(contract=source)),
    )

    contract = guard.build_contract(_request(repository))

    assert contract.goal == source.goal
    assert contract.acceptance_criteria == source.acceptance_criteria
    assert contract.scope == source.scope
    assert contract.non_goals == source.non_goals
    assert contract.constraints == source.constraints
    assert json.loads(json.dumps(contract.to_dict()))["non_goals"] == ["no database migration"]


def test_reuse_candidates_are_ranked_before_new_symbols(repository: Path):
    guard = _guard(repository)
    request = _request(repository, query="user endpoint get_user")

    candidates = guard.find_reuse_candidates(request, guard.build_contract(request))

    assert candidates
    assert candidates[0].path == "backend/users.py"
    assert any(candidate.symbol == "UserEndpoint" for candidate in candidates)
    assert candidates.index(next(candidate for candidate in candidates if candidate.symbol == "UserService")) < candidates.index(next(candidate for candidate in candidates if candidate.symbol == "UserEndpoint"))
    assert candidates[0].candidate_id
    assert all(candidate.score >= 0 for candidate in candidates)


def test_reuse_ranking_beats_reversed_high_score_reinvention(repository: Path, monkeypatch):
    guard = _guard(repository)
    monkeypatch.setattr(
        guard.repository_tools,
        "search",
        lambda *_args, **_kwargs: {
            "success": True,
            "results": [
                {"path": "backend/new_endpoint.py", "start_line": 1, "score": 999, "text": "class UserEndpoint"},
                {"path": "backend/users.py", "start_line": 1, "score": 1, "text": "class UserService"},
            ],
        },
    )

    candidates = guard.find_reuse_candidates(_request(repository, query="user service endpoint"), GoalContract(goal="user service"))

    assert candidates[0].symbol == "UserService"
    assert candidates[0].path == "backend/users.py"


def test_rejected_reuse_requires_reason(repository: Path):
    guard = _guard(repository)
    request = _request(repository, query="UserService")
    contract = guard.build_contract(request)
    candidates = guard.find_reuse_candidates(request, contract)

    warnings = guard.check_drift(
        request,
        contract,
        (),
        {
            "reuse_decisions": [{"candidate_id": candidates[0].candidate_id, "decision": "reject"}],
            "evidence": [{"evidence_id": "reuse-evidence", "path": "backend/users.py", "raw": "class UserService"}],
        },
    )

    assert any(w.code == "reuse_rejection_reason_required" for w in warnings)
    assert all(w.evidence_ids for w in warnings if w.code == "reuse_rejection_reason_required")
    assert all(not w.requires_approval for w in warnings)


def test_drift_warnings_keep_exact_evidence_ids(repository: Path):
    guard = _guard(repository)
    request = _request(repository, changed_paths=("backend/users.py",))
    contract = guard.build_contract(request)
    evidence = [{"evidence_id": "diff-evidence", "path": "backend/users.py", "raw": "class UserService"}]
    candidate = guard.find_reuse_candidates(request, contract)[0]

    warnings = guard.check_drift(
        request,
        contract,
        ("frontend/users.ts",),
        {
            "changed_paths": ["frontend/users.ts"],
            "diff": "+class NewPublicThing",
            "evidence": evidence,
            "reuse_decisions": [{"candidate_id": "missing", "decision": "reject", "evidence_ids": ["diff-evidence"]}],
        },
    )

    by_code = {warning.code: warning for warning in warnings}
    assert by_code["unknown_reuse_candidate"].evidence_ids == ("diff-evidence",)
    assert set(candidate.evidence_ids).issubset(by_code["new_public_symbol_despite_reuse"].evidence_ids)
    assert by_code["new_public_symbol_despite_reuse"].evidence_ids
    assert by_code["scope_drift"].evidence_ids == ("diff-evidence",)


def test_drift_without_evidence_gets_stable_synthetic_trace(repository: Path, monkeypatch):
    guard = _guard(repository)
    monkeypatch.setattr(guard.repository_tools, "search", lambda *_args, **_kwargs: {"success": True, "results": []})
    request = _request(repository, changed_paths=("backend/users.py",))
    contract = guard.build_contract(request)
    common = "diff-prefix\n" * 2000
    first_diff = common + "TAIL-A\n"
    second_diff = common + "TAIL-B\n"
    retained = first_diff[:12000]
    diff = {
        "changed_paths": ["frontend/users.ts"],
        "diff": retained,
        "diff_sha256": hashlib.sha256(first_diff.encode()).hexdigest(),
    }

    first = guard.check_drift(request, contract, ("frontend/users.ts",), diff)
    repeat = guard.check_drift(request, contract, ("frontend/users.ts",), diff)
    changed = guard.check_drift(
        request,
        contract,
        ("frontend/users.ts",),
        {
            "changed_paths": ["frontend/users.ts"],
            "diff": retained,
            "diff_sha256": hashlib.sha256(second_diff.encode()).hexdigest(),
        },
    )

    first_scope = next(warning for warning in first if warning.code == "scope_drift")
    repeat_scope = next(warning for warning in repeat if warning.code == "scope_drift")
    assert first_scope.evidence_ids
    assert first_scope.evidence_ids == repeat_scope.evidence_ids
    assert first_scope.evidence_ids[0].startswith("synthetic-drift-")
    changed_scope = next(warning for warning in changed if warning.code == "scope_drift")
    assert changed_scope.evidence_ids != first_scope.evidence_ids


def test_forged_decision_evidence_id_is_replaced_by_synthetic_trace(repository: Path):
    guard = _guard(repository)
    request = _request(repository, query="UserService")
    contract = guard.build_contract(request)
    candidate = guard.find_reuse_candidates(request, contract)[0]

    warnings = guard.check_drift(
        request,
        contract,
        (),
        {"reuse_decisions": [{"candidate_id": candidate.candidate_id, "decision": "reject", "evidence_ids": ["forged-id"]}]},
    )

    warning = next(item for item in warnings if item.code == "reuse_rejection_reason_required")
    assert warning.evidence_ids
    assert "forged-id" not in warning.evidence_ids
    assert warning.evidence_ids[0].startswith("synthetic-decision-")


def test_local_model_evidence_cannot_form_contract_mapping(repository: Path):
    guard = _guard(repository)
    evidence = [
        {"evidence_id": "be-1", "path": "backend/users.py", "raw": "GET /users/{id} -> User {id: string}"},
        {"evidence_id": "fe-local", "path": "frontend/users.ts", "provider": "qwen3.5:9b", "raw": "type User = { id: string }"},
    ]

    mappings, warnings = guard.build_contract_mappings(_request(repository), evidence)

    assert mappings == ()
    assert warnings == ()


def test_guard_bounds_evidence_generator_without_exhausting_it(repository: Path):
    guard = _guard(repository)

    def evidence_stream():
        for index in range(64):
            yield {"evidence_id": f"evidence-{index}", "path": "backend/users.py", "raw": "class UserService"}
        raise AssertionError("evidence generator exhausted past guard bound")

    warnings = guard.check_claims(evidence_stream(), [{"claim": "missing", "evidence_ids": ["not-present"]}])

    assert warnings[0].code == "unknown_claim"


def test_be_fe_contract_reports_response_and_error_mismatches(repository: Path):
    guard = _guard(repository)
    evidence = [
        {"evidence_id": "be-1", "path": "backend/users.py", "raw": "GET /users/{id} -> User {id: string, name: string | null}; error USER_NOT_FOUND"},
        {"evidence_id": "fe-1", "path": "frontend/users.ts", "raw": "getUser(id): Promise<User>; type User = { id: string }; handles error NOT_FOUND"},
    ]

    mappings, warnings = guard.build_contract_mappings(_request(repository), evidence)

    assert mappings
    assert any(mapping.kind in {"response", "error"} for mapping in mappings)
    assert any(w.code in {"response_schema_mismatch", "error_identifier_mismatch"} for w in warnings)
    assert all(w.evidence_ids for w in warnings)


def test_unknown_claim_has_no_authoritative_evidence(repository: Path):
    guard = _guard(repository)
    evidence = [{"evidence_id": "src-1", "path": "backend/users.py", "raw": "class UserService"}]
    claims = [{"claim": "PaymentGateway exists", "evidence_ids": ["model-claim"]}]

    result = guard.check_claims(evidence, claims)
    repeat = guard.check_claims(evidence, claims)

    assert result[0].code == "unknown_claim"
    assert result[0].evidence_ids
    assert result[0].evidence_ids == repeat[0].evidence_ids
    assert result[0].evidence_ids[0].startswith("synthetic-claim-")
    assert "synthetic claim-evidence reference" in result[0].message
    assert result[0].requires_approval is False


@pytest.mark.parametrize(
    "field,label",
    [
        ("source", "model"),
        ("source", "LLM"),
        ("source", "Generated"),
        ("source", "local_model"),
        ("source", "local-model"),
        ("source", "local model"),
        ("source", "ollama"),
        ("source", "Ollama/qwen3.5:9b"),
        ("source", "local inference"),
        ("source", "model-generated output"),
        ("source", "generated by local model"),
        ("source", "local_ai_runner"),
        ("source", "local"),
        ("provider", "local"),
        ("provider", "local-inference"),
        ("provider", "qwen3.5:9b"),
    ],
)
def test_local_model_evidence_is_never_authoritative(repository: Path, field: str, label: str):
    guard = _guard(repository)
    evidence = [{"evidence_id": "model-1", "path": "backend/users.py", field: label, "raw": "UserService exists"}]

    result = guard.check_claims(evidence, [{"claim": "UserService exists", "evidence_ids": ["model-1"]}])

    assert result and result[0].code == "unknown_claim" and result[0].evidence_ids


class _Hostile:
    def __bool__(self):
        raise RuntimeError("truthiness denied")

    def __str__(self):
        raise RuntimeError("stringification denied")

    def __iter__(self):
        raise RuntimeError("iteration denied")


def test_dataclass_to_dict_is_recursively_bounded_and_json_safe(repository: Path):
    hostile = _Hostile()
    pack = AdaptiveContextPack(
        contract=None,
        reuse_candidates=(ReuseCandidate(hostile, hostile, hostile, score=hostile, suitable=hostile),),
        mappings=(ContractMapping(hostile, backend_fields=(hostile,)),),
        warnings=(GuardWarning(hostile, message=hostile, requires_approval=hostile),),
        evidence=({hostile: hostile},),
        repo_revision=hostile,
        changed_paths=(hostile,),
        stale=hostile,
        context_id=hostile,
    )
    request = _request(repository, focus=(hostile,), changed_paths=(hostile,), staged=hostile, approval=hostile, token_budget=hostile)

    payloads = [request.to_dict(), pack.to_dict()]

    for payload in payloads:
        assert json.loads(json.dumps(payload)) == payload
    assert isinstance(request.to_dict()["staged"], bool)
    assert isinstance(pack.to_dict()["stale"], bool)


class _MemoryStoreFake:
    def __init__(self):
        self.records = []

    def record(self, record, **kwargs):
        self.records.append((record, kwargs))
        return record


class _VerificationStoreFake:
    def __init__(self):
        self.receipts = []

    def record(self, receipt):
        self.receipts.append(receipt)
        return receipt


def test_claim_decisions_use_existing_memory_and_verification_stores(repository: Path):
    memory = _MemoryStoreFake()
    verification = _VerificationStoreFake()
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory, verification_store=verification)
    request = _request(repository)
    evidence = [{
        "evidence_id": "src-1",
        "path": "backend/users.py",
        "file_sha256": hashlib.sha256((repository / "backend" / "users.py").read_bytes()).hexdigest(),
        "repository_revision": guard.repository_tools.git_snapshot(str(repository)).revision,
        "raw": "class UserService",
    }]

    result = guard.check_claims(evidence, [{"claim": "UserService exists", "evidence_ids": ["src-1"]}], request=request)

    assert result == ()
    assert len(memory.records) == 1
    assert memory.records[0][0].evidence_ids == ("src-1",)
    assert memory.records[0][0].provenance["related_task"] == request.task_id
    assert len(verification.receipts) == 1
    assert verification.receipts[0].evidence_id == "src-1"
    assert verification.receipts[0].repository_revision

    unknown = guard.check_claims(evidence, [{"claim": "UnknownService exists"}], request=request)
    assert unknown[0].evidence_ids
    assert memory.records[-1][0].evidence_ids == unknown[0].evidence_ids


def test_claim_rejects_stale_foreign_and_missing_evidence_ids(repository: Path):
    guard = _guard(repository)
    request = _request(repository)
    revision = guard.repository_tools.git_snapshot(str(repository)).revision
    current_hash = hashlib.sha256((repository / "backend" / "users.py").read_bytes()).hexdigest()
    evidence = [
        {"evidence_id": "stale-1", "path": "backend/users.py", "file_sha256": "0" * 64, "repository_revision": revision},
        {"evidence_id": "foreign-1", "path": "../outside.py", "file_sha256": current_hash, "repository_revision": revision},
        {"evidence_id": "current-1", "path": "backend/users.py", "file_sha256": current_hash, "repository_revision": revision},
    ]

    for evidence_id in ("stale-1", "foreign-1", "missing-1"):
        claims = [{"claim": f"claim {evidence_id}", "evidence_ids": [evidence_id]}]
        first = guard.check_claims(evidence, claims, request=request)
        repeat = guard.check_claims(evidence, claims, request=request)
        assert first and first[0].code == "unknown_claim"
        assert first[0].evidence_ids
        assert first[0].evidence_ids == repeat[0].evidence_ids

    assert guard.check_claims(evidence, [{"claim": "current", "evidence_ids": ["current-1"]}], request=request) == ()


def test_metadata_only_current_claim_evidence_is_not_authoritative(repository: Path):
    guard = _guard(repository)
    revision = guard.repository_tools.git_snapshot(str(repository)).revision
    evidence = [{"evidence_id": "forged-current", "status": "current", "repository_revision": revision}]

    first = guard.check_claims(evidence, [{"claim": "forged", "evidence_ids": ["forged-current"]}], request=_request(repository))
    repeat = guard.check_claims(evidence, [{"claim": "forged", "evidence_ids": ["forged-current"]}], request=_request(repository))

    assert first and first[0].code == "unknown_claim"
    assert first[0].evidence_ids == repeat[0].evidence_ids


def test_claims_without_request_accept_deterministic_path_hash_evidence(repository: Path):
    guard = _guard(repository)
    evidence = [{
        "evidence_id": "deterministic-no-request",
        "path": "backend/users.py",
        "file_sha256": hashlib.sha256((repository / "backend" / "users.py").read_bytes()).hexdigest(),
    }]

    assert guard.check_claims(evidence, [{"claim": "UserService exists", "evidence_ids": ["deterministic-no-request"]}]) == ()


def test_check_drift_does_not_use_snapshot_after_diff_path_failure(repository: Path, monkeypatch):
    guard = _guard(repository)
    request = _request(repository)
    contract = guard.build_contract(request)
    monkeypatch.setattr(
        guard.repository_tools,
        "git_diff",
        lambda *_args, **_kwargs: {
            "success": False,
            "paths_complete": False,
            "retryable": True,
            "error": "path capture failed",
        },
    )
    monkeypatch.setattr(guard.repository_tools, "git_snapshot", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("incomplete paths used")))

    assert guard.check_drift(request, contract, (), None) == ()


def test_check_drift_refuses_incomplete_diff_even_with_supplied_paths(repository: Path):
    guard = _guard(repository)
    request = _request(repository)
    contract = guard.build_contract(request)
    for diff in (
        {"success": False, "paths_complete": False, "error": "capture failed"},
        {"success": True, "paths_complete": False},
        {"success": True, "truncated": True},
        {"success": True, "incomplete": True},
        {"success": True, "error": "partial evidence"},
    ):
        assert guard.check_drift(request, contract, ("frontend/users.ts",), diff) == ()


def test_soft_warning_has_required_fields(repository: Path):
    warning = GuardWarning(
        severity="warning",
        code="scope_drift",
        message="changed path is outside task scope",
        evidence_ids=("diff-1",),
        affected_paths=("frontend/users.ts",),
        recommended_action="explain or narrow the change",
    )

    payload = warning.to_dict()

    assert set(("severity", "code", "message", "evidence_ids", "affected_paths", "recommended_action", "requires_approval")).issubset(payload)
    assert payload["requires_approval"] is False
    assert json.loads(json.dumps(payload)) == payload


def test_structured_evidence_excludes_raw_source_and_local_model_rows(repository: Path):
    guard = _guard(repository)
    projected = guard.structured_evidence([
        {"evidence_id": "det-1", "path": "backend/users.py", "raw": "secret-value"},
        {"evidence_id": "model-1", "path": "backend/users.py", "source": "local model", "raw": "invented"},
    ])

    assert len(projected) == 1
    assert projected[0]["evidence_id"] == "det-1"
    assert "secret-value" not in json.dumps(projected)
    assert "raw" not in json.dumps(projected)


def test_postprocess_drops_unsupported_claims(repository: Path):
    guard = _guard(repository)
    evidence = [{
        "evidence_id": "det-1",
        "path": "backend/users.py",
        "file_sha256": hashlib.sha256((repository / "backend" / "users.py").read_bytes()).hexdigest(),
    }]

    result = guard.postprocess_model_claims(evidence, [
        {"claim": "UserService exists", "evidence_ids": ["det-1"]},
        {"claim": "PaymentGateway exists", "evidence_ids": ["forged-1"]},
    ])

    assert [claim["claim"] for claim in result["claims"]] == ["UserService exists"]
    assert result["unknowns"] == ("PaymentGateway exists",)
    assert result["warnings"][0].code == "unsupported_model_claim"
    assert result["warnings"][0].kind == "unsupported_claim"


def test_adaptive_context_pack_serializes_relevance_metadata(repository: Path):
    payload = AdaptiveContextPack(
        phase="review",
        focus=("contracts",),
        preload_profile="review",
        memory_revision="memory-1",
        model_warnings=(GuardWarning("warning", "unsupported_model_claim", "dropped"),),
    ).to_dict()

    assert payload["phase"] == "review"
    assert payload["focus"] == ["contracts"]
    assert payload["preload_profile"] == "review"
    assert payload["memory_revision"] == "memory-1"
    assert payload["model_warnings"][0]["code"] == "unsupported_model_claim"


def test_guard_records_verified_finding_after_discovery(repository: Path):
    state = AgentStateStore(repository.parent / "guard-state.sqlite3")
    memory = MemoryStore(state)
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory)
    request = _request(repository)

    saved = guard.record_finding(
        request,
        finding={"summary": "UserService is reusable", "raw": "secret source must not persist"},
        evidence_ids=("ev-users",),
        path_refs=("backend/users.py",),
        symbol_refs=("UserService",),
        confidence=0.91,
    )
    repeat = guard.record_finding(
        request,
        finding={"summary": "changed but same stable finding"},
        evidence_ids=("ev-users",),
        path_refs=("backend/users.py",),
        symbol_refs=("UserService",),
        confidence=0.91,
    )

    assert saved is not None
    assert repeat is not None
    assert saved.record_id == repeat.record_id
    assert saved.kind is MemoryKind.FINDING
    assert saved.repository_revision
    assert saved.path_refs == ("backend/users.py",)
    assert saved.symbol_refs == ("UserService",)
    assert saved.related_task == request.task_id
    assert saved.expires_at is not None
    assert "secret source" not in json.dumps(saved.to_dict())


def test_guard_records_reuse_decision_and_rejected_approach(repository: Path):
    state = AgentStateStore(repository.parent / "guard-state.sqlite3")
    memory = MemoryStore(state)
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory)
    request = _request(repository)

    accepted = guard.record_reuse_decision(
        request, candidate_id="reuse-1", decision="accepted", evidence_ids=("ev-1",), reason="existing service fits"
    )
    rejected = guard.record_rejected_approach(
        request, approach="new UserEndpoint", reason="reuse-1 covers the contract", evidence_ids=("ev-1",)
    )

    assert accepted is not None and accepted.kind is MemoryKind.REUSABLE_CANDIDATE
    assert rejected is not None and rejected.kind is MemoryKind.REJECTED_APPROACH
    assert accepted.provenance["related_task"] == request.task_id
    assert rejected.repository_revision == accepted.repository_revision
    assert memory.count() == 2


def test_soft_stop_override_records_decision(repository: Path):
    state = AgentStateStore(repository.parent / "guard-state.sqlite3")
    memory = MemoryStore(state)
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory)

    saved = guard.record_decision(
        _request(repository, override_reason="boundary approved"),
        decision="override",
        reason="boundary approved",
        approved=True,
        evidence_ids=("synthetic-drift-1",),
    )

    assert saved is not None and saved.kind is MemoryKind.DECISION
    assert saved.value["approved"] is True
    assert saved.value["reason"] == "boundary approved"


def test_guard_records_unknown_and_validation_receipt(repository: Path):
    state = AgentStateStore(repository.parent / "guard-state.sqlite3")
    memory = MemoryStore(state)
    verification = VerificationStore(state)
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory, verification_store=verification)
    request = _request(repository)

    unknown = guard.record_unknown(request, claim="PaymentGateway exists", evidence_ids=("synthetic-claim-1",))
    validation = guard.record_validation(request, criterion="tests", passed=True, evidence_ids=("ev-tests",))

    assert unknown is not None and unknown.kind is MemoryKind.UNKNOWN
    assert validation is not None and validation.kind is MemoryKind.VALIDATION
    assert verification.completion(request.task_id).receipts[0].evidence_id == "ev-tests"


def test_guard_metrics_store_categories_without_raw_prompt_or_source(repository: Path):
    guard = _guard(repository)
    guard.record_metric("reuse_candidates", 2)
    guard.record_metric("reuse_accepted")
    guard.record_metric("reuse_rejected")
    guard.record_metric("warning", 3, severity="boundary")
    guard.record_metric("unknown_claims")
    guard.record_metric("contract_mismatches")
    guard.record_metric("duplicate_context_reuse")
    guard.record_metric("degraded_local_model_fallback")

    metrics = guard.metrics_snapshot()
    encoded = json.dumps(metrics)

    assert metrics["reuse_candidates"] == 2
    assert metrics["reuse_accepted"] == 1
    assert metrics["reuse_rejected"] == 1
    assert metrics["warning_boundary"] == 3
    assert metrics["unknown_claims"] == 1
    assert metrics["contract_mismatches"] == 1
    assert metrics["duplicate_context_reuse"] == 1
    assert metrics["degraded_local_model_fallback"] == 1
    assert "prompt" not in encoded.lower()
    assert "source snippet" not in encoded.lower()
    assert "UserService" not in encoded


def test_guard_memory_is_noop_when_store_disabled(repository: Path):
    state = AgentStateStore(repository.parent / "disabled.sqlite3", enabled=False)
    memory = MemoryStore(state)
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory)

    saved = guard.record_unknown(_request(repository), claim="unknown service", evidence_ids=("ev-unknown",))

    assert saved is None
    assert memory.count() == 0


def test_guard_memory_keys_are_root_scoped_and_sensitive_fields_redacted(repository: Path):
    memory = _MemoryStoreFake()
    guard = AgentConsistencyGuard(RepositoryTools(_cfg(repository.parent)), memory_store=memory)
    other_root = repository.parent / "repo-two"
    other_root.mkdir()

    guard.record_decision(
        _request(repository),
        decision="approve",
        reason="Approved token=secret-value prompt: private instruction",
        stable_key="stable token=stable-secret prompt: private key",
    )
    guard.record_unknown(
        _request(other_root),
        claim="claim token=claim-secret prompt: private claim",
        stable_key="claim-key token=key-secret",
    )

    first, second = memory.records
    assert first[0].key != second[0].key
    assert first[1]["idempotency_key"] != second[1]["idempotency_key"]
    encoded = json.dumps({
        "key": first[0].key,
        "idempotency_key": first[1]["idempotency_key"],
        "value": first[0].value,
        "provenance": first[0].provenance,
    }) + json.dumps(second[0].value)
    for secret in ("secret-value", "stable-secret", "claim-secret", "key-secret", "private instruction", "private claim"):
        assert secret not in encoded


def test_raw_string_diff_fails_closed(repository: Path):
    guard = _guard(repository)
    request = _request(repository)
    contract = guard.build_contract(request)

    assert guard.check_drift(request, contract, ("frontend/users.ts",), "+class NewPublicThing") == ()


def test_telemetry_savings_labels_use_fixed_allowlist():
    clean = TelemetryStore._clean_event({
        "savings_source": "response_compaction",
        "input_savings_source": "prompt:secret-value",
        "output_savings_source": "untrusted-label",
        "savings_breakdown_json": '{"response_compaction": 3, "prompt-secret": 9}',
    })

    assert clean["savings_source"] == "response_compaction"
    assert clean["input_savings_source"] == ""
    assert clean["output_savings_source"] == ""
    assert clean["savings_breakdown_json"] == '{"response_compaction":3}'
