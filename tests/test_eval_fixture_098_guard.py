from pathlib import Path
import ast
import importlib.util
import subprocess
import sys

FIXTURE = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-098'
INVOCATION = FIXTURE / 'invocation.py'


def _load_invocation():
    spec = importlib.util.spec_from_file_location('case_098_invocation', INVOCATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SCRIPT = Path(__file__).resolve().parents[1] / 'docs' / 'agent-evaluation' / 'fixtures' / 'case-098' / 'run.py'


def test_sandbox_runner_rejects_foreign_interpreter_before_writes(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'sandbox venv interpreter' in result.stderr
    assert not (tmp_path / 'state').exists()


def test_sandbox_runner_rejects_noncanonical_task_id_before_writes(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--task-id', '../escape'], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'invalid task ID' in result.stderr
    assert not (tmp_path / 'state').exists()


def test_sandbox_runner_accepts_noninteractive_option_before_sandbox_checks(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--no-wait'], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'sandbox venv interpreter' in result.stderr
    assert not (tmp_path / 'state').exists()


def test_fixture_adapter_allows_context_compile_only_for_exact_sandbox_root(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    validate = _load_invocation().validate_invocation

    tool, arguments = validate({
        'tool': 'local_ai_coord', 'action': 'context_compile',
        'root': str(workspace), 'task_id': 'task_fixture_104',
    }, workspace)

    assert tool == 'local_ai_coord'
    assert arguments['action'] == 'context_compile'
    assert 'tool' not in arguments


def test_fixture_adapter_reads_artifact_pages_only_with_explicit_id_and_root(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    validate = _load_invocation().validate_invocation

    tool, arguments = validate({
        'tool': 'local_ai_artifact', 'action': 'get',
        'artifact_id': 'artifact_fixture_104', 'root': str(workspace),
        'offset': 0, 'max_chars': 1000,
    }, workspace)

    assert tool == 'local_ai_artifact'
    assert arguments['artifact_id'] == 'artifact_fixture_104'
    assert arguments['offset'] == 0
    assert 'tool' not in arguments


def test_fixture_adapter_rejects_mutation_and_foreign_root(tmp_path):
    workspace = tmp_path / 'workspace'
    other = tmp_path / 'other'
    workspace.mkdir()
    other.mkdir()
    validate = _load_invocation().validate_invocation

    for arguments in (
        {'tool': 'local_ai_coord', 'action': 'memory_record', 'root': str(workspace)},
        {'tool': 'local_ai_coord', 'action': 'context_compile', 'root': str(other), 'task_id': 'task_104'},
        {'tool': 'local_ai_artifact', 'action': 'get', 'root': str(workspace)},
        {'tool': 'local_ai_artifact', 'action': 'source', 'root': str(workspace), 'path': 'x.py'},
    ):
        try:
            validate(arguments, workspace)
        except ValueError:
            continue
        raise AssertionError(f'unsafe fixture invocation accepted: {arguments!r}')


def test_fixture_adapter_preserves_null_terminal_paging_metadata():
    import json

    class MCPResult:
        structuredContent = {'next_offset': None, 'success': True}

        def model_dump_json(self, *, exclude_none):
            value = {'structuredContent': dict(self.structuredContent)}
            if exclude_none:
                value['structuredContent'].pop('next_offset')
            return json.dumps(value)

    serialize_result = _load_invocation().serialize_result

    result = json.loads(serialize_result(MCPResult()))

    assert result == {'next_offset': None, 'success': True}


def test_fixture_adapter_suppresses_child_mcp_logs_from_json_output():
    tree = ast.parse((FIXTURE / 'call_mcp.py').read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == 'stdio_client']

    assert calls and any(keyword.arg == 'errlog' for call in calls for keyword in call.keywords)
