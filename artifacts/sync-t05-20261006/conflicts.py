import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATTERN = re.compile(r'^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n', re.M | re.S)
paths = subprocess.check_output(['git', 'diff', '--name-only', '--diff-filter=U'], cwd=ROOT, text=True).splitlines()
for path in paths:
    if len(sys.argv) > 1 and sys.argv[1] not in path:
        continue
    content = (ROOT / path).read_text(encoding='utf-8')
    for i, match in enumerate(PATTERN.finditer(content), 1):
        a, b = match.groups()
        print(json.dumps({'path': path, 'hunk': i, 'line': content[:match.start()].count('\n') + 1,
                          'ours_lines': len(a.splitlines()), 'master_lines': len(b.splitlines()),
                          'ours_symbols': re.findall(r'^\s*(?:async )?def (\w+)', a, re.M),
                          'master_symbols': re.findall(r'^\s*(?:async )?def (\w+)', b, re.M),
                          'ours': a if len(a.splitlines()) <= 25 else a[:550],
                          'master': b if len(b.splitlines()) <= 25 else b[:550]}))
