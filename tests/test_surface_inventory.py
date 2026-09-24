from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
            "parameters": {"properties": {"action": {"enum": ["search", "context", "batch_replace"]}}},
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


def test_check_mode_detects_rendered_coverage_row_drift(tmp_path, capsys):
    make_repo(tmp_path)
    stale_coverage = "# API surface coverage\n\n| Surface | Name |\n|---|---|\n| stale | `row` |\n"
    write(tmp_path, "docs/API_COVERAGE.md", stale_coverage)

    assert MODULE.main(["--root", str(tmp_path), "--check"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("rendered coverage rows differ" in item for item in output["drift"])
    assert (tmp_path / "docs" / "API_COVERAGE.md").read_text(encoding="utf-8") == stale_coverage


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

    result = subprocess.run(
        [sys.executable, "tools/surface_inventory.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert coverage_path.read_bytes() == before_bytes
    assert coverage_path.stat().st_mtime_ns == before_mtime
    assert result.returncode == 0, result.stdout + result.stderr


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
