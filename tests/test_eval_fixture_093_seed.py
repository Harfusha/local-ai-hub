from pathlib import Path
import subprocess
import sys

BUILDER = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-093' / 'prepare.py'


def test_preparation_creates_real_conflict_in_disposable_root(tmp_path):
    root = tmp_path / 'sandbox'
    prepared = subprocess.run([sys.executable, str(BUILDER), str(root)], capture_output=True, text=True, timeout=30)
    assert prepared.returncode == 0, prepared.stderr
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True, check=True, timeout=5)
    assert 'UU pricing.py' in status.stdout
    source = (root / 'pricing.py').read_text(encoding='utf-8')
    assert '<<<<<<<' in source and '>>>>>>>' in source
    assert 'discount' in source and 'fee' in source
    check = subprocess.run([sys.executable, '-m', 'unittest', '-q'], cwd=root, capture_output=True, text=True, timeout=10)
    assert check.returncode != 0
    (root / 'pricing.py').write_text('def total(price, fee, discount):\n    return price + fee - discount\n', encoding='utf-8')
    check = subprocess.run([sys.executable, '-m', 'unittest', '-q'], cwd=root, capture_output=True, text=True, timeout=10)
    assert check.returncode == 0, check.stderr


def test_builder_rejects_nested_git_repository(tmp_path):
    subprocess.run(['git', 'init'], cwd=tmp_path, check=True, capture_output=True, timeout=10)
    root = tmp_path / 'nested'
    prepared = subprocess.run([sys.executable, str(BUILDER), str(root)], capture_output=True, text=True, timeout=10)
    assert prepared.returncode != 0
    assert not root.exists()


def test_builder_rejects_parent_inside_bare_git_repository(tmp_path):
    bare = tmp_path / 'bare.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True, timeout=10)
    root = bare / 'nested'
    prepared = subprocess.run([sys.executable, str(BUILDER), str(root)], capture_output=True, text=True, timeout=15)
    assert prepared.returncode != 0
    assert not root.exists()
