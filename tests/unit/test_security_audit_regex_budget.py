import random
from types import SimpleNamespace

import local_ai_hub.deterministic as deterministic
from local_ai_hub.deterministic import DeterministicEngine


def _audit(root, path):
    inventory = {'complete': True, 'reasons': [], '_identity': {str(path): ()}}
    engine = SimpleNamespace(_root=lambda _: str(root), repo_tools=SimpleNamespace(
        security_inventory=lambda *_args, **_kwargs: ([path], dict(inventory)),
        max_file_bytes=2_000_000,
    ))
    return DeterministicEngine.security_audit(engine, str(root))


def test_adversarial_yaml_scan_completes_without_quadratic_regex(tmp_path, monkeypatch):
    path = tmp_path / 'data.js'
    path.write_text('yaml.load(' * 5000 + 'x' * 50000, encoding='utf-8')
    expensive = dict(deterministic._SECURITY_AUDIT_SMELLS)['Unsafe PyYAML']
    original = deterministic._pattern_match_lines
    def check(text, pattern):
        assert pattern is not expensive, 'unbounded PyYAML regex was invoked'
        return original(text, pattern)
    monkeypatch.setattr(deterministic, '_pattern_match_lines', check)

    result = _audit(tmp_path, path)
    assert result['scan_complete'] is True and result['is_clean'] is True
    assert result['scan_errors'] == []


def test_ordinary_yaml_finding_is_preserved(tmp_path):
    path = tmp_path / 'normal.js'
    path.write_text('data = yaml.load(payload)\n', encoding='utf-8')
    result = _audit(tmp_path, path)
    assert result['scan_complete'] is True
    assert any(finding['title'] == 'Unsafe PyYAML' for finding in result['findings'])


def test_yaml_scanner_matches_original_regex_on_varied_short_inputs():
    original = dict(deterministic._SECURITY_AUDIT_SMELLS)['Unsafe PyYAML']
    tokens = ['yaml.load(', ')', ',', 'x', ' ', '\n', 'Loader=', 'yaml.', 'Unsafe', 'Full', 'Loader', '_', '']
    generator = random.Random(427)
    cases = ['yaml.load(x)', 'yaml.load()', 'yaml.load(fn(x), Loader=yaml.FullLoader)',
             'yaml.load(yaml.load(x))', 'yaml.load(x, Loader=SafeLoader)']
    cases.extend(''.join(generator.choices(tokens, k=generator.randrange(1, 40))) for _ in range(2500))
    for text in cases:
        assert deterministic._yaml_load_match_lines(text) == deterministic._pattern_match_lines(text, original), repr(text)
