"""Pure deterministic file-card summary construction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def build_file_card(
    path: str,
    language: str,
    is_test: bool,
    kinds: dict[str, list[str]],
    symbols: list[str],
    dependencies: list[str],
    code_index_summary: Any,
) -> dict[str, Any]:
    """Build a reusable card from parsed facts and optional code-index facts."""
    symbols = list(symbols)
    dependencies = list(dependencies)
    ci = code_index_summary
    for item in ci.get("symbols", []) if isinstance(ci, dict) else []:
        name = str(item.get("name", ""))
        if name and name not in symbols and len(symbols) < 24:
            symbols.append(name)
    for item in ci.get("edges", []) if isinstance(ci, dict) else []:
        if str(item.get("kind")) == "imports":
            name = str(item.get("dst", ""))
            if name and name not in dependencies and len(dependencies) < 24:
                dependencies.append(name)
    side_effects = []
    if kinds.get("database"): side_effects.append("database")
    if kinds.get("route"): side_effects.append("http-route")
    if kinds.get("env") or kinds.get("config"): side_effects.append("configuration")
    if kinds.get("concurrency"): side_effects.append("concurrency")
    if kinds.get("service") or kinds.get("container_base") or kinds.get("container_image"): side_effects.append("containers")
    if kinds.get("port"): side_effects.append("network-ports")
    if kinds.get("ci_job") or kinds.get("ci_action"): side_effects.append("ci")
    if kinds.get("terraform_resource") or kinds.get("terraform_module") or kinds.get("k8s_kind") or kinds.get("k8s_resource"): side_effects.append("infrastructure")
    if kinds.get("proto_service") or kinds.get("proto_rpc"): side_effects.append("rpc-api")
    risks = []
    if kinds.get("security"): risks.append("security-sensitive")
    if kinds.get("concurrency"): risks.append("concurrency-sensitive")
    if kinds.get("database") or kinds.get("db_table"): risks.append("data/persistence")
    if kinds.get("todo"): risks.append("todo/fixme")
    tests = [path] if is_test else []
    keywords = []
    call_names = [str(x.get("name", "")) for x in ci.get("references", [])[:20]] if isinstance(ci, dict) else []
    for group in (symbols, dependencies, call_names, kinds.get("route", []), kinds.get("env", []), kinds.get("config", []), kinds.get("service", []), kinds.get("terraform_resource", []), kinds.get("proto_service", [])):
        for item in group:
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", str(item)):
                low = token.lower()
                if low not in keywords:
                    keywords.append(low)
                if len(keywords) >= 30: break
    name = Path(path).name
    purpose_bits = ["test" if is_test else "source", language]
    if kinds.get("route"): purpose_bits.append("HTTP routing")
    if kinds.get("entrypoint") or kinds.get("entrypoint_file"): purpose_bits.append("entry point")
    if kinds.get("database"): purpose_bits.append("data access")
    if kinds.get("config") or kinds.get("env"): purpose_bits.append("configuration")
    if kinds.get("service") or kinds.get("container_base"): purpose_bits.append("container infrastructure")
    if kinds.get("ci_job") or kinds.get("ci_action"): purpose_bits.append("CI workflow")
    if kinds.get("terraform_resource"): purpose_bits.append("infrastructure-as-code")
    if kinds.get("proto_service") or kinds.get("proto_rpc"): purpose_bits.append("RPC schema")
    purpose = f"{name}: " + ", ".join(purpose_bits)
    richness = len(symbols) * 2 + len(dependencies) + min(12, len(call_names)) + len(side_effects) * 2 + len(kinds.get("route", [])) * 2 + len(kinds.get("env", []))
    low_manifest = name.lower(); low_path = path.replace("\\", "/").lower()
    manifest_like = low_manifest in {
        "package.json", "package-lock.json", "composer.json", "composer.lock", "pyproject.toml", "poetry.lock",
        "cargo.toml", "cargo.lock", "go.mod", "go.sum", "pom.xml", "pipfile", "gemfile", "gemfile.lock", "yarn.lock",
        "build.gradle", "build.gradle.kts", "makefile", "gnumakefile", "justfile", "dockerfile", "containerfile",
        "compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml", ".env", ".env.example", ".env.sample"
    } or (low_manifest.startswith("requirements") and low_manifest.endswith(".txt")) or "/.github/workflows/" in f"/{low_path}" or Path(path).suffix.lower() in {".tf", ".tfvars", ".proto", ".ini", ".cfg", ".properties"}
    confidence = 0.97 if manifest_like else min(0.95, 0.64 + 0.035 * richness + (0.08 if is_test else 0.0))
    return {
        "success": True, "deterministic": True, "confidence": round(confidence, 4),
        "card": {
            "purpose": purpose, "symbols": symbols, "dependencies": dependencies, "side_effects": side_effects,
            "risks": risks, "tests": tests, "keywords": keywords,
        },
    }
