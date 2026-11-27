from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.split_changes import run_split_changes


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _plan(root: Path, paths=None, cache=None, **comparison):
    return run_split_changes(
        SimpleNamespace(_root=lambda value: value, git_status_timeout=10, _change_summary_cache=cache),
        str(root), paths, path_type=Path, subprocess_module=subprocess,
        hidden_run_kwargs_fn=lambda: {}, **comparison,
    )


def _repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "tests").mkdir()
    for path in ("payment.py", "tests/test_payment.py", "cache.py"):
        (root / path).write_text("original\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")


def test_same_name_test_is_not_assumed_to_share_a_change_group(tmp_path):
    _repo(tmp_path)
    (tmp_path / "payment.py").write_text("staged\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    (tmp_path / "payment.py").write_text("unstaged\n", encoding="utf-8")
    (tmp_path / "tests/test_payment.py").write_text("test changed\n", encoding="utf-8")
    (tmp_path / "cache.py").write_text("cache changed\n", encoding="utf-8")
    (tmp_path / "new file.py").write_text("new\n", encoding="utf-8")
    before = _git(tmp_path, "diff", "--cached", "--binary")
    result = _plan(tmp_path)
    assert result["success"]
    assert result["total_files"] == 4
    assert result["cluster_count"] == 4
    payment = next(g for g in result["clusters"] if "payment.py" in g["files"])
    assert payment["files"] == ["payment.py"]
    test = next(g for g in result["clusters"] if "tests/test_payment.py" in g["files"])
    assert test["files"] == ["tests/test_payment.py"]
    assert "mixed_staged_unstaged" in payment["risks"]
    assert payment["changes"][0]["staged_lines"] == [1, 1]
    assert payment["changes"][0]["unstaged_lines"] == [1, 1]
    assert result["commit_ready"] is False
    assert _git(tmp_path, "diff", "--cached", "--binary") == before
    assert _plan(tmp_path)["clusters"] == result["clusters"]


def test_clean_invalid_and_scoped(tmp_path):
    assert not _plan(tmp_path)["success"]
    _repo(tmp_path)
    assert _plan(tmp_path)["clusters"] == []
    (tmp_path / "cache.py").write_text("changed\n", encoding="utf-8")
    assert _plan(tmp_path, ["cache.py"])["total_files"] == 1
    assert not _plan(tmp_path, ["missing.py"])["success"]


def test_non_git_explicit_paths_fail_closed(tmp_path):
    result = _plan(tmp_path, ["src/main.py", "tests/test_main.py"])

    assert result["success"] is False
    assert result["error"] == "Git inventory unavailable"
    assert "clusters" not in result


def test_retired_commit_synthesis_contract_is_not_exposed():
    from local_ai_hub.operation_contracts import operation_actions
    from local_ai_hub.http_route_registry import POST_ROUTE_REGISTRY
    from local_ai_hub.services import LocalAIServices

    assert "synthesize_commit" not in operation_actions("local_ai_repo")
    assert all("/api/git/synthesize_commit" not in route.paths for route in POST_ROUTE_REGISTRY)
    assert not hasattr(LocalAIServices, "synthesize_commit")


def test_ambiguous_test_stays_separate(tmp_path):
    _repo(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other/payment.py").write_text("original\n", encoding="utf-8")
    _git(tmp_path, "add", "other/payment.py")
    _git(tmp_path, "commit", "-m", "second")
    for path in ("payment.py", "other/payment.py", "tests/test_payment.py"):
        (tmp_path / path).write_text("changed\n", encoding="utf-8")
    assert _plan(tmp_path)["cluster_count"] == 3


def test_content_identity_changes_with_same_line_counts(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("first\n", encoding="utf-8")
    first = _plan(tmp_path)
    second = _plan(tmp_path)
    assert second["summary_cache_hits"] >= 1
    assert first["observed_change_set_id"] == second["observed_change_set_id"]
    group = first["clusters"][0]
    assert group["observed_hunk_count"] == 1
    path.write_text("other\n", encoding="utf-8")
    third = _plan(tmp_path)
    assert third["observed_change_set_id"] != first["observed_change_set_id"]
    assert third["clusters"][0]["group_key"] == group["group_key"]
    assert third["clusters"][0]["line_totals"] == group["line_totals"]
    assert third["verification_status"] == "unknown"


def test_patch_scopes_and_partial_coverage(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("first\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    path.write_text("other\n", encoding="utf-8")
    (tmp_path / "new.py").write_bytes(b"private content\n" * 50000)
    result = _plan(tmp_path)
    assert not result["patch_coverage_complete"]
    group = next(g for g in result["clusters"] if "payment.py" in g["files"])
    atoms = group["changes"][0]["atoms"]
    assert {a["scope"] for a in atoms} == {"staged", "unstaged"}
    assert len({a["atom_id"] for a in atoms}) == 2
    assert "private content" not in str(result)
    assert "first" not in str(atoms)


def test_persistent_metadata_cache_survives_memory_eviction(tmp_path):
    from local_ai_hub.cache import SQLiteCache
    from local_ai_hub.change_atoms import _CACHE, _LOCK

    root = tmp_path / "repo"
    root.mkdir()
    _repo(root)
    (root / "payment.py").write_text("private new value\n", encoding="utf-8")
    cache_path = tmp_path / "cache.sqlite"
    first = _plan(root, cache=SQLiteCache(cache_path, "test-hunk-cache"))
    assert first["persistent_summary_cache_hits"] == 0
    with _LOCK:
        _CACHE.clear()
    second = _plan(root, cache=SQLiteCache(cache_path, "test-hunk-cache"))
    assert second["persistent_summary_cache_hits"] == 1
    assert first["clusters"] == second["clusters"]
    assert b"private new value" not in cache_path.read_bytes()


def test_unchanged_hunk_id_survives_unrelated_edit(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    original = [f"line {i}" for i in range(20)]
    path.write_text("\n".join(original) + "\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    _git(tmp_path, "commit", "-m", "multi-line fixture")
    modified = original.copy()
    modified[2] = "first change"
    modified[17] = "second change"
    path.write_text("\n".join(modified) + "\n", encoding="utf-8")
    first = _plan(tmp_path)["clusters"][0]["changes"][0]["atoms"][0]
    modified[17] = "other change"
    path.write_text("\n".join(modified) + "\n", encoding="utf-8")
    second = _plan(tmp_path)["clusters"][0]["changes"][0]["atoms"][0]
    assert first["atom_id"] != second["atom_id"]
    assert first["hunks"][0]["hunk_id"] == second["hunks"][0]["hunk_id"]
    assert first["hunks"][1]["hunk_id"] != second["hunks"][1]["hunk_id"]


def test_malformed_persistent_cache_is_recomputed(tmp_path):
    from local_ai_hub.change_atoms import _CACHE, _LOCK

    class InvalidCache:
        def get(self, key):
            return {"schema": 2, "rows": [[1, 1, 1, 1, "invalid"]], "count": 1}

        def set(self, key, value):
            assert value.get("schema") == 2 or value.get("method") == "python_ast_v2"

    _repo(tmp_path)
    (tmp_path / "payment.py").write_text("different\n", encoding="utf-8")
    with _LOCK:
        _CACHE.clear()
    result = _plan(tmp_path, cache=InvalidCache())
    assert result["success"]
    assert result["persistent_summary_cache_hits"] == 0
    assert result["clusters"][0]["observed_hunk_count"] == 1


def test_staged_python_ast_summary_is_structural_not_verification(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("def pay():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    _git(tmp_path, "commit", "-m", "python fixture")
    path.write_text("def pay():\n    return 2\n\ndef refund():\n    return 0\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    result = _plan(tmp_path)
    group = result["clusters"][0]
    semantic = group["changes"][0]["atoms"][0]["semantic"]
    assert semantic["status"] == "observed"
    assert semantic["change_counts"] == {"modified": 1, "added": 1}
    assert group["semantic_change_counts"] == semantic["change_counts"]
    assert not semantic["behavior_equivalence_proven"]
    assert result["verification_status"] == "unknown"


def test_unstaged_python_blob_reconstruction(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "payment.py"
    path.write_text("def pay():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    _git(tmp_path, "commit", "-m", "python fixture")
    path.write_text("def pay():\n    return 987654\n", encoding="utf-8")
    result = _plan(tmp_path)
    group = result["clusters"][0]
    atom = group["changes"][0]["atoms"][0]
    assert atom["scope"] == "unstaged"
    assert atom["semantic"]["status"] == "observed"
    assert atom["semantic"]["change_counts"] == {"modified": 1}
    assert "pay" in group["suggested_commit_message"]


def test_reconstruction_requires_exact_blob_identity():
    import hashlib
    from local_ai_hub.change_semantics import reconstruct_blob

    before, after = b"old", b"new"
    oid = hashlib.sha1(b"blob 3\0" + after).hexdigest()
    patch = b"@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
    assert reconstruct_blob(before, patch, oid) == after
    assert reconstruct_blob(before, patch, "1" * 40) is None
    assert reconstruct_blob(b"different", patch, oid) is None


def test_committed_comparison_ignores_dirty_worktree(tmp_path):
    _repo(tmp_path)
    base = _git(tmp_path, "rev-parse", "HEAD").strip().decode()
    (tmp_path / "payment.py").write_text("committed\n", encoding="utf-8")
    _git(tmp_path, "add", "payment.py")
    _git(tmp_path, "commit", "-m", "payment")
    (tmp_path / "cache.py").write_text("dirty only\n", encoding="utf-8")
    result = _plan(tmp_path, base=base, head="HEAD")
    assert result["success"]
    assert result["total_files"] == 1
    assert result["comparison"]["base"] == base
    group = result["clusters"][0]
    assert group["files"] == ["payment.py"]
    assert set(group["line_totals"]) == {"committed"}
    assert group["changes"][0]["atoms"][0]["scope"] == "committed"
    assert result["commit_ready"] is False
    assert not _plan(tmp_path, base="--help", head="HEAD")["success"]


def test_observed_identity_binds_head_and_index(tmp_path):
    _repo(tmp_path)
    (tmp_path / "payment.py").write_text("changed\n", encoding="utf-8")
    first = _plan(tmp_path)
    _git(tmp_path, "commit", "--allow-empty", "-m", "new head")
    second = _plan(tmp_path)
    assert first["git_snapshot_metadata"]["head"] != second["git_snapshot_metadata"]["head"]
    assert first["observed_change_set_id"] != second["observed_change_set_id"]
    assert first["clusters"][0]["observed_atom_ids"] == second["clusters"][0]["observed_atom_ids"]


def test_untracked_identity_and_structural_summary(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "new.py"
    path.write_text("def new_feature():\n    return 1\n", encoding="utf-8")
    first = _plan(tmp_path)
    assert first["git_visible_observation_complete"], {
        "git_snapshot_metadata": first.get("git_snapshot_metadata"),
        "unavailable_patch_scopes": first.get("unavailable_patch_scopes"),
        "inventory_scope": first.get("inventory_scope"),
    }
    atom = first["clusters"][0]["changes"][0]["atoms"][0]
    assert atom["scope"] == "untracked"
    assert atom["semantic"]["change_counts"] == {"added": 1}
    assert "untracked_requires_review" in first["clusters"][0]["risks"]
    path.write_text("def new_feature():\n    return 2\n", encoding="utf-8")
    second = _plan(tmp_path)
    assert first["observed_change_set_id"] != second["observed_change_set_id"]


def test_binary_patch_identity(tmp_path):
    _repo(tmp_path)
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\0before")
    _git(tmp_path, "add", "blob.bin")
    _git(tmp_path, "commit", "-m", "binary")
    path.write_bytes(b"\0after")
    first = _plan(tmp_path)
    assert first["success"]
    group = first["clusters"][0]
    assert "binary_change" in group["risks"]
    assert group["changes"][0]["atoms"][0]["content_kind"] == "binary"
    assert first["git_visible_observation_complete"]
    path.write_bytes(b"\0other")
    assert _plan(tmp_path)["observed_change_set_id"] != first["observed_change_set_id"]


def test_import_candidate_order_and_hunk_symbol_overlap(tmp_path):
    _repo(tmp_path)
    (tmp_path / "cache.py").write_text("def get():\n    return 1\n", encoding="utf-8")
    (tmp_path / "payment.py").write_text("from cache import get\n\ndef pay():\n    return get()\n", encoding="utf-8")
    result = _plan(tmp_path)
    payment = next(g for g in result["clusters"] if "payment.py" in g["files"])
    cache = next(g for g in result["clusters"] if "cache.py" in g["files"])
    assert payment["dependency_group_candidates"] == [cache["group_key"]]
    order = result["dependency_plan"]["candidate_order"]
    assert order.index(cache["group_key"]) < order.index(payment["group_key"])
    assert not result["dependency_plan"]["dependencies_verified"]
    assert any("pay" in h["symbol_candidates"] for h in payment["changes"][0]["atoms"][0]["hunks"])


def test_import_edges_are_typed_as_uncertain_candidates():
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [
        {"group_key": "provider", "files": ["cache.py"], "risks": [],
         "changes": [{"path": "cache.py", "status": "M", "atoms": []}]},
        {"group_key": "consumer", "files": ["payment.py"], "risks": [],
         "changes": [{"path": "payment.py", "status": "M", "atoms": [{
             "semantic": {"status": "observed", "imports_after": ["cache"],
                          "imports_truncated": False, "imports_before_truncated": False}
         }]}]},
    ]

    graph = annotate_dependencies(groups)

    assert graph["hard_dependencies"] == []
    assert graph["soft_dependencies"] == []
    assert graph["uncertain_candidates"] == [{
        "source_group_key": "consumer",
        "target_group_key": "provider",
        "kind": "import_candidate",
        "evidence": [{"source": "payment.py", "target": "cache.py", "kind": "import_candidate"}],
    }]


def test_unresolved_and_ambiguous_imports_are_explicit_candidates():
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [
        {"group_key": "provider_a", "files": ["one/cache.py"], "risks": [],
         "changes": [{"path": "one/cache.py", "status": "M", "atoms": []}]},
        {"group_key": "provider_b", "files": ["two/cache.py"], "risks": [],
         "changes": [{"path": "two/cache.py", "status": "M", "atoms": []}]},
        {"group_key": "consumer", "files": ["entry.py"], "risks": [],
         "changes": [{"path": "entry.py", "status": "M", "atoms": [{
             "semantic": {"status": "observed", "imports_after": ["cache", "missing"],
                          "imports_truncated": False, "imports_before_truncated": False}
         }]}]},
    ]

    graph = annotate_dependencies(groups)

    assert graph["ambiguous_import_count"] == 1
    assert graph["unmatched_import_count"] == 1
    assert graph["unresolved_import_candidates"] == [
        {"source_group_key": "consumer", "source": "entry.py", "import_name": "cache",
         "kind": "ambiguous_import_candidate", "candidate_group_keys": ["provider_a", "provider_b"],
         "candidate_groups_omitted": 0,
         "candidate_paths": ["one/cache.py", "two/cache.py"], "candidate_paths_omitted": 0},
        {"source_group_key": "consumer", "source": "entry.py", "import_name": "missing",
         "kind": "unmatched_import_candidate", "candidate_group_keys": [],
         "candidate_groups_omitted": 0,
         "candidate_paths": [], "candidate_paths_omitted": 0},
    ]


def test_unresolved_import_removal_is_explicit_and_counted():
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [{
        "group_key": "consumer", "files": ["entry.py"], "risks": [],
        "changes": [{"path": "entry.py", "status": "M", "atoms": [{
            "semantic": {"status": "observed", "imports_before": ["missing"],
                         "imports_after": [], "imports_truncated": False,
                         "imports_before_truncated": False}
        }]}],
    }]

    graph = annotate_dependencies(groups)

    assert graph["unresolved_removed_import_count"] == 1
    assert graph["unresolved_import_candidates"] == [{
        "source_group_key": "consumer", "source": "entry.py", "import_name": "missing",
        "kind": "unmatched_import_removal_candidate", "candidate_group_keys": [],
        "candidate_groups_omitted": 0, "candidate_paths": [], "candidate_paths_omitted": 0,
    }]


def test_unresolved_import_candidate_output_is_bounded_with_omitted_count():
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [{
        "group_key": "consumer", "files": ["entry.py"], "risks": [],
        "changes": [{"path": "entry.py", "status": "M", "atoms": [{
            "semantic": {"status": "observed",
                         "imports_after": [f"missing_{index:03d}" for index in range(257)],
                         "imports_truncated": False, "imports_before_truncated": False}
        }]}],
    }]

    graph = annotate_dependencies(groups)

    assert len(graph["unresolved_import_candidates"]) == 256
    assert graph["unresolved_import_candidates_omitted"] == 1
    assert graph["unresolved_import_candidates"][0]["import_name"] == "missing_000"

def test_source_fact_delta_is_not_behavior_proof():
    from local_ai_hub.change_source_facts import summarize_facts

    def extract(path, text):
        return [{"kind": "php_class", "name": text, "value": text, "extra": {"fqn": text}}]

    result = summarize_facts("src/Foo.php", "Old", "New", extract)
    assert result["change_counts"] == {"added": 1, "removed": 1}
    assert result["structural_equivalence_unknown"]
    assert not result["behavior_equivalence_proven"]


def test_dependency_units_keep_cycles_together_and_order_dependents():
    from local_ai_hub.change_dependencies import _dependency_units

    edges = {"a": {"b"}, "b": {"a", "base"}, "base": set(), "consumer": {"a"}, "other": set()}
    units = _dependency_units(edges)
    positions = {key: index for index, unit in enumerate(units) for key in unit}
    assert sorted(key for unit in units for key in unit) == sorted(edges)
    assert ["a", "b"] in units
    assert positions["base"] < positions["a"] == positions["b"] < positions["consumer"]
    assert units == _dependency_units(dict(reversed(list(edges.items()))))
    assert _dependency_units({}) == []


def test_dependency_unit_preflight_refuses_partial_cycle_but_accepts_joint_selection():
    from local_ai_hub.change_commit_preflight import commit_preflight
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [
        {"group_key": name, "files": [name + ".py"], "risks": [],
         "changes": [{"path": name + ".py", "status": " M", "atoms": [
             {"semantic": {"imports_after": [dependency]}}
         ]}]}
        for name, dependency in (("a", "b"), ("b", "a"))
    ]
    graph = annotate_dependencies(groups)
    assert graph["candidate_commit_units"] == [["a", "b"]]
    assert graph["cyclic_unit_count"] == 1
    plan = {"success": True, "clusters": groups, "observed_change_set_id": "1" * 64,
            "git_visible_observation_complete": True}
    partial = commit_preflight(plan, ["a.py"], "1" * 64)
    assert "partial_dependency_component" in partial["blockers"]
    joint = commit_preflight(plan, ["a.py", "b.py"], "1" * 64)
    assert joint["staging_preview_available"], joint
    assert not joint["commit_ready"]


def test_dependency_removal_orders_consumer_before_deleted_provider():
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [
        {"group_key": "provider", "files": ["provider.py"], "risks": [],
         "changes": [{"path": "provider.py", "status": "D ", "atoms": []}]},
        {"group_key": "consumer", "files": ["consumer.py"], "risks": [],
         "changes": [{"path": "consumer.py", "status": "M ", "atoms": [{
             "semantic": {"status": "observed", "imports_before": ["provider"], "imports_after": [],
                          "imports_before_truncated": False, "imports_truncated": False}
         }]}]},
    ]
    graph = annotate_dependencies(groups)
    assert graph["candidate_order"] == ["consumer", "provider"]
    assert graph["removed_import_ordering_edges"] == 1
    assert groups[0]["dependency_group_candidates"] == ["consumer"]
    assert groups[0]["dependency_evidence"] == [
        {"source": "provider.py", "target": "consumer.py", "kind": "import_removal_candidate"}
    ]
    assert not graph["dependencies_verified"]


def test_remaining_import_to_deleted_provider_is_reported():
    from local_ai_hub.change_dependencies import annotate_dependencies

    groups = [
        {"group_key": "provider", "files": ["provider.py"], "risks": [],
         "changes": [{"path": "provider.py", "status": "D", "atoms": []}]},
        {"group_key": "consumer", "files": ["consumer.py"], "risks": [],
         "changes": [{"path": "consumer.py", "status": "M", "atoms": [{
             "semantic": {"status": "observed", "imports_before": ["provider"], "imports_after": ["provider"],
                          "imports_before_truncated": False, "imports_truncated": False}
         }]}]},
    ]
    graph = annotate_dependencies(groups)
    assert graph["unresolved_removed_import_count"] == 1
    assert "import_candidate_points_to_removed_path" in groups[1]["risks"]
    assert not graph["dependencies_verified"]


def test_paired_benchmark_keeps_quality_regression_visible():
    from tools.benchmark_git_change_evaluation import evaluate

    def run(input_tokens, findings, *, completed=True):
        return {"input_tokens": input_tokens, "output_tokens": 100,
                "cached_input_tokens": 0, "calls": 2, "completed": completed,
                "usage_source": "provider_reported", "finding_ids": findings}

    case = {"case_id": "review-1", "task_digest": "a" * 64, "revision": "b" * 40,
            "provider_model": "provider/model", "expected_finding_ids": ["bug-a", "bug-b"],
            "raw": run(1000, ["bug-a", "bug-b"]),
            "compact": run(500, ["bug-a", "false-positive"], completed=False)}
    result = evaluate({"schema": 1, "cases": [case]})
    assert result["input_token_difference"] == 500
    assert result["aggregate"]["raw"]["recall"] == 1
    assert result["aggregate"]["compact"]["recall"] == 0.5
    assert result["aggregate"]["compact"]["precision"] == 0.5
    assert not result["compact_no_additional_missed_findings_per_case"]
    assert not result["all_pairs_completed"]


def test_paired_benchmark_refuses_estimated_or_inconsistent_usage():
    import pytest
    from tools.benchmark_git_change_evaluation import evaluate

    run = {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 101,
           "calls": 1, "completed": True, "usage_source": "provider_reported",
           "finding_ids": []}
    case = {"case_id": "review-1", "task_digest": "a" * 64, "revision": "b" * 40,
            "provider_model": "provider/model", "expected_finding_ids": [],
            "raw": run, "compact": run}
    with pytest.raises(ValueError, match="inconsistent cached"):
        evaluate({"schema": 1, "cases": [case]})
    run["cached_input_tokens"] = 0
    run["usage_source"] = "estimated"
    with pytest.raises(ValueError, match="Provider-reported"):
        evaluate({"schema": 1, "cases": [case]})


def test_php_deleted_provider_orders_removed_import_and_reports_retained_import():
    from local_ai_hub.change_dependencies import annotate_dependencies
    from local_ai_hub.change_source_facts import summarize_facts

    def extract(path, text):
        return [{"kind": "php_class", "name": "App\\Foo", "value": text,
                 "extra": {"fqn": "App\\Foo"}}] if text else []

    provider = summarize_facts("src/Foo.php", "class Foo {}", "", extract)
    assert provider["declarations_before"] == ["App\\Foo"]
    assert provider["declarations_after"] == []
    groups = [
        {"group_key": "provider", "files": ["src/Foo.php"], "risks": [],
         "changes": [{"path": "src/Foo.php", "status": "D", "atoms": [{"semantic": provider}]}]},
        {"group_key": "consumer", "files": ["src/Use.php"], "risks": [],
         "changes": [{"path": "src/Use.php", "status": "M", "atoms": [{"semantic": {
             "status": "observed", "imports_before": ["App\\Foo"], "imports_after": [],
             "imports_before_truncated": False, "imports_truncated": False,
         }}]}]},
    ]
    graph = annotate_dependencies(groups)
    assert graph["candidate_order"] == ["consumer", "provider"]
    assert graph["removed_import_ordering_edges"] == 1
    groups[1]["changes"][0]["atoms"][0]["semantic"]["imports_after"] = ["App\\Foo"]
    graph = annotate_dependencies(groups)
    assert graph["unresolved_removed_import_count"] == 1
    assert "import_candidate_points_to_removed_path" in groups[1]["risks"]
    assert graph["dependencies_verified"] is False


def test_module_path_candidates_typescript_emitted_extensions_and_python_overshoot():
    from local_ai_hub.change_dependencies import _js_module_paths, _python_module_paths

    paths = {"src/api.ts", "src/api.js", "src/entry.mts", "src/worker.cts"}
    assert _js_module_paths("src/main.ts", "./api.js", paths) == {"src/api.ts", "src/api.js"}
    assert _js_module_paths("src/main.ts", "./entry.mjs", paths) == {"src/entry.mts"}
    assert _js_module_paths("src/main.ts", "./worker.cjs", paths) == {"src/worker.cts"}
    assert _python_module_paths("pkg/main.py", "...api", {"api.py"}) == set()


def test_patch_batch_preserves_exact_individual_bytes_and_special_filenames(tmp_path):
    import os

    from local_ai_hub.change_patch_batch import PatchBatchReader, patch_arguments, partition_patches

    _repo(tmp_path)
    names = ["a b.txt", "unicode-é.txt", "binary.dat", "delete.txt", "mode.txt"]
    if os.name != "nt":
        names += ["with\ttab", 'quote".txt', "line\nbreak"]
    for name in names:
        (tmp_path / name).write_bytes(b"\0old" if name == "binary.dat" else b"old\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "fixture")
    for name in names:
        if name == "delete.txt":
            (tmp_path / name).unlink()
        else:
            (tmp_path / name).write_bytes(b"\0new" if name == "binary.dat" else b"new\n")
    def git(*args):
        return _git(tmp_path, "-c", "core.quotePath=true", *args)
    raw = git(*patch_arguments(names, staged=False))
    parts = partition_patches(raw, names)
    assert parts == {name: git(*patch_arguments([name], staged=False)) for name in names}
    reader = PatchBatchReader(git, names, staged=False)
    assert {name: reader.read(name) for name in names} == parts
    assert reader.batch_reads == 1


def test_large_dirty_worktree_batches_all_supported_patch_scopes(tmp_path):
    _repo(tmp_path)
    names = [f"component_{index:03d}.txt" for index in range(80)]
    for name in names:
        (tmp_path / name).write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "large fixture")
    for name in names:
        (tmp_path / name).write_text("after\n", encoding="utf-8")
    before = _git(tmp_path, "diff", "--binary")
    result = _plan(tmp_path)
    assert result["success"], result
    assert result["patch_scope_limit"] == 256
    assert result["git_visible_observation_complete"], result["unavailable_patch_scopes"]
    assert result["patch_batch_reads"] >= 20
    from local_ai_hub.change_commit_preflight import commit_preflight

    group = next(group for group in result["clusters"] if names[0] in group["files"])
    preflight = commit_preflight(result, group["files"], result["observed_change_set_id"])
    assert preflight["staging_preview_available"], preflight
    changes = {change["path"]: change for group in result["clusters"] for change in group["changes"]}
    assert set(changes) == set(names)
    assert all(len(change["atoms"]) == 1 for change in changes.values())
    for name in (names[0], names[-1]):
        focused = _plan(tmp_path, [name])
        assert focused["clusters"][0]["changes"][0]["atoms"][0]["atom_id"] == changes[name]["atoms"][0]["atom_id"]
    assert _git(tmp_path, "diff", "--binary") == before


def test_patch_batch_falls_back_when_partition_or_transport_fails():
    from local_ai_hub.change_patch_batch import PatchBatchReader, patch_arguments

    names = ["a.txt", "b.txt"]
    patches = {name: f"diff --git a/{name} b/{name}\n".encode() for name in names}
    calls = []

    def git(*args):
        calls.append(args)
        paths = [arg[len(":(literal)"):] for arg in args if arg.startswith(":(literal)")]
        if len(paths) > 1:
            return b"unexpected batch response\n"
        return patches[paths[0]]

    reader = PatchBatchReader(git, names, staged=False)
    assert [reader.read(name) for name in names] == [patches[name] for name in names]
    assert reader.batch_reads == 0
    assert calls == [patch_arguments(names, staged=False),
                     *[patch_arguments([name], staged=False) for name in names]]
