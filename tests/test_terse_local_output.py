from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.normalizer import postprocess_model_output
from local_ai_hub.ollama_subagents import OllamaSubagentCatalog
from local_ai_hub.services import LocalAIServices


def test_postprocess_strips_conversational_preambles() -> None:
    samples = [
        ("Sure! Here is the fix:\n```python\ndef foo():\n    return 1\n```", "```python\ndef foo():\n    return 1\n```"),
        ("Certainly, here are the findings:\n- bug in auth\n- missing check", "- bug in auth\n- missing check"),
        ("Of course! Here is the diff:\n```diff\n--- a/b.py\n+++ a/b.py\n```", "```diff\n--- a/b.py\n+++ a/b.py\n```"),
        ("Hello! Based on the provided context:\n- fact 1\n- fact 2", "- fact 1\n- fact 2"),
        ("Okay, here is the solution:\n1. Update config\n2. Restart", "1. Update config\n2. Restart"),
    ]
    for raw, expected in samples:
        cleaned, _ = postprocess_model_output(raw, role="code")
        assert cleaned == expected, f"Failed on raw: {raw!r}, got: {cleaned!r}"


def test_postprocess_strips_conversational_postambles() -> None:
    samples = [
        ("```python\ndef foo():\n    return 1\n```\n\nHope this helps!", "```python\ndef foo():\n    return 1\n```"),
        ("- issue 1\n- issue 2\n\nLet me know if you need any further assistance!", "- issue 1\n- issue 2"),
        ("SUMMARY: done.\n\nFeel free to ask if you have more questions.", "SUMMARY: done."),
        ("SUMMARY: done.\n\nHope that helps with your implementation!", "SUMMARY: done."),
    ]
    for raw, expected in samples:
        cleaned, _ = postprocess_model_output(raw, role="review")
        assert cleaned == expected, f"Failed on raw: {raw!r}, got: {cleaned!r}"


def test_postprocess_preserves_substantive_code_and_text() -> None:
    raw = "```python\n# Sure, this comment is inside code\ndef test():\n    assert True\n```"
    cleaned, _ = postprocess_model_output(raw, role="code")
    assert cleaned == raw

    # Text that is purely technical should not be stripped
    pure_technical = "SUMMARY: auth failure\nROOT_CAUSE: expired token in header\nFIX: bump ttl"
    cleaned_tech, _ = postprocess_model_output(pure_technical, role="qwen-explorer")
    assert cleaned_tech == pure_technical


def test_subagent_system_contract_contains_terse_directive() -> None:
    catalog = OllamaSubagentCatalog({
        "models": {"fast_code": "qwen2.5-coder:7b"},
        "ollama_subagents": {
            "enabled": True,
            "profiles": {
                "qwen-explorer": {"model": "qwen2.5-coder:7b", "role": "explorer"},
            },
        },
    })
    contract = catalog.system_contract(catalog.resolve("qwen-explorer"), "Find defect")
    assert "TERSE TECHNICAL OUTPUT" in contract
    assert "zero conversational filler" in contract.lower()


def test_services_delegation_prompts_contain_terse_directive(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {
            "fast_code": "qwen2.5-coder:7b",
            "heavy_code": "qwen3.5:9b",
            "reasoning": "qwen3.5:9b",
            "general": "qwen2.5-coder:7b",
        },
    }
    services = LocalAIServices(
        config=config,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )
    services._generate = MagicMock(return_value={"success": True, "text": "OK"})

    for task_type in ["code", "review", "reasoning", "general"]:
        services.delegate({"task": "test task", "task_type": task_type}, tenant="default")
        assert services._generate.called
        call_args = services._generate.call_args
        system_prompt = call_args[0][2]
        assert "Terse technical output only: zero conversational filler" in system_prompt
