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
