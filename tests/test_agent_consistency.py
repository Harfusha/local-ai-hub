from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.config import load_config
from local_ai_hub.agent_consistency import (
    AgentConsistencyGuard,
    ConsistencyRequest,
    ContractMapping,
    GuardWarning,
    ReuseCandidate,
)
from local_ai_hub.agent_tasks import GoalContract
from local_ai_hub.repo_tools import RepositoryTools


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
    request = _request(repository, query="UserService user endpoint")

    candidates = guard.find_reuse_candidates(request, guard.build_contract(request))

    assert candidates
    assert candidates[0].path == "backend/users.py"
    assert candidates[0].candidate_id
    assert all(candidate.score >= 0 for candidate in candidates)


def test_rejected_reuse_requires_reason(repository: Path):
    guard = _guard(repository)
    request = _request(repository, query="UserService")
    contract = guard.build_contract(request)
    candidates = guard.find_reuse_candidates(request, contract)

    warnings = guard.check_drift(
        request,
        contract,
        (),
        {"reuse_decisions": [{"candidate_id": candidates[0].candidate_id, "decision": "reject"}]},
    )

    assert any(w.code == "reuse_rejection_reason_required" for w in warnings)
    assert all(not w.requires_approval for w in warnings)


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

    result = guard.check_claims(
        [{"evidence_id": "src-1", "path": "backend/users.py", "raw": "class UserService"}],
        [{"claim": "PaymentGateway exists", "evidence_ids": ["model-claim"]}],
    )

    assert result[0].code == "unknown_claim"
    assert result[0].evidence_ids == ()
    assert result[0].requires_approval is False


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
