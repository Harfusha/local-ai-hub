from local_ai_hub.services import _context_path_priority, _source_focused_query


def test_source_queries_rank_current_code_before_historical_docs() -> None:
    assert _source_focused_query("Audit source code implementation")
    source = _context_path_priority(
        "src/local_ai_hub/services.py", source_focused=True, override_match=False
    )
    test = _context_path_priority(
        "tests/unit/test_services.py", source_focused=True, override_match=False
    )
    plan = _context_path_priority(
        "docs/plans/old-implementation.md", source_focused=True, override_match=False
    )
    assert source < test < plan


def test_path_overrides_remain_highest_and_doc_queries_keep_default_priority() -> None:
    assert _context_path_priority(
        "docs/plans/guide.md", source_focused=True, override_match=True
    ) == 0
    assert _context_path_priority(
        "src/module.py", source_focused=False, override_match=False
    ) == 1
    assert _context_path_priority(
        "docs/guide.md", source_focused=False, override_match=False
    ) == 1
