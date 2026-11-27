"""Launch the experimental Hub-backed OpenCode profile on Windows."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SANDBOX_BLOCKER = (
    "Managed OpenCode launch is disabled: production filesystem and network sandbox, "
    "GPU admission, and owned process cleanup are not implemented and verified."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experimental Hub-backed OpenCode launcher")
    parser.add_argument("--model", help="Explicit installed Ollama model")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print read-only integration evidence without launching OpenCode",
    )
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--config", help="Hub configuration path")
    parser.add_argument("--executable", type=Path, help="Verified OpenCode 2.2.5 executable")
    parser.add_argument("--timeout-seconds", type=float, default=28_800)
    args = parser.parse_args(argv)
    if args.diagnostics:
        manifest_path = Path(__file__).resolve().parents[1] / "generated" / "opencode-mcp.json"
        report = {
            "generated_manifest": {
                "path": "generated/opencode-mcp.json",
                "status": "present" if manifest_path.is_file() else "not_present",
            },
            "configured": "NOT_VERIFIED",
            "installed": "NOT_VERIFIED",
            "trusted": "NOT_VERIFIED",
            "connected": "NOT_VERIFIED",
            "user_visible_tools": "NOT_VERIFIED",
            "launcher": {"status": "disabled", "reason": _SANDBOX_BLOCKER},
        }
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.model is None:
        parser.error("--model is required unless --diagnostics is used")
    if os.name != "nt":
        print("Experimental launcher currently supports Windows only.", file=sys.stderr)
        return 2
    print(_SANDBOX_BLOCKER, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
