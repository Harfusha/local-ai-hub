"""Conservative classification for package and build tools."""
from __future__ import annotations

from typing import Any


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
            return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": "read-only dotnet inspection"}
        if primary_verb in {"test", "vstest"}:
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "dotnet test"}
        if primary_verb in {"build", "compile", "pack", "restore", "clean", "run", "msbuild"}:
            return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"dotnet {primary_verb}"}
        if primary_verb == "format":
            if any(flag in lower for flag in {"--verify-no-changes", "--check"}):
                return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "dotnet format check"}
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "dotnet format changes source without --verify-no-changes"}

    package_tools = {"npm", "pnpm", "yarn", "bun"}
    if exe_base in package_tools:
        mutating = {"install", "i", "add", "remove", "rm", "uninstall", "update", "upgrade", "publish", "link", "unlink", "pack", "version"}
        if primary_verb in mutating:
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} {primary_verb} changes dependencies or publishes artifacts"}
        script = ""
        if primary_verb in {"run", "run-script"} and len(positional_verbs) > 1:
            script = positional_verbs[1]
        elif primary_verb:
            script = primary_verb
        safe_validation = {"test", "lint", "check", "typecheck", "type-check", "analyse", "analyze", "audit"}
        safe_build = {"build", "compile"}
        if script in safe_validation:
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} safe validation script"}
        if script in safe_build:
            return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} safe build script"}
        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} script is not in the safe validation/build allowlist"}

    if exe_base == "composer":
        if primary_verb in {"install", "update", "upgrade", "remove", "require", "create-project", "dump-autoload", "global"}:
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"composer {primary_verb} may change dependencies or generated files"}
        if primary_verb in {"validate", "audit", "test", "phpunit", "phpstan", "analyse", "analyze", "check"}:
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "composer validation command"}
        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "composer command is not in the safe validation allowlist"}

    if exe_base == "make":
        if any(verb in {"clean", "install", "uninstall", "deploy", "publish", "release"} for verb in positional_verbs):
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "make target may mutate or deploy"}
        safe_validation = {"test", "tests", "check", "lint", "validate", "verify", "typecheck"}
        safe_build = {"build", "compile", "all"}
        if positional_verbs and all(verb in safe_validation for verb in positional_verbs):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "make validation target"}
        if positional_verbs and all(verb in safe_build for verb in positional_verbs):
            return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "make build target"}
        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "make target is not in the safe validation/build allowlist"}

    if exe_base == "cargo":
        if primary_verb == "fmt" and "--check" not in lower:
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": "cargo fmt changes source without --check"}
        if primary_verb in {"test", "check", "clippy", "bench"} or (primary_verb == "fmt" and "--check" in lower):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "cargo validation command"}
        if primary_verb == "build":
            return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "cargo build"}
        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": "cargo command is not in the safe validation/build allowlist"}

    if exe_base in {"go", "mvn", "mvnw", "gradle", "gradlew", "gradlew.bat", "cmake", "ctest"}:
        if any(verb in mutating_words or verb in {"tidy", "publish", "deploy", "release"} for verb in positional_verbs):
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"{exe_base} command may mutate project or publish artifacts"}
        validation_words = {"test", "tests", "check", "verify", "lint", "vet", "clippy", "ctest"}
        build_words = {"build", "compile", "package", "assemble"}
        if exe_base == "ctest" or any(verb in validation_words for verb in positional_verbs):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"{exe_base} validation command"}
        if exe_base == "cmake" or any(verb in build_words for verb in positional_verbs):
            return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"{exe_base} build command"}
        return {"class": "unknown", "cacheable": False, "allowed": bool(cfg.get("allow_unknown", False)), "reason": f"{exe_base} command is not in the safe validation/build allowlist"}

    if exe_base in validators:
        if primary_verb in mutating_words:
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"mutating verb {primary_verb}"}
        if any(verb in positional_verbs for verb in ("build", "compile")):
            return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": "build command"}
        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": "validation/test command"}

    return None
