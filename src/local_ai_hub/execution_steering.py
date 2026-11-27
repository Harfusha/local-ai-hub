"""Strict additive graph steering, with dependency-selective receipt retirement."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .execution_problems import problem_confirmation_dependencies
from .verified_execution import EXECUTION_KEY, _canonical, _order

GRAPH_REVISION_KEY = "execution_graph_revision"


def revise_graph(contract: Any, patch: Any, *, problems: Any) -> tuple[Any, set[str]]:
    """Return a normalized candidate and criteria whose old proofs must retire.

    Inventory membership, checks, evidence kinds and existing prerequisites are
    immutable. Additional obligations and prerequisites can only strengthen work.
    Priority changes do not change the meaning of an existing obligation.
    """
    if type(patch) is not dict or set(patch) - {"add_criteria", "units", "required_dimensions"}:
        raise ValueError("invalid execution graph amendment")
    old = contract.slo_profile.get(EXECUTION_KEY)
    if not isinstance(old, Mapping):
        raise ValueError("graph amendment requires verified execution")
    added = patch.get("add_criteria", [])
    if type(added) is not list:
        raise ValueError("add_criteria must be an array")
    for criterion in added:
        _canonical(criterion, "added criterion")
    existing = tuple(contract.acceptance_criteria)
    if len(set(added)) != len(added) or set(added) & set(existing):
        raise ValueError("added criteria must be unique and new")
    criteria = (*existing, *added)
    raw_units = patch.get("units", {})
    if type(raw_units) is not dict or set(raw_units) - set(criteria):
        raise ValueError("amendment units must refer to exact criteria")
    units = {name: dict(metadata) for name, metadata in old.get("units", {}).items()}
    for name, amendment in raw_units.items():
        if type(amendment) is not dict or set(amendment) - {"dimension", "evidence_type", "priority", "depends_on"}:
            raise ValueError("invalid graph amendment unit")
        previous = units.get(name, {})
        if name in existing:
            if set(amendment) & {"dimension", "evidence_type"}:
                raise ValueError("existing obligation dimension and evidence kind cannot change")
            if "depends_on" in amendment:
                deps = amendment["depends_on"]
                if type(deps) is not list or any(type(dep) is not str for dep in deps):
                    raise ValueError("invalid graph amendment prerequisites")
                if not set(previous.get("depends_on", [])).issubset(deps):
                    raise ValueError("existing graph prerequisites cannot be removed")
        units[name] = {**previous, **amendment}
    dimensions = patch.get("required_dimensions", old["required_dimensions"])
    if (type(dimensions) is not list or any(type(item) is not str for item in dimensions)
            or not set(old["required_dimensions"]).issubset(dimensions)):
        raise ValueError("required dimensions cannot be removed")
    candidate = replace(contract, acceptance_criteria=criteria, slo_profile={
        **contract.slo_profile,
        EXECUTION_KEY: {**old, "units": units, "required_dimensions": dimensions},
    })
    new = candidate.slo_profile[EXECUTION_KEY]
    if tuple(candidate.acceptance_criteria) != criteria or new.get("inventory") != old.get("inventory"):
        raise ValueError("graph amendment cannot modify inventory")
    if candidate == contract:
        raise ValueError("graph amendment has no effect")
    combined = {name: dict(new["units"].get(name, {})) for name in criteria}
    for name, predecessors in problem_confirmation_dependencies(problems).items():
        if name not in combined or set(predecessors) - set(criteria):
            raise ValueError("problem confirmation graph contains unknown criteria")
        combined[name]["depends_on"] = sorted(set(combined[name].get("depends_on", [])) | set(predecessors))
    order = _order(criteria, combined)
    retired = set(added)
    for name in order:
        previous_deps = set(old["units"].get(name, {}).get("depends_on", []))
        current_deps = set(new["units"].get(name, {}).get("depends_on", []))
        if previous_deps != current_deps or retired.intersection(combined[name].get("depends_on", [])):
            retired.add(name)
    return candidate, retired
