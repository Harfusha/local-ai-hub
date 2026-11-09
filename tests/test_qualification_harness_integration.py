from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.work_orchestrator import _bounded_tool_qualification
from tools.local_model_eval_tool_harness import run_tool_case
from tools.prepare_local_model_eval_fixture import prepare_fixture
from tools.qualify_local_tool_model import persist_qualification


class SyntheticBackend:
    def __init__(self, case):
        self.case = case
        self.count = 0

    def model_digest(self, model):
        return "a" * 64 if model == "synthetic:1" else None

    def request(self, endpoint, payload=None, timeout=None):
        if endpoint == "/api/tags":
            return {"models": [{"name": "synthetic:1", "digest": "a" * 64}]}
        if endpoint == "/api/show":
            return {"capabilities": ["tools"]}
        raise AssertionError(endpoint)

    def request_interruptible(self, endpoint, payload, *, should_stop):
        self.count += 1
        if self.case != "C2" and self.count == 1:
            return {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "repo_search", "arguments": {"query": "clamp"}}}
            ]}, "eval_count": 10}
        return {"message": {"role": "assistant", "content": "I refuse" if self.case == "C2" else "src/clamp.py"},
                "eval_count": 10}


class InlineScheduler:
    """Synchronous scheduler fixture matching the shared admission contract."""

    def submit(self, model, *, source, execute, priority=5, wait_timeout=None,
               background=False, cancel_event=None):
        assert model == "synthetic:1"
        assert source.startswith("tool-agent:")
        assert callable(execute)
        return execute()


def test_reviewed_raw_harness_cases_round_trip(tmp_path):
    cases = {}
    for case in ("C1", "C2", "C3"):
        root = tmp_path / case
        prepare_fixture(root, case)
        cases[case] = run_tool_case(case, root, "synthetic:1", SyntheticBackend(case),
                                    scheduler=InlineScheduler(),
                                    context_tokens=16384, timeout_seconds=10)
    store = ArtifactStore(tmp_path / "state")
    runtime = SyntheticBackend("C1")
    artifact_id = persist_qualification(store, runtime, cases, reviewed=True)
    config = {"_hardware": {"profile": "high"}, "work_orchestrator": {"tool_exploration": {
        "enabled": True, "model": "synthetic:1", "qualification_artifact_id": artifact_id}}}
    assert _bounded_tool_qualification(config, store, runtime)["qualified"] is True
