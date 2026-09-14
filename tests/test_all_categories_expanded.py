import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
import urllib.request

import pytest

from local_ai_hub.agent_blackboard import BlackboardStore
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_tasks import TaskStore, GoalContract, ScopeContext, TaskStatus, AgentScope, TaskCheckpoint
from local_ai_hub.commands import CommandBroker
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.rag import RAGStore
from local_ai_hub.services import generation_cache_key


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@agent.local"], cwd=repo_dir, capture_output=True, check=True)


def test_git_diff_and_history_search(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    f1 = repo / "hello.py"
    f1.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit feat: greeting"], cwd=repo, capture_output=True, check=True)

    # Modify file
    f1.write_text("def hello():\n    # greeting update\n    return 'universe'\n", encoding="utf-8")

    det = DeterministicEngine()
    diff_res = det.git_diff(str(repo), max_lines=100)
    assert diff_res["success"] is True
    assert diff_res["stats"]["insertions"] >= 1
    assert diff_res["stats"]["deletions"] >= 1
    assert len(diff_res["files"]) == 1
    assert diff_res["files"][0]["file"] == "hello.py"

    # Test git history search
    hist_res = det.git_history_search(str(repo), query="greeting")
    assert hist_res["success"] is True
    assert len(hist_res["commits"]) >= 1
    assert "greeting" in hist_res["commits"][0]["message"]


def test_debt_hotspots(tmp_path: Path):
    repo = tmp_path / "repo_hotspots"
    repo.mkdir()
    _init_git_repo(repo)

    f = repo / "complex_logic.py"
    f.write_text("""
def process_data(x):
    if x > 10:
        for i in range(x):
            if i % 2 == 0:
                print(i)
            elif i % 3 == 0:
                print('three')
            else:
                pass
    return x
""", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=repo, capture_output=True, check=True)

    # Add another commit touching the same file
    f.write_text(f.read_text(encoding="utf-8") + "\n# touch\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=repo, capture_output=True, check=True)

    det = DeterministicEngine()
    hotspots_res = det.find_hotspots(str(repo), days=7, limit=10)
    assert hotspots_res["success"] is True
    assert len(hotspots_res["hotspots"]) >= 1
    assert hotspots_res["hotspots"][0]["path"] == "complex_logic.py"
    assert hotspots_res["hotspots"][0]["churn"] >= 2
    assert hotspots_res["hotspots"][0]["debt_score"] > 0


def test_generate_tests_for_diff(tmp_path: Path):
    diff_text = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,3 +1,5 @@
+def add(a, b):
+    return a + b
"""
    det = DeterministicEngine()
    test_gen = det.generate_tests_for_diff(str(tmp_path), diff=diff_text)
    assert test_gen["success"] is True
    assert "test_add_regression" in test_gen["test_skeleton"]
    assert "calculator" in test_gen["target_modules"]


def test_cross_repo_contract(tmp_path: Path):
    backend = tmp_path / "backend"
    backend.mkdir()
    openapi_spec = backend / "openapi.json"
    openapi_spec.write_text(json.dumps({
        "openapi": "3.0.0",
        "paths": {
            "/api/endpoints/users": {"get": {}},
            "/api/endpoints/items": {"post": {}},
        }
    }), encoding="utf-8")

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    client_file = frontend / "api.ts"
    client_file.write_text("""
async function getUsers() {
    return fetch('/api/endpoints/users');
}
async function getLegacy() {
    return axios.get('/api/endpoints/unknown_endpoint');
}
""", encoding="utf-8")

    det = DeterministicEngine()
    contract_res = det.cross_repo_contract(str(backend), str(frontend))
    assert contract_res["success"] is True
    assert "/api/endpoints/users" in contract_res["matched_endpoints"]
    assert "/api/endpoints/unknown_endpoint" in contract_res["unmatched_frontend_calls"]
    assert "/api/endpoints/items" in contract_res["uncalled_backend_endpoints"]


def test_structural_search_multi_lang(tmp_path: Path):
    ts_file = tmp_path / "test.ts"
    ts_file.write_text("""
try {
    doWork();
} catch (e) {
}
const x: any = 123;
""", encoding="utf-8")

    det = DeterministicEngine()
    res_catch = det.structural_search(str(tmp_path), pattern="empty_catch")
    assert res_catch["success"] is True
    assert len(res_catch["matches"]) >= 1

    res_any = det.structural_search(str(tmp_path), pattern="any_type")
    assert res_any["success"] is True
    assert len(res_any["matches"]) >= 1


def test_blackboard_occ_versioning(tmp_path: Path):
    bb = BlackboardStore(tmp_path / "bb.db")

    up1 = bb.update("board1", "sectionA", "initial value", author="agent1")
    assert up1["version"] == 1
    assert up1["content"] == "initial value"

    # Update with correct expected_version
    up2 = bb.update("board1", "sectionA", "second value", author="agent2", expected_version=1)
    assert up2["version"] == 2
    assert up2["content"] == "second value"

    # Update with stale expected_version must fail with version_conflict
    conflict = bb.update("board1", "sectionA", "stale write", author="agent1", expected_version=1)
    assert conflict["success"] is False
    assert conflict["version_conflict"] is True
    assert conflict["current_version"] == 2
    assert conflict["expected_version"] == 1


def test_task_checkpoint_and_rollback(tmp_path: Path):
    state_store = AgentStateStore(db_path=tmp_path / "agent_state.db", enabled=True)
    task_store = TaskStore(state_store)

    test_file = tmp_path / "app.py"
    test_file.write_text("print('version 1')\n", encoding="utf-8")

    contract = GoalContract(goal="test task rollback", acceptance_criteria=(), scope=AgentScope.TASK)
    ctx = ScopeContext(repository_id="repo1", branch="main", task_id="t-rollback")
    task = task_store.create(contract, ctx, actor="agent1")
    task_id = task.task_id

    # Checkpoint 1: saves version 1
    cp1 = TaskCheckpoint(phase="p1", next_action="a1", affected_paths=(str(test_file),), state_data={"step": 1})
    task_store.checkpoint(task_id, cp1, capture_files=True, actor="agent1")

    # Modify file and create Checkpoint 2
    test_file.write_text("print('version 2 - modified')\n", encoding="utf-8")
    cp2 = TaskCheckpoint(phase="p2", next_action="a2", affected_paths=(str(test_file),), state_data={"step": 2})
    task_store.checkpoint(task_id, cp2, capture_files=True, actor="agent1")

    # Modify file further to version 3
    test_file.write_text("print('version 3 - buggy')\n", encoding="utf-8")

    # Rollback should restore checkpoint 1 and file version 1
    rb_res = task_store.rollback(task_id, actor="agent1")
    assert rb_res.task_id == task_id
    assert rb_res.checkpoint.state_data.get("step") == 1
    assert test_file.read_text(encoding="utf-8") == "print('version 1')\n"


def test_curate_training_dataset(tmp_path: Path):
    state_store = AgentStateStore(db_path=tmp_path / "agent_state.db", enabled=True)
    task_store = TaskStore(state_store)

    contract = GoalContract(goal="curate test", acceptance_criteria=(), scope=AgentScope.TASK)
    ctx = ScopeContext(repository_id="repo1", branch="main", task_id="t-curate")
    task = task_store.create(contract, ctx, actor="agent1")
    task_id = task.task_id

    # Append verification receipt and transition
    task_store.add_verification_receipt(task_id, "tests pass", "receipt-1")
    task_store.transition(task_id, TaskStatus.ACTIVE, actor="agent1", reason="start", idempotency_key="act_1")
    task_store.complete(task_id, actor="agent1", reason="done", idempotency_key="comp_1")

    out_file = tmp_path / "dataset.jsonl"
    cur_res = task_store.curate_training_dataset(str(out_file), min_receipts=1, format="jsonl")
    assert cur_res["success"] is True
    assert cur_res["dataset_count"] == 1
    assert out_file.is_file()

    line = json.loads(out_file.read_text(encoding="utf-8").strip())
    assert line["task_id"] == task_id
    assert "curate test" in line["prompt"]


def test_mock_openapi_server(tmp_path: Path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "openapi": "3.0.0",
        "paths": {
            "/api/users": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "example": [{"id": 1, "name": "Alice"}]
                                }
                            }
                        }
                    }
                }
            }
        }
    }), encoding="utf-8")

    broker = CommandBroker({"commands": {}})
    port = 11488
    start_res = broker.mock_server_start(str(tmp_path), spec_path=str(spec), port=port)
    assert start_res["success"] is True

    try:
        status_res = broker.mock_server_status(port)
        assert status_res["running"] is True
        assert status_res["port"] == port

        # Query mock server
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/users")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data.get("mock") is True
            assert data.get("status") == 200
            assert data.get("path") == "/api/users"
    finally:
        stop_res = broker.mock_server_stop(port)
        assert stop_res["success"] is True


class _MockRagServices:
    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        return {"success": True, "embeddings": [[0.1, 0.2] for _ in batch]}


class _MockReranker:
    def rerank(self, query, texts, top_k=8, priority=3):
        return {"success": True, "results": [{"index": i, "score": 1.0} for i in range(len(texts))][:top_k]}


def test_rag_ingest_diagram(tmp_path: Path):
    svg_file = tmp_path / "architecture.svg"
    svg_file.write_text("""<svg xmlns="http://www.w3.org/2000/svg">
<text>Microservice Authentication Architecture</text>
<text>Token Validator Node</text>
</svg>""", encoding="utf-8")

    rag = RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py", ".svg"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": True},
        },
        _MockRagServices(),
        _MockReranker(),
    )
    res = rag.ingest_diagram("test_ws", str(svg_file), caption="System Arch Overview")
    assert res["success"] is True
    assert res["diagram_indexed"] is True

    # Search in workspace for text from diagram
    search_res = rag.search("Authentication Token Validator", tenant="test", workspace="test_ws", top_k=5)
    assert search_res["success"] is True
    assert len(search_res["results"]) >= 1
    assert "architecture" in search_res["results"][0]["path"]


def test_vram_context_scaling():
    policy = ModelExecutionPolicy({
        "models": {"fast_code": "qwen2.5-coder:7b"},
        "model_execution": {"fast": {"context_tokens": 32768, "max_context_tokens": 65536}},
    })
    # If 1GB VRAM, context clamped to 8192
    prof_1g = policy.profile("qwen2.5-coder:7b", requested_ctx=49152, vram_free_mb=1024)
    assert prof_1g.num_ctx == 8192

    # If 3GB VRAM, context clamped to 16384
    prof_3g = policy.profile("qwen2.5-coder:7b", requested_ctx=49152, vram_free_mb=3072)
    assert prof_3g.num_ctx == 16384

    # The model's 32K context cap applies even with 12GB VRAM.
    prof_12g = policy.profile("qwen2.5-coder:7b", requested_ctx=49152, vram_free_mb=12288)
    assert prof_12g.num_ctx == 32768


def test_generation_cache_key_with_format():
    key1 = generation_cache_key(model="qwen2.5-coder:7b", prompt="p", system="s", options={}, think=None, execution=None, format=None)
    key2 = generation_cache_key(model="qwen2.5-coder:7b", prompt="p", system="s", options={}, think=None, execution=None, format="json")
    key3 = generation_cache_key(model="qwen2.5-coder:7b", prompt="p", system="s", options={}, think=None, execution=None, format={"type": "object"})
    assert key1 != key2
    assert key2 != key3
