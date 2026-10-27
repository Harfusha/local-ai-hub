import pytest

from local_ai_hub.features import FeatureSet


@pytest.mark.parametrize("value, expected", [(True, True), (False, False), (None, False), ("true", False), (1, False)])
def test_async_feature_requires_explicit_boolean(value, expected):
    assert FeatureSet({"async_jobs": {"enabled": value}}).async_jobs is expected


def test_async_feature_is_disabled_when_omitted():
    assert FeatureSet({}).async_jobs is False


@pytest.mark.parametrize("enabled", [False, True])
def test_mcp_status_respects_loaded_feature_config(monkeypatch, enabled):
    from local_ai_hub import mcp_server

    calls = []

    class Client:
        max_request_timeout = 30

        def post(self, path, payload, timeout, **kwargs):
            calls.append((path, payload))
            return {"success": True, "job_id": payload["job_id"], "state": "running"}

    monkeypatch.setattr(mcp_server, "FEATURES", FeatureSet({"async_jobs": {"enabled": enabled}}))
    monkeypatch.setattr(mcp_server, "CLIENT", Client())
    monkeypatch.setattr(mcp_server, "_compact", lambda value, _kind, **kwargs: value)
    result = mcp_server.local_ai_task(action="status", job_id="case-066-job")
    assert result["success"] is enabled
    assert bool(calls) is enabled
    if enabled:
        assert calls == [("/api/async-jobs", {"action": "status", "job_id": "case-066-job"})]
