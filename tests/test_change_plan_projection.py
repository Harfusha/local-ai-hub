from __future__ import annotations

from local_ai_hub.change_plan_projection import project_change_plan


def _result():
    return {"success": True, "cluster_count": 10, "clusters": [
        {"cluster_id": i, "name": f"group {i}", "summary": "changed",
         "suggested_commit_message": "chore: update component", "files": ["a.py"] * 10,
         "verification_status": "unknown"} for i in range(10)
    ], "unavailable_patch_scopes": [{"path": "a.py"}] * 12}


def test_bounded_projection_preserves_omission_counts():
    result = project_change_plan(_result(), limit=3, offset=3)
    assert [g["cluster_id"] for g in result["clusters"]] == [3, 4, 5]
    assert result["clusters"][0]["files_omitted"] == 4
    assert result["unavailable_patch_scopes_omitted"] == 4
    assert result["next_offset"] == 6
    assert result["has_more"] is True
    assert result["commit_ready"] is False


def test_model_advice_is_separate_and_invalid_output_fails_closed():
    def delegate(args):
        return {"success": True, "text": '{"messages":[{"id":0,"message":"chore: update payment"}]}'}
    result = project_change_plan(_result(), mode="semantic", limit=1, delegate=delegate)
    group = result["clusters"][0]
    assert group["model_commit_message"] == "chore: update payment"
    assert group["suggested_commit_message"] == "chore: update component"
    assert group["verification_status"] == "unknown"
    rejected = project_change_plan(_result(), mode="semantic", limit=2, delegate=delegate)
    assert rejected["model_advice_status"] == "invalid"
    assert "model_commit_message" not in rejected["clusters"][0]



def test_local_model_proposes_complete_nonoverlapping_partition():
    import json

    def delegate(args):
        return {"success": True, "text": json.dumps({
            "messages": [{"id": 0, "message": "chore: update payment"}, {"id": 1, "message": "test: update tests"}],
            "groups": [{"ids": [0, 1], "summary": "Payment and test updates", "message": "chore: update payment and tests"}],
        })}

    result = project_change_plan(_result(), mode="semantic", limit=2, delegate=delegate)
    assert result["model_advice_status"] == "available"
    assert result["semantic_group_proposals"][0]["cluster_ids"] == [0, 1]
    assert result["semantic_group_scope"] == "current_page_only"
    assert not result["semantic_group_proposals"][0]["commit_ready"]


def test_model_partition_rejects_missing_and_duplicate_ids():
    import json

    for ids in ([0], [0, 0], [0, 2]):
        def delegate(args):
            return {"success": True, "text": json.dumps({
                "messages": [{"id": 0, "message": "chore: update payment"}, {"id": 1, "message": "test: update tests"}],
                "groups": [{"ids": ids, "summary": "Payment updates", "message": "chore: update payment"}],
            })}
        result = project_change_plan(_result(), mode="semantic", limit=2, delegate=delegate)
        assert result["model_advice_status"] == "invalid"
        assert not result["semantic_group_proposals"]


def test_change_plan_artifact_omits_task_candidates():
    from local_ai_hub.change_plan_artifact import publish_change_plan
    from unittest.mock import MagicMock

    source = {"success": True, "clusters": [{"files": ["a.py"], "task_candidates": [{"goal": "private"}]}],
              "task_context": {"linked_task_count": 1}, "commit_ready": True}
    store = MagicMock()
    store.put_json.return_value = "art_example"
    output = publish_change_plan(source, store)
    assert output["artifact_id"] == "art_example"
    payload = store.put_json.call_args.args[0]
    assert "task_context" not in payload
    assert "task_candidates" not in payload["clusters"][0]
    assert payload["commit_ready"] is False
    assert output["commit_ready"] is False


def test_delta_projects_changed_content_and_counts_removed_groups():
    from local_ai_hub.change_plan_delta import change_delta, remember_baseline

    class Cache:
        data = {}
        def set(self, key, value):
            self.data[key] = value
        def get(self, key):
            return self.data.get(key)

    def group(key, atom):
        return {"group_key": key * 64, "observed_atom_ids": [atom * 64],
                "files": [key + ".py"], "summary": "change", "cluster_id": 1}
    base = {"success": True, "root": "/repo", "comparison": None,
            "inventory_scope": "git_visible_changes", "git_visible_observation_complete": True,
            "observed_change_set_id": "1" * 64,
            "clusters": [group("a", "a"), group("b", "b"), group("c", "c")]}
    cache = Cache()
    assert remember_baseline(base, cache)
    now = {**base, "observed_change_set_id": "2" * 64,
           "clusters": [group("a", "a"), group("b", "d")]}
    result = change_delta(now, cache, "1" * 64, limit=4, offset=0)
    assert result["success"]
    assert result["unchanged_content_group_count"] == 1
    assert result["changed_group_count"] == 1
    assert result["removed_group_count"] == 1
    assert [g["group_key"] for g in result["clusters"]] == ["b" * 64]
    assert not result["commit_ready"]
    assert not change_delta({**now, "root": "/other"}, cache, "1" * 64, limit=4, offset=0)["success"]


def test_delta_reprojects_transitive_consumers_when_prerequisite_changes():
    from local_ai_hub.change_plan_delta import change_delta, remember_baseline

    class Cache:
        def __init__(self):
            self.data = {}
        def set(self, key, value):
            self.data[key] = value
        def get(self, key):
            return self.data.get(key)

    def group(key, atom, dependencies=()):
        return {"group_key": key * 64, "observed_atom_ids": [atom * 64],
                "files": [key + ".py"], "cluster_id": 1,
                "dependency_group_candidates": [dep * 64 for dep in dependencies]}
    base = {"success": True, "root": "/repo", "comparison": None,
            "inventory_scope": "git_visible_changes", "git_visible_observation_complete": True,
            "observed_change_set_id": "1" * 64,
            "clusters": [group("a", "a"), group("b", "b", ("a",)),
                         group("c", "c", ("b",)), group("d", "d")]}
    cache = Cache()
    assert remember_baseline(base, cache)
    current = {**base, "observed_change_set_id": "2" * 64,
               "clusters": [group("a", "e"), *base["clusters"][1:]]}
    result = change_delta(current, cache, "1" * 64, limit=8, offset=0)
    assert result["success"]
    assert result["changed_group_count"] == 3
    assert result["content_changed_group_count"] == 1
    assert result["dependency_context_only_changed_group_count"] == 2
    assert result["unchanged_content_group_count"] == 3
    assert [group["group_key"] for group in result["clusters"]] == [key * 64 for key in "abc"]
    assert result["verification_status"] == "unknown"


def test_delta_pages_all_deleted_groups_even_without_changed_groups():
    from local_ai_hub.change_plan_delta import change_delta, remember_baseline

    class Cache:
        def __init__(self):
            self.values = {}

        def get(self, key):
            return self.values.get(key)

        def set(self, key, value):
            self.values[key] = value

    cache = Cache()
    groups = [{"group_key": f"{index:064x}", "observed_atom_ids": [f"{index + 100:064x}"]}
              for index in range(1, 21)]
    old = {"success": True, "root": "/repo", "comparison": None,
           "inventory_scope": "git_visible_changes", "git_visible_observation_complete": True,
           "observed_change_set_id": "a" * 64, "clusters": groups}
    assert remember_baseline(old, cache)
    current = {**old, "observed_change_set_id": "b" * 64, "clusters": []}
    offset = 0
    continuation_revision = None
    collected = []
    for _ in range(5):
        page = change_delta(current, cache, old["observed_change_set_id"], limit=8, offset=offset,
                            continuation_revision=continuation_revision)
        assert page["success"]
        assert page["changed_group_count"] == 0
        assert page["removed_group_count"] == 20
        collected.extend(page["removed_group_keys"])
        if not page["has_more"]:
            assert page["next_offset"] is None
            break
        offset = page["next_offset"]
        continuation_revision = page["continuation_revision"]
    assert collected == sorted(group["group_key"] for group in groups)


def test_delta_reports_review_and_verification_changes_without_content_changes():
    from local_ai_hub.change_plan_delta import change_delta, remember_baseline

    class Cache:
        def __init__(self):
            self.values = {}
        def get(self, key):
            return self.values.get(key)
        def set(self, key, value):
            self.values[key] = value

    cache = Cache()
    group = {"group_key": "a" * 64, "observed_atom_ids": ["b" * 64], "files": ["a.py"],
             "verification_status": "unknown", "risks": ["review_not_verified"],
             "task_candidates": [{"task_id": "task-1", "verification": {"status": "unknown"}}]}
    old = {"success": True, "root": "/repo", "comparison": None,
           "inventory_scope": "git_visible_changes", "git_visible_observation_complete": True,
           "observed_change_set_id": "1" * 64, "clusters": [group]}
    assert remember_baseline(old, cache)
    current = {**old, "observed_change_set_id": "2" * 64, "clusters": [{
        **group, "verification_status": "verified", "risks": [],
        "task_candidates": [{"task_id": "task-1", "verification": {"status": "task_completion_current"}}],
    }]}

    result = change_delta(current, cache, old["observed_change_set_id"], limit=8, offset=0)

    assert result["content_changed_group_count"] == 0
    assert result["dependency_context_only_changed_group_count"] == 0
    assert result["review_verification_changed_group_count"] == 1
    assert result["clusters"][0]["verification_status"] == "verified"
    assert result["clusters"][0]["task_candidates"][0]["verification"]["status"] == "task_completion_current"
    assert result["commit_ready"] is False


def test_delta_requires_matching_current_revision_for_continuation_pages():
    from local_ai_hub.change_plan_delta import change_delta, remember_baseline

    class Cache:
        def __init__(self):
            self.values = {}
        def get(self, key):
            return self.values.get(key)
        def set(self, key, value):
            self.values[key] = value

    cache = Cache()
    old_groups = [{"group_key": f"{i:064x}", "observed_atom_ids": [f"{i + 100:064x}"], "files": [f"{i}.py"]}
                  for i in range(1, 4)]
    old = {"success": True, "root": "/repo", "comparison": None,
           "inventory_scope": "git_visible_changes", "git_visible_observation_complete": True,
           "observed_change_set_id": "1" * 64, "clusters": old_groups}
    current = {**old, "observed_change_set_id": "2" * 64,
               "clusters": [{**group, "observed_atom_ids": [f"{i + 200:064x}"]}
                            for i, group in enumerate(old_groups, 1)]}
    assert remember_baseline(old, cache)

    first = change_delta(current, cache, old["observed_change_set_id"], limit=1, offset=0)
    assert isinstance(first["continuation_revision"], str)
    assert first["continuation_revision"] != current["observed_change_set_id"]
    missing = change_delta(current, cache, old["observed_change_set_id"], limit=1, offset=1)
    stale = change_delta({**current, "observed_change_set_id": "3" * 64}, cache,
                         old["observed_change_set_id"], limit=1, offset=1,
                         continuation_revision="3" * 64)
    page = change_delta(current, cache, old["observed_change_set_id"], limit=1, offset=1,
                        continuation_revision=first["continuation_revision"])

    assert missing["success"] is False
    assert stale["success"] is False
    assert page["success"] is True
    assert page["clusters"][0]["group_key"] == current["clusters"][1]["group_key"]


def test_split_changes_contract_exposes_scoped_delta_continuation_revision():
    from local_ai_hub.operation_contracts import operation_contract, operation_tool_input_schema

    schema = operation_tool_input_schema("local_ai_repo")
    split_changes_inputs = operation_contract("local_ai_repo")["actions"]["split_changes"]["allowed"]

    assert "continuation_revision" in schema["properties"]
    assert "continuation_revision" in split_changes_inputs


def test_mcp_split_changes_forwards_delta_continuation_revision(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.mcp_tools_repo import local_ai_repo

    captured = {}

    def post(path, payload, timeout=None):
        captured.update(path=path, payload=payload)
        return {"success": True, "continuation_revision": "c" * 64, "commit_ready": False}

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = local_ai_repo(
        action="split_changes", root=str(tmp_path), mode="delta", limit=8, offset=8,
        expected_revision="a" * 64, continuation_revision="b" * 64,
    )

    assert captured["path"] == "/api/repo/split_changes"
    assert captured["payload"]["changed_paths"] is None
    assert "paths" not in captured["payload"]
    assert "changed_files" not in captured["payload"]
    assert captured["payload"]["expected_revision"] == "a" * 64
    assert captured["payload"]["continuation_revision"] == "b" * 64
    assert result["continuation_revision"] == "c" * 64


def test_change_plan_artifact_does_not_export_private_local_provenance():
    from unittest.mock import MagicMock

    from local_ai_hub.change_plan_artifact import publish_change_plan

    source = {"success": True, "watcher_context": {"private": "watcher"}, "broker_postimage_context": {},
              "indexed_impact": {"private": "index"}, "clusters": [
        {"files": ["a.py"], "watcher_candidate_paths": 1, "broker_postimage_candidate_paths": 1,
         "changes": [{"path": "a.py", "watcher_candidate": {"observed_at": 1},
                      "broker_postimage_candidate": {"task_id": "private-task", "attempt_id": "private-attempt"},
                      "atoms": [{"atom_id": "a" * 64, "local_annotations": [{"actor": "private-actor"}]}]}]}
    ]}
    store = MagicMock()
    store.put_json.return_value = "art_example"
    assert publish_change_plan(source, store)["success"]
    payload = store.put_json.call_args.args[0]
    assert "private" not in str(payload)
    assert "broker_postimage_context" not in payload
    assert "watcher_context" not in payload
    assert payload["clusters"][0]["changes"][0]["atoms"] == [{"atom_id": "a" * 64}]
    assert source["clusters"][0]["changes"][0]["broker_postimage_candidate"]["task_id"] == "private-task"


def test_change_plan_artifact_rejects_non_utf8_metadata_without_storage():
    from unittest.mock import MagicMock

    from local_ai_hub.change_plan_artifact import publish_change_plan

    store = MagicMock()
    result = publish_change_plan({"success": True, "clusters": [{"files": ["invalid-" + chr(0xDCFF)]}]}, store)
    assert not result["success"] and not result["commit_ready"]
    store.put_json.assert_not_called()
