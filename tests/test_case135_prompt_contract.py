from pathlib import Path


def test_case135_runtime_prompt_keeps_one_call_and_forbids_ui_tools():
    text = (Path(__file__).resolve().parents[1] / "docs/agent-evaluation/prompts.md").read_text(encoding="utf-8")
    case = text.split("### 135 —", 1)[1].split("### 136 —", 1)[0]

    assert "právě jeden cílený runtime call" in case
    assert "Nepoužívej shell, browser, CUA ani jiné MCP endpointy" in case
    assert "mcp__cua_repl.js(completion_summary)" in case
    assert "response_profile=compact" in case
    assert "Při odmítnutí callu nebo chybě neopakuj." in case
    assert "Po callu odešli právě jednu finální odpověď." in case
