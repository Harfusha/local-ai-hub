"""Separate-process durability regressions for policy budget accounting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


_CONCURRENT_CHILD = r"""
import json, pathlib, sys, time
from types import SimpleNamespace
from local_ai_hub.agent_policy import BudgetCost, PolicyEngine

db, ready_dir, gate, child_id = map(pathlib.Path, sys.argv[1:5])
store = SimpleNamespace(enabled=True, db_path=str(db))
engine = PolicyEngine(store)
engine.get_budget("cross-process")
(ready_dir / (child_id.name + ".ready")).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15
while not gate.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("parent did not release child barrier")
    time.sleep(0.01)
for _ in range(20):
    engine.consume("cross-process", BudgetCost(tokens=2, compute_seconds=0.5, external_calls=1))
result = engine.get_budget("cross-process")
print(json.dumps({"success": True, "task_id": result.task_id,
                  "used_tokens": result.used_tokens,
                  "used_compute_seconds": result.used_compute_seconds,
                  "used_external_calls": result.used_external_calls}))
"""


_FAILURE_CHILD = r"""
import json, pathlib, sqlite3, sys
from types import SimpleNamespace
import local_ai_hub.agent_policy as policy

db, task_id, failure_stage = sys.argv[1:4]
engine = policy.PolicyEngine(SimpleNamespace(enabled=True, db_path=db))
before = engine.get_budget(task_id)
before_tuple = (before.max_tokens, before.used_tokens, before.max_compute_seconds,
                before.used_compute_seconds, before.max_external_calls, before.used_external_calls)
original_connect = policy.connect_sqlite
def injected_connect(path, *args, **kwargs):
    connection = original_connect(path, *args, **kwargs)
    def authorize(action, first, second, database, source):
        if failure_stage == "read" and action == sqlite3.SQLITE_READ and first == "agent_budgets":
            return sqlite3.SQLITE_DENY
        if failure_stage == "write" and action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE) and first == "agent_budgets":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorize)
    return connection
policy.connect_sqlite = injected_connect
try:
    engine.consume(task_id, policy.BudgetCost(tokens=1, compute_seconds=1.0, external_calls=1))
    outcome = "unexpected-success"
except policy.BudgetUnavailableError:
    outcome = "budget-unavailable"
after = engine._budgets.get(task_id)
after_tuple = None if after is None else (after.max_tokens, after.used_tokens,
    after.max_compute_seconds, after.used_compute_seconds,
    after.max_external_calls, after.used_external_calls)
print(json.dumps({"outcome": outcome, "cache_unchanged": after_tuple == before_tuple,
                  "before": before_tuple, "after": after_tuple}))
"""


def _managed_child(code: str, args: list[str], *, job_name: str, env: dict[str, str]):
    from local_ai_hub.process_utils import hidden_run_kwargs, popen_managed

    return popen_managed(
        [sys.executable, "-c", code, *args],
        job_name=job_name,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **hidden_run_kwargs(text=True),
    )


def _stop_child(child) -> None:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)


def _close_child(child) -> None:
    _stop_child(child)
    for stream in (child.stdout, child.stderr):
        if stream is not None:
            stream.close()


def _wait_ready(ready_files: list[Path], children: list, deadline: float) -> None:
    while time.monotonic() < deadline:
        if all(path.is_file() for path in ready_files):
            return
        failed = [(index, child.returncode) for index, child in enumerate(children) if child.poll() not in (None, 0)]
        if failed:
            raise AssertionError(f"child exited before synchronization barrier: {failed}")
        time.sleep(0.01)
    raise TimeoutError("separate-process children did not reach barrier")


def _communicate_bounded(child, deadline: float) -> tuple[str, str]:
    remaining = max(0.1, deadline - time.monotonic())
    try:
        stdout, stderr = child.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        _stop_child(child)
        stdout, stderr = child.communicate(timeout=2)
        raise TimeoutError(f"child exceeded bounded deadline; stderr={stderr[-800:]!r}")
    return stdout, stderr


def _child_environment() -> dict[str, str]:
    env = os.environ.copy()
    source_root = str(ROOT / "src")
    env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def test_budget_updates_are_durable_across_two_python_processes(tmp_path):
    from local_ai_hub.agent_policy import PolicyEngine

    db = tmp_path / "process-budget.sqlite3"
    store = SimpleNamespace(enabled=True, db_path=str(db))
    PolicyEngine(store).set_budget(
        "cross-process",
        max_tokens=10_000,
        max_compute_seconds=10_000,
        max_external_calls=10_000,
    )
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    gate = tmp_path / "release-children"
    env = _child_environment()
    children = []
    deadline = time.monotonic() + 30
    try:
        for index in range(2):
            children.append(
                _managed_child(
                    _CONCURRENT_CHILD,
                    [str(db), str(ready_dir), str(gate), str(index)],
                    job_name=f"budget-process-{index}",
                    env=env,
                )
            )
        _wait_ready([ready_dir / "0.ready", ready_dir / "1.ready"], children, min(deadline, time.monotonic() + 15))
        gate.write_text("release", encoding="utf-8")
        child_outputs = []
        for child in children:
            stdout, stderr = _communicate_bounded(child, deadline)
            assert child.returncode == 0, stderr[-1200:]
            child_outputs.append(json.loads(stdout.strip().splitlines()[-1]))
        assert all(output["success"] is True for output in child_outputs)
        assert all(output["task_id"] == "cross-process" for output in child_outputs)

        durable = PolicyEngine(store).get_budget("cross-process")
        assert (
            durable.used_tokens,
            durable.used_compute_seconds,
            durable.used_external_calls,
        ) == (80, 20.0, 40)
        assert (
            durable.max_tokens,
            durable.max_compute_seconds,
            durable.max_external_calls,
        ) == (10_000, 10_000.0, 10_000)
    finally:
        gate.touch(exist_ok=True)
        for child in children:
            _close_child(child)


@pytest.mark.parametrize("failure_stage", ["read", "write"])
def test_exhausted_budget_failure_in_another_process_preserves_durable_row(tmp_path, failure_stage):
    from local_ai_hub.agent_policy import BudgetCost, PolicyEngine

    task_id = "exhausted-process-budget"
    db = tmp_path / f"{failure_stage}-failure.sqlite3"
    store = SimpleNamespace(enabled=True, db_path=str(db))
    setup = PolicyEngine(store)
    setup.set_budget(task_id, max_tokens=8, max_compute_seconds=4.0, max_external_calls=2)
    setup.consume(task_id, BudgetCost(
        tokens=8, compute_seconds=4.0, external_calls=2
    ))
    before = PolicyEngine(store).get_budget(task_id)
    assert (before.used_tokens, before.used_compute_seconds, before.used_external_calls) == (8, 4.0, 2)

    child = _managed_child(
        _FAILURE_CHILD,
        [str(db), task_id, failure_stage],
        job_name=f"budget-{failure_stage}-failure",
        env=_child_environment(),
    )
    deadline = time.monotonic() + 15
    try:
        stdout, stderr = _communicate_bounded(child, deadline)
        assert child.returncode == 0, stderr[-1200:]
        observed = json.loads(stdout.strip().splitlines()[-1])
        assert observed["outcome"] == "budget-unavailable"
        assert observed["cache_unchanged"] is True
        assert observed["before"] == observed["after"]
    finally:
        _close_child(child)

    after = PolicyEngine(store).get_budget(task_id)
    assert (
        after.max_tokens,
        after.used_tokens,
        after.max_compute_seconds,
        after.used_compute_seconds,
        after.max_external_calls,
        after.used_external_calls,
    ) == (
        before.max_tokens,
        before.used_tokens,
        before.max_compute_seconds,
        before.used_compute_seconds,
        before.max_external_calls,
        before.used_external_calls,
    )
