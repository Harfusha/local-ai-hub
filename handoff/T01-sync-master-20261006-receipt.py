"""Generate bounded T01 synchronization receipts; never change source or Git state."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = Path('C:/Users/Adam/.codex/worktrees/t01-coverage-main-verify/.local-ai-hub').resolve()
assert ROOT == EXPECTED
PIN = '614a6a50ac2a3e4106270136cb8e584e770c3752'
CHECKPOINT = 'refs/checkpoints/sync-t01-complete-original-20261006'

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def sha(data):
    return hashlib.sha256(data).hexdigest().upper()

snapshot = json.loads((ROOT / 'handoff/T01-sync-master-20261006-original-state.json').read_text())
originals = snapshot['tracked_dirty'] + snapshot['untracked']
backup_failures = [e['path'] for e in originals if sha(git('show', CHECKPOINT + ':' + e['path'])) != e['sha256']]
archives = [e for e in snapshot['untracked'] if not e['master_collision']]
archive_failures = [e['path'] for e in archives if sha(git('show', 'HEAD:' + e['path'])) != e['sha256']]
working_failures = [e['path'] for e in archives if sha((ROOT / e['path']).read_bytes()) != e['sha256']]
tracked = set(git('ls-files').decode().splitlines())
missing = [e['path'] for e in snapshot['untracked'] if e['path'] not in tracked]
runtime = ROOT / '.sync-t01-runtime'
runtime_files = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p.read_bytes())}
                 for p in sorted(runtime.rglob('*')) if p.is_file()]
assert not backup_failures and not archive_failures and not working_failures and not missing
assert not git('ls-files', '-u')
assert subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', PIN, 'HEAD']).returncode == 0
receipt = {
    'root': str(ROOT), 'branch': git('branch', '--show-current').decode().strip(),
    'audited_merge_head': git('rev-parse', 'HEAD').decode().strip(),
    'initial_pin': PIN, 'initial_pin_is_ancestor': True,
    'latest_observed_not_merged': '9b794d7fa24abb179a17d87e14becdfa7fc8cd50',
    'latest_merge_skipped_by_final_user_instruction': True,
    'checkpoint_ref': CHECKPOINT, 'checkpoint_head': git('rev-parse', CHECKPOINT).decode().strip(),
    'original_files_checkpoint_verified': len(originals), 'checkpoint_hash_failures': backup_failures,
    'original_untracked_now_tracked': len(snapshot['untracked']), 'missing_original_untracked': missing,
    'original_handoff_committed_byte_exact': len(archives), 'archive_hash_failures': archive_failures,
    'original_handoff_working_hash_failures': working_failures,
    'unresolved_entries': [],
    'status_before_receipt_writes': git('status', '--porcelain=v1', '--untracked-files=all').decode().splitlines(),
    'excluded_original_untracked': [], 'excluded_new_runtime_files': len(runtime_files),
    'runtime_manifest': 'handoff/T01-sync-master-20261006-runtime-paths.json',
    'diff_paths_against_initial_pin': git('diff', '--name-only', PIN, 'HEAD').decode().splitlines(),
    'diff_stat_against_initial_pin': git('diff', '--stat', PIN, 'HEAD').decode(),
    'diff_numstat_against_initial_pin': git('diff', '--numstat', PIN, 'HEAD').decode(),
    'targeted_tests': {'initial_passed': 821, 'initial_failed': 11, 'seconds': 89.82,
                       'context_followup_passed': 2, 'context_followup_seconds': 7.00,
                       'other_initial_failures_not_rerun': 9},
    'coverage_check': {'coverage_matches': True, 'rows': 652, 'drift': [], 'exit_code': 0},
    'acceptance': 'INCOMPLETE; committed reconciliation does not prove acceptance',
    'receipt_commit_note': 'This audits merge commit; receipts are committed in its direct child.'
}
(ROOT / 'handoff/T01-sync-master-20261006-runtime-paths.json').write_text(json.dumps(runtime_files, indent=2) + '\n')
(ROOT / 'handoff/T01-sync-master-20261006-final-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({k: receipt[k] for k in ('audited_merge_head', 'original_files_checkpoint_verified',
      'original_untracked_now_tracked', 'original_handoff_committed_byte_exact',
      'status_before_receipt_writes', 'excluded_new_runtime_files')}))
