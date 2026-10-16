import pytest

from local_ai_hub.operation_contracts import operation_contract, validate_operation_arguments
from local_ai_hub.search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW


@pytest.mark.parametrize("action", ["search", "code_index"])
def test_repo_pagination_contract_exposes_positive_defaults(action):
    contract = operation_contract("local_ai_repo")

    assert contract["properties"]["limit"]["default"] == 24
    assert contract["properties"]["offset"]["default"] == 0
    assert contract["properties"]["limit"]["maximum"] == MAX_PAGE_SIZE
    assert contract["properties"]["offset"]["maximum"] == MAX_PAGE_WINDOW - 1
    assert "limit" in contract["actions"][action]["allowed"]
    assert "offset" in contract["actions"][action]["allowed"]
    assert validate_operation_arguments(
        "local_ai_repo", action, {"limit": 20, "offset": 20}
    ) is None


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(-1, 0), (MAX_PAGE_SIZE + 1, 0), (24, -1), (True, 0), (24, False),
     ("24", 0), (MAX_PAGE_SIZE, MAX_PAGE_WINDOW - MAX_PAGE_SIZE + 1)],
)
def test_repo_pagination_contract_rejects_invalid_values(limit, offset):
    error = validate_operation_arguments(
        "local_ai_repo", "search", {"limit": limit, "offset": offset}
    )

    assert error is not None


def test_pagination_arguments_are_scoped_to_search_actions():
    error = validate_operation_arguments(
        "local_ai_repo", "context", {"limit": 24, "offset": 0}
    )

    assert error is not None
