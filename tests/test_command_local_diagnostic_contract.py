import pytest

from local_ai_hub.services import LocalAIServices
from local_ai_hub.commands import CommandBroker


def test_automatic_diagnostic_is_opt_in_by_default():
    import tomllib
    from pathlib import Path
    defaults = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "defaults.toml"
    with defaults.open("rb") as source:
        config = tomllib.load(source)
    assert config["features"]["local_diagnostic_dispatch"] is False


@pytest.mark.parametrize("status", ["completed", "timed_out", "unavailable", "cancelled"])
def test_response_budget_preserves_local_diagnostic_evidence(status):
    from local_ai_hub.response_budget import budget_response
    value = {"success": False, "execution_id": "e" * 32, "error": "command failed",
             "local_diagnostic_status": status, "diagnostic_context_artifact_id": "art_example",
             "noise": "x" * 5000}
    if status == "completed":
        value["local_diagnostic"] = {"text": "Check the failure.", "artifact_id": "art_example", "advisory": True}
    response = budget_response(value, max_tokens=256, profile="compact")
    assert response["local_diagnostic_status"] == status
    assert response["diagnostic_context_artifact_id"] == "art_example"
    if status == "completed":
        assert response["local_diagnostic"] == value["local_diagnostic"]


def test_response_budget_explicitly_rejects_oversized_diagnostic():
    from local_ai_hub.response_budget import budget_response
    value = {"success": False, "execution_id": "e" * 32, "error": "command failed",
             "local_diagnostic_status": "completed", "diagnostic_context_artifact_id": "art_example",
             "local_diagnostic": {"text": "x" * 300, "artifact_id": "art_example", "advisory": True},
             "noise": "y" * 5000}
    response = budget_response(value, max_tokens=128, profile="compact")
    assert response["response_budget"]["rejected"] is True
    assert response["response_budget"]["returned_tokens"] <= 128


@pytest.mark.parametrize("response", [
    {"text": "misleading advice"},
    {"success": False, "text": "misleading advice"},
    {"success": 1, "text": "misleading advice"},
    {"success": True, "text": {"unexpected": "object"}},
])
def test_command_diagnostic_rejects_ambiguous_model_response(response):
    services = object.__new__(LocalAIServices)
    services.reason = lambda _args: response
    assert services.distill_command_error({"summary": "command failed"}) == ""


def test_command_diagnostic_accepts_explicit_successful_text():
    services = object.__new__(LocalAIServices)
    services.reason = lambda _args: {"success": True, "text": " Check the failing dependency. "}
    assert services.distill_command_error({"summary": "command failed"}) == "Check the failing dependency."


@pytest.mark.parametrize("quality", [{"usable": False}, {"usable": "true"}, {}, None])
def test_command_diagnostic_rejects_unusable_or_ambiguous_quality(quality):
    services = object.__new__(LocalAIServices)
    services.reason = lambda _args: {"success": True, "text": "unsupported conclusion", "semantic_quality": quality}
    assert services.distill_command_error({"summary": "command failed"}) == ""


def test_command_diagnostic_accepts_usable_quality():
    services = object.__new__(LocalAIServices)
    services.reason = lambda _args: {"success": True, "text": "Check failure.", "semantic_quality": {"usable": True}}
    assert services.distill_command_error({"summary": "command failed"}) == "Check failure."


def test_command_diagnostic_limits_context_to_preview_size():
    services = object.__new__(LocalAIServices)
    seen = []
    services.reason = lambda args: seen.append(args) or {"success": True, "text": "Check failure."}
    assert services.distill_command_error({"summary": "x" * 1000}) == "Check failure."
    assert seen[0]["context"] == "x" * 800


def test_command_diagnostic_propagates_cancellation_and_rejects_late_answer():
    import threading
    services = object.__new__(LocalAIServices)
    event = threading.Event()
    seen = []
    def reason(args, *, cancel_event):
        seen.append(cancel_event)
        cancel_event.set()
        return {"success": True, "text": "late answer"}
    services.reason = reason
    assert services.distill_command_error({"summary": "failure"}, cancel_event=event) == ""
    assert seen == [event]


def test_pre_cancelled_diagnostic_does_not_call_model():
    import threading
    services = object.__new__(LocalAIServices)
    event = threading.Event()
    event.set()
    services.reason = lambda *_args, **_kwargs: pytest.fail("cancelled diagnostic called model")
    assert services.distill_command_error({"summary": "failure"}, cancel_event=event) == ""


def test_command_diagnostic_deadline_cancels_cooperative_model():
    import time
    services = object.__new__(LocalAIServices)
    observed = []
    def reason(_args, *, cancel_event):
        observed.append(cancel_event.wait(2))
        return {"success": True, "text": "late answer"}
    services.reason = reason
    start = time.monotonic()
    assert services.distill_command_error({"summary": "failure"}, timeout_seconds=0.05) == ""
    assert observed == [True]
    assert time.monotonic() - start < 1.0


@pytest.mark.parametrize("timeout", [0, -1, 31, float("inf"), float("nan"), True, "1"])
def test_command_diagnostic_rejects_invalid_deadlines(timeout):
    services = object.__new__(LocalAIServices)
    services.reason = lambda *_args, **_kwargs: pytest.fail("invalid deadline called model")
    assert services.distill_command_error({"summary": "failure"}, timeout_seconds=timeout) == ""


def test_diagnostic_deadline_does_not_cancel_parent_request():
    import threading
    parent = threading.Event()
    services = object.__new__(LocalAIServices)
    services.reason = lambda _args, *, cancel_event: (
        cancel_event.wait(2) and {"success": True, "text": "late"}
    )
    assert services.distill_command_error({"summary": "failure"}, cancel_event=parent, timeout_seconds=0.05) == ""
    assert not parent.is_set()


@pytest.mark.parametrize("response", [
    {"text": "unverified"},
    {"success": False, "text": "unverified"},
    {"success": True, "summary": "not a text response"},
    {"success": True, "text": ["not a string"]},
])
def test_broker_does_not_accept_ambiguous_diagnostic(response):
    broker = object.__new__(CommandBroker)
    broker.error_distiller = lambda _payload: response
    assert broker._distill_error_with_model({"summary": "failed", "exit_code": 1}) == ""


def test_broker_accepts_validated_service_text():
    services = object.__new__(LocalAIServices)
    services.reason = lambda _args: {"success": True, "text": "Inspect dependency."}
    broker = object.__new__(CommandBroker)
    broker.error_distiller = services.distill_command_error
    assert broker._distill_error_with_model({"summary": "failed", "exit_code": 1}) == "Inspect dependency."


def test_broker_diagnostic_forwards_cancellation_and_discards_late_text():
    import threading
    event = threading.Event()
    seen = []
    broker = object.__new__(CommandBroker)
    def distill(_payload, *, cancel_event):
        seen.append(cancel_event)
        cancel_event.set()
        return "late answer"
    broker.error_distiller = distill
    assert broker._distill_error_with_model({"summary": "failed", "exit_code": 1}, cancel_event=event) == ""
    assert seen == [event]


def test_application_does_not_enable_automatic_diagnostic_without_opt_in(tmp_path, monkeypatch):
    import json
    from local_ai_hub.app import LocalAIApp
    from test_work_orchestrator import init_repo

    root = init_repo(tmp_path)
    (root / "a.txt").write_text("new\n", encoding="utf-8")
    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[security]\nallowed_roots = ["
        + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        assert app.config["features"]["local_diagnostic_dispatch"] is False
        calls = []
        monkeypatch.setattr(app.services, "reason", lambda args: calls.append(args) or {"success": True, "text": "invented"})
        result = app.commands.run("git diff --exit-code", str(root), force=True)
        assert result["success"] is False
        assert result["error_distillation_source"] == "deterministic"
        assert calls == []
        assert callable(app.commands.error_distiller)
    finally:
        app.close()


def test_opt_in_failure_preview_produces_bounded_context_artifact(tmp_path):
    import json
    from local_ai_hub.app import LocalAIApp

    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[features]\nlocal_diagnostic_dispatch = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        result = app.commands._compact(
            {"success": False, "exit_code": 1, "stdout": "", "stderr": "unstructured failure"}, "git diff"
        )
        assert result["artifact_id"]
        artifact = app.artifacts.get(result["artifact_id"], max_chars=2000)
        assert artifact["success"] is True
        assert artifact["kind"] == "local_diagnostic_context"
        assert artifact["text"] == result["preview"][:800]
        assert len(artifact["text"]) <= 800
        assert callable(app.commands.error_distiller)
    finally:
        app.close()


def test_full_output_and_bounded_diagnostic_artifacts_are_distinct(tmp_path):
    import json
    from local_ai_hub.app import LocalAIApp

    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[features]\n"
        + "local_diagnostic_dispatch = true\ndiagnostic_artifacts = true\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        failure = {"success": False, "exit_code": 1, "stdout": "",
                   "stderr": "error " + "x" * (app.commands.inline_chars + 1000)}
        result = app.commands._compact(failure, "git diff")
        full_id = result["output_artifact_id"]
        diagnostic_id = result["diagnostic_context_artifact_id"]
        assert full_id != diagnostic_id
        context = app.artifacts.get(diagnostic_id, max_chars=2000)
        assert context["kind"] == "local_diagnostic_context"
        assert context["text"] == result["preview"][:800]
        assert len(context["text"]) <= 800
        for extra in ({"success": True}, {"success": False, "cancelled": True}):
            other = app.commands._compact({**failure, **extra}, "git diff")
            assert "diagnostic_context_artifact_id" not in other
        sensitive = app.commands._compact({"success": False, "exit_code": 1, "stdout": "",
                                          "stderr": "password=example-secret-123"}, "git diff")
        assert sensitive["local_diagnostic_status"] == "skipped_sensitive"
        assert "diagnostic_context_artifact_id" not in sensitive
        assert app.artifacts.get(sensitive["artifact_id"])["kind"] == "command_diagnostic"
    finally:
        app.close()


@pytest.mark.parametrize("sensitive", ["password=example-secret-123", "Authorization: Bearer example-secret-token"])
def test_sensitive_preview_does_not_create_local_diagnostic_artifact(tmp_path, sensitive):
    import json
    from local_ai_hub.app import LocalAIApp

    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[features]\n"
        + "local_diagnostic_dispatch = true\ndiagnostic_artifacts = false\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        for stderr in (sensitive, sensitive + ("x" * (app.commands.inline_chars + 100))):
            result = app.commands._compact({"success": False, "exit_code": 1, "stdout": "", "stderr": stderr}, "git diff")
            assert "diagnostic_context_artifact_id" not in result
            assert "artifact_id" not in result
            assert result["local_diagnostic_status"] == "skipped_sensitive"
    finally:
        app.close()


def test_diagnostic_context_checks_fresh_root_and_artifact_content(tmp_path):
    import json
    from local_ai_hub.app import LocalAIApp
    from test_work_orchestrator import init_repo

    root = init_repo(tmp_path)
    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[features]\nlocal_diagnostic_dispatch = true\n",
        encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        compacted = app.commands._compact({
            "success": False, "exit_code": 1, "stdout": "", "stderr": "unstructured failure",
            "cache_hit": False, "coalesced": False, "repo_state": {"root": str(root)},
        }, "git diff")
        evidence = app.commands._local_diagnostic_context(compacted, str(root))
        assert evidence == {"artifact_id": compacted["diagnostic_context_artifact_id"],
                            "summary": compacted["preview"][:800]}
        for changes in ({"cache_hit": True}, {"coalesced": True}, {"timed_out": True},
                        {"cancelled": True}, {"outcome_unknown": True}, {"exit_code": None},
                        {"in_progress": True}, {"aborted_interactive": True},
                        {"log_callback_delivery_unconfirmed": True}, {"budget_accounting_unavailable": True},
                        {"preview": "forged"}, {"diagnostic_context_artifact_id": "missing"}):
            assert app.commands._local_diagnostic_context({**compacted, **changes}, str(root)) is None
        assert app.commands._local_diagnostic_context(compacted, str(tmp_path)) is None
        for sensitive in ("password=example-secret-123", "Authorization: Bearer example-secret-token"):
            artifact_id = app.artifacts.put(sensitive, kind="local_diagnostic_context")
            candidate = {**compacted, "preview": sensitive, "diagnostic_context_artifact_id": artifact_id}
            assert app.commands._local_diagnostic_context(candidate, str(root)) is None
    finally:
        app.close()


def test_opt_in_fresh_command_dispatches_bounded_local_diagnostic(tmp_path, monkeypatch):
    import json
    from local_ai_hub.app import LocalAIApp
    from test_work_orchestrator import init_repo

    root = init_repo(tmp_path)
    (root / "a.txt").write_text("new\n", encoding="utf-8")
    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[features]\nlocal_diagnostic_dispatch = true"
        + "\n[security]\nallowed_roots = [" + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        seen = []
        def reason(args, *, cancel_event):
            seen.append((args, cancel_event))
            return {"success": True, "text": "Review the changed file."}
        monkeypatch.setattr(app.services, "reason", reason)
        result = app.commands.run("git diff --exit-code", str(root), force=True)
        assert result["success"] is False
        assert result["error_distillation_source"] == "deterministic"
        assert result["local_diagnostic"]["text"] == "Review the changed file."
        assert result["local_diagnostic"]["artifact_id"] == result["diagnostic_context_artifact_id"]
        assert result["local_diagnostic"]["advisory"] is True
        assert result["local_diagnostic_status"] == "completed"
        assert len(seen) == 1
        assert seen[0][0]["context"] == result["preview"][:800]
        seen.clear()
        def failed_reason(args, *, cancel_event):
            seen.append(args)
            return {"success": False, "text": "do not use"}
        monkeypatch.setattr(app.services, "reason", failed_reason)
        failed = app.commands.run("git diff --exit-code", str(root), force=True)
        assert failed["success"] is False
        assert failed["error_distillation_source"] == "deterministic"
        assert "local_diagnostic" not in failed
        assert failed["local_diagnostic_status"] == "unavailable"
        assert len(seen) == 1
        import threading
        parent_cancel = threading.Event()
        def cancelled_reason(_args, *, cancel_event):
            parent_cancel.set()
            assert cancel_event.is_set()
            return {"success": True, "text": "late advice"}
        monkeypatch.setattr(app.services, "reason", cancelled_reason)
        cancelled = app.commands.run("git diff --exit-code", str(root), force=True,
                                     request_cancel_event=parent_cancel)
        assert "local_diagnostic" not in cancelled
        assert cancelled["local_diagnostic_status"] == "cancelled"
    finally:
        app.close()


def test_opt_in_diagnostic_timeout_is_visible(tmp_path, monkeypatch):
    import json
    from local_ai_hub.app import LocalAIApp
    from test_work_orchestrator import init_repo

    root = init_repo(tmp_path)
    (root / "a.txt").write_text("new\n", encoding="utf-8")
    config = tmp_path / "hub.toml"
    config.write_text(
        "[server]\nstate_dir = " + json.dumps(str(tmp_path / "state"))
        + "\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
        + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
        + "\n[preprocessing]\nenabled = false\n[features]\nlocal_diagnostic_dispatch = true"
        + "\n[security]\nallowed_roots = [" + json.dumps(str(root)) + "]\n", encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    try:
        def slow_reason(_args, *, cancel_event):
            assert cancel_event.wait(15)
            return {"success": True, "text": "late advice"}
        monkeypatch.setattr(app.services, "reason", slow_reason)
        result = app.commands.run("git diff --exit-code", str(root), force=True)
        assert result["success"] is False
        assert result["error_distillation_source"] == "deterministic"
        assert result["local_diagnostic_status"] == "timed_out"
        assert "local_diagnostic" not in result
    finally:
        app.close()


