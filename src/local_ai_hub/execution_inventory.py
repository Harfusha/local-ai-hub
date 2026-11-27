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
import subprocess
import re
from typing import Any

from .verified_execution import EXECUTION_KEY, MAX_OBLIGATIONS, MAX_REPOSITORY_RESOURCES, normalize_exclusions


def repository_scope(config: Any) -> bool:
    if not isinstance(config, Mapping):
        return False
    inventory = config.get("inventory")
    return isinstance(inventory, Mapping) and inventory.get("scope") in {"repository", "changes"}


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


def change_resources(root: str, base_revision: str = "") -> list[str]:
    """Enumerate tracked, staged, deleted and untracked Git paths, not file contents.

    Optional pinned base includes committed changes as well as the worktree.
    No Git ref expression or caller-supplied command is accepted.
    """
    from .process_utils import hidden_run_kwargs
    from .repo_state import RepoStateTracker

    if not root or not Path(root).is_absolute() or not Path(root).is_dir():
        raise ValueError("change inventory requires an existing absolute repository root")
    base = Path(root).resolve(strict=True)

    def git(*args: str) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(base), *args], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5.0,
            check=False, **hidden_run_kwargs(),
        )
        if result.returncode or len(result.stdout) > 8_000_000:
            raise ValueError("Git change inventory unavailable or exceeds byte limit")
        return result.stdout

    actual_root = Path(git("rev-parse", "--show-toplevel").decode("utf-8").rstrip("\r\n")).resolve()
    if actual_root != base:
        raise ValueError("change inventory requires the Git checkout root")
    if not isinstance(base_revision, str):
        raise ValueError("base_revision must be a string")
    if base_revision:
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", base_revision):
            raise ValueError("base_revision must be a full lowercase Git commit ID")
        if git("rev-parse", "--verify", base_revision + "^{commit}").decode("ascii").strip() != base_revision:
            raise ValueError("base_revision is not a commit")
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    resources = set(RepoStateTracker._parse_porcelain_v1(status))
    if base_revision:
        resources.update(path.decode("utf-8", errors="strict") for path in
                         git("diff", "--no-renames", "--name-only", "-z", base_revision, "HEAD", "--").split(b"\0") if path)
    if not resources or len(resources) > MAX_REPOSITORY_RESOURCES:
        raise ValueError("Git change inventory empty or exceeds resource limit")
    for path in resources:
        if (not path or path != path.strip() or len(path) > 360 or "\\" in path
                or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in path)
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise ValueError("Git change inventory contains an unsupported path")
    return sorted(resources)


def _full_resources(inventory: dict[str, Any], root: str) -> list[str]:
    if inventory.get("scope") != "changes":
        if "include_mapped_tests" in inventory or "policy_sha256" in inventory:
            raise ValueError("mapped tests require Git changes scope")
        return repository_resources(root)
    resources = change_resources(root, inventory.get("base_revision", ""))
    mapped = inventory.get("include_mapped_tests", False)
    if type(mapped) is not bool or ("policy_sha256" in inventory and not mapped):
        raise ValueError("invalid mapped test inventory policy")
    if not mapped:
        return resources

    from .project_config import path_is_allowed, path_matches_pattern, resolve_project_config

    policy = resolve_project_config(root)
    if policy.error_codes:
        raise ValueError("project impact policy is unavailable")
    if "policy_sha256" in inventory and inventory["policy_sha256"] != policy.config_digest:
        raise ValueError("project impact policy changed")
    inventory["policy_sha256"] = policy.config_digest
    # Resolve transitive, project-declared impact edges to a fixed point.
    # Process each source rule only once; cycles terminate and every newly
    # impacted path can activate another rule.
    rules = policy.settings.affected_tests_mapping
    pending = set(rules)
    impacted = set(resources)
    allowed: list[str] | None = None
    deadline = time.monotonic() + 5.0
    while pending:
        if time.monotonic() >= deadline:
            raise ValueError("project impact expansion exceeded deadline")
        active = sorted(source for source in pending
                        if any(path_matches_pattern(path, source) for path in impacted))
        if not active:
            break
        if allowed is None:
            allowed = [
                path for path in repository_resources(root)
                if path_is_allowed(root, path, policy.settings, phase="test")
            ]
        pending.difference_update(active)
        for source in active:
            for pattern in rules[source]:
                if time.monotonic() >= deadline:
                    raise ValueError("project impact expansion exceeded deadline")
                matched = {path for path in allowed if path_matches_pattern(path, pattern)}
                if not matched:
                    raise ValueError("configured affected test pattern has no allowed inventory match")
                impacted.update(matched)
                if len(impacted) > MAX_REPOSITORY_RESOURCES:
                    raise ValueError("Git impact inventory exceeds resource limit")
    if time.monotonic() >= deadline:
        raise ValueError("project impact expansion exceeded deadline")
    return sorted(impacted)


def _resources(inventory: dict[str, Any], root: str) -> list[str]:
    resources = _full_resources(inventory, root)
    exclusions = normalize_exclusions(inventory.get("exclusions", []))
    paths = {item["path"] for item in exclusions}
    if paths - set(resources):
        raise ValueError("inventory exclusion does not match the current server scope")
    included = [path for path in resources if path not in paths]
    if not included:
        raise ValueError("inventory exclusions remove every resource")
    if exclusions:
        inventory["exclusions"] = exclusions
    return included


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
    inventory = dict(config["inventory"])
    resources = _resources(inventory, root)
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
        resources = _resources(dict(config["inventory"]), root)
        partition = config["inventory"].get("partition")
        if partition is not None:
            try:
                resources, _ = select_partition(resources, partition)
            except ValueError:
                return {"complete": False, "status": "partition_manifest_changed"}
        actual = set(resources)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return {"complete": False, "status": "inventory_unavailable"}
    added, removed = sorted(actual - expected), sorted(expected - actual)
    return {
        "complete": not added and not removed,
        "status": "matched" if not added and not removed else "scope_changed",
        "expected_count": len(expected), "current_count": len(actual),
        "added_count": len(added), "removed_count": len(removed),
        "added_preview": added[:12], "removed_preview": removed[:12],
    }
