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
    parser.add_argument("--discover-caveman", action="append", metavar="ROOT", help="Discover instruction files under an explicit agent root; repeat for multiple roots.")
    parser.add_argument("--caveman-skill-dir", help="Directory containing the upstream caveman-compress scripts.")
    parser.add_argument("--caveman-model", help="Installed local model for caveman compression.")
    parser.add_argument("--caveman-review-model", default="qwen3.5:9b", help="Installed local model for independent semantic review (default: qwen3.5:9b).")
    parser.add_argument("--caveman-endpoint", default=None, help="Local OpenAI-compatible endpoint (default: http://127.0.0.1:11434/v1).")
    parser.add_argument("--caveman-staging-dir", help="Directory outside the source tree for backups and candidates.")
    parser.add_argument("--apply-caveman", action="store_true", help="Apply semantically reviewed candidates after verifying backup and source hashes.")
    parser.add_argument("--restore-caveman", action="append", metavar="MANIFEST", help="Restore a previously applied file from its verified Caveman manifest; repeat for multiple files.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    caveman_mode = bool(args.stage_caveman or args.discover_caveman or args.apply_caveman or args.restore_caveman)
    if args.restore_caveman:
        if args.stage_caveman or args.discover_caveman or args.apply_caveman or args.generate:
            raise SystemExit("--restore-caveman cannot be combined with compression or generation")
        from pathlib import Path
        from .caveman_instructions import restore_instruction_manifest
        failures = 0
        for manifest in args.restore_caveman:
            try:
                restore_instruction_manifest(Path(manifest))
                print(f"restored from verified backup: {manifest}")
            except Exception as exc:
                failures += 1
                print(f"restore failed: {manifest}\nreason: {type(exc).__name__}: {exc}")
        return 1 if failures else 0
    if not caveman_mode and (args.caveman_skill_dir or args.caveman_model or args.caveman_staging_dir or args.caveman_endpoint or args.caveman_review_model != "qwen3.5:9b"):
        raise SystemExit("caveman options require --stage-caveman or --discover-caveman")
    if caveman_mode:
        from pathlib import Path
        from . import caveman_instructions
        if args.generate or not args.caveman_skill_dir or not args.caveman_model or not args.caveman_staging_dir:
            raise SystemExit("Caveman compression requires skill directory, compressor model, and staging directory; cannot combine with --generate")
        roots = [Path(value) for value in (args.discover_caveman or [])]
        files = [Path(value) for value in (args.stage_caveman or [])]
        if roots:
            files.extend(caveman_instructions.discover_instruction_files(roots))
        files = sorted({path.expanduser().absolute() for path in files}, key=lambda path: str(path).casefold())
        if not files:
            raise SystemExit("No eligible instruction files found")
        endpoint = args.caveman_endpoint or "http://127.0.0.1:11434"
        backup_failures = []
        prepared = []
        for source in files:
            try:
                prepared.append(caveman_instructions.backup_instruction(source, Path(args.caveman_staging_dir)))
            except Exception as exc:
                backup_failures.append((source, exc))
        if backup_failures:
            for source, exc in backup_failures:
                print(f"source: {source}\nbackup: FAILED\nreason: {type(exc).__name__}: {exc}")
            print(f"compression not started; verified backups: {len(prepared)}/{len(files)}")
            return 1
        print(f"verified byte-for-byte backups: {len(prepared)}/{len(files)}")
        failures = 0
        for item in prepared:
            source = item.source
            try:
                result = caveman_instructions.compress_backed_up_instruction(
                    item,
                    lambda text: caveman_instructions.compress_with_caveman(
                        text, skill_dir=Path(args.caveman_skill_dir), model=args.caveman_model, endpoint=endpoint
                    ),
                    lambda original, candidate: caveman_instructions.review_instruction_semantics(
                        original, candidate, model=args.caveman_review_model, endpoint=endpoint
                    ),
                )
                if args.apply_caveman:
                    caveman_instructions.apply_instruction(result)
                before = len(result.backup.read_bytes())
                after = len(result.candidate.read_bytes())
                print(
                    f"source: {source}\nbackup: {result.backup} sha256={result.backup_sha256}"
                    f"\nmanifest: {result.backup.parent / 'manifest.json'}"
                    f"\ncandidate: {result.candidate} sha256={result.candidate_sha256}"
                    f"\nsemantic review: PASS ({args.caveman_review_model})"
                    f"\nbytes: {before} -> {after}; compression: {100 * (before - after) / max(before, 1):.1f}%"
                    f"\nelapsed: {result.duration_seconds:.3f}s; applied: {args.apply_caveman}"
                )
            except Exception as exc:
                failures += 1
                print(f"source: {source}\nstatus: NOT APPLIED\nreason: {type(exc).__name__}: {exc}")
        return 1 if failures else 0
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
