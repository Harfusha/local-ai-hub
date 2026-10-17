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


def test_python_sdk_docs_cover_t19_workflows():
    sdk_doc = (ROOT / "docs" / "PYTHON_SDK.md").read_text(encoding="utf-8")

    for workflow in (
        "callers(",
        "context_pack(",
        "verify_receipt(",
        "continue_conversation(",
        "cancel_job(",
        'coord("pubsub_poll"',
        'coord("task_resume"',
        "get_evidence(",
    ):
        assert workflow in sdk_doc

    assert "maps one client call to one endpoint" in sdk_doc
    assert "terminal" in sdk_doc and "retryable" in sdk_doc
    assert "8/8 successful workflows on first direct call; 8 HTTP requests total" in sdk_doc
    assert 'client.coord("pubsub_poll", root=root, topic=..., after_seq=0, limit=50)' in sdk_doc
    assert "integer `after_seq` cursor" in sdk_doc
    assert "historical evidence, not acceptance for this merged revision" in sdk_doc


def test_sdk_docs_explain_resume_state_and_failure_recovery():
    sdk_doc = (ROOT / "docs" / "PYTHON_SDK.md").read_text(encoding="utf-8")

    assert "Sets task status to `ACTIVE` and preserves checkpoint metadata; does not restore workspace files." in sdk_doc
    assert "context mode must be adaptive" in sdk_doc
    assert "conversation not found" in sdk_doc
    continuation_guidance = next(
        line.lower()
        for line in sdk_doc.splitlines()
        if "a continuation is already running" in line.lower()
    )
    assert "continuation is already running" in continuation_guidance
    assert "wait for it to finish" in continuation_guidance
    assert "do not send a duplicate request" in continuation_guidance
    assert "`in_progress=true`" in continuation_guidance
    assert "`retryable=true`" in continuation_guidance
    assert "Inspect current task or job state before retrying." in sdk_doc
