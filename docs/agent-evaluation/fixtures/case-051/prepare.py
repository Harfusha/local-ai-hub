"""Prepare an isolated same-session MCP context-delta fixture."""
from __future__ import annotations

import argparse
import importlib.util
import shutil
from pathlib import Path


def prepare(target: Path, port: int, source: Path) -> Path:
    if port == 11434:
        raise ValueError("choose a non-production port")
    fixture = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("case076_prepare", fixture.parent / "case-076" / "prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = module.prepare(target, port, source)
    (root / "workspace" / "marker.txt").write_text("CASE051_CONTEXT_MARKER\n", encoding="utf-8")
    shutil.copyfile(fixture / "session_probe.py", root / "session_probe.py")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.target, args.port, args.source))
