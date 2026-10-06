"""Checkpoint exact original ordinary artifact bytes; never execute archived code."""
import hashlib
import json
import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
AUDIT = pathlib.Path(__file__).parent
BASE_HEAD = 'f3ffb01851ffdecf33127892a0cdd93f433a2239'
BASE_REF = 'refs/heads/codex/backup-t05-pre-sync-20261006'
SUPPLEMENT_REF = 'refs/heads/codex/backup-t05-all-ordinary-20261006'

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def paths(*args):
    return [p for p in git(*args, '-z').decode().split('\0') if p]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def entry(path, reason=None):
    target = ROOT/path
    assert target.is_file(), path
    result = {'path': path, 'sha256': digest(target.read_bytes()), 'size': target.stat().st_size}
    if reason:
        result['exclusion_reason'] = reason
    return result

assert ROOT.as_posix() == 'C:/Users/Adam/.codex/worktrees/t05-identity-recovery/.local-ai-hub'
original = json.loads((AUDIT/'original-inventory.json').read_text())
relevant = set(original['relevant_untracked'])
remaining = [e for e in original['untracked'] if e['path'] not in relevant]
assert len(remaining) == 386
errors = [e['path'] for e in remaining if not (ROOT/e['path']).is_file() or digest((ROOT/e['path']).read_bytes()) != e['sha256']]
assert not errors, errors
assert git('rev-parse', BASE_REF).decode().strip() == 'df9850131a79191c5a860a1d231d3acd867869db'
ignored = paths('ls-files', '--others', '--ignored', '--exclude-standard')
expanded_ignored = []
for path in ignored:
    target = ROOT/path
    if target.is_dir():
        expanded_ignored.extend(p.relative_to(ROOT).as_posix() for p in target.rglob('*') if p.is_file())
    else:
        expanded_ignored.append(path)
ignored = sorted(set(expanded_ignored))
excluded = []
extra_ordinary = []
for path in ignored:
    if path.startswith('artifacts/sync-t05-20261006/pytest-run'):
        reason = 'generated test temporary state; whole test fixture namespace remains outside Git'
    elif '/__pycache__/' in path or path.endswith(('.pyc', '.pyo')):
        reason = 'generated Python bytecode cache'
    elif path.startswith('.pytest_cache/'):
        reason = 'generated pytest cache state'
    elif path.startswith('.serena/'):
        reason = 'preexisting local Serena backend registration/configuration/cache state; outside original nonignored inventory'
    elif path.startswith('artifacts/') and path.endswith('.log'):
        extra_ordinary.append(entry(path))
        continue
    else:
        raise AssertionError('unclassified ignored path: '+path)
    excluded.append(entry(path, reason))

if len(sys.argv) == 1 or sys.argv[1] == 'checkpoint':
    assert git('rev-parse', 'HEAD').decode().strip() == BASE_HEAD
    assert not git('diff', '--name-only').strip()
    ordinary = remaining + extra_ordinary
    for e in ordinary:
        with (ROOT/e['path']).open('rb') as source:
            assert source.read(16) != b'SQLite format 3\x00', e['path']
        assert not e['path'].endswith(('.sqlite3', '.db', '.pyc', '.pyo', '.pid', '.lock')), e['path']
    with zipfile.ZipFile(AUDIT/'original-ordinary-bytes.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for e in ordinary:
            archive.write(ROOT/e['path'], e['path'])
    with zipfile.ZipFile(AUDIT/'original-ordinary-bytes.zip') as archive:
        archive_errors = [e['path'] for e in ordinary if digest(archive.read(e['path'])) != e['sha256']]
    assert not archive_errors
    manifest = {'base_head': BASE_HEAD, 'baseline_checkpoint_ref': BASE_REF,
                'supplemental_checkpoint_ref': SUPPLEMENT_REF, 'original_ordinary_count': len(remaining),
                'additional_preexisting_ignored_receipt_log_count': len(extra_ordinary),
                'original_hash_errors': errors, 'archive_hash_errors': archive_errors,
                'committed_ordinary_paths_and_raw_hashes': ordinary,
                'excluded_original_inventory_paths': [],
                'excluded_untracked_or_ignored_state_paths': excluded}
    (AUDIT/'ordinary-preservation-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    git('add', '--', *[e['path'] for e in remaining])
    if extra_ordinary:
        git('add', '-f', '--', *[e['path'] for e in extra_ordinary])
    git('add', '--', 'artifacts/sync-t05-20261006/preserve-ordinary.py',
        'artifacts/sync-t05-20261006/original-ordinary-bytes.zip',
        'artifacts/sync-t05-20261006/ordinary-preservation-manifest.json')
    git('commit', '-m', 'chore(sync): checkpoint all original T05 ordinary artifacts and exact bytes')
    git('update-ref', SUPPLEMENT_REF, 'HEAD')
    print(json.dumps({'checkpoint': git('rev-parse', 'HEAD').decode().strip(),
                      'ref': SUPPLEMENT_REF, 'original_ordinary_count': len(remaining),
                      'extra_receipt_logs': len(extra_ordinary), 'excluded_state_count': len(excluded),
                      'original_hash_errors': errors, 'archive_hash_errors': archive_errors}))
else:
    assert sys.argv[1] == 'receipt'
    manifest = json.loads((AUDIT/'ordinary-preservation-manifest.json').read_text())
    tracked = set(paths('ls-files'))
    with zipfile.ZipFile(AUDIT/'original-ordinary-bytes.zip') as archive:
        archive_errors = [e['path'] for e in manifest['committed_ordinary_paths_and_raw_hashes']
                          if digest(archive.read(e['path'])) != e['sha256']]
    with zipfile.ZipFile(AUDIT/'original-bytes.zip') as archive:
        baseline_entries = original['tracked_dirty']+[e for e in original['untracked'] if e['path'] in relevant]
        baseline_errors = [e['path'] for e in baseline_entries if digest(archive.read(e['path'])) != e['sha256']]
    assert not baseline_errors and not archive_errors and not errors
    uncommitted_original = [e['path'] for e in original['untracked'] if e['path'] not in tracked]
    assert not uncommitted_original, uncommitted_original
    receipt = json.loads((AUDIT/'preservation-receipt.json').read_text())
    receipt['supplemental_checkpoint_ref'] = SUPPLEMENT_REF
    receipt['supplemental_checkpoint_head'] = git('rev-parse', SUPPLEMENT_REF).decode().strip()
    receipt['final_head_branch_ref'] = 'refs/heads/codex/sync-t05-20261006'
    receipt['final_head_status_blob_ref'] = 'refs/codex/receipts/t05-complete-preservation-final'
    receipt['all_original_raw_backup_verified_count'] = len(baseline_entries)+len(remaining)
    receipt['supplemental_raw_archive_verified_count'] = len(manifest['committed_ordinary_paths_and_raw_hashes'])
    receipt['all_archived_file_bytes_verified_count'] = len(baseline_entries)+len(manifest['committed_ordinary_paths_and_raw_hashes'])
    receipt['all_original_raw_backup_errors'] = baseline_errors+archive_errors
    receipt['all_original_untracked_committed_count'] = len(original['untracked'])
    receipt['remaining_original_untracked_status'] = []
    receipt['remaining_tracked_source_dirty'] = []
    receipt['final_expected_git_status_porcelain'] = ''
    receipt['final_head_status_receipt_method'] = 'Exact final head/status stored after audit commit in final_head_status_blob_ref; prevents self-referential commit hash.'
    receipt['excluded_original_inventory_paths'] = []
    receipt['excluded_untracked_or_ignored_state_paths'] = excluded
    receipt['supplemental_committed_paths_and_raw_hashes'] = manifest['committed_ordinary_paths_and_raw_hashes']
    receipt['original_path_final_hashes'] = [dict(path=e['path'], original_sha256=e['sha256'],
                                               size=e['size'], tracked_now=e['path'] in tracked,
                                               current_sha256=digest((ROOT/e['path']).read_bytes()))
                                           for e in original['tracked_dirty']+original['untracked']]
    (AUDIT/'preservation-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'all_original_raw_backup_verified_count': receipt['all_original_raw_backup_verified_count'],
                      'all_original_raw_backup_errors': receipt['all_original_raw_backup_errors'],
                      'remaining_original_untracked': uncommitted_original,
                      'excluded_state_count': len(excluded), 'supplemental_checkpoint': receipt['supplemental_checkpoint_head']}))
