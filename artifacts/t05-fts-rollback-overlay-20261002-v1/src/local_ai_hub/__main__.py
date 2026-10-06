from __future__ import annotations

import argparse
import os
from typing import Sequence

from . import __version__
from .http_server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-ai-hub",
        description="Run the Local AI Hub HTTP service or generate agent artifacts.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("LOCAL_AI_CONFIG"),
        help="Path to config.toml. Defaults to LOCAL_AI_CONFIG or the standard user/source config.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate dynamic skill, instruction policies, and MCP configs based on config.toml, then exit.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="Target directory for generated artifacts when using --generate (default: current directory).",
    )
    parser.add_argument("--version", action="version", version=f"Local AI Hub {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.generate:
        from pathlib import Path
        from .config import load_config
        from .generator import write_all_generated
        cfg = load_config(args.config)
        out = Path(args.output_dir).resolve() if args.output_dir else Path.cwd()
        res = write_all_generated(cfg, out)
        print(f"Generated artifacts in {out}:")
        for k, v in res.items():
            print(f"  {k}: {len(v)} files")
        return 0
    serve(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
