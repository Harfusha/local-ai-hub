import json
from datetime import datetime
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from local_ai_hub import token_accounting
from tools import benchmark_native_candidates as benchmark
from tools import benchmark_surfaces


@pytest.mark.parametrize("value", [
    4.312797543837288e-05, 1e-7, 1e20, float("nan"),
    {1e20: "value"}, datetime(2026, 1, 2, 3, 4, 5),
])
def test_json_tokens_matches_canonical_stdlib_bytes_with_orjson(monkeypatch, value):
    orjson = pytest.importorskip("orjson")
    monkeypatch.setattr(token_accounting, "_orjson", orjson)
    for length in range(40):
        payload = {"x": value, "pad": "p" * length}
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        expected = max(1, (len(raw) * 10 + 33) // 34)
        assert token_accounting.json_tokens(payload) == expected


@pytest.mark.parametrize("result,exit_code", [
    ({"success": False, "failed_stages": ["queue_admission"]}, 1),
    ({"success": True, "comparison": {"status": "incomparable"}}, 1),
    ({"success": True, "comparison": {"status": "inconclusive"}}, 2),
    ({"success": True, "failed_stages": []}, 0),
])
def test_surface_worker_exit_preserves_failed_or_unavailable_result(tmp_path, monkeypatch, capsys, result, exit_code):
    monkeypatch.setattr(benchmark_surfaces, "run_benchmark", lambda **kwargs: result)
    assert benchmark_surfaces.main(["--state-dir", str(tmp_path), "--_benchmark-worker"]) == exit_code
    assert json.loads(capsys.readouterr().out) == result


def test_candidate_benchmark_refuses_state_dir_inside_repo(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    exit_code = benchmark.main([
        "--case", "simhash", "--root", str(repo), "--state-dir", str(repo / "state"),
    ])
    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["error_type"] == "ValueError"
    assert "outside" in output["error"]


def test_candidate_benchmark_runs_case_and_records_schema(tmp_path, capsys):
    output_file = tmp_path / "result.json"
    exit_code = benchmark.main([
        "--case", "simhash", "--root", str(Path.cwd()), "--state-dir", str(tmp_path / "ext_state"),
        "--repetitions", "10", "--output", str(output_file),
    ])
    assert exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "perf_candidate.v1"
    assert data["success"] is True
    assert data["case"] == "simhash"
    assert data["measurement"]["sample_count"] == 10
    assert data["measurement"]["tail_sample_gate_met"] is False
    assert "p95_ms" in data["measurement"]["candidate_stats"]


def test_candidate_benchmark_distinguishes_tail_acceptance_gate(tmp_path):
    result = benchmark.run_benchmark_case(
        case="json-budget", root=Path.cwd(), state_dir=tmp_path / "ext_state_tail", repetitions=1000,
    )
    assert result["success"] is True
    assert result["measurement"]["sample_count"] == 1000
    assert result["measurement"]["tail_sample_gate_met"] is True
    assert result["measurement"]["baseline_provenance"] == "measured_reference"
    assert len(result["samples_summary"]) == 1000


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
