"""An experiment record, not merely a subprocess exit, determines success."""

import pytest

from tools import benchmark_surfaces


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
    import json
    assert json.loads(capsys.readouterr().out) == result
