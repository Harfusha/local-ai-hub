"""OpenAI-compatible transport helpers for the managed OpenCode gateway."""

from __future__ import annotations

import json
import math
import time
import uuid
from datetime import datetime
from typing import Any, Iterator


_REQUEST_KEYS = frozenset({
    "model", "messages", "stream", "max_tokens", "max_completion_tokens",
    "temperature", "top_p", "top_k", "stop", "seed", "tools",
    "tool_choice", "parallel_tool_calls", "response_format", "stream_options",
})
_ROLES = frozenset({"system", "developer", "user", "assistant", "tool"})
_MAX_MESSAGES = 512
_MAX_TOOLS = 128
_MAX_OUTPUT_TOKENS = 32768


def _bounded_number(value: Any, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"invalid {name}")
    if value < minimum or value > maximum:
        raise ValueError(f"invalid {name}")
    return float(value)


def _validate_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list) or not 1 <= len(messages) <= _MAX_MESSAGES:
        raise ValueError("invalid messages")
    result = []
    for message in messages:
        if not isinstance(message, dict) or set(message) - {"role", "content", "name", "tool_call_id", "tool_calls"}:
            raise ValueError("invalid message")
        if message.get("role") not in _ROLES:
            raise ValueError("invalid message role")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("only text message content is supported")
        if "name" in message and (not isinstance(message["name"], str) or len(message["name"]) > 128):
            raise ValueError("invalid message name")
        if "tool_call_id" in message and (not isinstance(message["tool_call_id"], str) or len(message["tool_call_id"]) > 256):
            raise ValueError("invalid tool call id")
        if "tool_calls" in message and not isinstance(message["tool_calls"], list):
            raise ValueError("invalid assistant tool calls")
        result.append(dict(message))
    return result


def _ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate OpenAI tool-call history to Ollama's native argument objects."""
    normalized: list[dict[str, Any]] = []
    for message in messages:
        current = dict(message)
        calls = current.get("tool_calls")
        if calls is not None:
            normalized_calls = []
            for call in calls:
                if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                    raise ValueError("invalid assistant tool call")
                function = dict(call["function"])
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError as exc:
                        raise ValueError("invalid assistant tool call arguments") from exc
                if not isinstance(arguments, dict):
                    raise ValueError("assistant tool call arguments must be an object")
                function["arguments"] = arguments
                normalized_call = dict(call)
                normalized_call["function"] = function
                normalized_calls.append(normalized_call)
            current["tool_calls"] = normalized_calls
        normalized.append(current)
    return normalized


def _validate_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list) or len(tools) > _MAX_TOOLS:
        raise ValueError("invalid tools")
    for item in tools:
        if (not isinstance(item, dict) or set(item) != {"type", "function"} or item.get("type") != "function"
                or not isinstance(item.get("function"), dict)):
            raise ValueError("invalid tool definition")
        function = item["function"]
        if (not isinstance(function.get("name"), str) or not function["name"] or len(function["name"]) > 128
                or set(function) - {"name", "description", "parameters", "strict"}
                or ("description" in function and not isinstance(function["description"], str))
                or ("parameters" in function and not isinstance(function["parameters"], dict))
                or ("strict" in function and not isinstance(function["strict"], bool))):
            raise ValueError("invalid function schema")
    return [dict(item) for item in tools]


def to_ollama_chat(request: Any, allowed_models: set[str] | frozenset[str]) -> tuple[dict[str, Any], bool]:
    """Validate an OpenAI chat request and translate it to queued Ollama chat."""
    if not isinstance(request, dict) or set(request) - _REQUEST_KEYS:
        raise ValueError("invalid or unsupported chat request fields")
    model = request.get("model")
    if not isinstance(model, str) or model not in allowed_models:
        raise ValueError("model is not an installed, configured local OpenCode model")
    messages = _ollama_messages(_validate_messages(request.get("messages")))
    wants_stream = request.get("stream", False)
    if not isinstance(wants_stream, bool):
        raise ValueError("invalid stream flag")

    out: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    options: dict[str, Any] = {}
    max_tokens = request.get("max_completion_tokens", request.get("max_tokens"))
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= _MAX_OUTPUT_TOKENS:
            raise ValueError("invalid output token limit")
        options["num_predict"] = max_tokens
    for key, low, high in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0)):
        if key in request:
            options[key] = _bounded_number(request[key], name=key, minimum=low, maximum=high)
    if "top_k" in request:
        value = request["top_k"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 128:
            raise ValueError("invalid top_k")
        options["top_k"] = value
    if "seed" in request:
        value = request["seed"]
        if isinstance(value, bool) or not isinstance(value, int) or not -(2**31) <= value < 2**31:
            raise ValueError("invalid seed")
        options["seed"] = value
    if "stop" in request:
        stop = request["stop"]
        if isinstance(stop, str):
            stop = [stop]
        if (not isinstance(stop, list) or len(stop) > 16
                or any(not isinstance(item, str) or len(item) > 256 for item in stop)):
            raise ValueError("invalid stop sequences")
        options["stop"] = stop
    if options:
        out["options"] = options
    if "tools" in request:
        out["tools"] = _validate_tools(request["tools"])
    if "tool_choice" in request and request["tool_choice"] not in ("auto", "none"):
        raise ValueError("forced tool choice is unsupported")
    if request.get("tool_choice") == "none":
        out.pop("tools", None)
    if "parallel_tool_calls" in request and not isinstance(request["parallel_tool_calls"], bool):
        raise ValueError("invalid parallel_tool_calls")
    if "response_format" in request:
        response_format = request["response_format"]
        if response_format == {"type": "json_object"}:
            out["format"] = "json"
        elif isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            schema = response_format.get("json_schema")
            if not isinstance(schema, dict) or not isinstance(schema.get("schema"), dict):
                raise ValueError("invalid JSON schema response format")
            out["format"] = schema["schema"]
        else:
            raise ValueError("unsupported response format")
    if "stream_options" in request:
        stream_options = request["stream_options"]
        if not isinstance(stream_options, dict) or set(stream_options) - {"include_usage"}:
            raise ValueError("unsupported stream options")
        if "include_usage" in stream_options and not isinstance(stream_options["include_usage"], bool):
            raise ValueError("invalid stream usage option")
    return out, wants_stream


def to_openai_completion(result: Any, *, request_id: str) -> dict[str, Any]:
    """Convert a successful non-streaming Ollama chat result to OpenAI shape."""
    if (not isinstance(result, dict) or result.get("error") or result.get("done") is not True
            or not isinstance(request_id, str) or not request_id or len(request_id) > 128):
        raise ValueError("invalid Hub inference result")
    model = result.get("model")
    message = result.get("message")
    if not isinstance(model, str) or not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("invalid Hub assistant result")
    content = message.get("content", "")
    if not isinstance(content, str):
        raise ValueError("invalid Hub assistant content")
    tool_calls = []
    raw_calls = message.get("tool_calls", [])
    if not isinstance(raw_calls, list) or len(raw_calls) > _MAX_TOOLS:
        raise ValueError("invalid Hub tool call result")
    for index, item in enumerate(raw_calls):
        function = item.get("function") if isinstance(item, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ValueError("invalid Hub tool call function")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid Hub tool call arguments") from exc
            arguments = parsed
        if not isinstance(arguments, dict):
            raise ValueError("invalid Hub tool call arguments")
        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex}", "type": "function", "index": index,
            "function": {"name": function["name"], "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))},
        })
    created_at = result.get("created_at")
    created = int(time.time())
    if isinstance(created_at, str):
        try:
            created = int(datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    prompt_tokens = result.get("prompt_eval_count", 0)
    completion_tokens = result.get("eval_count", 0)
    for count in (prompt_tokens, completion_tokens):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("invalid Hub usage counts")
    reason = "tool_calls" if tool_calls else "length" if result.get("done_reason") == "length" else "stop"
    assistant = {"role": "assistant", "content": content or None}
    if tool_calls:
        assistant["tool_calls"] = [{key: value for key, value in call.items() if key != "index"} for call in tool_calls]
    return {
        "id": request_id, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": assistant, "finish_reason": reason}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


def openai_sse(completion: dict[str, Any], *, include_usage: bool = False) -> Iterator[bytes]:
    """Emit an OpenAI-compatible SSE response after a complete Hub result."""
    choice = completion["choices"][0]
    message = choice["message"]
    common = {"id": completion["id"], "object": "chat.completion.chunk", "created": completion["created"],
              "model": completion["model"], "choices": [{"index": 0}]}

    def frame(data: dict[str, Any] | str) -> bytes:
        payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"data: {payload}\n\n".encode("utf-8")

    yield frame({**common, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
    content = message.get("content")
    if isinstance(content, str) and content:
        for offset in range(0, len(content), 1024):
            yield frame({**common, "choices": [{"index": 0, "delta": {"content": content[offset:offset + 1024]}, "finish_reason": None}]})
    for index, call in enumerate(message.get("tool_calls", [])):
        yield frame({**common, "choices": [{"index": 0, "delta": {
            "tool_calls": [{"index": index, "id": call["id"], "type": "function", "function": call["function"]}],
        }, "finish_reason": None}]})
    yield frame({**common, "choices": [{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]})
    if include_usage:
        yield frame({**common, "choices": [], "usage": completion["usage"]})
    yield frame("[DONE]")
