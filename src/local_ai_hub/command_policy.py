"""Command classification data shared by the command broker."""

import ntpath
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def _classification_result(
    class_name: str,
    *,
    cacheable: bool,
    allowed: bool,
    reason: str,
    replay_safe: bool | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "class": class_name,
        "cacheable": cacheable,
        "allowed": allowed,
        "reason": reason,
    }
    if replay_safe is not None:
        result["replay_safe"] = replay_safe
    return result


READ_ONLY = {
    "git", "rg", "ripgrep", "grep", "findstr", "where", "which",
    "fd", "fdfind", "find", "cat", "type", "head", "tail", "wc",
    "diff", "cmp", "sort", "uniq", "cut", "tr", "file", "stat",
    "echo", "pwd", "tree", "jq", "yq", "ls", "dir",
    "tasklist", "whoami", "hostname", "systeminfo", "ver", "ipconfig", "netstat",
    "fc", "comp", "attrib", "set", "env", "printenv",
}
READ_FILTERS = {
    "grep", "ripgrep", "rg", "findstr", "select-string", "find", "head", "tail",
    "wc", "sort", "uniq", "cut", "tr", "jq", "yq", "cat", "type",
    "format-table", "select-object", "convertto-json", "convertfrom-json",
    "out-string", "out-null", "tee", "more", "less",
}
# Host/process/network reads cannot be cached as repository snapshots.
VOLATILE_READS = frozenset({
    "tasklist", "whoami", "hostname", "systeminfo", "ver", "ipconfig", "netstat",
    "set", "env", "printenv",
})
VALIDATORS = {
    "pytest", "phpunit", "phpstan", "ruff", "mypy", "eslint", "tsc", "cargo",
    "dotnet", "go", "npm", "pnpm", "yarn", "bun", "composer", "make", "cmake",
    "ctest", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "flake8", "pylint",
    "black", "isort", "bandit", "shellcheck", "yamllint",
}
PURE_VALIDATORS = {
    "pytest", "phpunit", "phpstan", "pest", "ruff", "mypy", "eslint", "tsc",
    "pyflakes", "flake8", "pylint", "bandit", "radon", "yamllint", "shellcheck",
    "markdownlint", "biome", "oxlint", "clippy", "coverage", "vitest", "jest",
    "mocha", "ava", "playwright", "cypress", "tox", "nox", "pre-commit",
}
KNOWN_PYTHON_MODULES = {
    "pytest", "ruff", "mypy", "unittest", "compileall", "pyflakes", "flake8",
    "pylint", "bandit", "coverage", "tox", "nox", "pre_commit", "pre-commit",
    "build", "wheel", "setuptools", "flit", "local_ai_hub", "local_ai_hub.generator",
    "pip", "json.tool", "platform", "sysconfig", "site", "venv", "pydoc", "black", "isort",
}
MUTATING_WORDS = {
    "commit", "push", "pull", "merge", "rebase", "reset", "clean", "checkout", "switch",
    "restore", "add", "stash", "apply", "install", "update", "upgrade", "publish", "deploy",
    "migrate", "migration", "seed", "format", "fix", "write", "delete", "remove",
}
DANGEROUS_EXES = {
    "rm", "del", "erase", "rmdir", "shutdown", "reboot", "poweroff", "mkfs", "diskpart", "format",
}
SHELL_INTERPRETERS = {"sh", "bash", "dash", "zsh", "fish", "cmd", "powershell", "pwsh"}


_INTERACTIVE_OUTPUT_PATTERNS = [
    re.compile(r"\[[yY]/[nN]\]"),
    re.compile(r"\(yes/no\)", re.IGNORECASE),
    re.compile(r"password(\s+for\s+.*)?:", re.IGNORECASE),
    re.compile(r"press\s+any\s+key", re.IGNORECASE),
    re.compile(r"do\s+you\s+want\s+to\s+continue", re.IGNORECASE),
]
_INTERACTIVE_COMMAND_PATTERNS = [
    re.compile(r"\[y/n\]", re.I),
    re.compile(r"\(y/n\)", re.I),
    re.compile(r"password\s*:", re.I),
    re.compile(r"enter\s+(?:passphrase|password|pin|key|choice)", re.I),
    re.compile(r"press\s+(?:any\s+key|enter)\s+to\s+continue", re.I),
    re.compile(r"do\s+you\s+want\s+to\s+continue\s*\?", re.I),
    re.compile(r"are\s+you\s+sure\s*\?", re.I),
]


def is_interactive_output_prompt(text: str) -> bool:
    """Detect common interactive prompts in the bounded output tail."""
    if not text:
        return False
    tail = text[-300:] if len(text) > 300 else text
    return any(pattern.search(tail) for pattern in _INTERACTIVE_OUTPUT_PATTERNS)


def is_interactive_command_prompt(text: str) -> bool:
    """Detect prompts that require aborting a non-interactive command run."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INTERACTIVE_COMMAND_PATTERNS)


def command_executable_identity(tokens: Sequence[str]) -> tuple[str, list[str]]:
    """Normalize the executable basename and arguments used for classification."""
    raw_executable = tokens[0].strip('"').replace("/", "\\")
    executable = ntpath.basename(raw_executable).lower() or Path(
        tokens[0].strip('"')
    ).name.lower()
    executable_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", executable)
    lower_arguments = [token.lower() for token in tokens[1:]]
    return executable_base, lower_arguments


def normalize_user_whitelisted_tools(values: Iterable[Any]) -> set[str]:
    """Normalize configured extra-allowed tool names once for all classifiers."""
    normalized: set[str] = set()
    for value in values:
        tool = str(value).strip().lower()
        if tool:
            normalized.add(tool)
    return normalized


def contains_user_whitelisted_tool(text: str, extra_allowed: set[str]) -> bool:
    """Find configured extra-allowed tool names using the broker's word boundaries."""
    return any(
        bool(tool)
        and re.search(r"(?<!\w)" + re.escape(tool) + r"(?!\w)", text, re.IGNORECASE)
        is not None
        for tool in extra_allowed
    )


def classify_user_whitelisted_tool(
    executable: str,
    extra_allowed: set[str],
) -> dict[str, object] | None:
    """Classify an explicit extra-allowed tool without bypassing shell checks."""
    if executable not in extra_allowed or executable in SHELL_INTERPRETERS:
        return None
    return _classification_result(
        "validation", cacheable=True, allowed=True, replay_safe=False,
        reason=f"user-whitelisted tool: {executable}",
    )


def classify_dangerous_or_whitelisted_tool(
    executable: str,
    extra_allowed: set[str],
) -> dict[str, object] | None:
    """Apply dangerous-executable precedence before user allowlisting."""
    if executable in DANGEROUS_EXES:
        return _classification_result(
            "dangerous", cacheable=False, allowed=False,
            reason="dangerous executable",
        )
    return classify_user_whitelisted_tool(executable, extra_allowed)


def classify_pipeline_filter(
    tokens: Sequence[str],
    read_filters: set[str],
    read_only: set[str],
) -> dict[str, Any] | None:
    """Reject pipeline stages whose executable is not a known read filter."""
    if not tokens:
        return None
    executable, _ = command_executable_identity(tokens)
    if executable in read_filters or executable in read_only:
        return None
    return _classification_result(
        "unknown", cacheable=False, allowed=False,
        reason=f"pipeline filter {executable} not allowed",
    )


def classify_command_sequence(
    classifications: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine classified shell sequence results using broker precedence."""
    classes = [result.get("class", "unknown") for result in classifications]
    dangerous = next(
        (result for result in classifications if result.get("class") == "dangerous"),
        None,
    )
    if dangerous is not None:
        return dangerous

    blocked = next((result for result in classifications if not result.get("allowed")), None)
    if blocked is not None:
        return blocked

    order = ["dangerous", "unknown", "mutating", "build", "validation", "read"]
    for command_class in order:
        if command_class in classes:
            return _classification_result(
                command_class, cacheable=False,
                allowed=bool(
                    cfg.get(
                        f"allow_{command_class}",
                        command_class in {"read", "validation", "build"},
                    )
                ),
                replay_safe=(
                    command_class == "validation" and all(
                        bool(result.get("replay_safe", result.get("class") == "read"))
                        for result in classifications
                    )
                ),
                reason=f"compound sequence ({command_class})",
            )
    return _classification_result(
        "read", cacheable=False, allowed=True, reason="compound sequence"
    )


POWERSHELL_DANGEROUS = (
    "remove-item", "format-volume", "stop-computer", "restart-computer",
    "stop-process", "invoke-webrequest", "invoke-restmethod", "start-bitstransfer",
    "set-executionpolicy", "new-service", "stop-service", "rmdir /s", "del /s",
    "-encodedcommand", " -e ", " -enc ",
)
POWERSHELL_MUTATING = (
    "set-content", "add-content", "out-file", "new-item", "copy-item",
    "move-item", "rename-item", "clear-content", "git push", "git commit",
    "start-process", "start-service", "stop-service", "restart-service", "set-service",
    "git add", "git merge", "git reset", "git rebase", "git checkout -b",
    "git branch -d", "git stash", "git rm", "git clean", "git switch",
    "git restore", "git cherry-pick", "git revert", "git tag -d",
)
POWERSHELL_VALIDATION_KEYWORDS = {"test", "validate", "check", "audit", "-runtests", "pester"}
POWERSHELL_READ_PREFIXES = (
    "get-", "select-", "measure-", "format-", "test-path", "where-",
    "out-string", "compare-", "convertfrom-", "convertto-",
)
