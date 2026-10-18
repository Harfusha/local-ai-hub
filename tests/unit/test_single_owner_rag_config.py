import pytest
from local_ai_hub.config import ConfigError, validate_config


@pytest.mark.parametrize("value", [None, False, "", "shared", "tenant"])
def test_retired_rag_scope_rejects_by_presence(value):
    with pytest.raises(ConfigError, match=r"rag.scope was removed"):
        validate_config({"rag": {"scope": value}})
