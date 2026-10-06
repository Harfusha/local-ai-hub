"""Inspect duplicated merge definitions and emit reviewed block deletions."""
import ast
from collections import defaultdict
import difflib
import json
from pathlib import Path
import subprocess
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding='utf-8')
lines = source.splitlines(True)
tree = ast.parse(source)
groups = {}
for parent in ast.walk(tree):
    if not isinstance(parent, (ast.Module, ast.ClassDef)):
        continue
    members = defaultdict(list)
    for node in parent.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            members[node.name].append(node)
    for name, nodes in members.items():
        if len(nodes) > 1:
            groups[name] = nodes
if len(sys.argv) == 2:
    for name, nodes in groups.items():
        blocks = [''.join(lines[min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1:node.end_lineno]) for node in nodes]
        print(f'{name} lines {[n.lineno for n in nodes]} identical={blocks[0] == blocks[-1]}')
        diff = list(difflib.unified_diff(blocks[0].splitlines(True), blocks[-1].splitlines(True), n=1))
        print(''.join(diff[:65]))
        if len(diff) > 65:
            print(f'... {len(diff)} diff lines; further slices needed')
else:
    decisions = json.loads(sys.argv[2])
    patch = '*** Begin Patch\n*** Update File: ' + str(path.resolve()).replace('\\', '/') + '\n'
    deletions = []
    for name, keep in decisions.items():
        for index, node in enumerate(groups[name], 1):
            if index == keep:
                continue
            first = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            block = lines[first:node.end_lineno]
            deletions.append((first, block))
    for first, block in sorted(deletions):
        patch += '@@\n' + ''.join('-' + line.rstrip('\n') + '\n' for line in block)
    print(json.dumps({'patch': patch + '*** End Patch\n'}))
