from __future__ import annotations

from local_ai_hub.services import cache_decision_reason, enclosing_symbol_at_line, generation_cache_key, normalize_generation_cache_prompt


def test_generation_cache_prompt_normalizes_only_line_endings():
    unix = "TASK:\n  keep indentation\nvalue\n"
    windows = "TASK:\r\n  keep indentation\r\nvalue\r\n"

    assert normalize_generation_cache_prompt(windows) == unix
    assert normalize_generation_cache_prompt(unix) == unix


def test_cache_decision_reason_never_relaxes_semantic_scope():
    assert cache_decision_reason("ollama", semantic_query="same question") == "semantic_not_reused"
    assert cache_decision_reason("ollama", semantic_query="") == "new_exact_key"
    assert cache_decision_reason("semantic", semantic_query="same question") == "semantic_reuse"


def test_exact_generation_cache_key_normalizes_system_line_endings():
    common = {
        "model": "fast",
        "prompt": "Question: same work\r\n",
        "options": {"num_predict": 64, "temperature": 0},
        "think": False,
        "execution": {"tier": "fast"},
    }

    windows = generation_cache_key(system="Use evidence.\r\nBe concise.\r\n", **common)
    unix = generation_cache_key(system="Use evidence.\nBe concise.\n", **common)

    assert windows == unix


def test_enriched_search_uses_existing_tree_sitter_symbols(monkeypatch):
    monkeypatch.setattr(
        "local_ai_hub.services.parse_treesitter",
        lambda _source, _language: ([
            {"name": "outer", "kind": "function", "line": 1, "end_line": 12, "name_path": "outer"},
            {"name": "inner", "kind": "function", "line": 4, "end_line": 7, "name_path": "outer/inner"},
        ], [], []),
    )

    assert enclosing_symbol_at_line("def outer():\n", "module.py", 5) == {
        "name": "inner", "kind": "function", "line": 4, "end_line": 7, "name_path": "outer/inner",
    }
