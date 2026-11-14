"""Conservative classification for package and build tools."""
from __future__ import annotations

from typing import Any

from .command_policy import _classification_result
from .command_validation import _validation_classification


def _build_classification(cfg: dict[str, Any], reason: str) -> dict[str, Any]:
    return _classification_result(
        "build", cacheable=True,
        allowed=bool(cfg.get("allow_build", True)), reason=reason,
    )


def _mutating_classification(cfg: dict[str, Any], reason: str) -> dict[str, Any]:
    return _classification_result(
        "mutating", cacheable=False,
        allowed=bool(cfg.get("allow_mutating", False)), reason=reason,
    )


def _unknown_classification(cfg: dict[str, Any], reason: str) -> dict[str, Any]:
    return _classification_result(
        "unknown", cacheable=False,
        allowed=bool(cfg.get("allow_unknown", False)), reason=reason,
    )


def classify_build_command(
    exe_base: str,
    tokens: list[str],
    lower: list[str],
    cfg: dict[str, Any],
    *,
    mutating_words: set[str],
    validators: set[str],
) -> dict[str, Any] | None:
    positional_verbs = [token.lower() for token in tokens[1:] if not token.startswith(("-", "/"))]
    primary_verb = positional_verbs[0] if positional_verbs else ""

    if exe_base == "dotnet":
        flag_info = {"--info", "--version", "--list-sdks", "--list-runtimes", "--help", "-h", "-v"}
        if any(flag in lower for flag in flag_info) and not any(
            verb in lower for verb in ("build", "test", "run", "clean", "publish")
        ):
            return _classification_result(
                "read", cacheable=True,
                allowed=bool(cfg.get("allow_read", True)),
                reason="read-only dotnet inspection",
            )
        if primary_verb in {"test", "vstest"}:
            return _validation_classification(cfg, "dotnet test")
        if primary_verb in {"build", "compile", "pack", "restore", "clean", "run", "msbuild"}:
            return _build_classification(cfg, f"dotnet {primary_verb}")
        if primary_verb == "format":
            if any(flag in lower for flag in {"--verify-no-changes", "--check"}):
                return _validation_classification(cfg, "dotnet format check")
            return _mutating_classification(cfg, "dotnet format changes source without --verify-no-changes")

    package_tools = {"npm", "pnpm", "yarn", "bun"}
    if exe_base in package_tools:
        mutating = {"install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade", "publish", "link", "unlink", "pack", "version"}
        if primary_verb in mutating:
            return _mutating_classification(cfg, f"{exe_base} {primary_verb} changes dependencies or publishes artifacts")
        script = ""
        if primary_verb in {"run", "run-script"} and len(positional_verbs) > 1:
            script = positional_verbs[1]
        elif primary_verb:
            script = primary_verb
        safe_validation = {"test", "lint", "check", "typecheck", "type-check", "analyse", "analyze", "audit"}
        safe_build = {"build", "compile"}
        if script in safe_validation:
            return _validation_classification(cfg, f"{exe_base} safe validation script")
        if script in safe_build:
            return _build_classification(cfg, f"{exe_base} safe build script")
        return _unknown_classification(cfg, f"{exe_base} script is not in the safe validation/build allowlist")

    if exe_base == "composer":
        if primary_verb in {"install", "update", "upgrade", "remove", "require", "create-project", "dump-autoload", "global"}:
            return _mutating_classification(cfg, f"composer {primary_verb} may change dependencies or generated files")
        if primary_verb in {"validate", "audit", "test", "phpunit", "phpstan", "analyse", "analyze", "check"}:
            return _validation_classification(cfg, "composer validation command")
        return _unknown_classification(cfg, "composer command is not in the safe validation allowlist")

    if exe_base == "make":
        if any(verb in {"clean", "install", "uninstall", "deploy", "publish", "release"} for verb in positional_verbs):
            return _mutating_classification(cfg, "make target may mutate or deploy")
        safe_validation = {"test", "tests", "check", "lint", "validate", "verify", "typecheck"}
        safe_build = {"build", "compile", "all"}
        if positional_verbs and all(verb in safe_validation for verb in positional_verbs):
            return _validation_classification(cfg, "make validation target")
        if positional_verbs and all(verb in safe_build for verb in positional_verbs):
            return _build_classification(cfg, "make build target")
        return _unknown_classification(cfg, "make target is not in the safe validation/build allowlist")

    if exe_base == "cargo":
        if primary_verb == "fmt" and "--check" not in lower:
            return _mutating_classification(cfg, "cargo fmt changes source without --check")
        if primary_verb in {"test", "check", "clippy", "bench"} or (primary_verb == "fmt" and "--check" in lower):
            return _validation_classification(cfg, "cargo validation command")
        if primary_verb == "build":
            return _build_classification(cfg, "cargo build")
        return _unknown_classification(cfg, "cargo command is not in the safe validation/build allowlist")

    if exe_base in {"go", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "cmake", "ctest"}:
        if any(verb in mutating_words or verb in {"tidy", "publish", "deploy", "release"} for verb in positional_verbs):
            return _mutating_classification(cfg, f"{exe_base} command may mutate project or publish artifacts")
        validation_words = {"test", "tests", "check", "verify", "lint", "vet", "clippy", "ctest"}
        build_words = {"build", "compile", "package", "assemble"}
        if exe_base == "ctest" or any(verb in validation_words for verb in positional_verbs):
            return _validation_classification(cfg, f"{exe_base} validation command")
        if exe_base == "cmake" or any(verb in build_words for verb in positional_verbs):
            return _build_classification(cfg, f"{exe_base} build command")
        return _unknown_classification(cfg, f"{exe_base} command is not in the safe validation/build allowlist")

    if exe_base in validators:
        if primary_verb in mutating_words:
            return _mutating_classification(cfg, f"mutating verb {primary_verb}")
        if any(verb in positional_verbs for verb in ("build", "compile")):
            return _build_classification(cfg, "build command")
        return _validation_classification(cfg, "validation/test command")

    return None
