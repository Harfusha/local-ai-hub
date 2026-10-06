"""Bounded, checkout-local merge checks and changed-path inventory; no build."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PIN = "ca2f86237b1f8ac9ce4f576a308b65b94a24a69c"

def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)

if ROOT.resolve() != Path("C:/Users/Adam/.codex/worktrees/t13-operational-mode/.local-ai-hub").resolve():
    raise SystemExit("wrong checkout")
unresolved = git("diff", "--name-only", "--diff-filter=U").stdout.splitlines()
if unresolved:
    raise SystemExit(f"unresolved: {unresolved}")
syntax_errors = []
sources = list((ROOT / "src/local_ai_hub").glob("*.py"))
sources += [ROOT / "tools/hubctl.py", ROOT / "tests/test_t13_sync_cancellation.py"]
for path in sources:
    try:
        compile(path.read_bytes(), str(path), "exec")
    except (SyntaxError, ValueError) as exc:
        syntax_errors.append(f"{path.relative_to(ROOT)}: {exc}")
protected = [
    "src/local_ai_hub/http_server.py", "src/local_ai_hub/preprocess.py",
    "src/local_ai_hub/mcp_server.py", "src/local_ai_hub/operational_mode.py",
    "src/local_ai_hub/client.py", "src/local_ai_hub/repo_tools.py",
    "tools/setup.py", "tools/uninstall.py", "docs/INSTALL_PROMPT.md",
    "docs/UPDATE_PROMPT.md",
]
different = git("diff", "--name-only", PIN, "--", *protected).stdout.splitlines()
whitespace = git("diff", "--check", PIN, "--", "src", "tests", "tools")
changed = git("diff", "--cached", "--name-status", PIN).stdout.splitlines()
inventory_name = "handoff/T13-sync-changed-files-20261006.json"
if not any(line.endswith(inventory_name) for line in changed):
    changed.append("A\t" + inventory_name)
inventory = {
    "pinned_master": PIN,
    "checkpoint": "4aa2edef7f788602da59ab7cfdf5015cd1b304cb",
    "changed_files": sorted(changed),
    "changed_count": len(changed),
    "unresolved": unresolved,
    "syntax_files_checked": len(sources),
    "syntax_errors": syntax_errors,
    "protected_files_different_from_master": different,
    "source_test_tool_whitespace_exit": whitespace.returncode,
    "source_test_tool_whitespace_summary": whitespace.stdout.splitlines()[:12],
}
(ROOT / inventory_name).write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: value for key, value in inventory.items() if key != "changed_files"}, indent=2))
if syntax_errors or different:
    raise SystemExit(1)
