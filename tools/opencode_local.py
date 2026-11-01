"""Launch the experimental Hub-backed OpenCode profile on Windows."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.opencode_launcher import LaunchError, launch_opencode
from tools.opencode_install import VERSION, WINDOWS_X64_EXECUTABLE_SHA256, _file_digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experimental Hub-backed OpenCode launcher")
    parser.add_argument("--model", required=True, help="Explicit installed Ollama model")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--config", help="Hub configuration path")
    parser.add_argument("--executable", type=Path, help="Verified OpenCode 2.2.5 executable")
    parser.add_argument("--timeout-seconds", type=float, default=28_800)
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("Experimental launcher currently supports Windows only.", file=sys.stderr)
        return 2
    executable = args.executable or Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OpenCode-LocalAIHub" / VERSION / "opencode.exe"
    try:
        if not executable.is_file() or _file_digest(executable) != WINDOWS_X64_EXECUTABLE_SHA256:
            raise LaunchError("OpenCode executable is missing or its checksum does not match the pinned release")
        client = HubClient(config_path=args.config, auto_start=False)
        print("Experimental local profile: project OpenCode config is disabled; shell network access is not sandboxed.", file=sys.stderr)
        return launch_opencode(client, install_dir=ROOT, hub_python=Path(sys.executable), executable=executable,
                               project=args.project, model=args.model, timeout_seconds=args.timeout_seconds)
    except (LaunchError, ValueError, OSError) as exc:
        print(f"OpenCode launch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
