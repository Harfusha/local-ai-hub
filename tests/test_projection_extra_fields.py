from __future__ import annotations

from local_ai_hub.projection import AgentProjector


def test_default_projection_strips_hashes_and_telemetry():
    projector = AgentProjector({})
    payload = {
        "success": True,
        "root": "/test",
        "engine": "git-grep",
        "scanned_files": 4,
        "candidate_context_tokens_est": 1072,
        "progressive_disclosure": True,
        "cache_hit": False,
        "cache": "workspace-miss",
        "terms": ["agentprojector"],
        "results": [
            {
                "path": "src/local_ai_hub/app.py",
                "start_line": 28,
                "end_line": 38,
                "text": "import something",
                "file_sha256": "d45b95b1ac9b39f03c92b5d9bb1216e5a162e1b6d369a9f9be922ce9f42ada61",
                "content_hash": "d45b95b1ac9b39f03c92b5d9bb1216e5a162e1b6d369a9f9be922ce9f42ada61",
                "evidence_id": "E3117854690107742d581",
            }
        ],
    }

    projected = projector.project(payload, agent="generic", task_kind="search")

    assert projected["success"] is True
    assert projected["root"] == "/test"
    # Noise and plumbing keys must be stripped by default
    assert "file_sha256" not in projected["results"][0]
    assert "content_hash" not in projected["results"][0]
    assert "candidate_context_tokens_est" not in projected
    assert "progressive_disclosure" not in projected
    assert "engine" not in projected
    assert "scanned_files" not in projected
    assert "cache" not in projected
    assert "cache_hit" not in projected

    # Essential fields must be preserved
    assert projected["results"][0]["path"] == "src/local_ai_hub/app.py"
    assert projected["results"][0]["start_line"] == 28
    assert projected["results"][0]["end_line"] == 38
    assert projected["results"][0]["evidence_id"] == "E3117854690107742d581"
    assert projected["results"][0]["text"] == "import something"


def test_projection_with_extra_fields_retains_requested_keys():
    projector = AgentProjector({})
    payload = {
        "success": True,
        "root": "/test",
        "engine": "git-grep",
        "scanned_files": 4,
        "candidate_context_tokens_est": 1072,
        "results": [
            {
                "path": "src/local_ai_hub/app.py",
                "start_line": 28,
                "end_line": 38,
                "file_sha256": "d45b95b1ac9b39f03c92b5d9bb1216e5a162e1b6d369a9f9be922ce9f42ada61",
                "content_hash": "d45b95b1ac9b39f03c92b5d9bb1216e5a162e1b6d369a9f9be922ce9f42ada61",
                "evidence_id": "E3117854690107742d581",
            }
        ],
    }

    projected = projector.project(
        payload, agent="generic", task_kind="search", extra_fields=["file_sha256", "engine"]
    )

    # Explicitly requested extra fields must be present
    assert projected["results"][0]["file_sha256"] == "d45b95b1ac9b39f03c92b5d9bb1216e5a162e1b6d369a9f9be922ce9f42ada61"
    assert projected["engine"] == "git-grep"

    # Non-requested extra fields must remain stripped
    assert "content_hash" not in projected["results"][0]
    assert "scanned_files" not in projected
    assert "candidate_context_tokens_est" not in projected


def test_mcp_compact_passes_extra_fields():
    from local_ai_hub.mcp_server import _compact

    payload = {
        "success": True,
        "root": "/test",
        "engine": "git-grep",
        "results": [
            {
                "path": "test.py",
                "start_line": 1,
                "end_line": 2,
                "text": "abc",
                "file_sha256": "1234567890abcdef",
            }
        ],
    }

    default_out = _compact(payload, "search")
    assert "file_sha256" not in default_out["results"][0]
    assert "engine" not in default_out

    with_extra = _compact(payload, "search", extra_fields=["file_sha256", "engine"])
    assert with_extra["results"][0]["file_sha256"] == "1234567890abcdef"
    assert with_extra["engine"] == "git-grep"


def test_all_mcp_tools_expose_extra_fields():
    import inspect
    from local_ai_hub import mcp_server

    for tool_fn in (
        mcp_server.local_ai_repo,
        mcp_server.local_ai_rag,
        mcp_server.local_ai_command,
        mcp_server.local_ai_coord,
        mcp_server.local_ai_artifact,
        mcp_server.local_ai_status,
        mcp_server.local_ai_task,
        mcp_server.local_ai_work,
    ):
        sig = inspect.signature(tool_fn)
        assert "extra_fields" in sig.parameters, f"extra_fields missing in {tool_fn.__name__}"


def test_clean_empty_values():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({"agent_output": {"strip_empty": True}})
    data = {
        "success": True,
        "exit_code": 0,
        "active": False,
        "empty_str": "",
        "empty_list": [],
        "empty_dict": {},
        "none_val": None,
        "nested": {
            "valid": "ok",
            "inner_empty": "",
            "inner_list": [],
        },
    }
    projected = projector.project(data, agent="generic")
    assert projected["success"] is True
    assert projected["exit_code"] == 0
    assert projected["active"] is False
    assert "empty_str" not in projected
    assert "empty_list" not in projected
    assert "empty_dict" not in projected
    assert "none_val" not in projected
    assert projected["nested"] == {"valid": "ok"}


def test_coalesce_overlapping_snippets():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({"agent_output": {"coalesce_snippets": True}})
    data = {
        "success": True,
        "results": [
            {
                "path": "app.py",
                "start_line": 10,
                "end_line": 15,
                "text": "10: line 10\n11: line 11\n12: line 12\n13: line 13\n14: line 14\n15: line 15",
            },
            {
                "path": "app.py",
                "start_line": 14,
                "end_line": 18,
                "text": "14: line 14\n15: line 15\n16: line 16\n17: line 17\n18: line 18",
            },
            {
                "path": "other.py",
                "start_line": 1,
                "end_line": 2,
                "text": "1: other",
            },
        ],
    }
    projected = projector.project(data, agent="generic", task_kind="search")
    assert len(projected["results"]) == 2
    app_hit = projected["results"][0]
    assert app_hit["path"] == "app.py"
    assert app_hit["start_line"] == 10
    assert app_hit["end_line"] == 18
    # Merged lines must not duplicate line 14 and 15
    assert app_hit["text"].count("line 14") == 1
    assert app_hit["text"].count("line 15") == 1
    assert "line 18" in app_hit["text"]


def test_strip_terms_and_redundant_root():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    data = {
        "success": True,
        "root": ".",
        "terms": ["my_query"],
        "results": [],
    }
    projected = projector.project(data, agent="generic", task_kind="search")
    assert "terms" not in projected

    # Can be retained via extra_fields
    with_extra = projector.project(data, agent="generic", task_kind="search", extra_fields=["terms"])
    assert with_extra["terms"] == ["my_query"]


def test_clean_command_output_on_success():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    success_cmd = {
        "success": True,
        "exit_code": 0,
        "command": "pytest -q",
        "stdout": "5 passed",
        "stderr": "",
        "summary": "Command completed with exit code 0.",
    }
    projected = projector.project(success_cmd, agent="generic", task_kind="command")
    assert projected["exit_code"] == 0
    assert projected["stdout"] == "5 passed"
    assert "stderr" not in projected
    assert "summary" not in projected

    fail_cmd = {
        "success": False,
        "exit_code": 1,
        "command": "pytest -q",
        "stdout": "",
        "stderr": "AssertionError: failed",
        "summary": "Command failed with exit code 1",
    }
    fail_proj = projector.project(fail_cmd, agent="generic", task_kind="command")
    assert fail_proj["exit_code"] == 1
    assert fail_proj["stderr"] == "AssertionError: failed"
    assert fail_proj["summary"] == "Command failed with exit code 1"


def test_prune_stacktrace():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({"agent_output": {"prune_stacktraces": True}})
    raw_tb = (
        "Traceback (most recent call last):\n"
        '  File "C:\\Python313\\Lib\\site-packages\\pytest\\runner.py", line 120, in pytest_runtest_protocol\n'
        '  File "C:\\Python313\\Lib\\site-packages\\pluggy\\callers.py", line 80, in _multicall\n'
        '  File "C:\\Python313\\Lib\\site-packages\\pytest\\main.py", line 250, in wrap_session\n'
        '  File "src/local_ai_hub/app.py", line 42, in my_func\n'
        "    raise ValueError('invalid parameter')\n"
        "ValueError: invalid parameter"
    )
    cmd_data = {
        "success": False,
        "exit_code": 1,
        "stderr": raw_tb,
    }
    projected = projector.project(cmd_data, agent="generic", task_kind="command")
    assert "vendor frames omitted" in projected["stderr"]
    assert "src/local_ai_hub/app.py" in projected["stderr"]
    assert "ValueError: invalid parameter" in projected["stderr"]
    assert "runner.py" not in projected["stderr"]


def test_format_text_search():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    data = {
        "success": True,
        "results": [
            {
                "path": "app.py",
                "start_line": 10,
                "end_line": 12,
                "text": "10: def foo():\n11:     return 42",
            }
        ],
    }
    projected = projector.project(data, agent="generic", task_kind="search", extra_fields=["format:text"])
    assert projected.get("format") == "text"
    assert "--- app.py:10-12 ---" in projected.get("text", "")
    assert "return 42" in projected.get("text", "")
    assert "results" not in projected


def test_trim_diff_context():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({"agent_output": {"trim_diff_context": True}})
    diff_text = (
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -10,7 +10,7 @@\n"
        " ctx1\n"
        " ctx2\n"
        " ctx3\n"
        "-old_code\n"
        "+new_code\n"
        " ctx4\n"
        " ctx5\n"
        " ctx6\n"
    )
    data = {
        "success": True,
        "diff": diff_text,
    }
    projected = projector.project(data, agent="generic", task_kind="review_diff")
    # Outer context lines should be trimmed, while keeping 1 context line around changes
    trimmed = projected["diff"]
    assert "-old_code" in trimmed
    assert "+new_code" in trimmed
    assert "--- a/file.py" in trimmed
    assert "ctx3" in trimmed
    assert "ctx4" in trimmed
    assert "ctx1" not in trimmed
    assert "ctx6" not in trimmed


def test_flatten_symbols():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({"agent_output": {"flat_symbols": True}})
    data = {
        "success": True,
        "symbols": [
            {
                "name": "MyClass",
                "path": "app.py",
                "line": 15,
                "kind": "class",
                "docstring": "Very long documentation string...",
                "edges": [{"to": "OtherClass", "kind": "inherits"}],
                "references": [{"file": "main.py", "line": 50}],
                "complexity": {"cyclomatic": 12},
            }
        ],
    }
    projected = projector.project(data, agent="generic", task_kind="architecture")
    sym = projected["symbols"][0]
    assert sym["name"] == "MyClass"
    assert sym["path"] == "app.py"
    assert sym["line"] == 15
    assert sym["kind"] == "class"
    assert "edges" not in sym
    assert "references" not in sym
    assert "docstring" not in sym
    assert "complexity" not in sym


def test_clean_command_output_strips_repo_state_and_classification():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    cmd_data = {
        "success": True,
        "exit_code": 0,
        "stdout": "hello",
        "duration_ms": 45.0,
        "classification": {
            "class": "read",
            "cacheable": True,
            "allowed": True,
            "reason": "python inline read",
        },
        "repo_state": {
            "success": True,
            "root": "/repo",
            "kind": "git",
            "head": "abc1234",
            "dirty": True,
            "changed_files": 42,
            "changed_paths": [f"file_{i}.py" for i in range(42)],
            "fingerprint": "hash123",
        },
        "timed_out": False,
        "cancelled": False,
        "aborted_interactive": False,
        "output_truncated": False,
        "cache_hit": False,
        "coalesced": False,
        "summary": "hello",
    }
    projected = projector.project(cmd_data, agent="generic", task_kind="command")

    # Essential fields must be preserved
    assert projected["success"] is True
    assert projected["exit_code"] == 0
    assert projected["stdout"] == "hello"
    assert projected["duration_ms"] == 45.0

    # Bloat & low-value keys must be stripped
    assert "repo_state" not in projected
    assert "classification" not in projected
    assert "timed_out" not in projected
    assert "cancelled" not in projected
    assert "aborted_interactive" not in projected
    assert "output_truncated" not in projected
    assert "cache_hit" not in projected
    assert "coalesced" not in projected
    assert "summary" not in projected


def test_clean_command_output_preserves_repo_state_and_classification_with_extra_fields():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    cmd_data = {
        "success": True,
        "exit_code": 0,
        "stdout": "ok",
        "classification": {"class": "read", "allowed": True},
        "repo_state": {
            "root": "/repo",
            "changed_files": 50,
            "changed_paths": [f"file_{i}.py" for i in range(50)],
        },
    }
    projected = projector.project(
        cmd_data,
        agent="generic",
        task_kind="command",
        extra_fields=["repo_state", "classification"],
    )

    assert "repo_state" in projected
    assert "classification" in projected
    assert projected["classification"]["class"] == "read"
    # changed_paths must be bounded when retained
    assert len(projected["repo_state"]["changed_paths"]) <= 10


def test_clean_command_output_retains_true_flags():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    timed_out_cmd = {
        "success": False,
        "timed_out": True,
        "cancelled": False,
        "error": "command timed out",
    }
    projected = projector.project(timed_out_cmd, agent="generic", task_kind="command")
    assert projected["timed_out"] is True
    assert "cancelled" not in projected


def test_clean_task_output_strips_telemetry_and_profile():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    task_res = {
        "success": True,
        "model": "qwen2.5-coder:7b",
        "requested_model": "qwen2.5-coder:7b",
        "text": "2",
        "prompt_eval_duration_ns": 117409000,
        "eval_duration_ns": 30035000,
        "execution_profile": {
            "tier": "fast",
            "num_ctx": 32768,
            "max_ctx": 32768,
            "parallel_limit": 2,
            "think": False,
            "prompt_budget_tokens": 28000,
        },
        "fallback_used": False,
        "latency": {"queue_wait_ms": 5206.3, "service_ms": 203.9},
        "route": {
            "task_type": "reasoning",
            "complexity_score": 0,
            "complexity": "fast",
            "model": "qwen2.5-coder:7b",
        },
    }
    projected = projector.project(task_res, agent="generic", task_kind="reason")

    assert projected["success"] is True
    assert projected["model"] == "qwen2.5-coder:7b"
    assert projected["text"] == "2"

    assert "prompt_eval_duration_ns" not in projected
    assert "eval_duration_ns" not in projected
    assert "execution_profile" not in projected
    assert "fallback_used" not in projected
    assert "latency" not in projected
    assert "route" not in projected
    assert "requested_model" not in projected


def test_clean_rag_search_strips_search_cache():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    rag_res = {
        "success": True,
        "workspace": "main",
        "results": [{"text": "chunk1"}],
        "search_cache": {
            "hit": False,
            "coalesced": False,
            "revision": "08b27477751c5a4ccb930e3e7c7443f02b91df990d469b7d1268197bee4b1221",
        },
    }
    projected = projector.project(rag_res, agent="generic", task_kind="search")
    assert projected["success"] is True
    assert "search_cache" not in projected


def test_clean_repo_search_and_profile():
    from local_ai_hub.projection import AgentProjector

    projector = AgentProjector({})
    search_res = {
        "success": True,
        "root": "/repo",
        "results": [],
        "targeted": True,
        "preprocessed_hit": True,
    }
    projected_search = projector.project(search_res, agent="generic", task_kind="search")
    assert "targeted" not in projected_search
    assert "preprocessed_hit" not in projected_search

    profile_res = {
        "success": True,
        "root": "/repo",
        "languages": [{"name": "Python", "files": 10}],
        "note": "Validation commands are detected/suggested only; Local AI Hub does not execute project code.",
        "cache_hit": False,
        "cache": "workspace-miss",
    }
    projected_profile = projector.project(profile_res, agent="generic", task_kind="profile")
    assert "note" not in projected_profile
    assert "cache" not in projected_profile
    assert "cache_hit" not in projected_profile

    status_res = {
        "success": True,
        "enabled": True,
        "phases": ["inventory", "hash", "code_index", "deterministic", "serena", "codegraph", "lexical", "rag", "files", "modules", "project", "hot_queries", "complete"],
    }
    projected_status = projector.project(status_res, agent="generic", task_kind="status")
    assert "phases" not in projected_status


