import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from local_ai_hub.commands import CommandBroker
from local_ai_hub.token_router import shrink_signatures
from local_ai_hub.memory import WorkspaceMemoryStore
from local_ai_hub.rag import RAGStore
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.background_gpu import IdleGPUWorker


def test_commands_diagnostics_populated_early():
    with tempfile.TemporaryDirectory() as tmp:
        mock_incident_store = MagicMock()
        mock_incident_store.capture.return_value = None
        mock_incident_store.find_regressions.return_value = []
        broker = CommandBroker({"commands": {"enabled": True, "allow_validation": True}})
        broker.set_incident_store(mock_incident_store)

        # Run a python command that fails with traceback
        res = broker.run("python -c \"raise ValueError('early diagnostic test')\"", tmp)
        assert res["success"] is False
        # Verify diagnostics are populated in res
        assert "diagnostics" in res
        assert len(res["diagnostics"]) > 0
        # Verify incident store capture was called
        assert mock_incident_store.capture.called
        outcome = mock_incident_store.capture.call_args[0][0]
        assert "early diagnostic test" in outcome.error


def test_token_router_shrink_signatures_comments():
    # C# with apostrophe in comment should not treat subsequent braces as string
    cs_code = """
    // It's important to keep this
    public class Service {
        public void Process() {
            int a = 1;
            int b = 2;
            int c = 3;
            int d = 4;
            int e = 5;
            int f = 6;
            int g = 7;
            int h = 8;
            int i = 9;
            int j = 10;
        }
    }
    """
    shrunk = shrink_signatures(cs_code, language="csharp")
    assert "public class Service" in shrunk
    assert "/* ... implementation ... */" in shrunk


def test_token_router_shrink_signatures_python_functions():
    # Python code with two distinct functions
    py_code = """def first_func():
    a = 1
    b = 2
    c = 3
    d = 4

def second_func():
    return 42
"""
    shrunk = shrink_signatures(py_code, language="python")
    assert "first_func" in shrunk
    assert "second_func" in shrunk
    assert "return 42" in shrunk
    assert "..." in shrunk


def test_memory_store_thread_safe_init():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        store = WorkspaceMemoryStore(state_dir)
        assert hasattr(store, "_lock")
        assert store._initialized is True
        res = store.put(str(state_dir), "key1", "val1", "tenant1")
        assert res["success"] is True
        get_res = store.get(str(state_dir), "key1")
        assert get_res["success"] is True
        assert get_res["value"] == "val1"


def test_rag_store_uses_retry_busy():
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        rag = RAGStore({"server": {"state_dir": str(state_dir)}})
        assert rag.db_path.exists()


def test_deterministic_security_audit_multiline():
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp)
        vuln_file = repo_dir / "vuln.py"
        vuln_file.write_text("""import subprocess

def run_cmd():
    subprocess.Popen(
        "ls -la",
        shell=True,
    )
""", encoding="utf-8")
        repo_tools = RepositoryTools({"rag": {"extensions": [".py"]}})
        engine = DeterministicEngine({}, repo_tools)
        audit = engine.security_audit(str(repo_dir))
        assert audit["success"] is True
        assert any(f["title"] == "Shell Injection Risk" and f["line"] == 4 for f in audit["findings"])


def test_repo_tools_iter_files_not_starved_by_assets():
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp)
        # Create 10 dummy asset files that are not in extensions
        for i in range(10):
            (repo_dir / f"image_{i}.png").write_text("png", encoding="utf-8")
        # Create a code file
        code_file = repo_dir / "main.py"
        code_file.write_text("print('hello')", encoding="utf-8")

        tools = RepositoryTools({
            "rag": {"extensions": [".py"]},
            "search": {"max_files": 5},  # small cap to test starvation resistance
        })
        files = list(tools.iter_files(str(repo_dir)))
        assert any(f.name == "main.py" for f in files)


def test_async_jobs_missing_row_safety():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {"server": {"state_dir": tmp}}
        mgr = AsyncJobManager(cfg, None, None, lambda act, payload, t: {"success": True})
        # Executing a nonexistent job_id should return gracefully and not crash
        res = mgr._execute("nonexistent_job_123")
        assert res["success"] is False
        assert "cancelled" in res["error"]
        mgr.close()


def test_background_gpu_cpu_lease_reset():
    worker = IdleGPUWorker({"models": {}, "server": {"state_dir": "."}}, MagicMock())
    assert worker._cpu_lease is False
    worker._cpu_lease = True
    worker.close()
    assert worker._cpu_lease is False
