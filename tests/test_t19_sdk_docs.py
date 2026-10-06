from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _public_client_methods() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    source = ast.parse(
        (ROOT / "src/local_ai_hub/client.py").read_text(encoding="utf-8")
    )
    client = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "HubClient"
    )
    return [
        node
        for node in client.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]


def test_python_sdk_docs_cover_public_methods_and_literal_routes() -> None:
    docs = (ROOT / "docs/PYTHON_SDK.md").read_text(encoding="utf-8")
    methods = _public_client_methods()
    missing_methods = sorted(
        method.name
        for method in methods
        if f"`{method.name}`" not in docs
        and f"`client.{method.name}`" not in docs
        and f"client.{method.name}(" not in docs
    )
    routes = {
        call.args[0].value
        for method in methods
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr in {"get", "post", "request"}
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and call.args[0].value.startswith("/api/")
    }
    missing_routes = sorted(route for route in routes if route not in docs)

    assert methods
    assert not missing_methods
    assert routes
    assert not missing_routes


def test_python_sdk_docs_describe_request_id_and_replay_limits() -> None:
    docs = (ROOT / "docs/PYTHON_SDK.md").read_text(encoding="utf-8")
    methods = {method.name: method for method in _public_client_methods()}

    assert "request_id" in {arg.arg for arg in methods["request"].args.kwonlyargs}
    assert "request_id" in {arg.arg for arg in methods["post"].args.kwonlyargs}
    assert "verified server journal coverage" in docs
    assert "inspect resulting state before retry" in docs


def test_python_sdk_docs_describe_fail_closed_post_replay_policy() -> None:
    docs = (ROOT / "docs/PYTHON_SDK.md").read_text(encoding="utf-8")
    source = (ROOT / "src/local_ai_hub/client.py").read_text(encoding="utf-8")

    assert "small, fail-closed allowlist of read-only POST paths/actions" in docs
    assert "unknown or mutating posts are not resent automatically after transport loss" in docs.lower()
    assert "`request()` defaults to `replay_safe=False`" in docs
    assert "A caller-supplied `request_id` does not make an operation replay-safe" in docs
    assert "def _post_replay_safe(path: str, payload: dict[str, Any] | None) -> bool:" in source
    assert "replay_safe: bool = False" in source
