from local_ai_hub.deterministic import DeterministicEngine


def test_package_audit_missing_manifest_has_client_error_contract(tmp_path):
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.package_audit(str(tmp_path), "missing.lock")

    assert result["success"] is False
    assert result["error_code"] == "package_manifest_unavailable"
    assert result["status_code"] == 422
    assert result["terminal"] is True
    assert result["retryable"] is False
