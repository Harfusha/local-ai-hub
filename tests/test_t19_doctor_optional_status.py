from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _doctor_helpers(*names: str) -> dict[str, object]:
    source_path = ROOT / "tools" / "doctor.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace


def test_missing_optional_components_have_exact_actionable_doctor_outcomes() -> None:
    helpers = _doctor_helpers("_openvino_fallback_reason", "_optional_component_status", "_optional_component_lines")
    status = helpers["_optional_component_status"](
        False, None, ["embeddings", "reranking"], False, True, None, False, False
    )

    assert status["tree_sitter"] == {"installed": False, "state": "missing"}
    assert status["whisper"] == {
        "installed": False,
        "state": "missing",
        "command": None,
        "reason": "transcription returns audio metadata without a transcript.",
    }
    assert status["openvino"] == {
        "installed": False,
        "requested": True,
        "requested_components": ["embeddings", "reranking"],
        "cpu_fallback_enabled": True,
        "cpu_fallback_available": False,
        "fallback_dependencies": {"sentence-transformers": False, "torch": False},
        "state": "missing",
        "reason": (
            "CPU fallback for embeddings is unavailable (missing sentence-transformers). "
            "CPU fallback for reranking is unavailable (missing sentence-transformers, torch)."
        ),
    }
    assert status["serena"] == {
        "enabled": None,
        "state": "unavailable",
        "reason": "Hub did not report Serena diagnostics.",
    }
    assert helpers["_optional_component_lines"](status) == [
        "  [ERR] Tree-sitter:     Missing",
        "  [ERR] Whisper CLI:     Missing; transcription returns audio metadata without a transcript.",
        "  [ERR] OpenVINO:        Requested but missing; CPU fallback for embeddings is unavailable (missing sentence-transformers). CPU fallback for reranking is unavailable (missing sentence-transformers, torch).",
        "  [??] Serena:          Status unavailable; Hub did not report Serena diagnostics.",
    ]


def test_codegraph_standalone_is_not_reported_as_a_hub_component() -> None:
    helpers = _doctor_helpers(
        "_openvino_fallback_reason", "_optional_component_status", "_optional_component_lines"
    )
    status = helpers["_optional_component_status"](
        False, None, [], False, True, None, False, False
    )

    assert "codegraph" not in status
    assert all("codegraph" not in line.casefold() for line in helpers["_optional_component_lines"](status))


def test_openvino_fallback_names_only_the_requested_component() -> None:
    helpers = _doctor_helpers("_openvino_fallback_reason", "_optional_component_status")

    embeddings = helpers["_optional_component_status"](False, None, ["embeddings"], False, True, None, True, True)["openvino"]
    reranking = helpers["_optional_component_status"](False, None, ["reranking"], False, True, None, True, True)["openvino"]
    no_fallback = helpers["_optional_component_status"](False, None, ["embeddings"], False, False, None)["openvino"]

    assert embeddings["requested_components"] == ["embeddings"]
    assert embeddings["cpu_fallback_available"] is True
    assert embeddings["fallback_dependencies"] == {"sentence-transformers": True}
    assert embeddings["reason"] == "embeddings use CPU fallback."
    assert reranking["requested_components"] == ["reranking"]
    assert reranking["cpu_fallback_available"] is True
    assert reranking["fallback_dependencies"] == {"sentence-transformers": True, "torch": True}
    assert reranking["reason"] == "reranking uses CPU fallback."
    assert no_fallback["cpu_fallback_enabled"] is False
    assert no_fallback["cpu_fallback_available"] is False
    assert no_fallback["fallback_dependencies"] == {}
    assert no_fallback["reason"] == "CPU fallback is disabled for embeddings; missing OpenVINO causes an error."


def test_openvino_cpu_fallback_reports_missing_component_runtime_dependencies() -> None:
    helpers = _doctor_helpers("_openvino_fallback_reason", "_optional_component_status")
    embeddings = helpers["_optional_component_status"](
        False, None, ["embeddings"], False, True, None, False, True
    )["openvino"]
    reranking = helpers["_optional_component_status"](
        False, None, ["reranking"], False, True, None, True, False
    )["openvino"]

    assert embeddings["cpu_fallback_available"] is False
    assert embeddings["fallback_dependencies"] == {"sentence-transformers": False}
    assert embeddings["reason"] == (
        "CPU fallback for embeddings is unavailable (missing sentence-transformers)."
    )
    assert reranking["cpu_fallback_available"] is False
    assert reranking["fallback_dependencies"] == {"sentence-transformers": True, "torch": False}
    assert reranking["reason"] == "CPU fallback for reranking is unavailable (missing torch)."


def test_installed_optional_components_keep_runtime_state_and_serena_reason() -> None:
    helpers = _doctor_helpers("_openvino_fallback_reason", "_optional_component_status", "_optional_component_lines")
    serena = {"enabled": True, "state": "missing", "unavailable_reason": "command not found"}
    status = helpers["_optional_component_status"](
        True, "C:/tools/whisper.exe", [], True, True, serena, True, True
    )

    assert status["tree_sitter"] == {"installed": True, "state": "available"}
    assert status["whisper"] == {"installed": True, "state": "available", "command": "C:/tools/whisper.exe", "reason": ""}
    assert status["openvino"] == {
        "installed": True, "requested": False, "requested_components": [],
        "cpu_fallback_enabled": True, "cpu_fallback_available": None,
        "fallback_dependencies": {}, "state": "available", "reason": "",
    }
    assert status["serena"]["state"] == "missing"
    assert status["serena"]["reason"] == "command not found"
    assert "  [OK] Tree-sitter:     Installed" in helpers["_optional_component_lines"](status)


def test_doctor_json_and_text_report_share_the_optional_component_contract() -> None:
    source_path = ROOT / "tools" / "doctor.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    string_keys = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "_optional_component_status" in calls
    assert "_optional_component_lines" in calls
    assert "optional_components" in string_keys


def test_doctor_does_not_discover_or_report_standalone_codegraph() -> None:
    operational_paths = (
        ROOT / "config.toml.example",
        *(
            path
            for path in ROOT.joinpath("src", "local_ai_hub").rglob("*.py")
            if path.name not in {"preprocess.py", "generator.py", "repo_tools.py"}
        ),
        *(path for path in ROOT.joinpath("tools").rglob("*.py") if path.name != "doctor.py"),
    )
    for path in operational_paths:
        source = path.read_text(encoding="utf-8")
        if path.name == "benchmark_t10_repository.py":
            source = source.replace('"tests/test_codegraph_package_policy.py"', "")
        assert "codegraph" not in source.casefold(), path.name

    doctor = (ROOT / "tools" / "doctor.py").read_text(encoding="utf-8")
    assert "codegraph" not in doctor.casefold()
    installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8").casefold()
    assert "codegraphcontext is not a hub dependency or analysis backend" in installation
    assert "hub does not install, configure, preprocess, invoke, or report it" in installation
