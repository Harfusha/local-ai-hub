from __future__ import annotations

import pytest

from local_ai_hub.agent_task_models import GoalContract
from local_ai_hub.verified_execution import execution_projection, normalize_execution


def _project(*, satisfied=(), unsatisfied=(), stale=(), blockers=(), complete=False):
    return execution_projection(
        ("api", "consumer", "docs"),
        {"profile": "implementation", "units": {
            "api": {"dimension": "contract"},
            "consumer": {"dimension": "integration", "depends_on": ["api"], "priority": 90},
            "docs": {"dimension": "documentation"},
        }},
        satisfied=satisfied, unsatisfied=unsatisfied, stale=stale,
        receipt_ids={"consumer": "receipt-consumer", "api": "receipt-api"},
        receipt_gate_complete=complete, blockers=blockers,
    )


def test_contract_round_trip_and_no_aliasing():
    raw = {"verified_execution": {"units": {"b": {"depends_on": ["a"]}}}}
    contract = GoalContract("implement", acceptance_criteria=("a", "b"), slo_profile=raw)
    raw["verified_execution"]["units"]["b"]["depends_on"].clear()
    restored = GoalContract.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.slo_profile["verified_execution"]["units"]["b"]["depends_on"] == ["a"]


@pytest.mark.parametrize("config", [
    {"units": {"a": {"depends_on": ["b"]}, "b": {"depends_on": ["a"]}}},
    {"units": {"a": {"depends_on": ["missing"]}}},
    {"units": {"a": {"priority": True}}},
    {"units": {"a": {"depends_on": ["a"]}}},
    {"units": {"missing": {}}},
    {"required_dimensions": ["security"]},
    {"version": True},
    {"units": {"a": {"status": "verified"}}},
])
def test_reject_invalid_contract_graph(config):
    with pytest.raises(ValueError):
        normalize_execution(("a", "b"), config)


def test_reject_duplicate_or_empty_criteria():
    for criteria in ((), ("a", "a")):
        with pytest.raises(ValueError):
            normalize_execution(criteria, {})


def test_stale_prerequisite_invalidates_dependent_coverage():
    result = _project(satisfied=("consumer",), stale=("api",), unsatisfied=("docs",))
    assert result["coverage"] == {
        "total": 3, "verified": 0, "unverified": 1, "stale": 1, "dependency_blocked": 1,
    }
    assert result["next_obligation"]["criterion"] == "api"
    assert not result["ready_for_completion_attempt"]


def test_no_receipt_id_can_fake_verification():
    result = _project(unsatisfied=("api", "consumer", "docs"))
    assert result["coverage"]["verified"] == 0
    assert result["next_obligation"]["criterion"] == "api"
    assert "verified_receipt_id" not in result["next_obligation"]


def test_project_obligation_and_checkpoint_blockers():
    result = _project(satisfied=("api", "consumer", "docs"), unsatisfied=("lint",))
    assert result["dimensions"]["project_verification"] == {"total": 1, "verified": 0}
    assert result["next_obligation"]["criterion"] == "lint"
    blocked = _project(satisfied=("api", "consumer", "docs"), complete=True, blockers=("investigate",))
    assert blocked["receipt_gate_complete"] is True
    assert blocked["ready_for_completion_attempt"] is False
    assert blocked["checkpoint_blocker_count"] == 1


def test_all_obligations_verified():
    result = _project(satisfied=("api", "consumer", "docs"), complete=True)
    assert result["coverage"]["verified"] == 3
    assert result["ready_for_completion_attempt"] is True
    assert result["next_obligation"] is None


def test_preview_is_bounded_and_counts_are_not_truncated():
    criteria = tuple(f"check-{i:04}" for i in range(100))
    result = execution_projection(
        criteria, {}, satisfied=(), unsatisfied=criteria, stale=(),
        receipt_ids={}, receipt_gate_complete=False,
    )
    assert result["remaining_count"] == 100
    assert len(result["remaining_preview"]) == 12
    assert result["preview_truncated"] is True


def test_additive_steering_inherits_mandatory_independent_unit():
    raw = normalize_execution(("a",), {"units": {"a": {"dimension": "audit"}}})
    result = execution_projection(
        ("a", "new-obligation"), raw, satisfied=("a",), unsatisfied=("new-obligation",),
        stale=(), receipt_ids={"a": "r"}, receipt_gate_complete=False,
    )
    assert result["next_obligation"]["criterion"] == "new-obligation"
    assert result["coverage"]["total"] == 2


def test_inventory_compiles_generic_resource_check_matrix():
    contract = GoalContract(
        "evaluate a collection",
        acceptance_criteria=("final review",),
        slo_profile={"verified_execution": {
            "profile": "research",
            "inventory": {
                "resources": ["article-a", "article-b"],
                "checks": [
                    {"name": "source review", "dimension": "quality", "priority": 50},
                    {"name": "verify citation", "dimension": "citations"},
                ],
            },
            "required_dimensions": ["quality", "citations"],
        }},
    )
    assert contract.acceptance_criteria == (
        "final review", "source review: article-a", "verify citation: article-a",
        "source review: article-b", "verify citation: article-b",
    )
    assert GoalContract.from_dict(contract.to_dict()) == contract
    projection = execution_projection(
        contract.acceptance_criteria, contract.slo_profile["verified_execution"],
        satisfied=(), unsatisfied=contract.acceptance_criteria, stale=(),
        receipt_ids={}, receipt_gate_complete=False,
    )
    assert projection["inventory"] == {
        "authority": "declared", "resources": 2, "checks": 2, "obligations": 4,
    }
    assert projection["next_obligation"]["criterion"] == "source review: article-a"


def test_inventory_cannot_be_silently_removed_by_criteria_only_update():
    from dataclasses import replace
    contract = GoalContract("review", slo_profile={"verified_execution": {
        "inventory": {"resources": ["a"], "checks": [{"name": "review"}]},
    }})
    updated = replace(contract, acceptance_criteria=())
    assert updated.acceptance_criteria == ("review: a",)


@pytest.mark.parametrize("inventory", [
    {"resources": ["a", "a"], "checks": [{"name": "review"}]},
    {"resources": [], "checks": [{"name": "review"}]},
    {"resources": ["a"], "checks": [{"name": "review: a"}]},
    {"resources": ["a"], "checks": [{"name": "review"}, {"name": "review"}]},
    {"resources": [str(i) for i in range(300)], "checks": [{"name": "review"}, {"name": "verify"}]},
])
def test_inventory_rejects_duplicate_or_oversized_scope(inventory):
    with pytest.raises(ValueError):
        GoalContract("review", slo_profile={"verified_execution": {"inventory": inventory}})


def test_inventory_rejects_conflicting_generated_metadata():
    with pytest.raises(ValueError):
        GoalContract("review", slo_profile={"verified_execution": {
            "inventory": {"resources": ["a"], "checks": [{"name": "review", "dimension": "security"}]},
            "units": {"review: a": {"dimension": "general"}},
        }})


def test_inventory_check_dependencies_apply_per_resource():
    contract = GoalContract("review", slo_profile={"verified_execution": {
        "inventory": {"resources": ["a", "b"], "checks": [
            {"name": "inspect"},
            {"name": "verify", "depends_on": ["inspect"], "priority": 90},
        ]},
    }})
    config = contract.slo_profile["verified_execution"]
    assert config["units"]["verify: a"]["depends_on"] == ["inspect: a"]
    assert config["units"]["verify: b"]["depends_on"] == ["inspect: b"]
    assert GoalContract.from_dict(contract.to_dict()) == contract
    result = execution_projection(contract.acceptance_criteria, config,
                                  satisfied=("inspect: a",), unsatisfied=("verify: a", "inspect: b", "verify: b"),
                                  stale=(), receipt_ids={}, receipt_gate_complete=False)
    assert result["coverage"]["dependency_blocked"] == 1
    assert result["next_obligation"]["criterion"] == "verify: a"


@pytest.mark.parametrize("checks", [
    [{"name": "inspect", "depends_on": ["missing"]}],
    [{"name": "a", "depends_on": ["b"]}, {"name": "b", "depends_on": ["a"]}],
])
def test_inventory_check_dependencies_reject_invalid_graph(checks):
    with pytest.raises(ValueError):
        GoalContract("review", slo_profile={"verified_execution": {
            "inventory": {"resources": ["a"], "checks": checks},
        }})


def test_evidence_progress_is_advisory_and_ignores_future_observations():
    from local_ai_hub.verified_execution import evidence_progress

    result = evidence_progress(created_at=10, now=1000, active=True, complete=False,
                               observed_receipt_times=[20, 2000])
    assert result["status"] == "no_recent_verified_evidence"
    assert result["seconds_since_verified_observation_or_creation"] == 980
    assert result["advisory"] is True
    assert evidence_progress(created_at=10, now=1000, active=False, complete=False,
                             observed_receipt_times=[])["status"] == "recent_or_not_active"


def test_inventory_projection_preserves_exact_resource_and_check_identity():
    from local_ai_hub.verified_execution import execution_resume_summary

    contract = GoalContract("review", slo_profile={"verified_execution": {
        "inventory": {"resources": ["module: detail.py"], "checks": [
            {"name": "inspect", "evidence_type": "source_review"},
        ]},
    }})
    result = execution_projection(
        contract.acceptance_criteria, contract.slo_profile["verified_execution"],
        satisfied=(), unsatisfied=contract.acceptance_criteria, stale=(),
        receipt_ids={}, receipt_gate_complete=False,
    )
    unit = result["next_obligation"]
    assert unit["resource"] == "module: detail.py"
    assert unit["check"] == "inspect"
    assert unit["evidence_type"] == "source_review"
    assert "Declared resource: module: detail.py; check: inspect" in execution_resume_summary(result)
    assert "Required evidence: source_review" in execution_resume_summary(result)


def test_seeded_missing_receipt_in_maximum_inventory_prevents_completion():
    resources = [f"resource-{i:03d}" for i in range(256)]
    contract = GoalContract("review collection", slo_profile={"verified_execution": {
        "inventory": {"resources": resources, "checks": [
            {"name": "inspect"}, {"name": "verify", "depends_on": ["inspect"]},
        ]},
    }})
    missing = "inspect: resource-255"
    result = execution_projection(
        contract.acceptance_criteria, contract.slo_profile["verified_execution"],
        satisfied=tuple(c for c in contract.acceptance_criteria if c != missing),
        unsatisfied=(missing,), stale=(), receipt_ids={}, receipt_gate_complete=True,
    )
    assert result["coverage"]["total"] == 512
    assert result["coverage"]["verified"] == 510
    assert result["coverage"]["dependency_blocked"] == 1
    assert result["next_obligation"]["criterion"] == missing
    assert not result["ready_for_completion_attempt"]


def test_dependency_receipt_order_invalidates_only_affected_chain():
    criteria = ("api", "consumer", "integration", "docs")
    config = {"units": {"consumer": {"depends_on": ["api"]},
                        "integration": {"depends_on": ["consumer"]}}}
    result = execution_projection(
        criteria, config, satisfied=criteria, unsatisfied=(), stale=(),
        receipt_ids={key: key for key in criteria}, receipt_gate_complete=True,
        receipt_observed_at={"api": 20, "consumer": 10, "integration": 30, "docs": 5},
    )
    assert result["coverage"] == {
        "total": 4, "verified": 2, "stale": 1, "unverified": 0, "dependency_blocked": 1,
    }
    assert result["dependency_stale_criteria"] == ["consumer"]
    assert result["next_obligation"]["superseded_by"] == ["api"]
    assert "verified_receipt_id" not in result["next_obligation"]
    assert not result["ready_for_completion_attempt"]
    refreshed = execution_projection(
        criteria, config, satisfied=criteria, unsatisfied=(), stale=(),
        receipt_ids={key: key for key in criteria}, receipt_gate_complete=True,
        receipt_observed_at={"api": 20, "consumer": 40, "integration": 30, "docs": 5},
    )
    assert refreshed["dependency_stale_criteria"] == ["integration"]
    complete = execution_projection(
        criteria, config, satisfied=criteria, unsatisfied=(), stale=(),
        receipt_ids={key: key for key in criteria}, receipt_gate_complete=True,
        receipt_observed_at={"api": 20, "consumer": 40, "integration": 50, "docs": 5},
    )
    assert complete["ready_for_completion_attempt"]


def test_evidence_progress_detects_repeated_failures_only_for_current_scope():
    from types import SimpleNamespace

    from local_ai_hub.verified_execution import consecutive_failed_verifications, evidence_progress

    def receipt(receipt_id, observed_at, *, passed=False, criterion="review", revision="rev", generation=1, owner="agent"):
        return SimpleNamespace(receipt_id=receipt_id, observed_at=observed_at, passed=passed,
                               criterion=criterion, repository_revision=revision,
                               mutation_generation=generation, owner=owner)

    attempts = [receipt("other", 100, criterion="other"), receipt("foreign", 99, owner="other"),
                receipt("three", 98), receipt("three", 98), receipt("two", 96),
                receipt("old-revision", 95, revision="old"), receipt("one", 94),
                receipt("passed", 93, passed=True), receipt("before-success", 92)]
    kwargs = dict(criterion="review", now=100, repository_revision="rev",
                  mutation_generation=1, valid_owners={"agent"})
    count = consecutive_failed_verifications(attempts, **kwargs)
    assert count == 3
    assert consecutive_failed_verifications([receipt("new-success", 100, passed=True), *attempts], **kwargs) == 0
    assert consecutive_failed_verifications(attempts, **{**kwargs, "mutation_generation": 2}) == 0
    assert consecutive_failed_verifications(attempts, **{**kwargs, "now": 1100}) == 0
    result = evidence_progress(created_at=90, now=100, active=True, complete=False,
                               observed_receipt_times=[], repeated_failure_count=count)
    assert result["status"] == "repeated_failed_verification"
    assert result["consecutive_failed_verifications"] == 3
    assert evidence_progress(created_at=90, now=100, active=True, complete=True,
                             observed_receipt_times=[], repeated_failure_count=count)["status"] == "recent_or_not_active"


def test_verified_execution_seeded_graph_benchmark():
    from tools.benchmark_verified_execution import run_benchmark

    result = run_benchmark(seed=17, trials=8, obligations=64)
    graph = result["metrics"]["graph"]
    baseline = result["metrics"]["receipt_only"]
    assert graph["false_positive"] == graph["false_negative"] == 0
    assert graph["recall_ppm"] == graph["precision_ppm"] == 1_000_000
    assert baseline["false_negative"] > 0
    assert result["compact_resume_estimated_tokens"] < result["full_contract_estimated_tokens"]
    assert result["graph_projection_seconds"] >= 0


def test_verified_execution_checkpoint_pattern_is_bounded_and_resets_on_evidence():
    from types import SimpleNamespace
    from local_ai_hub.execution_progress import (
        PROGRESS_STATE_KEY, observe_checkpoint, repeated_checkpoint_count,
    )
    from local_ai_hub.verified_execution import evidence_progress

    task = SimpleNamespace(owner="agent", verification_receipts={},
                           checkpoint=SimpleNamespace(state_data={"contract_revision": 1}))
    checkpoint = SimpleNamespace(phase="review", next_action="a", affected_paths=("a.py",),
                                 evidence_ids=(), blockers=())
    for i in range(8):
        checkpoint.next_action = "a" if i % 2 else "b"
        task.checkpoint.state_data[PROGRESS_STATE_KEY] = observe_checkpoint(
            task, checkpoint, now=100 + i, idempotency_key=str(i),
        )
    assert repeated_checkpoint_count(task, now=108) == 4
    assert evidence_progress(created_at=100, now=108, active=True, complete=False,
                             observed_receipt_times=[], repeated_checkpoint_count=4)["status"] == "repeated_checkpoint_pattern"
    replay = observe_checkpoint(task, checkpoint, now=109, idempotency_key="7")
    assert len(replay["samples"]) == 8
    assert replay == task.checkpoint.state_data[PROGRESS_STATE_KEY]
    assert repeated_checkpoint_count(task, now=2000) == 0
    task.verification_receipts["a"] = "new-receipt"
    assert repeated_checkpoint_count(task, now=109) == 0
    new_epoch = observe_checkpoint(task, checkpoint, now=110)
    assert len(new_epoch["samples"]) == 1


def test_verified_execution_graph_steering_rejects_weakening_and_confirmation_cycles():
    from local_ai_hub.execution_problems import record_problem
    from local_ai_hub.execution_steering import revise_graph, revision_proof_cutoffs

    contract = GoalContract("review", acceptance_criteria=("a", "b", "c"),
                            slo_profile={"verified_execution": {"units": {
                                "c": {"depends_on": ["b"], "evidence_type": "source_review"},
                            }}})
    registry = record_problem({}, {"id": "problem", "title": "problem", "criterion": "a",
                                   "resolution_criterion": "b"},
                              criteria=contract.acceptance_criteria, receipt_ids={},
                              reporter="agent", now=1)
    for patch in (
        {"units": {"a": {"depends_on": ["c"]}}},
        {"units": {"c": {"depends_on": []}}},
        {"units": {"c": {"evidence_type": "test"}}},
        {"add_criteria": ["a"]},
        {"units": {"missing": {"priority": 1}}},
    ):
        with pytest.raises(ValueError):
            revise_graph(contract, patch, problems=registry)
    revised, retired = revise_graph(contract, {"add_criteria": ["d"],
                                                "units": {"a": {"depends_on": ["d"]}}},
                                    problems=registry)
    assert revised.acceptance_criteria == ("a", "b", "c", "d")
    assert retired == {"a", "b", "c", "d"}
    _, retired = revise_graph(contract, {"units": {"a": {"priority": 90}}}, problems=registry)
    assert not retired
    assert revision_proof_cutoffs([
        {"recorded_at": 10, "retired_criteria": ["a", "b"]},
        {"recorded_at": 20, "retired_criteria": ["a", "c"]},
        {"recorded_at": 30},
    ]) == {"a": 20.0, "b": 10.0, "c": 20.0}


def test_ci_provider_assets_cleanup_rejects_changed_or_added_assets(tmp_path):
    from tools.ci_provider_assets import cleanup, snapshot

    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / ".gitkeep").touch()
    asset = generated / "instructions.md"
    asset.write_text("expected", encoding="utf-8")
    baseline = snapshot(tmp_path)
    asset.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed during tests"):
        cleanup(tmp_path, baseline)
    assert asset.exists()
    asset.write_text("expected", encoding="utf-8")
    extra = generated / "unexpected.json"
    extra.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="changed during tests"):
        cleanup(tmp_path, baseline)
    assert extra.exists() and asset.exists()
    extra.unlink()
    cleanup(tmp_path, baseline)
    assert not asset.exists()
    assert (generated / ".gitkeep").exists()
