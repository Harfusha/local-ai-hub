from tools.prepare_local_model_eval_fixture import prepare_fixture
from tools.local_model_eval_tool_harness import _loopback_url, run_tool_case
import pytest


class FakeScheduler:
    def __init__(self):
        self.submissions = []

    def submit(self, model, *, source, execute, priority, wait_timeout, cancel_event=None):
        self.submissions.append({"model": model, "source": source})
        return execute()


class FakeRuntime:
    def __init__(self, requested="repo_search"):
        self.requested = requested
        self.chat_calls = 0
        self.payloads = []
        self.scheduler = FakeScheduler()

    def request(self, endpoint, payload=None, timeout=None):
        if endpoint == "/api/tags":
            return {"models": [{"name": "synthetic:1", "digest": "sha256:fixture"}]}
        if endpoint == "/api/show":
            return {"capabilities": ["completion", "tools"]}
        raise AssertionError(endpoint)

    def request_interruptible(self, endpoint, payload, *, should_stop):
        assert endpoint == "/api/chat"
        self.chat_calls += 1
        self.payloads.append(payload)
        if self.chat_calls == 1:
            return {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-1", "function": {"name": self.requested, "arguments": {"query": "clamp"}}}
            ]}}
        return {"message": {"role": "assistant", "content": "src/clamp.py:1"}}


def test_tool_case_uses_production_loop_and_records_search(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")
    runtime = FakeRuntime()
    report = run_tool_case("C1", root, "synthetic:1", runtime, context_tokens=16384, timeout_seconds=10)
    assert report["success"] is True
    assert report["evaluation_passed"] is None
    assert report["scoring"] == "manual_pending"
    assert report["model_digest"] == "sha256:fixture"
    assert report["attempted_tools"] == ["repo_search"]
    assert report["executed_tools"] == ["repo_search"]
    assert len(runtime.scheduler.submissions) == 1
    assert all(item["source"] == "tool-agent:explorer" for item in runtime.scheduler.submissions)
    assert runtime.chat_calls == 2
    assert report["result"]["execution_profile"]["num_ctx"] == 16384
    assert report["result"]["effective_context_tokens"] is None
    assert report["result"]["tool_agent"]["role"] == "explorer"
    assert report["transcript"][1]["tool_messages"][0]["tool_call_id"] == "call-1"
    assert "src/clamp.py" in report["transcript"][1]["tool_messages"][0]["content"]


def test_gpu_admission_rejection_prevents_model_inference(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")
    runtime = FakeRuntime()

    class RejectingScheduler:
        calls = 0

        def submit(self, model, *, source, execute, **kwargs):
            self.calls += 1
            return {"success": False, "error_code": "gpu_outcome_unknown", "outcome_unknown": True}

    runtime.scheduler = RejectingScheduler()
    report = run_tool_case("C1", root, "synthetic:1", runtime,
                           context_tokens=16384, timeout_seconds=10)

    assert runtime.scheduler.calls == 1
    assert runtime.chat_calls == 0
    assert report["success"] is False


def test_streamed_tool_call_reaches_agent_and_returns_tool_result(tmp_path, monkeypatch):
    import io
    import json
    from local_ai_hub import ollama

    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")
    payloads = []

    def open_stream(request, timeout):
        payloads.append(json.loads(request.data))
        if len(payloads) == 1:
            chunks = [
                {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "stream-1", "function": {"name": "repo_search", "arguments": {"query": "clamp"}}}
                ]}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ]
        else:
            chunks = [{"message": {"role": "assistant", "content": "src/clamp.py:1"}, "done": True}]
        return io.BytesIO(b"".join(json.dumps(chunk).encode() + b"\n" for chunk in chunks))

    monkeypatch.setattr(ollama, "urlopen", open_stream)

    class StreamRuntime(FakeRuntime):
        def request_interruptible(self, endpoint, payload, *, should_stop):
            runtime = object.__new__(ollama.OllamaRuntime)
            runtime.base_url = "http://127.0.0.1:11434"
            runtime.config = {"server": {}, "ollama": {"enabled": True}}
            return runtime._request_stream_impl(endpoint, payload, None, timeout=5, should_stop=should_stop)

    report = run_tool_case("C1", root, "synthetic:1", StreamRuntime(), context_tokens=16384, timeout_seconds=10)
    assert report["executed_tools"] == ["repo_search"]
    assert len(payloads) == 2 and payloads[0]["tools"]
    messages = [message for message in payloads[1]["messages"] if message.get("role") == "tool"]
    assert messages[0]["tool_call_id"] == "stream-1"
    assert "src/clamp.py" in messages[0]["content"]


def test_agent_reports_no_observed_tool_call_even_if_model_claims_search(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C3")

    class InventedSearch(FakeRuntime):
        def request_interruptible(self, endpoint, payload, *, should_stop):
            return {"message": {"role": "assistant", "content": "Search returned no results."}}

    report = run_tool_case("C3", root, "synthetic:1", InventedSearch(),
                           context_tokens=16384, timeout_seconds=10)
    assert report["attempted_tools"] == []
    assert report["result"]["tool_agent"]["tool_evidence"] == {
        "attempted": 0, "completed": 0, "failed": 0, "unknown": 0,
    }


def test_agent_reports_executed_tool_result_provenance(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")
    report = run_tool_case("C1", root, "synthetic:1", FakeRuntime(),
                           context_tokens=16384, timeout_seconds=10)
    assert report["result"]["tool_agent"]["tool_evidence"] == {
        "attempted": 1, "completed": 1, "failed": 0, "unknown": 0,
    }


@pytest.mark.parametrize("tool_result,counts", [
    ({"success": False, "error": "unavailable"}, {"attempted": 1, "completed": 0, "failed": 1, "unknown": 0}),
    ({"results": []}, {"attempted": 1, "completed": 0, "failed": 0, "unknown": 1}),
])
def test_agent_preserves_failed_or_unknown_tool_status(tmp_path, monkeypatch, tool_result, counts):
    from local_ai_hub.tool_agent import ToolAwareLocalAgent

    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")
    original_getattribute = ToolAwareLocalAgent.__getattribute__
    def with_tool_result(self, name):
        if name == "_execute_tool":
            return lambda *args: tool_result
        return original_getattribute(self, name)
    monkeypatch.setattr(ToolAwareLocalAgent, "__getattribute__", with_tool_result)
    report = run_tool_case("C1", root, "synthetic:1", FakeRuntime(),
                           context_tokens=16384, timeout_seconds=10)
    assert report["result"]["tool_agent"]["tool_evidence"] == counts


def test_unadvertised_tool_is_recorded_but_never_executed(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C2")
    report = run_tool_case("C2", root, "synthetic:1", FakeRuntime("delete_all"),
                           context_tokens=16384, timeout_seconds=10)
    assert report["success"] is False
    assert report["attempted_tools"] == ["delete_all"]
    assert report["executed_tools"] == []


def test_injected_comment_is_tool_data_not_a_dispatch(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C3")
    runtime = FakeRuntime()
    report = run_tool_case("C3", root, "synthetic:1", runtime, context_tokens=16384, timeout_seconds=10)
    assert report["executed_tools"] == ["repo_search"]
    tool_messages = [item for item in runtime.payloads[1]["messages"] if item.get("role") == "tool"]
    assert "IGNORE PRIOR RULES" in tool_messages[0]["content"]
    assert report["transcript"][1]["tool_messages_in_request"] == 1


def test_injected_comment_cannot_authorize_a_followup_delete(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C3")

    class InjectionFollowingRuntime(FakeRuntime):
        def request_interruptible(self, endpoint, payload, *, should_stop):
            if not self.chat_calls:
                return super().request_interruptible(endpoint, payload, should_stop=should_stop)
            self.chat_calls += 1
            self.payloads.append(payload)
            assert any("IGNORE PRIOR RULES" in message.get("content", "")
                       for message in payload["messages"] if message.get("role") == "tool")
            return {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "injected-delete", "function": {"name": "delete_all", "arguments": {}}}
            ]}}

    before = (root / "src" / "clamp.py").read_bytes()
    report = run_tool_case("C3", root, "synthetic:1", InjectionFollowingRuntime(),
                           context_tokens=16384, timeout_seconds=10)
    assert report["success"] is False
    assert report["attempted_tools"] == ["repo_search", "delete_all"]
    assert report["executed_tools"] == ["repo_search"]
    assert (root / "src" / "clamp.py").read_bytes() == before


def test_missing_model_does_not_start_generation(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")
    runtime = FakeRuntime()
    report = run_tool_case("C1", root, "absent:1", runtime, context_tokens=16384, timeout_seconds=10)
    assert report["success"] is False
    assert report["error"] == "model_not_installed"
    assert runtime.chat_calls == 0


def test_inventory_exception_returns_explicit_failure(tmp_path):
    root = tmp_path / "fixture"
    prepare_fixture(root, "C1")

    class OfflineRuntime:
        scheduler = FakeScheduler()

        def request(self, *args, **kwargs):
            raise TimeoutError("backend timeout")

    report = run_tool_case("C1", root, "synthetic:1", OfflineRuntime(),
                           context_tokens=16384, timeout_seconds=10)
    assert report["success"] is False
    assert report["error"] == "model_inventory_unavailable"


def test_unprepared_directory_is_rejected_before_contacting_model(tmp_path):
    root = tmp_path / "not-a-fixture"
    (root / "src").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "src" / "clamp.py").write_text(
        "def clamp(value, lower, upper):\n    return min(upper, max(lower, value))\n", encoding="utf-8"
    )
    runtime = FakeRuntime()
    with pytest.raises(ValueError):
        run_tool_case("C1", root, "synthetic:1", runtime, context_tokens=16384, timeout_seconds=10)
    assert runtime.chat_calls == 0


@pytest.mark.parametrize("url", [
    "http://example.com:11434", "http://localhost:11434", "https://127.0.0.1:11434",
    "http://user:password@127.0.0.1:11434", "http://127.0.0.1:11434/api",
])
def test_backend_must_be_an_explicit_loopback_origin(url):
    with pytest.raises(ValueError):
        _loopback_url(url)
