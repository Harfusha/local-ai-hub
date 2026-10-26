"""Unit tests for repository-owned plan files schema and semantic validation."""

import json
from pathlib import Path

import jsonschema
import pytest

from local_ai_hub.project_config import resolve_project_config
from local_ai_hub.repo_plan import (
    PlanLifecycle,
    RepoPlan,
    RepoPlanValidationError,
    parse_plan_json,
    serialize_plan_json,
    validate_plan_dict,
    validate_repo_path,
)

EXAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "superpowers"
    / "specs"
    / "contracts"
    / "repo-plan.v1.example.json"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "superpowers"
    / "specs"
    / "contracts"
    / "repo-plan.v1.schema.json"
)


def test_schema_metaschema_valid():
    """Verify that repo-plan.v1.schema.json is a valid Draft 2020-12 schema."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)


def test_example_plan_valid_and_roundtrip():
    """Verify that repo-plan.v1.example.json is valid and round-trips deterministically."""
    raw_bytes = EXAMPLE_PLAN_PATH.read_bytes()
    data = parse_plan_json(raw_bytes)
    validate_plan_dict(data)

    plan = RepoPlan.from_dict(data)
    assert plan.id == "plan_example"
    assert plan.title == "Project workspace"
    assert plan.lifecycle == PlanLifecycle.DRAFT
    assert len(plan.tasks) == 1

    task = plan.tasks["task_example"]
    assert task.title == "Implement scoped plan editing"
    assert task.kind == "code"
    assert task.work_status == "planned"
    assert len(task.acceptance_criteria) == 1

    serialized = serialize_plan_json(plan.to_dict())
    assert json.loads(serialized) == json.loads(raw_bytes.decode("utf-8"))
    # Determinism: serializing again produces identical string
    assert serialize_plan_json(plan.to_dict()) == serialized


def test_reject_duplicate_keys():
    """Reject duplicate JSON keys anywhere in the plan file."""
    bad_json = """{
      "schema_version": 1,
      "id": "plan_test",
      "title": "Title 1",
      "title": "Title 2",
      "description": "Desc",
      "lifecycle": "draft",
      "default_target_ref": null,
      "spec_refs": [],
      "tasks": {}
    }"""
    with pytest.raises(RepoPlanValidationError, match="Duplicate JSON key: 'title'"):
        parse_plan_json(bad_json)


def test_reject_nan_infinity():
    """Reject non-finite JSON numbers."""
    bad_json = """{
      "schema_version": 1,
      "id": "plan_test",
      "title": "Title",
      "description": "Desc",
      "lifecycle": "draft",
      "default_target_ref": null,
      "spec_refs": [],
      "tasks": {
        "task_1": {
          "title": "Task",
          "description": "",
          "kind": "code",
          "work_status": "planned",
          "depends_on": [],
          "clarifications": [],
          "acceptance_criteria": [],
          "next_action": "",
          "blocker": null,
          "order": NaN
        }
      }
    }"""
    with pytest.raises(RepoPlanValidationError, match="Non-finite JSON number"):
        parse_plan_json(bad_json)


def test_reject_overflowing_json_number():
    """Reject finite-looking JSON literals that Python converts to infinity."""
    with pytest.raises(RepoPlanValidationError, match="Non-finite"):
        parse_plan_json('{"schema_version":1,"number":1e999}')


def test_reject_extreme_raw_nesting_before_json_decoder_recurses():
    """Reject deeply nested raw JSON as a validation error, not RecursionError."""
    raw = "[" * 1500 + "0" + "]" * 1500
    with pytest.raises(RepoPlanValidationError, match="maximum nesting depth"):
        parse_plan_json(raw)


def test_validate_and_serialize_reject_non_finite_values():
    """Dictionary entry points enforce finite JSON values too."""
    data = json.loads(EXAMPLE_PLAN_PATH.read_text(encoding="utf-8"))
    data["tasks"]["task_example"]["order"] = float("inf")
    with pytest.raises(RepoPlanValidationError, match="Non-finite"):
        validate_plan_dict(data)
    with pytest.raises(RepoPlanValidationError, match="Non-finite"):
        serialize_plan_json(data)


def test_model_from_dict_rejects_invalid_root_instead_of_coercing():
    """Model loading validates complete v1 shape before constructing dataclasses."""
    data = json.loads(EXAMPLE_PLAN_PATH.read_text(encoding="utf-8"))
    data["schema_version"] = "1"
    with pytest.raises(RepoPlanValidationError):
        RepoPlan.from_dict(data)


def test_cycle_detection_handles_maximum_task_chain():
    """Maximum-sized acyclic plan does not hit Python recursion limit."""
    data = {
        "schema_version": 1,
        "id": "plan_chain",
        "title": "Chain",
        "description": "",
        "lifecycle": "draft",
        "default_target_ref": None,
        "spec_refs": [],
        "tasks": {
            f"task_{i:04d}": {
                "title": f"Task {i}", "description": "", "kind": "code",
                "work_status": "planned",
                "depends_on": ([{"plan_id": "plan_chain", "task_id": f"task_{i - 1:04d}"}] if i else []),
                "clarifications": [], "acceptance_criteria": [], "next_action": "", "blocker": None,
            }
            for i in range(1000)
        },
    }
    validate_plan_dict(data)


def test_reject_oversized_file():
    """Reject plan files exceeding 1 MiB."""
    huge_text = " " * (1024 * 1024 + 10)
    with pytest.raises(RepoPlanValidationError, match="exceeds maximum size"):
        parse_plan_json(huge_text)


def test_reject_excessive_nesting():
    """Reject JSON structures nested deeper than 32 levels."""
    curr = {}
    root = curr
    for _ in range(35):
        curr["nested"] = {}
        curr = curr["nested"]
    json_str = json.dumps(root)
    with pytest.raises(RepoPlanValidationError, match="maximum nesting depth"):
        parse_plan_json(json_str)


def test_reject_too_many_tasks():
    """Reject plan containing more than 1000 tasks."""
    data = {
        "schema_version": 1,
        "id": "plan_huge",
        "title": "Huge plan",
        "description": "Too many tasks",
        "lifecycle": "draft",
        "default_target_ref": None,
        "spec_refs": [],
        "tasks": {
            f"task_{i:04d}": {
                "title": f"Task {i}",
                "description": "",
                "kind": "code",
                "work_status": "planned",
                "depends_on": [],
                "clarifications": [],
                "acceptance_criteria": [],
                "next_action": "",
                "blocker": None,
            }
            for i in range(1005)
        },
    }
    with pytest.raises(RepoPlanValidationError):
        validate_plan_dict(data)


def test_reject_invalid_identities():
    """Reject invalid plan_id, task_id, change_id, delivery_id."""
    base_data = {
        "schema_version": 1,
        "id": "plan_test",
        "title": "Title",
        "description": "Desc",
        "lifecycle": "draft",
        "default_target_ref": None,
        "spec_refs": [],
        "tasks": {},
    }

    # Bad plan ID (whitespace)
    bad_plan = dict(base_data, id="plan_ bad id")
    with pytest.raises(RepoPlanValidationError):
        validate_plan_dict(bad_plan)

    # Bad task ID (missing task_ prefix)
    bad_task = dict(base_data, tasks={"bad_task_1": {
        "title": "Task", "description": "", "kind": "code", "work_status": "planned",
        "depends_on": [], "clarifications": [], "acceptance_criteria": [], "next_action": "", "blocker": None
    }})
    with pytest.raises(RepoPlanValidationError):
        validate_plan_dict(bad_task)


def test_reject_invalid_paths(tmp_path):
    """Reject repo_paths with backslashes, leading slash, drive letters, and traversal."""
    with pytest.raises(RepoPlanValidationError, match="forward slashes only"):
        validate_repo_path("src\\plans\\test.json", repo_root=tmp_path)

    with pytest.raises(RepoPlanValidationError, match="cannot start with '/'"):
        validate_repo_path("/etc/passwd", repo_root=tmp_path)

    with pytest.raises(RepoPlanValidationError, match="cannot include Windows drive letter"):
        validate_repo_path("C:/foo/bar", repo_root=tmp_path)

    with pytest.raises(RepoPlanValidationError, match="cannot contain '.' or '..' segments"):
        validate_repo_path("foo/../bar", repo_root=tmp_path)


def test_dependency_validation():
    """Reject missing dependencies and cyclic dependencies within the plan."""
    # 1. Missing dependency in same plan
    missing_dep_data = {
        "schema_version": 1,
        "id": "plan_dep",
        "title": "Dependencies",
        "description": "",
        "lifecycle": "active",
        "default_target_ref": None,
        "spec_refs": [],
        "tasks": {
            "task_a": {
                "title": "A", "description": "", "kind": "code", "work_status": "planned",
                "depends_on": [{"plan_id": "plan_dep", "task_id": "task_nonexistent"}],
                "clarifications": [], "acceptance_criteria": [], "next_action": "", "blocker": None
            }
        }
    }
    with pytest.raises(RepoPlanValidationError, match="depends on non-existent task 'task_nonexistent'"):
        validate_plan_dict(missing_dep_data)

    # 2. Cycle A -> B -> A
    cycle_data = {
        "schema_version": 1,
        "id": "plan_cycle",
        "title": "Cycle",
        "description": "",
        "lifecycle": "active",
        "default_target_ref": None,
        "spec_refs": [],
        "tasks": {
            "task_a": {
                "title": "A", "description": "", "kind": "code", "work_status": "planned",
                "depends_on": [{"plan_id": "plan_cycle", "task_id": "task_b"}],
                "clarifications": [], "acceptance_criteria": [], "next_action": "", "blocker": None
            },
            "task_b": {
                "title": "B", "description": "", "kind": "code", "work_status": "planned",
                "depends_on": [{"plan_id": "plan_cycle", "task_id": "task_a"}],
                "clarifications": [], "acceptance_criteria": [], "next_action": "", "blocker": None
            }
        }
    }
    with pytest.raises(RepoPlanValidationError, match="Cyclic dependency detected: task_a -> task_b -> task_a"):
        validate_plan_dict(cycle_data)


def test_project_config_workspace_settings(tmp_path):
    """Test that project_config properly parses [workspace] and rejects invalid keys."""
    config_file = tmp_path / ".local-ai.toml"

    # Default settings when [workspace] is omitted
    config_file.write_text("", encoding="utf-8")
    settings = resolve_project_config(tmp_path).settings
    assert settings.workspace.plans_dir == ".local-ai-hub/plans"
    assert settings.workspace.specs_dir == "docs/superpowers/specs"
    assert settings.workspace.intents_dir == ".local-ai-hub/local/intents"

    # Explicit workspace settings
    config_file.write_text("""[workspace]
plans_dir = ".custom-plans"
specs_dir = "specs"
""", encoding="utf-8")
    settings = resolve_project_config(tmp_path).settings
    assert settings.workspace.plans_dir == ".custom-plans"
    assert settings.workspace.specs_dir == "specs"

    # Invalid workspace key
    config_file.write_text("""[workspace]
unknown_field = "bad"
""", encoding="utf-8")
    res = resolve_project_config(tmp_path)
    assert "invalid_config" in res.error_codes
