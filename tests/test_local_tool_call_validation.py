import pytest
from types import SimpleNamespace
import hashlib

from local_ai_hub.tool_agent import ToolAwareLocalAgent
from local_ai_hub.evidence import EvidenceStore


def call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


def test_local_tool_limits_cannot_exceed_bounded_contract():
    agent = ToolAwareLocalAgent({"local_tools": {"max_steps": 100, "max_tool_calls": 100}}, SimpleNamespace(), None, None)
    assert agent.max_steps == 3
    assert agent.max_calls == 6


@pytest.mark.parametrize("budget", [True, 0, -1, 4, "2"])
def test_parent_model_step_budget_rejects_invalid_values_before_dispatch(tmp_path, budget):
    agent = ToolAwareLocalAgent({}, SimpleNamespace(), None, None)
    result = agent.run("model", "worker", "task", str(tmp_path), 128, 5, max_model_steps=budget)
    assert result["success"] is False
    assert "max_model_steps" in result["error"]


@pytest.mark.parametrize("allowed", [[], "repo_search", ["repo_search", "repo_search"],
                                      ["rag_search"], [" repo_search"], [{"bad": "value"}]])
def test_parent_tool_scope_rejects_invalid_or_expanded_lists_before_dispatch(tmp_path, allowed):
    agent = ToolAwareLocalAgent({}, SimpleNamespace(), None, None)
    result = agent.run("model", "critic", "task", str(tmp_path), 128, 5, allowed_tool_names=allowed)
    assert result["success"] is False
    assert "allowed_tool_names" in result["error"]


def test_parent_model_step_budget_is_part_of_cache_identity(tmp_path):
    keys = []
    profile = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    services = SimpleNamespace(
        model_policy=SimpleNamespace(profile=lambda *a, **k: profile),
        runtime=SimpleNamespace(request=lambda *a, **k: {"capabilities": ["tools"]}, model_digest=lambda model: "a" * 64),
        repo_tools=SimpleNamespace(_root=lambda root: root),
        _repo_cache_state=lambda root: {"fingerprint": "same"},
        generation_cache=SimpleNamespace(get_or_compute=lambda key, compute: (keys.append(key) or {"success": False}, False, False)),
    )
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "same")
    agent = ToolAwareLocalAgent({}, services, preprocessor, SimpleNamespace(workspace_id=lambda root: "same"))
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, max_model_steps=2)
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, max_model_steps=3)
    assert len(keys) == 2 and keys[0] != keys[1]


def test_tool_cache_identity_binds_system_and_bootstrap_context(tmp_path):
    keys = []
    profile = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    services = SimpleNamespace(
        model_policy=SimpleNamespace(profile=lambda *a, **k: profile),
        runtime=SimpleNamespace(request=lambda *a, **k: {"capabilities": ["tools"]}, model_digest=lambda model: "a" * 64),
        repo_tools=SimpleNamespace(_root=lambda root: root),
        _repo_cache_state=lambda root: {"fingerprint": "same"},
        generation_cache=SimpleNamespace(get_or_compute=lambda key, compute: (keys.append(key) or {"success": False}, False, False)),
    )
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "same")
    agent = ToolAwareLocalAgent({}, services, preprocessor, SimpleNamespace(workspace_id=lambda root: "same"))
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, system_suffix="scope A", bootstrap={"facts": ["A"]})
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, system_suffix="scope B", bootstrap={"facts": ["A"]})
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, system_suffix="scope A", bootstrap={"facts": ["B"]})
    other = ToolAwareLocalAgent({"local_tools": {"bootstrap_deterministic_tools": False}}, services,
                                preprocessor, SimpleNamespace(workspace_id=lambda root: "same"))
    other.run("model", "worker", "task", str(tmp_path), 128, 5, system_suffix="scope A", bootstrap={"facts": ["A"]})
    services.runtime.model_digest = lambda model: "b" * 64
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, system_suffix="scope A", bootstrap={"facts": ["A"]})
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, allowed_tool_names=["repo_search"])
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, allowed_tool_names=["file_slice"])
    assert len(set(keys)) == 7


def test_parent_tool_scope_also_limits_automatic_bootstrap(tmp_path):
    called = []
    execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    def request(endpoint, payload, **kwargs):
        if endpoint == "/api/show":
            return {"capabilities": ["tools"]}
        return {"message": {"role": "assistant", "content": "done"}}
    services = SimpleNamespace(
        config={}, model_policy=SimpleNamespace(profile=lambda *a, **k: execution,
                                                apply_payload=lambda model, payload, **kwargs: (payload, execution)),
        runtime=SimpleNamespace(request=request), scheduler=SimpleNamespace(submit=lambda model, execute, **kwargs: execute()),
        repo_tools=SimpleNamespace(_root=lambda root: root), _repo_cache_state=lambda root: {"fingerprint": "same"},
        deterministic_query=lambda *args: called.append("deterministic"),
        code_query=lambda *args: called.append("code"),
    )
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "same",
                                   compact_context=lambda *args: called.append("preprocessed"))
    external = SimpleNamespace(query=lambda *args, **kwargs: called.append("external"))
    agent = ToolAwareLocalAgent({}, services, preprocessor, SimpleNamespace(workspace_id=lambda root: "same"),
                                external_tools=external)
    result = agent.run("model", "worker", "find symbol references", str(tmp_path), 128, 5,
                       allowed_tool_names=["repo_search"])
    assert result["success"] is True
    assert called == []


@pytest.mark.parametrize("digest, llama_config", [
    (None, {}),
    ("a" * 64, {"mode": "auto", "models": {"model": {"url": "http://127.0.0.1:12438"}}}),
])
def test_tool_cache_is_bypassed_when_model_identity_is_unknown(tmp_path, digest, llama_config):
    execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    requests = []
    def request(endpoint, payload, **kwargs):
        if endpoint == "/api/show":
            return {"capabilities": ["tools"]}
        requests.append(payload)
        return {"message": {"role": "assistant", "content": "done"}}
    def forbidden_cache(*args):
        raise AssertionError("unknown model identity must bypass the cache")
    services = SimpleNamespace(
        config={}, model_policy=SimpleNamespace(profile=lambda *a, **k: execution,
                                                apply_payload=lambda model, payload, **kwargs: (payload, execution)),
        runtime=SimpleNamespace(request=request, model_digest=lambda model: digest),
        scheduler=SimpleNamespace(submit=lambda model, execute, **kwargs: execute()),
        repo_tools=SimpleNamespace(_root=lambda root: root), _repo_cache_state=lambda root: {"fingerprint": "same"},
        generation_cache=SimpleNamespace(get_or_compute=forbidden_cache),
    )
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "same",
                                   compact_context=lambda *args: "")
    agent = ToolAwareLocalAgent({"local_tools": {"bootstrap_deterministic_tools": False}, "llama_cpp": llama_config}, services,
                                preprocessor, SimpleNamespace(workspace_id=lambda root: "same"))
    result = agent.run("model", "worker", "task", str(tmp_path), 128, 5)
    assert result["success"] is True and len(requests) == 1
    assert result["tool_agent_cache"]["bypass_reason"] == "model_identity_unavailable"


def test_tool_cache_identity_binds_full_profile_contract(tmp_path):
    from dataclasses import replace
    from local_ai_hub.ollama_subagents import OllamaSubagentProfile

    keys = []
    execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    services = SimpleNamespace(
        model_policy=SimpleNamespace(profile=lambda *a, **k: execution),
        runtime=SimpleNamespace(request=lambda *a, **k: {"capabilities": ["tools"]}, model_digest=lambda model: "a" * 64),
        repo_tools=SimpleNamespace(_root=lambda root: root),
        _repo_cache_state=lambda root: {"fingerprint": "same"},
        generation_cache=SimpleNamespace(get_or_compute=lambda key, compute: (keys.append(key) or {"success": False}, False, False)),
    )
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "same")
    agent = ToolAwareLocalAgent({}, services, preprocessor, SimpleNamespace(workspace_id=lambda root: "same"))
    profile = OllamaSubagentProfile(name="same", role="worker", model="model", tools=("repo_search",),
                                    max_steps=3, max_tool_calls=2, max_tokens=128, temperature=0.2)
    agent.run("model", "worker", "task", str(tmp_path), 128, 5, profile=profile)
    agent.run("model", "worker", "task", str(tmp_path), 128, 5,
              profile=replace(profile, tools=("file_slice",)))
    assert len(keys) == 2 and keys[0] != keys[1]


def test_tool_loop_uses_same_bootstrap_snapshot_as_cache_key(tmp_path):
    supplied = {"facts": ["ORIGINAL_FACT"]}
    prompts = []
    execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})

    def request(endpoint, payload, **kwargs):
        if endpoint == "/api/show":
            return {"capabilities": ["tools"]}
        prompts.append(payload["messages"])
        return {"message": {"role": "assistant", "content": "done"}}

    def get_or_compute(key, compute):
        supplied["facts"].append("LATE_MUTATION")
        return compute(), False, False

    services = SimpleNamespace(
        config={}, model_policy=SimpleNamespace(profile=lambda *a, **k: execution,
                                                apply_payload=lambda model, payload, **kwargs: (payload, execution)),
        runtime=SimpleNamespace(request=request, model_digest=lambda model: "a" * 64), scheduler=SimpleNamespace(submit=lambda model, execute, **kwargs: execute()),
        repo_tools=SimpleNamespace(_root=lambda root: root), _repo_cache_state=lambda root: {"fingerprint": "same"},
        generation_cache=SimpleNamespace(get_or_compute=get_or_compute),
    )
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "same",
                                   compact_context=lambda *args: "")
    agent = ToolAwareLocalAgent({}, services, preprocessor, SimpleNamespace(workspace_id=lambda root: "same"))
    result = agent.run("model", "worker", "task", str(tmp_path), 128, 5, bootstrap=supplied)
    assert result["success"] is True
    assert "ORIGINAL_FACT" in str(prompts[0])
    assert "LATE_MUTATION" not in str(prompts[0])


def test_valid_tool_call_accepts_native_and_json_arguments():
    tools = ToolAwareLocalAgent._tools_for_role("critic")
    assert ToolAwareLocalAgent._validated_call(call("repo_search", '{"query":"name","top_k":3}'), tools) == ("repo_search", {"query": "name", "top_k": 3})


@pytest.mark.parametrize("value", [
    None,
    call("rag_search", {"query": "x"}),
    call("repo_search", "{bad"),
    call("repo_search", {"query": "x", "top_k": True}),
    call("repo_search", {"query": "x", "top_k": 100}),
    call("repo_search", {"query": "x", "root": "other"}),
    call("repo_search", {"query": "x\x00y"}),
    call("repo_search", {}),
])
def test_invalid_or_unadvertised_calls_are_rejected(value):
    with pytest.raises(ValueError):
        ToolAwareLocalAgent._validated_call(value, ToolAwareLocalAgent._tools_for_role("critic"))


@pytest.mark.parametrize("stage,expected_calls", [("tool_call", 0), ("direct_answer", 0), ("final_answer", 2)])
@pytest.mark.parametrize("done", [True, False, None, 1])
def test_tool_loop_rejects_backend_length_truncation(tmp_path, stage, expected_calls, done):
    class Runtime:
        def __init__(self): self.requests = 0
        def request(self, endpoint, payload, timeout=None):
            if endpoint == "/api/show":
                return {"capabilities": ["completion", "tools"]}
            self.requests += 1
            if stage == "tool_call":
                return {"done": done, "done_reason": "length", "message": {"tool_calls": [call("repo_search", {"query": "x"})]}}
            if stage == "direct_answer":
                return {"done": done, "done_reason": "length", "message": {"content": "partial"}}
            if self.requests <= 2:
                return {"message": {"tool_calls": [call("repo_search", {"query": str(self.requests)})]}}
            return {"done": done, "done_reason": "length", "message": {"content": "partial"}}
    runtime = Runtime()
    execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    services = SimpleNamespace(model_policy=SimpleNamespace(profile=lambda *a, **k: execution,
            apply_payload=lambda model, payload, **kwargs: (payload, execution)), runtime=runtime,
        scheduler=SimpleNamespace(submit=lambda model, execute, **kwargs: execute()),
        repo_tools=SimpleNamespace(_root=lambda root: root), _repo_cache_state=lambda root: {"fingerprint": "1"},
        generation_cache=SimpleNamespace(get_or_compute=lambda key, compute: (compute(), False, False)))
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "1",
                                   compact_context=lambda *args: "")
    agent = ToolAwareLocalAgent({"local_tools": {"bootstrap_deterministic_tools": False}}, services,
                                preprocessor, SimpleNamespace(workspace_id=lambda root: "test"))
    executed = []
    agent._execute_tool = lambda *args: executed.append(args) or {"success": True}
    result = agent.run("model", "critic", "review", str(tmp_path), 128, 5)
    assert result["success"] is False and result["output_truncated"] is True, result
    assert result["stop_reason"] == "length" and result["retryable"] is False
    assert (result.get("_lah_backend_completed") is True) is (done is True)
    assert len(executed) == expected_calls


def test_tool_cache_key_excludes_old_completion_contract(tmp_path, monkeypatch):
    import local_ai_hub.tool_agent as module
    original_hash = module.stable_hash
    seen = []
    def observed_hash(value):
        if isinstance(value, dict) and "tool_evidence_version" in value:
            seen.append(value)
        return original_hash(value)
    monkeypatch.setattr(module, "stable_hash", observed_hash)
    execution = SimpleNamespace(cache_scope=lambda: {"num_ctx": 16384})
    services = SimpleNamespace(model_policy=SimpleNamespace(profile=lambda *a, **k: execution),
        runtime=SimpleNamespace(request=lambda *a, **k: {"capabilities": ["tools"]}, model_digest=lambda model: "a" * 64),
        repo_tools=SimpleNamespace(_root=lambda root: root), _repo_cache_state=lambda root: {"fingerprint": "1"},
        generation_cache=SimpleNamespace(get_or_compute=lambda key, compute: ({"success": False}, False, False)))
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None, context_revision=lambda root: "1")
    agent = ToolAwareLocalAgent({}, services, preprocessor, SimpleNamespace(workspace_id=lambda root: "test"))
    agent.run("model", "critic", "review", str(tmp_path), 128, 5)
    assert len(seen) == 1 and seen[0]["tool_completion_version"] == 1
    old = {key: value for key, value in seen[0].items() if key != "tool_completion_version"}
    assert original_hash(old) != original_hash(seen[0])


@pytest.mark.parametrize("name, expected_calls, success", [("repo_search", 1, True), ("rag_search", 0, False), (None, 0, False), ("overflow", 0, False), ("steps", 2, False), ("parent_two", 1, False), ("parent_one", 0, False), ("parent_denied", 0, False), ("duplicate", 1, False), ("unsupported", 0, True), ("unsupported_tool", 0, False), ("empty", 0, False), ("tool_failure", 1, False), ("tool_unknown", 1, False), ("tool_uncertain", 1, False), ("tool_conflict", 1, False)])
def test_tool_loop_enforces_advertised_role_tools(tmp_path, name, expected_calls, success):
    class Runtime:
        def __init__(self):
            self.requests = []

        def request(self, endpoint, payload, timeout=None):
            if endpoint == "/api/show":
                return {"capabilities": ["completion"] if name in {"unsupported", "unsupported_tool", "empty"} else ["completion", "tools"]}
            self.requests.append(payload)
            if name in {"unsupported", "unsupported_tool"}:
                assert "tools" not in payload
                return {"message": {"role": "assistant", "content": "done", **({"tool_calls": [call("repo_search", {"query": "x"})]} if name == "unsupported_tool" else {})}}
            if name == "empty":
                return {"message": {"role": "assistant", "content": ""}}
            if len(self.requests) == 1 or name in {"steps", "parent_two", "parent_one"}:
                calls = [call("repo_search", {"query": str(len(self.requests))})] if name in {"steps", "parent_two", "parent_one"} else [call("repo_search", {"query": "x"})] * (9 if name == "overflow" else 2) if name in {"overflow", "duplicate"} else [call("repo_search" if name in {"tool_failure", "tool_unknown", "tool_uncertain", "tool_conflict"} else "file_slice" if name == "parent_denied" else name, {"query": "x"})] if name is not None else "invalid"
                return {"message": {"role": "assistant", "content": "", "tool_calls": calls}}
            return {"message": {"role": "assistant", "content": "done"}}

    runtime = Runtime()
    profile = SimpleNamespace(cache_scope=lambda: {"tier": "smart", "num_ctx": 16384})
    policy = SimpleNamespace(profile=lambda *a, **k: profile,
                             apply_payload=lambda model, payload, **kwargs: (payload, profile))
    services = SimpleNamespace(model_policy=policy, runtime=runtime,
        scheduler=SimpleNamespace(submit=lambda model, execute, **kwargs: execute()),
        repo_tools=SimpleNamespace(_root=lambda root: root),
        _repo_cache_state=lambda root: {"fingerprint": "1"},
        generation_cache=SimpleNamespace(get_or_compute=lambda key, compute: (compute(), False, False)))
    preprocessor = SimpleNamespace(touch_if_registered=lambda root: None,
        context_revision=lambda root: "1", compact_context=lambda *args: "")
    agent = ToolAwareLocalAgent({"local_tools": {"bootstrap_deterministic_tools": False}},
                                services, preprocessor, SimpleNamespace(workspace_id=lambda root: "test"))
    executed = []
    agent._execute_tool = lambda *args: executed.append(args) or ({"success": False, "error": "unavailable"} if name == "tool_failure" else {} if name == "tool_unknown" else {"success": False, "outcome_unknown": True} if name == "tool_uncertain" else {"success": True, "outcome_unknown": True} if name == "tool_conflict" else {"success": True})

    result = agent.run("model", "critic", "review", str(tmp_path), 512, 5,
                       **({"max_model_steps": 2 if name == "parent_two" else 1} if name in {"parent_two", "parent_one"} else
                          {"allowed_tool_names": ["repo_search"]} if name == "parent_denied" else {}))
    assert result["success"] is success
    assert len(executed) == expected_calls
    assert len(runtime.requests) <= 3
    if name == "parent_two":
        assert len(runtime.requests) == 2
    if name == "parent_one":
        assert len(runtime.requests) == 1 and "tools" not in runtime.requests[0]
    if name == "parent_denied":
        assert [item["function"]["name"] for item in runtime.requests[0]["tools"]] == ["repo_search"]
    if name in {"tool_failure", "tool_unknown", "tool_uncertain", "tool_conflict"}:
        assert len(runtime.requests) == 1
        assert result["tool_agent"]["tool_evidence"]["failed" if name == "tool_failure" else "unknown"] == 1
    if success:
        assert result["execution_profile"]["num_ctx"] == 16384
        assert result["effective_context_tokens"] is None
        assert result["backend_eval_count"] is None
    if name == "unsupported":
        assert result["tool_agent"]["tool_fallback"] is True
        assert result["tool_agent"]["tool_capability"] is False
        assert "use an advertised read-only tool" not in runtime.requests[0]["messages"][0]["content"]
    elif success:
        assert runtime.requests[1]["messages"][-1]["role"] == "tool"
        assert "use an advertised read-only tool" in runtime.requests[0]["messages"][0]["content"]


@pytest.mark.parametrize("response, expected", [
    ({"capabilities": ["completion", "tools"]}, True),
    ({"capabilities": ["completion"]}, False),
    ({"capabilities": ["completion"], "capabilities_complete": False}, None),
    ({"capabilities": "tools"}, None),
    ({"error": "timeout"}, None),
])
def test_tool_capability_requires_explicit_backend_evidence(response, expected):
    runtime = SimpleNamespace(request=lambda endpoint, payload, timeout: response)
    assert ToolAwareLocalAgent._tool_capability(runtime, "model") is expected


def test_model_response_telemetry_requires_real_generation_evidence():
    events = []
    agent = ToolAwareLocalAgent({}, SimpleNamespace(telemetry=SimpleNamespace(record_stage=lambda **kw: events.append(kw))), None, None)
    agent._record_model_response("critic", "model", {"message": {"content": "secret"}})
    agent._record_model_response("critic", "model", {"eval_count": 3})
    agent._record_model_response("critic", "model", {"eval_count": 3, "done_reason": "length"})
    assert [event["stage"] for event in events] == ["model_response_unverified", "model_inference_observed", "model_inference_observed"]
    assert events[0]["success"] is True
    assert events[2]["success"] is False
    assert "secret" not in str(events)


def test_local_evidence_fetch_is_confined_to_bound_root(tmp_path):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    content = "foreign source"
    (root_b / "data.py").write_text(content, encoding="utf-8")
    store = EvidenceStore(tmp_path / "state")
    eid = store.put(str(root_b), {"path": "data.py", "text": content,
        "file_sha256": hashlib.sha256(content.encode()).hexdigest()})
    agent = ToolAwareLocalAgent({}, SimpleNamespace(), None, None, evidence=store)
    denied = agent._execute_tool("evidence_get", {"evidence_id": eid}, str(root_a), "")
    assert denied["success"] is False
    assert "text" not in denied
    assert agent._execute_tool("evidence_get", {"evidence_id": eid}, str(root_b), "")["text"] == content
