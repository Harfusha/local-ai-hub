"""Keep MCP tool wrapper delegation aligned without importing the Hub runtime."""
import ast
from pathlib import Path


def test_local_ai_repo_wrapper_matches_internal_implementation_signature():
    source = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "mcp_tools_repo.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    wrapper = functions["local_ai_repo"]
    implementation = functions["_local_ai_repo_impl"]
    call = next(
        node
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_local_ai_repo_impl"
    )

    positional = [
        arg.arg for arg in implementation.args.posonlyargs + implementation.args.args
    ]
    parameters = set(positional) | {
        arg.arg for arg in implementation.args.kwonlyargs
    }
    assert len(call.args) <= len(positional)

    positional_names = set(positional[:len(call.args)])
    keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
    assert not (positional_names & keyword_names)
    assert keyword_names <= parameters


def test_client_status_projection_preserves_provider_hook_event_inventory():
    source = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "mcp_server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    protected = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_COORD_PROTECTED_KEYS" for target in node.targets)
    )

    assert "hook_events" in ast.literal_eval(protected)
