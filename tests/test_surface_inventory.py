from __future__ import annotations

import ast
import builtins
import importlib.util
import hashlib
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


def test_git_ignore_check_uses_hidden_process_options(tmp_path, monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(MODULE, "_hidden_run_kwargs", lambda _root: {"creationflags": 123})
    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE._git_ignores(tmp_path, "generated/schemas/local_ai_repo.json") is True
    assert captured["creationflags"] == 123


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

class FeatureSet:
    commands = True
    speculative_lint = True

    def supported_command_actions(self):
        actions = ["run"]
        if self.speculative_lint:
            actions.append("speculative_lint")
        return actions
''',
    )
    write(
        root,
        "src/local_ai_hub/generator.py",
        '''TOOLS = ("local_ai_repo", "local_ai_status")

def generate(root):
    (root / "generated/schemas/local_ai_repo.json").write_text("{}")
    (root / "generated" / "schemas" / "local_ai_status.json").write_text("{}")
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
ROOT_INVENTORY = MODULE.collect_inventory(ROOT)
ROOT_COVERAGE_ROWS = MODULE.coverage_rows(
    MODULE._findings(ROOT_INVENTORY),
    task_id=ROOT_TASK_ID,
)


def test_root_inventory_resolves_imported_actions_and_redacted_pack_route():
    drift = ROOT_INVENTORY["drift"]

    assert not any(item.startswith("missing MCP action handler local_ai_status:") for item in drift)
    assert not any(item.startswith("orphan client target POST /api/context/pack ") for item in drift)
    status_details = set(ROOT_INVENTORY["mcp_actions"]["local_ai_status"])
    assert status_details == {"brief"}
    assert {"status", "health", "check", "info"}.isdisjoint(status_details)
    assert ROOT_INVENTORY.get("mcp_action_aliases", {}) == {}
    assert any(
        route["method"] == "POST"
        and route["path"] == "/api/context/pack"
        and route["classification"] == "registered_dynamic"
        for route in ROOT_INVENTORY["http_routes"]
    )


def test_operation_owner_tasks_follow_surface_families():
    cases = (
        ({"surface": "HTTP GET", "name": "/api/context/pack"}, "T14"),
        ({"surface": "HTTP GET", "name": "/api/benchmark"}, "T02"),
        ({"surface": "MCP tool", "name": "local_ai_repo"}, "T03"),
        ({"surface": "HubClient method", "name": "get_health"}, "T04"),
        ({"surface": "HTTP POST", "name": "/api/memory"}, "T05"),
        ({"surface": "HTTP POST", "name": "/api/search"}, "T21"),
        ({"surface": "HTTP POST", "name": "/api/command/run"}, "T15"),
        ({"surface": "MCP action local_ai_coord", "name": "task_list"}, "T08"),
        ({"surface": "HTTP POST", "name": "/api/evidence/verify"}, "T09"),
        ({"surface": "MCP action local_ai_repo", "name": "context"}, "T10"),
        ({"surface": "MCP action local_ai_repo", "name": "search"}, "T21"),
        ({"surface": "MCP action local_ai_rag", "name": "docset_search"}, "T11"),
        ({"surface": "MCP action local_ai_task", "name": "delegate"}, "T12"),
        ({"surface": "HTTP POST", "name": "/api/conversations/continue"}, "T13"),
        ({"surface": "MCP action local_ai_artifact", "name": "get"}, "T14"),
        ({"surface": "MCP action local_ai_work", "name": "submit"}, "T16"),
        ({"surface": "HTTP POST", "name": "/api/vision/analyze"}, "T17"),
        ({"surface": "MCP action local_ai_status", "name": "brief"}, "T18"),
        ({"surface": "CLI operation", "name": "generate"}, "T19"),
        ({"surface": "CLI operation", "name": "release-check"}, "T20"),
        ({"surface": "HTTP GET", "name": "/api/project-config"}, "T21"),
    )

    assert all(MODULE._operation_owner_task(finding) == expected for finding, expected in cases)
    assert all(row["owner_task"] in MODULE._OPERATION_OWNER_TASKS for row in ROOT_COVERAGE_ROWS)
    assert all(
        row["owner_task"] == MODULE._operation_owner_task({**row, "owner_task": None})
        for row in ROOT_COVERAGE_ROWS
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
    expected_owner_task = MODULE._operation_owner_task({**row, "owner_task": None})
    assert row["owner_task"] == expected_owner_task
    assert row["owner_task"] in MODULE._OPERATION_OWNER_TASKS
    assert row["acceptance"]
    assert row["evidence"]
    assert row["state"] in {"verified", "conditional", "unsupported", "removed"}
    if row["test_coverage"] == "metadata only; operation behavior unverified":
        assert row["behavioral_disposition"] == "no asserted operation test linked; behavior unverified"
        assert row["test_ids"] == [
            f"tests/test_surface_inventory.py::test_operation_contract_metadata[{row['operation_id']}]"
        ]
    else:
        assert row["behavioral_disposition"] == "asserted behavior test linked"
        assert row["test_coverage"] == "behavioral tests linked; coverage bounded to cited assertions"
        assert row["test_ids"]
        assert row["fixtures"] == row["test_ids"]
    assert required_contract_fields <= row["contract"].keys()
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
    assert inventory["http_routes_by_target"]["POST /api/context/pack"]["classification"] == (
        "registered_dynamic"
    )
    assert "GET /api/context/pack" not in inventory["http_routes_by_target"]
    assert inventory["http_routes_by_target"]["OPTIONS /api/browser/"]["match"] == "prefix"
    assert inventory["http_routes_by_target"]["OPTIONS /api/vision/review"]["match"] == "exact"
    assert "GET /health" in inventory["http_routes_by_target"]
    assert "POST /health" in inventory["http_routes_by_target"]
    assert inventory["http_routes_by_target"]["OPTIONS /api/browser/"]["classification"] == (
        "registered_dynamic"
    )
    assert "POST /api/browser/" not in inventory["http_routes_by_target"]
    assert "/api/chat/completions" not in {
        route["path"] for route in inventory["http_routes"]
    }
    assert "get_health" in {method["name"] for method in inventory["client_methods"]}
    assert "status" in inventory["cli_operations"]
    assert "semantic" in inventory["feature_gates"]
    assert not {"search", "context", "batch_replace"} & set(inventory["feature_gates"])
    assert inventory["conditional_mcp_actions"]["local_ai_repo"]["batch_replace"] == (
        "batch_replacement"
    )
    assert "local_ai_command" not in inventory["conditional_mcp_actions"]
    assert inventory["mcp_action_aliases"] == {"local_ai_repo": {"ctx": "context"}}
    assert {"agent-state", "clean"} <= set(inventory["cli_operations"])
    assert set(inventory["generated_manifests"]) == {
        "generated/schemas/local_ai_repo.json",
        "generated/schemas/local_ai_status.json",
    }
    assert inventory["drift"] == []


def test_http_route_evidence_status_captures_dynamic_and_backend_gates(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/http_server.py",
        '''class Handler:
    def do_GET(self):
        if self.path.startswith("/api/jobs/"):
            return self.job()
        if self.path == "/api/agent-state/events":
            if not getattr(APP, "agent_state", None) or not APP.agent_state.enabled:
                return self._send(403, {"error": "agent state disabled"})
            return self.events()
        if self.path in {"/", "/dashboard"}:
            if not bool(APP.config.get("features", {}).get("dashboard", True)):
                return self._send(404, {"error": "dashboard disabled"})
            return self.dashboard()
        if self.path == "/api/browser/capability":
            if not APP.config.get("browser_bridge", {}).get("enabled", True):
                return self._send(501, {"error": "browser bridge disabled"})
            return self.capability()
''',
    )

    inventory = MODULE.collect_inventory(tmp_path)
    rows = MODULE.coverage_rows(MODULE._findings(inventory))
    routes = {(route["method"], route["path"]): route for route in inventory["http_routes"]}
    rows_by_target = {(row["surface"], row["name"]): row for row in rows}

    assert routes[("GET", "/api/jobs/")]["match"] == "prefix"
    assert routes[("GET", "/api/jobs/")]["evidence_status"] == "confirmed"
    for path, gate in (
        ("/api/agent-state/events", "agent_state.enabled"),
        ("/dashboard", "features"),
        ("/api/browser/capability", "browser_bridge"),
    ):
        route = routes[("GET", path)]
        row = rows_by_target[("HTTP GET", path)]
        assert route["evidence_status"] == "conditional"
        assert any(gate in condition for condition in route["conditional_gates"])
        assert row["evidence_status"] == "conditional"
        assert row["state"] == "conditional"
        assert gate in row["condition"]


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


def test_client_inventory_includes_urllib_health_and_event_stream_targets():
    source = '''from urllib.request import Request, urlopen

class HubClient:
    def _online(self):
        with urlopen(Request(f"{self.base_url}/health")) as response:
            return response.status == 200

    def send_positional_post(self):
        return urlopen(Request("/api/positional", None, {}, None, False, "POST"))

    def send_dynamic_method(self, method):
        return urlopen(Request("/api/dynamic", method=method))

    def send_keyword_url(self):
        return urlopen(Request(url="/api/named"))

    def send_data_post(self):
        return urlopen(Request("/api/data-post", data=b"payload"))

    def send_dynamic_data(self, payload):
        return urlopen(Request("/api/dynamic-data", data=payload))

    def send_none_data(self):
        payload = None
        return urlopen(Request("/api/none-data", data=payload))

    def send_branch_data(self, enabled):
        payload = None
        if enabled:
            payload = b"payload"
        return urlopen(Request("/api/branch-data", data=payload))

    def send_reassigned_parameter(self, payload, enabled):
        if enabled:
            payload = None
        return urlopen(Request("/api/reassigned-parameter", data=payload))

    def stream_events(self):
        url = f"{self.base_url}/api/agent-state/events/stream{query}"
        request = Request(url)
        return urlopen(request)
'''

    _, targets = MODULE._extract_client(ast.parse(source), "src/local_ai_hub/client.py")

    assert {
        (target["method"], target["path"].split("{", 1)[0])
        for target in targets
    } >= {
        ("GET", "/health"),
        ("GET", "/api/agent-state/events/stream"),
        ("POST", "/api/positional"),
        ("ANY", "/api/dynamic"),
        ("GET", "/api/named"),
        ("POST", "/api/data-post"),
        ("ANY", "/api/dynamic-data"),
        ("GET", "/api/none-data"),
        ("ANY", "/api/branch-data"),
        ("ANY", "/api/reassigned-parameter"),
    }


def test_current_client_inventory_includes_urllib_targets():
    client_tree = ast.parse((ROOT / "src/local_ai_hub/client.py").read_text(encoding="utf-8"))

    _, targets = MODULE._extract_client(client_tree, "src/local_ai_hub/client.py")

    assert {
        (target["method"], target["path"]) for target in targets
    } >= {
        ("GET", "/ready"),
        ("GET", "/api/agent-state/events/stream"),
    }


def test_inventory_recognizes_action_alias_checked_against_dynamic_detail_type(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/mcp_server.py",
        '''from typing import Literal, TypeAlias
StatusDetail: TypeAlias = Literal.__getitem__(operation_actions("local_ai_status"))
@mcp.tool()
def local_ai_status(action: str = "", detail: StatusDetail = "brief"):
    if action:
        act = action.strip().lower()
        if act in StatusDetail.__args__:
            detail = act
''',
    )
    write(
        tmp_path,
        "generated/schemas/local_ai_status.json",
        json.dumps({
            "name": "local_ai_status",
            "parameters": {
                "properties": {
                    "action": {"enum": ["brief", "cache"]},
                    "detail": {"enum": ["brief", "cache"]},
                },
            },
        }),
    )

    inventory = MODULE.collect_inventory(tmp_path)

    json.dumps(inventory)
    assert "missing MCP action handler local_ai_status:brief" not in inventory["drift"]


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
    assert all(row["owner_task"] is None for row in rows)




def test_behavioral_coverage_links_are_operation_specific_legacy_get_candidate(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "tests/test_operation_behavior.py",
        '''import urllib.request
from urllib.request import Request as HttpRequest, urlopen as fetch_url
from local_ai_hub.mcp_server import local_ai_repo
from tools.hubctl import main as cli_main

def test_repo_search_dispatch():
    result = local_ai_repo(action="search")
    assert result["success"] is True

def test_repo_context_dispatch():
    result = local_ai_repo(action="context")
    assert result["success"] is True

def test_post_health_route():
    result = request("POST", "http://127.0.0.1/health", {})
    assert result["success"] is True

def test_urllib_request_route():
    with urllib.request.urlopen("http://127.0.0.1/api/health") as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_request_alias_defaults_to_get():
    request = HttpRequest("http://127.0.0.1/api/health")
    with fetch_url(request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_urlopen_data_uses_post():
    with urllib.request.urlopen("http://127.0.0.1/health", data=b"{}") as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_keyword_url_route():
    request = urllib.request.Request(url="http://127.0.0.1/api/health")
    with urllib.request.urlopen(url=request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_post_helper_route():
    def post_json(endpoint, data):
        request = urllib.request.Request(
            f"http://127.0.0.1{endpoint}", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    result = post_json("/health", {})
    assert result["success"] is True

def _module_request(url, *, method="GET", body=None):
    request = urllib.request.Request(url, method="GET")
    request = urllib.request.Request(url, data=body, method=method)
    with urllib.request.urlopen(request) as response:
        return response.status, dict(response.headers), response.read()

def test_module_level_urllib_helper_links_asserted_operation():
    url = "http://127.0.0.1" + "/api/status"
    url = "http://127.0.0.1" + "/api/repo/search"
    status, _, body = _module_request(url, method="POST", body=b"{}")
    assert status == 200
    assert json.loads(body)["success"] is True

def _module_discarded_request(url):
    with urllib.request.urlopen(url) as response:
        response.read()
    return {"success": True}

def test_module_level_helper_discarding_response_is_not_route_coverage():
    result = _module_discarded_request("http://127.0.0.1/api/repo/search")
    assert result["success"] is True

def test_module_level_urllib_helper_defaults_to_get():
    _, _, body = _module_request("http://127.0.0.1/api/health")
    assert json.loads(body)["success"] is True

def test_client_health_method():
    client = HubClient()
    result = client.get_health()
    assert result["success"] is True

def test_cli_status_operation():
    assert cli_main(["status"]) == 0

def test_status_route_is_only_documented():
    assert "/api/status" in "documented route: /api/status"

def test_context_pack_http_request():
    result = request("GET", "http://127.0.0.1/api/context/pack", {})
    assert result["success"] is True
''',
    )

    links = MODULE.collect_inventory(tmp_path)["behavioral_test_links"]

    assert links["MCP action local_ai_repo::search"] == [
        "tests/test_operation_behavior.py::test_repo_search_dispatch"
    ]
    assert links["MCP action local_ai_repo::context"] == [
        "tests/test_operation_behavior.py::test_repo_context_dispatch"
    ]
    assert links["HTTP POST::/health"] == sorted([
        "tests/test_operation_behavior.py::test_post_health_route",
        "tests/test_operation_behavior.py::test_urllib_post_helper_route",
        "tests/test_operation_behavior.py::test_urllib_urlopen_data_uses_post",
    ])
    assert links["HTTP GET::/api/health"] == sorted([
        "tests/test_operation_behavior.py::test_urllib_request_alias_defaults_to_get",
        "tests/test_operation_behavior.py::test_urllib_request_route",
        "tests/test_operation_behavior.py::test_urllib_keyword_url_route",
        "tests/test_operation_behavior.py::test_module_level_urllib_helper_defaults_to_get",
    ])
    assert "tests/test_operation_behavior.py::test_module_level_urllib_helper_defaults_to_get" not in links.get(
        "HTTP POST::/api/health", []
    )
    assert links["HTTP POST::/api/repo/"] == [
        "tests/test_operation_behavior.py::test_module_level_urllib_helper_links_asserted_operation"
    ]
    assert "tests/test_operation_behavior.py::test_module_level_helper_discarding_response_is_not_route_coverage" not in links.get(
        "HTTP POST::/api/repo/", []
    )
    assert "tests/test_operation_behavior.py::test_module_level_urllib_helper_links_asserted_operation" not in links.get(
        "HTTP GET::/api/repo/", []
    )
    assert links["HubClient method::get_health"] == [
        "tests/test_operation_behavior.py::test_client_health_method"
    ]
    assert links["CLI operation::status"] == [
        "tests/test_operation_behavior.py::test_cli_status_operation"
    ]
    assert "HTTP GET::/api/status" not in links
    assert "HTTP GET::/api/context/pack" not in links
    rows = MODULE.coverage_rows(MODULE._findings(MODULE.collect_inventory(tmp_path)))
    for key, expected_selector in (
        (("MCP action local_ai_repo", "search"), "test_repo_search_dispatch"),
        (("HTTP POST", "/health"), "test_post_health_route"),
        (("HubClient method", "get_health"), "test_client_health_method"),
        (("CLI operation", "status"), "test_cli_status_operation"),
    ):
        row = next(row for row in rows if (row["surface"], row["name"]) == key)
        assert row["test_coverage"] == "behavioral tests linked; coverage bounded to cited assertions"
        assert any(expected_selector in selector for selector in row["test_ids"])








def test_behavioral_links_only_reference_inventoried_operations():
    inventory = MODULE.collect_inventory(ROOT)
    links = inventory["behavioral_test_links"]
    finding_keys = {
        f"{finding['surface']}::{finding['name']}"
        + (f"::{finding.get('handler', '')}" if finding["surface"] == "HubClient target" else "")
        for finding in MODULE._findings(inventory)
    }

    assert set(links) <= finding_keys
    context_selector = (
        "tests/test_client_operation_acceptance.py::"
        "test_client_context_compile_targets_agent_state_context"
    )
    assert context_selector in links["HubClient target::POST /api/agent-state/context::context_compile"]
    assert (
        "tests/test_mcp_compact_transport.py::test_local_ai_repo_context_forwards_guarded_pack_fields"
        in links["MCP action local_ai_repo::context"]
    )
    for route, selector in (
        (
            "/api/agent-state/blackboard",
            "test_http_get_agent_state_blackboard_forwards_board_and_section",
        ),
        (
            "/api/agent-state/events",
            "test_http_get_agent_state_events_forwards_stream_cursor_and_limit",
        ),
        (
            "/api/agent-state/swarm",
            "test_http_get_agent_state_swarm_forwards_state_and_limit",
        ),
        (
            "/api/agent-state/swarm/",
            "test_http_get_agent_state_swarm_detail_forwards_swarm_id",
        ),
        ("/api/config", "test_http_get_config_redacts_configured_token"),
        ("/api/capabilities", "test_http_get_capabilities_returns_surface_and_features"),
        ("/api/audit/tail", "test_http_get_audit_tail_forwards_limit"),
        ("/api/audit_dependencies", "test_http_get_audit_dependencies_forwards_root"),
        (
            "/api/repo/affected_tests",
            "test_http_get_affected_tests_forwards_root_and_repeated_paths",
        ),
    ):
        key = f"HTTP GET::{route}"
        assert any(selector in item for item in links[key])
    assert any(
        "test_http_post_affected_tests_forwards_json_paths" in item
        for item in links["HTTP POST::/api/repo/affected_tests"]
    )
    assert "MCP action local_ai_repo::not_a_real_action" not in links
    assert "MCP action local_ai_task::not_a_real_action" not in links
    task_list_selector = (
        "tests/test_mcp_coord_operation_acceptance.py::"
        "test_local_ai_coord_task_list_forwards_status_and_stale_filter"
    )
    assert task_list_selector in links["MCP action local_ai_coord::task_list"]
    # The retired command tool must not become a live operation or schema gap.
    assert not any("local_ai_command::" in key for key in finding_keys)
    assert not any("local_ai_command::" in key for key in links)
    assert not any(
        "test_mcp_command_operation_acceptance.py::" in selector
        for selectors in links.values() for selector in selectors
    )










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


def test_inventory_includes_get_routes_from_dispatch_registry(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/http_route_registry.py",
        '''from types import MappingProxyType
GET_ROUTE_HANDLER_BOUNDARIES = MappingProxyType({
    "/api/live/status": "_handle_get_live_status",
})
POST_ROUTE_REGISTRY = (("post_telemetry_timeline_1", frozenset(("/api/telemetry/timeline",))),)
POST_ROUTE_HANDLER_BOUNDARIES = MappingProxyType({
    "post_telemetry_timeline_1": "_handle_post_telemetry_timeline",
})
''',
    )
    write(
        tmp_path,
        "src/local_ai_hub/client.py",
        '''class HubClient:
    def get_live_status(self):
        return self._request("GET", "/api/live/status?light=1")
''',
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert "GET /api/live/status" in inventory["http_routes_by_target"]
    assert "POST /api/telemetry/timeline" in inventory["http_routes_by_target"]
    assert not any("orphan client target GET /api/live/status" in item
                   for item in inventory["drift"])


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


def test_context_pack_dynamic_route_is_owned_by_t14(tmp_path):
    make_repo(tmp_path)

    inventory = MODULE.collect_inventory(tmp_path)
    route = next(
        item for item in inventory["http_routes"]
        if item["method"] == "POST" and item["path"] == "/api/context/pack"
    )

    assert route["classification"] == "registered_dynamic"
    assert route["owner_task"] == "T14"
    assert "owner_gate" not in route["contract"]


def test_generated_schema_without_source_tool_is_reported(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "generated/schemas/local_ai_rogue.json",
        json.dumps({"name": "local_ai_rogue", "parameters": {"properties": {}}}),
    )

    inventory = MODULE.collect_inventory(tmp_path)

    assert any("generated MCP schema local_ai_rogue" in item for item in inventory["drift"])


def test_check_with_disabled_source_tools_is_read_only_and_not_drift(tmp_path, capsys):
    make_repo(tmp_path)
    mcp_path = tmp_path / "src" / "local_ai_hub" / "mcp_server.py"
    mcp_path.write_text(
        mcp_path.read_text(encoding="utf-8")
        + "\n@mcp.tool()\ndef local_ai_task(action: str):\n    pass\n"
        + "@mcp.tool()\ndef local_ai_work(action: str):\n    pass\n",
        encoding="utf-8",
    )
    schema_dir = tmp_path / "generated" / "schemas"
    for schema_path in schema_dir.glob("*.json"):
        schema_path.unlink()
    schema_dir.rmdir()
    write(tmp_path, "defaults.toml", (ROOT / "defaults.toml").read_text(encoding="utf-8"))
    write(
        tmp_path,
        "config.toml",
        "[features]\ntasks = false\nlocal_models = false\nwork_orchestrator = false\n",
    )

    def snapshot_tree(root):
        snapshot = {}
        for item in (root, *root.rglob("*")):
            stat = item.stat()
            relative = item.relative_to(root)
            if item.is_dir():
                snapshot[relative] = ("directory", stat.st_mtime_ns)
            else:
                snapshot[relative] = ("file", stat.st_mtime_ns, stat.st_size, item.read_bytes())
        return snapshot

    before = snapshot_tree(tmp_path)
    result = MODULE.main(["--root", str(tmp_path), "--check"])
    summary = json.loads(capsys.readouterr().out)

    assert result == 1
    assert summary["coverage_matches"] is False
    assert any("rendered coverage document differs" in item for item in summary["drift"])
    assert not any(
        "source MCP tool local_ai_task has no generated schema" in item
        or "source MCP tool local_ai_work has no generated schema" in item
        for item in summary["drift"]
    )
    after = snapshot_tree(tmp_path)
    assert after == before


def test_check_mode_detects_drift_without_mutating_coverage(tmp_path, capsys):
    make_repo(tmp_path)
    stale_coverage = "# API surface coverage\n\n| Surface | Name |\n|---|---|\n| stale | `row` |\n"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    write(tmp_path, "docs/API_COVERAGE.md", stale_coverage)
    before_bytes = coverage_path.read_bytes()
    before_mtime = coverage_path.stat().st_mtime_ns

    assert MODULE.main(["--root", str(tmp_path), "--check"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert any("rendered coverage document differs" in item for item in output["drift"])
    assert output["coverage_matches"] is False
    assert "written" not in output
    assert coverage_path.read_bytes() == before_bytes
    assert coverage_path.stat().st_mtime_ns == before_mtime


def test_check_cli_preserves_stale_coverage_hash_on_drift(tmp_path):
    make_repo(tmp_path)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    stale_coverage = b"# API surface coverage\n\n| Surface | Name |\n|---|---|\n| stale | `row` |\n"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_bytes(stale_coverage)
    before_hash = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    command = [
        sys.executable,
        str(ROOT / "tools" / "surface_inventory.py"),
        "--root",
        str(tmp_path),
        "--check",
    ]

    check = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )

    assert check.returncode == 1
    summary = json.loads(check.stdout)
    assert summary["coverage_matches"] is False
    assert summary["drift"]
    assert "written" not in summary
    after_hash = hashlib.sha256(coverage_path.read_bytes()).hexdigest()
    assert after_hash == before_hash

def test_check_mode_reports_missing_coverage_without_creating_doc(tmp_path, capsys):
    make_repo(tmp_path)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    assert not coverage_path.exists()

    result = MODULE.main(["--root", str(tmp_path), "--check"])
    summary = json.loads(capsys.readouterr().out)

    assert result == 1
    assert summary["coverage_matches"] is False
    assert any("rendered coverage document differs" in item for item in summary["drift"])
    assert "written" not in summary
    assert not coverage_path.exists()


def test_check_mode_infers_task_id_and_preserves_matching_document(tmp_path, capsys, monkeypatch):
    make_repo(tmp_path)
    task_id = "task-from-coverage-doc"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    inventory = MODULE.collect_inventory(tmp_path)
    write(tmp_path, "docs/API_COVERAGE.md", MODULE.render_coverage(inventory, task_id))
    write(tmp_path, "docs/API_COVERAGE.json", MODULE.render_coverage_artifact(inventory, task_id))
    before = coverage_path.read_bytes()
    artifact_path = tmp_path / "docs" / "API_COVERAGE.json"
    artifact_before = artifact_path.read_bytes()
    before_mtime = coverage_path.stat().st_mtime_ns
    writes = []
    original_write_text = Path.write_text

    def record_write(path, *args, **kwargs):
        writes.append(path)
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", record_write)

    result = MODULE.main(["--root", str(tmp_path), "--check"])

    assert result == 0
    assert coverage_path.read_bytes() == before
    assert artifact_path.read_bytes() == artifact_before
    assert coverage_path.stat().st_mtime_ns == before_mtime
    assert writes == []
    assert coverage_path.read_text(encoding="utf-8") == MODULE.render_coverage(MODULE.collect_inventory(tmp_path), task_id)
    summary = json.loads(capsys.readouterr().out)
    assert summary["coverage_matches"] is True
    assert summary["artifact_matches"] is True
    assert summary["drift"] == []
    assert "written" not in summary


def test_check_mode_with_real_schema_generator_does_not_write_coverage(tmp_path, monkeypatch, capsys):
    make_repo(tmp_path)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
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

    def snapshot_tree(root):
        directories = {path.relative_to(root) for path in root.rglob("*") if path.is_dir()}
        files = {
            path.relative_to(root): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and path.resolve() != coverage_path.resolve()
        }
        return directories, files

    scoped_roots = (tmp_path, ROOT / "src" / "local_ai_hub")
    before = {root: snapshot_tree(root) for root in scoped_roots}

    def reject_write(file, *args, **kwargs):
        pytest.fail("--check schema fallback attempted a filesystem mutation")

    original_builtin_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_path_write_text = Path.write_text
    original_path_write_bytes = Path.write_bytes

    def guarded_path_write(method):
        def write_if_coverage(path, *args, **kwargs):
            return reject_write(path)
        return write_if_coverage

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

    monkeypatch.setattr(Path, "write_text", guarded_path_write(original_path_write_text))
    monkeypatch.setattr(Path, "write_bytes", guarded_path_write(original_path_write_bytes))
    monkeypatch.setattr(Path, "mkdir", reject_write)
    monkeypatch.setattr(Path, "touch", reject_write)
    monkeypatch.setattr(Path, "unlink", reject_write)
    monkeypatch.setattr(Path, "rmdir", reject_write)
    monkeypatch.setattr(builtins, "open", guarded_open(original_builtin_open))
    monkeypatch.setattr(io, "open", guarded_open(original_io_open))
    monkeypatch.setattr(os, "open", guarded_os_open)
    for name in ("mkdir", "makedirs", "replace", "rename", "remove", "unlink", "rmdir"):
        monkeypatch.setattr(os, name, reject_write)

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

    coverage_before = coverage_path.read_bytes()
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
    assert summary["coverage_matches"] is False
    assert "written" not in summary
    assert coverage_path.read_text(encoding="utf-8") == "# Existing coverage\n"
    assert coverage_path.read_bytes() == coverage_before
    after = {root: snapshot_tree(root) for root in scoped_roots}
    assert after == before
    assert coverage_path.is_file()


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


def test_check_cli_accepts_coverage_without_writing_it(tmp_path):
    make_repo(tmp_path)
    inventory = MODULE.collect_inventory(tmp_path)
    expected = MODULE.render_coverage(inventory)
    expected_artifact = MODULE.render_coverage_artifact(inventory)
    write(tmp_path, "docs/API_COVERAGE.md", expected)
    write(tmp_path, "docs/API_COVERAGE.json", expected_artifact)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    artifact_path = tmp_path / "docs" / "API_COVERAGE.json"
    before_bytes = coverage_path.read_bytes()
    before_mtime = coverage_path.stat().st_mtime_ns
    artifact_before = artifact_path.read_bytes()
    artifact_mtime = artifact_path.stat().st_mtime_ns
    command = [sys.executable, "tools/surface_inventory.py", "--root", str(tmp_path), "--check"]

    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert coverage_path.read_bytes() == before_bytes
    assert coverage_path.stat().st_mtime_ns == before_mtime
    assert artifact_path.read_bytes() == artifact_before
    assert artifact_path.stat().st_mtime_ns == artifact_mtime
    summary = json.loads(result.stdout)
    assert summary["coverage_matches"] is True
    assert summary["artifact_matches"] is True
    assert "written" not in summary



def test_check_cli_reports_drift_without_rewriting_coverage(tmp_path):
    make_repo(tmp_path)
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_text("# Stale coverage\n", encoding="utf-8")
    before_bytes = coverage_path.read_bytes()
    before_mtime = coverage_path.stat().st_mtime_ns
    command = [
        sys.executable,
        "tools/surface_inventory.py",
        "--root",
        str(tmp_path),
        "--check",
    ]

    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["coverage_matches"] is False
    assert any("rendered coverage document differs" in item for item in summary["drift"])
    assert "written" not in summary
    assert coverage_path.read_bytes() == before_bytes
    assert coverage_path.stat().st_mtime_ns == before_mtime




def test_write_doc_cli_process_generates_coverage(tmp_path):
    make_repo(tmp_path)
    task_id = "task-write-coverage-cli-test"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    assert not coverage_path.exists()
    expected = MODULE.render_coverage(MODULE.collect_inventory(tmp_path), task_id=task_id)
    expected_artifact = MODULE.render_coverage_artifact(MODULE.collect_inventory(tmp_path), task_id=task_id)

    command = [
        sys.executable,
        "tools/surface_inventory.py",
        "--root",
        str(tmp_path),
        "--write-doc",
        "--task-id",
        task_id,
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert coverage_path.read_text(encoding="utf-8") == expected
    assert (tmp_path / "docs" / "API_COVERAGE.json").read_text(encoding="utf-8") == expected_artifact
    summary = json.loads(result.stdout)
    assert summary["written"] == "docs/API_COVERAGE.md"
    assert summary["coverage_rows"] > 0


def test_write_doc_mode_updates_coverage(tmp_path, capsys):
    make_repo(tmp_path)
    task_id = "task-write-coverage-test"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    write(tmp_path, "docs/API_COVERAGE.md", "# Stale coverage\n")
    inventory = MODULE.collect_inventory(tmp_path)
    expected = MODULE.render_coverage(inventory, task_id=task_id)
    expected_artifact = MODULE.render_coverage_artifact(inventory, task_id=task_id)

    result = MODULE.main(["--root", str(tmp_path), "--write-doc", "--task-id", task_id])

    assert result == 0
    assert coverage_path.read_text(encoding="utf-8") == expected
    assert (tmp_path / "docs" / "API_COVERAGE.json").read_text(encoding="utf-8") == expected_artifact
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

    assert "coverage-task-id: " + task_id in rendered
    assert lines[header_index] == "| Surface | Name | Evidence status | Owner | Operation ID |"
    assert data_rows
    artifact = json.loads(MODULE.render_coverage_artifact(MODULE.collect_inventory(tmp_path), task_id))
    assert all(row.get("task_id") == task_id for row in artifact["coverage_rows"])
    assert len(data_rows) == len(artifact["coverage_rows"])


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


def test_generic_truthy_return_does_not_handle_unmatched_generated_mcp_action(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "src/local_ai_hub/mcp_server.py",
        '''from typing import Literal

@mcp.tool()
def local_ai_repo(action: Literal["search", "missing"]):
    if action == "search":
        return search()
    return {"ok": True}
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


def test_schema_fallback_uses_project_defaults_not_ambient_config(tmp_path, monkeypatch):
    write(tmp_path, "defaults.toml", (ROOT / "defaults.toml").read_text(encoding="utf-8"))
    ambient_config = tmp_path / "ambient.toml"
    ambient_config.write_text(
        "[features]\nstatus = false\ntasks = false\nwork_orchestrator = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_AI_CONFIG", str(ambient_config))

    schemas, evidence, errors, disabled_tools = MODULE._generated_mcp_schemas(tmp_path)

    assert errors == []
    assert "local_ai_status" in schemas
    assert set(evidence) == set(schemas)
    assert "local_ai_status" not in disabled_tools


def test_ignored_runtime_config_and_schemas_do_not_change_inventory(tmp_path, monkeypatch):
    make_repo(tmp_path)
    write(tmp_path, "defaults.toml", (ROOT / "defaults.toml").read_text(encoding="utf-8"))
    write(
        tmp_path,
        "config.toml",
        "[features]\nstatus = false\n",
    )
    write(
        tmp_path,
        "generated/schemas/local_ai_rogue.json",
        json.dumps({"name": "local_ai_rogue", "parameters": {"properties": {}}}),
    )
    monkeypatch.setattr(
        MODULE,
        "_git_ignores",
        lambda root, relative: relative in {"config.toml", "generated/schemas/local_ai_repo.json"},
    )

    schemas, evidence, errors, disabled_tools = MODULE._generated_mcp_schemas(tmp_path)

    assert errors == []
    assert "local_ai_status" in schemas
    assert "local_ai_rogue" not in schemas
    assert set(evidence) == set(schemas)
    assert all(value.endswith("generate_mcp_tool_schemas") for value in evidence.values())
    assert "local_ai_status" not in disabled_tools


def test_missing_generated_manifest_is_reported(tmp_path):
    make_repo(tmp_path)
    (tmp_path / "docs" / "UPDATE_PROMPT.md").unlink()

    inventory = MODULE.collect_inventory(tmp_path)

    assert set(inventory["generated_manifests"]) == {
        "generated/schemas/local_ai_repo.json",
        "generated/schemas/local_ai_status.json",
    }
    assert not any("missing generated manifest" in item for item in inventory["drift"])


def test_missing_declared_generated_manifest_is_reported(tmp_path):
    make_repo(tmp_path)
    (tmp_path / "generated" / "schemas" / "local_ai_status.json").unlink()

    inventory = MODULE.collect_inventory(tmp_path)

    assert any(
        "missing generated manifest generated/schemas/local_ai_status.json" in item
        for item in inventory["drift"]
    )


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
        "scope_boundary",
        "provenance",
        "test_ids",
        "test_coverage",
        "behavioral_disposition",
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
    assert all(row.get("task_id") == task_id for row in rows)
    artifact = json.loads(MODULE.render_coverage_artifact(inventory, task_id))
    assert all(row["test_ids"] and row["test_coverage"] for row in artifact["coverage_rows"])
    assert all(row["behavioral_disposition"] for row in artifact["coverage_rows"])
    assert all(
        row["owner_task"] == (MODULE._operation_owner_task({**row, "owner_task": None}) or task_id)
        for row in rows
    )
    assert all(row["operation_id"] and row["handler"] and row["test_ids"] for row in rows)
    contract = next(row["contract"] for row in rows if row["surface"] == "MCP tool" and row["name"] == "local_ai_repo")
    assert contract["input_schema"]["properties"]["query"]["default"] == ""
    assert contract["output_schema"]["properties"]["success"]["type"] == "boolean"


def test_check_cli_preserves_coverage_until_explicit_write_doc(tmp_path):
    make_repo(tmp_path)
    task_id = "task-check-is-read-only"
    coverage_path = tmp_path / "docs" / "API_COVERAGE.md"
    stale_coverage = b"# Stale coverage; check must not replace it.\n"
    stale_hash = hashlib.sha256(stale_coverage).hexdigest()
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.write_bytes(stale_coverage)
    before_mtime = coverage_path.stat().st_mtime_ns
    root_coverage_path = ROOT / "docs" / "API_COVERAGE.md"
    root_before_bytes = root_coverage_path.read_bytes()
    root_before_mtime = root_coverage_path.stat().st_mtime_ns
    command = [sys.executable, str(ROOT / "tools" / "surface_inventory.py"), "--root", str(tmp_path)]

    check = subprocess.run(
        [*command, "--check"], cwd=ROOT, capture_output=True, text=True, check=False
    )

    assert check.returncode == 1
    check_summary = json.loads(check.stdout)
    assert check_summary["coverage_matches"] is False
    assert "written" not in check_summary
    assert coverage_path.read_bytes() == stale_coverage
    assert hashlib.sha256(coverage_path.read_bytes()).hexdigest() == stale_hash
    assert coverage_path.stat().st_mtime_ns == before_mtime
    assert root_coverage_path.read_bytes() == root_before_bytes
    assert root_coverage_path.stat().st_mtime_ns == root_before_mtime

    write_doc = subprocess.run(
        [*command, "--write-doc", "--task-id", task_id],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert write_doc.returncode == 0, write_doc.stdout + write_doc.stderr
    write_summary = json.loads(write_doc.stdout)
    assert write_summary["written"] == "docs/API_COVERAGE.md"
    assert coverage_path.read_text(encoding="utf-8") == MODULE.render_coverage(
        MODULE.collect_inventory(tmp_path), task_id
    )
    assert coverage_path.read_bytes() != stale_coverage


def test_behavioral_coverage_links_are_operation_specific(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "tests/test_operation_behavior.py",
        '''import urllib.request
from urllib.request import Request as HttpRequest, urlopen as fetch_url
from local_ai_hub.mcp_server import local_ai_repo
from tools.hubctl import main as cli_main

def test_repo_search_dispatch():
    result = local_ai_repo(action="search")
    assert result["success"] is True

def test_repo_context_dispatch():
    result = local_ai_repo(action="context")
    assert result["success"] is True

def test_post_health_route():
    result = request("POST", "http://127.0.0.1/health", {})
    assert result["success"] is True

def test_urllib_request_route():
    with urllib.request.urlopen("http://127.0.0.1/api/health") as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_request_alias_defaults_to_get():
    request = HttpRequest("http://127.0.0.1/api/health")
    with fetch_url(request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_urlopen_data_uses_post():
    with urllib.request.urlopen("http://127.0.0.1/health", data=b"{}") as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_keyword_url_route():
    request = urllib.request.Request(url="http://127.0.0.1/api/health")
    with urllib.request.urlopen(url=request) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert result["success"] is True

def test_urllib_post_helper_route():
    def post_json(endpoint, data):
        request = urllib.request.Request(
            f"http://127.0.0.1{endpoint}", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    result = post_json("/health", {})
    assert result["success"] is True

def _module_request(url, *, method="GET", body=None):
    request = urllib.request.Request(url, method="GET")
    request = urllib.request.Request(url, data=body, method=method)
    with urllib.request.urlopen(request) as response:
        return response.status, dict(response.headers), response.read()

def test_module_level_urllib_helper_links_asserted_operation():
    url = "http://127.0.0.1" + "/api/status"
    url = "http://127.0.0.1" + "/api/repo/search"
    status, _, body = _module_request(url, method="POST", body=b"{}")
    assert status == 200
    assert json.loads(body)["success"] is True

def _module_discarded_request(url):
    with urllib.request.urlopen(url) as response:
        response.read()
    return {"success": True}

def test_module_level_helper_discarding_response_is_not_route_coverage():
    result = _module_discarded_request("http://127.0.0.1/api/repo/search")
    assert result["success"] is True

def test_module_level_urllib_helper_defaults_to_get():
    _, _, body = _module_request("http://127.0.0.1/api/health")
    assert json.loads(body)["success"] is True

def test_client_health_method():
    client = HubClient()
    result = client.get_health()
    assert result["success"] is True

def test_cli_status_operation():
    assert cli_main(["status"]) == 0

def test_status_route_is_only_documented():
    assert "/api/status" in "documented route: /api/status"

def test_context_pack_http_request():
    result = request("POST", "http://127.0.0.1/api/context/pack", {})
    assert result["success"] is True
''',
    )

    write(
        tmp_path,
        "tests/test_mcp_compact_transport.py",
        '''from local_ai_hub.mcp_server import local_ai_repo

def test_local_ai_repo_context_forwards_guarded_pack_fields():
    result = local_ai_repo(action="context", root="C:/repo", query="context")
    assert result["success"] is True
''',
    )

    links = MODULE.collect_inventory(tmp_path)["behavioral_test_links"]

    assert links["MCP action local_ai_repo::search"] == [
        "tests/test_operation_behavior.py::test_repo_search_dispatch"
    ]
    context_action_selector = (
        "tests/test_mcp_compact_transport.py::"
        "test_local_ai_repo_context_forwards_guarded_pack_fields"
    )
    assert context_action_selector in links["MCP action local_ai_repo::context"]
    assert links["HTTP POST::/health"] == sorted([
        "tests/test_operation_behavior.py::test_post_health_route",
        "tests/test_operation_behavior.py::test_urllib_post_helper_route",
        "tests/test_operation_behavior.py::test_urllib_urlopen_data_uses_post",
    ])
    assert links["HTTP GET::/api/health"] == sorted([
        "tests/test_operation_behavior.py::test_urllib_request_alias_defaults_to_get",
        "tests/test_operation_behavior.py::test_urllib_request_route",
        "tests/test_operation_behavior.py::test_urllib_keyword_url_route",
        "tests/test_operation_behavior.py::test_module_level_urllib_helper_defaults_to_get",
    ])
    assert "tests/test_operation_behavior.py::test_module_level_urllib_helper_defaults_to_get" not in links.get(
        "HTTP POST::/api/health", []
    )
    assert links["HTTP POST::/api/repo/"] == [
        "tests/test_operation_behavior.py::test_module_level_urllib_helper_links_asserted_operation"
    ]
    assert "tests/test_operation_behavior.py::test_module_level_helper_discarding_response_is_not_route_coverage" not in links.get(
        "HTTP POST::/api/repo/", []
    )
    assert "tests/test_operation_behavior.py::test_module_level_urllib_helper_links_asserted_operation" not in links.get(
        "HTTP GET::/api/repo/", []
    )
    assert links["HubClient method::get_health"] == [
        "tests/test_operation_behavior.py::test_client_health_method"
    ]
    assert links["CLI operation::status"] == [
        "tests/test_operation_behavior.py::test_cli_status_operation"
    ]
    assert "HTTP GET::/api/status" not in links
    assert "HTTP POST::/api/context/pack" not in links
    rows = MODULE.coverage_rows(MODULE._findings(MODULE.collect_inventory(tmp_path)))
    for key, expected_selector in (
        (("MCP action local_ai_repo", "search"), "test_repo_search_dispatch"),
        (("HTTP POST", "/health"), "test_post_health_route"),
        (("HubClient method", "get_health"), "test_client_health_method"),
        (("CLI operation", "status"), "test_cli_status_operation"),
    ):
        row = next(row for row in rows if (row["surface"], row["name"]) == key)
        assert row["test_coverage"] == "behavioral tests linked; coverage bounded to cited assertions"
        assert any(expected_selector in selector for selector in row["test_ids"])

def test_cli_operation_links_allow_dynamic_option_values():
    links = MODULE.collect_inventory(ROOT)["behavioral_test_links"]
    for operation, selector in (
        (
            "generate",
            "tests/test_hubctl_unlinked_operations.py::test_hubctl_generate_dispatches_writers_and_optional_agent_install",
        ),
        (
            "service-status",
            "tests/test_hubctl_unlinked_operations.py::test_hubctl_service_status_reads_configured_supervisor_file",
        ),
        (
            "status",
            "tests/test_hubctl_unlinked_operations.py::test_hubctl_status_reports_offline_without_starting_service",
        ),
    ):
        assert selector in links[f"CLI operation::{operation}"]

def test_behavioral_links_require_receiver_invocation_and_result_assertion(tmp_path):
    make_repo(tmp_path)
    write(
        tmp_path,
        "tests/test_behavioral_precision.py",
        '''import sys
import urllib.request
from urllib.request import Request as UrlRequest, urlopen as fetch_url
from local_ai_hub import mcp_server as mcp_mod
from local_ai_hub import http_server as http_mod
from local_ai_hub.http_server import Handler
from tools.hubctl import main as cli_main
from tools import hubctl

def test_hubclient_call_is_asserted():
    client = HubClient()
    result = client.get_health()
    assert result["success"] is True

def test_same_method_name_on_other_receiver_is_not_hubclient():
    store = Store()
    result = store.get_health()
    assert result["success"] is True

def test_hubclient_call_without_result_assertion_is_not_coverage():
    client = HubClient()
    client.get_health()
    assert True

def test_mcp_action_without_result_assertion_is_not_coverage():
    local_ai_repo(action="search")
    assert True

def test_status_word_in_payload_is_not_cli_operation():
    result = cli_main(["doctor"])
    payload = {"status": "OK"}
    assert result == 0 and payload["status"] == "OK"

def test_cli_status_invocation_is_asserted():
    result = cli_main(["status"])
    assert result == 0

def test_http_methods_stay_paired_with_their_paths():
    get_result = request("GET", "http://127.0.0.1/api/health", {})
    post_result = request("POST", "http://127.0.0.1/health", {})
    assert get_result["success"] is True
    assert post_result["success"] is True

def test_http_get_from_running_app_client_fixture_is_coverage(running_app_client):
    client, app = running_app_client
    result = client.get("http://127.0.0.1/api/health")
    assert result["success"] is True

def test_http_call_without_result_assertion_is_not_coverage():
    request("POST", "http://127.0.0.1/health", {})
    assert True

def test_mcp_tool_name_on_unrelated_receiver_is_not_coverage():
    result = fake.local_ai_repo(action="search")
    assert result["success"] is True

def test_mcp_action_from_imported_module_is_coverage():
    result = mcp_mod.local_ai_repo(action="search")
    assert result["success"] is True

def test_mcp_action_from_imported_alias_is_coverage():
    from local_ai_hub.mcp_server import local_ai_repo as repo_call
    result = repo_call(action="search")
    assert result["success"] is True

async def test_mcp_protocol_call_dispatches_tool():
    result = await mcp_mod.mcp.call_tool("local_ai_status", {"detail": "brief"})
    assert result is not None

async def test_unrelated_receiver_call_tool_is_not_mcp_protocol():
    result = await fake.mcp.call_tool("local_ai_status", {"detail": "brief"})
    assert result is not None

def test_local_mcp_function_with_tool_name_is_not_coverage():
    def local_ai_repo(action):
        return {"success": True}
    result = local_ai_repo(action="search")
    assert result["success"] is True

def test_http_method_on_unrelated_receiver_is_not_coverage():
    result = fake.get("http://127.0.0.1/health")
    urlopen("http://127.0.0.1/api/health")
    assert result["success"] is True

def test_unrelated_urlopen_is_not_coverage():
    result = fake.urlopen("http://127.0.0.1/api/health")
    assert result["success"] is True

def test_unrelated_request_constructor_is_not_coverage():
    result = fake.Request("http://127.0.0.1/health", method="POST")
    assert result["success"] is True

def test_stale_urllib_request_binding_is_not_coverage():
    request = UrlRequest("http://127.0.0.1/api/health")
    request = "http://127.0.0.1/api/status"
    with fetch_url(request) as response:
        result = response.read()
    assert result is not None

def test_local_wrapper_that_discards_http_result_is_not_coverage():
    def post_json(endpoint, data):
        request = urllib.request.Request(
            f"http://127.0.0.1{endpoint}", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request):
            pass
        return {"success": True}

    result = post_json("/health", {})
    assert result["success"] is True

def test_cli_sys_argv_patch_links_imported_main():
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "doctor"])
    result = hubctl.main()
    assert result == 0

def test_local_main_name_is_not_cli_operation():
    def main(argv):
        return 0
    result = main(["status"])
    assert result == 0

def test_cli_sys_argv_patch_on_same_line_links_operation():
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "status"]); result = hubctl.main()
    assert result == 0

def test_cli_sys_argv_index_update_replaces_earlier_operation():
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "status"])
    sys.argv[1] = "doctor"
    result = hubctl.main()
    assert result == 0

def test_cli_unknown_sys_argv_index_update_clears_earlier_operation():
    monkeypatch.setattr(sys, "argv", ["hubctl.py", "status"])
    sys.argv[1] = operation
    result = hubctl.main()
    assert result == 0

def test_direct_handler_route_with_asserted_response_is_coverage():
    handler = Handler.__new__(Handler)
    handler.path = "/health"
    handler._send = lambda status, body: sent.append((status, body))
    handler.do_GET()
    assert sent[0][0] == 200

def test_direct_handler_route_without_response_assertion_is_not_coverage():
    handler = Handler.__new__(Handler)
    handler.path = "/health"
    handler.do_GET()
    assert True

class TestHandlerOperations:
    def test_class_method_route_with_asserted_response(self):
        handler = Handler.__new__(Handler)
        handler.path = "/health"
        handler._send = lambda status, body: sent.append((status, body))
        handler.do_GET()
        assert sent[0][0] == 200

def test_module_qualified_handler_route_with_asserted_response():
    handler = http_mod.Handler.__new__(http_mod.Handler)
    handler.path = "/health"
    handler._send = lambda status, body: sent.append((status, body))
    handler.do_GET()
    assert sent[0][0] == 200

def test_unimported_handler_path_is_not_linked():
    handler = local_ai_hub.http_server.Handler.__new__(local_ai_hub.http_server.Handler)
    handler.path = "/health"
    handler._send = lambda status, body: sent.append((status, body))
    handler.do_GET()
    assert sent[0][0] == 200
''',
    )

    links = MODULE.collect_inventory(tmp_path)["behavioral_test_links"]

    assert links["HubClient method::get_health"] == [
        "tests/test_behavioral_precision.py::test_hubclient_call_is_asserted"
    ]
    assert links["MCP action local_ai_repo::search"] == [
        "tests/test_behavioral_precision.py::test_mcp_action_from_imported_alias_is_coverage",
        "tests/test_behavioral_precision.py::test_mcp_action_from_imported_module_is_coverage",
    ]
    assert links["MCP tool::local_ai_status"] == [
        "tests/test_behavioral_precision.py::test_mcp_protocol_call_dispatches_tool"
    ]
    assert "tests/test_behavioral_precision.py::test_unrelated_receiver_call_tool_is_not_mcp_protocol" not in links[
        "MCP tool::local_ai_status"
    ]
    assert "tests/test_behavioral_precision.py::test_mcp_tool_name_on_unrelated_receiver_is_not_coverage" not in links.get(
        "MCP action local_ai_repo::search", []
    )
    assert "tests/test_behavioral_precision.py::test_local_mcp_function_with_tool_name_is_not_coverage" not in links.get(
        "MCP action local_ai_repo::search", []
    )
    assert links["CLI operation::status"] == sorted([
        "tests/test_behavioral_precision.py::test_cli_status_invocation_is_asserted",
        "tests/test_behavioral_precision.py::test_cli_sys_argv_patch_on_same_line_links_operation",
    ])
    assert links["HTTP GET::/api/health"] == sorted([
        "tests/test_behavioral_precision.py::test_http_methods_stay_paired_with_their_paths",
        "tests/test_behavioral_precision.py::test_http_get_from_running_app_client_fixture_is_coverage",
    ])
    assert links["HTTP POST::/health"] == [
        "tests/test_behavioral_precision.py::test_http_methods_stay_paired_with_their_paths"
    ]
    assert "HTTP POST::/api/health" not in links
    wrong_http_selector = "tests/test_behavioral_precision.py::test_http_method_on_unrelated_receiver_is_not_coverage"
    assert wrong_http_selector not in links.get("HTTP GET::/health", [])
    assert wrong_http_selector not in links.get("HTTP GET::/api/health", [])
    assert "tests/test_behavioral_precision.py::test_unrelated_urlopen_is_not_coverage" not in links.get(
        "HTTP GET::/api/health", []
    )
    assert "tests/test_behavioral_precision.py::test_unrelated_request_constructor_is_not_coverage" not in links.get(
        "HTTP POST::/health", []
    )
    assert "tests/test_behavioral_precision.py::test_stale_urllib_request_binding_is_not_coverage" not in links.get(
        "HTTP GET::/api/health", []
    )
    assert "tests/test_behavioral_precision.py::test_local_wrapper_that_discards_http_result_is_not_coverage" not in links.get(
        "HTTP POST::/health", []
    )
    assert links["CLI operation::doctor"] == sorted([
        "tests/test_behavioral_precision.py::test_status_word_in_payload_is_not_cli_operation",
        "tests/test_behavioral_precision.py::test_cli_sys_argv_patch_links_imported_main",
        "tests/test_behavioral_precision.py::test_cli_sys_argv_index_update_replaces_earlier_operation",
    ])
    assert "tests/test_behavioral_precision.py::test_cli_unknown_sys_argv_index_update_clears_earlier_operation" not in links.get(
        "CLI operation::status", []
    )
    assert links["HTTP GET::/health"] == sorted([
        "tests/test_behavioral_precision.py::test_direct_handler_route_with_asserted_response_is_coverage",
        "tests/test_behavioral_precision.py::TestHandlerOperations::test_class_method_route_with_asserted_response",
        "tests/test_behavioral_precision.py::test_module_qualified_handler_route_with_asserted_response",
    ])
    assert "tests/test_behavioral_precision.py::test_unimported_handler_path_is_not_linked" not in links[
        "HTTP GET::/health"
    ]
    assert "tests/test_behavioral_precision.py::test_direct_handler_route_without_response_assertion_is_not_coverage" not in links[
        "HTTP GET::/health"
    ]

def test_existing_cli_argv_calls_link_each_operation():
    links = MODULE.collect_inventory(ROOT)["behavioral_test_links"]
    selector = "tests/test_agent_os_enhancements.py::test_hubctl_agent_state_and_cleanup"

    assert selector in links["CLI operation::agent-state"]
    assert selector in links["CLI operation::cleanup"]


def test_hubclient_target_links_match_the_client_method_handler():
    inventory = MODULE.collect_inventory(ROOT)
    findings = MODULE._findings(inventory)
    task_target_rows = [
        finding
        for finding in findings
        if finding["surface"] == "HubClient target"
        and finding["name"] == "POST /api/agent-state/tasks"
    ]
    create_selector = (
        "tests/test_client_operation_acceptance.py::"
        "test_client_create_task_targets_agent_state_tasks"
    )
    by_handler = {finding["handler"]: finding for finding in task_target_rows}

    assert create_selector in by_handler["create_task"].get("behavioral_test_ids", [])
    assert all(
        create_selector not in finding.get("behavioral_test_ids", [])
        for handler, finding in by_handler.items()
        if handler != "create_task"
    )
    fixture_selector = "tests/test_agent_state_transport.py::test_client_convenience_methods"
    links = inventory["behavioral_test_links"]

    assert fixture_selector in links["HubClient method::get_task"]
    assert fixture_selector in links["HubClient target::POST /api/agent-state/tasks::get_task"]
    incident_selector = (
        "tests/test_client_operation_acceptance.py::"
        "test_client_incident_decision_targets_agent_state_incidents"
    )
    incident_coord_targets = [
        finding
        for finding in findings
        if finding["surface"] == "HubClient target"
        and finding["name"] == "POST /api/agent-state/incidents"
        and finding["handler"] == "coord"
    ]

    assert len(incident_coord_targets) == 3
    assert all(
        incident_selector not in finding.get("behavioral_test_ids", [])
        for finding in incident_coord_targets
    )


def test_generation_task_preserves_explicit_dynamic_route_owner():
    inventory = MODULE.collect_inventory(ROOT)
    rows = MODULE.coverage_rows(MODULE._findings(inventory), task_id="T19")
    matches = [
        row for row in rows
        if row["surface"] == "HTTP POST" and row["name"] == "/api/context/pack"
    ]

    assert len(matches) == 1
    assert matches[0]["owner_task"] == "T14"
    assert matches[0]["task_id"] == "T19"






def test_context_pack_dynamic_route_retains_t14_owner(tmp_path):
    make_repo(tmp_path)

    inventory = MODULE.collect_inventory(tmp_path)
    route = next(
        item for item in inventory["http_routes"]
        if item["method"] == "POST" and item["path"] == "/api/context/pack"
    )

    assert route["classification"] == "registered_dynamic"
    assert route["owner_task"] == "T14"
    assert "owner_gate" not in route["contract"]


def test_coverage_rows_dispose_behavioral_evidence_explicitly():
    rows = MODULE.coverage_rows([
        {
            "surface": "HTTP GET",
            "name": "/verified",
            "evidence": ["src/local_ai_hub/http_server.py:10"],
            "behavioral_test_ids": ["tests/test_http.py::test_verified"],
        },
        {
            "surface": "HTTP GET",
            "name": "/metadata",
            "evidence": ["src/local_ai_hub/http_server.py:20"],
        },
        {
            "surface": "HTTP GET",
            "name": "/linked-unverified",
            "evidence": ["src/local_ai_hub/http_server.py:30"],
            "test_ids": ["tests/test_http.py::test_transport"],
        },
    ])

    assert [row["behavioral_disposition"] for row in rows] == [
        "asserted behavior test linked",
        "no asserted operation test linked; behavior unverified",
        "test selector linked; behavior unverified",
    ]

def test_behavioral_disposition_excludes_metadata_only_selectors():
    inventory = MODULE.collect_inventory(ROOT)
    rows = MODULE.coverage_rows(MODULE._findings(inventory), task_id=ROOT_TASK_ID)
    metadata_rows = [
        row for row in rows
        if row["test_coverage"] == "metadata only; operation behavior unverified"
    ]
    behavioral_rows = [
        row for row in rows
        if row["test_coverage"] == "behavioral tests linked; coverage bounded to cited assertions"
    ]
    selectors = [selector for linked in inventory["behavioral_test_links"].values() for selector in linked]

    assert metadata_rows
    assert behavioral_rows
    assert not any("test_operation_contract_metadata" in selector for selector in selectors)
    assert any(
        "test_client_create_task_targets_agent_state_tasks" in selector
        for selector in selectors
    )
    assert all(
        row["behavioral_disposition"] == "no asserted operation test linked; behavior unverified"
        and row["test_ids"] == [
            f"tests/test_surface_inventory.py::test_operation_contract_metadata[{row['operation_id']}]"
        ]
        for row in metadata_rows
    )
    assert all(
        row["behavioral_disposition"] == "asserted behavior test linked"
        and row["test_ids"]
        and all("test_operation_contract_metadata" not in selector for selector in row["test_ids"])
        for row in behavioral_rows
    )
