from __future__ import annotations

import builtins
import importlib.util
import io
import json
import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "surface_inventory", ROOT / "tools" / "surface_inventory.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(root: Path) -> None:
    write(
        root,
        "src/local_ai_hub/mcp_server.py",
        '''from typing import Literal, TypeAlias

_ACTION_ALIASES = {"repo": {"ctx": "context"}}
_REPO_ACTIONS = ("search", "context")

class Flags:
    batch_replacement = True

FEATURES = Flags()
RepoAction: TypeAlias = Literal.__getitem__(
    _REPO_ACTIONS + (("batch_replace",) if FEATURES.batch_replacement else ())
)

@mcp.tool()
def local_ai_repo(action: RepoAction):
    if action == "search":
        pass
    elif action == "context":
        pass
    elif action == "batch_replace":
        pass

@mcp.tool(name="local_ai_status")
def status(detail: Literal["brief", "full"]):
    pass
''',
    )
    write(
        root,
        "src/local_ai_hub/http_server.py",
        '''class Handler:
    def do_GET(self):
        if self.path in {"/health", "/api/health"}:
            return self.health()
        elif self.path.startswith("/api/jobs/"):
            return self.job()
        elif self.path.startswith("/api/agent-state/"):
            return self.agent_state()
        elif self.path == "/api/status":
            return self.status()
        elif self.path == "/api/context/pack":
            return self.context_pack()

    def do_POST(self):
        if self.path == "/health":
            return self.health()
        elif self.path.startswith("/api/repo/"):
            return self.repo()
        elif self.path.startswith("/api/task/"):
            return self.task()
        elif self.path.startswith("/api/agent-state/"):
            return self.agent_state()

def browser_path_helper(self):
    if self.path.startswith("/api/browser/"):
        return self.browser()

def chat_path_helper(self):
    if self.path == "/api/chat/completions":
        return self.chat()
''',
    )
    write(
        root,
        "src/local_ai_hub/client.py",
        '''class HubClient:
    def get_health(self):
        return self._request("GET", "/api/health")

    def get_job(self, job_id):
        return self._request("GET", f"/api/jobs/{job_id}")
''',
    )
    write(
        root,
        "src/local_ai_hub/features.py",
        '''FEATURES = {"semantic": True, "vision": False}
''',
    )
    write(
        root,
        "src/local_ai_hub/generator.py",
        '''TOOLS = ("local_ai_repo", "local_ai_status")
MANIFESTS = ("docs/INSTALL_PROMPT.md", "docs/UPDATE_PROMPT.md")
''',
    )
    write(
        root,
        "tools/hubctl.py",
        '''parser.add_subparsers(dest="operation")
sub.add_parser("status")
sub.add_parser("doctor")
parser.add_argument("operation", choices=["status", "doctor", "agent-state", "clean"])

@cli.command(name="inspect")
def inspect_command():
    pass
''',
    )
    write(root, "docs/INSTALL_PROMPT.md", "local_ai_repo local_ai_status")
    write(root, "docs/UPDATE_PROMPT.md", "local_ai_repo local_ai_status")
    write(
        root,
        "generated/schemas/local_ai_repo.json",
        json.dumps({
            "name": "local_ai_repo",
            "parameters": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"enum": ["search", "context", "batch_replace"]},
                    "query": {"type": "string", "default": ""},
                },
            },
            "outputSchema": {"type": "object", "properties": {"success": {"type": "boolean"}}},
        }),
    )
    write(
        root,
        "generated/schemas/local_ai_status.json",
        json.dumps({
            "name": "local_ai_status",
            "parameters": {"properties": {"detail": {"enum": ["brief", "full"]}}},
        }),
    )


ROOT_TASK_ID = MODULE._coverage_task_id((ROOT / "docs" / "API_COVERAGE.md").read_text(encoding="utf-8"))
ROOT_COVERAGE_ROWS = MODULE.coverage_rows(
    MODULE._findings(MODULE.collect_inventory(ROOT)),
    task_id=ROOT_TASK_ID,
)


@pytest.mark.parametrize("row", ROOT_COVERAGE_ROWS, ids=lambda row: row["operation_id"])
def test_operation_contract_metadata(row):
    required_contract_fields = {
        "request_payload",
        "response_contract",
        "status_codes",
        "timeout",
        "operation_side_effects",
        "backend_availability",
    }

    assert row["owner"]
    assert row["owner_task"] == ROOT_TASK_ID
    assert row["acceptance"]
    assert row["evidence"]
    assert row["state"] in {"verified", "conditional", "unsupported", "removed"}
    assert row["test_coverage"] == "metadata only; operation behavior unverified"
    assert required_contract_fields <= row["contract"].keys()
    assert row["test_ids"] == [
        f"tests/test_surface_inventory.py::test_operation_contract_metadata[{row['operation_id']}]"
    ]
    assert all(row["contract"][field] not in (None, "") for field in required_contract_fields)
    assert row["contract_gaps"]
    assert all(gap["reason"] and gap["owner_task"] and gap["owner"] and gap["disposition"] for gap in row["contract_gaps"])
    assert "not statically identified" not in json.dumps(row)
    assert "not statically classified" not in json.dumps(row)
    assert "not measured" not in json.dumps(row)


def test_unmeasured_contract_fields_have_concrete_gate_dispositions():
    row = MODULE.coverage_rows(
        [{
            "surface": "Feature gate",
            "name": "retrieval",
            "evidence": ["src/local_ai_hub/features.py:10"],
            "contract": {
                "backend_availability": "not statically identified",
                "quality": "not measured",
            },
        }],
        task_id="T01",
    )[0]

    assert "not statically identified" not in json.dumps(row)
    assert "not measured" not in json.dumps(row)
    gaps = {gap["field"]: gap for gap in row["contract_gaps"]}
    assert {"backend_availability", "quality"} <= gaps.keys()
    assert gaps["backend_availability"]["owner_task"] == "T11"
    assert gaps["quality"]["owner_task"] == "T02"
    assert all(
        gap["reason"] and gap["owner"] and gap["disposition"]
        for gap in row["contract_gaps"]
    )


def test_http_inventory_extracts_handler_contract_facts_without_pack_body():
    tree = MODULE.ast.parse('''class Handler:
    def do_POST(self):
        if self.path == "/api/items":
            payload = self._read_json()
            query = {"limit": ["2"]}
            item = payload.get("name")
            limit = query.get("limit")
            self._send(201, {"item": item, "limit": limit})
        elif self.path == "/api/context/pack":
            self._send(418, self._read_json())
''')

    routes = MODULE._extract_http(tree, "http_server.py")

    assert len(routes) == 1
    assert routes[0]["contract"]["status_codes"] == [201]
    assert routes[0]["contract"]["body_fields"] == ["name"]
    assert routes[0]["contract"]["query_fields"] == ["limit"]
    assert "/api/context/pack" not in json.dumps(routes)


def test_cli_inventory_records_parser_options_and_module_exit_values():
    tree = MODULE.ast.parse('''import argparse
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["status", "clean"])
parser.add_argument("--limit", type=int, default=4)
def main():
    return 0 if ready else 1
''')

    details = MODULE._extract_cli_contract(tree)

    assert details["operations"] == ["clean", "status"]
    assert details["parameters"] == [
        {"names": ["action"], "choices": ["clean", "status"]},
        {"names": ["--limit"], "default": 4, "type": "int"},
    ]
    assert details["return_codes"] == [0, 1]
    assert details["platform_guards"] == []


def test_inventory_extracts_surfaces_and_resolves_dynamic_route_registry(tmp_path):
    make_repo(tmp_path)

    inventory = MODULE.collect_inventory(tmp_path)

    assert {tool["name"] for tool in inventory["mcp_tools"]} == {
        "local_ai_repo",
        "local_ai_status",
    }
    assert inventory["mcp_actions"]["local_ai_repo"] == [
        "batch_replace",
        "context",
        "search",
    ]
    assert {route["path"] for route in inventory["http_routes"]} >= {
        "/health",
        "/api/health",
        "/api/jobs/",
        "/api/context/pack",
    }
    assert any(route["path"] == "/api/jobs/" and route["match"] == "prefix"
               for route in inventory["http_routes"])
    assert inventory["http_routes_by_target"]["GET /api/context/pack"]["classification"] == (
        "registered_dynamic"
    )
    assert "GET /health" in inventory["http_routes_by_target"]
    assert "POST /health" in inventory["http_routes_by_target"]
    assert not {"/api/browser/", "/api/chat/completions"} & {
        route["path"] for route in inventory["http_routes"]
    }
    assert "get_health" in {method["name"] for method in inventory["client_methods"]}
    assert "status" in inventory["cli_operations"]
    assert "semantic" in inventory["feature_gates"]
    assert not {"search", "context", "batch_replace"} & set(inventory["feature_gates"])
    assert inventory["conditional_mcp_actions"]["local_ai_repo"]["batch_replace"] == (
        "batch_replacement"
    )
    assert inventory["mcp_action_aliases"]["local_ai_repo"]["ctx"] == "context"
    assert {"agent-state", "clean"} <= set(inventory["cli_operations"])
    assert set(inventory["generated_manifests"]) == {
        "docs/INSTALL_PROMPT.md",
        "docs/UPDATE_PROMPT.md",
    }
    assert inventory["drift"] == []


def test_inventory_reports_orphan_client_target_and_ignores_prompt_text(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/client.py",
        '''class HubClient:
    def missing(self):
        return self._request("GET", "/api/missing")
''',
    )
    write(tmp_path, "docs/INSTALL_PROMPT.md", "local_ai_status")

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("/api/missing" in item for item in inventory["drift"])
    assert not any("MCP tool" in item and "INSTALL_PROMPT.md" in item for item in inventory["drift"])


def test_coverage_rows_never_claim_unobserved_audit_findings():
    rows = MODULE.coverage_rows(
        [
            {
                "surface": "mcp",
                "name": "local_ai_status",
                "evidence": ["src/local_ai_hub/mcp_server.py:10"],
                "condition": None,
            },
            {
                "surface": "route",
                "name": "/optional",
                "evidence": ["dynamic registry"],
                "condition": "feature flag",
            },
        ],
        task_id=None,
    )

    assert [row["evidence_status"] for row in rows] == ["confirmed", "conditional"]
    assert all(row["reproduction"] and row["evidence"] for row in rows)
    assert all(row["owner"] and row["acceptance"] for row in rows)
    assert all("task_id" not in row for row in rows)


def test_coverage_rows_disambiguate_same_surface_and_name_by_handler():
    rows = MODULE.coverage_rows(
        [
            {
                "surface": "HTTP GET",
                "name": "/status",
                "handler": "StatusHandler.get_status",
                "evidence": ["src/local_ai_hub/http_server.py:10"],
            },
            {
                "surface": "HTTP GET",
                "name": "/status",
                "handler": "AdminHandler.get_status",
                "evidence": ["src/local_ai_hub/admin.py:20"],
            },
        ],
        task_id="T01",
    )

    assert len({row["operation_id"] for row in rows}) == 2
    assert {row["handler"] for row in rows} == {
        "StatusHandler.get_status",
        "AdminHandler.get_status",
    }


def test_coverage_rows_preserve_refuted_evidence_status():
    rows = MODULE.coverage_rows(
        [{
            "surface": "MCP action",
            "name": "invented",
            "evidence": ["src/local_ai_hub/mcp_server.py:1"],
            "evidence_status": "refuted",
            "owner": "mcp-server",
            "acceptance": "Generated schema excludes this action.",
        }]
    )

    assert rows[0]["evidence_status"] == "refuted"
    assert rows[0]["owner"] == "mcp-server"
    assert rows[0]["acceptance"] == "Generated schema excludes this action."


def test_client_route_parity_requires_matching_http_method(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
    "src/local_ai_hub/client.py",
    '''class HubClient:
    def get_health(self):
        return self._request("POST", "/api/health")
''',
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("POST /api/health" in item for item in inventory["drift"])


def test_client_route_parity_accepts_optional_query_suffix(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/client.py",
        '''class HubClient:
    def get_health(self, qs=""):
        return self._request("GET", f"/api/health{qs}")
''',
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert inventory["drift"] == []


def test_orphan_dynamic_route_registry_entry_is_reported(tmp_path, monkeypatch):
    make_repo(tmp_path)
    monkeypatch.setattr(
        MODULE,
        "DYNAMIC_ROUTE_REGISTRY",
        ({
            "path": "/api/orphan/{item_id}",
            "method": "GET",
            "match": "prefix",
            "prefix": "/api/orphan/",
            "classification": "registered_dynamic",
        },),
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("orphan dynamic route registry entry GET /api/orphan/{item_id}" in item
               for item in inventory["drift"])


def test_generated_schema_without_source_tool_is_reported(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "generated/schemas/local_ai_rogue.json",
        json.dumps({"name": "local_ai_rogue", "parameters": {"properties": {}}}),
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("generated MCP schema local_ai_rogue" in item for item in inventory["drift"])


def test_check_mode_detects_drift_without_writing_coverage(tmp_path, capsys, monkeypatch):
    make_repo(tmp_path)
    stale_coverage = "# API surface coverage\n\n| Surface | Name |\n|---|---|\n| stale | `row` |\n"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    write(tmp_path, "docs/API_COVERAGE.md", stale_coverage)
    before_bytes = coverage_path.read_bytes()
    before_mtime = coverage_path.stat().st_mtime_ns

    def reject_write(*args, **kwargs):
        pytest.fail("--check attempted a filesystem write")

    monkeypatch.setattr(Path, "write_text", reject_write)
    monkeypatch.setattr(Path, "write_bytes", reject_write)

    assert MODULE.main(["--root", str(tmp_path), "--check"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("rendered coverage rows differ" in item for item in output["drift"])
    assert output["coverage_matches"] is False
    assert coverage_path.read_bytes() == before_bytes
    assert coverage_path.stat().st_mtime_ns == before_mtime


def test_check_mode_does_not_create_missing_coverage_doc(tmp_path, capsys, monkeypatch):
    make_repo(tmp_path)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    assert not coverage_path.exists()

    def reject_write(*args, **kwargs):
        pytest.fail("--check attempted to create a coverage file")

    monkeypatch.setattr(Path, "write_text", reject_write)
    monkeypatch.setattr(Path, "write_bytes", reject_write)

    result = MODULE.main(["--root", str(tmp_path), "--check"])
    summary = json.loads(capsys.readouterr().out)

    assert result == 1
    assert summary["coverage_matches"] is False
    assert any("rendered coverage rows differ" in item for item in summary["drift"])
    assert not coverage_path.exists()


def test_check_mode_infers_document_task_id_and_preserves_bytes(tmp_path, capsys):
    make_repo(tmp_path)
    task_id = "task-from-coverage-doc"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    write(tmp_path, "docs/API_COVERAGE.md", MODULE.render_coverage(MODULE.collect_inventory(tmp_path), task_id))
    before = coverage_path.read_bytes()

    result = MODULE.main(["--root", str(tmp_path), "--check"])

    assert result == 0
    assert coverage_path.read_bytes() == before
    summary = json.loads(capsys.readouterr().out)
    assert summary["coverage_matches"] is True
    assert summary["drift"] == []


def test_check_mode_with_real_schema_generator_does_not_write_files(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path)
    schema_dir = tmp_path / "generated" / "schemas"
    for schema_path in schema_dir.glob("*.json"):
        schema_path.unlink()
    schema_dir.rmdir()
    state_dir = tmp_path / "isolated-state"
    write(
        tmp_path,
        "config.toml",
        f'[server]\nstate_dir = "{state_dir.as_posix()}"\n[hardware]\nauto_tune = false\n',
    )
    write(tmp_path, "docs/API_COVERAGE.md", "# Existing coverage\n")
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    for name in tuple(sys.modules):
        if name == "local_ai_hub" or name.startswith("local_ai_hub."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    hardware = import_module("local_ai_hub.hardware")
    monkeypatch.setattr(hardware, "detect_hardware", lambda profile="auto": {"profile": profile})
    generator = import_module("local_ai_hub.generator")
    real_schema_generator = generator.generate_mcp_tool_schemas
    generated_schema_counts = []

    def track_schema_generation(cfg):
        schemas = real_schema_generator(cfg)
        generated_schema_counts.append(len(schemas))
        return schemas

    monkeypatch.setattr(generator, "generate_mcp_tool_schemas", track_schema_generation)

    def snapshot_tree():
        snapshot = {}
        for path in (tmp_path, *tmp_path.rglob("*")):
            stat = path.stat()
            relative = path.relative_to(tmp_path)
            if path.is_dir():
                snapshot[relative] = ("directory", stat.st_mtime_ns)
            else:
                snapshot[relative] = ("file", stat.st_mtime_ns, stat.st_size, path.read_bytes())
        return snapshot

    before = snapshot_tree()

    def reject_write(*args, **kwargs):
        pytest.fail("--check schema fallback attempted a filesystem mutation")

    original_builtin_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open

    def guarded_open(open_fn):
        def open_without_writes(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                reject_write(file, mode)
            return open_fn(file, mode, *args, **kwargs)
        return open_without_writes

    def guarded_os_open(file, flags, *args, **kwargs):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & write_flags and os.fspath(file) != os.devnull:
            reject_write(file, flags)
        return original_os_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", reject_write)
    monkeypatch.setattr(Path, "write_bytes", reject_write)
    monkeypatch.setattr(Path, "mkdir", reject_write)
    monkeypatch.setattr(Path, "touch", reject_write)
    monkeypatch.setattr(Path, "unlink", reject_write)
    monkeypatch.setattr(Path, "rmdir", reject_write)
    monkeypatch.setattr(builtins, "open", guarded_open(original_builtin_open))
    monkeypatch.setattr(io, "open", guarded_open(original_io_open))
    monkeypatch.setattr(os, "open", guarded_os_open)
    for name in ("mkdir", "makedirs", "replace", "rename", "remove", "unlink", "rmdir"):
        monkeypatch.setattr(os, name, reject_write)

    result = MODULE.main(["--root", str(tmp_path), "--check"])
    summary = json.loads(capsys.readouterr().out)

    assert result == 1
    assert "local_ai_hub.generator" in sys.modules
    assert (
        Path(sys.modules["local_ai_hub.generator"].__file__).resolve()
        == ROOT / "src" / "local_ai_hub" / "generator.py"
    )
    assert generated_schema_counts and generated_schema_counts[0] > 0
    assert summary["success"] is False
    assert summary["coverage_rows"] > 0
    after = snapshot_tree()
    assert after == before


def test_check_and_write_doc_are_rejected_before_mutating_coverage(tmp_path, capsys):
    make_repo(tmp_path)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    sentinel = "# Do not overwrite during check\n"
    write(tmp_path, "docs/API_COVERAGE.md", sentinel)

    with pytest.raises(SystemExit) as error:
        MODULE.main(["--root", str(tmp_path), "--check", "--write-doc"])

    assert error.value.code == 2
    assert coverage_path.read_text(encoding="utf-8") == sentinel
    assert "cannot be used together" in capsys.readouterr().err


def test_check_cli_accepts_coverage_without_writing_it():
    coverage_path = ROOT / "docs" / "API_COVERAGE.md"
    before_bytes = coverage_path.read_bytes()
    before_mtime = coverage_path.stat().st_mtime_ns
    command = [sys.executable, "tools/surface_inventory.py", "--check"]

    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert coverage_path.read_bytes() == before_bytes
    assert coverage_path.stat().st_mtime_ns == before_mtime
    assert result.returncode == 0, result.stdout + result.stderr


def test_write_doc_mode_updates_coverage(tmp_path, capsys):
    make_repo(tmp_path)
    task_id = "task-write-coverage-test"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    write(tmp_path, "docs/API_COVERAGE.md", "# Stale coverage\n")
    expected = MODULE.render_coverage(MODULE.collect_inventory(tmp_path), task_id=task_id)

    result = MODULE.main(["--root", str(tmp_path), "--write-doc", "--task-id", task_id])

    assert result == 0
    assert coverage_path.read_text(encoding="utf-8") == expected
    summary = json.loads(capsys.readouterr().out)
    assert summary["written"] == "docs/API_COVERAGE.md"
    assert summary["coverage_rows"] > 0


def test_rendered_coverage_includes_task_id_for_every_finding(tmp_path):
    make_repo(tmp_path)
    task_id = "task-inventory-test"

    rendered = MODULE.render_coverage(MODULE.collect_inventory(tmp_path), task_id=task_id)
    lines = rendered.splitlines()
    header_index = next(index for index, line in enumerate(lines) if line.startswith("| Surface | Name |"))
    data_rows = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        data_rows.append(line)

    assert lines[header_index].endswith("| Task ID |")
    assert data_rows
    assert all(line.endswith(f"| `{task_id}` |") for line in data_rows)


def test_inventory_finds_decorated_cli_operations_and_dataclass_feature_gates(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "tools/hubctl.py",
        '''@cli.command(name="repair")
def repair_command():
    pass
parser.add_argument("operation", choices=["repair", "doctor"])
''',
    )
    write(
        tmp_path,
        "src/local_ai_hub/features.py",
        '''from dataclasses import dataclass

@dataclass
class FeatureFlags:
    semantic: bool = True
    vision: bool = False
''',
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert set(inventory["cli_operations"]) >= {"repair"}
    assert set(inventory["feature_gates"]) >= {"semantic", "vision"}


def test_cli_positional_action_choices_are_inventoried():
    tree = MODULE.ast.parse(
        'parser.add_argument("action", choices=["status", "start", "stop"])'
    )

    assert MODULE._extract_cli(tree) == ["start", "status", "stop"]


def test_conditional_action_stays_in_inventory_when_generated_schema_hides_it(tmp_path):
    make_repo(tmp_path)
    schema_path = tmp_path / "generated" / "schemas" / "local_ai_repo.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["parameters"]["properties"]["action"]["enum"] = ["search", "context"]
    write(tmp_path, "generated/schemas/local_ai_repo.json", json.dumps(schema))

    inventory = MODULE.collect_inventory(tmp_path)
    action = next(
        finding
        for finding in MODULE._findings(inventory)
        if finding["surface"] == "MCP action local_ai_repo"
        and finding["name"] == "batch_replace"
    )

    assert "batch_replace" not in inventory["mcp_actions"]["local_ai_repo"]
    assert action["evidence_status"] == "conditional"
    assert "batch_replacement" in action["condition"]


def test_generated_mcp_action_without_dispatch_handler_is_reported(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/mcp_server.py",
        '''from typing import Literal

@mcp.tool()
def local_ai_repo(action: Literal["search", "missing"], detail: Literal["brief", "missing"]):
    if action == "search":
        return search()
''',
    )
    write(
        tmp_path,
        "generated/schemas/local_ai_repo.json",
        json.dumps({
            "name": "local_ai_repo",
            "parameters": {"properties": {
                "action": {"enum": ["search", "missing"]},
                "detail": {"enum": ["brief", "missing"]},
            }},
        }),
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("missing MCP action handler local_ai_repo:missing" in item for item in inventory["drift"])


def test_generic_return_does_not_handle_unmatched_generated_mcp_action(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/mcp_server.py",
        '''from typing import Literal

@mcp.tool()
def local_ai_repo(action: str):
    if action == "search":
        return search()
    return None
''',
    )
    write(
        tmp_path,
        "generated/schemas/local_ai_repo.json",
        json.dumps({
            "name": "local_ai_repo",
            "parameters": {"properties": {
                "action": {"enum": ["search", "missing"]},
            }},
        }),
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("missing MCP action handler local_ai_repo:missing" in item for item in inventory["drift"])


def test_source_mcp_tool_without_generated_schema_is_reported(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/mcp_server.py",
        '''@mcp.tool()
def local_ai_orphan():
    pass
''',
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("source MCP tool local_ai_orphan has no generated schema" in item for item in inventory["drift"])


def test_missing_generated_manifest_is_reported(tmp_path):
    make_repo(tmp_path)
    (tmp_path / "docs" / "UPDATE_PROMPT.md").unlink()

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("missing generated manifest docs/UPDATE_PROMPT.md" in item for item in inventory["drift"])


def test_inventory_contract_rows_include_required_machine_readable_fields(tmp_path):
    make_repo(tmp_path)
    task_id = "task-contract-inventory"
    inventory = MODULE.collect_inventory(tmp_path)

    rows = MODULE.coverage_rows(MODULE._findings(inventory), task_id=task_id)
    required = {
        "operation_id",
        "owner_task",
        "handler",
        "fixtures",
        "access_classification",
        "cache_key",
        "tenant_scope",
        "provenance",
        "test_ids",
        "benchmark_cohort",
        "state",
        "contract",
    }
    required_contract_fields = {
        "request_payload",
        "response_contract",
        "status_codes",
        "timeout",
        "operation_side_effects",
        "backend_availability",
    }

    assert rows
    assert all(required <= row.keys() for row in rows)
    assert all(required_contract_fields <= row["contract"].keys() for row in rows)
    assert all(
        row["contract"][field] not in (None, "")
        for row in rows for field in required_contract_fields
    )
    assert all(row["owner_task"] == task_id for row in rows)
    assert all(row["operation_id"] and row["handler"] and row["test_ids"] for row in rows)
    contract = next(row["contract"] for row in rows if row["surface"] == "MCP tool" and row["name"] == "local_ai_repo")
    assert contract["input_schema"]["properties"]["query"]["default"] == ""
    assert contract["output_schema"]["properties"]["success"]["type"] == "boolean"
