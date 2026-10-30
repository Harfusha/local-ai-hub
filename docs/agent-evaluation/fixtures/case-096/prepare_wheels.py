"""Build two committed revisions offline in a new disposable directory."""
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile


def command(args, **kwargs):
    return subprocess.run(args, check=True, timeout=120, **kwargs)


def prepare(repository, before, after, target):
    if not Path(repository).is_absolute() or not Path(target).is_absolute():
        raise ValueError('repository and target must be absolute paths')
    repository = Path(repository).resolve(strict=True)
    target = Path(target).resolve()
    if not target.parent.is_dir():
        raise ValueError('target parent must already exist')
    git_env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    git_env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C'})
    if any((ancestor / '.git').exists() for ancestor in (target.parent, *target.parent.parents)):
        raise ValueError('target must not be inside a Git repository')
    probe = subprocess.run(['git', '-C', str(target.parent), 'rev-parse', '--git-dir'], env=git_env, capture_output=True, text=True, encoding='utf-8', timeout=10)
    if probe.returncode == 0:
        raise ValueError('target must not be inside a Git repository')
    if probe.returncode != 128 or 'not a git repository' not in probe.stderr.lower():
        raise RuntimeError('could not establish whether the target parent belongs to a Git repository')
    resolved_root = command(['git', '-C', str(repository), 'rev-parse', '--show-toplevel'], env=git_env, capture_output=True, text=True, encoding='utf-8')
    if Path(resolved_root.stdout.rstrip('\r\n')).resolve(strict=True) != repository:
        raise ValueError('repository must be the exact Git worktree root')
    commits = []
    for ref in (before, after):
        if not ref or ref.startswith('-') or len(ref) > 512:
            raise ValueError('invalid revision')
        result = command(['git', '-C', str(repository), 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}'], env=git_env, capture_output=True, text=True, encoding='utf-8')
        commit = result.stdout.strip()
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
            raise ValueError('revision did not resolve to a commit')
        commits.append(commit)
    if commits[0] == commits[1]:
        raise ValueError('revisions must identify different commits')
    target.mkdir(parents=False, exist_ok=False)
    releases = []
    for label, commit in zip(('before', 'after'), commits):
        folder = target / label
        source = folder / 'source'
        output = folder / 'wheels'
        source.mkdir(parents=True)
        output.mkdir()
        archive = folder / 'source.tar'
        with archive.open('wb') as stream:
            command(['git', '-C', str(repository), 'archive', '--format=tar', commit], env=git_env, stdout=stream, stderr=subprocess.PIPE)
        with tarfile.open(archive) as tar:
            for item in tar:
                destination = (source / item.name).resolve()
                if not destination.is_relative_to(source) or not (item.isfile() or item.isdir()):
                    raise ValueError('unsafe archive member')
                if item.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(item) as input_stream, destination.open('wb') as output_stream:
                        shutil.copyfileobj(input_stream, output_stream)
        environment = dict(os.environ, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
        command([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-deps', '--no-build-isolation', '--wheel-dir', str(output), '.'], cwd=source, env=environment, capture_output=True)
        wheels = list(output.glob('*.whl'))
        if len(wheels) != 1:
            raise RuntimeError('expected exactly one wheel per revision')
        wheel = wheels[0]
        releases.append({'commit':commit, 'wheel':str(wheel.relative_to(target)), 'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()})
    environment = {
        'python_executable': str(Path(sys.executable).resolve()),
        'python_version': platform.python_version(),
        'platform': platform.platform(),
        'setuptools_version': importlib.metadata.version('setuptools'),
        'wheel_version': importlib.metadata.version('wheel'),
    }
    (target / 'wheel_manifest.json').write_text(json.dumps({'schema_version':1, 'releases':releases, 'build_environment':environment, 'runtime_acceptance':False}, indent=2)+'\n', encoding='utf-8')
    print(target)

if __name__ == '__main__':
    if len(sys.argv) != 5:
        raise SystemExit('Usage: prepare_wheels.py REPOSITORY BEFORE_REF AFTER_REF NEW_DISPOSABLE_ROOT')
    prepare(*sys.argv[1:])
