"""One-shot T06 preservation; writes only this assigned checkout and new Git refs."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = Path('C:/Users/Adam/.codex/worktrees/t06-safe-commands/.local-ai-hub')
assert ROOT == EXPECTED
ORIGINAL = '94337de7309b66c63ff427cce8cd3a49e6414d73'
DIRTY = '348ce8ac'
REF = 'refs/heads/codex/checkpoint-t06-artifacts-20261006'
EXCLUDED = ('handoff/verify-root-final-95ylfgzj/',
            'handoff/verify-root-minimal-nwnilmii/',
            'handoff/verify-root-rollback-_nbj9j92/',
            'handoff/verify-sequential-lpwutn00/',
            'handoff/t06-sync-test-temp', 'handoff/t06-sync-runtime/')

def git(*args, data=None, env=None):
    return subprocess.check_output(['git', *args], cwd=ROOT, input=data, env=env, timeout=60)

def paths(*args):
    return git(*args).decode('utf-8').splitlines()

untracked = paths('ls-files', '--others', '--exclude-standard')
eligible = [p for p in untracked if not p.startswith(EXCLUDED)
            and not p.startswith('handoff/t06-sync-')
            and p != 'handoff/t06_sync_preservation.py']
dirty_paths = paths('diff', '--name-only', ORIGINAL, DIRTY)
entries = []
archive_path = ROOT / 'handoff/t06-sync-original-preservation.zip'
with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as archive:
    for path in dirty_paths:
        blob = git('show', DIRTY + ':' + path)
        for variant, raw in [('git-blob', blob), ('crlf-variant', blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))]:
            archive.writestr(variant + '/' + path, raw)
            entries.append({'path': path, 'variant': variant, 'sha256': hashlib.sha256(raw).hexdigest()})
    for path in eligible:
        raw = (ROOT / path).read_bytes()
        archive.writestr('original-untracked-raw/' + path, raw)
        entries.append({'path': path, 'variant': 'original-untracked-raw', 'sha256': hashlib.sha256(raw).hexdigest()})
excluded = sorted(set(p for p in untracked if p.startswith(EXCLUDED)) |
                  set(paths('ls-files', '--others', '--ignored', '--exclude-standard')))
manifest = {'original_head': ORIGINAL, 'dirty_checkpoint': DIRTY,
            'raw_untracked_count': len(eligible), 'entries': entries,
            'excluded_preserved_in_place': excluded,
            'newline_limit': 'Initial tracked bytes were Git-normalized before raw snapshot. LF Git blobs and CRLF variants recover content, but exact original newline identity is unverified.'}
manifest_path = ROOT / 'handoff/t06-sync-preservation-manifest.json'
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
index_path = ROOT / 'handoff/.t06-preservation.index'
environment = {**os.environ, 'GIT_INDEX_FILE': str(index_path)}
git('read-tree', DIRTY, env=environment)
for path in eligible + ['handoff/t06-sync-original-preservation.zip', 'handoff/t06-sync-preservation-manifest.json']:
    blob = git('hash-object', '-w', '--no-filters', '--', path).decode().strip()
    git('update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + path, env=environment)
tree = git('write-tree', env=environment).decode().strip()
commit = git('commit-tree', tree, '-p', DIRTY, data=b'checkpoint(t06): preserve original handoff artifacts and newline variants\n').decode().strip()
git('update-ref', REF, commit, '0' * 40)
print(json.dumps({'checkpoint_ref': REF, 'commit': commit, 'raw_untracked_count': len(eligible),
                  'excluded_path_count': len(excluded), 'archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest()}))
