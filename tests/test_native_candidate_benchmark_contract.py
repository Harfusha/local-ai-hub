from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from local_ai_hub import token_accounting
from tools import benchmark_native_candidates as benchmark


def test_source_identity_detects_a_dirty_repository(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "sample.txt").write_text("clean", encoding="utf-8")
    subprocess.run(["git", "add", "sample.txt"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
        cwd=root, check=True,
    )

    assert benchmark._get_git_dirty(root) is False
    (root / "sample.txt").write_text("changed", encoding="utf-8")
    assert benchmark._get_git_dirty(root) is True


def test_json_budget_measures_both_implementations_and_alternates_order(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    calls = []

    def baseline(value):
        calls.append(("baseline", value["epoch"]))
        return 42

    def candidate(value):
        calls.append(("candidate", value["epoch"]))
        return 42

    monkeypatch.setattr(token_accounting, "_streaming_json_tokens", baseline)
    monkeypatch.setattr(token_accounting, "json_tokens", candidate)
    result = benchmark.run_benchmark_case("json-budget", root, tmp_path / "state", repetitions=2)

    assert calls == [("baseline", 0), ("candidate", 0), ("candidate", 1), ("baseline", 1)]
    assert all("baseline_ms" in pair and "candidate_ms" in pair for pair in result["samples_summary"])
    assert result["quality_scope"]["verified_parity"] is True
    assert result["source_identity"]["dirty"] is None


def test_json_budget_rejects_token_count_mismatch(monkeypatch, tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(token_accounting, "_streaming_json_tokens", lambda _value: 41)
    monkeypatch.setattr(token_accounting, "json_tokens", lambda _value: 42)

    with pytest.raises(RuntimeError, match="parity"):
        benchmark.run_benchmark_case("json-budget", root, tmp_path / "state", repetitions=1)


def test_synthetic_baseline_cannot_pass_tail_gate(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    result = benchmark.run_benchmark_case("search", root, tmp_path / "state", repetitions=1000)

    assert result["measurement"]["tail_gate_met"] is False
    assert result["measurement"]["baseline_provenance"] == "synthetic_diagnostic"
    assert result["quality_scope"]["verified_parity"] is False


@pytest.mark.parametrize(
    ("dirty", "backend_active", "source_bound", "expected"),
    [(False, True, True, True), (True, True, True, False), (None, True, True, False),
     (False, False, True, False), (False, True, False, False)],
)
def test_tail_gate_requires_clean_bound_source_and_active_candidate(monkeypatch, tmp_path, dirty, backend_active, source_bound, expected):
    root = tmp_path / "repo"
    root.mkdir()
    clock = [0.0]

    def baseline(_value):
        clock[0] += 0.002
        return 42

    def candidate(_value):
        clock[0] += 0.001
        return 42

    monkeypatch.setattr(benchmark, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    monkeypatch.setattr(benchmark, "_get_git_commit", lambda _root: "abc123")
    monkeypatch.setattr(benchmark, "_get_git_dirty", lambda _root: dirty)
    monkeypatch.setattr(token_accounting, "_streaming_json_tokens", baseline)
    monkeypatch.setattr(token_accounting, "json_tokens", candidate)
    monkeypatch.setattr(token_accounting, "_orjson", object() if backend_active else None)
    module_file = (root if source_bound else tmp_path) / "src/local_ai_hub/token_accounting.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("# fixture", encoding="utf-8")
    monkeypatch.setattr(token_accounting, "__file__", str(module_file))

    result = benchmark.run_benchmark_case("json-budget", root, tmp_path / "state", repetitions=1000)

    assert result["measurement"]["tail_gate_met"] is expected
    assert len(result["samples_summary"]) == 1000
