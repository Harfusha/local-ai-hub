from __future__ import annotations

import sys
from pathlib import Path

from local_ai_hub.commands import CommandBroker
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore


class _Artifacts:
    def put(self, *_args, **_kwargs):
        return "artifact"


class _RepoState:
    def fingerprint(self, _cwd):
        return {"fingerprint": "stable-rev-1"}


def test_command_failure_attaches_auto_remediation(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    incidents = IncidentStore(state_store)

    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_read": True, "allow_validation": True},
        },
        _Artifacts(),
        _RepoState(),
    )
    broker.set_incident_store(incidents)

    # Run python validation command that fails with missing module
    cmd = f'{sys.executable} -m unittest non_existent_mod_99999'
    res = broker.run(cmd, str(tmp_path), "tenant-1")

    assert res["success"] is False
    assert "remediation" in res
    rem = res["remediation"]
    assert "missing Python module 'non_existent_mod_99999'" in rem["root_cause"]
    assert "install 'non_existent_mod_99999'" in rem["verified_fix"]
    assert rem["confidence"] >= 0.9
    assert rem["attempts"] == 1

    # Verify diagnostics also contains remediation guidance
    assert any("Remediation" in d["message"] for d in res.get("diagnostics", []))

    # Verify cached failure preserves remediation
    cached = broker.run(cmd, str(tmp_path), "tenant-1")
    assert cached.get("cache_hit") is True or cached.get("suppression_cache_hit") is True
    assert "remediation" in cached
    assert cached["remediation"]["incident_id"] == rem["incident_id"]
