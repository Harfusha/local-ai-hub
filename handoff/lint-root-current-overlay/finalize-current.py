"""Source-only final handoff from fresh normal-filesystem root copies."""
import ast
import datetime
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

base = Path(__file__).resolve().parent
snapshot = base / 'refresh3'
capture = json.loads((snapshot / 'capture.json').read_text(encoding='utf-8-sig'))
root = Path(capture['root'])
publish = base / 'ready-current-root'
if publish.exists():
    assert not any(publish.iterdir()), 'Refusing overwrite of existing publication'
else:
    publish.mkdir()
sha = lambda data: hashlib.sha256(data).hexdigest()
expected_changed = {'src/local_ai_hub/deterministic.py', 'src/local_ai_hub/scheduler.py', 'src/local_ai_hub/repo_tools.py', 'tools/benchmark_command_broker.py'}
receipt = {
    'status': 'VALIDATING', 'root': str(root), 'snapshot': str(snapshot),
    'owner': 'overlay misc worker; main review; T20 integration and release validation',
    'captured_utc': capture['captured_utc'],
    'source_only': True, 'root_writes': False, 'app_imports': False,
    'hub_gpu_build_pytest': False, 'new_chat_task_worktree': False,
    'baseline': capture['baseline'],
    'ast_command': subprocess.list2cmdline([sys.executable, '-B', str(Path(__file__).resolve())]),
    'ast_proof': 'Each of 14 final source ASTs equals prior validated desired AST; scheduler loop binding alpha-renamed only within requested_fields loop',
    'root_drift_resolution': 'Fresh Copy-Item capture; omit 10 already-applied files; restore original lower() RHS; complete existing metric_name loop references; preserve as_posix() RHS; restore original CommandBroker annotation via TYPE_CHECKING',
    'files': [], 'checks': [],
}
parts = []
changed = set()

def normalize(tree, relative):
    if relative == 'src/local_ai_hub/scheduler.py':
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) and node.iter.id == 'requested_fields':
                assert isinstance(node.target, ast.Name) and node.target.id in {'metric_field', 'metric_name'}
                binding = node.target.id
                for item in ast.walk(node):
                    if isinstance(item, ast.Name) and item.id == binding:
                        item.id = '__owned_metric_binding'
    return ast.dump(tree, include_attributes=False)

for entry in capture['files']:
    relative = entry['path']
    pre = (snapshot / 'preimage' / relative).read_bytes()
    post = (snapshot / 'owned' / relative).read_bytes()
    assert sha(pre) == entry['pre_sha256'] == sha((root / relative).read_bytes()), 'Root preimage drift: ' + relative
    ast.parse(pre, filename=relative)
    current = ast.parse(post, filename=relative)
    desired = ast.parse((base / 'owned' / relative).read_bytes(), filename=relative)
    assert normalize(current, relative) == normalize(desired, relative), 'Unexpected source AST: ' + relative
    receipt['files'].append({'path': relative, 'pre_sha256': sha(pre), 'post_sha256': sha(post), 'ast': 'PASS', 'changed': pre != post})
    if pre != post:
        changed.add(relative)
        parts.extend(difflib.unified_diff(pre.decode('utf-8').splitlines(keepends=True), post.decode('utf-8').splitlines(keepends=True), fromfile='a/' + relative, tofile='b/' + relative, n=3))
assert changed == expected_changed, changed
patch = publish / 'misc-pyflakes-current-root.patch'
patch.write_bytes(''.join(parts).replace('\r\n', '\n').encode('utf-8'))
receipt['patch_sha256'] = sha(patch.read_bytes())
receipt['patch_files'] = sorted(changed)
receipt['ast_passed'] = 14

def check(args, cwd):
    result = subprocess.run(args, cwd=str(cwd), capture_output=True, timeout=60)
    item = {'argv': args, 'command': subprocess.list2cmdline(args), 'cwd': str(cwd), 'exit_code': result.returncode, 'stdout': result.stdout.decode('utf-8', errors='replace'), 'stderr': result.stderr.decode('utf-8', errors='replace'), 'timeout_seconds': 60}
    receipt['checks'].append(item)
    (publish / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    assert result.returncode == 0, item

check([sys.executable, '-B', '-m', 'pyflakes', *[str(snapshot / 'owned' / item['path']) for item in capture['files']]], snapshot)
check(['git', 'apply', '--check', '--whitespace=error', str(patch)], root)
assert all(sha((root / item['path']).read_bytes()) == item['pre_sha256'] for item in receipt['files']), 'Root drift after checks'
receipt['root_preimages_match_after_checks'] = True
receipt['status'] = 'READY_SOURCE_STATIC_PASS; main review next; T20 root integration/release acceptance NOT RUN'
receipt['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
(publish / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
shutil.copyfile(snapshot / 'capture.json', publish / 'capture.json')
shutil.copyfile(Path(__file__), publish / 'finalize-current.py')
shutil.copyfile(base / 'refresh-current.ps1', publish / 'refresh-current.ps1')
shutil.copyfile(base / 'publish-20261001T160429863497Z' / 'receipt.json', publish / 'prior-14-file-static-receipt.json')
hashes = {path.name: sha(path.read_bytes()) for path in sorted(publish.iterdir()) if path.is_file()}
(publish / 'SHA256.json').write_text(json.dumps(hashes, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'status': receipt['status'], 'patch_path': str(patch), 'patch_sha256': receipt['patch_sha256'], 'patch_files': sorted(changed), 'ast': '14/14 PASS', 'pyflakes': 0, 'git_apply_check': 0, 'root_preimages_match': True, 'receipt_path': str(publish / 'receipt.json'), 'receipt_sha256': hashes['receipt.json']}, indent=2))
