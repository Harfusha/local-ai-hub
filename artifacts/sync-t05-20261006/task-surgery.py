import ast
import pathlib

root = pathlib.Path(__file__).resolve().parents[2]
path = root/'src/local_ai_hub/agent_tasks.py'
text = path.read_text(encoding='utf-8')
lines = text.splitlines(keepends=True)
tree = ast.parse(text)
task = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TaskStore')
duplicates = [n for n in task.body if isinstance(n, ast.FunctionDef) and n.name == 'set_memory_adoption']
assert len(duplicates) == 2
snapshot = next(n for n in task.body if isinstance(n, ast.FunctionDef) and n.name == '_memory_context_snapshot')
resume = next(n for n in task.body if isinstance(n, ast.FunctionDef) and n.name == 'resume')
returned = next(n for n in resume.body if isinstance(n, ast.Return))
spans = [(duplicates[-1].lineno, snapshot.end_lineno), (returned.end_lineno+1, resume.end_lineno)]
print('*** Begin Patch\n*** Update File: '+str(path))
for start, end in spans:
    print('@@')
    for line in lines[start-1:end]:
        print('-'+line.rstrip('\n'))
print('*** End Patch')
