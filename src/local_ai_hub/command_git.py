"""Git command classification rules for the safe CLI broker."""

from collections.abc import Mapping, Sequence
from typing import Any


def classify_git_command(
    tokens: Sequence[str], lower: Sequence[str], cfg: Mapping[str, Any]
) -> dict[str, Any]:
    unsafe_git_flags = {"--paginate", "--exec-path", "--config-env"}
    if any(
        flag in unsafe_git_flags
        or flag.startswith(
            ("--exec-path=", "--config-env=", "--upload-pack=", "--receive-pack=")
        )
        for flag in lower
    ):
        return {
            "class": "unknown",
            "cacheable": False,
            "allowed": False,
            "reason": "git flags may execute a pager or external program",
        }
    for idx, arg in enumerate(tokens[1:], 1):
        if arg == "-c" and idx < len(tokens) - 1:
            config_pair = tokens[idx + 1].lower()
            if any(
                config_pair.startswith(bad)
                for bad in (
                    "core.pager",
                    "pager.",
                    "alias.",
                    "core.fsmonitor",
                    "core.sshcommand",
                )
            ):
                return {
                    "class": "unknown",
                    "cacheable": False,
                    "allowed": False,
                    "reason": "git -c config may execute arbitrary commands",
                }

    skip_next = False
    sub = ""
    sub_idx = 0
    for idx, token in enumerate(tokens[1:], 1):
        if skip_next:
            skip_next = False
            continue
        if token in {
            "-C",
            "-c",
            "--git-dir",
            "--work-tree",
            "--namespace",
            "--no-optional-locks",
            "--no-pager",
        }:
            if token in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
                skip_next = True
            continue
        if token.startswith("-"):
            continue
        sub = token.lower()
        sub_idx = idx
        break

    if not sub:
        return {
            "class": "read",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_read", True)),
            "reason": "read-only git",
        }

    git_read_subs = {
        "status",
        "diff",
        "show",
        "log",
        "grep",
        "ls-files",
        "rev-parse",
        "branch",
        "tag",
        "describe",
        "blame",
        "remote",
        "cat-file",
        "check-ignore",
        "check-attr",
        "merge-base",
        "shortlog",
        "ls-tree",
        "var",
        "reflog",
        "version",
        "whatchanged",
        "for-each-ref",
        "show-ref",
        "rev-list",
        "diff-tree",
        "hash-object",
        "check-ref-format",
        "name-rev",
        "count-objects",
        "ls-remote",
        "verify-pack",
        "verify-commit",
        "verify-tag",
    }
    if sub in git_read_subs:
        return {
            "class": "read",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_read", True)),
            "reason": f"read-only git {sub}",
        }

    if sub == "stash":
        stash_args = [t.lower() for t in tokens[sub_idx + 1 :] if not t.startswith("-")]
        stash_sub = stash_args[0] if stash_args else "list"
        if stash_sub in {"list", "show"}:
            return {
                "class": "read",
                "cacheable": True,
                "allowed": bool(cfg.get("allow_read", True)),
                "reason": f"read-only git stash {stash_sub}",
            }

    if sub == "worktree":
        wt_args = [t.lower() for t in tokens[sub_idx + 1 :] if not t.startswith("-")]
        wt_sub = wt_args[0] if wt_args else "list"
        if wt_sub in {"list"}:
            return {
                "class": "read",
                "cacheable": True,
                "allowed": bool(cfg.get("allow_read", True)),
                "reason": f"read-only git worktree {wt_sub}",
            }

    if sub == "config":
        config_args = [t.lower() for t in tokens[sub_idx + 1 :]]
        read_flags = {
            "--get",
            "--get-all",
            "--get-regexp",
            "-l",
            "--list",
            "--show-origin",
            "--show-scope",
        }
        if any(rf in config_args for rf in read_flags):
            return {
                "class": "read",
                "cacheable": True,
                "allowed": bool(cfg.get("allow_read", True)),
                "reason": "read-only git config",
            }

    return {
        "class": "mutating",
        "cacheable": False,
        "allowed": bool(cfg.get("allow_mutating", False)),
        "reason": f"git {sub} may mutate",
    }
