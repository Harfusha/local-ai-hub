import ast
import hashlib
import json
import pathlib
import subprocess
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
AUDIT = pathlib.Path(__file__).parent
original = json.loads((AUDIT/'original-inventory.json').read_text())
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)
def sha(data):
    return hashlib.sha256(data).hexdigest()
relevant = set(original['relevant_untracked'])
untouched = [e for e in original['untracked'] if e['path'] not in relevant]
changed = [e['path'] for e in untouched if not (ROOT/e['path']).is_file() or sha((ROOT/e['path']).read_bytes()) != e['sha256']]
with zipfile.ZipFile(AUDIT/'original-bytes.zip') as archive:
    preserved = original['tracked_dirty'] + [e for e in original['untracked'] if e['path'] in relevant]
    backup_errors = [e['path'] for e in preserved if e['exists'] and sha(archive.read(e['path'])) != e['sha256']]
python_paths = git('diff', '--name-only', original['pin'], '--', 'src/', 'tests/').decode().splitlines()
syntax_errors = []
for p in python_paths:
    if not p.endswith('.py') or not (ROOT/p).is_file():
        continue
    try:
        compile((ROOT/p).read_bytes(), p, 'exec')
    except SyntaxError as exc:
        syntax_errors.append({'path': p, 'line': exc.lineno, 'error': str(exc)})
def pack_branch(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and any(isinstance(n, ast.Constant) and n.value == '/api/context/pack' for n in ast.walk(node.test)):
            return ast.dump(node, include_attributes=False)
    raise AssertionError('context pack branch not found')
master_http = git('show', original['pin']+':src/local_ai_hub/http_server.py').decode()
pack_same = pack_branch(master_http) == pack_branch((ROOT/'src/local_ai_hub/http_server.py').read_text())
remaining = git('status', '--porcelain=v1', '-uall').decode()
final_inventory = [{'path': e['path'], 'original_sha256': e['sha256'],
                    'current_sha256': sha((ROOT/e['path']).read_bytes()) if (ROOT/e['path']).is_file() else None,
                    'tracked_now': bool(git('ls-files', '--', e['path']).strip())}
                   for e in original['tracked_dirty'] + original['untracked']]
report = {'original_head': original['original_head'], 'checkpoint': 'df9850131a79191c5a860a1d231d3acd867869db',
          'checkpoint_ref': 'refs/heads/codex/backup-t05-pre-sync-20261006',
          'original_tracked_count': len(original['tracked_dirty']), 'original_untracked_count': len(original['untracked']),
          'raw_backup_verified_count': len(preserved), 'raw_backup_errors': backup_errors,
          'untouched_original_artifact_count': len(untouched), 'untouched_original_artifact_errors': changed,
          'python_compile_errors': syntax_errors, 'context_pack_ast_matches_initial_pin': pack_same,
          'remaining_status': remaining, 'original_path_final_hashes': final_inventory}
(AUDIT/'preservation-receipt.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in {'remaining_status', 'original_path_final_hashes'}}))
assert not changed and not backup_errors and not syntax_errors and pack_same
