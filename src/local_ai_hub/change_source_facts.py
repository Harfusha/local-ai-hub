"""Conservative source-fact and import candidates from exact source bytes."""
from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from .source_facts import _SOURCE_JS_IMPORT, _SOURCE_PHP_USE

_EXTENSIONS = {
    ".php", ".ctp", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
    ".vue", ".svelte", ".cs", ".html", ".htm", ".css", ".scss", ".sass",
    ".json", ".toml", ".xml", ".yaml", ".yml", ".sql", ".rs", ".go", ".java",
}
_FACT_KINDS = {
    "php_class", "php_trait", "php_interface", "php_enum", "php_function", "php_namespace",
    "ts_class", "ts_interface", "ts_type", "ts_function", "ts_enum", "ts_const",
    "react_component", "react_hook", "db_table", "db_column", "cake_table", "cake_entity",
    "cake_association", "eloquent_table", "eloquent_relation", "config_key",
    "css_class", "css_variable", "unity_lifecycle", "html_id", "web_component",
}
_SAFE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.\\:/\-$]{0,199}")


def supports_facts(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in _EXTENSIONS


def import_candidates(path: str, text: str) -> tuple[list[str], bool]:
    names: set[str] = set()
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    prefix = "." * node.level + (node.module or "")
                    if node.module:
                        names.add(prefix)
                    for alias in node.names:
                        if alias.name != "*":
                            names.add(prefix + ("." if node.module else "") + alias.name)
        except (SyntaxError, ValueError, RecursionError):
            return [], False
    elif suffix in {".php", ".ctp"}:
        names.update(match.group(1) for match in _SOURCE_PHP_USE.finditer(text))
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"}:
        names.update(match.group(3) for match in _SOURCE_JS_IMPORT.finditer(text) if match.group(3).startswith("."))
    clean = sorted(n for n in names if isinstance(n, str) and 0 < len(n) <= 200
                   and re.fullmatch(r"[A-Za-z0-9_.\\/@\-$]+", n))
    return clean[:32], len(clean) > 32


def summarize_facts(
    path: str, before: str, after: str, extract: Callable[[str, str], Any],
) -> dict[str, Any]:
    def collect(text: str) -> tuple[dict[tuple[str, str], list[str]], bool]:
        raw = extract(path, text)
        if not isinstance(raw, list):
            raise ValueError("Invalid source facts")
        output: dict[tuple[str, str], list[str]] = defaultdict(list)
        for fact in raw[:2000]:
            if not isinstance(fact, dict) or fact.get("kind") not in _FACT_KINDS:
                continue
            kind = fact["kind"]
            extra = fact.get("extra", {})
            name = extra.get("fqn", fact.get("name")) if isinstance(extra, dict) else fact.get("name")
            if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
                continue
            value = fact.get("value")
            if not isinstance(value, str):
                continue
            output[(kind, name)].append(hashlib.sha256(value.encode("utf-8")).hexdigest())
        return output, len(raw) > 2000

    try:
        old, old_truncated = collect(before)
        new, new_truncated = collect(after)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return {"status": "unavailable", "reason": "source_fact_extraction_failed"}
    changes = []
    ambiguous = 0
    for key in sorted(old.keys() | new.keys()):
        left, right = old.get(key, []), new.get(key, [])
        if len(left) > 1 or len(right) > 1:
            if Counter(left) != Counter(right):
                ambiguous += 1
            continue
        if not left:
            change = "added"
        elif not right:
            change = "removed"
        elif left != right:
            change = "modified"
        else:
            continue
        changes.append({"symbol": key[1], "types": [change], "fact_kind": key[0]})
    imports, imports_truncated = import_candidates(path, after)
    imports_before, before_truncated = import_candidates(path, before)
    declarations = sorted({name for kind, name in new if kind in {"php_class", "php_trait", "php_interface", "php_enum"}})
    old_declarations = sorted({name for kind, name in old if kind in {"php_class", "php_trait", "php_interface", "php_enum"}})
    return {
        "status": "observed", "method": "source_fact_delta_v1",
        "structural_equal": False, "formatting_only": False,
        "structural_equivalence_unknown": True,
        "change_counts": dict(Counter(c["types"][0] for c in changes)),
        "symbols": changes[:24], "symbols_truncated": len(changes) > 24,
        "fact_coverage_partial": old_truncated or new_truncated or bool(ambiguous),
        "ambiguous_fact_identities": ambiguous,
        "imports_after": imports, "imports_truncated": imports_truncated,
        "imports_before": imports_before, "imports_before_truncated": before_truncated,
        "declarations_after": declarations[:32], "declarations_truncated": len(declarations) > 32,
        "declarations_before": old_declarations[:32],
        "declarations_before_truncated": old_truncated or len(old_declarations) > 32,
        "behavior_equivalence_proven": False,
    }
