"""Server checked inventory for a bounded, read-only repository review scope.

Reuse the existing confined security inventory, with an explicit fixed policy
and limits. The scope excludes the inventory's ignored directories, extensions,
archives and links. This is not a claim about every byte in a checkout.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from .verified_execution import EXECUTION_KEY, MAX_OBLIGATIONS, MAX_REPOSITORY_RESOURCES


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
    tools = RepositoryTools({"search": {"max_files": MAX_REPOSITORY_RESOURCES}})
    paths, status = tools.security_inventory(str(base), deadline=time.monotonic() + 5.0)
    if status.get("complete") is not True:
        raise ValueError("repository inventory incomplete or exceeds the task limit")
    if status.get("excluded_link_paths", 0):
        raise ValueError("repository inventory contains excluded links; use explicit declared scope")
    result = sorted(path.relative_to(base).as_posix() for path in paths)
    if not result or len(result) != len(set(result)):
        raise ValueError("repository inventory empty or ambiguous")
    return result


def select_partition(resources: list[str], raw: Any) -> tuple[list[str], dict[str, Any]]:
    """Stable complete manifest and deterministic nonoverlapping slices."""
    if type(raw) is not dict or not {"index", "size"}.issubset(raw) or set(raw) - {
        "index", "size", "total", "resource_count", "manifest_sha256",
    }:
        raise ValueError("partition requires index and size")
    index, size = raw["index"], raw["size"]
    if type(index) is not int or type(size) is not int or not 1 <= size <= MAX_OBLIGATIONS:
        raise ValueError("invalid partition index or size")
    total = (len(resources) + size - 1) // size
    if not 0 <= index < total:
        raise ValueError("partition index outside inventory")
    digest = hashlib.sha256(
        json.dumps(resources, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    result = {
        "index": index, "size": size, "total": total,
        "resource_count": len(resources), "manifest_sha256": digest,
    }
    if any(key in raw and raw[key] != value for key, value in result.items()):
        raise ValueError("repository partition manifest changed")
    return resources[index * size:(index + 1) * size], result


def compile_repository_contract(contract: Mapping[str, Any], root: str) -> dict[str, Any]:
    """Compile an explicit repository scope before GoalContract normalization."""
    profile = contract.get("slo_profile")
    config = profile.get(EXECUTION_KEY) if isinstance(profile, Mapping) else None
    if not repository_scope(config):
        return dict(contract)
    if not isinstance(profile, Mapping) or not isinstance(config, Mapping):
        raise ValueError("invalid repository execution profile")
    resources = repository_resources(root)
    inventory = dict(config["inventory"])
    if "partition" in inventory:
        resources, partition = select_partition(resources, inventory["partition"])
        inventory["partition"] = partition
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
        resources = repository_resources(root)
        partition = config["inventory"].get("partition")
        if partition is not None:
            try:
                resources, _ = select_partition(resources, partition)
            except ValueError:
                return {"complete": False, "status": "partition_manifest_changed"}
        actual = set(resources)
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
