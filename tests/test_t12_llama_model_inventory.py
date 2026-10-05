from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import json
import time
import pytest

import local_ai_hub.llama_cpp as llama_cpp_module
from local_ai_hub.llama_cpp import LlamaCppRouter

_TEST_SOURCE_ROOT = Path(__file__).resolve().parents[1]
assert Path(llama_cpp_module.__file__).resolve() == _TEST_SOURCE_ROOT / "src" / "local_ai_hub" / "llama_cpp.py"


def test_loaded_inventory_lists_unmapped_served_ids_and_marks_each_endpoint_status(monkeypatch) -> None:
    first_url = "http://127.0.0.1:12438"
    second_url = "http://127.0.0.1:12439"
    router = LlamaCppRouter(
        {
            "llama_cpp": {
                "mode": "auto",
                "models": {
                    "configured-a": {"url": first_url, "served_model": "mapped-a"},
                    "configured-b": {"url": second_url, "served_model": "mapped-b"},
                },
            }
        }
    )
    queried: list[tuple[str, bool]] = []

    def model_info(url, *, force_refresh=False, strict=False, **_kwargs):
        queried.append((url, force_refresh))
        if url == second_url:
            raise TimeoutError("endpoint inventory timeout")
        return {
            "mapped-a": {"status": {"value": "loaded"}},
            "served-only-by-runner": {"status": {"value": "loaded"}},
            "cold-model": {"status": {"value": "unloaded"}},
        }

    monkeypatch.setattr(router, "_model_info", model_info)

    inventory = router.loaded_model_inventory(force_refresh=True)

    assert queried == [(first_url, True), (second_url, True)]
    assert inventory["complete"] is False
    assert "configured-b" in inventory["errors"]
    assert {row["name"] for row in inventory["models"]} == {"mapped-a", "served-only-by-runner"}
    assert all(row["endpoint_url"] == first_url for row in inventory["models"])


def test_force_fresh_model_info_ignores_cached_empty_snapshot(monkeypatch) -> None:
    url = "http://127.0.0.1:12438"
    router = LlamaCppRouter(
        {"llama_cpp": {"mode": "auto", "models": {"model": {"url": url}}}}
    )
    router._models[url] = (time.monotonic(), {})
    monkeypatch.setattr(
        llama_cpp_module,
        "_open_interruptible_response",
        lambda *_args, **_kwargs: nullcontext(object()),
    )
    monkeypatch.setattr(llama_cpp_module, "_cancel_response_on_stop", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        llama_cpp_module,
        "_read_response_body",
        lambda *_args, **_kwargs: b'{"data":[{"id":"fresh-served-id","status":{"value":"loaded"}}]}',
    )

    models = router._model_info(url, force_refresh=True, strict=True)

    assert "fresh-served-id" in models
    assert models["fresh-served-id"]["status"]["value"] == "loaded"


def test_strict_model_inventory_raises_when_deadline_expires_before_http(monkeypatch) -> None:
    url = "http://127.0.0.1:12438"
    router = LlamaCppRouter(
        {"llama_cpp": {"mode": "auto", "models": {"model": {"url": url}}}}
    )
    clock_values = iter((50.0, 51.0))
    monkeypatch.setattr(llama_cpp_module.time, "monotonic", lambda: next(clock_values))
    monkeypatch.setattr(
        llama_cpp_module,
        "_open_interruptible_response",
        lambda *_args, **_kwargs: pytest.fail("expired inventory must not start HTTP"),
    )

    with pytest.raises(TimeoutError, match="inventory deadline expired"):
        router._model_info(url, force_refresh=True, strict=True, deadline=50.5)


def test_unload_model_routes_unmapped_served_id_to_its_configured_endpoint(monkeypatch) -> None:
    url = "http://127.0.0.1:12438"
    router = LlamaCppRouter(
        {"llama_cpp": {"mode": "auto", "models": {"configured-name": {"url": url}}}}
    )
    requests = []

    def open_response(request, *_args, **_kwargs):
        requests.append((request.full_url, request.data))
        return nullcontext(object())

    monkeypatch.setattr(llama_cpp_module, "_open_interruptible_response", open_response)
    monkeypatch.setattr(llama_cpp_module, "_cancel_response_on_stop", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(llama_cpp_module, "_read_response_body", lambda *_args, **_kwargs: b'{"success":true}')

    result = router.unload_model(
        "served-only-by-runner", endpoint_url=url, deadline=time.monotonic() + 1.0,
    )

    assert result is True
    assert requests[0][0] == f"{url}/models/unload"
    assert json.loads(requests[0][1]) == {"model": "served-only-by-runner"}
