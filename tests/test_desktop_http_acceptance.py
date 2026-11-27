"""Real local HTTP + actual desktop IPC subprocess; no external models or production state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading

import pytest

from local_ai_hub import http_server
from local_ai_hub.app import LocalAIApp
from local_ai_hub.endpoint_stats import EndpointStatsStore

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_bridge_roundtrip_and_scoped_reset(tmp_path, monkeypatch):
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    app = None
    thread = None
    config = tmp_path / "isolated.toml"
    roots = [tmp_path / "a" / "shared", tmp_path / "b" / "shared"]
    for root in roots:
        root.mkdir(parents=True)
    config.write_text(
        "[local_ai_hub]\nconfig_schema_version = 1\n[server]\n"
        + "port = " + str(server.server_address[1]) + "\n"
        + "state_dir = " + json.dumps(str(tmp_path / "state"))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[agent_state]\nenabled = true\n",
        encoding="utf-8",
    )

    def call(op, **args):
        env = os.environ.copy()
        env["LOCAL_AI_CONFIG"] = str(config)
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/desktop.py"), "--bridge", "--config", str(config)],
            input=json.dumps({"op": op, "args": args}), capture_output=True,
            text=True, encoding="utf-8", timeout=40, env=env, cwd=ROOT, check=True,
        )
        return json.loads(result.stdout)

    try:
        app = LocalAIApp(str(config))
        app.endpoint_stats = EndpointStatsStore(tmp_path / "endpoint-state")
        monkeypatch.setattr(http_server, "APP", app)
        for root in roots:
            app.endpoint_stats.record_call(item_type="mcp", item_name="test:isolated", duration_ms=2, root=str(root))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        probe = call("probe")
        assert probe["ok"] and probe["result"]["online"] is True, probe
        first = call("read", view="Endpoint analytics", root=str(roots[0]))
        second = call("read", view="Endpoint analytics", root=str(roots[1]))
        assert first["ok"] and second["ok"], (first, second)
        assert first["result"]["root"] != second["result"]["root"]
        def recorded(response):
            return sum(item["calls"] for item in response["result"]["items"]
                       if item["name"] == "test:isolated" and item["type"] == "mcp")
        assert recorded(first) == 1
        assert recorded(second) == 1
        rejected = call("endpoint_reset", root=str(roots[0]))
        assert rejected["ok"] is False
        reset = call("endpoint_reset", root=str(roots[0]), confirmed=True)
        assert reset["ok"] and reset["result"]["reset"] is True, reset
        first = call("read", view="Endpoint analytics", root=str(roots[0]))
        second = call("read", view="Endpoint analytics", root=str(roots[1]))
        assert first["ok"] and second["ok"], (first, second)
        assert recorded(first) == 0
        assert recorded(second) == 1

        # Exercise actual plan storage, revision fences and scope using the
        # same bridge process and live HTTP transport, not mocked handlers.
        for index, root in enumerate(roots):
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=10,
                           capture_output=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Desktop Test",
                            "-c", "user.email=desktop@example.invalid", "-c", "commit.gpgsign=false",
                            "commit", "--allow-empty", "-m", "Fixture baseline"],
                           check=True, timeout=10, capture_output=True)
            created = call("plan_create", root=str(root), id="plan_desktop",
                           title=f"Plan {index}", description=f"scope-{index}", confirmed=True)
            assert created["ok"], created
        # Identical keys in unrelated repositories must not become a shared
        # memory selection, even when their directory basenames are the same.
        saved = []
        for index, root in enumerate(roots):
            record = call("memory_record", root=str(root), scope="repository",
                          key="desktop-scope-marker", value=json.dumps(f"memory-{index}"),
                          kind="fact", confirmed=True)
            assert record["ok"] and record["result"]["success"] is True, record
            saved.append(record["result"]["record"]["record_id"])
        assert saved[0] != saved[1]
        for index, root in enumerate(roots):
            found = call("memory_find", root=str(root), scope="repository", query="")
            assert found["ok"], found
            ids = {item["record_id"] for item in found["result"]["records"]}
            assert saved[index] in ids and saved[1-index] not in ids, found
        first_scope = {"root": str(roots[0]), "scope": "repository", "record_id": saved[0]}
        wrong_scope = {**first_scope, "root": str(roots[1])}
        detail = call("memory_get", **first_scope)
        assert detail["ok"] and detail["result"]["record"]["value"] == "memory-0", detail
        assert call("memory_get", **wrong_scope)["ok"] is False
        assert call("memory_quarantine", **first_scope, reason="fixture review")["ok"] is False
        assert call("memory_quarantine", **wrong_scope, reason="wrong root", confirmed=True)["ok"] is False
        quarantined = call("memory_quarantine", **first_scope, reason="fixture review", confirmed=True)
        assert quarantined["ok"] and quarantined["result"]["record"]["status"] == "quarantined", quarantined
        found = call("memory_find", root=str(roots[0]), scope="repository",
                     key="desktop-scope-marker", status="quarantined", limit=25)
        assert found["ok"] and [row["record_id"] for row in found["result"]["records"]] == [saved[0]], found
        other = call("memory_find", root=str(roots[1]), scope="repository",
                     key="desktop-scope-marker", status="quarantined", limit=25)
        assert other["ok"] and other["result"]["records"] == [], other
        wrong = call("memory_delete", root=str(roots[1]), scope="repository",
                     record_id=saved[0], confirmed=True)
        assert wrong["ok"] is False, wrong
        missing_confirmation = call("memory_delete", root=str(roots[0]),
                                    scope="repository", record_id=saved[0])
        assert missing_confirmation["ok"] is False
        deleted = call("memory_delete", root=str(roots[0]), scope="repository",
                       record_id=saved[0], confirmed=True)
        assert deleted["ok"] and deleted["result"]["deleted"] is True, deleted
        for index, root in enumerate(roots):
            found = call("memory_find", root=str(root), scope="repository", query="")
            assert found["ok"], found
            ids = {item["record_id"] for item in found["result"]["records"]}
            assert saved[0] not in ids and (saved[1] in ids) == (index == 1), found

        # Real task contract creation, scoped paging and completion gating.
        from local_ai_hub.agent_tasks import GoalContract, ScopeContext

        task_ids = []
        for index, root in enumerate(roots):
            created = call("task_create", root=str(root), goal=f"Desktop task fixture {index}",
                           criteria="verified test result", description="fixture contract",
                           constraints="no external calls", non_goals="unrelated repositories",
                           scope="repository", risk="critical", slo='{"latency_ms": 100}', confirmed=True)
            assert created["ok"], created
            task = created["result"]["task"]
            assert task["contract"]["description"] == "fixture contract"
            assert task["contract"]["non_goals"] == ["unrelated repositories"]
            assert task["contract"]["constraints"] == ["no external calls"]
            assert task["contract"]["risk_profile"] == "critical"
            task_ids.append(task["task_id"])
            if index == 0:
                # Seed additional real store records to force cursor continuation
                # without spawning another 25 Python adapter processes.
                context = ScopeContext.from_dict(task["context"])
                for number in range(25):
                    app.agent_tasks.create(
                        GoalContract(goal=f"Desktop task fixture page {number}"),
                        context, repo_root=str(root), actor="desktop-fixture",
                    )
        first_page = call("task_page", root=str(roots[0]), query="Desktop task fixture", status="planned", limit=25)
        assert first_page["ok"], first_page
        page = first_page["result"]
        assert page["has_more"] is True and len(page["tasks"]) == 25
        next_page = call("task_page", root=str(roots[0]), query="Desktop task fixture", status="planned",
                         limit=25, offset=page["next_offset"])
        assert next_page["ok"], next_page
        assert next_page["result"]["has_more"] is False and len(next_page["result"]["tasks"]) == 1
        first_ids = {row["task_id"] for row in page["tasks"]}
        next_ids = {row["task_id"] for row in next_page["result"]["tasks"]}
        assert not first_ids.intersection(next_ids)
        assert task_ids[0] in first_ids | next_ids and task_ids[1] not in first_ids | next_ids
        other_page = call("task_page", root=str(roots[1]), query="Desktop task fixture", status="planned", limit=25)
        assert other_page["ok"] and [row["task_id"] for row in other_page["result"]["tasks"]] == [task_ids[1]]
        wrong_task = call("task", root=str(roots[1]), id=task_ids[0], action="get", confirmed=True)
        assert wrong_task["ok"] is False
        active = call("task", root=str(roots[0]), id=task_ids[0], action="transition",
                      status="active", reason="fixture started", confirmed=True)
        assert active["ok"], active
        verifying = call("task", root=str(roots[0]), id=task_ids[0], action="transition",
                         status="verifying", reason="fixture verification", confirmed=True)
        assert verifying["ok"], verifying
        completed = call("task", root=str(roots[0]), id=task_ids[0], action="complete",
                         reason="must not complete without receipt", confirmed=True)
        assert completed["ok"] is False, completed
        current = call("task", root=str(roots[0]), id=task_ids[0], action="get", confirmed=True)
        assert current["ok"] and current["result"]["task"]["status"] == "verifying", current

        # Real incident recording, resolution filter and repository isolation.
        incident_ids = []
        for index, root in enumerate(roots):
            recorded = call("incident", root=str(root), kind="desktop-fixture",
                            message="Desktop fixture parser mismatch", cause="Incorrect parser configuration",
                            fix="Validated parser configuration with regression test" if index == 0 else "",
                            confirmed=True)
            assert recorded["ok"], recorded
            incident_ids.append(recorded["result"]["incident"]["incident_id"])
        assert incident_ids[0] != incident_ids[1]
        for index, root in enumerate(roots):
            inventory = call("incident_list", root=str(root), status="resolved" if index == 0 else "unresolved", limit=25)
            assert inventory["ok"], inventory
            ids = {row["incident_id"] for row in inventory["result"]["incidents"]}
            assert incident_ids[index] in ids and incident_ids[1-index] not in ids
            found = call("incident_find", root=str(root), query="parser mismatch", limit=25)
            assert found["ok"], found
            ids = {row["incident_id"] for row in found["result"]["incidents"]}
            assert incident_ids[index] in ids and incident_ids[1-index] not in ids

        original = call("plan_detail", root=str(roots[0]), id="plan_desktop")
        assert original["ok"], original
        revision = original["result"]["file_revision"]
        added = call("plan_task_create", root=str(roots[0]), id="plan_desktop",
                     task_id="task_desktop", revision=revision, title="Task",
                     description="preserve this description", criteria="first\nsecond",
                     confirmed=True)
        assert added["ok"], added
        current = call("plan_detail", root=str(roots[0]), id="plan_desktop")
        assert current["ok"], current
        current_revision = current["result"]["file_revision"]
        duplicate = call("plan_task_create", root=str(roots[0]), id="plan_desktop",
                         task_id="task_desktop", revision=current_revision,
                         title="must not replace", confirmed=True)
        assert duplicate["ok"] is False
        stale = call("plan_task_edit", root=str(roots[0]), id="plan_desktop",
                     task_id="task_desktop", revision=revision, title="stale", confirmed=True)
        assert stale["ok"] is False
        edited = call("plan_task_edit", root=str(roots[0]), id="plan_desktop",
                      task_id="task_desktop", revision=current_revision,
                      next_action="verify", confirmed=True)
        assert edited["ok"], edited
        own = call("plan_detail", root=str(roots[0]), id="plan_desktop")
        foreign = call("plan_detail", root=str(roots[1]), id="plan_desktop")
        assert own["ok"] and foreign["ok"], (own, foreign)
        task = own["result"]["plan"]["tasks"]["task_desktop"]
        assert task["title"] == "Task" and task["description"] == "preserve this description"
        assert task["acceptance_criteria"] == ["first", "second"]
        assert task["next_action"] == "verify"
        assert foreign["result"]["plan"]["description"] == "scope-1"
        assert foreign["result"]["plan"]["tasks"] == {}
        # The all-plan board must be usable before a card is selected.
        board = call("plan_board", root=str(roots[0]))
        assert board["ok"], board
        assert any(card["task_id"] == "task_desktop"
                   for cards in board["result"]["columns"].values() for card in cards)
        briefing = call("session_briefing", root=str(roots[0]), include=["board", "plans"])
        assert briefing["ok"] and briefing["result"]["success"] is True, briefing
        other_board = call("plan_board", root=str(roots[1]))
        assert other_board["ok"] and other_board["result"]["total_items"] == 0, other_board
        listed = call("plans", root=str(roots[0]), query="scope-0", lifecycle="active", limit=25)
        assert listed["ok"] and listed["result"]["count"] == 1, listed
        assert listed["result"]["desktop_list_limit"] == 25
        valid = call("plan_validate", root=str(roots[0]), id="plan_desktop")
        assert valid["ok"] and valid["result"]["valid"] is True, valid
        archive = dict(root=str(roots[0]), id="plan_desktop",
                       revision=own["result"]["file_revision"])
        assert call("plan_archive", **archive)["ok"] is False
        assert call("plan_archive", **{**archive, "revision": revision}, confirmed=True)["ok"] is False
        archived = call("plan_archive", **archive, confirmed=True)
        assert archived["ok"], archived
        own = call("plan_detail", root=str(roots[0]), id="plan_desktop")
        foreign = call("plan_detail", root=str(roots[1]), id="plan_desktop")
        assert own["result"]["plan"]["lifecycle"] == "archived"
        assert foreign["result"]["plan"]["lifecycle"] == "active"
        board = call("plan_board", root=str(roots[0]))
        assert board["ok"] and board["result"]["total_items"] == 0, board
    finally:
        if thread is not None:
            server.shutdown()
            thread.join(timeout=3)
        server.server_close()
        if app is not None:
            app.close()
    # The adapter is no longer connected; a read must not launch a new service.
    # The existing client is auto_start=False, verified by the unit contract too.
    result = call("probe")
    assert result["ok"] and result["result"]["online"] is False
    result = call("read", view="Endpoint analytics", root=str(roots[0]))
    assert result["ok"] is False


def test_timeline_storage_failure_is_not_an_empty_success():
    from local_ai_hub.telemetry_queries import TelemetryQueryMixin

    class UnavailableStore:
        enabled = True

        def _connect(self):
            raise sqlite3.OperationalError("database unavailable")

    with pytest.raises(sqlite3.OperationalError, match="unavailable"):
        TelemetryQueryMixin.get_timeline_page(UnavailableStore(), 50, _flush=False)


@pytest.mark.skipif(
    sys.platform != "linux" or os.environ.get("LOCAL_AI_RUN_DESKTOP_LIFECYCLE_SMOKE") != "1",
    reason="isolated Linux detached-supervisor acceptance is an explicit CI job",
)
def test_desktop_supervisor_lifecycle(tmp_path):
    import socket
    import time
    from local_ai_hub.process_utils import process_owner_state, terminate_owned_process

    # No installed user unit, production config, default ports or model servers.
    # A real detached supervisor and its real Hub child are required.
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state"
    config = tmp_path / "lifecycle.toml"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config.write_text(
        "[local_ai_hub]\nconfig_schema_version = 1\n[server]\n"
        + f"port = {port}\nstate_dir = " + json.dumps(str(state))
        + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[llama_cpp]\nmode = 'off'\n[observability]\nenabled = false"
        + "\n[background_gpu]\nenabled = false\n[preprocessing]\nenabled = false"
        + "\n[mcp_http]\nenabled = false\n[headless]\nmanage_ollama = false"
        + "\nstop_managed_ollama_on_stop = false\nstartup_grace_seconds = 20"
        + "\nunhealthy_grace_seconds = 10\nhealth_check_interval_seconds = 0.5\n",
        encoding="utf-8",
    )
    env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_CACHE_HOME": str(home / ".cache"), "XDG_DATA_HOME": str(home / ".local/share"),
           "LOCAL_AI_CONFIG": str(config)}
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)

    def call(op, **args):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/desktop.py"), "--bridge", "--config", str(config)],
            input=json.dumps({"op": op, "args": args}), capture_output=True,
            text=True, encoding="utf-8", timeout=150, env=env, cwd=ROOT, check=True,
        )
        return json.loads(result.stdout)

    def owner(role):
        value = json.loads((state / f"{role}.owner.json").read_text(encoding="utf-8"))
        assert process_owner_state(value, state, role) == "owned"
        return value

    def assert_stopped(owners):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if all(process_owner_state(value, state, role) == "stale" for role, value in owners.items()):
                break
            time.sleep(0.1)
        else:
            pytest.fail("Previous owned supervisor or Hub identity remains live or unverified")
        assert call("probe")["result"]["online"] is False
        with socket.socket() as sock:
            sock.settimeout(1)
            assert sock.connect_ex(("127.0.0.1", port)) != 0

    try:
        assert call("probe")["result"]["online"] is False
        started = call("lifecycle", action="start", confirmed=True)
        assert started["ok"], started
        assert call("probe")["result"]["online"] is True
        first = {role: owner(role) for role in ("supervisor", "hub")}
        repeated = call("lifecycle", action="start", confirmed=True)
        assert repeated["ok"], repeated
        assert all(owner(role) == value for role, value in first.items())
        rejected = call("lifecycle", action="stop")
        assert rejected["ok"] is False
        assert call("probe")["result"]["online"] is True
        restarted = call("lifecycle", action="restart", confirmed=True)
        assert restarted["ok"], restarted
        second = {role: owner(role) for role in ("supervisor", "hub")}
        assert all(second[role] != value for role, value in first.items())
        assert all(process_owner_state(value, state, role) == "stale" for role, value in first.items())
        assert call("probe")["result"]["online"] is True
        stopped = call("lifecycle", action="stop", confirmed=True)
        assert stopped["ok"], stopped
        assert_stopped(second)
        assert (state / "service.disabled").is_file()
        again = call("lifecycle", action="stop", confirmed=True)
        assert again["ok"], again
    finally:
        # On failure, only terminate identities proven to belong to this
        # temporary state directory; never use a listening PID alone.
        state.mkdir(exist_ok=True)
        (state / "service.disabled").touch()
        for role in ("supervisor", "hub"):
            try:
                value = json.loads((state / f"{role}.owner.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if process_owner_state(value, state, role) == "owned":
                assert terminate_owned_process(value, state, role, grace_seconds=5.0)
