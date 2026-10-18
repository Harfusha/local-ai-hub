from types import SimpleNamespace

import local_ai_hub.commands as commands


def test_cached_command_preserves_execution_timing_but_measures_current_request(tmp_path, monkeypatch):
    broker = commands.CommandBroker(
        {"server": {"state_dir": str(tmp_path / "state")}, "commands": {"enabled": True}},
        SimpleNamespace(put=lambda *args, **kwargs: "test-artifact"),
        SimpleNamespace(fingerprint=lambda root: {"fingerprint": "unchanged-revision"}),
    )
    monkeypatch.setattr(broker, "_tool_identity", lambda *args, **kwargs: {"version": "test-tool"})
    monkeypatch.setattr(broker, "_unavailable_executable", lambda *args: None)
    executions = []

    def execute(*args, **kwargs):
        executions.append(True)
        return {
            "success": True, "exit_code": 0, "stdout": "pass\n", "stderr": "",
            "duration_ms": 20.0,
            "phase_timings_ms": {"shell_startup_ms": 7.25, "stream_capture_ms": 12.5},
        }

    clock = {"now": 0.0, "step": 0.001}

    def perf_counter():
        clock["now"] += clock["step"]
        return clock["now"]

    monkeypatch.setattr(broker, "_execute", execute)
    monkeypatch.setattr(commands.time, "perf_counter", perf_counter)
    first = broker.run("python -m pytest -q", str(tmp_path))
    clock["step"] = 0.003
    cached = broker.run("python -m pytest -q", str(tmp_path))

    assert first["cache_hit"] is False
    assert cached["cache_hit"] is True
    assert executions == [True]
    assert cached["phase_timings_ms"]["shell_startup_ms"] == 7.25
    assert cached["phase_timings_ms"]["stream_capture_ms"] == 12.5
    for field in ("command_classification_ms",):
        assert first["phase_timings_ms"][field] == 1.0
        assert cached["phase_timings_ms"][field] == 3.0
    # Cache reads may do additional clocked bookkeeping; at least one current
    # 3ms clock tick must replace the historical 1ms lookup measurement.
    assert first["phase_timings_ms"]["result_cache_lookup_ms"] == 1.0
    assert cached["phase_timings_ms"]["result_cache_lookup_ms"] >= 3.0
