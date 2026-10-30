from pathlib import Path
import shutil
import subprocess
import sys

FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-095'


def run_oracle(root):
    return subprocess.run([sys.executable, 'oracle_095.py'], cwd=root, capture_output=True, text=True, timeout=15)


def test_seed_exposes_data_loss(tmp_path):
    target = tmp_path / 'case'
    shutil.copytree(FIXTURE, target)
    result = run_oracle(target)
    assert result.returncode != 0
    assert 'FAILED' in result.stderr and 'Ran 2 tests' in result.stderr


def test_oracle_accepts_atomic_reference(tmp_path):
    target = tmp_path / 'case'
    shutil.copytree(FIXTURE, target)
    (target / 'writer.py').write_text('''import os\nimport tempfile\nfrom pathlib import Path\n\ndef replace_bytes(path, data, before_replace=lambda: None):\n    path = Path(path)\n    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".case095-")\n    try:\n        with os.fdopen(fd, "wb") as stream:\n            stream.write(data)\n        before_replace()\n        os.replace(name, path)\n    finally:\n        if os.path.exists(name):\n            os.unlink(name)\n''', encoding='utf-8')
    result = run_oracle(target)
    assert result.returncode == 0, result.stderr
