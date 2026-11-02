"""Prepare an isolated state and explicit loopback configuration for case 076."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def prepare(target: Path, port: int, source: Path) -> Path:
    if not target.is_absolute() or target.exists():
        raise ValueError("target must be an absolute, new directory")
    if not 1024 <= port <= 65535 or port == 11435:
        raise ValueError("choose an explicit unprivileged non-production port")
    if not source.is_absolute() or not (source / "src" / "local_ai_hub" / "mcp_server.py").is_file():
        raise ValueError("source must be an absolute Local AI Hub source checkout")
    target = target.resolve()
    if any((parent / ".git").exists() for parent in (target.parent, *target.parent.parents)):
        raise ValueError("target must be outside a Git checkout")
    target.mkdir(parents=False)
    (target / "workspace").mkdir()
    (target / "state").mkdir()
    q = lambda path: json.dumps(str(path).replace("\\", "/"), ensure_ascii=True)
    config = f'''[server]
bind = "127.0.0.1"
port = {port}
state_dir = {q(target / "state")}
auto_start_ollama = false

[security]
allowed_roots = [{q(target / "workspace")}]

[hardware]
profile = "cpu"
auto_tune = false

[prewarm]
enabled = false

[preprocessing]
enabled = false
fs_watcher_enabled = false

[resilience]
watchdog_enabled = false

[code_intelligence]
enabled = false

[observability]
enabled = false
'''
    (target / "config.toml").write_text(config, encoding="utf-8")
    (target / "source.txt").write_text(str(source.resolve()), encoding="utf-8")
    fixture = Path(__file__).resolve().parent
    shutil.copyfile(fixture / "zadani.md", target / "workspace" / "zadani.md")
    (target / "workspace" / "marker.txt").write_text("CASE076_SEARCH_MARKER\n", encoding="utf-8")
    shutil.copyfile(fixture / "call_mcp.py", target / "call_mcp.py")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.target, args.port, args.source))
