"""Regression test suite for Audit Round 5 findings (B01 through B19).
Documented in docs/AUDIT_ROUND_5_2026-11-08.md.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.normalizer import postprocess_model_output
from local_ai_hub.resilience import RecoveryJournal
from local_ai_hub.retrieval import _SOURCE_SUFFIXES


def test_t5_01_model_policy_13b_is_not_small():
    """T5-01 (B02): ModelExecutionPolicy does not classify 13B, 23B, 33B models as small 3B models."""
    policy = ModelExecutionPolicy({})
    # Small models
    assert policy._is_small_model("qwen2.5-coder:1.5b") is True
    assert policy._is_small_model("qwen2.5-coder:3b") is True
    assert policy._is_small_model("llama3.2:3b") is True
    assert policy._is_small_model("deepseek-r1:1.5b") is True

    # Heavy / non-small models that contain substring '3b' or similar
    assert policy._is_small_model("qwen:13b") is False
    assert policy._is_small_model("model:23b") is False
    assert policy._is_small_model("custom:33b") is False
    assert policy._is_small_model("qwen2.5-coder:7b") is False
    assert policy._is_small_model("qwen2.5:14b") is False
    assert policy._is_small_model("qwen2.5:32b") is False


def test_t5_02_retrieval_source_suffixes():
    """T5-02 (B04): _SOURCE_SUFFIXES includes .php, .rb, .vue, .svelte."""
    for ext in (".php", ".rb", ".vue", ".svelte", ".py", ".go", ".rs", ".ts"):
        assert ext in _SOURCE_SUFFIXES, f"Missing {ext} in _SOURCE_SUFFIXES"


def test_t5_03_normalizer_preserves_code_done_stop_token():
    """T5-03 (B10): postprocess_model_output preserves [DONE] token when embedded inside code assertions."""
    code_text = 'def test_stream():\n    assert resp == "[DONE]"\n'
    cleaned, _ = postprocess_model_output(code_text, role="code")
    assert 'assert resp == "[DONE]"' in cleaned

    # Standalone trailing [DONE] stop token at end of stream is stripped
    chat_text = "Here is the response text.\n[DONE]"
    cleaned_chat, _ = postprocess_model_output(chat_text, role="general")
    assert "[DONE]" not in cleaned_chat
    assert cleaned_chat == "Here is the response text."


def test_t5_04_recovery_journal_finish_cas_running(tmp_path: Path):
    """T5-04 (B13): RecoveryJournal write completion only updates records in 'running' state."""
    journal = RecoveryJournal(state_dir=tmp_path)
    res = journal.begin("req_1", action="generate", payload={"prompt": "hi"})
    assert res.get("claimed") is True

    # Manually transition req_1 to 'failed' in database
    con = journal._connect()
    try:
        con.execute("UPDATE requests SET state = 'failed' WHERE request_id = 'req_1'")
        con.commit()
    finally:
        con.close()

    # Late finish with success=True should not overwrite the terminal failed state
    journal._write_completion_batch([("req_1", "done", time.time(), "late success", 200, "", 1)])

    con = journal._connect()
    try:
        row = con.execute("SELECT state FROM requests WHERE request_id = 'req_1'").fetchone()
        assert row[0] == "failed"
    finally:
        con.close()


def test_t5_05_root_family_budget_coalesced_status_handled():
    """T5-05 (B01): RootFamilyBudget coalesces identical scope and does not double count."""
    from local_ai_hub.budget import RootFamilyBudget
    budget = RootFamilyBudget(default_limit=200, max_active_scopes=1)
    res1 = budget.reserve("fam", input_tokens=100, task_id="t1", scope="scope1")
    assert res1["status"] == "accepted"
    assert budget.used_tokens("fam") == 100

    # Second call with same scope coalesces without increasing tokens
    res2 = budget.reserve("fam", input_tokens=100, task_id="t1", scope="scope1")
    assert res2["status"] == "coalesced"
    assert budget.used_tokens("fam") == 100


def test_t5_06_typescript_nodenext_import_resolution(tmp_path: Path):
    """T5-06 (B06): _resolve_relative_module resolves ./user.js to user.ts in TS projects."""
    from local_ai_hub.code_index_demand import _resolve_relative_module
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "user.ts").write_text("export const user = 1;\n", encoding="utf-8")
    eligible = {"src/main.ts", "src/user.ts"}
    res = _resolve_relative_module(
        tmp_path,
        "src/main.ts",
        "./user.js",
        eligible,
        None,
        extensions=(".ts", ".tsx", ".js"),
    )
    assert res == "src/user.ts"


def test_t5_07_rust_nested_module_resolution():
    """T5-07 (B07): _rust_import_candidates resolves mod bar; in src/foo.rs to src/foo/bar.rs."""
    from local_ai_hub.code_index_demand import _rust_import_candidates
    source = "pub mod bar;\n"
    eligible = {"src/foo.rs", "src/foo/bar.rs"}
    candidates = _rust_import_candidates("src/foo.rs", source, eligible)
    assert "src/foo/bar.rs" in candidates


def test_t5_08_go_root_package_import(tmp_path: Path):
    """T5-08 (B18): _go_import_candidates resolves root package import matching module_name."""
    from local_ai_hub.code_index_demand import _go_import_candidates
    (tmp_path / "go.mod").write_text("module example.com/tool\n\ngo 1.22\n", encoding="utf-8")
    source = 'package main\n\nimport "example.com/tool"\n'
    eligible = {"main.go", "tool.go", "sub/sub.go"}
    candidates = _go_import_candidates(tmp_path, source, eligible)
    assert "main.go" in candidates
    assert "tool.go" in candidates
    assert "sub/sub.go" not in candidates


def test_t5_09_circuit_breaker_probe_generation():
    """T5-09 (B09): CircuitBreakerRegistry ignores late outcomes with outdated probe generation."""
    from local_ai_hub.resilience import CircuitBreakerRegistry
    cb = CircuitBreakerRegistry(failure_threshold=1, cooldown_seconds=0.01, probe_timeout_seconds=0.01)
    cb.failure("modelA")
    assert cb.status()["modelA"]["open"] is True

    time.sleep(0.02)
    assert cb.allow("modelA") is True
    gen1 = cb.probe_generation("modelA")

    time.sleep(0.02)
    assert cb.allow("modelA") is True
    gen2 = cb.probe_generation("modelA")
    assert gen2 > gen1

    cb.success("modelA", probe_generation=gen1)
    assert cb.probe_generation("modelA") == gen2


def test_t5_10_paired_retrieval_delta_mixed_scope_handled():
    """T5-10 (B14): paired_retrieval_delta catches mixed measurement scopes without raising KeyError."""
    from local_ai_hub.evaluation_quality import paired_retrieval_delta
    baseline = {
        "retrieval": [
            {
                "case": "c1",
                "query": "find users",
                "expected_path": "users.py",
                "metrics": {"status": "measured", "recall_at_k": 1.0, "reciprocal_rank": 1.0, "citation_validity": 1.0},
            },
            {
                "case": "c2",
                "query": "find auth",
                "expected_path": "auth.py",
                "expected_symbols": {"auth.py": ["auth_func"]},
                "intent": "production",
                "metrics": {
                    "status": "measured", "recall_at_k": 1.0, "reciprocal_rank": 1.0, "citation_validity": 1.0,
                    "measurement_scope": "symbol_ast", "k": 5, "expected_symbol_recall_at_k": 1.0,
                    "citation_precision": 1.0, "source_evidence_sufficient": True,
                },
            },
        ]
    }
    candidate = dict(baseline)
    res = paired_retrieval_delta(baseline, candidate)
    assert res["success"] is False
    assert "mixed" in res["reason"] or "differ" in res["reason"]


def test_t5_11_php_psr4_import_uses_composer_mapping(tmp_path: Path):
    """R5-03 (B03): PSR-4 import resolves mapped service, not same-basename decoys."""
    from local_ai_hub.code_index_demand import one_hop_related_files
    from local_ai_hub.repo_tools import RepositoryTools

    (tmp_path / "composer.json").write_text(
        '{"autoload":{"psr-4":{"App\\\\":"src/"}}}', encoding="utf-8"
    )
    controller = tmp_path / "src" / "Http" / "InvoiceController.php"
    service = tmp_path / "src" / "Services" / "InvoiceService.php"
    decoy = tmp_path / "vendor" / "Legacy" / "InvoiceService.php"
    controller.parent.mkdir(parents=True)
    service.parent.mkdir(parents=True)
    decoy.parent.mkdir(parents=True)
    controller.write_text(
        "<?php\nnamespace App\\Http;\nuse App\\Services\\InvoiceService;\n",
        encoding="utf-8",
    )
    service.write_text("<?php\nnamespace App\\Services;\nclass InvoiceService {}\n", encoding="utf-8")
    decoy.write_text("<?php\nnamespace Legacy;\nclass InvoiceService {}\n", encoding="utf-8")

    eligible = {
        "src/Http/InvoiceController.php",
        "src/Services/InvoiceService.php",
        "vendor/Legacy/InvoiceService.php",
    }
    neighbors = one_hop_related_files(
        tmp_path,
        ["src/Http/InvoiceController.php"],
        eligible,
        RepositoryTools({}),
    )

    assert neighbors == ["src/Services/InvoiceService.php"]


def test_t5_12_czech_implementation_query_activates_source_first():
    """R5-04 (B05): Czech implementation intent activates source-context ranking."""
    from local_ai_hub.retrieval import is_source_context_query

    assert is_source_context_query("Najdi chybu ve funkci UsersController")
    assert is_source_context_query("Oprav tuto komponentu")


def test_t5_13_czech_vision_fix_prompt_uses_repository_context(tmp_path: Path, monkeypatch):
    """R5-13 (B16): Czech visual repair request activates the bounded fix workflow."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import local_ai_hub.vision_service as vision
    from local_ai_hub.vision_contracts import VisionParseResult

    prepared = SimpleNamespace(
        images=["image"], image_artifact_id="", bundle_artifact_id="",
        bundle_context={}, frontend_bundle={"capture": True}, model_context=None, image_size=None,
    )
    parsed = VisionParseResult(summary="Visual issue found")
    repo_tools = MagicMock()
    repo_tools.context_pack.return_value = {"success": True, "files": []}
    runtime = MagicMock()
    runtime.request.side_effect = lambda endpoint, *args, **kwargs: (
        {"response": "{}"} if endpoint == "/api/generate" else {}
    )

    monkeypatch.setattr(vision, "select_vision_model", lambda *args: ("vision-local", None))
    monkeypatch.setattr(vision, "prepare_vision_inputs", lambda **kwargs: prepared)
    monkeypatch.setattr(
        vision,
        "build_vision_request",
        lambda **kwargs: SimpleNamespace(payload={}, prompt_context="prompt", schema=None),
    )
    monkeypatch.setattr(vision, "vision_request_timeout", lambda *_args: 1.0)
    monkeypatch.setattr(vision, "vision_capability_error", lambda *_args: None)
    monkeypatch.setattr(vision, "vision_generation_error", lambda *_args: None)
    monkeypatch.setattr(vision, "parse_vision_result", lambda *_args, **_kwargs: parsed)
    monkeypatch.setattr(vision, "bound_vision_result", lambda value: value)
    monkeypatch.setattr(vision, "build_coder_context", lambda *_args, **_kwargs: {"terminal": False})

    service = vision.VisionService(
        config={"ollama": {"enabled": False}},
        runtime=runtime,
        artifacts=MagicMock(),
        model_policy=None,
        repo_tools=repo_tools,
        max_output_tokens=128,
    )
    result = service.run({
        "prompt": "Oprav tuto komponentu",
        "image": "image",
        "root": str(tmp_path),
    })

    assert result["success"] is True
    repo_tools.context_pack.assert_called_once()
    assert repo_tools.context_pack.call_args.args[0] == str(tmp_path)


def test_t5_14_failed_context_warmup_can_retry_after_short_backoff():
    """R5-14 (B17): Failed warmup keeps only short backoff, then permits retry."""
    import threading

    from local_ai_hub.context_warmup import ContextWarmup

    warmup = ContextWarmup()
    failed_calls = []

    def fail_once():
        failed_calls.append("failed")
        raise RuntimeError("temporary contention")

    try:
        assert warmup.submit("repo:task", fail_once)
        warmup._queue.join()
        assert failed_calls == ["failed"]
        assert not warmup.submit("repo:task", lambda: {"success": True})

        time.sleep(1.05)
        assert warmup.submit("repo:task", lambda: {"success": True})
        warmup._queue.join()
        assert warmup.submit("repo:task", lambda: {"success": True}) is False
    finally:
        warmup.close()


def test_t5_15_csharp_using_does_not_follow_basename_only(tmp_path: Path):
    """B19: C# namespace resolver does not promote a basename-only decoy."""
    from local_ai_hub.code_index_demand import one_hop_related_files
    from local_ai_hub.repo_tools import RepositoryTools

    source = tmp_path / "Program.cs"
    decoy = tmp_path / "src" / "IO.cs"
    decoy.parent.mkdir()
    source.write_text("using System.IO;\nclass Program {}\n", encoding="utf-8")
    decoy.write_text("namespace MyApplication.IO;\nclass IO {}\n", encoding="utf-8")

    eligible = {"Program.cs", "src/IO.cs"}
    assert one_hop_related_files(
        tmp_path, ["Program.cs"], eligible, RepositoryTools({}),
    ) == []
