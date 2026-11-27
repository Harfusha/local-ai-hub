from __future__ import annotations

import json

import pytest

from local_ai_hub.opencode_gateway import openai_sse, to_ollama_chat, to_openai_completion


def test_openai_request_maps_to_hub_queued_ollama_chat_without_streaming_upstream():
    request = {
        "model": "gemma4:12b-128k",
        "messages": [
            {"role": "system", "content": "Follow repository instructions."},
            {"role": "user", "content": "Fix the bug."},
        ],
        "stream": True,
        "max_tokens": 321,
        "temperature": 0.2,
        "top_p": 0.8,
        "stop": ["<END>"],
        "tools": [{
            "type": "function",
            "function": {"name": "local_ai_status", "description": "Hub status", "parameters": {"type": "object"}},
        }],
    }

    translated, wants_stream = to_ollama_chat(request, {"gemma4:12b-128k"})

    assert wants_stream is True
    assert translated == {
        "model": "gemma4:12b-128k",
        "messages": request["messages"],
        "stream": False,
        "tools": request["tools"],
        "options": {"num_predict": 321, "temperature": 0.2, "top_p": 0.8, "stop": ["<END>"]},
    }


def test_openai_tool_call_history_normalizes_arguments_for_ollama():
    messages = [
        {"role": "user", "content": "Check Hub status."},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_123", "type": "function",
            "function": {"name": "local_ai_status", "arguments": '{"detail":"brief"}'},
        }]},
        {"role": "tool", "tool_call_id": "call_123", "name": "local_ai_status", "content": "ready"},
    ]

    translated, _ = to_ollama_chat({"model": "gemma4:12b-128k", "messages": messages}, {"gemma4:12b-128k"})

    assert translated["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"detail": "brief"}
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == '{"detail":"brief"}'


def test_openai_tool_call_history_rejects_malformed_arguments():
    with pytest.raises(ValueError, match="invalid assistant tool call arguments"):
        to_ollama_chat({
            "model": "gemma4:12b-128k",
            "messages": [{"role": "assistant", "tool_calls": [{
                "function": {"name": "local_ai_status", "arguments": '{"detail":'},
            }]}],
        }, {"gemma4:12b-128k"})


def test_openai_response_and_sse_preserve_tool_call_and_usage():
    completion = to_openai_completion({
        "model": "gemma4:12b-128k",
        "created_at": "2026-11-25T10:00:00Z",
        "message": {"role": "assistant", "content": "", "tool_calls": [{
            "function": {"name": "local_ai_status", "arguments": {"detail": "brief"}},
        }]},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 42,
        "eval_count": 7,
    }, request_id="chatcmpl-test")

    assert completion["id"] == "chatcmpl-test"
    assert completion["choices"][0]["finish_reason"] == "tool_calls"
    assert completion["choices"][0]["message"]["tool_calls"][0]["function"] == {
        "name": "local_ai_status", "arguments": json.dumps({"detail": "brief"}, separators=(",", ":")),
    }
    assert completion["usage"] == {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49}

    frames = b"".join(openai_sse(completion)).decode("utf-8")
    assert '"object":"chat.completion.chunk"' in frames
    assert '"tool_calls"' in frames
    assert "data: [DONE]\n\n" in frames


def test_openai_sse_can_emit_final_usage_chunk():
    completion = {
        "id": "chatcmpl-x", "object": "chat.completion", "created": 1, "model": "local",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }
    output = list(openai_sse(completion, include_usage=True))
    assert b'"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}' in output[-2]
    assert output[-1] == b"data: [DONE]\n\n"


def test_opencode_auto_model_routes_with_authorized_repository_scope(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from local_ai_hub.http_routes_post import HTTPPostRoutesMixin
    from local_ai_hub.http_server_proxy import services_module
    from local_ai_hub.services import LocalAIServices

    root = str(tmp_path.resolve())
    config = {"models": {"general": "base-model", "opencode": "base-model"}}
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = config
    service.model_policy = SimpleNamespace(apply_payload=lambda _model, payload, **_kwargs: (payload, None))
    service.semantic_cache = SimpleNamespace(enabled=False)
    service.router = SimpleNamespace(classify=lambda *_args: {"task_type": "code", "complexity": "fast"})
    service._resolve_local_task_project = lambda *_args: (None, None, None, None)
    service.scheduled_models = []
    service._request_laya_model_route = lambda _args, route, *_rest, **_kwargs: (
        route.update(model="smart-model") or "smart"
    )
    service.runtime = SimpleNamespace(
        installed_models=lambda: ["base-model", "smart-model"],
        request=lambda _endpoint, payload, **_kwargs: {
            "model": payload["model"], "done": True,
            "message": {"role": "assistant", "content": "routed"},
        },
    )
    service.generation_cache = SimpleNamespace(
        get_or_compute=lambda _key, compute: (compute(), False, False),
    )
    service.scheduler = SimpleNamespace(
        submit=lambda model, *, execute, **_kwargs: (service.scheduled_models.append(model), execute())[1],
    )
    app = SimpleNamespace(config=config, runtime=service.runtime, services=service)
    monkeypatch.setattr(services_module, "APP", app)

    class Handler(HTTPPostRoutesMixin):
        response = None

        def _bind_repository_root_payload(self, payload):
            return payload.get("root") == root

        def _send(self, status, body, **_kwargs):
            self.response = (status, body)

    handler = Handler()
    handler._handle_post_opencode_gateway({
        "root": root,
        "model": "auto",
        "messages": [{"role": "user", "content": "Explain this repository module"}],
    })

    assert handler.response[0] == 200
    assert service.scheduled_models == ["smart-model"]


@pytest.mark.parametrize("payload", [
    {"model": "cloud/model", "messages": [{"role": "user", "content": "hi"}]},
    {"model": "gemma4:12b-128k", "messages": [{"role": "user", "content": "hi"}], "stream": "yes"},
    {"model": "gemma4:12b-128k", "messages": [{"role": "user", "content": "hi"}], "n": 2},
    {"model": "gemma4:12b-128k", "messages": [{"role": "user", "content": "hi"}], "unknown": True},
])
def test_openai_gateway_rejects_unapproved_or_ambiguous_requests(payload):
    with pytest.raises(ValueError):
        to_ollama_chat(payload, {"gemma4:12b-128k"})
