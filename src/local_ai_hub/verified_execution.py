"""Verified work graph projected from Agent OS contracts and receipt gates."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
import math
from collections.abc import Mapping, Sequence
from typing import Any

EXECUTION_KEY = "verified_execution"
MAX_OBLIGATIONS = 512
MAX_REPOSITORY_RESOURCES = 8000
MAX_PREVIEW = 12
EVIDENCE_TYPES = frozenset({"source_review", "test", "benchmark"})


def _canonical(value: Any, label: str, limit: int = 512) -> str:
    if (type(value) is not str or not value or value != value.strip()
            or "\x00" in value or len(value) > limit):
        raise ValueError(f"{label} must be a bounded nonempty canonical string")
    return value


def normalize_exclusions(raw: Any) -> list[dict[str, str]]:
    """Exact, auditable exclusions; never accept globs or implicit path prefixes."""
    if type(raw) is not list or len(raw) > 128:
        raise ValueError("inventory exclusions must be a bounded array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if type(item) is not dict or set(item) != {"path", "reason"}:
            raise ValueError("inventory exclusion requires path and reason")
        path = _canonical(item["path"], "excluded path", 360)
        reason = _canonical(item["reason"], "exclusion reason", 240)
        if (any(c in path for c in "\\*?[]:")
                or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in path)
                or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise ValueError("inventory exclusion requires an exact relative path")
        if path in seen:
            raise ValueError("duplicate inventory exclusion")
        seen.add(path)
        result.append({"path": path, "reason": reason})
    return sorted(result, key=lambda item: item["path"])


def expand_declared_inventory(
    criteria: Sequence[str], raw: Any,
) -> tuple[tuple[str, ...], Any]:
    """Compile a declared resource × check matrix into mandatory criteria.

    This is a generic input compiler, not proof that a repository inventory
    is exhaustive. Resource identity is opaque and does not authorize reads.
    """
    if type(raw) is not dict or "inventory" not in raw:
        return tuple(criteria), raw
    inventory = raw["inventory"]
    if (type(inventory) is not dict or not {"resources", "checks"}.issubset(inventory)
            or set(inventory) - {"resources", "checks", "scope", "partition", "base_revision", "include_mapped_tests", "policy_sha256", "exclusions"}):
        raise ValueError("inventory must contain resources and checks")
    scope = inventory.get("scope", "declared")
    if scope not in ("declared", "repository", "changes"):
        raise ValueError("invalid inventory scope")
    base_revision = inventory.get("base_revision", "")
    if "base_revision" in inventory and (scope != "changes" or type(base_revision) is not str
            or len(base_revision) not in (40, 64) or any(c not in "0123456789abcdef" for c in base_revision)):
        raise ValueError("base_revision requires a full Git commit ID in changes scope")
    mapped = inventory.get("include_mapped_tests", False)
    policy_digest = inventory.get("policy_sha256", "")
    if type(mapped) is not bool or ("include_mapped_tests" in inventory and scope != "changes"):
        raise ValueError("invalid mapped test scope")
    if mapped and (type(policy_digest) is not str or len(policy_digest) != 64
                   or any(c not in "0123456789abcdef" for c in policy_digest)):
        raise ValueError("mapped tests require a server-compiled project policy digest")
    if not mapped and "policy_sha256" in inventory:
        raise ValueError("unexpected mapped test policy digest")
    exclusions = normalize_exclusions(inventory.get("exclusions", []))
    if "exclusions" in inventory and scope == "declared":
        raise ValueError("exclusions require server-checked inventory scope")
    resources = inventory["resources"]
    checks = inventory["checks"]
    if type(resources) is not list or not 1 <= len(resources) <= MAX_OBLIGATIONS:
        raise ValueError("inventory resources must be a nonempty bounded array")
    if type(checks) is not list or not 1 <= len(checks) <= 64:
        raise ValueError("inventory checks must be a nonempty bounded array")
    if len(resources) * len(checks) > MAX_OBLIGATIONS:
        raise ValueError("inventory matrix exceeds obligation limit; split the work into scoped tasks")
    for resource in resources:
        _canonical(resource, "resource", 360)
    if len(set(resources)) != len(resources):
        raise ValueError("duplicate inventory resource")
    if set(resources) & {item["path"] for item in exclusions}:
        raise ValueError("excluded paths cannot remain in the resource matrix")
    partition = inventory.get("partition")
    if "partition" in inventory:
        if scope not in ("repository", "changes") or type(partition) is not dict or set(partition) != {
            "index", "size", "total", "resource_count", "manifest_sha256",
        }:
            raise ValueError("repository partition requires a server compiled manifest")
        index, size = partition["index"], partition["size"]
        total, count = partition["total"], partition["resource_count"]
        digest = partition["manifest_sha256"]
        if (any(type(number) is not int for number in (index, size, total, count))
                or not 1 <= size <= MAX_OBLIGATIONS
                or not 1 <= count <= MAX_REPOSITORY_RESOURCES
                or total != (count + size - 1) // size
                or not 0 <= index < total
                or len(resources) != min(size, count - index * size)
                or type(digest) is not str or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("invalid repository partition manifest")
        if size * len(checks) > MAX_OBLIGATIONS:
            raise ValueError("partition size times check count exceeds obligation limit")
    check_names: set[str] = set()
    normalized_checks: list[dict[str, Any]] = []
    for check in checks:
        if type(check) is not dict or set(check) - {"name", "dimension", "priority", "depends_on", "evidence_type"}:
            raise ValueError("invalid inventory check")
        name = _canonical(check.get("name"), "check name", 100)
        if ":" in name or name in check_names:
            raise ValueError("inventory check names must be unique and cannot contain ':'")
        check_names.add(name)
        dimension = _canonical(check.get("dimension", "general"), "dimension", 64)
        priority = check.get("priority", 0)
        if type(priority) is not int or not 0 <= priority <= 100:
            raise ValueError("inventory check priority must be an integer from 0 to 100")
        dependencies = check.get("depends_on", [])
        if type(dependencies) is not list or len(dependencies) > 64:
            raise ValueError("check dependencies must be a bounded array")
        for dependency in dependencies:
            _canonical(dependency, "check dependency", 100)
        if len(set(dependencies)) != len(dependencies) or name in dependencies:
            raise ValueError("invalid check dependencies")
        evidence = check.get("evidence_type")
        if "evidence_type" in check and (type(evidence) is not str or evidence not in EVIDENCE_TYPES):
            raise ValueError("unsupported check evidence_type")
        normalized_checks.append({
            "name": name, "dimension": dimension, "priority": priority,
            **({"evidence_type": evidence} if evidence is not None else {}),
            **({"depends_on": list(dependencies)} if dependencies else {}),
        })
    if any(set(check.get("depends_on", [])) - check_names for check in normalized_checks):
        raise ValueError("check dependencies must refer to exact check names")
    supplied = raw.get("units", {})
    if type(supplied) is not dict:
        raise ValueError("execution units must be an object")
    units = dict(supplied)
    expanded = list(criteria)
    existing = set(expanded)
    for resource in resources:
        for check in normalized_checks:
            criterion = f"{check['name']}: {resource}"
            expected = {"dimension": check["dimension"], "priority": check["priority"]}
            if "evidence_type" in check:
                expected["evidence_type"] = check["evidence_type"]
            metadata = units.get(criterion, {})
            if type(metadata) is not dict or any(
                key in metadata and metadata[key] != value for key, value in expected.items()
            ):
                raise ValueError("inventory criterion metadata conflicts with check")
            check_dependencies = [f"{dependency}: {resource}" for dependency in check.get("depends_on", [])]
            dependencies = metadata.get("depends_on", [])
            if type(dependencies) is not list or any(type(dep) is not str for dep in dependencies):
                raise ValueError("invalid inventory criterion dependencies")
            # Explicit graph metadata may add prerequisites but cannot drop mandatory check prerequisites.
            units[criterion] = {**metadata, **expected, "depends_on": list(dict.fromkeys((*dependencies, *check_dependencies)))}
            if criterion not in existing:
                expanded.append(criterion)
                existing.add(criterion)
    if len(expanded) > MAX_OBLIGATIONS:
        raise ValueError("expanded execution exceeds obligation limit")
    return tuple(expanded), {
        **raw, "units": units,
        "inventory": {
            "resources": list(resources), "checks": normalized_checks,
            **({"scope": scope} if scope != "declared" else {}),
            **({"base_revision": base_revision} if base_revision else {}),
            **({"include_mapped_tests": True, "policy_sha256": policy_digest} if mapped else {}),
            **({"partition": dict(partition)} if partition is not None else {}),
            **({"exclusions": exclusions} if exclusions else {}),
        },
    }


def normalize_execution(criteria: Sequence[str], raw: Any) -> dict[str, Any]:
    """Validate contract metadata. Missing metadata means a mandatory independent unit."""
    if type(raw) is not dict or set(raw) - {"version", "profile", "units", "required_dimensions", "inventory", "host_continuation"}:
        raise ValueError("invalid verified_execution contract")
    expanded, raw = expand_declared_inventory(criteria, raw)
    if tuple(criteria) != expanded:
        raise ValueError("inventory criteria must be present in the goal contract")
    if type(raw.get("version", 1)) is not int or raw.get("version", 1) != 1:
        raise ValueError("unsupported verified_execution version")
    if not 1 <= len(criteria) <= MAX_OBLIGATIONS or len(set(criteria)) != len(criteria):
        raise ValueError("verified_execution requires unique, nonempty bounded acceptance criteria")
    for criterion in criteria:
        _canonical(criterion, "criterion")
    profile = _canonical(raw.get("profile", "custom"), "profile", 64)
    host_continuation = raw.get("host_continuation", False)
    if type(host_continuation) is not bool:
        raise ValueError("host_continuation must be a boolean")
    supplied = raw.get("units", {})
    if type(supplied) is not dict or set(supplied) - set(criteria):
        raise ValueError("execution units must refer to exact acceptance criteria")
    units: dict[str, dict[str, Any]] = {}
    for criterion, metadata in supplied.items():
        if type(metadata) is not dict or set(metadata) - {"dimension", "depends_on", "priority", "evidence_type"}:
            raise ValueError("invalid execution unit metadata")
        dimension = _canonical(metadata.get("dimension", "general"), "dimension", 64)
        dependencies = metadata.get("depends_on", [])
        if type(dependencies) is not list or len(dependencies) > 64:
            raise ValueError("depends_on must be a bounded array")
        for dependency in dependencies:
            _canonical(dependency, "dependency")
        if (len(set(dependencies)) != len(dependencies) or criterion in dependencies
                or set(dependencies) - set(criteria)):
            raise ValueError("invalid execution dependency")
        priority = metadata.get("priority", 0)
        if type(priority) is not int or not 0 <= priority <= 100:
            raise ValueError("execution priority must be an integer from 0 to 100")
        evidence = metadata.get("evidence_type")
        if "evidence_type" in metadata and (type(evidence) is not str or evidence not in EVIDENCE_TYPES):
            raise ValueError("unsupported execution unit evidence_type")
        units[criterion] = {"dimension": dimension, "depends_on": list(dependencies), "priority": priority,
                            **({"evidence_type": evidence} if evidence is not None else {})}
    dimensions = raw.get("required_dimensions", [])
    if type(dimensions) is not list or len(dimensions) > 64:
        raise ValueError("required_dimensions must be a bounded array")
    for dimension in dimensions:
        _canonical(dimension, "required dimension", 64)
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("duplicate required dimension")
    actual = {units.get(c, {}).get("dimension", "general") for c in criteria}
    if set(dimensions) - actual:
        raise ValueError("required execution dimension has no acceptance criterion")
    _order(criteria, units)
    normalized = {"version": 1, "profile": profile, "units": units, "required_dimensions": list(dimensions)}
    if "inventory" in raw:
        normalized["inventory"] = raw["inventory"]
    if host_continuation:
        normalized["host_continuation"] = True
    return normalized


def _order(criteria: Sequence[str], units: Mapping[str, Any]) -> list[str]:
    """Stable topological order; reject cycles without recursive traversal."""
    children: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    for criterion in criteria:
        dependencies = units.get(criterion, {}).get("depends_on", [])
        indegree[criterion] = len(dependencies)
        for dependency in dependencies:
            children[dependency].append(criterion)
    ready = deque(c for c in criteria if not indegree[c])
    ordered: list[str] = []
    while ready:
        criterion = ready.popleft()
        ordered.append(criterion)
        for child in children[criterion]:
            indegree[child] -= 1
            if not indegree[child]:
                ready.append(child)
    if len(ordered) != len(criteria):
        raise ValueError("verified_execution dependency graph contains a cycle")
    return ordered


def execution_projection(
    criteria: Sequence[str],
    config: dict[str, Any],
    *,
    satisfied: Sequence[str],
    unsatisfied: Sequence[str],
    stale: Sequence[str],
    receipt_ids: Mapping[str, str],
    receipt_gate_complete: bool,
    blockers: Sequence[str] = (),
    receipt_observed_at: Mapping[str, float] | None = None,
    include_verified_criteria: bool = False,
    confirmation_dependencies: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Compute coverage from the canonical evaluator, never from claimed progress."""
    normalized = normalize_execution(criteria, config)
    units = normalized["units"]
    declared = set(criteria)
    for criterion, dependencies in (confirmation_dependencies or {}).items():
        if criterion not in declared or set(dependencies) - declared or criterion in dependencies:
            raise ValueError("invalid persisted problem confirmation dependencies")
        metadata = units.get(criterion, {})
        units[criterion] = {**metadata, "depends_on": list(dict.fromkeys((*metadata.get("depends_on", []), *dependencies)))}
    inventory = normalized.get("inventory")
    resource_checks = {
        f"{check['name']}: {resource}": (resource, check["name"])
        for resource in inventory["resources"] for check in inventory["checks"]
    } if inventory is not None else {}
    extra = list(dict.fromkeys(c for c in (*unsatisfied, *stale, *satisfied) if c not in declared))
    ordered = _order(criteria, units) + extra
    verified_receipts = set(satisfied) - set(unsatisfied) - set(stale)
    stale_set = set(stale)
    verified: set[str] = set()
    states: Counter[str] = Counter()
    dimensions: dict[str, Counter[str]] = defaultdict(Counter)
    rows: list[dict[str, Any]] = []
    dependency_stale: list[str] = []
    ready: list[dict[str, Any]] = []
    fanout: Counter[str] = Counter(dep for metadata in units.values() for dep in metadata["depends_on"])
    for criterion in ordered:
        metadata = units.get(criterion, {})
        dimension = metadata.get("dimension", "general" if criterion in declared else "project_verification")
        dependencies = metadata.get("depends_on", [])
        waiting = [dep for dep in dependencies if dep not in verified]
        superseded: list[str] = []
        if receipt_observed_at is not None and criterion in verified_receipts and not waiting:
            observed = receipt_observed_at.get(criterion, 0.0)
            for dep in dependencies:
                prerequisite = receipt_observed_at.get(dep, 0.0)
                if (not math.isfinite(observed) or not math.isfinite(prerequisite)
                        or observed <= 0 or prerequisite <= 0 or observed < prerequisite):
                    superseded.append(dep)
        if waiting:
            status = "dependency_blocked"
        elif superseded:
            status = "stale"
            dependency_stale.append(criterion)
        elif criterion in verified_receipts:
            status = "verified"
            verified.add(criterion)
        elif criterion in stale_set:
            status = "stale"
        else:
            status = "unverified"
        states[status] += 1
        dimensions[dimension]["total"] += 1
        dimensions[dimension][status] += 1
        row: dict[str, Any] = {
            "criterion": criterion, "dimension": dimension, "status": status,
            "priority": metadata.get("priority", 0), "dependent_count": fanout[criterion],
            **({"evidence_type": metadata["evidence_type"]} if "evidence_type" in metadata else {}),
        }
        if criterion in resource_checks:
            row["resource"], row["check"] = resource_checks[criterion]
        if waiting:
            row["waiting_on"] = waiting[:MAX_PREVIEW]
            row["waiting_on_count"] = len(waiting)
        if superseded:
            row["superseded_by"] = superseded[:MAX_PREVIEW]
            row["superseded_by_count"] = len(superseded)
        if status == "verified" and criterion in receipt_ids:
            row["verified_receipt_id"] = receipt_ids[criterion]
        if status != "verified":
            rows.append(row)
        if status in {"unverified", "stale"}:
            ready.append(row)
    ready.sort(key=lambda row: (-row["priority"], -row["dependent_count"], row["criterion"]))
    total = len(ordered)
    inventory_summary = ({
        "authority": "declared", "resources": len(inventory["resources"]),
        **({"excluded_count": len(inventory["exclusions"]),
            "exclusions_preview": inventory["exclusions"][:MAX_PREVIEW]} if inventory.get("exclusions") else {}),
        "checks": len(inventory["checks"]),
        "obligations": len(inventory["resources"]) * len(inventory["checks"]),
        **({"partition": dict(inventory["partition"])} if "partition" in inventory else {}),
    } if inventory is not None else None)
    return {
        "version": 1, "profile": normalized["profile"],
        **({"verified_criteria": [criterion for criterion in ordered if criterion in verified]}
           if include_verified_criteria else {}),
        **({"inventory": inventory_summary} if inventory_summary is not None else {}),
        "coverage": {
            "total": total, "verified": len(verified),
            "unverified": states["unverified"], "stale": states["stale"],
            "dependency_blocked": states["dependency_blocked"],
        },
        "dimensions": {
            name: {"total": counts["total"], "verified": counts["verified"]}
            for name, counts in sorted(dimensions.items())
        },
        "receipt_gate_complete": receipt_gate_complete,
        **({"dependency_stale_criteria": dependency_stale} if dependency_stale else {}),
        "ready_for_completion_attempt": receipt_gate_complete and len(verified) == total and not blockers,
        "checkpoint_blocker_count": len(blockers),
        "next_obligation": ready[0] if ready else None,
        "remaining_preview": rows[:MAX_PREVIEW],
        "remaining_count": len(rows),
        "preview_truncated": len(rows) > MAX_PREVIEW,
    }


def contract_evidence_types(contract: Any) -> dict[str, str]:
    """Read explicit evidence kinds from the persisted structured contract."""
    profile = getattr(contract, "slo_profile", {})
    config = profile.get(EXECUTION_KEY) if isinstance(profile, Mapping) else None
    if not isinstance(config, Mapping):
        return {}
    return {
        criterion: metadata["evidence_type"]
        for criterion, metadata in config.get("units", {}).items()
        if isinstance(metadata, Mapping) and metadata.get("evidence_type") in EVIDENCE_TYPES
    }


def consecutive_failed_verifications(
    receipts: Sequence[Any], *, criterion: str, now: float,
    repository_revision: str, mutation_generation: int, valid_owners: set[str],
    window_seconds: int = 900,
) -> int:
    """Advisory count from bounded newest-first persisted receipt history."""
    seen: set[str] = set()
    for receipt in receipts[:128]:
        if (receipt.criterion != criterion
                or receipt.repository_revision != repository_revision
                or receipt.mutation_generation != mutation_generation
                or (valid_owners and receipt.owner not in valid_owners)):
            continue
        if not now - window_seconds <= receipt.observed_at <= now:
            continue
        if receipt.passed:
            break
        seen.add(receipt.receipt_id)
    return len(seen)


def evidence_progress(
    *, created_at: float, now: float, active: bool, complete: bool,
    observed_receipt_times: Sequence[float], threshold_seconds: int = 900,
    repeated_failure_count: int = 0,
) -> dict[str, Any]:
    """Advisory evidence age, not an estimate of effort or proof of stagnation."""
    last_observation = max([created_at, *(t for t in observed_receipt_times if 0 < t <= now)])
    elapsed = max(0, int(now - last_observation))
    status = "recent_or_not_active"
    if active and not complete:
        if repeated_failure_count >= 3:
            status = "repeated_failed_verification"
        elif elapsed >= threshold_seconds:
            status = "no_recent_verified_evidence"
    return {
        "status": status,
        **({"consecutive_failed_verifications": repeated_failure_count} if repeated_failure_count else {}),
        "seconds_since_verified_observation_or_creation": elapsed,
        "threshold_seconds": threshold_seconds,
        "advisory": True,
    }


def validate_criteria_revision(contract: Any, criteria: Sequence[str]) -> None:
    """Check the exact resulting structured contract before a plan is mutated."""
    from dataclasses import replace

    profile = getattr(contract, "slo_profile", {})
    if not isinstance(profile, Mapping) or EXECUTION_KEY not in profile:
        return
    candidate = replace(contract, acceptance_criteria=tuple(criteria))
    if (tuple(criteria) != candidate.acceptance_criteria
            or not set(contract.acceptance_criteria).issubset(candidate.acceptance_criteria)):
        raise ValueError("verified execution contract revisions must preserve existing obligations")


def execution_resume_summary(execution: Mapping[str, Any]) -> str:
    """Compact, explicit advisory handoff; no completion authorization."""
    if not execution:
        return "Verification status unavailable; call verify_completion before proceeding."
    counts = execution.get("coverage", {})
    problems = execution.get("problems", {})
    scope = execution.get("scope_check", {})
    inventory = execution.get("inventory", {})
    next_unit = execution.get("next_obligation")
    progress = execution.get("progress", {})
    parts = [
        "Verified execution (advisory snapshot; recheck with verify_completion):",
        f"coverage {counts.get('verified', 0)}/{counts.get('total', 0)}; "
        f"stale={counts.get('stale', 0)}; dependency-blocked={counts.get('dependency_blocked', 0)}; "
        f"open blocking problems={problems.get('blocking_open', 0)}",
        f"checkpoint blockers={execution.get('checkpoint_blocker_count', 0)}",
    ]
    if isinstance(inventory, Mapping) and inventory.get("excluded_count", 0):
        parts.append(f"Explicit scope exclusions: {inventory['excluded_count']}; inspect task contract for rationale. "
                     "Coverage does not include excluded resources.")
    if scope and scope.get("complete") is not True:
        parts.append("Repository scope changed or unavailable; reconcile the scope before completion.")
    elif isinstance(next_unit, Mapping):
        parts.append(f"Next obligation: {next_unit.get('criterion', '')}")
        if next_unit.get("resource") and next_unit.get("check"):
            parts.append(f"Declared resource: {next_unit['resource']}; check: {next_unit['check']}")
        if next_unit.get("evidence_type"):
            parts.append(f"Required evidence: {next_unit['evidence_type']}")
    elif execution.get("ready_for_completion_attempt") is True:
        parts.append("Evidence preview ready; run the authoritative completion gate.")
    else:
        parts.append("Completion not ready; inspect remaining obligations and blockers.")
    if progress.get("status") == "repeated_failed_verification":
        parts.append("Repeated failed verification of the next obligation; diagnose the failure before retrying.")
    if progress.get("status") == "no_recent_verified_evidence":
        parts.append("No recent verified evidence; check for blocked or repetitive work.")
    return "\n".join(parts)
