from pathlib import Path
import shutil
import subprocess
import sys
import pytest

FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-091'


def oracle(root):
    return subprocess.run([sys.executable, 'oracle_091.py'], cwd=root, text=True, capture_output=True, timeout=20)


def test_seed_and_reference(tmp_path):
    if not shutil.which('node'):
        pytest.skip('fixture 091 requires Node.js with TypeScript stripping')
    node = subprocess.run(['node', '--experimental-strip-types', '-e', ''], capture_output=True, timeout=10)
    if node.returncode:
        pytest.skip('installed Node.js does not support TypeScript stripping')
    target = tmp_path / 'case'
    shutil.copytree(FIXTURE, target)
    result = oracle(target)
    assert result.returncode != 0 and 'FAILED' in result.stderr and 'Ran 3 tests' in result.stderr
    (target / 'backend.py').write_text('def select_ready(rows):\n    return [{"id": r["id"], "name": r["name"]} for r in rows if r["status"] == "ready"]\n', encoding='utf-8')
    (target / 'frontend.ts').write_text('''import {readFileSync} from "node:fs";\ntype Row = {id: string; name: string};\nconst rows: Row[] = JSON.parse(readFileSync(0, "utf8"));\nconst escape = (s: string) => `"${s.replaceAll('"', '""')}"`;\nprocess.stdout.write("id,name\\n" + rows.map(r => `${escape(r.id)},${escape(r.name)}\\n`).join(""));\n''', encoding='utf-8')
    result = oracle(target)
    assert result.returncode == 0, result.stderr
