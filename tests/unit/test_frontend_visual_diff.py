from __future__ import annotations

import base64
import struct
import zlib
import json
from types import SimpleNamespace

import pytest

from local_ai_hub import frontend_review
from local_ai_hub.vision_service import VisionService
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub import mcp_server


def _png(color: bytes) -> bytes:
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00' + color)) + chunk(b'IEND', b''))


def test_visual_diff_sends_ordered_images_to_existing_vision_runner():
    baseline, candidate = _png(b'\x00\x00\x00'), _png(b'\xff\xff\xff')
    calls = []
    def review(args):
        calls.append(args)
        return {'success': True, 'findings': [{'category': 'visual-regression'}]}
    result = frontend_review.compare_screens(baseline, candidate, review=review)
    assert result['success'] is True
    assert result['comparison']['bytes_identical'] is False
    assert base64.b64decode(calls[0]['image']) == baseline
    assert base64.b64decode(calls[0]['comparison_image']) == candidate
    assert 'Image 0 is the baseline' in calls[0]['prompt']
    assert 'untrusted' in calls[0]['prompt'].lower()
    assert result['findings'] == [{'category': 'visual-regression'}]


@pytest.mark.parametrize('bad', [b'', b'not a png', b'\x89PNG\r\n\x1a\n'])
def test_visual_diff_rejects_invalid_input_before_model(bad):
    calls = []
    result = frontend_review.compare_screens(bad, _png(b'\x00\x00\x00'), review=lambda args: calls.append(args))
    assert result['success'] is False
    assert result['terminal'] is True
    assert calls == []


def test_visual_diff_preserves_model_unavailability():
    failure = {'success': False, 'error_code': 'vision_model_unavailable', 'retryable': False}
    png = _png(b'\x00\x00\x00')
    result = frontend_review.compare_screens(png, png, review=lambda args: failure)
    assert result['error_code'] == 'vision_model_unavailable'
    assert result['success'] is False


def test_visual_diff_rejects_corrupt_crc_and_excessive_dimensions_before_model():
    png = _png(b'\x00\x00\x00')
    corrupt_crc = png[:-1] + bytes([png[-1] ^ 1])
    huge = png[:16] + struct.pack('>II', 100_000, 100_000) + png[24:]
    calls = []
    for invalid in (corrupt_crc, huge):
        result = frontend_review.compare_screens(invalid, png, review=lambda args: calls.append(args))
        assert result['error_code'] == 'visual_comparison_input_invalid'
    assert calls == []


def test_shared_vision_service_compares_owner_global_artifacts(tmp_path):
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    baseline, candidate = _png(b'\x00\x00\x00'), _png(b'\xff\xff\xff')
    before = artifacts.put_bytes(baseline, kind='before', mime_type='image/png')
    after = artifacts.put_bytes(candidate, kind='after', mime_type='image/png')
    calls = []
    def request(endpoint, payload, *, timeout):
        calls.append((endpoint, payload))
        if endpoint == '/api/show':
            return {'capabilities': ['vision']}
        return {'response': json.dumps({'summary': 'Background changed.', 'findings': [], 'unknowns': [], 'recommended_checks': []})}
    service = VisionService(
        config={'models': {'vision': 'installed-vl'}}, runtime=SimpleNamespace(request=request),
        artifacts=artifacts, model_policy=SimpleNamespace(apply_payload=lambda model, payload, **kw: (payload, {})),
        repo_tools=None, max_output_tokens=1024,
    )
    args = {'baseline_screenshot_artifact_id': before, 'screenshot_artifact_id': after}
    result = service.run(args)
    assert result['success'] is True
    assert result['comparison']['bytes_identical'] is False
    payload = next(payload for endpoint, payload in calls if endpoint == '/api/generate')
    assert [base64.b64decode(item) for item in payload['images']] == [baseline, candidate]
    calls.clear()
    repeated = service.run(args)
    assert repeated['success'] is True
    assert calls
    calls.clear()
    cloud = service.run({**args, 'cloud_fallback': True})
    assert cloud['error_code'] == 'visual_comparison_local_only'
    assert calls == []


def test_mcp_adapter_routes_comparison_and_preserves_result(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, 'tasks', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'vision', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'has_any_model', lambda: True)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda _event: None)
    comparison = {'bytes_identical': False, 'baseline_sha256': 'a' * 64, 'candidate_sha256': 'b' * 64}
    def post(path, payload, timeout=None):
        calls.append((path, payload))
        return {'success': True, 'review': {'summary': 'Changed', 'findings': []}, 'comparison': comparison}
    monkeypatch.setattr(mcp_server, 'CLIENT', SimpleNamespace(post=post))
    monkeypatch.setattr(mcp_server, '_record_tool_accounting', lambda **_: None)
    result = mcp_server.local_ai_task(
        action='vision', root=str(tmp_path), baseline_screenshot_artifact_id='before',
        screenshot_artifact_id='after',
    )
    assert calls, result
    assert calls[0][0] == '/api/task/vision'
    assert calls[0][1]['baseline_screenshot_artifact_id'] == 'before'
    assert result['comparison'] == comparison
