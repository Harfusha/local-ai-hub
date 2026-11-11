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
    "phpunit": frozenset({".php"}),
    "pest": frozenset({".php"}),
}
_RUNNER_ALIASES = {"python": "pytest", "unittest": "pytest", "jest": "npm", "vitest": "npm", "php": "phpunit"}


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
    """Preserve runner priority; never infer Python from unrelated files."""
    for runner in ("pytest", "npm", "dotnet", "cargo", "go", "phpunit", "pest"):
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
        # Cargo's positional argument filters test names. Select direct
        # integration-test targets with --test; other source paths do not
        # identify a Cargo target, so run the package's tests without a filter.
        cargo_paths = [PurePosixPath(path.replace("\\", "/")) for path in selected]
        if all(len(path.parts) == 2 and path.parts[0] == "tests" for path in cargo_paths):
            targets = dict.fromkeys(path.stem for path in cargo_paths)
            return "cargo test " + " ".join(f"--test {quote(target)}" for target in targets)
        return "cargo test"
    if runner == "go":
        go_paths = [PurePosixPath(path.replace("\\", "/")) for path in selected]
        packages = dict.fromkeys(
            "." if path.parent == PurePosixPath(".") else "./" + path.parent.as_posix()
            for path in go_paths
        )
        return "go test " + " ".join(quote(package) for package in packages)
    if runner in {"phpunit", "pest"}:
        return f"vendor/bin/{runner} {arguments}"
    return ""
