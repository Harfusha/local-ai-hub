"""Bound project-command verification for an OpenCode goal.

This adapter does not create receipts: the existing broker owns execution and
persists any authentic receipt. It is not an HTTP route by itself.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent_tasks import TaskState, TaskStatus, _canonical_repository_root, _task_matches_scope
from .commands import CommandInvocation
from .state_paths import configured_state_dir


def _denied(reason: str) -> dict[str, Any]:
    return {"success": False, "error_code": reason, "terminal": True, "retryable": False}


def run_goal_project_verification(
    tasks: Any, broker: Any, *, root: str, task_id: str, session_id: str, alias: str,
) -> dict[str, Any]:
    """Run only a configured command required by the exact active goal contract."""
    values = (task_id, session_id, alias)
    if any(type(value) is not str or not value or value != value.strip() or "\x00" in value or len(value) > 256 for value in values):
        return _denied("invalid_goal_verification_request")
    try:
        canonical_root = _canonical_repository_root(root)
        task = tasks.get(task_id)
        if (not isinstance(task, TaskState) or not _task_matches_scope(task, canonical_root, task_id)
                or task.owner != "opencode-local" or task.context.session_id != session_id
                or task.status not in {TaskStatus.PLANNED, TaskStatus.ACTIVE, TaskStatus.VERIFYING}):
            return _denied("goal_binding_mismatch")
        project = broker._cached_project_command_context(canonical_root, configured_state_dir(broker.config))
        if (_canonical_repository_root(project.root) != canonical_root or project.resolution.error_codes
                or not isinstance(project.settings.commands, Mapping)
                or not isinstance(project.settings.verification_rules, Mapping)):
            return _denied("goal_project_configuration_invalid")
        commands = project.settings.commands
        rules = project.settings.verification_rules
        allowed = set(task.contract.acceptance_criteria).intersection(commands)
        for criterion in task.contract.acceptance_criteria:
            if criterion not in rules:
                continue
            rule = rules[criterion]
            if rule is True:
                allowed.update(("lint", "test"))
            elif isinstance(rule, (tuple, list)) and rule and all(type(item) is str and item and item == item.strip() for item in rule):
                allowed.update(rule)
            else:
                return _denied("goal_verification_rule_invalid")
        if alias not in commands or alias not in allowed:
            return _denied("goal_command_not_required")
        resolved = broker._resolve_project_command(alias, canonical_root)
        if (resolved.alias != alias or not project.config_digest or resolved.config_digest != project.config_digest
                or resolved.caller_arguments):
            return _denied("goal_project_configuration_changed")
        command = resolved.command.argv if isinstance(resolved.command, CommandInvocation) else resolved.command
        classification = broker.classify(command)
        if (not isinstance(classification, dict) or classification.get("class") != "validation"
                or classification.get("allowed") is not True or classification.get("replay_safe") is not True):
            return _denied("goal_command_not_validation")
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return _denied("goal_verification_preflight_failed")

    try:
        result = broker.run(resolved.command, canonical_root, task_id=task_id, criterion=alias, bypass_cache=True,
                            _project_command_context=resolved, _environment_overrides=resolved.environment,
                            _cache_context=resolved.cache_context)
    except Exception:
        return {"success": False, "error_code": "goal_verification_outcome_unknown", "outcome_unknown": True, "retryable": False}
    if not isinstance(result, dict):
        return {"success": False, "error_code": "goal_verification_outcome_unknown", "outcome_unknown": True, "retryable": False}
    return result
