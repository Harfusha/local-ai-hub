import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ['LOCAL_AI_CONFIG'] = str(ROOT / '.t03-sync-checks/config.toml')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONPATH'] = str(ROOT / 'src')
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / '.t03-sync-checks/tmp')
Path(os.environ['TEMP']).mkdir(exist_ok=True)
paths = subprocess.check_output(['git', 'diff', '--name-only', 'MERGE_HEAD'], text=True).splitlines()
errors = []
for path in paths:
    if path.endswith('.py') and Path(path).exists():
        try:
            ast.parse(Path(path).read_text(encoding='utf-8'), filename=path)
        except SyntaxError as exc:
            errors.append(f'{path}:{exc.lineno}: {exc.msg}')
print('AST:', 'PASS' if not errors else errors, flush=True)
if errors:
    sys.exit(2)
tests = [
    'tests/test_operation_contracts.py', 'tests/test_mcp_contract_dispatch.py',
    'tests/test_mcp_autostart_contract.py', 'tests/test_mutation_replay.py',
    'tests/test_agent_state_transport.py', 'tests/test_recovery_journal_contract.py',
    'tests/test_http_request_id_fallback.py', 'tests/test_inprocess_transport.py',
    'tests/test_mcp_operational_mode_dispatch.py', 'tests/test_async_operational_mode.py',
]
args = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider',
        '--basetemp=' + str(ROOT / '.t03-sync-checks/pytest-temp'), *tests]
print('COMMAND:', ' '.join(args), flush=True)
try:
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
except subprocess.TimeoutExpired as exc:
    print('TIMEOUT: 180 seconds', flush=True)
    sys.exit(124)
(ROOT / '.t03-sync-checks/pytest.log').write_text(result.stdout + result.stderr, encoding='utf-8')
print('\n'.join((result.stdout + result.stderr).splitlines()[-65:]), flush=True)
sys.exit(result.returncode)
