from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.commands import CommandBroker
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.services import LocalAIServices
from local_ai_hub.work_orchestrator import WorkOrchestrator


class _Artifacts:
    def __init__(self) -> None:
        self.records = {}

    def put(self, text: str, tenant: str, kind: str) -> str:
        artifact_id = f"artifact-{kind}-{len(self.records) + 1}"
        self.records[artifact_id] = {
            "success": True,
            "artifact_id": artifact_id,
            "kind": kind,
            "text": text,
            "next_offset": None,
        }
        return artifact_id

    def get(self, artifact_id: str, *, max_chars: int, tenant: str):
        return self.records.get(artifact_id)


class _Leases:
    def claim_batch(self, tenant, root, paths, ttl_seconds=900, purpose="", *, coordination_id=None):
        return {"success": True, "lease_id": "advisory-lease", "paths": paths}

    def release(self, tenant, lease_id=""):
        return {"success": True}


class _RegisteredTaskStore:
    def __init__(self, root: Path, work_id: str) -> None:
        self.root = root.resolve()
        self.work_id = work_id

    def get(self, task_id: str):
        if task_id != self.work_id:
            return None
        branch = subprocess.run(
            ["git", "-C", str(self.root), "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return SimpleNamespace(checkpoint=SimpleNamespace(state_data={
            "worktree": {
                "success": True,
                "worktree_path": str(self.root),
                "repo_root": str(self.root),
                "branch": branch,
            }
        }))


class _BrokerRoutedServices:
    def __init__(self, patch: str, broker_service: LocalAIServices) -> None:
        self.patch = patch
        self.broker_service = broker_service
        self.delegate_calls = 0
        self.run_results: list[dict] = []
        self.attempts = []

    @property
    def verification_store(self):
        return None

    def repo_profile(self, root):
        return {"success": True, "validation_commands": ["git diff --check"]}

    def repo_map(self, root, max_symbols=80):
        return {"success": True, "files": ["owned.txt"]}

    def test_matrix(self, root):
        return {"success": True, "commands": ["git diff --check"]}

    def deterministic_query(self, root, query, limit=24):
        return {"success": True, "facts": []}

    def code_query(self, root, query, limit=20):
        return {"success": True, "symbols": []}

    def fast_context(self, root, query, max_tokens):
        return {"success": True, "evidence": []}

    def repo_diff(self, root, base="HEAD", staged=False, max_tokens=5000):
        result = subprocess.run(
            ["git", "-C", str(root), "diff"],
            capture_output=True,
            text=True,
            check=False,
        )
        return {"success": result.returncode == 0, "diff": result.stdout}

    def delegate_repo(self, args, tenant):
        self.delegate_calls += 1
        if self.delegate_calls == 1:
            plan = {
                "summary": "edit owned file and verify",
                "needs_agent": False,
                "steps": [
                    {"id": "edit", "kind": "edit", "task": "replace old with new", "depends_on": [], "acceptance": ["owned file updated"]},
                    {"id": "validate", "kind": "validate", "task": "run validation", "depends_on": ["edit"], "acceptance": ["validation succeeds"]},
                    {"id": "review", "kind": "review", "task": "review result", "depends_on": ["validate"], "acceptance": ["owned file updated"]},
                ],
                "validation_commands": ["git diff --check"],
            }
            return {"success": True, "text": json.dumps(plan)}
        return {"success": True, "text": self.patch}

    def second_opinion(self, args, tenant):
        return {"success": True, "text": json.dumps({
            "passed": True,
            "summary": "verified",
            "criteria": [
                {"criterion": "owned file updated", "passed": True},
                {"criterion": "validation succeeds", "passed": True},
            ],
            "risks": [],
        })}

    def command(self, args, tenant):
        if args.get("action") == "discover":
            return {"success": True, "validation_commands": ["git diff --check"]}
        attempt = args.get("writer_fence")
        self.attempts.append(attempt)
        result = self.broker_service.command(args, tenant)
        self.run_results.append(result)
        return result


def test_work_orchestrator_validation_reaches_real_broker_with_fence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "owned.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "owned.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T16", "-c", "user.email=t16@example.invalid", "commit", "-qm", "fixture"],
        check=True,
    )

    state_dir = tmp_path / "state"
    config = {
        "server": {"state_dir": str(state_dir)},
        "commands": {"enabled": True, "allow_unknown": True, "allow_mutating": True},
        "work_orchestrator": {
            "enabled": True,
            "max_pending_work_orders": 4,
            "max_steps": 4,
            "max_llm_steps": 4,
            "max_seconds": 30,
            "step_retry_limit": 0,
        },
    }
    broker = CommandBroker(config, _Artifacts(), RepoStateTracker(config))
    broker.set_task_store(_RegisteredTaskStore(root, "t16-broker-e2e"))
    broker._transaction_docker_ready = lambda: (True, "")
    spawned = []
    execute = broker._execute

    def track_transaction_spawn(command, *args, **kwargs):
        if isinstance(command, list) and command and command[0] == "docker":
            spawned.append(command)
            return {"success": True, "exit_code": 0, "stdout": "", "stderr": ""}
        return execute(command, *args, **kwargs)

    broker._execute = track_transaction_spawn
    app = WorkOrchestrator(
        config,
        state_dir,
        services=object(),
        commands=broker,
        leases=_Leases(),
        artifacts=_Artifacts(),
    )
    broker_service = object.__new__(LocalAIServices)
    broker_service.commands = broker
    broker_service.agent_state = None
    patch = (
        "--- a/owned.txt\n+++ b/owned.txt\n@@ -1 +1 @@\n"
        "-old\n+new\n"
    )
    services = _BrokerRoutedServices(patch, broker_service)
    app.services = services
    app._ensure_workers = lambda: None

    try:
        submitted = app.submit("tenant", {
            "root": str(root.resolve()),
            "task": "edit and validate owned file",
            "work_id": "t16-broker-e2e",
            "acceptance_criteria": ["owned file updated", "validation succeeds"],
            "budget": {"max_seconds": 30, "max_llm_calls": 4},
        })
        row = app._next()
        assert row is not None and row["work_id"] == submitted["work_id"]
        app._execute(row)

        result = app.get("tenant", submitted["work_id"], profile="debug")
        assert result["status"] == "complete", result
        assert (root / "owned.txt").read_text(encoding="utf-8") == "new\n"
        assert services.run_results and services.run_results[0]["success"] is True
        assert services.run_results[0]["exit_code"] == 0
        assert services.attempts[0] is not None
        stale_attempt = services.attempts[0]
        spawned.clear()

        stale_result = broker_service.command({
            "action": "run",
            "command": "git add owned.txt",
            "cwd": str(root),
            "task_id": "t16-broker-e2e",
            "criterion": "stale orchestrator attempt",
            "record_verification": False,
            "paths": ["owned.txt"],
            "writer_fence": stale_attempt,
        }, "tenant")

        assert stale_result["success"] is False, stale_result
        stale_reason = " ".join(
            str(stale_result.get(key, "")) for key in ("error", "failure_kind")
        ).lower()
        assert "attempt" in stale_reason, stale_result
        assert spawned == []
        assert subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--quiet", "--", "owned.txt"],
            check=False,
        ).returncode == 0
    finally:
        app.close()
