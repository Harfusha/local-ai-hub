from __future__ import annotations

import argparse
import os
from typing import Sequence

from . import __version__
from .http_server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-ai-hub",
        description="Run the Local AI Hub HTTP service.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("LOCAL_AI_CONFIG"),
        help="Path to config.toml. Defaults to LOCAL_AI_CONFIG or the standard user/source config.",
    )
    parser.add_argument("--version", action="version", version=f"Local AI Hub {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    serve(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
