import pytest

from local_ai_hub import trace_context
from local_ai_hub.token_accounting import token_efficiency_metadata


@pytest.mark.parametrize("alias,canonical", [
    ("parent_task_id", "parent_task"), ("activity_class", "activity"),
    ("repository_revision", "revision"), ("reuse", "reuse_state"),
    ("cache", "cache_state"),
])
def test_retired_metadata_field_cannot_supply_canonical_value(alias, canonical):
    result = token_efficiency_metadata({alias: "retired"})
    assert result[canonical] == ""
    assert alias not in result
    current = token_efficiency_metadata({alias: "retired", canonical: "current"})
    assert current[canonical] == "current"


def test_trace_metadata_has_one_setter_and_resetter():
    assert not hasattr(trace_context, "set_efficiency_metadata")
    assert not hasattr(trace_context, "reset_efficiency_metadata")
