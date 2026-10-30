"""Materialize a new disposable Git repository; never touch an existing target."""
from pathlib import Path
import os
import subprocess
import sys

def prepare(destination):
    candidate = Path(destination)
    if not candidate.is_absolute():
        raise ValueError('disposable root must be an absolute path')
    root = candidate.resolve()
    if not root.parent.is_dir():
        raise ValueError('disposable root parent must already exist')
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C'})
    if any((ancestor / '.git').exists() for ancestor in (root.parent, *root.parent.parents)):
        raise ValueError('disposable root must not be inside another Git repository')
    parent_probe = subprocess.run(['git', '-C', str(root.parent), 'rev-parse', '--git-dir'], env=env, capture_output=True, text=True, timeout=10)
    if parent_probe.returncode == 0:
        raise ValueError('disposable root must not be inside another Git repository')
    if parent_probe.returncode != 128 or 'not a git repository' not in parent_probe.stderr.lower():
        raise RuntimeError('could not establish whether the parent belongs to a Git repository')
    root.mkdir(parents=False, exist_ok=False)
    template = root / '.fixture-empty-template'
    template.mkdir()
    seed = Path(__file__).resolve().parent / 'seed'
    for path in seed.iterdir():
        if path.is_file():
            (root / path.name).write_bytes(path.read_bytes())
    def git(*args):
        subprocess.run(['git', *args], cwd=root, env=env, capture_output=True, text=True, check=True, timeout=10)
    git('init', '--template', str(template))
    git('config', 'user.name', 'Fixture Operator')
    git('config', 'user.email', 'fixture@example.invalid')
    hooks = root / '.git' / 'fixture-empty-hooks'
    hooks.mkdir()
    git('config', 'core.hooksPath', str(hooks))
    git('config', 'commit.gpgsign', 'false')
    git('add', '.')
    git('commit', '-m', 'lifecycle fixture baseline')
    with (root / 'FOREIGN.md').open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('Unrelated change to preserve.\n')
    print(root)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: prepare.py NEW_DISPOSABLE_DIRECTORY')
    prepare(sys.argv[1])
