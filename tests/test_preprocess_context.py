"""Tests for cross-file architectural neighborhood context formatting."""

from src.local_ai_hub.preprocess_context import (
    NeighborSummary,
    format_neighborhood_prompt_section,
)


def test_format_neighborhood_prompt_section():
    neighbors = [
        NeighborSummary(
            rel_path="storage/db.py",
            relation="imports",
            purpose="Connection pool and transaction manager",
            key_symbols=("Pool", "connect"),
        ),
        NeighborSummary(
            rel_path="api/server.py",
            relation="imported_by",
            purpose="Upstream HTTP gateway",
            key_symbols=(),
        ),
    ]

    section = format_neighborhood_prompt_section(neighbors)
    assert "ARCHITECTURAL NEIGHBORHOOD CONTEXT:" in section
    assert "Imports 'storage/db.py': Connection pool and transaction manager" in section
    assert "(exports: Pool, connect)" in section
    assert "Imported by upstream caller 'api/server.py'" in section


def test_format_empty_neighborhood():
    assert format_neighborhood_prompt_section([]) == ""
