"""Fail CI when the retired dashboard is reintroduced or old modules remain imported."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RETIRED = {
    "local_ai_hub.dashboard", "local_ai_hub.dashboard_html",
    "local_ai_hub.dashboard_status_poller", "local_ai_hub.http_routes_ui",
    "tools.check_dashboard", "check_dashboard",
}
FORBIDDEN_FILES = {
    "package.json", "package-lock.json", "tsconfig.json", "tools/build_dashboard.mjs",
    "tools/check_dashboard.py", "src/local_ai_hub/dashboard.py",
    "src/local_ai_hub/dashboard_html.py", "src/local_ai_hub/dashboard_status_poller.py",
    "src/local_ai_hub/http_routes_ui.py",
}


def violations(root: Path = ROOT) -> list[str]:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    paths = tracked.decode("utf-8", errors="surrogateescape").split("\0")
    problems = []
    for name in paths:
        if name in FORBIDDEN_FILES or name.startswith("src/local_ai_hub/ui_static/"):
            problems.append(f"Retired frontend source: {name}")
        if not name.endswith(".py") or not name.startswith(("src/", "tools/", "tests/")):
            continue
        path = root / name
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        try:
            module = ast.parse(source, filename=name)
        except SyntaxError as exc:
            problems.append(f"Syntax error in {name}: {exc}")
            continue
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in RETIRED:
                        problems.append(f"{name}:{node.lineno}: retired import {alias.name}")
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if node.level and name.startswith("src/local_ai_hub/"):
                    module_name = "local_ai_hub." + module_name
                if module_name in RETIRED:
                    problems.append(f"{name}:{node.lineno}: retired import {module_name}")
                if module_name in {"local_ai_hub", "local_ai_hub."}:
                    for alias in node.names:
                        if "local_ai_hub." + alias.name in RETIRED:
                            problems.append(f"{name}:{node.lineno}: retired import {alias.name}")
            if isinstance(node, ast.Name) and node.id in {"DASHBOARD_HTML", "DASHBOARD_HTML_TEMPLATE", "HTTPRoutesUIMixin"}:
                problems.append(f"{name}:{node.lineno}: retired browser symbol {node.id}")
    workflow = root / ".github/workflows/ci.yml"
    if re.search(r"npm run (?:typecheck|build)|python tools/check_dashboard\.py", workflow.read_text(encoding="utf-8")):
        problems.append("CI still invokes retired browser build/check")
    return sorted(set(problems))


def main() -> int:
    errors = violations()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Desktop cutover source and import guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
