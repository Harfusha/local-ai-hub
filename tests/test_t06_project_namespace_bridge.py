from __future__ import annotations

import json
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp

project_config = pytest.importorskip("local_ai_hub.project_config")
work_fencing = pytest.importorskip("local_ai_hub.work_fencing")
FencingLeaseStore = work_fencing.FencingLeaseStore


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _linked_worktrees(tmp_path: Path) -> tuple[Path, Path]:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    primary.mkdir()
    _git("-C", str(primary), "init", "--quiet")
    _git("-C", str(primary), "config", "user.name", "T06 namespace fixture")
    _git("-C", str(primary), "config", "user.email", "t06@example.invalid")
    (primary / "owned.txt").write_text("before\n", encoding="utf-8")
    _git("-C", str(primary), "add", "owned.txt")
    _git("-C", str(primary), "commit", "--quiet", "-m", "fixture")
    _git("-C", str(primary), "worktree", "add", "--quiet", "-b", "linked", str(linked))
    return primary, linked


def test_http_lease_blocks_command_broker_across_linked_worktrees(tmp_path: Path, monkeypatch) -> None:
    if not callable(getattr(http_server, "_lease_coordination_id", None)):
        pytest.skip("requires T16 server-side project namespace route")

    primary, linked = _linked_worktrees(tmp_path)
    state_dir = tmp_path / "state"
    config_path = tmp_path / "hub.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    held_lease_id = ""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/leases/claim_batch",
            data=json.dumps({"owner": "t06-http-task", "root": str(primary), "paths": ["owned.txt"]}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Connection": "close",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            held = json.loads(response.read().decode("utf-8"))
        assert held.get("success") is True, held
        held_lease_id = str(held["lease_id"])

        coordination_id = project_config.resolve_project_context(
            linked, state_dir
        ).coordination_id
        assert coordination_id
        fencing = FencingLeaseStore(state_dir / "work_fencing.sqlite3")
        attempt = fencing.claim_attempt(
            str(linked), "t06-namespace-task", "t06-test", ttl_seconds=60,
            coordination_id=coordination_id,
        )
        broker = app.commands
        broker.set_fencing_lease_store(fencing)
        monkeypatch.setattr(broker, "_transaction_docker_ready", lambda: (True, ""))

        result = broker._run_private_transaction(
            "python -c \"from pathlib import Path; Path('owned.txt').write_text('after')\"",
            linked,
            task_id="t06-namespace-task",
            paths=["owned.txt"],
            timeout=5,
            docker_image="fixture-image",
            work_attempt_fence=attempt,
        )

        assert result["success"] is False, result
        assert result["failure_kind"] == "destination_conflict", result
        assert (linked / "owned.txt").read_text(encoding="utf-8") == "before\n"
    finally:
        if held_lease_id:
            app.leases.release(owner="t06-http-task", lease_id=held_lease_id)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        http_server.APP = previous_app
        app.close()
