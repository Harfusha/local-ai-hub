"""Command classification data shared by the command broker."""

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
