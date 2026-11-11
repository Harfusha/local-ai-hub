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
        lexical_source = " ".join(match.group() for match in _TOKENS.finditer(source)
                                  if not match.group().startswith(("//", "/*", "'", '"', "`")))
        # Preserve dotted/backslash namespace components after removing opaque text.
        lexical_source = re.sub(r"\s*([.\\])\s*", r"\1", lexical_source)
        if not re.search(rf"\b(?:class|interface|enum|trait|struct|record)\s+{re.escape(name)}\b", lexical_source):
            return False, "type_declaration_not_found"
        tokens = [
            match.group()
            for match in _TOKENS.finditer(source)
            if not match.group().startswith(("//", "/*", "'", '"', "\u0060"))
        ]
        namespace_scopes: dict[int, str] = {}
        file_namespace = ""
        pending_namespace: str | None = None
        depth = 0
        type_namespace_mismatch = False
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token == "namespace":
                end = index + 1
                while end < len(tokens) and tokens[end] not in {"{", ";"}:
                    end += 1
                if end >= len(tokens):
                    return False, "invalid_namespace_declaration"
                declared = "".join(tokens[index + 1 : end])
                if tokens[end] == "{":
                    pending_namespace = declared
                else:
                    file_namespace = declared
                    namespace_scopes.clear()
                index = end
                continue
            if token == "{":
                depth += 1
                if pending_namespace is not None:
                    parent_depth = max(namespace_scopes, default=-1)
                    parent = namespace_scopes.get(parent_depth, file_namespace)
                    namespace_scopes[depth] = ".".join(
                        part for part in (parent, pending_namespace) if part
                    )
                    pending_namespace = None
            elif token == "}":
                namespace_scopes.pop(depth, None)
                depth = max(0, depth - 1)
            elif token in {"class", "interface", "enum", "trait", "struct", "record"}:
                if index + 1 < len(tokens) and tokens[index + 1] == name:
                    active_depth = max(namespace_scopes, default=0)
                    declared_namespace = namespace_scopes.get(
                        active_depth, file_namespace
                    )
                    normalized_container = re.sub(
                        r"\s*([.\\])\s*", r"\1", container.strip()
                    )
                    if depth != active_depth:
                        type_namespace_mismatch = True
                    elif not container or declared_namespace == normalized_container:
                        return True, "indexed_namespace_type"
                    else:
                        type_namespace_mismatch = True
            index += 1
        if type_namespace_mismatch:
            return False, "nested_type_not_importable_by_namespace"
        return False, "type_declaration_not_found"
    return False, "export_language_unsupported"
