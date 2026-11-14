from __future__ import annotations

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.module_card_summary import build_module_card_summary


def test_module_card_summary_combines_cards_with_parser_coordinates():
    file_cards = [
        {
            "path": "src/main.py",
            "card": {
                "symbols": ["main", "serve"],
                "dependencies": ["flask", "sqlite"],
                "risks": ["data/persistence"],
                "tests": [],
                "side_effects": ["database", "http-route"],
            },
        },
        {
            "path": "tests/test_main.py",
            "card": {
                "symbols": ["test_main"],
                "dependencies": ["pytest", "flask"],
                "risks": [],
                "tests": ["tests/test_main.py"],
                "side_effects": ["http-route"],
            },
        },
    ]
    rows = [
        {"path": "src/main.py", "kind": "entrypoint", "name": "main", "line": 3},
        {"path": "src/main.py", "kind": "route", "name": "/health", "line": 8},
        {"path": "tests/test_main.py", "kind": "test_file", "name": "", "line": 1},
    ]

    result = build_module_card_summary("api", file_cards, ["src/main.py", "tests/test_main.py"], rows)

    assert result == {
        "success": True,
        "deterministic": True,
        "confidence": 0.98,
        "card": {
            "purpose": "module api; 2 files; effects=database,http-route",
            "entry_points": [
                "src/main.py",
                "src/main.py::main",
                "src/main.py:3 main",
                "src/main.py:8 /health",
            ],
            "dependencies": ["flask", "sqlite", "pytest"],
            "invariants": [
                "validation files are mapped from indexed test paths",
                "entry points are parser/index coordinates, not inferred behavior",
            ],
            "risks": ["data/persistence"],
            "validation": ["tests/test_main.py"],
        },
    }


def test_module_card_summary_preserves_empty_module_confidence():
    result = build_module_card_summary("empty", [], [], [])

    assert result == {
        "success": True,
        "deterministic": True,
        "confidence": 0.4,
        "card": {
            "purpose": "module empty; 0 files",
            "entry_points": [],
            "dependencies": [],
            "invariants": [],
            "risks": [],
            "validation": [],
        },
    }


def test_deterministic_engine_module_card_delegates_summary(tmp_path):
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.module_card(
        str(tmp_path / "repo"),
        "api",
        [{"path": "src/app.py", "card": {"symbols": ["main"], "dependencies": [], "risks": [], "tests": [], "side_effects": []}}],
    )

    assert result["success"] is True
    assert result["card"]["purpose"] == "module api; 1 files"
    assert result["card"]["entry_points"] == ["src/app.py", "src/app.py::main"]
