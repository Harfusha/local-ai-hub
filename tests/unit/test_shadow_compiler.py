import time
from pathlib import Path
import pytest

from local_ai_hub.shadow_compiler import ShadowCompiler


def test_shadow_compiler_valid_python():
    shm_name = f"test_shm_shadow_{int(time.time() * 1000)}"
    compiler = ShadowCompiler(shm_name=shm_name, size=64 * 1024)
    try:
        code = (
            "import os\n"
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        receipt = compiler.compile_source("calc.py", content=code)
        assert receipt["valid"] is True
        assert receipt["syntax_ok"] is True
        assert receipt["invariants_ok"] is True
        assert receipt["error"] is None
        assert receipt["duration_ms"] >= 0.0

        # Sub-millisecond SHM read
        cached = compiler.get_latest_receipt()
        assert cached is not None
        assert cached["file"] == "calc.py"
        assert cached["syntax_ok"] is True
        assert cached["valid"] is True
    finally:
        compiler.close()


def test_shadow_compiler_syntax_error():
    shm_name = f"test_shm_syn_{int(time.time() * 1000)}"
    compiler = ShadowCompiler(shm_name=shm_name, size=64 * 1024)
    try:
        bad_code = "def broken(:\n    pass\n"
        receipt = compiler.compile_source("bad.py", content=bad_code)
        assert receipt["valid"] is False
        assert receipt["syntax_ok"] is False
        assert "SyntaxError" in receipt["error"]
    finally:
        compiler.close()


def test_shadow_compiler_invariants():
    shm_name = f"test_shm_inv_{int(time.time() * 1000)}"
    compiler = ShadowCompiler(shm_name=shm_name, size=64 * 1024)
    try:
        code_with_violations = (
            "import requests\n"
            "def fetch():\n"
            "    f = open('data.txt')\n"
            "    r = requests.get('https://example.com')\n"
            "    try:\n"
            "        return r.text\n"
            "    except:\n"
            "        return None\n"
        )
        receipt = compiler.compile_source("fetcher.py", content=code_with_violations)
        assert receipt["syntax_ok"] is True
        assert receipt["invariants_ok"] is False
        rule_names = {v["rule"] for v in receipt["violations"]}
        assert "missing_with_open" in rule_names
        assert "missing_timeout" in rule_names
        assert "bare_except" in rule_names
    finally:
        compiler.close()


def test_shadow_compiler_json():
    shm_name = f"test_shm_json_{int(time.time() * 1000)}"
    compiler = ShadowCompiler(shm_name=shm_name, size=64 * 1024)
    try:
        good_json = '{"status": "ok", "count": 10}'
        r_good = compiler.compile_source("config.json", content=good_json)
        assert r_good["valid"] is True
        assert r_good["syntax_ok"] is True

        bad_json = '{"status": "incomplete", '
        r_bad = compiler.compile_source("broken.json", content=bad_json)
        assert r_bad["valid"] is False
        assert r_bad["syntax_ok"] is False
        assert "JSONDecodeError" in r_bad["error"]
    finally:
        compiler.close()


def test_shadow_compiler_selective_tests():
    shm_name = f"test_shm_sel_{int(time.time() * 1000)}"
    compiler = ShadowCompiler(shm_name=shm_name, size=64 * 1024)
    try:
        # Resolves tests for context_virtualizer
        targets = compiler.resolve_selective_tests("src/local_ai_hub/context_virtualizer.py")
        assert len(targets) > 0
        assert any("test_context_virtualizer" in t for t in targets)

        # Runs selective tests bounded
        exec_res = compiler.run_selective_tests("src/local_ai_hub/context_virtualizer.py", timeout=15.0)
        assert exec_res["ran"] is True
        assert exec_res["passed"] is True
        assert exec_res["exit_code"] == 0
    finally:
        compiler.close()
