import hashlib
import json
import pathlib
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
PIN = '614a6a50ac2a3e4106270136cb8e584e770c3752'
AUDIT = pathlib.Path(__file__).parent

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

assert ROOT.as_posix() == 'C:/Users/Adam/.codex/worktrees/t05-identity-recovery/.local-ai-hub'
tracked = git('diff', '--name-only', 'HEAD', '-z').decode().strip('\0').split('\0')
untracked = git('ls-files', '--others', '--exclude-standard', '-z').decode().strip('\0').split('\0')
untracked = [p for p in untracked if not p.startswith('artifacts/sync-t05-20261006/')]
master_paths = set(git('ls-tree', '-r', '--name-only', '-z', PIN).decode().strip('\0').split('\0'))
collisions = [p for p in untracked if p in master_paths]
relevant = [p for p in untracked if p.startswith(('src/', 'tests/', 'docs/', 'mcp/', 'tools/')) or p in collisions]
def entry(p):
    f = ROOT / p
    return {'path': p, 'exists': f.exists(), 'sha256': hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None,
            'size': f.stat().st_size if f.exists() else None}
inventory = {'root': str(ROOT), 'pin': PIN, 'original_head': git('rev-parse', 'HEAD').decode().strip(),
             'original_branch': git('branch', '--show-current').decode().strip(),
             'observed_master': git('rev-parse', 'refs/heads/master').decode().strip(),
             'status_porcelain': git('status', '--porcelain=v1', '-uall').decode(),
             'tracked_dirty': [entry(p) for p in tracked], 'untracked': [entry(p) for p in untracked],
             'relevant_untracked': relevant, 'collisions': collisions}
(AUDIT / 'original-inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
with zipfile.ZipFile(AUDIT / 'original-bytes.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for p in tracked + relevant:
        if (ROOT / p).is_file():
            archive.write(ROOT / p, p)
    archive.writestr('tracked-worktree.patch', git('diff', '--binary', 'HEAD'))
    archive.writestr('original-index.patch', git('diff', '--cached', '--binary'))
print(json.dumps({'tracked': len(tracked), 'untracked': len(untracked), 'relevant': relevant, 'collisions': collisions}))
git('switch', '-c', 'codex/sync-t05-20261006')
git('add', '-u')
if relevant:
    git('add', '--', *relevant)
git('add', '--', 'artifacts/sync-t05-20261006/checkpoint.py', 'artifacts/sync-t05-20261006/original-inventory.json', 'artifacts/sync-t05-20261006/original-bytes.zip')
git('commit', '-m', 'chore: checkpoint T05 identity and durable memory work before master sync')
git('update-ref', 'refs/heads/codex/backup-t05-pre-sync-20261006', 'HEAD')
print('checkpoint=' + git('rev-parse', 'HEAD').decode().strip())
