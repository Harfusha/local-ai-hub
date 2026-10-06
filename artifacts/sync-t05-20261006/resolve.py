"""Emit surgical patches from explicitly reviewed per-hunk merge decisions."""
import ast
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATTERN = re.compile(r'^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n', re.M | re.S)
# M = newer master contract; O = complementary T05 protection/fixture.
CHOICES = {
    'docs/SECURITY_MODEL.md': 'M',
    'src/local_ai_hub/agent_events.py': 'M'*18,
    'src/local_ai_hub/agent_tasks.py': 'MMM',
    'src/local_ai_hub/agent_memory.py': 'MMMMMMMMOMMMOMMMMMMM',
    'src/local_ai_hub/http_server.py': 'M'*12,
    'src/local_ai_hub/memory.py': 'O',
    'tests/test_agent_memory.py': 'M'*15,
    'tests/test_agent_memory_context_tenant_isolation.py': 'OMOMOOM',
    'tests/test_agent_memory_http_identity.py': 'O'*1+'M'*13,
    'tests/test_audit_round2_enhancements.py': 'MM',
    'tests/test_client_transport.py': 'M',
    'tests/test_identity_contracts.py': 'MMO',
    'tests/test_production_readiness_repairs.py': 'M',
    'tests/test_t05_agent_state_migrations.py': 'MMMMOMMMMMM',
    'tests/test_t05_cache_clear_durable_state.py': 'OO',
    'tests/test_t05_cache_state_isolation.py': 'O'*16,
    'tests/test_t05_memory_delete_artifacts.py': 'OMOOMOOOO',
    'tests/test_t05_memory_fts_atomicity.py': 'OOOMMO',
    'tests/test_vision_artifacts.py': 'M',
}
patches = []
for path, decisions in CHOICES.items():
    content = (ROOT/path).read_text(encoding='utf-8')
    matches = list(PATTERN.finditer(content))
    assert len(matches) == len(decisions), (path, len(matches), len(decisions))
    edits = []
    for match, decision in zip(matches, decisions):
        replacement = match.group(1 if decision == 'O' else 2)
        edits.append((match.group(0), replacement))
    merged = content
    for old, new in edits:
        merged = merged.replace(old, new, 1)
    # Independent original top-level tests/helpers survive collisions by name.
    if path.startswith('tests/'):
        original = subprocess.check_output(['git', 'show', 'df9850131a79191c5a860a1d231d3acd867869db:'+path], cwd=ROOT).decode('utf-8')
        old_tree = ast.parse(original)
        new_tree = ast.parse(merged)
        names = {getattr(n, 'name', '') for n in new_tree.body}
        lines = original.splitlines(keepends=True)
        missing = []
        for node in old_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name not in names:
                start = min([node.lineno]+[d.lineno for d in node.decorator_list])
                missing.append(''.join(lines[start-1:node.end_lineno]))
                names.add(node.name)
        if missing:
            addition = '\n\n'+'\n\n'.join(missing)+'\n'
            if matches[-1].end() == len(content):
                old, new = edits[-1]
                edits[-1] = (old, new + addition)
            else:
                edits.append(('', addition))
    chunks = ['*** Update File: '+str(ROOT/path)]
    for old, new in edits:
        if old:
            chunks.extend(['@@']+['-'+l for l in old.splitlines()]+['+'+l for l in new.splitlines()])
        else:
            chunks.extend(['@@', ' '+merged.splitlines()[-1]]+['+'+l for l in new.splitlines()])
    patches.extend(chunks)
print('*** Begin Patch\n'+'\n'.join(patches)+'\n*** End Patch')
