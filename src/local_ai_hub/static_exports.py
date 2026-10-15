"""Conservative named-export checks. Never imports or evaluates repository code."""
from __future__ import annotations

import ast
import re


_TOKENS = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|"
    r"`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|[^\s]"
)
_TYPE_KINDS = frozenset({"class", "interface", "struct", "enum", "record", "trait", "type"})


def named_export_status(source: str, language: str, name: str, *, container: str = "",
                        kind: str = "", access: str = "public") -> tuple[bool, str]:
    if len(source.encode("utf-8", errors="replace")) > 2_000_000:
        return False, "export_source_limit"
    if language == "python":
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return False, "invalid_module_syntax"
        # Named imports do not use __all__; it controls star imports only.
        for statement in tree.body:
            if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == name:
                return True, "top_level_python_declaration"
        return False, "not_top_level_declaration"
    if language in {"javascript", "typescript"}:
        if container:
            return False, "not_top_level_declaration"
        tokens: list[str] = []
        for match in _TOKENS.finditer(source):
            token = match.group()
            if token.startswith(("//", "/*", "'", '"', "`")):
                token = "<opaque>" if not token.startswith(("//", "/*")) else ""
            if token:
                tokens.append(token)
            if len(tokens) > 100_000:
                return False, "export_token_limit"
        if "/" in tokens:
            # Distinguishing regex literals from division requires a full JS parser.
            return False, "ambiguous_javascript_slash"
        declarations: set[str] = set()
        exports: set[str] = set()
        named: list[tuple[str, str]] = []
        depth = 0
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if depth == 0:
                exported = token == "export"
                j = i + 1 if exported else i
                while j < len(tokens) and tokens[j] in {"declare", "abstract", "async"}:
                    j += 1
                if j + 1 < len(tokens) and tokens[j] in {
                    "class", "interface", "enum", "type", "function", "const", "let", "var",
                }:
                    next_index = j + 1
                    if tokens[next_index] == "*":
                        next_index += 1
                    declared = tokens[next_index] if next_index < len(tokens) else ""
                    if re.fullmatch(r"[A-Za-z_$][\w$]*", declared):
                        declarations.add(declared)
                        if exported:
                            exports.add(declared)
                elif exported and j < len(tokens) and tokens[j] == "{":
                    end = j + 1
                    while end < len(tokens) and tokens[end] != "}" and end - j <= 4096:
                        end += 1
                    if end == len(tokens) or end - j > 4096:
                        return False, "unsupported_export_list"
                    # Re-exports require target-module validation; do not certify them here.
                    if end + 1 >= len(tokens) or tokens[end + 1] != "from":
                        items = tokens[j + 1:end]
                        segments: list[list[str]] = [[]]
                        for item in items:
                            if item == ",":
                                segments.append([])
                            else:
                                segments[-1].append(item)
                        for parts in segments:
                            if len(parts) == 1:
                                named.append((parts[0], parts[0]))
                            elif len(parts) == 3 and parts[1] == "as":
                                named.append((parts[0], parts[2]))
                    i = end + 1
                    continue
            if token == "{":
                depth += 1
                if depth > 128:
                    return False, "export_depth_limit"
            elif token == "}":
                depth -= 1
                if depth < 0:
                    return False, "invalid_module_braces"
            i += 1
        if depth:
            return False, "invalid_module_braces"
        exports.update(exported for local, exported in named if local in declarations)
        return (True, "static_named_export") if name in exports else (False, "named_export_not_proven")
    if language in {"csharp", "php"}:
        if kind not in _TYPE_KINDS or access.lower() in {"private", "protected"}:
            return False, "not_accessible_namespace_type"
        pattern = r"\bnamespace\s+([A-Za-z_][\w.\\]*)"
        lexical_source = " ".join(match.group() for match in _TOKENS.finditer(source)
                                  if not match.group().startswith(("//", "/*", "'", '"', "`")))
        # Preserve dotted/backslash namespace components after removing opaque text.
        lexical_source = re.sub(r"\s*([.\\])\s*", r"\1", lexical_source)
        namespaces = set(re.findall(pattern, lexical_source))
        if container and container not in namespaces:
            return False, "nested_type_not_importable_by_namespace"
        return True, "indexed_namespace_type"
    return False, "export_language_unsupported"
