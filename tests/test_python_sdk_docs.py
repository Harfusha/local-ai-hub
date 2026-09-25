from __future__ import annotations

import ast
from pathlib import Path

from local_ai_hub.client import HubClient

ROOT = Path(__file__).resolve().parents[1]


def test_python_sdk_quickstart_matches_supported_client_surface():
    sdk_path = ROOT / "docs" / "PYTHON_SDK.md"
    assert sdk_path.is_file(), "Python SDK quickstart is missing"
    sdk_doc = sdk_path.read_text(encoding="utf-8")
    installation_doc = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
    start = sdk_doc.index("```python") + len("```python")
    end = sdk_doc.index("```", start)
    example = sdk_doc[start:end]
    tree = ast.parse(example)

    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called_methods = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert ("local_ai_hub.client", "HubClient") in imports
    assert "status" in called_methods and callable(HubClient.status)
    assert "close" in called_methods and callable(HubClient.close)
    assert "[Python SDK](PYTHON_SDK.md)" in installation_doc
