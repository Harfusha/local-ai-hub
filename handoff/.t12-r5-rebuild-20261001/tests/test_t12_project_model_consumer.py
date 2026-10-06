from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from local_ai_hub.ollama import OllamaRuntime
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices, generation_cache_key
from local_ai_hub.trace_context import reset_observer, set_observer


def test_project_model_profile_and_prefix_are_request_scoped_for_local_generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True},
            "hardware": {"profile": "balanced"},
            "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
            "models": {"general": "qwen2.5-coder:7b"},
        }
    )
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(runtime, "request", lambda endpoint, payload=None, **_kw: calls.append((endpoint, payload)) or {"ok": True})

    runtime.generate(
        "qwen2.5-coder:7b",
        "task",
        system="Base system policy.",
        role="general",
        project_settings=SimpleNamespace(
            model_profile="high",
            system_prompt_prefix="Repository alpha context.",
        ),
    )
    runtime.generate(
        "qwen2.5-coder:7b",
        "repo beta task",
        system="Base system policy.",
        role="general",
        project_settings=SimpleNamespace(
            model_profile="balanced",
            system_prompt_prefix="Repository beta context.",
        ),
    )
    runtime.generate("qwen2.5-coder:7b", "no project task", system="Base system policy.", role="general")

    first = calls[0][1]
    second = calls[1][1]
    third = calls[2][1]
    assert first["model"] == "qwen3.5:9b"
    assert first["system"].startswith("Base system policy.")
    assert "Untrusted project context (subordinate to system policy):\nRepository alpha context." in first["system"]
    assert second["model"] == "qwen2.5-coder:7b"
    assert "Repository beta context." in second["system"]
    assert "Repository alpha context" not in second["system"]
    assert "Repository alpha context" not in third["system"]
    assert "Repository beta context" not in third["system"]


def test_project_prompt_prefix_is_attached_to_chat_system_message_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OllamaRuntime(
        {
            "server": {"state_dir": str(tmp_path), "ollama_url": "http://127.0.0.1:11434"},
            "ollama": {"enabled": True},
            "models": {"general": "local-model"},
        }
    )
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(runtime, "request", lambda endpoint, payload=None, **_kw: calls.append((endpoint, payload)) or {"ok": True})

    runtime.chat(
        "local-model",
        [{"role": "system", "content": "System policy."}, {"role": "user", "content": "Question."}],
        role="general",
        project_settings=SimpleNamespace(model_profile="balanced", system_prompt_prefix="Project context."),
    )

    endpoint, payload = calls[0]
    assert endpoint == "/api/chat"
    assert payload["messages"][0]["content"].startswith("System policy.")
    assert "Project context." in payload["messages"][0]["content"]
    assert "Project context." not in payload["messages"][1]["content"]


class _FakeTaskRuntime:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def is_online(self) -> bool:
        return True

    def request_stream(self, endpoint, payload, on_chunk, **_kwargs):
        assert endpoint == "/api/generate"
        self.payloads.append(payload)
        on_chunk("answer")
        return {"response": "answer", "done": True}


class _InlineScheduler:
    def status(self) -> dict:
        return {}

    def submit(self, _model, _tenant, _source, work, **_kwargs):
        return work()


class _NoopSemanticCache:
    def get(self, _scope, _query):
        return None, 0.0

    def set(self, _scope, _query, _value):
        return None


class _RecordingObserver:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def model_request(self, payload) -> None:
        self.requests.append(payload)

    def output_delta(self, _text: str) -> None:
        return None


def _task_services(tmp_path: Path) -> LocalAIServices:
    config = {
        "server": {"state_dir": str(tmp_path / "hub-state"), "request_timeout_seconds": 5},
        "models": {
            "background_code": "qwen2.5-coder:1.5b",
            "fast_code": "qwen2.5-coder:3b",
            "heavy_code": "qwen2.5-coder:7b",
            "reasoning": "qwen3.5:9b",
            "general": "qwen2.5-coder:7b",
            "vision": "qwen3.5:9b",
        },
        "hardware": {"profile": "balanced"},
        "_hardware": {"profile": "balanced", "ram": {"total_gb": 32}, "gpus": []},
        "routing": {"prefer_resident_model": False},
        "cache": {"generation": True, "embeddings": False},
        "resilience": {"model_fallback_enabled": False, "serve_stale_on_error": False},
        "token_saving": {"compact_responses": False},
    }
    runtime = _FakeTaskRuntime()
    service = LocalAIServices(
        config=config,
        runtime=runtime,
        scheduler=_InlineScheduler(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=RepositoryTools(config),
    )
    service.semantic_cache = _NoopSemanticCache()
    service.runtime = runtime
    return service


def test_local_task_resolves_project_model_and_prompt_without_cross_repo_cache_or_trace_leak(
    tmp_path: Path,
) -> None:
    pytest.importorskip("local_ai_hub.project_config")
    service = _task_services(tmp_path)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    project_toml = 'model_profile = "high"\nsystem_prompt_prefix = "Repository-only guidance alpha."\n'
    (repo_a / ".local-ai.toml").write_text(project_toml, encoding="utf-8")
    (repo_b / ".local-ai.toml").write_text(project_toml, encoding="utf-8")
    service.repo_tools.git_snapshot = lambda root: SimpleNamespace(
        common_dir=str(root), repository_revision="same-revision",
    )
    project_a, _digest_a, namespace_a, revision_a = service._resolve_local_task_project(repo_a)
    project_b, _digest_b, namespace_b, revision_b = service._resolve_local_task_project(repo_b)
    assert namespace_a == project_a.coordination_id
    assert namespace_b == project_b.coordination_id
    assert namespace_a != namespace_b
    assert revision_a == revision_b == "same-revision"
    observer = _RecordingObserver()
    observer_token = set_observer(observer)
    try:
        for root in (repo_a, repo_b):
            result = service.delegate(
                {"root": str(root), "task": "Explain this project briefly.", "task_type": "general", "complexity": "fast"},
                tenant="test",
            )
            assert result["success"] is True, result
            assert result["route"]["model"] == "qwen3.5:9b"
    finally:
        reset_observer(observer_token)

    runtime = service.runtime
    assert len(runtime.payloads) == 2
    assert all(payload["model"] == "qwen3.5:9b" for payload in runtime.payloads)
    assert all("Repository-only guidance alpha." in payload["system"] for payload in runtime.payloads)
    assert len(observer.requests) == 2
    assert all("Repository-only guidance alpha." not in str(payload) for payload in observer.requests)
    assert all("Repository-only guidance alpha." not in repr(call) for call in service.telemetry.method_calls)


@pytest.mark.parametrize("config_text", [None, 'model_profile = "unsupported"\n'])
def test_local_task_project_context_falls_back_for_missing_or_invalid_config(
    tmp_path: Path,
    config_text: str | None,
) -> None:
    project_config = pytest.importorskip("local_ai_hub.project_config")
    service = _task_services(tmp_path)
    root = tmp_path / ("missing-config" if config_text is None else "invalid-config")
    root.mkdir()
    if config_text is not None:
        (root / ".local-ai.toml").write_text(config_text, encoding="utf-8")
    service.repo_tools.git_snapshot = lambda _root: SimpleNamespace(common_dir=None, repository_revision="")

    context, digest, namespace, revision = service._resolve_local_task_project(root)

    assert isinstance(context, project_config.ProjectContext)
    assert context.settings.model_profile == "balanced"
    assert context.settings.system_prompt_prefix is None
    assert digest == context.config_digest
    assert namespace == (context.coordination_id or "")
    assert revision == ""
    result = service.delegate(
        {"root": str(root), "task": "Explain this project.", "task_type": "general", "complexity": "fast"},
        tenant="test",
    )
    assert result["success"] is True, result
    assert result["route"]["model"] == "qwen2.5-coder:7b"
    if config_text is not None:
        assert context.resolution.error_codes
        assert result["warnings"]
        assert "defaults used" in result["warnings"][0].lower()
        assert all(code in result["warnings"][0] for code in context.resolution.error_codes)
        assert str(root) not in result["warnings"][0]
        assert "Project-only" not in result["warnings"][0]
    else:
        assert not result.get("warnings")


def test_reason_and_review_use_project_profile_through_delegate(tmp_path: Path) -> None:
    pytest.importorskip("local_ai_hub.project_config")
    service = _task_services(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    (root / ".local-ai.toml").write_text(
        'model_profile = "max"\nsystem_prompt_prefix = "Project-only rule."\n',
        encoding="utf-8",
    )
    service.repo_tools.git_snapshot = lambda _root: SimpleNamespace(common_dir=str(root), repository_revision="rev-1")

    reason = service.reason(
        {"root": str(root), "problem": "Explain the issue.", "complexity": "heavy"},
        tenant="test",
    )
    review = service.review(
        {"root": str(root), "instructions": "Review this code.", "code": "print(1)", "complexity": "heavy"},
        tenant="test",
    )
    batch = service.batch_delegate(
        {
            "root": str(root),
            "tasks": [{"task": "Explain this project.", "task_type": "general", "complexity": "fast"}],
        },
        tenant="test",
    )

    assert reason["route"]["model"] == "qwen3.5:9b"
    assert review["route"]["model"] == "qwen3.5:9b"
    assert batch["success"] is True, batch
    assert batch["results"][0]["route"]["model"] == "qwen3.5:9b"
    assert len(service.runtime.payloads) == 3
    assert all("Project-only rule." in payload["system"] for payload in service.runtime.payloads)


def test_local_task_project_profiles_and_prefixes_are_isolated_concurrently(tmp_path: Path) -> None:
    pytest.importorskip("local_ai_hub.project_config")
    service = _task_services(tmp_path)
    repo_a = tmp_path / "concurrent-a"
    repo_b = tmp_path / "concurrent-b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / ".local-ai.toml").write_text(
        'model_profile = "high"\nsystem_prompt_prefix = "Concurrent alpha only."\n',
        encoding="utf-8",
    )
    (repo_b / ".local-ai.toml").write_text(
        'model_profile = "balanced"\nsystem_prompt_prefix = "Concurrent beta only."\n',
        encoding="utf-8",
    )
    service.repo_tools.git_snapshot = lambda root: SimpleNamespace(
        common_dir=str(root), repository_revision="same-revision",
    )
    barrier = threading.Barrier(2)
    payloads: list[dict] = []
    payload_lock = threading.Lock()

    def request_stream(endpoint, payload, on_chunk, **_kwargs):
        assert endpoint == "/api/generate"
        barrier.wait(timeout=3)
        with payload_lock:
            payloads.append(dict(payload))
        on_chunk("answer")
        return {"response": "answer", "done": True}

    service.runtime.request_stream = request_stream

    def invoke(root: Path, tenant: str) -> dict:
        return service.delegate(
            {"root": str(root), "task": "Explain this project briefly.", "task_type": "general", "complexity": "fast"},
            tenant=tenant,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(invoke, repo_a, "concurrent-a")
        future_b = pool.submit(invoke, repo_b, "concurrent-b")
        result_a = future_a.result(timeout=5)
        result_b = future_b.result(timeout=5)

    assert result_a["success"] is True, result_a
    assert result_b["success"] is True, result_b
    assert result_a["route"]["model"] == "qwen3.5:9b"
    assert result_b["route"]["model"] == "qwen2.5-coder:7b"
    assert len(payloads) == 2
    systems = [str(payload["system"]) for payload in payloads]
    assert sum("Concurrent alpha only." in system for system in systems) == 1
    assert sum("Concurrent beta only." in system for system in systems) == 1
    assert all(not ("Concurrent alpha only." in system and "Concurrent beta only." in system) for system in systems)


def test_batch_delegate_inherits_parent_root_for_items_without_project_root(tmp_path: Path, monkeypatch) -> None:
    service = _task_services(tmp_path)
    parent_root = str(tmp_path / "parent")
    explicit_root = str(tmp_path / "item")
    captured: list[dict] = []
    monkeypatch.setattr(service, "delegate", lambda item, _tenant: captured.append(dict(item)) or {"success": True})

    result = service.batch_delegate(
        {
            "root": parent_root,
            "cwd": "ignored-parent-cwd",
            "tasks": [{"task": "one"}, {"task": "two", "root": explicit_root}],
        },
        tenant="test",
    )

    assert result["success"] is True, result
    assert captured[0]["root"] == parent_root
    assert captured[1]["root"] == explicit_root


def test_generation_cache_key_isolated_by_project_digest_and_repository_revision() -> None:
    common = {
        "model": "local-model",
        "prompt": "task",
        "system": "system",
        "options": {},
        "think": None,
        "execution": "local",
    }
    baseline = generation_cache_key(**common, project_config_digest="digest-a", project_namespace="repo-a", repository_revision="rev-1")

    assert baseline != generation_cache_key(
        **common, project_config_digest="digest-b", project_namespace="repo-a", repository_revision="rev-1"
    )
    assert baseline != generation_cache_key(
        **common, project_config_digest="digest-a", project_namespace="repo-a", repository_revision="rev-2"
    )
