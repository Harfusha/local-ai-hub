from pathlib import Path
import subprocess
import sys

BUILDER = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-100' / 'prepare.py'


def test_builder_rejects_parent_inside_bare_git_repository(tmp_path):
    bare = tmp_path / 'bare.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True, timeout=10)
    root = bare / 'nested'
    prepared = subprocess.run([sys.executable, str(BUILDER), str(root)], capture_output=True, text=True, timeout=15)
    assert prepared.returncode != 0
    assert not root.exists()


def test_lifecycle_seed_has_two_failures_and_foreign_diff(tmp_path):
    root = tmp_path / 'case'
    prepare = subprocess.run([sys.executable, str(BUILDER), str(root)], capture_output=True, text=True, timeout=30)
    assert prepare.returncode == 0, prepare.stderr
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True, timeout=5, check=True)
    assert ' M FOREIGN.md' in status.stdout
    oracle = subprocess.run([sys.executable, 'oracle_100.py'], cwd=root, capture_output=True, text=True, timeout=10)
    assert oracle.returncode != 0 and 'Ran 2 tests' in oracle.stderr
    assert 'FAILED (failures=2, errors=1)' in oracle.stderr
    assert (root / 'FOREIGN.md').read_text(encoding='utf-8').endswith('Unrelated change to preserve.\n')
    (root / 'exporter.py').write_text('''import csv\nimport os\nimport tempfile\nfrom pathlib import Path\n\nclass ExportCancelled(Exception):\n    pass\n\ndef export(path, rows, cancelled=lambda: False):\n    path = Path(path)\n    if cancelled():\n        raise ExportCancelled()\n    fd, name = tempfile.mkstemp(dir=path.parent)\n    try:\n        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:\n            writer = csv.writer(stream, lineterminator="\\n")\n            writer.writerow(["id", "name"])\n            for row in rows:\n                if cancelled():\n                    raise ExportCancelled()\n                writer.writerow([row["id"], row["name"]])\n        os.replace(name, path)\n    finally:\n        if os.path.exists(name):\n            os.unlink(name)\n''', encoding='utf-8')
    repaired = subprocess.run([sys.executable, 'oracle_100.py'], cwd=root, capture_output=True, text=True, timeout=10)
    assert repaired.returncode == 0, repaired.stderr


def test_builder_rejects_nested_git_repository(tmp_path):
    subprocess.run(['git', 'init'], cwd=tmp_path, check=True, capture_output=True, timeout=10)
    root = tmp_path / 'nested'
    prepared = subprocess.run([sys.executable, str(BUILDER), str(root)], capture_output=True, text=True, timeout=10)
    assert prepared.returncode != 0
    assert not root.exists()
