"""Build layout checks need no compiler or extension execution."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import cython_experiment as experiment


def test_build_uses_external_non_inplace_output(tmp_path, monkeypatch):
    import setuptools

    command = SimpleNamespace()
    calls = []
    binary = tmp_path / "cython_simhash_votes.pyd"

    class Distribution:
        def __init__(self, options):
            pass

        def get_command_obj(self, name):
            assert name == "build_ext"
            return command

        def run_command(self, name):
            assert command.inplace is False
            assert Path(command.build_lib).resolve() == tmp_path.resolve()
            assert Path(command.build_temp).resolve().is_relative_to(tmp_path.resolve())
            binary.write_bytes(b"fixture-not-executable")
            calls.append(name)

    def cythonize(extensions, *, build_dir, compiler_directives):
        assert Path(build_dir).resolve().is_relative_to(tmp_path.resolve())
        return extensions

    monkeypatch.setitem(experiment.sys.modules, "Cython.Build", SimpleNamespace(cythonize=cythonize))
    monkeypatch.setattr(setuptools, "Distribution", Distribution)
    monkeypatch.setattr(experiment.importlib, "import_module", lambda name: SimpleNamespace(__file__=str(binary)))
    original_path = list(experiment.sys.path)
    module = experiment._build_extension(tmp_path)
    assert Path(module.__file__) == binary
    assert calls == ["build_ext"]
    assert experiment.sys.path == original_path


def test_build_refuses_checkout_before_compiler(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        experiment._build_extension(experiment.ROOT / "build-test")


def test_cli_persists_failed_compile_and_nonzero_exit(tmp_path, monkeypatch, capsys):
    def failed(*args, **kwargs):
        raise RuntimeError("compiler unavailable fixture")

    monkeypatch.setattr(experiment, "run", failed)
    output = tmp_path / "result.json"
    assert experiment.main(["--output", str(output)]) == 1
    import json
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["success"] is False
    assert result["error_type"] == "RuntimeError"
    assert result["parity"] is None
    assert result["production_enabled"] is False


def test_experiment_adapter_matches_production_with_mathematical_fixture():
    module = SimpleNamespace(simhash_votes=experiment._python_votes)
    result = experiment._check_parity(module)
    assert result == {"uint64_cases": 11, "production_text_cases": 11}

def test_indexing_workflow_measures_parity_and_schema():
    module = SimpleNamespace(simhash_votes=experiment._python_votes)
    results = experiment._measure_indexing_workflow(module, chunk_counts=(20,))
    assert len(results) == 2  # cold and warm
    for item in results:
        assert item["chunk_count"] == 20
        assert item["regime"] in ("cold", "warm")
        assert "simhash_speedup" in item
        assert "workflow_wall_reduction_pct" in item
        assert "workflow_cpu_reduction_pct" in item
        assert "simhash_share_of_workflow_pct" in item
        assert "kernel_gate_met" in item
        assert "workflow_gate_met" in item
