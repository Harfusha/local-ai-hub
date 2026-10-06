"""Bounded conflict inspection and patch generation for the 069d handoff."""
import ast
import difflib
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[2]).resolve()
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
hunks = []
i = 0
while i < len(lines):
    if lines[i].startswith("<<<<<<< "):
        start = i
        middle = next(j for j in range(i + 1, len(lines)) if lines[j].startswith("======="))
        end = next(j for j in range(middle + 1, len(lines)) if lines[j].startswith(">>>>>>> "))
        hunks.append((start, middle, end))
        i = end
    i += 1
if sys.argv[1] == "inspect":
    wanted = set(map(int, sys.argv[3].split(","))) if len(sys.argv) > 3 else None
    for number, (start, middle, end) in enumerate(hunks, 1):
        if wanted and number not in wanted:
            continue
        print(f"HUNK {number} line {start + 1} ({middle-start-1}/{end-middle-1})")
        print("".join(lines[max(0, start-2):start]).rstrip())
        if max(middle-start, end-middle) > 65 and (middle == start + 1 or end == middle + 1):
            side = lines[start+1:middle] or lines[middle+1:end]
            print("ONE-SIDED ADDITION/REMOVAL; declarations/assertions:")
            selected = [line.rstrip() for line in side if line.lstrip().startswith(("def ", "class ", "assert ", "with pytest.raises"))]
            print("\n".join(selected[:65]))
        elif max(middle-start, end-middle) > 180:
            for name, side in (("HISTORICAL", lines[start+1:middle]), ("MASTER", lines[middle+1:end])):
                print(name)
                print("".join(side[:12]).rstrip())
                selected = [line.rstrip() for line in side if line.lstrip().startswith(("def ", "class ", "assert ", "with pytest.raises"))]
                print("\n".join(selected[:45]))
                print("".join(side[-8:]).rstrip())
        elif max(middle-start, end-middle) > 65:
            print("".join(difflib.unified_diff(lines[start+1:middle], lines[middle+1:end], fromfile="historical", tofile="master", n=2)).rstrip())
        else:
            print("".join(lines[start:end+1]).rstrip())
        print("".join(lines[end+1:end+3]).rstrip())
elif sys.argv[1] == "dedupe":
    tree = ast.parse("".join(lines))
    seen = {}
    removals = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identity = (node.name, ast.dump(node))
            if identity in seen:
                removals.append((node.lineno - 1, node.end_lineno))
            seen[identity] = node
    output = list(lines)
    for start, end in reversed(removals):
        del output[start:end]
elif sys.argv[1] == "patch":
    choices = sys.argv[3].split(",")
    if len(choices) != len(hunks):
        raise SystemExit(f"Expected {len(hunks)} choices, got {len(choices)}")
    output = list(lines)
    for (start, middle, end), choice in reversed(list(zip(hunks, choices))):
        if choice == "o":
            replacement = lines[start+1:middle]
        elif choice == "t":
            replacement = lines[middle+1:end]
        elif choice == "b":
            replacement = lines[start+1:middle] + lines[middle+1:end]
        else:
            replacement = [value + "\n" for value in json.loads(choice)]
        output[start:end+1] = replacement
if sys.argv[1] in {"patch", "dedupe"}:
    diff = list(difflib.unified_diff(lines, output, n=3))
    print("*** Begin Patch")
    print(f"*** Update File: {path.as_posix()}")
    for line in diff[2:]:
        if line.startswith("@@"):
            print("@@")
        else:
            print(line, end="" if line.endswith("\n") else "\n")
    print("*** End Patch")
