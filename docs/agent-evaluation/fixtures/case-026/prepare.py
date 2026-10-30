"""Create a disposable Git root for evaluation case 026."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=20, capture_output=True)


def prepare(target: str) -> Path:
    path = Path(target)
    if not path.is_absolute() or path.exists():
        raise ValueError("target must be an absolute, new directory")
    root = path.resolve()
    if any((ancestor / ".git").exists() for ancestor in (root.parent, *root.parent.parents)):
        raise ValueError("target parent must not be inside a Git repository")
    root.mkdir(parents=False)
    env = os.environ.copy()
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
    with tempfile.TemporaryDirectory(prefix="lah-case-026-template-") as template:
        run("git", "init", "-b", "fixture-base", "--template", template, cwd=root, env=env)
    run("git", "config", "user.name", "Fixture Operator", cwd=root, env=env)
    run("git", "config", "user.email", "fixture@example.invalid", cwd=root, env=env)
    seed = Path(__file__).resolve().parent / "seed" / "task_overview.html"
    shutil.copyfile(seed, root / seed.name)
    run("git", "add", "task_overview.html", cwd=root, env=env)
    run("git", "commit", "-m", "seed case 026", cwd=root, env=env)
    return root


if __name__ == "__main__":
    print(prepare(sys.argv[1]))
