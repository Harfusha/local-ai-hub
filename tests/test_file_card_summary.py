from __future__ import annotations

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.file_card_summary import build_file_card


def test_file_card_summary_combines_facts_and_code_index_without_mutating_inputs():
    kinds = {
        "database": ["users"],
        "route": ["/api/search"],
        "env": ["APP_MODE"],
        "concurrency": ["Lock"],
        "security": ["token"],
        "db_table": ["users"],
        "todo": ["TODO"],
        "entrypoint": ["main"],
        "ci_job": ["unit"],
        "terraform_module": ["network"],
        "proto_rpc": ["Lookup"],
        "service": ["api"],
        "port": ["8080"],
    }
    symbols = ["Existing"]
    dependencies = ["existing_package"]

    result = build_file_card(
        "src/app.py",
        "python",
        False,
        kinds,
        symbols,
        dependencies,
        {
            "symbols": [{"name": "SearchHandler"}, {"name": "Existing"}],
            "edges": [{"kind": "imports", "dst": "index_package"}],
            "references": [{"name": "search_index"}],
        },
    )

    assert result == {
        "success": True,
        "deterministic": True,
        "confidence": 0.95,
        "card": {
            "purpose": "app.py: source, python, HTTP routing, entry point, data access, configuration, container infrastructure, CI workflow, RPC schema",
            "symbols": ["Existing", "SearchHandler"],
            "dependencies": ["existing_package", "index_package"],
            "side_effects": [
                "database",
                "http-route",
                "configuration",
                "concurrency",
                "containers",
                "network-ports",
                "ci",
                "infrastructure",
                "rpc-api",
            ],
            "risks": ["security-sensitive", "concurrency-sensitive", "data/persistence", "todo/fixme"],
            "tests": [],
            "keywords": ["existing", "searchhandler", "existing_package", "index_package", "search_index", "api", "search", "app_mode"],
        },
    }
    assert symbols == ["Existing"]
    assert dependencies == ["existing_package"]


def test_file_card_summary_uses_manifest_confidence_and_test_path():
    result = build_file_card(
        "tests/pyproject.toml",
        "toml",
        True,
        {"config": ["tool.pytest"]},
        [],
        [],
        {},
    )

    assert result["confidence"] == 0.97
    assert result["card"]["purpose"] == "pyproject.toml: test, toml, configuration"
    assert result["card"]["tests"] == ["tests/pyproject.toml"]
    assert result["card"]["side_effects"] == ["configuration"]


def test_deterministic_engine_file_card_keeps_fact_and_code_index_enrichment(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "app.py"
    source.write_text("import json\n\ndef search_index():\n    return json.loads('{}')\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    assert engine.update_file(str(repo), "app.py")["success"] is True
    result = engine.file_card(str(repo), "app.py")

    assert result["success"] is True
    assert result["deterministic"] is True
    assert result["card"]["symbols"] == ["search_index"]
    assert "json" in result["card"]["dependencies"]
