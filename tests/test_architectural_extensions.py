import io
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

from local_ai_hub.agent_events import SwarmPubSub
from local_ai_hub.commands import CommandBroker, _BoundedStreamBuffer, _redact_secrets
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.process_utils import (
    atomic_write_file,
    create_job_object_kill_on_close,
    assign_process_to_job,
)
from local_ai_hub.sqlite_support import wal_checkpoint_truncate, auto_checkpoint_wal


def test_sqlite_wal_checkpoint_and_auto_truncate(tmp_path: Path):
    db_file = tmp_path / "test_wal.db"
    con = sqlite3.connect(db_file)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
    con.executemany("INSERT INTO items (val) VALUES (?)", [(f"val_{i}",) for i in range(500)])
    con.commit()
    con.close()

    res = wal_checkpoint_truncate(db_file)
    assert res["success"] is True
    assert res["busy"] == 0

    auto_res = auto_checkpoint_wal(db_file, max_wal_bytes=1)
    assert auto_res["success"] is True


def test_atomic_write_file(tmp_path: Path):
    target = tmp_path / "subdir" / "atomic.txt"
    content = "Hello, atomic world!\nLine 2."
    written = atomic_write_file(target, content)
    assert written == target
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == content

    # Overwrite with bytes
    binary_content = b"\x00\x01\x02\x03\xff"
    atomic_write_file(target, binary_content)
    assert target.read_bytes() == binary_content


def test_windows_job_object_helpers():
    job = create_job_object_kill_on_close()
    if os.name == "nt":
        if job:
            assigned = assign_process_to_job(job, os.getpid())
            assert isinstance(assigned, bool)
    else:
        assert job is None
        assert assign_process_to_job(None, 1234) is False


def test_secret_redaction_and_bounded_buffer():
    raw_output = (
        "Starting auth: --token=secret_token_12345 --password my_secret_pass "
        "Authorization: Bearer my_super_secret_jwt_token sk-1234567890abcdef1234567890\n"
    )
    redacted = _redact_secrets(raw_output)
    assert "secret_token_12345" not in redacted
    assert "my_secret_pass" not in redacted
    assert "my_super_secret_jwt_token" not in redacted
    assert "sk-1234567890abcdef1234567890" not in redacted
    assert "***" in redacted

    buf = _BoundedStreamBuffer(max_chars=2048, redact=True)
    buf.append("Key: sk-ant-api03-abcdefghijklmnop1234567890\n")
    val = buf.getvalue()
    assert "sk-ant-api03" not in val
    assert "***" in val


def test_swarm_pubsub_lifecycle_and_ttl():
    pubsub = SwarmPubSub(max_age_seconds=1.0)
    topic = "agent_events_test"

    sub_id, q = pubsub.subscribe(topic, maxsize=10)
    assert sub_id.startswith("sub_")

    pub_res = pubsub.publish(topic, {"task": "solve_gap"}, sender="planner")
    assert pub_res["success"] is True

    # Check subscriber received event
    msg = q.get_nowait()
    assert msg["sender"] == "planner"
    assert msg["payload"]["task"] == "solve_gap"

    # Test polling
    poll_res = pubsub.poll(topic, since_timestamp=0.0)
    assert poll_res["success"] is True
    assert poll_res["count"] >= 1

    # Unsubscribe
    assert pubsub.unsubscribe(topic, sub_id) is True
    assert pubsub.unsubscribe(topic, "nonexistent") is False


def test_command_broker_flaky_detect(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path)}, "commands": {"enabled": True}}
    broker = CommandBroker(cfg)

    res = broker.test_flaky_detect(str(tmp_path), "python -c \"import sys; sys.exit(0)\"", runs=3, timeout_per_run=10)
    assert res["success"] is True
    assert res["passed"] == 3
    assert res["flaky"] is False
    assert res["status"] == "stable_pass"


def test_command_broker_diff_hunk_stage(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path)}, "commands": {"enabled": True}}
    broker = CommandBroker(cfg)

    res = broker.diff_hunk_stage(str(tmp_path), "")
    assert res["success"] is False
    assert "empty" in res["error"]


def test_command_broker_webhook_replay(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path)}, "commands": {"enabled": True}}
    broker = CommandBroker(cfg)

    res = broker.webhook_replay(
        "http://127.0.0.1:59999/webhook",
        {"event": "ping"},
        secret="test_secret_key",
        timeout=0.2,
    )
    assert res["success"] is False
    assert "error" in res


def test_command_broker_webhook_replay_bounds_response_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class Response:
        status = 200
        headers: dict[str, str] = {}

        def read(self, size: int = -1) -> bytes:
            assert size == 65_536
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}, "commands": {"enabled": True}})

    result = broker.webhook_replay("http://127.0.0.1/webhook", {"event": "ping"})

    assert result["success"] is True
    assert result["body_preview"] == "ok"


def test_command_broker_webhook_replay_bounds_error_response_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class ErrorBody(io.BytesIO):
        read_size: int | None = None

        def read(self, size: int = -1) -> bytes:
            self.read_size = size
            return super().read(size)

    body = ErrorBody(b"error")
    error = HTTPError("http://127.0.0.1/webhook", 413, "payload too large", {}, body)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    broker = CommandBroker({"server": {"state_dir": str(tmp_path)}, "commands": {"enabled": True}})

    result = broker.webhook_replay("http://127.0.0.1/webhook", {"event": "ping"})

    assert body.read_size == 65_536
    assert result["status_code"] == 413
    assert result["body_preview"] == "error"


def test_deterministic_find_circular_dependencies(tmp_path: Path):
    pkg = tmp_path / "cycle_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod_a.py").write_text("from cycle_pkg import mod_b\ndef a(): pass\n", encoding="utf-8")
    (pkg / "mod_b.py").write_text("from cycle_pkg import mod_c\ndef b(): pass\n", encoding="utf-8")
    (pkg / "mod_c.py").write_text("from cycle_pkg import mod_a\ndef c(): pass\n", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.find_circular_dependencies(str(tmp_path))
    assert res["success"] is True
    assert res["has_cycles"] is True
    assert res["cycles_found"] >= 1
    cycle_chain = res["cycles"][0]["chain"]
    assert "cycle_pkg.mod_a" in cycle_chain
    assert "cycle_pkg.mod_b" in cycle_chain


def test_deterministic_generate_types(tmp_path: Path):
    sample_file = tmp_path / "calculator.py"
    sample_file.write_text(
        "def add(x: int, y: int) -> int:\n    '''Add two integers.'''\n    return x + y\n\n"
        "class Calculator:\n    def multiply(self, a: float, b: float) -> float:\n        return a * b\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.generate_types(str(tmp_path), "calculator.py", write_stub=True)
    assert res["success"] is True
    assert "def add(x: int, y: int) -> int: ..." in res["stub_content"]
    assert "class Calculator:" in res["stub_content"]
    assert "def multiply(self, a: float, b: float) -> float: ..." in res["stub_content"]
    assert (tmp_path / "calculator.pyi").is_file()


def test_deterministic_code_complexity(tmp_path: Path):
    nested_file = tmp_path / "complex_code.py"
    nested_file.write_text(
        "def simple():\n    return 42\n\n"
        "def complex_logic(items):\n"
        "    for x in items:\n"
        "        if x > 0:\n"
        "            if x % 2 == 0:\n"
        "                while x > 10:\n"
        "                    x -= 1\n"
        "    return items\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.code_complexity(str(tmp_path), "complex_code.py")
    assert res["success"] is True
    assert res["total_functions"] == 2
    top = res["functions"][0]
    assert top["name"] == "complex_logic"
    assert top["cyclomatic_complexity"] >= 4
    assert top["cognitive_complexity"] >= 6


def test_code_complexity_excludes_test_tree_by_default(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("def production():\n    if True:\n        return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("def fixture():\n    if True:\n        return 1\n", encoding="utf-8")

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    production = engine.code_complexity(str(tmp_path))
    with_tests = engine.code_complexity(str(tmp_path), include_tests=True)

    assert production["include_tests"] is False
    assert all(not item["file"].startswith("tests\\") for item in production["functions"])
    assert with_tests["include_tests"] is True
    assert any(item["file"].startswith("tests\\") for item in with_tests["functions"])


def test_deterministic_extract_api_spec(tmp_path: Path):
    api_file = tmp_path / "routes.py"
    api_file.write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "@app.get('/items/{item_id}')\n"
        "def get_item(item_id: int):\n"
        "    '''Fetch item by ID.'''\n"
        "    return {'id': item_id}\n\n"
        "@app.post('/items')\n"
        "def create_item():\n"
        "    return {'status': 'created'}\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.extract_api_spec(str(tmp_path))
    assert res["success"] is True
    assert res["total_endpoints"] == 2
    assert "/items/{item_id}" in res["paths"]
    assert "get" in res["paths"]["/items/{item_id}"]
    assert "/items" in res["paths"]
    assert "post" in res["paths"]["/items"]


def test_deterministic_slice_dependency_graph(tmp_path: Path):
    code_file = tmp_path / "models_and_services.py"
    code_file.write_text(
        "def helper():\n    return 'clean'\n\n"
        "def main_process():\n    res = helper()\n    return res.upper()\n\n"
        "def unrelated():\n    return 12345\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.slice_dependency_graph(str(tmp_path), "main_process")
    assert res["success"] is True
    assert "helper" in res["dependencies_found"]
    assert "main_process" in res["sliced_code"]
    assert "helper" in res["sliced_code"]
    assert "unrelated" not in res["sliced_code"]


def test_deterministic_migration_drift(tmp_path: Path):
    db_file = tmp_path / "app.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    con.close()

    model_file = tmp_path / "models.py"
    model_file.write_text(
        "class User:\n"
        "    __tablename__ = 'users'\n"
        "    id: int\n"
        "    email: str\n"
        "    username: str\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.migration_drift(str(tmp_path), str(db_file))
    assert res["success"] is True
    assert res["drift_detected"] is True
    assert len(res["column_drifts"]) == 1
    drift = res["column_drifts"][0]
    assert drift["table"] == "users"
    assert "username" in drift["missing_in_db"]


def test_deterministic_package_audit(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "requests==2.25.1\n"
        "urllib3==1.26.5\n"
        "safe-pkg==1.0.0\n",
        encoding="utf-8",
    )

    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.package_audit(str(tmp_path))
    assert res["success"] is True
    assert res["packages_scanned"] == 3
    assert res["vulnerabilities_found"] >= 2
    vuln_names = [v["package"] for v in res["vulnerabilities"]]
    assert "requests" in vuln_names
    assert "urllib3" in vuln_names


def test_eval_drift(tmp_path: Path):
    from local_ai_hub.services import LocalAIServices
    from unittest.mock import MagicMock

    mock_self = MagicMock()
    mock_self.state_dir = tmp_path

    payload1 = {
        "suite_name": "test_suite",
        "current": {
            "summary": {"pass_rate": 0.8, "total": 10, "passed": 8, "failed": 2},
            "cases": [],
        },
    }
    r1 = LocalAIServices.eval_drift(mock_self, payload1)
    assert r1["success"] is True
    assert r1["status"] == "baseline"
    assert r1["current_pass_rate"] == 0.8

    payload2 = {
        "suite_name": "test_suite",
        "current": {
            "summary": {"pass_rate": 0.6, "total": 10, "passed": 6, "failed": 4},
            "cases": [],
        },
    }
    r2 = LocalAIServices.eval_drift(mock_self, payload2)
    assert r2["success"] is True
    assert r2["status"] == "regressed"
    assert r2["drift_delta"] == -0.2

    payload3 = {
        "suite_name": "test_suite",
        "current": {
            "summary": {"pass_rate": 0.9, "total": 10, "passed": 9, "failed": 1},
            "cases": [],
        },
    }
    r3 = LocalAIServices.eval_drift(mock_self, payload3)
    assert r3["success"] is True
    assert r3["status"] == "improved"
    assert r3["drift_delta"] == 0.3
