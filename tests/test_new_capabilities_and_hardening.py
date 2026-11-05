from __future__ import annotations

import py_compile
import sqlite3
import subprocess
import threading
import time
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.agent_events import AgentStateStore, SwarmPubSub
from local_ai_hub.agent_memory import MemoryStore
from local_ai_hub.commands import CommandBroker, _is_interactive_prompt, _BoundedStreamBuffer
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.doctor_support import install_git_precommit_hook, uninstall_git_precommit_hook
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.process_utils import list_git_worktrees, prune_git_worktrees, simulate_git_merge
from local_ai_hub.rag import _python_ast_chunks
from local_ai_hub.services import LocalAIServices, vram_priority

ROOT = Path(__file__).resolve().parents[1]


def test_repair_model_uses_only_low_confidence_artifact_preview():
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"local_diagnostic_dispatch": True}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock(return_value={"response": '{"diagnosis": "missing test setup"}'})
    failure = {
        "success": False,
        "failure_summary": {"path": "", "line": 0, "message": "unclassified failure"},
        "artifact_id": "art_failure_log",
        "preview": "test command failed after setup",
        "stderr": "RAW_LOG_MUST_NOT_REACH_MODEL" * 400,
    }

    result = services._synthesize_repair_patch("pytest -q", "C:/repo", failure)

    assert result is None
    assert failure["local_diagnostic"] == "missing test setup"
    prompt = services.proxy_request.call_args.args[1]["prompt"]
    assert "art_failure_log" in prompt
    assert "test command failed after setup" in prompt
    assert "RAW_LOG_MUST_NOT_REACH_MODEL" not in prompt
    payload = services.proxy_request.call_args.args[1]
    assert payload["options"]["num_predict"] == 320
    assert payload["format"] == {
        "type": "object",
        "properties": {"diagnosis": {"type": "string"}},
        "required": ["diagnosis"],
        "additionalProperties": False,
    }
    assert "_hub_timeout_seconds" not in payload
    assert services.proxy_request.call_args.args[3] == "local_ai_task"
    assert services.proxy_request.call_args.kwargs["diagnostic_timeout_seconds"] == 20


def test_repair_model_skips_high_confidence_failure():
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"local_diagnostic_dispatch": True}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "failure_summary": {"path": "tests/test_widget.py", "line": 42, "message": "AssertionError"},
        "artifact_id": "art_failure_log",
        "preview": "tests/test_widget.py:42: AssertionError",
    }

    assert services._synthesize_repair_patch("pytest -q", "C:/repo", failure) is None
    services.proxy_request.assert_not_called()


def test_repair_model_never_dispatches_open_ended_or_security_work():
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"local_diagnostic_dispatch": True}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "failure_summary": {"path": "", "line": 0, "message": "unclassified failure"},
        "artifact_id": "art_failure_log",
        "preview": "unclassified command failure",
    }

    assert services._synthesize_repair_patch("security audit architecture redesign", "C:/repo", failure) is None
    services.proxy_request.assert_not_called()


@pytest.mark.parametrize("command", [
    "git reset --hard",
    "python -c \"print('arbitrary')\"",
    "cmd /c echo arbitrary",
    "pytest -q | tee result.txt",
    "pytest -q > result.txt",
    "pytest --snapshot-update",
    "npm test -- -u",
    "npm test -- -u=true",
    "npm test -- --updateSnapshot",
    "pytest --inline-snapshot=fix",
    "pytest --update-goldens",
    "pytest --golden=write",
])
def test_repair_model_default_denies_mutating_or_arbitrary_commands(command: str):
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"local_diagnostic_dispatch": True}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "failure_summary": {"path": "", "line": 0, "message": "unclassified failure"},
        "artifact_id": "art_failure_log",
        "preview": "unclassified command failure",
    }

    assert services._synthesize_repair_patch(command, "C:/repo", failure) is None
    services.proxy_request.assert_not_called()


def test_repair_model_respects_disabled_local_tasks():
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"tasks": False, "local_diagnostic_dispatch": True}, "models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "failure_summary": {"path": "", "line": 0, "message": "unclassified failure"},
        "artifact_id": "art_failure_log",
        "preview": "unclassified command failure",
    }

    assert services._synthesize_repair_patch("pytest -q", "C:/repo", failure) is None
    services.proxy_request.assert_not_called()


def test_repair_model_requires_explicit_diagnostic_dispatch_opt_in():
    services = object.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "qwen2.5-coder:1.5b"}}
    services.proxy_request = MagicMock()
    failure = {
        "success": False,
        "failure_summary": {"path": "", "line": 0, "message": "unclassified failure"},
        "artifact_id": "art_failure_log",
        "preview": "unclassified command failure",
    }

    assert services._synthesize_repair_patch("pytest -q", "C:/repo", failure) is None
    services.proxy_request.assert_not_called()


def test_defaults_disable_local_diagnostic_dispatch():
    defaults = tomllib.loads((ROOT / "defaults.toml").read_text(encoding="utf-8"))

    assert defaults["features"]["local_diagnostic_dispatch"] is False


def test_proxy_timeout_clamps_only_explicit_diagnostic_cap():
    config = {"server": {"request_timeout_seconds": 300}}

    assert LocalAIServices._proxy_timeout_seconds(config) == 300
    assert LocalAIServices._proxy_timeout_seconds(config, 20) == 20
    assert LocalAIServices._proxy_timeout_seconds(config, 600) == 60


def test_proxy_diagnostic_cap_bounds_scheduler_wait():
    services = object.__new__(LocalAIServices)
    services.config = {"server": {"request_timeout_seconds": 300}}
    services.semantic_cache = MagicMock(enabled=False)
    services.generation_cache = MagicMock()
    services.generation_cache.get_or_compute.side_effect = lambda _key, compute: (compute(), False, False)
    services.scheduler = MagicMock()
    services.scheduler.submit.return_value = {"response": "ok"}
    services.runtime = MagicMock()

    services.proxy_request("/api/version", {}, source="hub", diagnostic_timeout_seconds=20)

    assert services.scheduler.submit.call_args.kwargs["wait_timeout"] == 20


def test_proxy_normal_call_uses_configured_scheduler_wait_default():
    services = object.__new__(LocalAIServices)
    services.config = {"server": {"request_timeout_seconds": 300}, "resilience": {"scheduler_wait_timeout_seconds": 180}}
    services.semantic_cache = MagicMock(enabled=False)
    services.generation_cache = MagicMock()
    services.generation_cache.get_or_compute.side_effect = lambda _key, compute: (compute(), False, False)
    services.scheduler = MagicMock()
    services.scheduler.submit.return_value = {"response": "ok"}
    services.runtime = MagicMock()

    services.proxy_request("/api/version", {}, source="hub")

    assert "wait_timeout" not in services.scheduler.submit.call_args.kwargs


def test_proxy_ignores_public_timeout_metadata():
    services = object.__new__(LocalAIServices)
    services.config = {"server": {"request_timeout_seconds": 300}}
    services.semantic_cache = MagicMock(enabled=False)
    services.generation_cache = MagicMock()
    services.generation_cache.get_or_compute.side_effect = lambda _key, compute: (compute(), False, False)
    services.scheduler = MagicMock()
    services.scheduler.submit.side_effect = lambda _model, *, execute, **_kwargs: execute()
    services.runtime = MagicMock(return_value={"response": "ok"})

    services.proxy_request("/api/version", {"_hub_timeout_seconds": 1}, source="hub")

    assert "wait_timeout" not in services.scheduler.submit.call_args.kwargs
    assert services.runtime.request.call_args.kwargs["timeout"] == 300
    assert "_hub_timeout_seconds" not in services.runtime.request.call_args.args[1]


def test_1_ast_aware_python_chunking(tmp_path: Path):
    code = '''"""Module docstring."""
import os
import sys

GLOBAL_VAR = 42

class Worker:
    """Worker class."""
    def __init__(self, name: str):
        self.name = name

    def process(self, item: int) -> int:
        return item * 2

def standalone_function(x: int) -> int:
    """Function docstring."""
    return x + 1
'''
    py_file = tmp_path / "sample.py"
    py_file.write_text(code, encoding="utf-8")

    chunks = _python_ast_chunks(code, py_file)
    assert len(chunks) >= 2
    # Check preamble preservation
    assert any("import os" in c and "standalone_function" in c for c in chunks)
    assert any("class Worker" in c and "process" in c for c in chunks)


def test_2_interactive_prompt_detection():
    assert _is_interactive_prompt("Do you want to continue [y/N]? ")
    assert _is_interactive_prompt("Enter password for root: ")
    assert _is_interactive_prompt("Overwrite existing file? (yes/no): ")
    assert not _is_interactive_prompt("Running test suite 100% complete")

    buf = _BoundedStreamBuffer(max_chars=100)
    buf.write("Proceed with install? [Y/n] ")
    assert _is_interactive_prompt(buf.peek(50))


def test_3_git_merge_tree_simulation(tmp_path: Path):
    res = simulate_git_merge(str(tmp_path), "feature-branch", "main")
    # Non-git directory or simulated run returns a structured dictionary
    assert isinstance(res, dict)
    assert "success" in res


def test_4_vram_priority_lock():
    order = []

    def heavy_inference():
        with vram_priority():
            order.append("inference_start")
            time.sleep(0.05)
            order.append("inference_end")

    def batch_embedding():
        time.sleep(0.01)
        with vram_priority():
            order.append("embedding")

    t1 = threading.Thread(target=heavy_inference)
    t2 = threading.Thread(target=batch_embedding)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert order == ["inference_start", "inference_end", "embedding"]


def test_5_callers_detection(tmp_path: Path):
    f1 = tmp_path / "module_a.py"
    f1.write_text("def target_func():\n    pass\n", encoding="utf-8")
    f2 = tmp_path / "module_b.py"
    f2.write_text("import module_a\n\ndef caller_one():\n    module_a.target_func()\n", encoding="utf-8")

    engine = DeterministicEngine()
    res = engine.find_callers(str(tmp_path), "target_func")
    assert res["success"] is True
    assert res["symbol"] == "target_func"
    assert res["caller_count"] >= 1
    assert any("caller_one" in c["caller"] for c in res["callers"])


def test_6_dead_code_detection(tmp_path: Path):
    f1 = tmp_path / "app.py"
    f1.write_text("""
def used_func():
    return 1

def unused_dead_func():
    return 2

def main():
    return used_func()
""", encoding="utf-8")

    engine = DeterministicEngine()
    res = engine.find_dead_code(str(tmp_path))
    assert res["success"] is True
    dead_names = [d["name"] for d in res["dead_code"]]
    assert "unused_dead_func" in dead_names
    assert "used_func" not in dead_names


def test_7_ast_outline(tmp_path: Path):
    f1 = tmp_path / "example.py"
    f1.write_text("""
class Greeter:
    def greet(self, name: str) -> str:
        # long body here
        x = 1 + 2
        return f"Hello {name}"

def helper(v: int) -> int:
    return v * 2
""", encoding="utf-8")

    engine = DeterministicEngine()
    res = engine.ast_outline(str(tmp_path), "example.py")
    assert res["success"] is True
    outline = res["outline"]
    assert "class Greeter:" in outline
    assert "def greet" in outline
    assert "..." in outline
    assert "long body here" not in outline




def test_9_secret_scanner(tmp_path: Path):
    f_sec = tmp_path / "config.py"
    aws_name = "AWS" + "_SECRET"
    openai_name = "OPENAI" + "_TOKEN"
    aws_value = "AKIA" + "IOSFODNN7EXAMPLE"
    openai_value = "sk-" + "1234567890abcdef1234567890abcdef123456"
    f_sec.write_text(
        f"{aws_name} = {aws_value!r}\n{openai_name} = {openai_value!r}\nNORMAL_VAR = 'hello'\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine()
    res = engine.secret_scan(str(tmp_path))
    assert res["success"] is True
    assert res["secrets_count"] >= 1
    types = [s["secret_type"] for s in res["findings"]]
    assert any("aws" in t or "key" in t or "openai" in t for t in types)


def test_10_sqlite_schema_inspect_and_explain(tmp_path: Path):
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL, created_at REAL)")
        conn.execute("CREATE INDEX idx_users_email ON users(email)")
        conn.execute("INSERT INTO users (email, created_at) VALUES ('test@example.com', 12345.0)")
        conn.commit()
    finally:
        conn.close()

    engine = DeterministicEngine()
    res_schema = engine.schema_inspect(str(tmp_path), str(db_file))
    assert res_schema["success"] is True
    assert "users" in res_schema["tables"]
    assert len(res_schema["tables"]["users"]["columns"]) == 3

    res_explain = engine.explain_query(str(tmp_path), "SELECT * FROM users WHERE email = 'test@example.com'", str(db_file))
    assert res_explain["success"] is True
    assert len(res_explain["plan"]) >= 1


def test_11_swarm_pubsub():
    bus = SwarmPubSub()
    topic = "planning_updates"

    res_pub = bus.publish(topic, {"status": "in_progress", "step": 1}, sender="agent_alpha")
    assert res_pub["success"] is True
    assert res_pub["topic"] == topic

    res_poll = bus.poll(topic, since_timestamp=0.0)
    assert res_poll["success"] is True
    assert res_poll["count"] == 1
    assert res_poll["messages"][0]["sender"] == "agent_alpha"
    assert res_poll["messages"][0]["payload"]["step"] == 1


def test_12_git_precommit_hooks(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)

    res_install = install_git_precommit_hook(str(tmp_path))
    assert res_install["success"] is True
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    assert hook_file.is_file()

    res_uninstall = uninstall_git_precommit_hook(str(tmp_path))
    assert res_uninstall["success"] is True
    assert not hook_file.exists()


def test_14_agent_eval_suite():
    services = LocalAIServices.__new__(LocalAIServices)
    # Run built-in dummy benchmark suite
    res = services.eval_suite({"suite_name": "built_in_code_generation"})
    assert res["success"] is True
    assert "summary" in res
    assert "total" in res["summary"]


def test_eval_suite_checks_model_output_instead_of_expected_text():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()
    services.runtime.request.return_value = {"response": "wrong answer"}
    payload = {"cases": [{"id": "bad", "input": "Return expected", "expected": "expected"}]}
    result = services.eval_suite(payload)
    assert result["summary"]["failed"] == 1
    services.runtime.request.assert_called_once()
    first_payload = services.runtime.request.call_args.args[1]
    assert first_payload["think"] is False
    assert "no greeting" in first_payload["system"]
    services.runtime.request.return_value = {"response": "expected"}
    result = services.eval_suite(payload)
    assert result["summary"]["passed"] == 1
    assert result["cases"][0]["response_chars"] == len("expected")
    assert "response_text" not in result["cases"][0]
    assert result["summary"]["quality_pass_rate"] == 1.0
    assert len(result["cases"][0]["response_sha256"]) == 64
    assert result["cases"][0]["model_digest"] is None
    assert result["cases"][0]["model_digest_status"] == "unavailable"


def test_eval_suite_records_installed_model_digest():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()
    services.runtime.request.return_value = {"response": "expected"}
    services.runtime.model_digest.return_value = "a" * 64

    result = services.eval_suite({"cases": [{"id": "identity", "input": "prompt", "expected": "expected"}]})

    assert result["cases"][0]["model_digest"] == "a" * 64
    services.runtime.model_digest.assert_called_once_with("test-model")


def test_eval_suite_can_return_bounded_full_response_on_request():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()
    services.runtime.request.return_value = {"response": "x" * 5000}

    result = services.eval_suite({"cases": [{
        "id": "full-response", "input": "prompt", "expected": "x",
        "include_response_text": True,
    }]})

    case = result["cases"][0]
    assert case["response_text"] == "x" * 4096
    assert case["response_text_truncated"] is True


def test_eval_suite_rejects_non_boolean_response_text_opt_in_before_generation():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()

    result = services.eval_suite({"cases": [{
        "id": "invalid-response-opt-in", "input": "prompt", "expected": "x",
        "include_response_text": "yes",
    }]})

    assert result["success"] is False
    assert result["error_code"] == "invalid_eval_case_rubric"
    services.runtime.request.assert_not_called()


def test_eval_suite_applies_explicit_word_and_citation_rubric():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()
    services.runtime.request.side_effect = [
        {"response": "Result [docs/search.md:10-13]."},
        {"response": "Result [src/other.py:1-2]. Later results were omitted."},
        {"response": "Result [docs/search.md:10-13]. [E2]"},
    ]
    citation = "[docs/search.md:10-13]"
    result = services.eval_suite({"cases": [
        {
            "id": "valid-rubric", "input": "summary", "expected": "Result",
            "max_words": 3, "allowed_citations": [citation],
            "required_citations": [citation], "forbidden_phrases": ["results were omitted"],
        },
        {
            "id": "invalid-rubric-output", "input": "summary", "expected": "Result",
            "max_words": 3, "allowed_citations": [citation],
            "required_citations": [citation], "forbidden_phrases": ["results were omitted"],
        },
        {
            "id": "identifier-is-not-a-citation", "input": "summary", "expected": "Result",
            "max_words": 3, "allowed_citations": [citation],
            "required_citations": [citation], "forbidden_phrases": ["results were omitted"],
        },
    ]})

    valid, invalid, identifier = result["cases"]
    assert valid["response_words"] == 2
    assert valid["style_quality"]["concise"] is True
    assert valid["style_quality"]["citation_precision"] is True
    assert valid["style_quality"]["required_citations_present"] is True
    assert valid["style_quality"]["forbidden_phrases_absent"] is True
    assert valid["style_quality"]["quality_pass"] is True
    assert invalid["style_quality"]["citation_precision"] is False
    assert invalid["style_quality"]["required_citations_present"] is False
    assert invalid["style_quality"]["forbidden_phrases_absent"] is False
    assert invalid["style_quality"]["quality_pass"] is False
    assert identifier["style_quality"]["citation_precision"] is False
    assert identifier["style_quality"]["quality_pass"] is False


def test_eval_suite_rejects_malformed_case_rubric_before_inference():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()

    result = services.eval_suite({"cases": [{
        "id": "bad-rubric", "input": "summary", "expected": "Result",
        "max_words": True,
    }]})

    assert result["success"] is False
    assert result["error_code"] == "invalid_eval_case_rubric"
    services.runtime.request.assert_not_called()


def test_eval_suite_rejects_unknown_case_fields_before_inference():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()

    result = services.eval_suite({"cases": [{
        "id": "bad-case", "input": "summary", "expected": "Result", "unexpected_alias": "ignored?",
    }]})

    assert result["success"] is False
    assert result["error_code"] == "invalid_eval_case_rubric"
    services.runtime.request.assert_not_called()


def test_eval_suite_rejects_explicit_empty_cases_before_inference():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()

    result = services.eval_suite({"cases": []})

    assert result["success"] is False
    assert result["error_code"] == "invalid_eval_suite_cases"
    services.runtime.request.assert_not_called()


def test_eval_suite_rejects_nonobject_and_overlimit_cases_before_inference():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "test-model"}}
    services.runtime = MagicMock()
    malformed = services.eval_suite({"cases": [None]})
    overlimit = services.eval_suite({"cases": [{"id": str(index), "input": "x", "expected": "x"} for index in range(33)]})

    assert malformed["success"] is False
    assert malformed["error_code"] == "invalid_eval_suite_cases"
    assert overlimit["success"] is False
    assert overlimit["error_code"] == "invalid_eval_suite_cases"
    services.runtime.request.assert_not_called()


def test_eval_suite_uses_scheduler_for_managed_inference():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "candidate"}}
    services.runtime = MagicMock()
    services.runtime.request.return_value = {"response": "expected"}

    class Scheduler:
        def __init__(self):
            self.calls = []

        def submit(self, model, *, source, execute, priority, wait_timeout=None):
            self.calls.append((model, source, priority))
            return execute()

    scheduler = Scheduler()
    services.scheduler = scheduler

    result = services.eval_suite({"cases": [{"id": "case", "input": "Return expected", "expected": "expected"}]})

    assert result["summary"]["quality_pass_rate"] == 1.0
    assert scheduler.calls == [("candidate", "eval_suite", 2)]
    services.runtime.request.assert_called_once()


def test_eval_suite_fails_closed_for_managed_mixed_route_without_scheduler():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "models": {"fast_code": "candidate"},
        "llama_cpp": {"managed_with_ollama": True},
    }
    services.runtime = MagicMock()

    result = services.eval_suite({"cases": [{"id": "case", "input": "Return expected", "expected": "expected"}]})

    assert result["summary"]["execution_failures"] == 1
    assert result["cases"][0]["status"] == "unavailable"
    assert "Scheduler required" in result["cases"][0]["error"]
    services.runtime.request.assert_not_called()


@pytest.mark.parametrize("state", ["pending", "running"])
def test_eval_suite_preserves_scheduler_timeout_identity(state):
    from types import SimpleNamespace
    from local_ai_hub.scheduler import SchedulerTimeoutError

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "candidate"}}
    services.runtime = MagicMock()

    class Scheduler:
        def submit(self, *_args, **_kwargs):
            raise SchedulerTimeoutError(SimpleNamespace(id=612), state, 0.1)

    services.scheduler = Scheduler()
    result = services.eval_suite({"cases": [{"id": "case", "input": "task", "expected": "ok"}]})
    case = result["cases"][0]

    assert case["timed_out"] is True
    assert case["job_id"] == 612
    if state == "pending":
        assert case["request_not_sent"] is True
        assert case["operation_not_started"] is True
        assert case.get("outcome_unknown") is not True
    else:
        assert case["outcome_unknown"] is True
        assert case["retryable"] is False
    services.runtime.request.assert_not_called()


def test_eval_suite_preserves_scheduler_returned_unknown_outcome():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "candidate"}}
    services.runtime = MagicMock()

    class Scheduler:
        def submit(self, *_args, **_kwargs):
            return {"success": False, "error": "scheduler outcome unknown", "timed_out": True,
                    "outcome_unknown": True, "retryable": False, "job_id": 713}

    services.scheduler = Scheduler()
    result = services.eval_suite({"cases": [{"id": "case", "input": "task", "expected": "ok"}]})
    case = result["cases"][0]

    assert case["timed_out"] is True
    assert case["outcome_unknown"] is True
    assert case["retryable"] is False
    assert case["job_id"] == 713
    services.runtime.request.assert_not_called()


def test_eval_suite_exposes_model_errors_without_hiding_them():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"models": {"fast_code": "qwen3.5:9b"}}
    services.runtime = MagicMock()
    services.runtime.request.return_value = {"error": "HTTP 404: model not found"}

    result = services.eval_suite({"cases": [{"id": "missing", "input": "task", "expected": "ok"}]})

    assert result["success"] is True
    assert result["summary"]["failed"] == 1
    assert result["cases"][0]["status"] == "unavailable"
    assert "404" in result["cases"][0]["error"]
    assert result["cases"][0]["response_chars"] == 0


def test_eval_suite_marks_vision_only_model_as_role_mismatch_for_text_suite():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "models": {
            "fast_code": "qwen2.5-coder:7b",
            "general": "qwen2.5-coder:7b",
            "vision": "qwen3.5:9b",
        }
    }
    services.runtime = MagicMock()

    result = services.eval_suite({
        "model": "qwen3.5:9b",
        "suite_name": "text_quality",
        "cases": [{"id": "text", "input": "Return 17", "expected": "17"}],
    })

    assert result["success"] is True
    assert result["summary"]["benchmark_valid"] is False
    assert result["summary"]["role_mismatch"] is True
    assert result["cases"][0]["status"] == "role_mismatch"
    services.runtime.request.assert_not_called()


def test_ast_outline_rejects_paths_outside_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text('secret = 123\n')
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
    result = engine.ast_outline(str(root), "../outside.py")
    assert result["success"] is False
    assert 'outside' in result["error"]


def test_ast_outline_rejects_resolved_directory_link_escape(tmp_path):
    import os

    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    private_source = outside / "private.py"
    private_source.write_text("private_marker = 123\n", encoding="utf-8")
    link = root / "linked"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})
        result = engine.ast_outline(str(root), "linked/private.py")
        assert result["success"] is False
        assert "outside" in result["error"]
        assert "private_marker" not in str(result)
        assert private_source.read_text(encoding="utf-8") == "private_marker = 123\n"
    finally:
        # Both endpoints are owned test paths; remove only the link, not its target.
        assert link.parent.resolve() == root.resolve()
        assert link.resolve() == outside.resolve()
        if os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


def test_batch_replace_preflight_does_not_write_bytecode(tmp_path, monkeypatch):
    target = tmp_path / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    def bytecode_write_forbidden(*_args, **_kwargs):
        raise AssertionError("batch preflight must not call py_compile.compile")

    monkeypatch.setattr(py_compile, "compile", bytecode_write_forbidden)
    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "value = 1", "new": "value = 2"}],
        dry_run=True,
    )

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_batch_replace_is_atomic_on_later_syntax_error(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first = 1\n", encoding="utf-8")
    second.write_text("second = 1\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [
            {"path": "first.py", "old": "first = 1", "new": "first = 2"},
            {"path": "second.py", "old": "second = 1", "new": "second = ("},
        ],
    )

    assert result["success"] is False
    assert "Syntax error" in result["error"]
    assert first.read_text(encoding="utf-8") == "first = 1\n"
    assert second.read_text(encoding="utf-8") == "second = 1\n"


def test_batch_replace_rejects_ambiguous_match(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("value = 1\nvalue = 1\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "value = 1", "new": "value = 2"}],
    )

    assert result["success"] is False
    assert "multiple times" in result["error"]
    assert target.read_text(encoding="utf-8") == "value = 1\nvalue = 1\n"


def test_batch_replace_rejects_dirty_target_file(tmp_path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.test"], cwd=str(tmp_path), capture_output=True, check=True)
    target = tmp_path / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "module.py"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=str(tmp_path), capture_output=True, check=True)
    target.write_text("value = 2\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "value = 2", "new": "value = 3"}],
    )

    assert result["success"] is False
    assert "dirty" in result["error"]
    assert target.read_text(encoding="utf-8") == "value = 2\n"


def _init_git_repo_with_file(tmp_path, contents: str) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.test"], cwd=str(tmp_path), capture_output=True, check=True)
    target = tmp_path / "module.py"
    target.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "add", "module.py"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=str(tmp_path), capture_output=True, check=True)
    return target


def test_batch_replace_allows_clean_target_outside_dirty_hunk(tmp_path):
    target = _init_git_repo_with_file(tmp_path, "value = 1\n\nother = 2\n")
    target.write_text("value = 10\n\nother = 2\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "other = 2", "new": "other = 3"}],
    )

    assert result["success"] is True
    assert result["applied"] is True
    assert target.read_text(encoding="utf-8") == "value = 10\n\nother = 3\n"


def test_batch_replace_rejects_target_overlapping_unowned_dirty_hunk(tmp_path):
    target = _init_git_repo_with_file(tmp_path, "value = 1\nother = 2\n")
    target.write_text("value = 10\nother = 2\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "value = 10", "new": "value = 11"}],
    )

    assert result["success"] is False
    assert "dirty" in result["error"].lower()
    assert target.read_text(encoding="utf-8") == "value = 10\nother = 2\n"


def test_batch_replace_treats_untracked_file_as_unowned_dirty_content(tmp_path):
    _init_git_repo_with_file(tmp_path, "baseline = 1\n")
    target = tmp_path / "new_module.py"
    target.write_text("value = 10\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "new_module.py", "old": "value = 10", "new": "value = 11"}],
    )

    assert result["success"] is False
    assert "dirty" in result["error"].lower()
    assert target.read_text(encoding="utf-8") == "value = 10\n"


def test_batch_replace_allows_overlapping_dirty_hunk_with_verified_owner_scope(tmp_path):
    target = _init_git_repo_with_file(tmp_path, "value = 1\nother = 2\n")
    target.write_text("value = 10\nother = 2\n", encoding="utf-8")
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "value = 10", "new": "value = 11"}],
        owned_paths=["module.py"],
    )

    assert result["success"] is True
    assert result["applied"] is True
    assert target.read_text(encoding="utf-8") == "value = 11\nother = 2\n"


def test_batch_replace_service_forwards_only_matching_active_lease_scope(tmp_path):
    class FakeLeaseStore:
        def list(self, root):
            assert root == str(tmp_path)
            return [
                {"lease_id": "lease_current", "owner": "execution-current", "root": str(tmp_path), "path": "src"},
                {"lease_id": "lease_other", "owner": "execution-other", "root": str(tmp_path), "path": "tests"},
            ]

    class FakeDeterministic:
        def __init__(self):
            self.owned_paths = None

        def batch_replace(self, root, edits, *, dry_run=False, owned_paths=None):
            self.owned_paths = owned_paths
            return {"success": True, "applied": False, "dry_run": dry_run}

    services = object.__new__(LocalAIServices)
    services.config = {"features": {"batch_replacement": True}}
    services.deterministic = FakeDeterministic()

    result = services.batch_replace(
        str(tmp_path),
        [{"path": "src/module.py", "old": "before", "new": "after"}],
        dry_run=True,
        owner="execution-current",
        lease_id="lease_current",
        lease_store=FakeLeaseStore(),
    )

    assert result["success"] is True
    assert services.deterministic.owned_paths == ["src"]


def test_batch_replace_service_rejects_unmatched_claim_without_mutation(tmp_path):
    class FakeLeaseStore:
        def list(self, _root):
            return [{"lease_id": "lease_current", "owner": "execution-current", "root": str(tmp_path), "path": "src"}]

    class FakeDeterministic:
        def batch_replace(self, *_args, **_kwargs):
            pytest.fail("an unmatched owner/lease must never reach replacement")

    services = object.__new__(LocalAIServices)
    services.config = {"features": {"batch_replacement": True}}
    services.deterministic = FakeDeterministic()

    result = services.batch_replace(
        str(tmp_path),
        [{"path": "src/module.py", "old": "before", "new": "after"}],
        owner="execution-other",
        lease_id="lease_current",
        lease_store=FakeLeaseStore(),
    )

    assert result["success"] is False
    assert "lease" in result["error"].lower()


def test_batch_replace_service_allows_actual_owner_lease_for_overlapping_hunk(tmp_path):
    target = _init_git_repo_with_file(tmp_path, "value = 1\nother = 2\n")
    target.write_text("value = 10\nother = 2\n", encoding="utf-8")
    lease_store = ScopeLeaseStore(tmp_path / "state")
    claim = lease_store.claim(
        owner="execution-current",
        root=str(tmp_path),
        paths=["module.py"],
        ttl_seconds=900,
        purpose="batch replacement acceptance test",
    )
    assert claim["success"] is True
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"batch_replacement": True}}
    services.deterministic = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}})

    result = services.batch_replace(
        str(tmp_path),
        [{"path": "module.py", "old": "value = 10", "new": "value = 11"}],
        owner="execution-current",
        lease_id=claim["lease_id"],
        lease_store=lease_store,
    )

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "value = 11\nother = 2\n"


def test_15_prompt_eval():
    services = LocalAIServices.__new__(LocalAIServices)
    template = "Fix the following error in {{language}}: {{error}}"
    variables = {"language": "Python", "error": "IndexError: list index out of range"}
    res = services.prompt_eval({"template": template, "variables": variables})
    assert res["success"] is True
    assert res["rendered_prompt"] == "Fix the following error in Python: IndexError: list index out of range"
    assert res["token_estimate"] > 0


def test_16_env_compatibility(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("pytest>=7.0.0\nrequests>=2.28.0\n", encoding="utf-8")

    engine = DeterministicEngine()
    res = engine.env_compat(str(tmp_path))
    assert res["success"] is True
    assert "python" in res
    assert "dependencies" in res
    assert "requirements.txt" in res["dependencies"]


def test_17_agent_memory_entity_relations(tmp_path: Path):
    state_store = AgentStateStore(tmp_path / "agent_state.sqlite3")
    store = MemoryStore(state_store)
    rec = store.record_relation("auth_module", "depends_on", "crypto_lib", weight=0.95)
    assert rec["success"] is True
    assert rec["source_entity"] == "auth_module"
    assert rec["relation"] == "depends_on"
    assert rec["target_entity"] == "crypto_lib"

    found = store.find_relations("auth_module")
    assert len(found) == 1
    assert found[0]["target_entity"] == "crypto_lib"

    store.record_relation("crypto_lib", "uses", "openssl", weight=0.8)
    trav = store.traverse_graph("auth_module", max_depth=2)
    assert trav["success"] is True
    assert "auth_module" in trav["nodes"]
    assert "crypto_lib" in trav["nodes"]
    assert "openssl" in trav["nodes"]
    assert len(trav["edges"]) >= 2


def test_18_structural_search(tmp_path: Path):
    code_file = tmp_path / "calc.py"
    code_file.write_text("""
def calculate():
    try:
        x = 1 / 0
    except:
        pass
""", encoding="utf-8")

    engine = DeterministicEngine()
    res = engine.structural_search(str(tmp_path), "bare_except")
    assert res["success"] is True
    assert res["count"] >= 1
    assert any(m["structure"] == "bare_except" for m in res["matches"])


def test_19_context_budget(tmp_path: Path):
    f1 = tmp_path / "mod.py"
    f1.write_text("""\"\"\"Long module docstring here.\nLine 2\nLine 3\"\"\"\nimport os\nimport sys\n\ndef run():\n    return 42\n""", encoding="utf-8")

    engine = DeterministicEngine()
    res = engine.context_budget(str(tmp_path), ["mod.py"], max_tokens=100)
    assert res["success"] is True
    assert res["total_tokens"] > 0
    assert any(f["path"] == "mod.py" for f in res["file_breakdown"])
    assert len(res["compressible_regions"]) >= 1


def test_20_git_worktrees_helpers(tmp_path: Path):
    res_list = list_git_worktrees(str(tmp_path))
    assert "success" in res_list
    res_prune = prune_git_worktrees(str(tmp_path))
    assert "success" in res_prune


def test_21_command_broker_powershell_safety(tmp_path: Path):
    broker = CommandBroker(config={"server": {"state_dir": str(tmp_path)}})
    res = broker.run("Remove-Item -Recurse C:\\secret", cwd=str(tmp_path))
    assert res["success"] is False
    assert "blocked" in res["error"].lower() or "dangerous" in res["error"].lower()
