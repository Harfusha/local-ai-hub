"""Create the scenario 093 export conflict in a new disposable Git repository."""
from pathlib import Path
import subprocess
import sys

from prepare import git_env, run


BASE = '''import csv
from pathlib import Path

def export(path, rows):
    with Path(path).open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "name"])
        writer.writeheader()
        writer.writerows(rows)
'''
ATOMIC = '''import csv
from pathlib import Path
from tempfile import NamedTemporaryFile

def export(path, rows):
    path = Path(path)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="ascii", newline="", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=["id", "name"])
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
'''
TESTS = '''import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from exporter import export

class ExportTests(unittest.TestCase):
    def test_utf8(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "export.csv"
            rows = [{"id": "1", "name": "Příliš žluťoučký"}]
            export(path, rows)
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), rows)

    def test_failure_preserves_existing_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "export.csv"
            path.write_bytes(b"original")
            with self.assertRaises(ValueError):
                export(path, [{"id": "1", "name": "ok", "unexpected": "x"}])
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(set(path.parent.iterdir()), {path})

if __name__ == "__main__":
    unittest.main()
'''


def prepare(destination):
    candidate = Path(destination)
    if not candidate.is_absolute():
        raise ValueError("disposable root must be an absolute path")
    root = candidate.resolve()
    if not root.parent.is_dir() or any((p / ".git").exists() for p in (root.parent, *root.parent.parents)):
        raise ValueError("parent must exist and be outside Git repositories")
    probe = subprocess.run(["git", "-C", str(root.parent), "rev-parse", "--git-dir"],
                           env=git_env(), capture_output=True, text=True, timeout=10)
    if probe.returncode != 128 or "not a git repository" not in probe.stderr.lower():
        raise ValueError("could not establish that parent is outside Git")
    root.mkdir(parents=False, exist_ok=False)
    template = root / ".fixture-empty-template"
    template.mkdir()
    run(root, "init", "-b", "fixture-base", "--template", str(template))
    run(root, "config", "user.name", "Fixture Operator")
    run(root, "config", "user.email", "fixture@example.invalid")
    hooks = root / ".git" / "fixture-empty-hooks"
    hooks.mkdir()
    run(root, "config", "core.hooksPath", str(hooks))
    run(root, "config", "commit.gpgsign", "false")
    (root / "exporter.py").write_text(BASE, encoding="utf-8", newline="\n")
    (root / "test_export.py").write_text(TESTS, encoding="utf-8", newline="\n")
    (root / "PLAN.md").write_text("Zachovej UTF-8 export i atomický zápis; konflikt vyřeš a ověř.\n", encoding="utf-8")
    run(root, "add", "exporter.py", "test_export.py", "PLAN.md")
    run(root, "commit", "-m", "fixture export base")
    run(root, "switch", "-c", "agent-a")
    (root / "exporter.py").write_text(BASE.replace('encoding="ascii"', 'encoding="utf-8"'), encoding="utf-8", newline="\n")
    run(root, "commit", "-am", "agent A UTF-8 export")
    run(root, "switch", "-c", "agent-b", "fixture-base")
    (root / "exporter.py").write_text(ATOMIC, encoding="utf-8", newline="\n")
    run(root, "commit", "-am", "agent B atomic export")
    run(root, "merge", "--no-edit", "agent-a", expect=1)
    if "UU exporter.py" not in run(root, "status", "--porcelain").stdout:
        raise RuntimeError("expected a genuine unmerged exporter.py")
    (root / "CHECKPOINT.md").write_text("Připravená simulace: agent-a UTF-8, agent-b atomický zápis. Toto není důkaz přerušení.\n", encoding="utf-8")
    print(root)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: prepare_export.py NEW_DISPOSABLE_DIRECTORY")
    prepare(sys.argv[1])
