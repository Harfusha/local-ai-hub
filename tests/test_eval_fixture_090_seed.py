from pathlib import Path
import shutil
import subprocess
import sys

FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-090'


def test_seed_is_disposable_and_oracle_detects_old_contract(tmp_path):
    target = tmp_path / 'fixture'
    shutil.copytree(FIXTURE, target)
    result = subprocess.run([sys.executable, 'oracle_090.py'], cwd=target, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert 'FAILED' in result.stderr
    assert 'Ran 4 tests' in result.stderr


def test_oracle_accepts_a_corrected_reference_copy(tmp_path):
    target = tmp_path / 'fixture'
    shutil.copytree(FIXTURE, target)
    server = target / 'server.py'
    source = server.read_text(encoding='utf-8')
    old = """            if self.path != '/checkpoint' or not isinstance(payload.get('phase'), str):
                raise ValueError('expected flat phase')
            result, status = {'ok': True, 'checkpoint': payload}, 200"""
    new = """            if self.path != '/checkpoint' or set(payload) != {'checkpoint'}:
                raise ValueError('expected checkpoint')
            checkpoint = payload['checkpoint']
            fields = {'phase', 'next_action', 'affected_paths', 'evidence_ids', 'blockers', 'state_data'}
            if not isinstance(checkpoint, dict) or set(checkpoint) != fields:
                raise ValueError('invalid fields')
            if any(not isinstance(checkpoint[k], str) or not checkpoint[k] for k in ('phase', 'next_action')):
                raise ValueError('invalid text')
            if any(not isinstance(checkpoint[k], list) or any(not isinstance(v, str) for v in checkpoint[k]) for k in ('affected_paths', 'evidence_ids', 'blockers')):
                raise ValueError('invalid list')
            if not isinstance(checkpoint['state_data'], dict):
                raise ValueError('invalid state')
            result, status = {'ok': True, 'checkpoint': checkpoint}, 200"""
    assert old in source
    server.write_text(source.replace(old, new), encoding='utf-8')
    sdk = target / 'sdk.py'
    sdk_source = sdk.read_text(encoding='utf-8').replace('def checkpoint(base_url, **fields):', 'def checkpoint(base_url, *, checkpoint):').replace('json.dumps(fields)', "json.dumps({'checkpoint': checkpoint})")
    sdk.write_text(sdk_source, encoding='utf-8')
    (target / 'adapter.py').write_text('from sdk import checkpoint\n\ndef checkpoint_task(base_url, *, checkpoint):\n    return __import__("sdk").checkpoint(base_url, checkpoint=checkpoint)\n', encoding='utf-8')
    for name in ('INSTALL_PROMPT.md', 'UPDATE_PROMPT.md'):
        (target / name).write_text('checkpoint phase next_action affected_paths evidence_ids blockers state_data', encoding='utf-8')
    result = subprocess.run([sys.executable, 'oracle_090.py'], cwd=target, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
