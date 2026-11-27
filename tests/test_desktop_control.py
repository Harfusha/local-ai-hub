"""Contract tests for the native desktop controller (no service or display)."""
import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from tools import desktop


def test_read_never_autostarts_or_calls_offline_hub():
    with patch.object(desktop, "HubClient") as factory:
        factory.return_value._online.return_value = False
        control = desktop.HubControl("config.toml")
        with pytest.raises(RuntimeError, match="not reachable"):
            control.read("Overview")
        factory.assert_called_once_with(config_path="config.toml", auto_start=False)
        factory.return_value.get.assert_not_called()
        factory.return_value.close.assert_called_once()


def test_scoped_read_requires_explicit_root():
    control = desktop.HubControl()
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="explicit"):
            control.read("Tasks")
        factory.assert_not_called()


def test_scoped_read_encodes_root(tmp_path):
    root = tmp_path / "space & name"
    root.mkdir()
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True, "tasks": []}
        result = desktop.HubControl().read("Tasks", str(root))
        assert result["tasks"] == []
        from urllib.parse import parse_qs, urlsplit
        url = client.get.call_args.args[0]
        assert parse_qs(urlsplit(url).query)["root"] == [str(root.resolve())]
        client.close.assert_called_once()


@pytest.mark.parametrize("action", ["stop", "restart"])
def test_lifecycle_reuses_existing_cli(action):
    control = desktop.HubControl("config.toml")
    with patch.object(control, "_cli", return_value="completed") as cli:
        assert control.lifecycle(action) == "completed"
        cli.assert_called_once_with((action,), timeout=760)


def test_start_when_offline():
    control = desktop.HubControl()
    with patch.object(control, "online", return_value=False), patch.object(
        control, "_cli", return_value="started"
    ) as cli:
        assert control.lifecycle("start") == "started"
        cli.assert_called_once_with(("start",), timeout=760)


def test_start_is_idempotent_if_online():
    control = desktop.HubControl()
    with patch.object(control, "online", return_value=True), patch.object(control, "_cli") as cli:
        assert control.lifecycle("start") == "Hub is already online."
        cli.assert_not_called()


@pytest.mark.parametrize("value", ["command", "start && anything", "--help"])
def test_rejects_unregistered_lifecycle_and_modes(value):
    control = desktop.HubControl()
    with patch.object(control, "_cli") as cli:
        with pytest.raises(ValueError):
            control.lifecycle(value)
        with pytest.raises(ValueError):
            control.mode(value)
        cli.assert_not_called()


def test_cli_uses_fixed_argv_no_shell():
    control = desktop.HubControl("config.toml")
    with patch.object(desktop.subprocess, "run") as run:
        run.return_value = MagicMock(returncode=0, stdout="started", stderr="")
        assert control._cli(("start",), 760) == "started"
        args, kwargs = run.call_args
        assert args[0] == [desktop.sys.executable, str(desktop.ROOT / "tools" / "hubctl.py"), "start"]
        assert not kwargs.get("shell", False)
        assert kwargs["env"]["LOCAL_AI_CONFIG"] == "config.toml"


def test_api_failure_is_not_rendered_as_success():
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": False, "error": "denied"}
        with pytest.raises(RuntimeError, match="denied"):
            desktop.HubControl().read("Overview")
        client.close.assert_called_once()


def test_maintenance_requires_explicit_success():
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.post.return_value = {"success": False, "error": "denied"}
        with pytest.raises(RuntimeError, match="denied"):
            desktop.HubControl().maintenance("Purge expired cache (7 days)")
        assert client.post.call_args.args == ("/api/maintenance/purge_cache", {"days": 7})
        client.close.assert_called_once()


def test_unknown_maintenance_is_rejected_before_transport():
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(KeyError):
            desktop.HubControl().maintenance("arbitrary shell")
        factory.assert_not_called()


def test_bridge_rejects_arbitrary_route_and_shell():
    control = MagicMock()
    for request in (
        {"op": "post", "args": {"route": "/api/command"}},
        {"op": "shell", "args": {"command": "echo no"}},
        {"op": "project", "args": {"action": "arbitrary", "confirmed": True}},
    ):
        with pytest.raises(ValueError):
            desktop.dispatch(control, request)
    control._client.assert_not_called()


@pytest.mark.parametrize("op,args", [
    ("maintenance", {"action": "Purge detailed traces"}),
    ("telemetry", {"mode": "full"}),
    ("config_reset", {}),
    ("task", {"action": "complete", "id": "task_1"}),
    ("project", {"action": "unregister"}),
])
def test_bridge_requires_confirmation(op, args):
    with pytest.raises(ValueError, match="confirmation"):
        desktop.dispatch(MagicMock(), {"op": op, "args": args})


def test_plan_board_requires_explicit_scope():
    with pytest.raises(ValueError, match="explicit"):
        desktop.dispatch(MagicMock(), {"op": "plan_board", "args": {"id": "plan_1"}})


def test_project_unregister_keeps_data(tmp_path):
    control = MagicMock()
    with patch.object(desktop, "checked_post", return_value={"success": True}) as post:
        desktop.dispatch(control, {"op": "project", "args": {
            "root": str(tmp_path), "action": "unregister", "confirmed": True}})
        post.assert_called_once_with(control, "/api/preprocess", {
            "root": str(tmp_path.resolve()), "action": "unregister", "purge_data": False})


def test_bridge_never_imports_tkinter():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(desktop.__file__).read_text(encoding="utf-8"))
    imports = [a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names]
    assert "tkinter" not in imports
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "tkinter"
                   for node in ast.walk(tree))


@pytest.mark.parametrize("path", ["/", "/dashboard", "/dashboard/", "/favicon.ico"])
def test_http_web_ui_route_is_retired(path):
    from local_ai_hub.http_api_get import HttpGetMixin
    handler = MagicMock()
    handler.path = path
    handler._reject_identity_fields.return_value = True
    HttpGetMixin.do_GET(handler)
    handler._send.assert_called_once_with(
        404, {"success": False, "error": "Web UI removed; use Local AI Hub Desktop."}
    )


def test_trace_identifier_cannot_select_another_route():
    control = MagicMock()
    with pytest.raises(ValueError, match="Invalid trace identifier"):
        desktop.dispatch(control, {"op": "trace_detail", "args": {"id": "../config"}})
    control._client.assert_not_called()


def test_plan_edit_requires_current_revision(tmp_path):
    control = MagicMock()
    with pytest.raises(ValueError, match="revision"):
        desktop.dispatch(control, {"op": "plan_update", "args": {
            "root": str(tmp_path), "id": "plan_1", "title": "new", "confirmed": True}})
    control._client.assert_not_called()


@pytest.mark.parametrize("operation", ["bundle_import", "bundle_export", "diagnostics_export"])
def test_binary_transfer_requires_confirmation(operation):
    control = MagicMock()
    with pytest.raises(ValueError, match="confirmation"):
        desktop.dispatch(control, {"op": operation, "args": {"file": "test.zip"}})
    control._client.assert_not_called()


def test_native_setting_rejects_retired_web_flags():
    control = MagicMock()
    with pytest.raises(ValueError, match="retired"):
        desktop.dispatch(control, {"op": "setting", "args": {
            "key": "features.dashboard", "value": True, "confirmed": True}})
    control._client.assert_not_called()


def test_native_plan_move_cannot_claim_done(tmp_path):
    control = MagicMock()
    with pytest.raises(ValueError, match="completion"):
        desktop.dispatch(control, {"op": "plan_task_move", "args": {
            "root": str(tmp_path), "id": "plan_1", "revision": "rev", "task_id": "task_1",
            "status": "done", "confirmed": True}})
    control._client.assert_not_called()


def test_vision_rejects_non_image_before_transport(tmp_path):
    image = tmp_path / "not-image.png"
    image.write_bytes(b"not an image")
    control = MagicMock()
    with pytest.raises(ValueError, match="Unsupported image"):
        desktop.dispatch(control, {"op": "vision_review", "args": {
            "file": str(image), "prompt": "Describe", "confirmed": True}})
    control._client.assert_not_called()


def test_native_event_stream_requires_repository_and_stream():
    with pytest.raises(ValueError, match="explicit"):
        desktop.dispatch(MagicMock(), {"op": "event_stream", "args": {"stream": "task_1"}})


def test_native_update_install_requires_confirmation():
    control = MagicMock()
    with pytest.raises(ValueError, match="confirmation"):
        desktop.dispatch(control, {"op": "update_install", "args": {"version": "1.0.0"}})
    control._client.assert_not_called()


def test_operator_catalog_is_available_without_hub():
    control = MagicMock()
    result = desktop.dispatch(control, {"op": "operator_catalog"})
    assert any(row["name"] == "Knowledge query" for row in result["operations"])
    control._client.assert_not_called()


def test_operator_fields_cannot_inject_cli_flags(tmp_path):
    from tools.desktop_operator import build_argv
    argv, _ = build_argv({"name": "Knowledge query", "root": str(tmp_path),
                          "fields": {"query": "--apply", "limit": "12"}})
    assert "--query=--apply" in argv
    assert "--apply" not in argv
    assert "--no-auto-start" in argv
    with pytest.raises(ValueError, match="Unknown operator field"):
        build_argv({"name": "Knowledge query", "root": str(tmp_path), "fields": {"apply": True}})


def test_operator_mutations_and_review_digests_fail_closed(tmp_path):
    from tools.desktop_operator import build_argv
    with pytest.raises(ValueError, match="confirmation"):
        build_argv({"name": "Knowledge batch apply", "root": str(tmp_path)})
    record = tmp_path / "batch.json"
    record.write_text('{"records":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="digest"):
        build_argv({"name": "Knowledge batch apply", "root": str(tmp_path), "confirmed": True,
                    "fields": {"record-file": str(record), "operation-id": "op"}})


def test_trace_export_requires_confirmed_server_redaction(tmp_path):
    control = desktop.HubControl()
    target = tmp_path / "trace.json"
    args = {"id": "trace-1", "file": str(target), "confirmed": True}
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True, "redacted_export": False}
        with pytest.raises(RuntimeError, match="redacted"):
            desktop.dispatch(control, {"op": "trace_export", "args": args})
        assert not target.exists()
        client.get.return_value = {"success": True, "redacted_export": True, "events": []}
        result = desktop.dispatch(control, {"op": "trace_export", "args": args})
        assert result["success"] and target.is_file()
        with pytest.raises(ValueError, match="Destination exists"):
            desktop.dispatch(control, {"op": "trace_export", "args": args})


def test_trace_rejects_conflicting_cursors():
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="either"):
            desktop.dispatch(desktop.HubControl(), {"op": "trace_detail", "args": {"id": "t", "before": 1, "after": 2}})
        factory.assert_not_called()


@pytest.mark.parametrize("op,args", [("lifecycle", {"action": "stop"}), ("lifecycle", {"action": "restart"}), ("mode", {"mode": "active"}), ("trace_content", {"id": "trace-1", "field": "request"})])
def test_sensitive_operator_actions_require_confirmation(op, args):
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="confirmation"):
            desktop.dispatch(desktop.HubControl(), {"op": op, "args": args})
        factory.assert_not_called()


def test_task_gate_is_scoped_and_preserves_server_receipts(tmp_path):
    control = desktop.HubControl()
    response = {"success": True, "completion": {"unsatisfied_criteria": ["test"]}}
    with patch.object(desktop, "checked_post", return_value=response) as post:
        result = desktop.dispatch(control, {"op": "task_gate", "args": {"root": str(tmp_path), "id": "t"}})
        assert result == response
        post.assert_called_once_with(control, "/api/agent-state/verification",
                                     {"root": str(tmp_path.resolve()), "action": "completion", "task_id": "t"})


def test_task_transition_does_not_bypass_completion_gate(tmp_path):
    with patch.object(desktop, "checked_post") as post:
        args = {"root": str(tmp_path), "id": "t", "action": "transition", "status": "completed",
                "reason": "review", "confirmed": True}
        with pytest.raises(ValueError, match="transition"):
            desktop.dispatch(desktop.HubControl(), {"op": "task", "args": args})
        post.assert_not_called()


def test_endpoint_reset_needs_explicit_global_scope():
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError, match="global"):
            desktop.dispatch(desktop.HubControl(), {"op": "endpoint_reset", "args": {"confirmed": True}})
        post.assert_not_called()


def test_project_purge_requires_confirmation_and_boolean(tmp_path):
    with patch.object(desktop, "checked_post") as post:
        args = {"root": str(tmp_path), "action": "unregister", "purge_data": "yes", "confirmed": True}
        with pytest.raises(ValueError, match="purge"):
            desktop.dispatch(desktop.HubControl(), {"op": "project", "args": args})
        post.assert_not_called()
        args["purge_data"] = True
        desktop.dispatch(desktop.HubControl(), {"op": "project", "args": args})
        assert post.call_args.args[2]["purge_data"] is True


def test_settings_batch_validates_before_transport():
    control = desktop.HubControl()
    with patch.object(desktop, "checked_post", return_value={"success": True, "restart_required": True}) as post:
        for settings in ({"features.dashboard": True}, {"telemetry.mode": "full"}, {"features.tasks": "true"}):
            with pytest.raises(ValueError):
                desktop.dispatch(control, {"op": "settings_batch", "args": {"confirmed": True, "settings": settings}})
        post.assert_not_called()
        settings = {"features.tasks": False, "hardware.profile": "cpu"}
        result = desktop.dispatch(control, {"op": "settings_batch", "args": {"confirmed": True, "settings": settings}})
        assert result["restart_required"] is True
        post.assert_called_once_with(control, "/api/config/update", {"action": "update", "settings": settings})


def test_live_period_is_allowlisted_and_not_injected():
    control = desktop.HubControl()
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="period"):
            control.read("Overview", period="window&secret=true")
        factory.assert_not_called()
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True}
        control.read("Overview", period="window")
        assert client.get.call_args.args[0] == "/api/live/status?light=1&scope=window"


def test_stats_reset_unavailable_is_not_success(tmp_path):
    with patch.object(desktop, "checked_post", return_value={"success": True, "reset": False, "available": False}):
        with pytest.raises(RuntimeError, match="confirm reset"):
            desktop.dispatch(desktop.HubControl(), {"op": "endpoint_reset", "args": {"root": str(tmp_path), "confirmed": True}})


@pytest.mark.parametrize("lines", [100, 250, 500])
def test_log_tail_uses_fixed_endpoint_and_no_autostart(lines):
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True, "lines": ["INFO ready"]}
        result = desktop.dispatch(desktop.HubControl("config.toml"),
                                  {"op": "log_tail", "args": {"lines": lines}})
        assert result["lines"] == ["INFO ready"]
        factory.assert_called_once_with(config_path="config.toml", auto_start=False)
        client.get.assert_called_once_with(f"/api/logs/tail?lines={lines}",
                                           timeout=15.0, requires_heavy_work=False)
        client.close.assert_called_once()


@pytest.mark.parametrize("lines", [0, 501, -1, "250", True])
def test_log_tail_rejects_unbounded_or_untyped_limits(lines):
    with patch.object(desktop, "HubClient") as factory:
        with pytest.raises(ValueError, match="Log tail requires"):
            desktop.dispatch(desktop.HubControl(), {"op": "log_tail", "args": {"lines": lines}})
        factory.assert_not_called()


@pytest.mark.parametrize("result", [
    {"success": False, "error": "disabled"},
    {"success": True, "lines": "not a list"},
    {"success": True, "lines": [None]},
    {"success": True, "lines": ["line"] * 101},
])
def test_log_tail_does_not_present_invalid_or_disabled_data_as_empty(result):
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = result
        with pytest.raises(RuntimeError):
            desktop.dispatch(desktop.HubControl(), {"op": "log_tail", "args": {"lines": 100}})
        client.close.assert_called_once()


def test_plan_detail_is_scoped_and_reads_canonical_route(tmp_path):
    with patch.object(desktop, "checked_post") as post:
        desktop.dispatch(desktop.HubControl(), {"op": "plan_detail", "args": {
            "root": str(tmp_path), "id": "plan_1",
        }})
        post.assert_called_once_with(
            post.call_args.args[0], "/api/coord/plan_get",
            {"root": str(tmp_path.resolve()), "plan_id": "plan_1"},
        )


def test_plan_text_patch_does_not_overwrite_omitted_fields():
    assert desktop.plan_text_patch({"next_action": "review"}, task=True) == {"next_action": "review"}
    assert desktop.plan_text_patch({"description": ""}, task=False) == {"description": ""}
    assert desktop.plan_text_patch({"blocker": ""}, task=True) == {"blocker": None}
    assert desktop.plan_text_patch({"criteria": "one\ntwo"}, task=True) == {
        "acceptance_criteria": ["one", "two"],
    }
    with pytest.raises(ValueError, match="description"):
        desktop.plan_text_patch({"description": "a" * 12001}, task=True)
    with pytest.raises(ValueError, match="next_action"):
        desktop.plan_text_patch({"next_action": 1}, task=True)
    with pytest.raises(ValueError, match="No plan fields"):
        desktop.plan_text_patch({}, task=True)


@pytest.mark.parametrize("existing,observed_revision", [(True, "rev"), (False, "stale")])
def test_add_task_refuses_existing_id_or_stale_revision(tmp_path, existing, observed_revision):
    plan = {"success": True, "file_revision": observed_revision,
            "plan": {"id": "plan_1", "tasks": {"task_1": {}} if existing else {}}}
    with patch.object(desktop, "checked_post", return_value=plan) as post:
        with pytest.raises(ValueError, match="already exists|Plan changed"):
            desktop.dispatch(desktop.HubControl(), {"op": "plan_task_create", "args": {
                "root": str(tmp_path), "id": "plan_1", "task_id": "task_1",
                "revision": "rev", "title": "new", "confirmed": True,
            }})
        assert post.call_count == 1
        assert post.call_args.args[1] == "/api/coord/plan_get"


def test_add_task_uses_exact_reviewed_revision_for_new_id(tmp_path):
    plan = {"success": True, "file_revision": "rev",
            "plan": {"id": "plan_1", "tasks": {}}}
    with patch.object(desktop, "checked_post", side_effect=[plan, {"success": True}]) as post:
        result = desktop.dispatch(desktop.HubControl(), {"op": "plan_task_create", "args": {
            "root": str(tmp_path), "id": "plan_1", "task_id": "task_1",
            "revision": "rev", "title": "new", "confirmed": True,
        }})
        assert result["success"] is True
        assert post.call_count == 2
        assert post.call_args.args[1] == "/api/coord/plan_task_edit"
        payload = post.call_args.args[2]
        assert payload["expected_revision"] == "rev" and payload["task_id"] == "task_1"
        assert payload["task_data"]["title"] == "new"


def test_desktop_doctor_uses_post_and_preserves_failed_checks():
    report = {"success": True, "checks": [
        {"component": "Runtime", "status": "FAIL", "detail": "offline"},
    ]}
    control = MagicMock()
    with patch.object(desktop, "checked_post", return_value=report) as post:
        assert desktop.dispatch(control, {"op": "doctor", "args": {}}) == report
        post.assert_called_once_with(control, "/api/doctor", {}, timeout=120.0)


@pytest.mark.parametrize("before,limit", [(True, 100), (-1, 100), (0, 99), (2**63, 100), (0, True)])
def test_telemetry_page_rejects_invalid_input(before, limit):
    control = MagicMock()
    with pytest.raises(ValueError):
        desktop.dispatch(control, {"op": "timeline_page", "args": {"before": before, "limit": limit}})
    control._client.assert_not_called()


def test_telemetry_page_uses_exclusive_cursor_and_never_autostarts():
    from urllib.parse import parse_qs, urlsplit

    page = {"success": True, "timeline": [{"id": 11}, {"id": 12}], "has_more": True, "next_cursor": 11}
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = page
        result = desktop.dispatch(desktop.HubControl(), {"op": "timeline_page", "args": {"before": 13, "limit": 50}})
        assert result == page
        assert factory.call_args.kwargs["auto_start"] is False
        route = urlsplit(client.get.call_args.args[0])
        assert route.path == "/api/telemetry/timeline"
        assert parse_qs(route.query) == {"limit": ["50"], "before_id": ["13"]}
        client.close.assert_called_once()


@pytest.mark.parametrize("rows,more,cursor", [
    ([{"id": 12}, {"id": 11}], False, None),
    ([{"id": 11}, {"id": 11}], False, None),
    ([{"id": 13}], False, None),
    ([{"id": True}], False, None),
    ([{"id": 11}], True, 12),
    ([], True, None),
    ([{"id": 11}], False, 11),
])
def test_telemetry_page_rejects_malformed_server_cursors(rows, more, cursor):
    control = MagicMock()
    client = control._client.return_value
    client._online.return_value = True
    client.get.return_value = {"success": True, "timeline": rows, "has_more": more, "next_cursor": cursor}
    with pytest.raises(RuntimeError, match="Malformed telemetry"):
        desktop.dispatch(control, {"op": "timeline_page", "args": {"before": 13}})
    client.close.assert_called_once()


@pytest.mark.parametrize("scope,field", [("task", "task_id"), ("session", "session_id"),
    ("clone", "clone_id"), ("worktree", "worktree_id"), ("branch", "branch")])
def test_memory_find_transmits_only_selected_scope(tmp_path, scope, field):
    control = MagicMock()
    with patch.object(desktop, "checked_post") as post:
        desktop.dispatch(control, {"op": "memory_find", "args": {
            "root": str(tmp_path), "scope": scope, field: "exact",
            "query": "search", "value": "not part of query",
        }})
        post.assert_called_once_with(control, "/api/agent-state/memory", {
            "root": str(tmp_path.resolve()), "scope": scope, field: "exact",
            "action": "find", "query": "search", "limit": 100,
        })


def test_memory_delete_requires_exact_record_and_scope(tmp_path):
    control = MagicMock()
    args = {"root": str(tmp_path), "scope": "task", "task_id": "task_a",
            "confirmed": True, "key": "not an identity"}
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError):
            desktop.dispatch(control, {"op": "memory_delete", "args": args})
        post.assert_not_called()
        args["record_id"] = "record_a"
        desktop.dispatch(control, {"op": "memory_delete", "args": args})
        post.assert_called_once_with(control, "/api/agent-state/memory", {
            "root": str(tmp_path.resolve()), "scope": "task", "task_id": "task_a",
            "action": "delete", "record_id": "record_a",
        })


def test_desktop_does_not_bypass_worktree_memory_delete_gate(tmp_path):
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError, match="verified scope"):
            desktop.dispatch(MagicMock(), {"op": "memory_delete", "args": {
                "root": str(tmp_path), "scope": "worktree", "worktree_id": "wt_a",
                "record_id": "record_a", "confirmed": True,
            }})
        post.assert_not_called()


@pytest.mark.parametrize("owner", ["wrong", ""])
def test_file_lease_release_requires_observed_owner(tmp_path, owner):
    with patch.object(desktop, "scoped_read", return_value={"success": True,
            "leases": [{"lease_id": "lease_a", "owner": "writer"}]}), patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError):
            desktop.dispatch(MagicMock(), {"op": "lease_release", "args": {
                "root": str(tmp_path), "id": "lease_a", "owner": owner, "confirmed": True,
            }})
        post.assert_not_called()


@pytest.mark.parametrize("released_rows", [0, True, None, 2])
def test_file_lease_release_checks_actual_result(tmp_path, released_rows):
    control = MagicMock()
    with patch.object(desktop, "scoped_read", return_value={"success": True,
            "leases": [{"lease_id": "lease_a", "owner": "writer"}]}) as read, patch.object(
            desktop, "checked_post", return_value={"success": True, "released_rows": released_rows}) as post:
        request = {"op": "lease_release", "args": {
            "root": str(tmp_path), "id": "lease_a", "owner": "writer", "confirmed": True,
        }}
        if type(released_rows) is int and released_rows > 0:
            assert desktop.dispatch(control, request)["released_rows"] == released_rows
        else:
            with pytest.raises(RuntimeError, match="release not confirmed"):
                desktop.dispatch(control, request)
        read.assert_called_once_with(control, "/api/leases", str(tmp_path.resolve()))
        post.assert_called_once_with(control, "/api/leases/release", {"lease_id": "lease_a", "owner": "writer"})


def test_semaphore_release_uses_owner_and_checks_release():
    control = MagicMock()
    with patch.object(desktop, "checked_post", return_value={"success": True, "released": False}) as post:
        with pytest.raises(RuntimeError, match="not released"):
            desktop.dispatch(control, {"op": "semaphore_release", "args": {
                "name": "gpu", "id": "lease_a", "owner": "worker", "confirmed": True,
            }})
        post.assert_called_once_with(control, "/api/coord/semaphore_release",
                                     {"name": "gpu", "lease_id": "lease_a", "owner": "worker"})


def test_session_briefing_is_scoped_read_without_confirmation(tmp_path):
    control = MagicMock()
    with patch.object(desktop, "checked_post") as post:
        desktop.dispatch(control, {"op": "session_briefing", "args": {"root": str(tmp_path)}})
        post.assert_called_once_with(control, "/api/coord/session_briefing", {
            "root": str(tmp_path.resolve()), "include": ["board", "plans", "active_tasks"],
        })
        post.reset_mock()
        with pytest.raises(ValueError, match="sections"):
            desktop.dispatch(control, {"op": "session_briefing", "args": {
                "root": str(tmp_path), "include": ["board", "board"],
            }})
        post.assert_not_called()


@pytest.mark.parametrize("op", ["plan_task_edit", "plan_task_move", "plan_task_delete"])
def test_plan_task_mutation_never_upserts_missing_card(tmp_path, op):
    plan = {"success": True, "file_revision": "rev",
            "plan": {"id": "plan_1", "tasks": {}}}
    with patch.object(desktop, "checked_post", return_value=plan) as post:
        with pytest.raises(ValueError, match="not found"):
            desktop.dispatch(desktop.HubControl(), {"op": op, "args": {
                "root": str(tmp_path), "id": "plan_1", "task_id": "task_missing",
                "revision": "rev", "title": "unexpected", "status": "ready", "confirmed": True,
            }})
        assert post.call_count == 1
        assert post.call_args.args[1] == "/api/coord/plan_get"


@pytest.mark.parametrize("limit", [True, 0, 1000, "100"])
def test_plan_list_rejects_unbounded_limits(tmp_path, limit):
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError, match="limit"):
            desktop.dispatch(MagicMock(), {"op": "plans", "args": {"root": str(tmp_path), "limit": limit}})
        post.assert_not_called()


def test_model_compare_requires_explicit_confirmation():
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError, match="confirmation"):
            desktop.dispatch(MagicMock(), {"op": "compare", "args": {"prompt": "test"}})
        post.assert_not_called()


@pytest.mark.parametrize("view", ["Model statistics", "Execution profiles", "Cache layers",
    "Agent statistics", "Execution routes", "Laya capture"])
def test_operational_statistics_use_existing_light_status_endpoint(view):
    with patch.object(desktop, "HubClient") as factory:
        client = factory.return_value
        client._online.return_value = True
        client.get.return_value = {"success": True, "observability": {}}
        desktop.HubControl().read(view, period="window")
        client.get.assert_called_once_with("/api/live/status?light=1&scope=window",
                                           timeout=15.0, requires_heavy_work=False)
        client.close.assert_called_once()


def test_archive_body_reads_bounded_chunks_and_rejects_short_file():
    raw = b"x" * 150_000
    body = desktop.BoundedArchiveBody(io.BytesIO(raw + b"ignored"), len(raw))
    chunks = [body.read(1_000_000), body.read(1_000_000), body.read(1_000_000)]
    assert max(map(len, chunks)) == 65536
    assert b"".join(chunks) == raw and body.remaining == 0
    assert body.read() == b""
    short = desktop.BoundedArchiveBody(io.BytesIO(b"a"), 2)
    assert short.read() == b"a"
    with pytest.raises(RuntimeError, match="changed during upload"):
        short.read()


def test_archive_import_streams_content_length_and_checks_zip(tmp_path):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("fixture.txt", b"x" * 150_000)
    control = MagicMock()
    client = control._client.return_value
    client._online.return_value = True
    client.config = {}
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = b'{"success": true}'
    seen = []

    def send(method, path, body, headers):
        assert method == "POST" and path.startswith("/api/bundle/import?")
        assert headers["Content-Length"] == str(archive.stat().st_size)
        assert isinstance(body, desktop.BoundedArchiveBody)
        while chunk := body.read(8192):
            assert len(chunk) <= 8192
            seen.append(chunk)

    connection.request.side_effect = send
    args = {"file": str(archive), "root": str(tmp_path), "confirmed": True}
    with patch.object(desktop.http.client, "HTTPConnection", return_value=connection):
        result = desktop.transfer(control, "bundle_import", args)
        assert result["success"] is True
        assert b"".join(seen) == archive.read_bytes()
        connection.request.reset_mock()
        archive.write_bytes(b"PK" + b"not a zip archive" * 3)
        with pytest.raises(ValueError, match="Invalid ZIP"):
            desktop.transfer(control, "bundle_import", args)
        connection.request.assert_not_called()


@pytest.mark.parametrize("valid", [True, False])
def test_export_requires_complete_valid_archive(tmp_path, valid):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        output.writestr("fixture.txt", "test")
    payload = buffer.getvalue() if valid else b"not a zip"
    target = tmp_path / "export.zip"
    control = MagicMock()
    control._client.return_value._online.return_value = True
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.status = 200
    response.getheader.side_effect = lambda key, default=None: {
        "Content-Type": "application/zip", "Content-Length": str(len(payload)),
        "X-Local-AI-Export-Password": "fixture-only-password",
    }.get(key, default)
    response.read.side_effect = [payload, b""]
    with patch.object(desktop.http.client, "HTTPConnection", return_value=connection):
        args = {"file": str(target), "confirmed": True}
        if valid:
            result = desktop.transfer(control, "diagnostics_export", args)
            assert result["archive_password"] == "fixture-only-password"
            assert target.read_bytes() == payload
        else:
            with pytest.raises(RuntimeError, match="invalid ZIP"):
                desktop.transfer(control, "diagnostics_export", args)
            assert not target.exists()
    connection.close.assert_called_once()
    control._client.return_value.close.assert_called_once()


def test_task_page_uses_server_filters_and_exact_continuation(tmp_path):
    from urllib.parse import parse_qs, urlsplit

    control = MagicMock()
    client = control._client.return_value
    client._online.return_value = True
    page = {"success": True, "tasks": [{"task_id": "task_a"}],
            "offset": 50, "limit": 25, "next_offset": 51, "has_more": True,
            "query_truncated": True}
    client.get.return_value = page
    result = desktop.dispatch(control, {"op": "task_page", "args": {
        "root": str(tmp_path), "status": "waiting", "query": "a & b",
        "limit": 25, "offset": 50,
    }})
    assert result == page
    query = parse_qs(urlsplit(client.get.call_args.args[0]).query)
    assert query["status"] == ["waiting"]
    assert query["query"] == ["a & b"]
    assert query["limit"] == ["25"] and query["offset"] == ["50"]
    assert query["root"] == [str(tmp_path.resolve())]
    client.close.assert_called_once()


@pytest.mark.parametrize("patch_fields", [{"status": "unknown"}, {"limit": True}, {"limit": 1000}])
def test_invalid_task_filters_rejected_before_transport(tmp_path, patch_fields):
    control = MagicMock()
    with pytest.raises(ValueError):
        desktop.dispatch(control, {"op": "task_page", "args": {
            "root": str(tmp_path), **patch_fields,
        }})
    control._client.assert_not_called()


@pytest.mark.parametrize("bad_page", [{"next_offset": -1}, {"next_offset": True},
    {"has_more": "true"}, {"limit": 25}, {"offset": 1}])
def test_task_page_rejects_invalid_server_cursor(tmp_path, bad_page):
    control = MagicMock()
    client = control._client.return_value
    client._online.return_value = True
    client.get.return_value = {"success": True, "tasks": [], "offset": 0,
                               "limit": 100, "next_offset": 0, "has_more": False, **bad_page}
    with pytest.raises(RuntimeError, match="Malformed task page"):
        desktop.dispatch(control, {"op": "task_page", "args": {"root": str(tmp_path)}})
    client.close.assert_called_once()


def test_memory_find_filters_do_not_include_mutation_fields(tmp_path):
    control = MagicMock()
    with patch.object(desktop, "checked_post") as post:
        desktop.dispatch(control, {"op": "memory_find", "args": {
            "root": str(tmp_path), "scope": "repository", "key": "exact",
            "query": "query", "status": "quarantined", "limit": 25,
            "reason": "unused", "record_id": "unused", "value": "unused",
        }})
        post.assert_called_once_with(control, "/api/agent-state/memory", {
            "root": str(tmp_path.resolve()), "scope": "repository", "action": "find",
            "key": "exact", "query": "query", "status": "quarantined", "limit": 25,
        })


@pytest.mark.parametrize("fields", [{"status": "wrong"}, {"limit": True}, {"limit": 1000}])
def test_memory_filter_rejects_invalid_values(tmp_path, fields):
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError):
            desktop.dispatch(MagicMock(), {"op": "memory_find", "args": {
                "root": str(tmp_path), **fields,
            }})
        post.assert_not_called()


@pytest.mark.parametrize("op", ["memory_get", "memory_quarantine"])
def test_memory_exact_response_identity_is_required(tmp_path, op):
    args = {"root": str(tmp_path), "scope": "repository", "record_id": "rec_a",
            "reason": "bad evidence", "confirmed": True}
    control = MagicMock()
    with patch.object(desktop, "checked_post", return_value={
        "success": True, "record": {"record_id": "rec_other", "scope": "repository", "status": "quarantined"},
    }) as post:
        with pytest.raises(RuntimeError, match="not confirmed"):
            desktop.dispatch(control, {"op": op, "args": args})
        payload = {"root": str(tmp_path.resolve()), "scope": "repository",
                   "record_id": "rec_a", "action": "get" if op == "memory_get" else "quarantine"}
        if op == "memory_quarantine":
            payload["reason"] = "bad evidence"
        post.assert_called_once_with(control, "/api/agent-state/memory", payload)


@pytest.mark.parametrize("fields", [{"confirmed": False}, {"reason": ""},
    {"scope": "worktree", "worktree_id": "worktree-a"}])
def test_memory_quarantine_requires_confirmed_authorized_scope_and_reason(tmp_path, fields):
    with patch.object(desktop, "checked_post") as post:
        with pytest.raises(ValueError):
            desktop.dispatch(MagicMock(), {"op": "memory_quarantine", "args": {
                "root": str(tmp_path), "scope": "repository", "record_id": "rec_a",
                "reason": "review", "confirmed": True, **fields,
            }})
        post.assert_not_called()
