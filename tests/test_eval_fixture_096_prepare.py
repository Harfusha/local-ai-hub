from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import pytest

BUILDER = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-096' / 'prepare_wheels.py'


def test_build_two_offline_wheels_and_reject_existing_target(tmp_path):
    try:
        import setuptools  # noqa: F401
        import wheel  # noqa: F401
    except ImportError:
        pytest.skip('offline build requires preinstalled setuptools and wheel')
    repo = tmp_path / 'repo-Žofie'
    repo.mkdir()
    def git(*args):
        return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    git('init')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'commit.gpgsign', 'false')
    hooks = repo / '.git' / 'fixture-empty-hooks'
    hooks.mkdir()
    git('config', 'core.hooksPath', str(hooks))
    (repo / 'package').mkdir()
    (repo / 'package' / '__init__.py').write_text('', encoding='utf-8')
    (repo / 'pyproject.toml').write_text('[build-system]\nrequires=["setuptools", "wheel"]\nbuild-backend="setuptools.build_meta"\n[project]\nname="fixture-package"\nversion="1.0.0"\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-m', 'v1')
    first = git('rev-parse', 'HEAD')
    pyproject = repo / 'pyproject.toml'
    pyproject.write_text(pyproject.read_text(encoding='utf-8').replace('1.0.0', '2.0.0'), encoding='utf-8')
    git('commit', '-am', 'v2')
    second = git('rev-parse', 'HEAD')
    target = tmp_path / 'sandbox'
    hostile_env = dict(os.environ, GIT_DIR=str(tmp_path / 'foreign-git-dir'))
    result = subprocess.run([sys.executable, str(BUILDER), str(repo), first, second, str(target)], env=hostile_env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((target / 'wheel_manifest.json').read_text(encoding='utf-8'))
    assert [x['commit'] for x in manifest['releases']] == [first, second]
    assert manifest['build_environment']['python_executable']
    assert manifest['build_environment']['python_version']
    assert manifest['build_environment']['setuptools_version']
    assert manifest['build_environment']['wheel_version']
    assert all((target / x['wheel']).is_file() for x in manifest['releases'])
    assert all(hashlib.sha256((target / x['wheel']).read_bytes()).hexdigest() == x['sha256'] for x in manifest['releases'])
    assert manifest['runtime_acceptance'] is False
    again = subprocess.run([sys.executable, str(BUILDER), str(repo), first, second, str(target)], capture_output=True, text=True, timeout=10)
    assert again.returncode != 0
    nested = repo / 'nested-sandbox'
    refusal = subprocess.run([sys.executable, str(BUILDER), str(repo), first, second, str(nested)], capture_output=True, text=True, timeout=10)
    assert refusal.returncode != 0
    assert not nested.exists()
    bare = tmp_path / 'bare.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True, timeout=10)
    bare_target = bare / 'nested'
    refusal = subprocess.run([sys.executable, str(BUILDER), str(repo), first, second, str(bare_target)], capture_output=True, text=True, timeout=15)
    assert refusal.returncode != 0
    assert not bare_target.exists()
