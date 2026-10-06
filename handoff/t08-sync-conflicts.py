"""Read conflict hunks or emit surgical apply_patch input; never write source."""
import json
import difflib
from pathlib import Path
import re
import sys

PATTERN = re.compile(r'^<<<<<<< [^\n]*\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n', re.M | re.S)
path = Path(sys.argv[1])
source = path.read_text(encoding='utf-8')
hunks = list(PATTERN.finditer(source))
if len(sys.argv) == 2 or sys.argv[2].startswith('range='):
    selected = range(1, len(hunks) + 1) if len(sys.argv) == 2 else range(*map(int, sys.argv[2][6:].split(':')))
    for number, match in enumerate(hunks, 1):
        if number not in selected:
            continue
        line = source[:match.start()].count('\n') + 1
        print(f'--- {number} line {line} ---')
        print(''.join(difflib.unified_diff(match[1].splitlines(True), match[2].splitlines(True), fromfile='OURS', tofile='MASTER', n=2)))
else:
    decisions = json.loads(sys.argv[2])
    patch = '*** Begin Patch\n*** Update File: ' + str(path.resolve()).replace('\\', '/') + '\n'
    for number, choice in decisions.items():
        match = hunks[int(number) - 1]
        replacement = match[1] if choice == 'ours' else match[2] if choice == 'master' else match[1] + match[2] if choice == 'both' else choice['text']
        patch += '@@\n' + ''.join('-' + line + '\n' for line in match[0].splitlines())
        patch += ''.join('+' + line + '\n' for line in replacement.splitlines())
    print(json.dumps({'patch': patch + '*** End Patch\n'}))
