"""token_economy.py — Core token efficiency tools and CLI entry points.

Provides:
- tokcount: Fast, exact token and context counter (o200k/Astra, cl100k) with heuristic fallbacks.
- trim_run: Terminal command wrapper that strips ANSI sequences and truncates oversized outputs.
- repo_map: High-density AST skeleton extractor for multi-language repositories.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from local_ai_hub.process_utils import hidden_run_kwargs

try:
    import tiktoken
    _ENC_O200K = tiktoken.get_encoding("o200k_base")
    _ENC_CL100K = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC_O200K = None
    _ENC_CL100K = None

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

    if _ENC_O200K is not None and _ENC_CL100K is not None:
        try:
            tok_o200k = len(_ENC_O200K.encode(text, disallowed_special=()))
            tok_cl100k = len(_ENC_CL100K.encode(text, disallowed_special=()))
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
            print(json.dumps({"source": "stdin", "lines": lines, "words": words, "chars": chars, "tokens_o200k": o200k, "tokens_cl100k": cl100k}, indent=2))
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
        print(json.dumps({
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


TRIM_RUN_READ_COMMANDS = {
    "tokcount", "repo-map", "grep-ast", "files-to-prompt", "ast-grep", "sg",
    "repomix", "rg", "ripgrep", "fd", "fdfind", "grep", "findstr", "jq",
    "yq", "cat", "type", "head", "tail", "wc", "sort", "uniq", "git",
}
TRIM_RUN_TEST_COMMANDS = {
    "pytest", "py.test", "ruff", "mypy", "pyflakes", "flake8", "pylint",
    "bandit", "shellcheck", "yamllint", "phpunit", "phpstan", "dotnet",
    "cargo", "go", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat",
    "npm", "pnpm", "yarn", "bun",
}
TRIM_RUN_BLOCKED_FLAGS = {
    "-o", "--output", "--output-file", "--outfile", "--write", "--rewrite",
    "--update-all", "--interactive", "--in-place", "--delete", "--remove",
    "--fix", "--copy", "--share", "--remote", "--remote-branch", "--remote-url",
}


def _trim_run_safe_command(command: list[str]) -> bool:
    """Limit trim-run subprocesses to read tools and safe validation commands."""
    if not command:
        return False
    executable = os.path.basename(command[0].replace("\\", "/")).lower()
    for suffix in (".cmd", ".bat", ".exe"):
        if executable.endswith(suffix):
            executable = executable[: -len(suffix)]
            break

    if executable in {"python", "python3", "py"}:
        # Never turn the output filter into an arbitrary Python execution path.
        return len(command) >= 3 and command[1:3] == ["-m", "pytest"]

    if executable not in TRIM_RUN_READ_COMMANDS | TRIM_RUN_TEST_COMMANDS:
        return False
    if any(arg in {"|", "||", "&&", ";", ">", ">>", "<", "&"} for arg in command[1:]):
        return False

    normalized = [arg.split("=", 1)[0].lower() for arg in command[1:]]
    if any(arg in TRIM_RUN_BLOCKED_FLAGS for arg in normalized):
        return False
    if executable == "repomix" and "--stdout" not in command[1:]:
        return False
    if executable in {"ast-grep", "sg"}:
        if any(arg in {"-u", "-uall"} for arg in normalized):
            return False
        positional = [arg.lower() for arg in command[1:] if not arg.startswith("-")]
        if positional and positional[0] in {"new", "test", "lsp"}:
            return False
    if executable == "repomix" and any(
        arg == "--remote" or arg == "--remote-branch" or arg == "--remote-url" or arg.startswith("--remote=")
        for arg in command[1:]
    ):
        return False
    if executable == "git":
        if any(arg in {"-c", "--config-env", "--exec-path"} for arg in normalized):
            return False
        verbs = [arg.lower() for arg in command[1:] if not arg.startswith("-")]
        if not verbs or verbs[0] not in {"status", "diff", "log", "show", "rev-parse", "branch"}:
            return False
        if verbs[0] == "branch" and any(arg in {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "--set-upstream-to"} for arg in normalized):
            return False
    if executable == "dotnet":
        verbs = [arg.lower() for arg in command[1:] if not arg.startswith("-")]
        if not verbs or verbs[0] != "test":
            return False
    if executable == "cargo":
        verbs = [arg.lower() for arg in command[1:] if not arg.startswith("-")]
        if not verbs or verbs[0] not in {"test", "check", "clippy"}:
            return False
    if executable in {"npm", "pnpm", "yarn", "bun"}:
        verbs = [arg.lower() for arg in command[1:] if not arg.startswith("-")]
        if not verbs or verbs[0] != "test":
            return False
    if executable in {"go", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat"}:
        verbs = [arg.lower() for arg in command[1:] if not arg.startswith("-")]
        if not verbs or verbs[0] != "test":
            return False
    return True


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

    if max_lines < 1 or max_lines > 1000:
        print("trim-run: line limit must be between 1 and 1000", file=sys.stderr)
        return 2

    if args and args[0] in ("-h", "--help"):
        print("Usage: trim-run [-n|--lines 1..1000] [SAFE_COMMAND [ARG ...]]")
        print("With no command, trim-run reads and trims stdin.")
        return 0

    # If no command arguments, read from stdin (pipe mode)
    if not args:
        if sys.stdin.isatty():
            print("Usage: trim-run [-n MAX_LINES] <command> [args...]")
            print("   or: <command> | trim-run [-n MAX_LINES]")
            return 0
        lines = sys.stdin.readlines()
        filter_and_print_trimmed(lines, max_lines)
        return 0

    # Subprocess execution mode
    try:
        command = shlex.split(args[0]) if len(args) == 1 else args
    except ValueError as exc:
        print(f"trim-run: invalid command quoting: {exc}", file=sys.stderr)
        return 2
    if not _trim_run_safe_command(command):
        print("trim-run: command is not in the safe read/validation allowlist", file=sys.stderr)
        return 2

    try:
        proc = subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
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
                            extracted_lines = [l for l in res.stdout.splitlines() if l.strip()]
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
