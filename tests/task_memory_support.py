"""Canonical repository identities for isolated memory integration fixtures."""

from pathlib import Path

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.project_config import resolve_project_context


def repository_memory_id(root: Path, state_store: AgentStateStore) -> str:
    return resolve_project_context(root, Path(state_store.db_path).parent).coordination_id
