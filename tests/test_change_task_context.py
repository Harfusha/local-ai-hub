from __future__ import annotations

from types import SimpleNamespace

from local_ai_hub.change_task_context import attach_task_context, task_verification_candidates


def test_task_receipts_are_current_candidates_not_commit_proof(tmp_path):
    task = SimpleNamespace(
        task_id="task-1", checkpoint=SimpleNamespace(affected_paths=("src/a.py",)),
        contract=SimpleNamespace(goal="change a"),
    )
    receipt = SimpleNamespace(passed=True, repository_revision="r1", criterion="test", receipt_id="receipt-current")
    stale = SimpleNamespace(passed=True, repository_revision="r0", criterion="test", receipt_id="receipt-stale")
    verification = SimpleNamespace(completion=lambda task_id, current_revision: SimpleNamespace(
        complete=True, satisfied_criteria=("test",), unsatisfied_criteria=(), stale_criteria=(),
        receipts=(receipt, stale),
    ))
    service = SimpleNamespace(
        repo_state=SimpleNamespace(fingerprint=lambda root, force: {"fingerprint": "r1"}),
        verification_store=verification,
    )
    result = {"success": True, "clusters": [{"files": ["src/a.py"]}, {"files": ["src/b.py"]}]}
    attach_task_context(service, result, [task], str(tmp_path), revision_before="r1", truncated=False)
    match = result["clusters"][0]["task_candidates"][0]
    assert match["verification"]["receipt_ids"] == ["receipt-current"]
    assert match["verification"]["commit_verified"] is False
    assert not result["clusters"][1]["task_candidates"]
    assert result["task_context"]["commit_receipt_reuse_authorized"] is False
    assert task_verification_candidates(service, task, "")["status"] == "unknown"


def test_index_impact_hints_remain_bounded_and_non_authoritative():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from local_ai_hub.change_task_context import attach_index_impact

    index = MagicMock()
    index.impact.return_value = {
        "success": True, "root": "/repo", "indexed_changed_files": 1, "truncated": False,
        "likely_dependents": [{"path": "consumer.py"}, {"path": "source.py"}, {"path": "../outside.py"}],
        "suggested_tests": [{"path": "tests/test_source.py"}, {"path": "/outside.py"}],
    }
    plan = {"success": True, "clusters": [{"group_key": "group-source", "files": ["source.py"]}],
            "dependency_plan": {"coverage": {"complete": False}}}
    attach_index_impact(SimpleNamespace(code_index=index), plan, "/repo")
    hints = plan["indexed_impact"]
    assert hints["dependent_paths"] == ["consumer.py"]
    assert hints["test_paths"] == ["tests/test_source.py"]
    assert hints["freshness"] == "not_checked"
    assert not hints["complete"] and not hints["dependencies_verified"]
    assert not hints["verification_reuse_authorized"]
    index.impact.assert_called_once_with("/repo", ["source.py"], max_symbols=48, max_dependents=24, verify_freshness=True)
    index.impact.return_value["freshness"] = {"status": "stale_candidates", "stale_paths": ["consumer.py", "../outside.py"],
                                              "unknown_paths": ["source.py"], "omitted_path_count": 0}
    attach_index_impact(SimpleNamespace(code_index=index), plan, "/repo")
    assert plan["indexed_impact"]["freshness"] == "stale_candidates"
    assert plan["indexed_impact"]["stale_candidate_paths"] == ["consumer.py"]
    assert plan["indexed_impact"]["unknown_candidate_paths"] == ["source.py"]
    assert plan["dependency_plan"]["unchanged_consumer_candidates"]["candidates"][0]["freshness"] == "stale_candidate"
    index.impact.return_value["root"] = "/other"
    attach_index_impact(SimpleNamespace(code_index=index), plan, "/repo")
    assert plan["indexed_impact"]["status"] == "unavailable"


def test_index_impact_adds_unchanged_consumers_as_uncertain_dependency_evidence():
    from unittest.mock import MagicMock
    from local_ai_hub.change_task_context import attach_index_impact

    index = MagicMock()
    index.impact.return_value = {
        "success": True, "root": "/repo", "indexed_changed_files": 1, "truncated": False,
        "changed_symbols": [{"name": "parse_item", "path": "src/parser.py"}],
        "likely_dependents": [{"path": "src/consumer.py", "symbols": ["parse_item"]}],
        "suggested_tests": [],
        "freshness": {"status": "verified_current_candidates", "stale_paths": [], "unknown_paths": []},
    }
    plan = {
        "success": True,
        "clusters": [{"group_key": "group-parser", "files": ["src/parser.py"]}],
        "dependency_plan": {"coverage": {"complete": False}},
    }

    attach_index_impact(SimpleNamespace(code_index=index), plan, "/repo")

    evidence = plan["dependency_plan"]["unchanged_consumer_candidates"]
    assert evidence["complete"] is False
    assert evidence["candidates"] == [{
        "path": "src/consumer.py", "symbols": ["parse_item"],
        "source_group_keys": ["group-parser"], "freshness": "verified_current_candidate",
        "certainty": "uncertain_candidate",
    }]
    assert plan["dependency_plan"]["coverage"]["complete"] is False


def test_index_impact_freshness_checks_content_and_generation_without_claiming_closure():
    from unittest.mock import MagicMock

    from local_ai_hub.code_index_impact import CodeIndexImpactMixin

    index = MagicMock()
    index._candidate_freshness.return_value = {"status": "verified_current_candidates"}
    index._cache_generation.return_value = 9
    result = {"root": "/repo", "likely_dependents": [{"path": "consumer.py"}],
              "suggested_tests": [{"path": "tests/test_source.py"}]}
    observed = CodeIndexImpactMixin._verify_impact_candidates(index, result, ["source.py"], 9)
    assert observed["freshness"]["status"] == "verified_current_candidates"
    assert observed["freshness"]["complete"] is False
    index._candidate_freshness.assert_called_once_with("/repo", ["source.py", "consumer.py", "tests/test_source.py"], content_hash=True)
    index._candidate_freshness.return_value = {"status": "verified_current_candidates"}
    index._cache_generation.return_value = 10
    assert CodeIndexImpactMixin._verify_impact_candidates(index, result, ["source.py"], 9)["freshness"]["status"] == "index_changed_during_verification"
    index._candidate_freshness.return_value = {"status": "verified_current_candidates"}
    index._cache_generation.return_value = 9
    changed = [f"src/{i}.py" for i in range(64)]
    freshness = CodeIndexImpactMixin._verify_impact_candidates(index, result, changed, 9)["freshness"]
    assert freshness["status"] == "verification_incomplete"
    assert freshness["omitted_path_count"] == 16
