"""Create an isolated baseline repository for scenario 089."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys


def prepare(destination):
    fixture = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("case093_helpers", fixture.parent / "case-093" / "prepare.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    candidate = Path(destination)
    if not candidate.is_absolute():
        raise ValueError("disposable root must be absolute")
    root = candidate.resolve()
    if not root.parent.is_dir() or any((p / ".git").exists() for p in (root.parent, *root.parent.parents)):
        raise ValueError("parent must exist and be outside Git repositories")
    probe = subprocess.run(["git", "-C", str(root.parent), "rev-parse", "--git-dir"],
                           env=helpers.git_env(), capture_output=True, text=True, timeout=10)
    if probe.returncode != 128 or "not a git repository" not in probe.stderr.lower():
        raise ValueError("could not establish that parent is outside Git")
    root.mkdir(parents=False, exist_ok=False)
    seed = fixture / "seed"
    for relative in ("README.md", "tasks.json", "test_listing.py", "task_export/__init__.py",
                     "task_export/__main__.py", "task_export/cli.py", "task_export/repository.py"):
        source, target = seed / relative, root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"invalid seed file: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    template = root / ".fixture-empty-template"
    template.mkdir()
    run = helpers.run
    run(root, "init", "-b", "fixture-base", "--template", str(template))
    run(root, "config", "user.name", "Fixture Operator")
    run(root, "config", "user.email", "fixture@example.invalid")
    hooks = root / ".git" / "fixture-empty-hooks"
    hooks.mkdir()
    run(root, "config", "core.hooksPath", str(hooks))
    run(root, "config", "commit.gpgsign", "false")
    run(root, "add", "README.md", "tasks.json", "test_listing.py", "task_export")
    run(root, "commit", "-m", "scenario 089 baseline")
    print(root)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: prepare.py NEW_DISPOSABLE_DIRECTORY")
    prepare(sys.argv[1])
