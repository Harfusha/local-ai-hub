from __future__ import annotations

import ast
from pathlib import Path

from local_ai_hub.telemetry import TelemetryStore
from tools.surface_inventory import _extract_http


def test_clean_telemetry_event_drops_prompt_source_and_path_fields():
    prompt = "PROMPT-SENSITIVE-SENTINEL"
    source = "SOURCE-SENSITIVE-SENTINEL"
    path = r"C:\private\project\secret.py"

    event = TelemetryStore._clean_event(
        {
            "event_type": "http",
            "action": "model.generate",
            "prompt": prompt,
            "source_text": source,
            "path": path,
        }
    )

    assert prompt not in repr(event)
    assert source not in repr(event)
    assert path not in repr(event)
    assert "prompt" not in event
    assert "source_text" not in event
    assert "path" not in event


def test_error_telemetry_redacts_prompt_source_and_absolute_path():
    prompt = "PROMPT-SENSITIVE-SENTINEL"
    source = "SOURCE-SENSITIVE-SENTINEL"
    path = r"C:\private\project\secret.py"
    captured = []
    store = object.__new__(TelemetryStore)
    store.enabled = True
    store._enqueue = lambda kind, payload: captured.append((kind, payload)) or True

    store.record_error(
        "ollama",
        "model_attempt",
        RuntimeError(f'provider rejected request from {path}; prompt="{prompt}" source_text="{source}"'),
    )

    error_payload = next(payload for kind, payload in captured if kind == "error")
    safe_message = error_payload["safe_message"]
    assert prompt not in safe_message
    assert source not in safe_message
    assert path not in safe_message


def test_http_telemetry_preserves_static_routes_but_redacts_dynamic_paths():
    route = "/api/agent-state/tasks"
    dynamic_route = f"{route}/sensitive-task-id"

    started = TelemetryStore._clean_event({"event_type": "request_start", "action": route})
    completed = TelemetryStore._clean_event({"event_type": "http", "action": route})
    dynamic = TelemetryStore._clean_event({"event_type": "http", "action": dynamic_route})

    assert started["action"] == route
    assert completed["action"] == route
    assert dynamic["action"] == "<path>"


def test_http_telemetry_preserves_every_static_get_route():
    root = Path(__file__).resolve().parents[1]
    source = root / "src" / "local_ai_hub" / "http_server.py"
    routes = _extract_http(ast.parse(source.read_text(encoding="utf-8")), "http_server.py")
    static_routes = {
        route["path"] for route in routes
        if route["method"] == "GET" and route.get("match") == "exact"
    }

    redacted = {
        route for route in static_routes
        if TelemetryStore._clean_event({"event_type": "http", "action": route})["action"] != route
    }

    assert not redacted
