"""Real large-source regression for native Point property reference crashes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from local_ai_hub.process_utils import hidden_run_kwargs


@pytest.mark.parametrize("grammar_provider", ["pack", "wheel"])
def test_native_worker_parses_large_current_sources_without_access_violation(grammar_provider):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_language_pack")
    if grammar_provider == "wheel":
        pytest.importorskip("tree_sitter_python")
    root = Path(__file__).resolve().parents[2]
    script = """
import faulthandler, json, sys
from pathlib import Path
from local_ai_hub import treesitter_parser as parser
parser._initialize_isolated_worker()
faulthandler.enable()
if sys.argv[1] == 'wheel':
    import tree_sitter_python
    from tree_sitter import Language, Parser
    parser._IN_WORKER = True
    parser._INIT_ATTEMPTED = True
    parser._PARSERS = {'python': Parser(Language(tree_sitter_python.language()))}
rows = []
expected = {
    'treesitter_parser.py': ('_extract_python', 'def _extract_python('),
    'code_index.py': ('CodeIndex', 'class CodeIndex'),
    'mcp_server.py': ('local_ai_repo', 'def local_ai_repo('),
}
for name in ('treesitter_parser.py', 'code_index.py', 'mcp_server.py'):
    source = Path(parser.__file__).with_name(name).read_text(encoding='utf-8')
    outcome = parser._worker_parse(source, 'python', source_key=name)
    assert outcome['status'] == 'ok', outcome
    symbol, marker = expected[name]
    expected_line = next(i for i, line in enumerate(source.splitlines(), 1) if line.startswith(marker))
    assert expected_line > 256
    match = next(row for row in outcome['result'][0] if row['name'] == symbol)
    assert match['line'] == expected_line, match
    reused = parser._worker_parse(source, 'python', source_key=name)
    assert reused['status'] == 'ok' and reused['incremental'] is True, reused
    edited = parser._worker_parse('# shifted source\\n' + source, 'python', source_key=name)
    assert edited['status'] == 'ok' and edited['incremental'] is True, edited
    match = next(row for row in edited['result'][0] if row['name'] == symbol)
    assert match['line'] == expected_line + 1, match
    rows.append(name)
print(json.dumps(rows))
"""
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    completed = subprocess.run(
        [sys.executable, "-c", script, grammar_provider], cwd=root, env=env,
        capture_output=True, timeout=35, **hidden_run_kwargs(text=True),
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    assert json.loads(completed.stdout) == [
        "treesitter_parser.py", "code_index.py", "mcp_server.py",
    ]
