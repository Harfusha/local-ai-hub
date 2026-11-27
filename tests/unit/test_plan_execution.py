from local_ai_hub.plan_execution import partition_coverage


def config(index, digest="a" * 64, checks=None):
    return {"inventory": {"checks": checks or ["review"], "partition": {
        "manifest_sha256": digest, "size": 10, "total": 3, "index": index,
    }}}


def test_partitions_require_full_disjoint_manifest():
    assert partition_coverage([config(0), config(1), config(2)])[0]["complete"]
    result = partition_coverage([config(0), config(2), config(2)])[0]
    assert not result["complete"]
    assert result["missing_preview"] == [1]
    assert result["duplicate_count"] == 1


def test_partitions_never_combine_different_checks_or_manifests():
    groups = partition_coverage([config(0), config(1, checks=["test"]),
                                 config(2, digest="b" * 64)])
    assert len(groups) == 3
    assert not any(group["complete"] for group in groups)


def test_partitions_never_combine_different_exclusion_reasons():
    first, second, third = config(0), config(1), config(2)
    for item in (first, second):
        item["inventory"]["exclusions"] = [{"path": "a.py", "reason": "generated"}]
    third["inventory"]["exclusions"] = [{"path": "a.py", "reason": "out of scope"}]
    groups = partition_coverage([first, second, third])
    assert len(groups) == 2
    assert not any(group["complete"] for group in groups)


def test_partitions_never_combine_different_static_import_policies():
    first, second, third = config(0), config(1), config(2)
    first["inventory"]["include_python_imports"] = True
    second["inventory"]["include_python_imports"] = True
    groups = partition_coverage([first, second, third])
    assert len(groups) == 2
    assert not any(group["complete"] for group in groups)


def test_partition_presence_does_not_imply_verified_coverage():
    configs = [config(0), config(1), config(2)]
    result = partition_coverage(configs, verified=[True, False, True])[0]
    assert result["complete"]
    assert not result["verified_complete"]
    assert result["verified_partitions"] == 2
    assert result["unverified_preview"] == [1]
    assert partition_coverage(configs, verified=[True] * 3)[0]["verified_complete"]


def test_duplicate_verified_partitions_do_not_complete_manifest():
    result = partition_coverage([config(0), config(1), config(2), config(2)],
                                verified=[True] * 4)[0]
    assert result["verified_partitions"] == 3
    assert not result["verified_complete"]


def test_plan_preview_aggregates_only_available_obligation_coverage(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from local_ai_hub import agent_tasks, verification_rules
    from local_ai_hub.repo_plan import agent_bridge
    from local_ai_hub.plan_execution import plan_execution_preview

    root = str(tmp_path)
    spec = {"acceptance_criteria": ["inspect"], "work_status": "done"}
    snapshot = {"plan": {"tasks": {"a": spec, "b": spec}}, "file_revision": "plan-rev",
                "rel_path": "plan.json"}
    workspace = SimpleNamespace(repo_root=tmp_path, get_plan=lambda _: snapshot)
    task = SimpleNamespace(
        contract=SimpleNamespace(acceptance_criteria=("inspect",), slo_profile={"verified_execution": {}}),
        context=SimpleNamespace(session_id="session"), checkpoint=SimpleNamespace(state_data={}),
        status=SimpleNamespace(value="completed"),
    )
    binding = SimpleNamespace(plan_task_id="a", task_id="task-a", bound_at=1,
                              plan_rel_path="plan.json", session_id="session", contract_revision=1)
    monkeypatch.setattr(agent_tasks, "_task_scope_root", lambda _: root)
    monkeypatch.setattr(agent_bridge, "TaskBindingManager",
                        lambda _: SimpleNamespace(bindings_for_plan=lambda _: [binding]))
    monkeypatch.setattr(verification_rules, "evaluate_project_completion",
                        lambda *args, **kwargs: SimpleNamespace(complete=True, execution={
                            "coverage": {"total": 1, "verified": 1},
                            "dimensions": {"general": {"total": 1, "verified": 1}},
                        }))
    store = SimpleNamespace(get=lambda key: task if key == "task-a" else None)
    verifier = SimpleNamespace(state_store=SimpleNamespace(db_path=tmp_path / "state.sqlite"))
    tracker = SimpleNamespace(fingerprint=lambda *args, **kwargs: {"fingerprint": "repo-rev"})
    result = plan_execution_preview(workspace, "plan", store, verifier, tracker)
    assert not result["complete"]
    assert result["counts"] == {"verified": 1, "unbound": 1}
    aggregate = result["obligation_coverage"]
    assert aggregate["partial"]
    assert aggregate["tasks_with_coverage"] == 1
    assert aggregate["counts"]["verified"] == aggregate["counts"]["total"] == 1
    assert aggregate["dimensions"] == {"general": {"total": 1, "verified": 1}}


def test_plan_actionability_requires_verified_local_dependencies_and_defers_external():
    from local_ai_hub.plan_execution import plan_actionability

    tasks = {
        "api": {"depends_on": [], "work_status": "done"},
        "consumer": {"depends_on": [{"plan_id": "p", "task_id": "api"}]},
        "integration": {"depends_on": [{"plan_id": "p", "task_id": "consumer"}]},
        "external": {"depends_on": [{"plan_id": "other", "task_id": "done"}]},
        "blocked": {"depends_on": [], "work_status": "blocked"},
        "conflict": {"depends_on": []},
        "cancelled": {"depends_on": [], "work_status": "cancelled"},
    }
    statuses = {"api": "verified", "consumer": "incomplete", "conflict": "binding_conflict"}
    rows = [{"plan_task_id": key, "status": statuses.get(key, "unbound")} for key in tasks]
    result = plan_actionability("p", tasks, rows)
    assert result["ready_count"] == 1
    assert result["next_plan_task"]["plan_task_id"] == "consumer"
    assert result["waiting_count"] == 4
    waiting = {row["plan_task_id"]: row for row in result["waiting_preview"]}
    assert waiting["external"]["waiting_preview"][0]["reason"] == "external_plan_unchecked"
    assert waiting["integration"]["waiting_preview"][0]["reason"] == "local_dependency_unverified"
    assert waiting["conflict"]["reason"] == "task_blocked_or_binding_conflict"
    rows[0]["status"] = "incomplete"
    assert plan_actionability("p", tasks, rows)["next_plan_task"]["plan_task_id"] == "api"
