"""Deferred F38 source producer contract; no database or filesystem access."""

from types import SimpleNamespace

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.operation_contracts import validate_operation_output


@pytest.mark.parametrize("status,expected", [
    ("verification_incomplete", None),
    ("not_checked", None),
    ("stale_candidates", True),
    ("stat_current_candidates", False),
    ("verified_current_candidates", False),
])
def test_freshness_unknown_omits_optional_boolean_instead_of_returning_null(status, expected):
    index = SimpleNamespace(
        _candidate_freshness=lambda *args, **kwargs: {"status": status, "unknown_paths": ["src/example.py"], "stale_paths": []},
    )
    result = {"success": True, "root": "C:/fixture/repo", "stale": None,
              "symbols": [{"path": "src/example.py"}], "coverage": {"query_term_coverage": 1.0}}
    CodeIndex._apply_query_freshness(index, result, verify_content=False)
    if expected is None:
        assert "stale" not in result
    else:
        assert result["stale"] is expected
    assert result["freshness"]["status"] == status
    assert validate_operation_output("local_ai_repo", "code_index", result) is None
