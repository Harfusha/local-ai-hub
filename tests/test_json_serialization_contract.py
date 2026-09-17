import ast
import json
from pathlib import Path

from local_ai_hub.http_server import _json_bytes


def test_http_json_bytes_are_compact_without_changing_value():
    value = {"items": [{"name": "žluťoučký", "ok": True}], "count": 1}

    encoded = _json_bytes(value).decode("utf-8")

    assert encoded == '{"items":[{"name":"žluťoučký","ok":true}],"count":1}'
    assert json.loads(encoded) == value


def test_production_json_dumps_are_compact_or_explicitly_human_readable():
    source_root = Path(__file__).parents[1] / "src" / "local_ai_hub"
    human_readable_files = {
        "agent_tasks.py",
        "artifacts.py",
        "benchmark.py",
        "commands.py",
        "deterministic.py",
        "generator.py",
        "token_economy.py",
        "work_orchestrator.py",
    }
    violations = []

    for path in sorted(source_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "json":
                continue
            if node.func.attr != "dumps":
                continue
            keywords = {keyword.arg for keyword in node.keywords if keyword.arg}
            has_pretty_exception = "indent" in keywords and path.name in human_readable_files
            if path.name != "json_utils.py" and "separators" not in keywords and not has_pretty_exception:
                violations.append(f"{path.name}:{node.lineno}")

    assert violations == [], "noncompact production JSON: " + ", ".join(violations)
