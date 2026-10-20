"""Opt-in deterministic pytest partitions with explicit completion manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pytest

_state = {}


def parse_shard(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)/[1-9][0-9]*", value):
        raise ValueError("shard must be zero-based index/count")
    index, count = map(int, value.split("/"))
    if not 1 <= count <= 32 or not 0 <= index < count:
        raise ValueError("invalid bounded shard")
    return index, count


def node_shard(nodeid, count):
    return int.from_bytes(hashlib.sha256(nodeid.encode("utf-8")).digest()[:8], "big") % count


def pytest_addoption(parser):
    group = parser.getgroup("audit validation shards")
    group.addoption("--audit-shard", default="")
    group.addoption("--audit-shard-manifest", default="")
    group.addoption("--audit-source-revision", default="")


def _write_manifest():
    if not _state:
        return
    target = Path(_state["manifest"])
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(_state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    option = config.getoption("--audit-shard")
    if not option:
        return
    try:
        index, count = parse_shard(option)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    manifest = config.getoption("--audit-shard-manifest")
    revision = config.getoption("--audit-source-revision")
    if not manifest or not revision:
        raise pytest.UsageError("sharding requires explicit manifest and source revision")
    all_nodeids = sorted(item.nodeid for item in items)
    if len(set(all_nodeids)) != len(all_nodeids):
        raise pytest.UsageError("duplicate collection identities cannot establish disjoint shards")
    selected = [item for item in items if node_shard(item.nodeid, count) == index]
    deselected = [item for item in items if node_shard(item.nodeid, count) != index]
    _state.clear()
    _state.update({
        "schema_version": 1, "manifest": manifest,
        "root": str(config.rootpath), "repository_revision": revision,
        "shard_index": index, "shard_count": count, "collected_count": len(items),
        "collection_sha256": hashlib.sha256("\n".join(all_nodeids).encode()).hexdigest(),
        "selected_nodeids": [item.nodeid for item in selected],
        "reports": [], "session_finished": False,
    })
    _write_manifest()
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)


def pytest_runtest_logreport(report):
    if _state:
        _state["reports"].append({"nodeid": report.nodeid, "phase": report.when,
                                  "outcome": report.outcome, "duration_seconds": report.duration})
        if report.failed or len(_state["reports"]) % 30 == 0:
            _write_manifest()


def pytest_sessionfinish(session, exitstatus):
    if _state:
        _state["session_finished"] = True
        _state["exit_status"] = int(exitstatus)
        _write_manifest()
