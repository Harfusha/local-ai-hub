import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from local_ai_hub.treesitter_parser import parse_treesitter, is_treesitter_available
from local_ai_hub.commands import CommandBroker
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.services import LocalAIServices


def make_services(cfg, repo_tools=None, code_idx=None):
    if "models" not in cfg:
        cfg["models"] = {"fast_code": "qwen2.5-coder:7b", "heavy_code": "qwen2.5-coder:7b"}
    if repo_tools is None:
        repo_tools = RepositoryTools(cfg)
    return LocalAIServices(
        config=cfg,
        runtime=MagicMock(),
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=repo_tools,
        code_index=code_idx,
    )



def test_treesitter_csharp_and_typescript_ast():
    if not is_treesitter_available("csharp") or not is_treesitter_available("typescript"):
        pytest.skip("tree-sitter csharp or typescript grammar not installed")

    # C# test
    cs_src = """
using System;
namespace Game.Core {
    public class Player : Entity {
        public int Health { get; set; }
        public void Attack(Entity target) {
            target.TakeDamage(10);
        }
    }
}
"""
    syms, refs, edges = parse_treesitter(cs_src, "csharp")
    sym_map = {s["name"]: s for s in syms}
    assert "Player" in sym_map
    assert sym_map["Player"]["kind"] == "class"
    assert sym_map["Player"]["line"] == 4
    assert sym_map["Player"]["end_line"] == 9

    assert "Attack" in sym_map
    assert sym_map["Attack"]["kind"] == "method"
    assert sym_map["Attack"]["line"] == 6
    assert sym_map["Attack"]["end_line"] == 8

    # Check edges & refs
    assert any(e["dst"] == "Entity" and e["kind"] == "inherits" for e in edges)
    assert any(r["name"] == "TakeDamage" for r in refs)

    # TypeScript test
    ts_src = """
import { Config } from "./config";
export class AuthService {
    verifyToken(token: string): boolean {
        return Config.check(token);
    }
}
"""
    syms_ts, refs_ts, edges_ts = parse_treesitter(ts_src, "typescript")
    sym_map_ts = {s["name"]: s for s in syms_ts}
    assert "AuthService" in sym_map_ts
    assert sym_map_ts["AuthService"]["kind"] == "class"
    assert "verifyToken" in sym_map_ts
    assert any(e["dst"] == "./config" and e["kind"] == "imports" for e in edges_ts)
    assert any(r["name"] == "check" for r in refs_ts)


def test_treesitter_shared_parser_is_safe_for_parallel_calls():
    if not is_treesitter_available("csharp"):
        pytest.skip("tree-sitter csharp grammar not installed")

    source = "namespace Demo { public class Worker { public void Run() {} } }\n"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: parse_treesitter(source, "csharp"), range(16)))

    assert all(result is not None and any(item["name"] == "Worker" for item in result[0]) for result in results)


def test_include_code_in_code_query(tmp_path: Path):
    py_file = tmp_path / "calculator.py"
    py_file.write_text(
        "class Calculator:\n    def add(self, a, b):\n        return a + b\n",
        encoding="utf-8"
    )

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(cfg)
    code_idx = CodeIndex(cfg, repo_tools)
    code_idx.update_file(str(tmp_path), "calculator.py")

    services = make_services(cfg, repo_tools=repo_tools, code_idx=code_idx)

    res = services.code_query(str(tmp_path), "Calculator", limit=5, include_code=True)
    assert res.get("success") is True
    symbols = res.get("symbols", [])
    assert len(symbols) > 0
    calc_sym = [s for s in symbols if s["name"] == "Calculator"][0]
    assert "code" in calc_sym
    assert "class Calculator" in calc_sym["code"]
    assert "def add" in calc_sym["code"]


def test_repo_investigate_cascade(tmp_path: Path):
    src_file = tmp_path / "service.py"
    src_file.write_text(
        "class OrderService:\n    def process_order(self, order_id):\n        return True\n",
        encoding="utf-8"
    )
    test_file = tmp_path / "test_service.py"
    test_file.write_text(
        "from service import OrderService\ndef test_process():\n    assert OrderService().process_order(1)\n",
        encoding="utf-8"
    )

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(cfg)
    code_idx = CodeIndex(cfg, repo_tools)
    code_idx.update_file(str(tmp_path), "service.py")
    code_idx.update_file(str(tmp_path), "test_service.py")

    services = make_services(cfg, repo_tools=repo_tools, code_idx=code_idx)

    inv = services.repo_investigate(str(tmp_path), "OrderService", include_code=True)
    assert inv.get("success") is True
    assert inv.get("primary_symbol") == "OrderService"
    assert len(inv.get("symbols", [])) > 0
    assert "code" in inv["symbols"][0]
    assert "class OrderService" in inv["symbols"][0]["code"]


def test_patch_and_verify_clean_success(tmp_path: Path):
    # Setup git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)

    target_file = tmp_path / "app.py"
    target_file.write_text("def hello():\n    return 'old'\n", encoding="utf-8")
    test_file = tmp_path / "test_app.py"
    test_file.write_text("from app import hello\ndef test_hello():\n    assert hello() == 'new'\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    diff = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'old'
+    return 'new'
"""

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)

    res = broker.patch_and_verify(
        patch=diff,
        cwd=str(tmp_path),
        tenant="test-agent",
        command=f"python -m pytest test_app.py -q",
        task_id="task-123",
        criterion="test_hello passes",
    )

    assert res["success"] is True
    assert res["applied"] is True
    assert res["tests_passed"] is True
    assert target_file.read_text(encoding="utf-8") == "def hello():\n    return 'new'\n"


def test_patch_and_verify_syntax_error_rollback(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)

    target_file = tmp_path / "main.py"
    initial_content = "def valid():\n    return 42\n"
    target_file.write_text(initial_content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    bad_syntax_diff = """--- a/main.py
+++ b/main.py
@@ -1,2 +1,2 @@
 def valid():
-    return 42
+    return def broken syntax!!!
"""

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)

    res = broker.patch_and_verify(
        patch=bad_syntax_diff,
        cwd=str(tmp_path),
        tenant="test-agent",
        auto_rollback=True,
    )

    assert res["success"] is False
    assert res["applied"] is False
    assert res["rolled_back"] is True
    assert "Syntax error" in res["error"]
    # Verify file was rolled back
    assert target_file.read_text(encoding="utf-8") == initial_content


def test_patch_and_verify_test_failure_rollback(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)

    app_file = tmp_path / "calc.py"
    initial_code = "def subtract(a, b):\n    return a - b\n"
    app_file.write_text(initial_code, encoding="utf-8")
    test_file = tmp_path / "test_calc.py"
    test_file.write_text("from calc import subtract\ndef test_sub():\n    assert subtract(5, 2) == 3\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # Patch breaks the logic
    bad_logic_diff = """--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def subtract(a, b):
-    return a - b
+    return a + b
"""

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)

    res = broker.patch_and_verify(
        patch=bad_logic_diff,
        cwd=str(tmp_path),
        tenant="test-agent",
        command="python -m pytest test_calc.py -q",
        auto_rollback=True,
    )

    assert res["success"] is False
    assert res["applied"] is False
    assert res["rolled_back"] is True
    assert "Validation command failed" in res["error"]
    # Verify clean rollback
    assert app_file.read_text(encoding="utf-8") == initial_code


def test_task_scaffold(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = make_services(cfg)
    services._generate = MagicMock(return_value={
        "success": True,
        "text": "```python\nclass UserDTO:\n    def __init__(self, username: str):\n        self.username = username\n```",
        "model": "qwen2.5-coder:7b",
        "tokens": 42,
    })
    res = services.task_scaffold(
        {"spec": "Create a UserDTO with username", "language": "python"},
        tenant="test-agent"
    )

    assert res["success"] is True
    assert "class UserDTO:" in res["code"]
    assert "```" not in res["code"]
    assert res["language"] == "python"


def test_treesitter_go_and_rust():
    if not is_treesitter_available("go") or not is_treesitter_available("rust"):
        pytest.skip("tree-sitter go or rust grammar not installed")

    # Go AST test
    go_src = """
package main

import "fmt"

type Service struct {
    Port int
}

func (s *Service) Start() {
    fmt.Println("Starting...")
}

func Helper() {
    println("help")
}
"""
    syms_go, refs_go, edges_go = parse_treesitter(go_src, "go")
    go_names = {s["name"]: s for s in syms_go}
    assert "Service" in go_names
    assert go_names["Service"]["kind"] == "struct"
    assert "Start" in go_names
    assert go_names["Start"]["kind"] == "method"
    assert "Helper" in go_names
    assert go_names["Helper"]["kind"] == "function"
    assert any(e["dst"] == "fmt" for e in edges_go)

    # Rust AST test
    rs_src = """
struct Engine {
    power: u32,
}

trait Driver {
    fn drive(&self);
}

impl Driver for Engine {
    fn drive(&self) {
        println!("driving");
    }
}
"""
    syms_rs, refs_rs, edges_rs = parse_treesitter(rs_src, "rust")
    rs_names = {s["name"]: s for s in syms_rs}
    assert "Engine" in rs_names
    assert rs_names["Engine"]["kind"] == "struct"
    assert "Driver" in rs_names
    assert rs_names["Driver"]["kind"] == "trait"
    assert "drive" in rs_names
    assert rs_names["drive"]["kind"] == "method"
    assert any(e["src"] == "Engine" and e["dst"] == "Driver" and e["kind"] == "implements" for e in edges_rs)


def test_repo_diagnose_python_traceback(tmp_path: Path):
    app_file = tmp_path / "calc.py"
    app_file.write_text(
        "def divide(a, b):\n    return a / b\n\ndef run():\n    return divide(10, 0)\n",
        encoding="utf-8"
    )

    tb = f"""
Traceback (most recent call last):
  File "{app_file.as_posix()}", line 5, in run
    return divide(10, 0)
  File "{app_file.as_posix()}", line 2, in divide
    return a / b
ZeroDivisionError: division by zero
"""

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = make_services(cfg)
    diag = services.repo_diagnose(str(tmp_path), tb)

    assert diag["success"] is True
    assert diag["error_type"] == "ZeroDivisionError"
    assert "division by zero" in diag["error_message"]
    assert diag["frames_count"] == 2
    assert diag["project_frames_count"] == 2
    root_cause = diag["root_cause"]
    assert root_cause is not None
    assert root_cause["line"] == 2
    assert "a / b" in root_cause["snippet"]


def test_repo_diagnose_javascript_stacktrace(tmp_path: Path):
    js_file = tmp_path / "index.js"
    js_file.write_text(
        "function boom() {\n    throw new TypeError('bad value');\n}\nboom();\n",
        encoding="utf-8"
    )

    stack = f"""
TypeError: bad value
    at boom ({js_file.as_posix()}:2:11)
    at Object.<anonymous> ({js_file.as_posix()}:4:1)
"""

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = make_services(cfg)
    diag = services.repo_diagnose(str(tmp_path), stack)

    assert diag["success"] is True
    assert diag["error_type"] == "TypeError"
    assert "bad value" in diag["error_message"]
    assert diag["frames_count"] == 2
    assert diag["root_cause"]["line"] == 4 or diag["root_cause"]["line"] == 2


def test_repo_briefing(tmp_path: Path):
    # Setup git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True, check=True)

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(tmp_path), capture_output=True, check=True)

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = make_services(cfg)
    brief = services.repo_briefing(str(tmp_path))

    assert brief["success"] is True
    assert "Python" in brief["stack"]
    assert "pyproject.toml" in brief["manifests"]
    assert "main.py" in brief["entry_points"]
    assert "pytest" in brief["test_commands"]
    assert "initial commit" in brief["git"]["recent_commits"][0]
    assert "**Stack**: Python" in brief["markdown_card"]


def test_patch_and_verify_auto_affected_tests(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)

    calc_file = tmp_path / "math_lib.py"
    calc_file.write_text("def multiply(a, b):\n    return a * b\n", encoding="utf-8")

    test_file = tmp_path / "test_math_lib.py"
    test_file.write_text("from math_lib import multiply\ndef test_mult():\n    assert multiply(3, 4) == 12\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init math"], cwd=str(tmp_path), capture_output=True, check=True)

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)

    # Patch modifying math_lib
    patch = """diff --git a/math_lib.py b/math_lib.py
--- a/math_lib.py
+++ b/math_lib.py
@@ -1,2 +1,2 @@
 def multiply(a, b):
-    return a * b
+    return (a * b)
"""

    res = broker.patch_and_verify(
        patch=patch,
        cwd=str(tmp_path),
        tenant="test-agent",
        command="auto",
    )

    assert res["success"] is True
    assert res["applied"] is True
    assert res["tests_passed"] is True
    assert "test_math_lib.py" in res.get("affected_tests_run", [])[0]


def test_repo_wide_ast_rename_clean_and_rollback(tmp_path: Path):
    file1 = tmp_path / "core.py"
    file1.write_text("class OldEngine:\n    pass\n", encoding="utf-8")
    file2 = tmp_path / "consumer.py"
    file2.write_text("from core import OldEngine\ne = OldEngine()\n", encoding="utf-8")

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(cfg)
    det = DeterministicEngine(cfg, repo_tools)

    # Dry run repo-wide rename
    res = det.ast_rename(str(tmp_path), "", "OldEngine", "NewEngine", apply_changes=False)
    assert res["success"] is True
    assert "core.py" in res["affected_files"]
    assert "consumer.py" in res["affected_files"]
    assert res["applied"] is False

    # Apply changes
    res_apply = det.ast_rename(str(tmp_path), "", "OldEngine", "NewEngine", apply_changes=True)
    assert res_apply["success"] is True
    assert res_apply["applied"] is True
    assert "class NewEngine:" in file1.read_text(encoding="utf-8")
    assert "NewEngine()" in file2.read_text(encoding="utf-8")


def test_preflight_linter(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    broker = CommandBroker(cfg)

    good_file = tmp_path / "valid.py"
    good_file.write_text("x = 1 + 2\n", encoding="utf-8")

    res_good = broker.preflight(cwd=str(tmp_path), paths=["valid.py"])
    assert res_good["success"] is True
    assert res_good["clean"] is True
    assert res_good["errors_count"] == 0

    bad_file = tmp_path / "syntax_err.py"
    bad_file.write_text("def foo(:\n    pass\n", encoding="utf-8")

    res_bad = broker.preflight(cwd=str(tmp_path), paths=["syntax_err.py"])
    assert res_bad["success"] is True
    assert res_bad["clean"] is False
    assert res_bad["errors_count"] > 0
    assert "syntax_error" in res_bad["errors"][0]["level"]


def test_review_diff_ast_mode(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=str(tmp_path), capture_output=True, check=True)

    f = tmp_path / "module.py"
    f.write_text("def original():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

    # Modify file
    f.write_text("def original(param):\n    pass\n\ndef added():\n    return 42\n", encoding="utf-8")

    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = make_services(cfg)

    res = services.review_diff({"root": str(tmp_path), "mode": "ast"}, tenant="test")
    assert res["success"] is True
    assert res["mode"] == "ast"
    assert "module.py" in res["changed_files"]
    assert "AST Diff Summary" in res["summary"]

