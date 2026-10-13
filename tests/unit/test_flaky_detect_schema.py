from local_ai_hub.operation_contracts import OPERATION_CONTRACTS

def test_command_schema_includes_runs():
    contract = OPERATION_CONTRACTS["local_ai_command"]
    assert "runs" in contract["properties"]
    assert contract["properties"]["runs"]["type"] == "integer"
    assert "root" in contract["properties"]
    assert "env" in contract["properties"]
