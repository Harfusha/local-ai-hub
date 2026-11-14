from __future__ import annotations

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.project_card_summary import build_project_card_summary


def test_project_card_summary_maps_deterministic_evidence_and_risks():
    result = build_project_card_summary(
        {"languages": {"Python": 4, "Rust": 2}},
        {"files": 12, "top_paths": [["src/api.py", 4], ["src/worker.py", 2]]},
        [],
        {"facts": [{"path": "src/main.py", "line": 1, "kind": "entrypoint", "name": "main"}]},
        {"facts": [{"path": "config.py", "line": 2, "kind": "env", "name": "MODE"}]},
        {"facts": [{"path": "auth.py", "line": 3, "kind": "security", "name": "token"}]},
        {"facts": [{"path": "worker.py", "line": 4, "kind": "concurrency", "name": "Lock"}]},
        {"facts": [{"path": "db.py", "line": 5, "kind": "database", "name": "users"}]},
        {"facts": [{"path": "deploy.yml", "line": 6, "kind": "ci_job", "name": "test"}]},
        {"scripts": [
            {"name": "pytest", "command": "python -m pytest", "purpose": "tests"},
            {"name": "docs", "command": "mkdocs", "purpose": "documentation"},
        ]},
        {"facts": [{"path": "broken.py", "line": 7, "kind": "syntax", "name": "parse-error"}]},
    )

    assert result == {
        "success": True,
        "deterministic": True,
        "confidence": 0.801,
        "card": {
            "architecture": "Deterministic project map: 12 indexed source files; languages: Python, Rust; top modules: src/api.py, src/worker.py",
            "entry_points": ["src/main.py:1 entrypoint=main"],
            "hot_paths": ["src/api.py", "src/worker.py"],
            "testing": ["pytest -> python -m pytest"],
            "configuration": ["config.py:2 env=MODE"],
            "data_flow": ["db.py:5 database=users"],
            "security": ["auth.py:3 security=token"],
            "concurrency": ["worker.py:4 concurrency=Lock"],
            "infrastructure": ["deploy.yml:6 ci_job=test"],
            "risks": [
                "security-sensitive code present",
                "concurrency-sensitive code present",
                "database/persistence code present",
                "deployment/infrastructure declarations present",
                "1 parser-detected syntax/config errors",
            ],
        },
    }


def test_project_card_summary_prefers_modules_and_accepts_language_shapes():
    result = build_project_card_summary(
        {"languages": ["Python", {"language": "TypeScript"}, 7]},
        {"files": 3, "top_paths": [["ignored.py", 3]]},
        [{"module": "src/first"}, {"module": "src/second"}],
        {"facts": []}, {}, {}, {}, {}, {}, {}, {},
    )

    assert result["card"]["architecture"] == "Deterministic project map: 3 indexed source files; languages: Python, TypeScript, 7; top modules: src/first, src/second"
    assert result["card"]["hot_paths"] == ["src/first", "src/second"]
    assert result["card"]["risks"] == []
    assert result["confidence"] == 0.8


def test_deterministic_engine_project_card_preserves_query_order_and_delegates(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    calls = []
    responses = {
        "entrypoint startup bootstrap main": {"facts": []},
        "configuration environment settings": {"facts": []},
        "security authentication authorization token": {"facts": []},
        "concurrency async threads locks queues": {"facts": []},
        "database sql persistence": {"facts": []},
        "docker compose terraform deployment ci workflow ports protobuf": {"facts": []},
        "test lint build commands": {"scripts": []},
        "syntax parse error": {"facts": []},
    }

    def query(root, query_text, limit):
        calls.append((root, query_text, limit))
        return responses[query_text]

    monkeypatch.setattr(engine, "query", query)
    result = engine.project_card(
        str(repo),
        {"languages": ["Python"]},
        {"files": 1},
        [{"module": "src/main"}],
    )

    assert [query_text for _, query_text, _ in calls] == list(responses)
    assert all(root == str(repo) for root, _, _ in calls)
    assert [limit for _, _, limit in calls] == [30, 35, 30, 30, 30, 40, 30, 20]
    assert result["card"]["architecture"] == "Deterministic project map: 1 indexed source files; languages: Python; top modules: src/main"
    assert result["card"]["hot_paths"] == ["src/main"]
