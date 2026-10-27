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
    parser.add_argument("--stage-caveman", action="append", metavar="FILE", help="Stage compression of an instruction file; repeat for multiple files.")
    parser.add_argument("--caveman-skill-dir", help="Directory containing the upstream caveman-compress scripts.")
    parser.add_argument("--caveman-model", help="Installed local model for caveman compression.")
    parser.add_argument("--caveman-endpoint", default=None, help="Local OpenAI-compatible endpoint (default: http://127.0.0.1:11434/v1).")
    parser.add_argument("--caveman-staging-dir", help="Directory outside the source tree for backups and candidates.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.stage_caveman and (args.caveman_skill_dir or args.caveman_model or args.caveman_staging_dir or args.caveman_endpoint):
        raise SystemExit("caveman options require --stage-caveman")
    if args.stage_caveman:
        from pathlib import Path
        from . import caveman_instructions
        if args.generate or not args.caveman_skill_dir or not args.caveman_model or not args.caveman_staging_dir:
            raise SystemExit("--stage-caveman requires skill directory, model and staging directory; cannot combine with --generate")
        for name in args.stage_caveman:
            result = caveman_instructions.stage_instruction(
                Path(name), Path(args.caveman_staging_dir),
                lambda text: caveman_instructions.compress_with_caveman(
                    text, skill_dir=Path(args.caveman_skill_dir), model=args.caveman_model,
                    endpoint=args.caveman_endpoint or "http://127.0.0.1:11434/v1"
                ),
            )
            print(f"source: {result.source}\nbackup: {result.backup}\ncandidate: {result.candidate}\nsemantic preservation: NOT VERIFIED; review before use")
        return 0
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
