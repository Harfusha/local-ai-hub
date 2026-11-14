from __future__ import annotations

import ast

def _python_shell_injection_lines(source: str, *, tree: ast.AST | None = None) -> list[int]:
    if tree is None:
        tree = ast.parse(source)
    scope_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    parents: dict[ast.AST, ast.AST] = {}
    scopes: list[ast.AST] = [tree]
    for node in ast.walk(tree):
        if isinstance(node, scope_types):
            scopes.append(node)
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    imports_by_scope: dict[ast.AST, dict[str, str]] = {}
    bindings_by_scope: dict[ast.AST, set[str]] = {}
    for scope in scopes:
        imported: dict[str, str] = {}
        bound: set[str] = set()

        def collect_bindings(node: ast.AST) -> None:
            if node is not scope and isinstance(node, scope_types):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    bound.add(node.name)
                return
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                        local_name = alias.asname or alias.name.split(".", 1)[0]
                        imported[local_name] = "module"
                    else:
                        bound.add(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    if node.module == "subprocess" and alias.name in {"Popen", "run", "call"}:
                        imported[local_name] = alias.name
                    else:
                        bound.add(local_name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            for child in ast.iter_child_nodes(node):
                collect_bindings(child)

        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = scope.args
            bound.update(arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs))
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        collect_bindings(scope)
        # A local assignment/parameter shadows an outer import throughout its scope.
        for name in bound:
            imported.pop(name, None)
        imports_by_scope[scope] = imported
        bindings_by_scope[scope] = bound

    def resolves_as(node: ast.AST, name: str, kind: str) -> bool:
        def enclosing_scope(current: ast.AST | None) -> ast.AST | None:
            while current is not None and not isinstance(current, (ast.Module, *scope_types)):
                current = parents.get(current)
            return current

        scope = enclosing_scope(node)
        while scope is not None:
            if imports_by_scope.get(scope, {}).get(name) == kind:
                return True
            if name in bindings_by_scope.get(scope, set()):
                return False
            parent_scope = enclosing_scope(parents.get(scope))
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and isinstance(parent_scope, ast.ClassDef):
                parent_scope = enclosing_scope(parents.get(parent_scope))
            scope = parent_scope
        return False

    def literal_dict_enables_shell(value: ast.AST) -> bool:
        found, enabled = literal_dict_shell_value(value)
        return found and enabled

    def literal_dict_shell_value(value: ast.AST) -> tuple[bool, bool]:
        if not isinstance(value, ast.Dict):
            return False, False
        found = False
        enabled = False
        for key, item in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and key.value == "shell":
                found = True
                enabled = not (isinstance(item, ast.Constant) and not bool(item.value))
            elif key is None:
                nested_found, nested_enabled = literal_dict_shell_value(item)
                if nested_found:
                    found = True
                    enabled = nested_enabled
        return found, enabled

    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        is_subprocess_call = (
            isinstance(function, ast.Attribute)
            and function.attr in {"Popen", "run", "call"}
            and isinstance(function.value, ast.Name)
            and resolves_as(node, function.value.id, "module")
        ) or (
            isinstance(function, ast.Name)
            and any(
                resolves_as(node, function.id, imported_name)
                for imported_name in {"Popen", "run", "call"}
            )
        )
        if not is_subprocess_call:
            continue
        keyword_shell = any(
            (
                keyword.arg == "shell"
                and not (
                    isinstance(keyword.value, ast.Constant)
                    and not bool(keyword.value.value)
                )
            )
            or (keyword.arg is None and literal_dict_enables_shell(keyword.value))
            for keyword in node.keywords
        )
        # Popen's eighth optional positional argument (index 8) is ``shell``.
        positional_shell = (
            (
                isinstance(function, ast.Attribute)
                and function.attr == "Popen"
                and isinstance(function.value, ast.Name)
                and resolves_as(node, function.value.id, "module")
                or isinstance(function, ast.Name)
                and resolves_as(node, function.id, "Popen")
            )
            and len(node.args) > 8
            and not (
                isinstance(node.args[8], ast.Constant)
                and not bool(node.args[8].value)
            )
        )
        if keyword_shell or positional_shell:
            lines.add(node.lineno)
    return sorted(lines)
