"""Prepare a separate, token-protected case 098 Hub state and workspace."""
from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import shutil
from pathlib import Path


def prepare(target: Path, port: int, source: Path) -> Path:
    if port == 11434:
        raise ValueError("choose a non-production Hub port")
    fixture = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("case076_prepare", fixture.parent / "case-076" / "prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = module.prepare(target, port, source)
    config_path = root / "config.toml"
    config = config_path.read_text(encoding="utf-8")
    token = secrets.token_urlsafe(32)
    config = config.replace("[security]\n", "[security]\napi_token = " + json.dumps(token) + "\n", 1)
    config_path.write_text(config, encoding="utf-8")
    shutil.copyfile(fixture / "call_mcp.py", root / "call_mcp.py")
    shutil.copyfile(fixture / "zadani.md", root / "workspace" / "zadani.md")
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.target, args.port, args.source))
