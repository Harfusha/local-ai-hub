from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.commands import CommandBroker
from local_ai_hub import project_config


def test_transaction_never_drops_coordination_for_old_provider_signatures(tmp_path, monkeypatch):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    # Obsolete provider signatures cannot select a physical-root-only namespace.
    broker._transaction_leases = SimpleNamespace(claim=lambda: None)
    fences = SimpleNamespace(acquire=lambda: None)
    monkeypatch.setattr(
        project_config, "resolve_project_context",
        lambda root, state: SimpleNamespace(coordination_id="project:shared-clones"),
    )

    binding = broker._transaction_namespace_kwargs(Path(tmp_path), fences)

    assert binding == {"coordination_id": "project:shared-clones"}
    with pytest.raises(TypeError):
        broker._transaction_leases.claim(**binding)


def test_transaction_missing_project_identity_rejects(tmp_path, monkeypatch):
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    monkeypatch.setattr(
        project_config, "resolve_project_context",
        lambda root, state: SimpleNamespace(coordination_id=""),
    )

    with pytest.raises(RuntimeError, match="coordination namespace is required"):
        broker._transaction_namespace_kwargs(Path(tmp_path), SimpleNamespace())
