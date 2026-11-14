"""Pure language-specific import statement formatting helpers."""

import re
from pathlib import Path


def language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".cs":
        return "csharp"
    if suffix == ".php":
        return "php"
    if suffix in {".ts", ".tsx", ".mts", ".cts"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"}:
        return "javascript"
    return "auto"


def import_for(symbol: str, container: str, path: str, lang: str, source: str) -> str:
    if lang == "csharp":
        namespace = container
        if not namespace:
            match = re.search(r"(?m)^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.]*)", source)
            namespace = match.group(1) if match else ""
        return f"using {namespace};" if namespace else ""
    if lang == "php":
        namespace = container
        if not namespace:
            match = re.search(r"(?m)^\s*namespace\s+([A-Za-z_][A-Za-z0-9_\\]*)", source)
            namespace = match.group(1) if match else ""
        fqn = f"{namespace}\\{symbol}" if namespace else symbol
        return f"use {fqn};"
    if lang == "python":
        mod_path = Path(path.replace("\\", "/"))
        without_suffix = mod_path.with_suffix("") if mod_path.suffix else mod_path
        parts = list(without_suffix.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if any(not part.isidentifier() for part in parts if part not in {".", ""}):
            return ""
        module = ".".join(part for part in parts if part not in {".", ""})
        return f"from {module} import {symbol}" if module else f"import {symbol}"
    if lang in {"typescript", "javascript"}:
        normalized = path.replace("\\", "/")
        pth = Path(normalized)
        if pth.suffix.lower() in {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}:
            normalized = str(pth.with_suffix("")).replace("\\", "/")
        if not normalized.startswith("."):
            normalized = "./" + normalized
        normalized = normalized.replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
        return f"import {{ {symbol} }} from '{normalized}';"
    return ""
