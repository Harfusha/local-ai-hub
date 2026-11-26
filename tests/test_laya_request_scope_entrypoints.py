from types import SimpleNamespace

from local_ai_hub.services import LocalAIServices


def _direct_delegate_service(root, evidence_id="ev-direct"):
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"workflow": {}}
    service.router = SimpleNamespace(
        classify=lambda *_args: {
            "task_type": "code", "complexity": "fast", "semantic_required": True,
        },
        model_for_role=lambda role: {"fast_code": "fast-model", "heavy_code": "smart-model"}[role],
    )
    service._hybrid_context = lambda *_args, **_kwargs: {
        "success": True,
        "root": str(root),
        "context": "verified repository context",
        "evidence": [{"evidence_id": evidence_id}],
    }
    canonical_root = str(root.resolve(strict=True))
    service.evidence_store = SimpleNamespace(get_many=lambda ids, **_kwargs: [
        {"success": True, "evidence_id": item, "root": canonical_root, "stale": False}
        for item in ids
    ])
    service._resolve_local_task_project = lambda *_args: (None, None, None, None)
    service._available_laya_model_route_options = lambda *_args, **_kwargs: {"fast", "smart"}
    service.delegate_calls = []
    service.delegate = lambda payload, **_kwargs: (
        service.delegate_calls.append(payload) or {"success": True}
    )
    return service


def test_direct_repo_delegate_applies_taskless_typed_model_route(tmp_path):
    service = _direct_delegate_service(tmp_path)
    evaluated = []
    service.evaluate_laya_advisory = lambda operation, **_kwargs: (
        evaluated.append(operation) or "smart"
    )

    result = service.delegate_repo({"root": str(tmp_path), "task": "implement a small change"})

    assert result["success"] is True
    assert len(evaluated) == 1
    assert evaluated[0]["action"] == "evaluate_decision"
    assert evaluated[0]["decision"]["category"] == "model_route"
    assert "task_id" not in evaluated[0]
    assert service.delegate_calls[0]["model"] == "smart-model"
    assert service.delegate_calls[0]["complexity"] == "heavy"
    assert result["laya_model_route"] == "smart"


def test_direct_repo_delegate_keeps_explicit_model_authoritative(tmp_path):
    service = _direct_delegate_service(tmp_path)
    service.evaluate_laya_advisory = lambda *_args, **_kwargs: "smart"

    service.delegate_repo({
        "root": str(tmp_path), "task": "implement a small change", "model": "operator-model",
    })

    assert service.delegate_calls[0]["model"] == "operator-model"


def test_direct_repo_delegate_does_not_send_unverified_evidence_to_laya(tmp_path):
    service = _direct_delegate_service(tmp_path)
    service.evidence_store.get_many = lambda *_args, **_kwargs: []
    evaluated = []
    service.evaluate_laya_advisory = lambda *args, **kwargs: evaluated.append(args)

    service.delegate_repo({"root": str(tmp_path), "task": "implement a small change"})

    assert evaluated == []
    assert "model" not in service.delegate_calls[0]


def _direct_proxy_service():
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"models": {"general": "general-model"}}
    service.scheduled_models = []
    service.model_policy = SimpleNamespace(
        apply_payload=lambda _model, payload, **_kwargs: (payload, None),
    )
    service.semantic_cache = SimpleNamespace(enabled=False)
    service.generation_cache = SimpleNamespace(
        get_or_compute=lambda _key, compute: (compute(), False, False),
    )
    service.scheduler = SimpleNamespace(
        submit=lambda model, *, execute, **_kwargs: (service.scheduled_models.append(model), execute())[1],
    )
    service.runtime = SimpleNamespace(
        request=lambda endpoint, payload, **_kwargs: {
            "endpoint": endpoint, "payload": payload,
        },
    )
    return service


def test_repository_scoped_chat_uses_taskless_laya_model_route(tmp_path):
    service = _direct_proxy_service()
    service.router = SimpleNamespace(classify=lambda *_args: {"task_type": "code", "complexity": "fast"})
    service._resolve_local_task_project = lambda *_args: (None, None, None, None)
    calls = []

    def advise(args, route, task, context, *, project_settings=None):
        calls.append((args, task, context, project_settings))
        route["model"] = "smart-model"
        return "smart"

    service._request_laya_model_route = advise
    result = service.proxy_request(
        "/api/chat",
        {"messages": [{"role": "user", "content": "Explain this repository module"}]},
        source="proxy:/api/chat",
        repository_root=str(tmp_path),
    )

    assert result["endpoint"] == "/api/chat"
    assert len(calls) == 1
    assert calls[0][0] == {"root": str(tmp_path)}
    assert calls[0][1] == "Explain this repository module"
    assert service.scheduled_models == ["smart-model"]
    assert result["payload"]["messages"][0]["content"] == "Explain this repository module"


def test_repository_scoped_generate_uses_taskless_laya_model_route(tmp_path):
    service = _direct_proxy_service()
    service.router = SimpleNamespace(classify=lambda *_args: {"task_type": "code", "complexity": "fast"})
    service._resolve_local_task_project = lambda *_args: (None, None, None, None)
    calls = []

    def advise(args, route, task, context, *, project_settings=None):
        calls.append((args, task, context))
        route["model"] = "smart-model"
        return "smart"

    service._request_laya_model_route = advise
    service.proxy_request(
        "/api/generate",
        {"prompt": "Explain this repository module"},
        source="proxy:/api/generate",
        repository_root=str(tmp_path),
    )

    assert calls == [({"root": str(tmp_path)}, "Explain this repository module", "")]
    assert service.scheduled_models == ["smart-model"]


def test_explicit_proxy_model_bypasses_laya_route(tmp_path):
    service = _direct_proxy_service()
    service.router = SimpleNamespace(classify=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected classify")))
    service._request_laya_model_route = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected Laya"))

    service.proxy_request(
        "/api/generate",
        {"prompt": "Explain this repository module", "model": "operator-model"},
        source="proxy:/api/generate",
        repository_root=str(tmp_path),
    )


def test_proxy_without_authorized_repository_root_bypasses_laya():
    service = _direct_proxy_service()
    service.router = SimpleNamespace(classify=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected classify")))
    service._request_laya_model_route = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected Laya"))

    service.proxy_request(
        "/api/generate", {"prompt": "Explain this repository module"}, source="proxy:/api/generate",
    )


def test_embedding_proxy_bypasses_laya_route(tmp_path):
    service = _direct_proxy_service()
    service.router = SimpleNamespace(classify=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected classify")))
    service._request_laya_model_route = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected Laya"))

    service.proxy_request(
        "/api/embed", {"input": "Explain this repository module"}, source="proxy:/api/embed",
        repository_root=str(tmp_path),
    )
