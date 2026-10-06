"""T09 fixture interface, reconciled with the production project-config owner.

The historical stash supplied a stand-in while that owner was unavailable.
Keep the interface, but never replace production validation or ProjectSettings.
"""
from __future__ import annotations

from local_ai_hub import project_config

ProjectConfigError = project_config.ProjectConfigError


def resolve_project_context(project_root, state_dir):
    return project_config.resolve_project_context(project_root, state_dir)


def install_t09_project_config_test_fixture(monkeypatch):
    """Use the real owner implementation; no sys.modules or guard substitution."""
    return project_config
