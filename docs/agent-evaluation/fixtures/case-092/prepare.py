"""Prepare a new, disposable Git repository for the closed-delegation case."""
from pathlib import Path
import os
import shutil
import subprocess
import sys


def prepare(target):
    candidate = Path(target)
    if not candidate.is_absolute():
        raise ValueError("the disposable root must be an absolute path")
    root = candidate.resolve()
    parent = root.parent
    if not parent.is_dir():
        raise ValueError("the disposable root's parent must already exist")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C'})
    if any((ancestor / '.git').exists() for ancestor in (parent, *parent.parents)):
        raise ValueError("the disposable root must not be inside another Git repository")
    probe = subprocess.run(['git', '-C', str(parent), 'rev-parse', '--git-dir'],
                           env=env, capture_output=True, text=True, timeout=15)
    if probe.returncode == 0:
        raise ValueError("the disposable root must not be inside another Git repository")
    if probe.returncode != 128 or 'not a git repository' not in probe.stderr.lower():
        raise RuntimeError("could not establish whether the parent belongs to a Git repository")
    root.mkdir(exist_ok=False)
    template = root / '.fixture-empty-template'
    hooks = root / '.fixture-empty-hooks'
    template.mkdir()
    hooks.mkdir()

    def git(*args):
        result = subprocess.run(['git', *args], cwd=root, env=env, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError(f"git {args[0]} failed: {result.stderr[:500]}")
        return result.stdout.strip()

    git('init', '-b', 'fixture-base', '--template', str(template))
    git('config', 'user.name', 'Fixture Operator')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'core.hooksPath', str(hooks))
    git('config', 'commit.gpgsign', 'false')
    git('config', 'core.autocrlf', 'false')
    seed = Path(__file__).resolve().parent
    names = ('report.py', 'oracle_092.py', 'zadani.md', 'seed_manifest.json', 'prepare.py')
    for name in names:
        shutil.copyfile(seed / name, root / name)
    git('add', '--', *names)
    git('commit', '-m', 'case 092 fixture seed')
    print(f"root={root}")
    print(f"seed_commit={git('rev-parse', 'HEAD')}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: prepare.py NEW_DISPOSABLE_DIRECTORY')
    prepare(sys.argv[1])
