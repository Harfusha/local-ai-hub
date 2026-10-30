"""Create an actual merge conflict only in a new disposable directory."""
from pathlib import Path
import os
import subprocess
import sys


def git_env():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'LC_ALL': 'C'})
    return env


def run(root, *args, expect=0):
    result = subprocess.run(['git', *args], cwd=root, env=git_env(), capture_output=True, text=True, timeout=10)
    if result.returncode != expect:
        raise RuntimeError(f'git {args}: {result.stderr} {result.stdout}')
    return result


def prepare(root):
    candidate = Path(root)
    if not candidate.is_absolute():
        raise ValueError('disposable root must be an absolute path')
    root = candidate.resolve()
    if not root.parent.is_dir():
        raise ValueError('disposable root parent must already exist')
    if any((ancestor / '.git').exists() for ancestor in (root.parent, *root.parent.parents)):
        raise ValueError('disposable root must not be inside another Git repository')
    parent_probe = subprocess.run(['git', '-C', str(root.parent), 'rev-parse', '--git-dir'], env=git_env(), capture_output=True, text=True, timeout=10)
    if parent_probe.returncode == 0:
        raise ValueError('disposable root must not be inside another Git repository')
    if parent_probe.returncode != 128 or 'not a git repository' not in parent_probe.stderr.lower():
        raise RuntimeError('could not establish whether the parent belongs to a Git repository')
    root.mkdir(parents=False, exist_ok=False)
    template = root / '.fixture-empty-template'
    template.mkdir()
    run(root, 'init', '-b', 'fixture-base', '--template', str(template))
    run(root, 'config', 'user.name', 'Fixture Operator')
    run(root, 'config', 'user.email', 'fixture@example.invalid')
    hooks = root / '.git' / 'fixture-empty-hooks'
    hooks.mkdir()
    run(root, 'config', 'core.hooksPath', str(hooks))
    run(root, 'config', 'commit.gpgsign', 'false')
    (root / 'pricing.py').write_text('def total(price, fee, discount):\n    return price\n', encoding='utf-8')
    (root / 'test_pricing.py').write_text('import unittest\nfrom pricing import total\n\nclass PricingTests(unittest.TestCase):\n    def test_fee_and_discount(self):\n        self.assertEqual(total(100, 8, 13), 95)\n        self.assertEqual(total(0, 5, 0), 5)\n        self.assertEqual(total(20, 0, 4), 16)\n', encoding='utf-8')
    (root / 'PLAN.md').write_text('Cíl: výsledná cena zahrnuje poplatek i slevu. Po integraci ověř oba scénáře aktuálním testem.\n', encoding='utf-8')
    run(root, 'add', 'pricing.py', 'test_pricing.py', 'PLAN.md')
    run(root, 'commit', '-m', 'fixture base')
    run(root, 'switch', '-c', 'agent-a')
    (root / 'pricing.py').write_text('def total(price, fee, discount):\n    return price + fee\n', encoding='utf-8')
    run(root, 'commit', '-am', 'agent A fee')
    run(root, 'switch', '-c', 'agent-b', 'fixture-base')
    (root / 'pricing.py').write_text('def total(price, fee, discount):\n    return price - discount\n', encoding='utf-8')
    run(root, 'commit', '-am', 'agent B discount')
    run(root, 'merge', '--no-edit', 'agent-a', expect=1)
    if 'UU pricing.py' not in run(root, 'status', '--porcelain').stdout:
        raise RuntimeError('Expected a genuine unmerged file')
    (root / 'CHECKPOINT.md').write_text('Fixture checkpoint: agent-a commit přidal poplatek, agent-b commit slevu; merge je konfliktní. Toto je připravená simulace, nikoli důkaz reálného přerušení agenta.\n', encoding='utf-8')
    print(root)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: prepare.py NEW_DISPOSABLE_DIRECTORY')
    prepare(sys.argv[1])
