import ast
import difflib
import json
from pathlib import Path

base = Path(__file__).resolve().parent
capture = json.loads((base / 'refresh2' / 'capture.json').read_text(encoding='utf-8-sig'))
results = []
for entry in capture['files']:
    relative = entry['path']
    original = ast.parse((base / 'preimage' / relative).read_bytes())
    desired = ast.parse((base / 'owned' / relative).read_bytes())
    current = ast.parse((base / 'refresh2' / 'preimage' / relative).read_bytes())
    dump = lambda tree: ast.dump(tree, include_attributes=False)
    if dump(current) == dump(original):
        status = 'OWNED_HUNK_PENDING'
    elif dump(current) == dump(desired):
        status = 'ALREADY_PRESENT_IN_ROOT; do not duplicate hunk'
    elif relative == 'src/local_ai_hub/deterministic.py':
        class DropUnused(ast.NodeTransformer):
            def visit_Assign(self, node):
                return None if node.lineno == 4150 else node
        assert dump(DropUnused().visit(original)) == dump(current), relative
        status = 'ROOT_REMOVED_RHS; restore original lower() evaluation bound to _'
    elif relative == 'src/local_ai_hub/scheduler.py':
        loop = next(node for node in ast.walk(current) if isinstance(node, ast.For) and node.lineno == 347)
        assert loop.target.id == 'metric_name'
        partial = any(isinstance(node, ast.Name) and node.id == 'field' for node in ast.walk(loop))
        for node in ast.walk(loop):
            if isinstance(node, ast.Name) and node.id in {'field', 'metric_name'}:
                node.id = 'metric_field'
        assert dump(current) == dump(desired), relative
        status = 'ROOT_LOOP_RENAME_PARTIAL; complete report body uses with metric_name' if partial else 'ALREADY_PRESENT_IN_ROOT; equivalent loop binding metric_name'
    else:
        diff = list(difflib.unified_diff((base / 'preimage' / relative).read_text(encoding='utf-8').splitlines(), (base / 'refresh2' / 'preimage' / relative).read_text(encoding='utf-8').splitlines(), n=3))
        print('\n'.join(diff[:50]))
        status = 'ROOT_VARIANT_REQUIRES_SOURCE_REVIEW'
    row = {'path': relative, 'status': status, 'root_pre_sha256': entry['pre_sha256']}
    results.append(row)
    print(json.dumps(row))
(base / 'refresh2' / 'rebase-status.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
