import ast
from pathlib import Path

from local_ai_hub.deterministic import DeterministicEngine


_HOISTED_FAMILIES = {
    "_extract_infra_facts",
    "_extract_source_facts",
    "_parse_manifest",
    "diff_facts",
    "fold_brace_blocks",
    "extract_api_spec",
}


def test_static_regexes_are_not_compiled_inside_parser_functions() -> None:
    source_path = Path(__file__).parents[2] / "src/local_ai_hub/deterministic.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    remaining = []

    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _HOISTED_FAMILIES:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if (
                isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "re"
                and child.func.attr == "compile"
            ):
                remaining.append(f"{node.name}:{child.lineno}")

    assert remaining == []


def test_regex_backed_parser_fixtures_keep_their_facts(tmp_path: Path) -> None:
    class SnapshotReader:
        @staticmethod
        def _read_snapshot(path: Path):
            return "fixture", path.read_text(encoding="utf-8").splitlines()

        @staticmethod
        def iter_files(root: str):
            return Path(root).rglob("*")

    engine = DeterministicEngine(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=SnapshotReader(),
    )

    infra = engine._extract_infra_facts(
        "azure-pipelines.yml", "stages:\n- stage: build\n  jobs:\n  - job: verify\n"
    )
    assert any(fact["kind"] == "ci_stage" and fact["value"] == "build" for fact in infra)

    js_source = engine._extract_source_facts(
        "src/server.js", "const endpoint = process.env.API_ENDPOINT;\n"
    )
    assert any("API_ENDPOINT" in str(fact) for fact in js_source)

    component_source = engine._extract_source_facts(
        "src/HealthPanel.jsx",
        "import React from 'react';\nexport function HealthPanel() { return null; }\n",
    )
    assert any(
        fact["kind"] == "react_component" and fact["name"] == "HealthPanel"
        for fact in component_source
    )

    manifest = tmp_path / "package.json"
    manifest.write_text('{"dependencies":{"fastify":"^5.0.0"}}', encoding="utf-8")
    dependencies, _scripts = engine._parse_manifest(manifest, "package.json")
    assert ("fastify", "^5.0.0", "dependencies") in dependencies

    api_root = tmp_path / "api"
    api_root.mkdir()
    (api_root / "server.js").write_text(
        "const app = express();\napp.get('/health', handler);\n", encoding="utf-8"
    )
    api = engine.extract_api_spec(str(api_root), framework="express")
    assert "/health" in str(api)

    diff = engine.diff_facts(
        "--- a/src/server.js\n+++ b/src/server.js\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert diff["files"] == ["src/server.js"]
    assert diff["hunks"] == 1

    folded = engine.fold_brace_blocks(
        "function calculate() {\n  return 42;\n}\n", {"keep"}
    )
    assert "function calculate()" in folded and "return 42" not in folded

    rename_file = tmp_path / "rename.js"
    rename_file.write_text(
        "const exact = old.name;\nconst near = oldXname;\n", encoding="utf-8"
    )
    engine.ast_rename(
        str(tmp_path), "rename.js", "old.name", "new.name", apply_changes=True
    )
    assert rename_file.read_text(encoding="utf-8") == (
        "const exact = new.name;\nconst near = oldXname;\n"
    )
