"""An experiment record, not merely a subprocess exit, determines success."""

import json
from pathlib import Path
import pytest

from tools import benchmark_surfaces
from tools import benchmark_native_candidates


@pytest.mark.parametrize("result,exit_code", [
    ({"success": False, "failed_stages": ["queue_admission"]}, 1),
    ({"success": True, "comparison": {"status": "incomparable"}}, 1),
    ({"success": True, "comparison": {"status": "inconclusive"}}, 2),
    ({"success": True, "failed_stages": []}, 0),
])
def test_surface_worker_exit_preserves_failed_or_unavailable_result(tmp_path, monkeypatch, capsys, result, exit_code):
    monkeypatch.setattr(benchmark_surfaces, "run_benchmark", lambda **kwargs: result)
    assert benchmark_surfaces.main([
        "--state-dir", str(tmp_path), "--_benchmark-worker",
    ]) == exit_code
    assert json.loads(capsys.readouterr().out) == result


def test_candidate_benchmark_refuses_state_dir_inside_repo(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    inside_state = repo / "state"

    exit_code = benchmark_native_candidates.main([
        "--case", "simhash",
        "--root", str(repo),
        "--state-dir", str(inside_state),
    ])
    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is False
    assert output["error_type"] == "ValueError"
    assert "outside" in output["error"]


def test_candidate_benchmark_runs_case_and_records_schema(tmp_path, capsys):
    repo = Path.cwd()
    external_state = tmp_path / "ext_state"
    output_file = tmp_path / "result.json"

    exit_code = benchmark_native_candidates.main([
        "--case", "simhash",
        "--root", str(repo),
        "--state-dir", str(external_state),
        "--repetitions", "10",
        "--output", str(output_file),
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


def test_candidate_benchmark_distinguishes_tail_acceptance_gate(tmp_path, capsys):
    repo = Path.cwd()
    external_state = tmp_path / "ext_state_tail"

    # Mock repetitions to verify tail gate logic
    result = benchmark_native_candidates.run_benchmark_case(
        case="json-budget",
        root=repo,
        state_dir=external_state,
        repetitions=1000,
    )
    assert result["success"] is True
    assert result["measurement"]["sample_count"] == 1000
    assert result["measurement"]["tail_sample_gate_met"] is True
    assert "1000+ independent pairs" in result["measurement"]["note"]
