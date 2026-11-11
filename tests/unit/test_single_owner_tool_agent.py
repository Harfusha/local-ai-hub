"""Source-level public contract checks for the tenant-free tool agent."""

import ast
from pathlib import Path


SOURCE = Path(__file__).parents[2] / "src" / "local_ai_hub" / "tool_agent.py"


def _functions():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_tool_agent_public_methods_have_no_tenant_parameter():
    functions = _functions()
    for name in ("run", "run_profile", "_execute_tool"):
        assert "tenant" not in {arg.arg for arg in functions[name].args.args}
        assert "tenant" not in {arg.arg for arg in functions[name].args.kwonlyargs}


def test_tool_agent_uses_canonical_rag_and_scheduler_keywords():
    source = SOURCE.read_text(encoding="utf-8")
    assert "self.rag.search(query, workspace=workspace, top_k=top_k, use_reranker=True)" in source
    assert 'self.services.scheduler.submit(\n                    model, source=f"tool-agent:{role}", execute=compute, priority=priority,' in source
    assert "model, tenant," not in source


def test_tool_agent_marks_capability_timeout_fallback_in_result():
    functions = _functions()
    capability = functions["_tool_capability"]
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "request"
        and any(keyword.arg == "timeout" and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == 1.0 for keyword in node.keywords)
        for node in ast.walk(capability)
    )
    assert any(
        isinstance(node, ast.ExceptHandler)
        and any(isinstance(child, ast.Return) and isinstance(child.value, ast.Constant)
                and child.value.value is None for child in ast.walk(node))
        for node in ast.walk(capability)
    )

    run = functions["run"]
    source = ast.unparse(run)
    assert "tool_fallback = bool(tools and tool_capability is not True)" in source
    assert "tools = []" in source[source.index("if tool_fallback") :]
    metadata = [
        node for node in ast.walk(run)
        if isinstance(node, ast.Dict)
        and {key.value for key in node.keys if isinstance(key, ast.Constant)}
        .issuperset({"tool_capability", "tool_fallback"})
    ]
    assert len(metadata) == 2
    for node in metadata:
        fields = {
            key.value: value.id
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(value, ast.Name)
        }
        assert fields["tool_capability"] == "tool_capability"
        assert fields["tool_fallback"] == "tool_fallback"
