"""An absent search match is not an operational incident or a passing check."""

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub.repo_state import RepoStateTracker


def no_match(**overrides):
    return {"success": False, "exit_code": 1, "stdout": "", "stderr": "",
            "timed_out": False, "cancelled": False, **overrides}


@pytest.mark.parametrize("command", ["rg absent src", "ripgrep -q absent src",
                                      "git grep absent -- src", "git -C repo --no-pager grep absent"])
def test_empty_direct_search_is_expected_without_rewriting_result(command):
    broker = object.__new__(CommandBroker)
    result = no_match()
    assert broker._expected_search_no_match(command, {"class": "read"}, result)
    assert result == no_match()


@pytest.mark.parametrize("command", ["git status", "git diff --exit-code", "python -m pytest",
                                      "powershell -Command rg absent", "rg absent | other", "rg --pre helper absent"])
def test_other_failures_are_not_suppressed(command):
    assert not object.__new__(CommandBroker)._expected_search_no_match(command, {"class": "read"}, no_match())


@pytest.mark.parametrize("overrides", [{"exit_code": 2}, {"exit_code": True}, {"exit_code": -1073741819},
    {"stderr": "syntax error"}, {"stdout": "partial result"}, {"error": "process failed"},
    {"timed_out": True}, {"cancelled": True}, {"outcome_unknown": True}, {"cleanup_unconfirmed": True},
    {"output_capture_unconfirmed": True}, {"output_truncated": True}, {"discarded_output_chars": 1},
    {"log_chunks_dropped": 1}, {"log_callback_delivery_unconfirmed": True},
    {"log_callback_dropped_chars": 1}, {"incident_required": True}])
def test_error_or_incomplete_search_evidence_is_not_suppressed(overrides):
    assert not object.__new__(CommandBroker)._expected_search_no_match("rg absent src", {"class": "read"}, no_match(**overrides))


def test_execution_argv_and_read_class_are_required():
    broker = object.__new__(CommandBroker)
    assert broker._expected_search_no_match("project-search", {"class": "read"}, no_match(), ["rg", "absent", "src"])
    assert not broker._expected_search_no_match("rg absent", {"class": "validation"}, no_match())
    assert not broker._expected_search_no_match("rg absent", {"class": "read"}, no_match(), ["python", "-m", "pytest"])
    assert not broker._expected_search_no_match("rg absent", {"class": "read"}, no_match(), "rg absent")


class Artifacts:
    def put(self, *args, **kwargs):
        return "test-artifact"


class Incidents:
    def __init__(self):
        self.captured = []
        self.knowledge_queries = []

    def capture(self, outcome):
        self.captured.append(outcome)

    def find_regressions(self, *args, **kwargs):
        return []

    def find_negative_knowledge(self, **kwargs):
        self.knowledge_queries.append(kwargs)
        return []


@pytest.mark.parametrize("command,execution,expected_incident", [
    ("git grep absent -- src", no_match(), False),
    ("rg absent src", no_match(), False),
    ("git status --porcelain", no_match(), True),
    ("rg invalid src", no_match(exit_code=2, stderr="invalid pattern"), True),
])
def test_broker_keeps_negative_exit_evidence_without_false_incidents(tmp_path, monkeypatch, command, execution, expected_incident):
    config = {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}}
    broker = CommandBroker(config, Artifacts(), RepoStateTracker(config))
    incidents = Incidents()
    broker.incident_store = incidents
    monkeypatch.setattr(broker.repo_state, "fingerprint", lambda cwd: {"fingerprint": "candidate", "changed_paths": []})
    monkeypatch.setattr(broker, "_tool_identity", lambda *args, **kwargs: "test-tool")
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *args, **kwargs: None)
    monkeypatch.setattr(broker, "_execute", lambda *args, **kwargs: dict(execution))
    monkeypatch.setattr(broker, "_needs_model_error_distillation", lambda result: False)
    result = broker.run(command, str(tmp_path), record_verification=False)
    assert result["success"] is False
    assert result["exit_code"] == execution["exit_code"]
    assert bool(incidents.captured) is expected_incident
    assert bool(incidents.knowledge_queries) is expected_incident
    if not expected_incident:
        assert "error_distillation" not in result
        assert not result.get("incident_recorded")
