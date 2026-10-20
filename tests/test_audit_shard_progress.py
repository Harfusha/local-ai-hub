import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _isolated_plugin():
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_pytest_shards.py"
    spec = importlib.util.spec_from_file_location("isolated_audit_shard_progress", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._state = {"reports": []}
    return module


def test_progress_writes_wait_until_test_fixtures_are_restored():
    module = _isolated_plugin()
    writes = []
    module._write_manifest = lambda: writes.append(True)
    report = SimpleNamespace(nodeid="test_case", when="call", outcome="passed", duration=0, failed=False)
    for _ in range(30):
        module.pytest_runtest_logreport(report)
    assert writes == []
    report.when = "teardown"
    module.pytest_runtest_logreport(report)
    assert writes == [True]


def test_transient_progress_failure_does_not_replace_test_result():
    module = _isolated_plugin()
    module._write_manifest = lambda: (_ for _ in ()).throw(NotImplementedError("patched pathlib"))
    report = SimpleNamespace(nodeid="test_case", when="teardown", outcome="failed", duration=0, failed=True)
    module.pytest_runtest_logreport(report)
    assert module._state["reports"][0]["outcome"] == "failed"
    writes = []
    module._write_manifest = lambda: writes.append(True)
    module.pytest_sessionfinish(None, 1)
    assert writes == [True]
    assert module._state["session_finished"] is True
    assert module._state["exit_status"] == 1
