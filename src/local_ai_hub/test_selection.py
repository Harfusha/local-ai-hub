"""Pure runner compatibility rules shared by affected-test execution paths."""
from pathlib import PurePosixPath
import os
import shlex
import subprocess


_RUNNER_EXTENSIONS = {
    "pytest": frozenset({".py"}),
    "npm": frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}),
    "dotnet": frozenset({".cs", ".fs", ".vb", ".csproj", ".fsproj", ".vbproj"}),
    "cargo": frozenset({".rs"}),
    "go": frozenset({".go"}),
}
_RUNNER_ALIASES = {"python": "pytest", "unittest": "pytest", "jest": "npm", "vitest": "npm"}


def canonical_runner(runner: str) -> str:
    name = str(runner).strip().lower()
    return _RUNNER_ALIASES.get(name, name)


def compatible_tests(paths: list[str], runner: str) -> tuple[list[str], list[str]]:
    """Keep order, deduplicate, and separate paths the selected runner cannot consume."""
    selected: list[str] = []
    excluded: list[str] = []
    extensions = _RUNNER_EXTENSIONS.get(canonical_runner(runner), frozenset())
    for path in dict.fromkeys(paths):
        suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
        (selected if suffix in extensions else excluded).append(path)
    return selected, excluded


def automatic_runner(paths: list[str]) -> str:
    """Preserve Python/JS/.NET priority; never infer Python from unrelated files."""
    for runner in ("pytest", "npm", "dotnet", "cargo", "go"):
        if compatible_tests(paths, runner)[0]:
            return runner
    return "unknown"


def runner_path_argument(path: str) -> str:
    """A relative filename beginning with '-' must not become a runner option."""
    return "./" + path if path.startswith("-") else path


def affected_test_command(paths: list[str], runner: str) -> str:
    runner = canonical_runner(runner)
    selected, _excluded = compatible_tests(paths, runner)
    if not selected:
        return ""
    quote = (lambda value: subprocess.list2cmdline([value])) if os.name == "nt" else shlex.quote
    arguments = " ".join(quote(runner_path_argument(path)) for path in selected)
    stems = [PurePosixPath(path.replace("\\", "/")).stem for path in selected]
    if runner == "pytest":
        return f"pytest {arguments}"
    if runner == "npm":
        return f"npm test -- {arguments}"
    if runner == "dotnet":
        filters = " | ".join(f"FullyQualifiedName~{stem}" for stem in stems)
        return f'dotnet test --filter "{filters}"'
    if runner == "cargo":
        return "cargo test " + " ".join(quote(stem) for stem in stems)
    if runner == "go":
        return f"go test {arguments}"
    return ""
