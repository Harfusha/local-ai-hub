from __future__ import annotations

import io
import json
import os
import sys
import runpy
from unittest.mock import Mock
from pathlib import Path

import pytest

from local_ai_hub.token_economy import (
    count_tokens,
    filter_and_print_trimmed,
    generate_repo_map,
    strip_ansi,
    tokcount_main,
    trim_run_main,
    repo_map_main,
)
from local_ai_hub.generator import (
    generate_token_economy_policy,
    TOKEN_ECONOMIZER_SKILL_MD,
)
from tools.clean import clean


def test_importing_cli_does_not_fetch_tokenizer(monkeypatch):
    tokenizer = Mock()
    monkeypatch.setitem(sys.modules, 'tiktoken', tokenizer)
    runpy.run_path(str(Path(__file__).parents[1] / 'src' / 'local_ai_hub' / 'token_economy.py'))
    tokenizer.get_encoding.assert_not_called()


def test_strip_ansi():
    ansi_str = "\x1b[31;1mERROR:\x1b[0m \x1b[32mFile saved\x1b[0m"
    assert strip_ansi(ansi_str) == "ERROR: File saved"
    assert strip_ansi("clean text") == "clean text"


def test_count_tokens():
    text = "def calculate_sum(a: int, b: int) -> int:\n    return a + b\n"
    lines, words, chars, o200k, cl100k = count_tokens(text)
    assert lines >= 2
    assert words >= 6
    assert chars == len(text)
    assert o200k > 0
    assert cl100k > 0

    assert count_tokens("") == (0, 0, 0, 0, 0)


def test_tokcount_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    f = tmp_path / "sample.py"
    f.write_text("print('hello world')\n", encoding="utf-8")

    ret = tokcount_main([str(f), "--json"])
    assert ret == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["total_files"] == 1
    assert data["tokens_o200k"] > 0

    # Quiet mode
    ret_q = tokcount_main([str(f), "-q"])
    assert ret_q == 0
    out_q = capsys.readouterr().out.strip()
    assert out_q.isdigit()


def test_trim_run_filter_and_print(capsys: pytest.CaptureFixture):
    lines = [f"line {i}\n" for i in range(100)]
    filter_and_print_trimmed(lines, max_lines=10)
    out = capsys.readouterr().out
    assert "line 0" in out
    assert "line 4" in out
    assert "truncated by trim-run" in out
    assert "line 99" in out


def test_generate_repo_map(tmp_path: Path):
    mod = tmp_path / "module.py"
    mod.write_text(
        "class OrderManager:\n"
        "    def __init__(self):\n"
        "        pass\n\n"
        "    def create_order(self, item_id: str) -> bool:\n"
        "        return True\n",
        encoding="utf-8",
    )
    lines, total = generate_repo_map(tmp_path, max_lines=50)
    assert total == 1
    joined = "\n".join(lines)
    assert "OrderManager" in joined
    assert "create_order" in joined


def test_token_economy_policy_generation():
    policy = generate_token_economy_policy()
    assert "<!-- BEGIN TOKEN ECONOMY POLICY -->" in policy
    assert "<!-- END TOKEN ECONOMY POLICY -->" in policy
    trigger = next(line for line in policy.splitlines() if line.startswith("- Before any repository task"))
    assert "repo-map" in policy
    assert "trim-run" in policy
    assert "tokcount" in policy
    assert "ast-grep" in policy
    install_prompt = (Path(__file__).resolve().parents[1] / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update_prompt = (Path(__file__).resolve().parents[1] / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    agents_file = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    assert all(trigger in instructions for instructions in (install_prompt, update_prompt, agents_file))


def test_token_economizer_skill_md():
    assert "name: token-economizer" in TOKEN_ECONOMIZER_SKILL_MD
    assert "Use when starting any coding or repository task" in TOKEN_ECONOMIZER_SKILL_MD
    assert "Load and follow this skill before any coding or repository task" in TOKEN_ECONOMIZER_SKILL_MD
    assert (Path(__file__).resolve().parents[1] / "skills" / "token-economizer" / "SKILL.md").read_text(encoding="utf-8").strip() == TOKEN_ECONOMIZER_SKILL_MD.strip()
    assert "Zero Full-File Dumping" in TOKEN_ECONOMIZER_SKILL_MD
    assert "trim-run" in TOKEN_ECONOMIZER_SKILL_MD
    assert "tokcount" in TOKEN_ECONOMIZER_SKILL_MD


def test_clean_tool(tmp_path: Path):
    # Setup dummy directory with cache and valid files
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir(parents=True)
    pyc_file = pycache / "main.cpython-313.pyc"
    pyc_file.write_bytes(b"dummy bytecode")

    valid_file = tmp_path / "src" / "main.py"
    valid_file.write_text("print('hello')", encoding="utf-8")

    cov_file = tmp_path / ".coverage"
    cov_file.write_bytes(b"cov data")

    dirs_removed, files_removed = clean(tmp_path, all_clean=True)
    assert dirs_removed >= 1
    assert files_removed >= 1
    assert not pycache.exists()
    assert not cov_file.exists()
    assert valid_file.exists()
