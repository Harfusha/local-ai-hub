"""Launch the experimental Hub-backed OpenCode profile on Windows."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SANDBOX_BLOCKER = (
    "Managed OpenCode launch is disabled: production filesystem and network sandbox, "
    "GPU admission, and owned process cleanup are not implemented and verified."
)


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
    print(_SANDBOX_BLOCKER, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
