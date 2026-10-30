from pathlib import Path
import shutil
import subprocess
import sys


def test_case_092_seed_is_disposable_and_lacks_output_option(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-092'
    fixture = tmp_path / 'case-092'
    shutil.copytree(source, fixture)
    target = fixture / 'output.json'
    result = subprocess.run(
        [sys.executable, str(fixture / 'report.py'), '--output', str(target)],
        cwd=fixture, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert 'unrecognized arguments' in result.stderr
    assert not target.exists()


def test_case_092_prepare_refuses_existing_root_before_git_mutation(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-092'
    target = tmp_path / 'existing'
    target.mkdir()
    marker = target / 'keep.txt'
    marker.write_text('keep', encoding='utf-8')
    result = subprocess.run([sys.executable, str(source / 'prepare.py'), str(target)], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert marker.read_text(encoding='utf-8') == 'keep'
    assert not (target / '.git').exists()


def test_case_092_prepare_refuses_parent_inside_bare_repository(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-092'
    bare = tmp_path / 'bare.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], capture_output=True, text=True, timeout=15, check=True)
    target = bare / 'fixture'
    result = subprocess.run([sys.executable, str(source / 'prepare.py'), str(target)], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert not target.exists()


def test_case_092_prepare_creates_committed_independent_repo(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-092'
    target = tmp_path / 'fixture'
    result = subprocess.run([sys.executable, str(source / 'prepare.py'), str(target)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert 'seed_commit=' in result.stdout
    assert (target / '.git').is_dir()
    tracked = subprocess.run(['git', 'status', '--porcelain'], cwd=target, capture_output=True, text=True, timeout=10, check=True)
    assert tracked.stdout == ''
