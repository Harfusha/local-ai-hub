"""Bounded merge syntax/duplicate inspection; no imports or bytecode writes."""
import ast
from collections import Counter
from pathlib import Path
import subprocess

paths = subprocess.check_output(['git', 'diff', '--name-only', 'b0779fc8', '--', 'src', 'tests'], text=True).splitlines()
failed = 0
for name in paths:
    path = Path(name)
    if path.suffix != '.py' or not path.is_file():
        continue
    try:
        source = path.read_text(encoding='utf-8-sig')
        compile(source, name, 'exec', dont_inherit=True)
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f'SYNTAX {name}:{exc.lineno} {exc.msg}')
        failed += 1
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef)):
            continue
        names = Counter(child.name for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        duplicates = [key for key, count in names.items() if count > 1]
        if duplicates:
            print(f'DUPLICATE {name}:{getattr(node, "lineno", 1)} {duplicates}')
print(f'Inspected {len(paths)} changed source/test paths; syntax failures={failed}')
raise SystemExit(bool(failed))
