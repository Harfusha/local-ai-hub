"""token_economy.py — Core token efficiency tools and CLI entry points.

Provides:
- tokcount: Fast, exact token and context counter (o200k/Astra, cl100k) with heuristic fallbacks.
- trim_run: Terminal command wrapper that strips ANSI sequences and truncates oversized outputs.
- repo_map: High-density AST skeleton extractor for multi-language repositories.
"""
from __future__ import annotations

from .json_utils import dumps as json_dumps

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from functools import lru_cache
from typing import Any, Iterable

from local_ai_hub.process_utils import hidden_run_kwargs

@lru_cache(maxsize=1)
def _encodings():
    # Help, trim-run and repo-map must not download tokenizers during import.
    try:
        import tiktoken
        return tiktoken.get_encoding("o200k_base"), tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None, None

ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
DEFAULT_EXTS = {
    ".py", ".cs", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
    ".php", ".ctp", ".vue", ".svelte", ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".go", ".rs", ".java", ".cpp", ".c", ".h",
}
IGNORE_DIRS = {".git", "node_modules", "vendor", "Library", "Temp", "obj", "bin", "__pycache__", ".venv", "dist", "build", ".idea", ".vscode", "tool-envs"}


def strip_ansi(text: str) -> str:
    """Remove ANSI color and control codes from output text."""
    return ANSI_REGEX.sub("", text)


def count_tokens(text: str) -> tuple[int, int, int, int, int]:
    """Count (lines, words, chars, o200k_tokens, cl100k_tokens) for a string."""
    chars = len(text)
    words = len(text.split())
    lines = text.count("\n") + (1 if text else 0)

    enc_o200k, enc_cl100k = _encodings()
    if enc_o200k is not None and enc_cl100k is not None:
        try:
            tok_o200k = len(enc_o200k.encode(text, disallowed_special=()))
            tok_cl100k = len(enc_cl100k.encode(text, disallowed_special=()))
            return lines, words, chars, tok_o200k, tok_cl100k
        except Exception:
            pass

    # High-accuracy fallback heuristic: ~3.8 chars per token for o200k, ~3.6 for cl100k
    tok_o200k = int(chars / 3.8) if chars else 0
    tok_cl100k = int(chars / 3.6) if chars else 0
    return lines, words, chars, tok_o200k, tok_cl100k


def tokcount_main(argv: list[str] | None = None) -> int:
    """CLI entry point for tokcount."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="tokcount", description="Fast token and context counter for AI coding agents.")
    parser.add_argument("paths", nargs="*", help="File or directory paths. If empty, reads stdin.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Print only token count number (o200k/Astra).")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    args = parser.parse_args(argv)

    if not args.paths:
        if sys.stdin.isatty():
            parser.print_help()
            return 0
        content = sys.stdin.read()
        lines, words, chars, o200k, cl100k = count_tokens(content)
        if args.json:
            import json
            print(json_dumps({"source": "stdin", "lines": lines, "words": words, "chars": chars, "tokens_o200k": o200k, "tokens_cl100k": cl100k}, indent=2))
        elif args.quiet:
            print(o200k)
        else:
            print(f"Stdin | Lines: {lines:,} | Words: {words:,} | Chars: {chars:,} | Tokens (o200k/Astra): {o200k:,} | Tokens (cl100k): {cl100k:,}")
        return 0

    total_lines = total_words = total_chars = total_o200k = total_cl100k = 0
    file_count = 0
    file_stats: list[dict[str, Any]] = []

    for path_str in args.paths:
        p = Path(path_str)
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                lines, words, chars, o200k, cl100k = count_tokens(content)
                total_lines += lines
                total_words += words
                total_chars += chars
                total_o200k += o200k
                total_cl100k += cl100k
                file_count += 1
                file_stats.append({"path": str(p), "lines": lines, "words": words, "chars": chars, "tokens_o200k": o200k, "tokens_cl100k": cl100k})
                if not args.quiet and not args.json and len(args.paths) > 1:
                    print(f"{p} | Lines: {lines:,} | Chars: {chars:,} | Tokens: {o200k:,}")
            except Exception as exc:
                if not args.quiet:
                    print(f"Error reading {p}: {exc}", file=sys.stderr)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                rel_parts = Path(root).relative_to(p).parts
                if any(part in IGNORE_DIRS for part in rel_parts):
                    continue
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for f in sorted(files):
                    fp = Path(root) / f
                    try:
                        content = fp.read_text(encoding="utf-8", errors="replace")
                        lines, words, chars, o200k, cl100k = count_tokens(content)
                        total_lines += lines
                        total_words += words
                        total_chars += chars
                        total_o200k += o200k
                        total_cl100k += cl100k
                        file_count += 1
                        file_stats.append({"path": str(fp), "lines": lines, "words": words, "chars": chars, "tokens_o200k": o200k, "tokens_cl100k": cl100k})
                    except Exception:
                        pass

    if args.json:
        import json
        print(json_dumps({
            "total_files": file_count,
            "lines": total_lines,
            "words": total_words,
            "chars": total_chars,
            "tokens_o200k": total_o200k,
            "tokens_cl100k": total_cl100k,
            "files": file_stats,
        }, indent=2))
    elif args.quiet:
        print(total_o200k)
    else:
        print(f"Total ({file_count:,} files) | Lines: {total_lines:,} | Words: {total_words:,} | Chars: {total_chars:,} | Tokens (o200k/Astra): {total_o200k:,} | Tokens (cl100k): {total_cl100k:,}")
    return 0


def filter_and_print_trimmed(lines: Iterable[str], max_lines: int) -> None:
    """Print trimmed lines preserving head and tail."""
    clean_lines = [strip_ansi(l.rstrip("\r\n")) for l in lines]
    total = len(clean_lines)
    if total <= max_lines:
        for l in clean_lines:
            print(l)
    else:
        half = max_lines // 2
        for l in clean_lines[:half]:
            print(l)
        skipped = total - max_lines
        print(f"\n[... {skipped:,} lines truncated by trim-run to save tokens (total: {total:,} lines) ...]\n")
        for l in clean_lines[-half:]:
            print(l)


_TRIM_RUN_ALLOWED_COMMANDS = {"rg", "fd", "grep-ast"}
_TRIM_RUN_BUNDLED_COMMANDS = {"tokcount": "tokcount", "repo-map": "repo_map"}


def trim_run_main(argv: list[str] | None = None) -> int:
    """CLI entry point for trim-run."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:] if argv is None else list(argv)
    max_lines = 50

    if args and args[0] in ("-n", "--lines") and len(args) > 1:
        try:
            max_lines = int(args[1])
            args = args[2:]
        except ValueError:
            pass

    # If no command arguments, read from stdin (pipe mode)
    if not args:
        if sys.stdin.isatty():
            print("Usage: trim-run [-n MAX_LINES] <command> [args...]")
            print("   or: <command> | trim-run [-n MAX_LINES]")
            return 0
        lines = sys.stdin.readlines()
        filter_and_print_trimmed(lines, max_lines)
        return 0

    # Subprocess execution mode is deliberately allowlisted. trim-run is not a
    # shell wrapper: use local_ai_command for arbitrary validation commands.
    command_name = os.path.basename(args[0]).lower()
    if os.path.basename(args[0]) != args[0]:
        print("trim-run: command is not in the safe read/validation allowlist", file=sys.stderr)
        return 2
    if command_name in _TRIM_RUN_BUNDLED_COMMANDS:
        command_args = [sys.executable, __file__, _TRIM_RUN_BUNDLED_COMMANDS[command_name], *args[1:]]
    elif command_name in _TRIM_RUN_ALLOWED_COMMANDS:
        lowered_args = [arg.lower() for arg in args[1:]]
        if command_name == "rg" and any(arg == "--pre" or arg.startswith("--pre=") for arg in lowered_args):
            print("trim-run: rg preprocessors are not allowed", file=sys.stderr)
            return 2
        if command_name == "fd" and any(
            arg in {"-x", "-X", "--exec", "--exec-batch"}
            or arg.startswith(("--exec=", "--exec-batch="))
            for arg in lowered_args
        ):
            print("trim-run: fd command execution options are not allowed", file=sys.stderr)
            return 2
        command_args = args
    else:
        print("trim-run: command is not in the safe read/validation allowlist", file=sys.stderr)
        return 2

    safe_env = os.environ.copy()
    # Search CLIs accept options from environment config files as well as argv;
    # strip those channels so an inherited --pre/--exec cannot escape the checks.
    safe_env.pop("RIPGREP_CONFIG_PATH", None)
    safe_env.pop("FD_OPTIONS", None)

    # Always pass argv directly. shell=True would turn this token-saving helper
    # into an arbitrary command launcher on Windows and POSIX.
    try:
        proc = subprocess.Popen(
            command_args,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=safe_env,
            **hidden_run_kwargs(),
        )
        lines: list[str] = []
        if proc.stdout:
            for line in proc.stdout:
                lines.append(line)
        ret = proc.wait()
        filter_and_print_trimmed(lines, max_lines)
        return ret
    except Exception as exc:
        print(f"trim-run failed to execute command: {exc}", file=sys.stderr)
        return 1


_OUTLINE_PATTERN = re.compile(
    r"^\s*(?:(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|struct|enum|record|def|trait)\b"
    r"|(?:(?:final|abstract|readonly)\s+)+(?:class|interface|trait|enum)\b"
    r"|(?:public|private|protected)\s+(?:static\s+)?(?:async\s+)?(?:function|\w+)\s+\w+\s*\("
    r"|(?:(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>)"
    r"|class\s+\w+|def\s+\w+|function\s+\w+"
    r"|@(?:keyframes|media)\b"
    r"|(?:\$builder|\$routes)->connect\b"
    r"|Schema::create\b"
    r"|<form\b)"
)


def generate_repo_map(root_dir: str | Path, max_lines: int = 250, exts: set[str] | None = None) -> tuple[list[str], int]:
    """Generate high-density AST skeleton of a codebase."""
    root_p = Path(root_dir).expanduser().resolve()
    target_exts = exts or DEFAULT_EXTS

    out_lines: list[str] = []
    total_files = 0
    has_grep_ast = bool(shutil.which("grep-ast"))
    grep_ast_pattern = r"(class |def |interface |function |struct |enum |record |trait |type |public |private |protected )"

    walk_items: list[tuple[Path, list[str]]] = []
    if root_p.is_file():
        walk_items = [(root_p.parent, [root_p.name])]
        base_dir = root_p.parent
    else:
        for dp, dn, fn in os.walk(root_p):
            rel_parts = Path(dp).relative_to(root_p).parts
            if any(part in IGNORE_DIRS for part in rel_parts):
                continue
            dn[:] = [d for d in dn if d not in IGNORE_DIRS]
            walk_items.append((Path(dp), sorted(fn)))
        base_dir = root_p

    for dirpath, filenames in walk_items:
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in target_exts:
                total_files += 1
                full_path = dirpath / f
                try:
                    rel_path = full_path.relative_to(base_dir).as_posix()
                except ValueError:
                    rel_path = full_path.as_posix()

                extracted_lines: list[str] = []
                if has_grep_ast:
                    try:
                        res = subprocess.run(
                            ["grep-ast", "-i", grep_ast_pattern, str(full_path)],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=5,
                            **hidden_run_kwargs(),
                        )
                        if res.stdout and res.stdout.strip():
                            candidates = [l for l in res.stdout.splitlines() if l.strip()]
                            # Some grep-ast releases print only a file heading
                            # for Python files they cannot parse. Treat that as
                            # an empty result so the built-in declaration scan
                            # remains a reliable fallback.
                            for candidate_line in candidates:
                                source_line = re.sub(r"^.*?:\d+:\s*", "", candidate_line)
                                if _OUTLINE_PATTERN.search(source_line):
                                    extracted_lines.append(source_line.rstrip())
                    except Exception:
                        pass

                if not extracted_lines:
                    # Built-in regex AST fallback scanner
                    try:
                        text = full_path.read_text(encoding="utf-8", errors="replace")
                        for line in text.splitlines():
                            if _OUTLINE_PATTERN.search(line):
                                extracted_lines.append(line.rstrip())
                    except Exception:
                        pass

                if extracted_lines:
                    out_lines.append(f"\n--- {rel_path} ---")
                    for el in extracted_lines:
                        out_lines.append(el)
                        if len(out_lines) >= max_lines:
                            out_lines.append(f"\n[... repo-map reached {max_lines} lines limit. Use --max-lines <N> or target a subfolder ...]")
                            return out_lines, total_files

    return out_lines, total_files


def repo_map_main(argv: list[str] | None = None) -> int:
    """CLI entry point for repo-map."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="repo-map", description="Generate high-density AST skeleton of a codebase.")
    parser.add_argument("path", nargs="?", default=".", help="Directory to map (default: current directory)")
    parser.add_argument("-n", "--max-lines", type=int, default=250, help="Maximum lines to output (default: 250)")
    parser.add_argument("-e", "--extensions", help="Comma-separated file extensions (e.g. .py,.cs,.ts)")
    args = parser.parse_args(argv)

    exts = set(e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}" for e in args.extensions.split(",")) if args.extensions else None
    lines, total_files = generate_repo_map(args.path, max_lines=args.max_lines, exts=exts)

    if not lines:
        print(f"No matching code files found in {args.path}")
        return 0

    print(f"# Repository AST Map ({total_files:,} files scanned)")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("tokcount", "trim_run", "trim-run", "repo_map", "repo-map"):
        subcmd = sys.argv[1].replace("-", "_")
        subargs = sys.argv[2:]
        if subcmd == "tokcount":
            raise SystemExit(tokcount_main(subargs))
        elif subcmd == "trim_run":
            raise SystemExit(trim_run_main(subargs))
        elif subcmd == "repo_map":
            raise SystemExit(repo_map_main(subargs))
    raise SystemExit(tokcount_main(sys.argv[1:]))
