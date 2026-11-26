"""Server checked inventory for a bounded, read-only repository review scope.

Reuse the existing confined security inventory, with an explicit fixed policy
and limits. The scope excludes the inventory's ignored directories, extensions,
archives and links. This is not a claim about every byte in a checkout.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import time
from typing import Any

from .verified_execution import EXECUTION_KEY, MAX_OBLIGATIONS


def repository_scope(config: Any) -> bool:
    if not isinstance(config, Mapping):
        return False
    inventory = config.get("inventory")
    return isinstance(inventory, Mapping) and inventory.get("scope") == "repository"


def repository_resources(root: str) -> list[str]:
    from .repo_tools import RepositoryTools

    if not root or not Path(root).is_absolute() or not Path(root).is_dir():
        raise ValueError("repository inventory requires an existing absolute repository root")
    base = Path(root).resolve(strict=True)
    tools = RepositoryTools({"search": {"max_files": MAX_OBLIGATIONS}})
    paths, status = tools.security_inventory(str(base), deadline=time.monotonic() + 5.0)
    if status.get("complete") is not True:
        raise ValueError("repository inventory incomplete or exceeds the task limit")
    if status.get("excluded_link_paths", 0):
        raise ValueError("repository inventory contains excluded links; use explicit declared scope")
    result = sorted(path.relative_to(base).as_posix() for path in paths)
    if not result or len(result) != len(set(result)):
        raise ValueError("repository inventory empty or ambiguous")
    return result


def compile_repository_contract(contract: Mapping[str, Any], root: str) -> dict[str, Any]:
    """Compile an explicit repository scope before GoalContract normalization."""
    profile = contract.get("slo_profile")
    config = profile.get(EXECUTION_KEY) if isinstance(profile, Mapping) else None
    if not repository_scope(config):
        return dict(contract)
    resources = repository_resources(root)
    inventory = config["inventory"]
    if "resources" in inventory:
        supplied = inventory["resources"]
        if (type(supplied) is not list or any(type(item) is not str for item in supplied)
                or sorted(supplied) != resources):
            raise ValueError("declared resources differ from the server repository inventory")
    return {
        **contract,
        "slo_profile": {
            **profile,
            EXECUTION_KEY: {**config, "inventory": {**inventory, "resources": resources}},
        },
    }


def check_repository_scope(config: Any, root: str) -> dict[str, Any]:
    """Recheck the same bounded inventory; never accept client coverage assertions."""
    if not repository_scope(config):
        return {}
    expected = set(config["inventory"]["resources"])
    try:
        actual = set(repository_resources(root))
    except (OSError, RuntimeError, ValueError):
        return {"complete": False, "status": "inventory_unavailable"}
    added, removed = sorted(actual - expected), sorted(expected - actual)
    return {
        "complete": not added and not removed,
        "status": "matched" if not added and not removed else "scope_changed",
        "expected_count": len(expected), "current_count": len(actual),
        "added_count": len(added), "removed_count": len(removed),
        "added_preview": added[:12], "removed_preview": removed[:12],
    }
