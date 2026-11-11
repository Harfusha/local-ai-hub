from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def classify_hubctl_command(
    subcommands: Sequence[str],
    lower: Sequence[str],
    cfg: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Classify recognized hubctl subcommands for scripts and native executables."""
    sub = subcommands[0] if subcommands else ""
    if sub == "tasks":
        is_mutating = any(token in lower for token in {"--complete", "--fail"})
        if is_mutating:
            return {
                "class": "mutating",
                "cacheable": False,
                "allowed": bool(cfg.get("allow_mutating", False)),
                "reason": "hubctl tasks status mutation",
            }
        return {
            "class": "validation",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_validation", True)),
            "replay_safe": True,
            "reason": "hubctl tasks status check",
        }
    if sub in {
        "status",
        "service-status",
        "agent-state",
        "dashboard",
        "watch",
        "memory",
        "doctor",
        "logs",
    }:
        return {
            "class": "validation",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_validation", True)),
            "replay_safe": True,
            "reason": f"hubctl {sub} status check",
        }
    if sub == "generate":
        return {
            "class": "build",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_build", True)),
            "reason": "hubctl generate dynamic artifacts",
        }
    if sub in {"start", "stop", "restart", "cleanup"}:
        return {
            "class": "mutating",
            "cacheable": False,
            "allowed": bool(cfg.get("allow_mutating", False)),
            "reason": f"hubctl {sub} service lifecycle mutation",
        }
    return None


def classify_python_module_command(
    tokens: Sequence[str],
    lower: Sequence[str],
    cfg: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Classify recognized Python -m commands without handling Python -c code."""
    dash_m = None
    for idx, arg in enumerate(tokens[1:], 1):
        if arg == "-m" and idx < len(tokens) - 1:
            dash_m = tokens[idx + 1].lower()
            break
    if dash_m is None:
        return None

    validation_modules = {
        "pytest", "ruff", "mypy", "unittest", "flake8", "compileall", "pyflakes",
        "pylint", "bandit", "coverage", "tox", "nox", "pre_commit", "pre-commit",
    }
    if dash_m in validation_modules:
        return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"python -m {dash_m} validation"}
    if dash_m in {"build", "wheel", "setuptools", "flit"}:
        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} packaging"}
    if dash_m in {"local_ai_hub", "local_ai_hub.generator"}:
        return {"class": "build", "cacheable": True, "allowed": bool(cfg.get("allow_build", True)), "reason": f"python -m {dash_m} dynamic artifacts generator"}
    if dash_m == "pip":
        pip_sub = [token.lower() for token in tokens[idx + 2:] if not token.startswith("-")]
        pip_action = pip_sub[0] if pip_sub else ""
        if pip_action in {"list", "show", "check"} or any(flag in lower for flag in {"--version", "-v"}):
            return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"python -m pip {pip_action or 'info'}"}
        if pip_action in {"install", "uninstall", "download"}:
            return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"python -m pip {pip_action} changes environment"}
    if dash_m in {"json.tool", "platform", "sysconfig", "site", "venv", "pydoc"}:
        return {"class": "read", "cacheable": True, "allowed": bool(cfg.get("allow_read", True)), "reason": f"python -m {dash_m} inspection"}
    if dash_m in {"black", "isort"}:
        if any(flag in lower for flag in {"--check", "--diff"}):
            return {"class": "validation", "cacheable": True, "allowed": bool(cfg.get("allow_validation", True)), "replay_safe": True, "reason": f"python -m {dash_m} validation"}
        return {"class": "mutating", "cacheable": False, "allowed": bool(cfg.get("allow_mutating", False)), "reason": f"python -m {dash_m} format without --check"}
    return None


def classify_python_script_command(
    tokens: Sequence[str],
    lower: Sequence[str],
    cfg: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Classify Python script invocations without handling -m or -c commands."""
    non_flag_args = [token for token in tokens[1:] if not token.startswith("-")]
    if not non_flag_args:
        return None

    script_name = Path(non_flag_args[0].replace("\\", "/")).name.lower()
    sub_args = [token.lower() for token in non_flag_args[1:]]
    if script_name in {"hubctl.py", "hubctl"}:
        hubctl_result = classify_hubctl_command(sub_args, lower, cfg)
        if hubctl_result is not None:
            return hubctl_result
    if script_name in {"setup.py", "setup"}:
        if any(token in lower for token in {"--generate-only", "--help", "-h"}):
            return {
                "class": "build",
                "cacheable": True,
                "allowed": bool(cfg.get("allow_build", True)),
                "reason": "setup.py generate dynamic artifacts",
            }

    script_path = non_flag_args[0].replace("\\", "/").lower()
    is_builtin_tool = (
        script_path.startswith("tools/")
        or script_path.startswith("./tools/")
        or script_path.startswith("src/")
    )
    is_read_only_surface_inventory_check = (
        script_name == "surface_inventory.py"
        and is_builtin_tool
        and "--check" in lower
        and "--write-doc" not in lower
    )
    is_validation_script = (
        script_name in {
            "doctor.py",
            "selftest.py",
            "telemetry_report.py",
            "benchmark.py",
            "show_summary.py",
            "release_check.py",
            "check_contracts.py",
        }
        or is_read_only_surface_inventory_check
        or (
            is_builtin_tool
            and any(keyword in script_name for keyword in ("test", "validate", "check", "audit", "verify", "lint"))
        )
    )
    if is_validation_script:
        return {
            "class": "validation",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_validation", True)),
            "replay_safe": True,
            "reason": "python validation script",
        }
    if any(fragment in script_name for fragment in ("generate", "build", "compile", "bundle")):
        return {
            "class": "build",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_build", True)),
            "reason": "python build/generate script",
        }
    return {
        "class": "mutating",
        "cacheable": False,
        "allowed": bool(cfg.get("allow_mutating", False)),
        "replay_safe": False,
        "reason": "unclassified Python script may have side effects",
    }


def classify_python_inline_code(source: str, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Classify Python -c source without changing the command broker policy."""
    dangerous_inline = (
        "os.system(", "os.popen(", "subprocess.", "exec(", "eval(", "__import__(",
        "importlib.", "ctypes.", "shutil.rmtree", "shutil.move", "os.remove(",
        "shutil.copy", "os.unlink(", "os.rmdir(", "os.open(", "socket.", "pty.",
    )
    source_lower = source.lower()
    if any(pattern in source_lower for pattern in dangerous_inline):
        return {
            "class": "dangerous",
            "cacheable": False,
            "allowed": False,
            "reason": "python -c inline code contains potentially dangerous call",
        }

    is_validation = False
    try:
        tree = ast.parse(source)

        safe_std_modules = {
            "sys", "os", "time", "json", "math", "re", "pathlib", "hashlib", "threading",
        }
        safe_module_names: set[str] = set()
        literal_bound_names: set[str] = set()
        unsafe_bound_names: set[str] = set()
        shadowed_names: set[str] = set()
        defined_function_names: set[str] = set()
        func_param_names: set[str] = set()
        for candidate in ast.walk(tree):
            if isinstance(candidate, ast.Import):
                safe_module_names.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for alias in candidate.names
                    if alias.name.split(".", 1)[0] in safe_std_modules
                )
            elif isinstance(candidate, ast.ImportFrom):
                module = (candidate.module or "").split(".", 1)[0]
                if module in safe_std_modules:
                    safe_module_names.update(
                        alias.asname or alias.name
                        for alias in candidate.names
                    )
            elif isinstance(candidate, ast.Name) and isinstance(candidate.ctx, ast.Store):
                shadowed_names.add(candidate.id)
            elif isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
                shadowed_names.add(candidate.name)
                defined_function_names.add(candidate.name)
                for argument in candidate.args.args:
                    func_param_names.add(argument.arg)
            elif isinstance(candidate, ast.ClassDef):
                shadowed_names.add(candidate.name)

            targets: list[ast.AST] = []
            value: ast.AST | None = None
            if isinstance(candidate, ast.Assign):
                targets, value = candidate.targets, candidate.value
            elif isinstance(candidate, ast.AnnAssign):
                targets, value = [candidate.target], candidate.value
            elif isinstance(candidate, ast.NamedExpr):
                targets, value = [candidate.target], candidate.value
            elif isinstance(candidate, ast.AugAssign):
                targets = [candidate.target]
            target_names = {
                target.id for target in targets if isinstance(target, ast.Name)
            }
            shadowed_names.update(target_names)
            if value is not None:
                if _literal_only(value):
                    literal_bound_names.update(target_names)
                else:
                    unsafe_bound_names.update(target_names)
            elif target_names:
                unsafe_bound_names.update(target_names)

        safe_value_names = (
            (literal_bound_names - unsafe_bound_names)
            | safe_module_names
            | defined_function_names
            | func_param_names
        )

        safe_builtin_exceptions = {
            "BaseException", "Exception", "ValueError", "TypeError", "KeyError",
            "IndexError", "RuntimeError", "AssertionError", "AttributeError",
            "FileNotFoundError", "OSError", "ZeroDivisionError", "NotImplementedError",
            "StopIteration", "LookupError", "ArithmeticError", "NameError",
            "PermissionError", "TimeoutError", "UnicodeDecodeError", "UnicodeEncodeError",
        }
        safe_builtin_calls = {
            "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
            "len", "list", "max", "min", "print", "range", "repr", "round",
            "set", "sorted", "str", "sum", "tuple", "zip",
            *safe_builtin_exceptions,
        }
        safe_method_names = {
            "get", "strip", "lstrip", "rstrip", "lower", "upper", "split",
            "rsplit", "replace", "startswith", "endswith", "join", "encode",
            "decode", "count", "find", "index", "format",
            "start", "join", "is_alive", "wait", "set", "clear", "is_set",
            "write", "flush", "read", "hex", "digest", "hexdigest",
        }
        safe_module_calls = {
            ("sys", "stdout", "write"),
            ("sys", "stdout", "flush"),
            ("sys", "stderr", "write"),
            ("sys", "stderr", "flush"),
            ("sys", "stdout", "buffer", "write"),
            ("sys", "stdout", "buffer", "flush"),
            ("sys", "stderr", "buffer", "write"),
            ("sys", "stderr", "buffer", "flush"),
            ("sys", "exit"),
            ("os", "getenv"),
            ("os", "getcwd"),
            ("os", "environ", "get"),
            ("hashlib", "sha256"),
            ("hashlib", "sha1"),
            ("hashlib", "md5"),
            ("hashlib", "new"),
            ("time", "sleep"),
            ("time", "time"),
            ("time", "monotonic"),
            ("time", "perf_counter"),
            ("json", "dumps"),
            ("json", "loads"),
            ("threading", "Thread"),
            ("threading", "Lock"),
            ("threading", "RLock"),
            ("threading", "Event"),
            ("threading", "Semaphore"),
            ("threading", "current_thread"),
        }

        python_safety = PythonInlineCodeSafety(
            safe_builtin_calls=safe_builtin_calls,
            shadowed_names=shadowed_names,
            defined_function_names=defined_function_names,
            safe_module_calls=safe_module_calls,
            func_param_names=func_param_names,
            safe_method_names=safe_method_names,
            safe_module_names=safe_module_names,
            safe_value_names=safe_value_names,
        )
        python_safety.propagate_safe_values(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name in {"exec", "eval", "compile"}:
                    return {
                        "class": "dangerous",
                        "cacheable": False,
                        "allowed": False,
                        "reason": f"python -c inline code contains dangerous call: {func_name}",
                    }
                if func_name in {
                    "open", "remove", "unlink", "rmdir", "mkdir", "makedirs",
                    "rename", "replace", "system", "popen", "spawn", "kill",
                }:
                    return {
                        "class": "unknown",
                        "cacheable": False,
                        "allowed": bool(cfg.get("allow_unknown", False)),
                        "reason": f"python -c inline code may mutate: {func_name}",
                    }
                if func_name in {"write_text", "write_bytes", "touch"}:
                    return {
                        "class": "unknown",
                        "cacheable": False,
                        "allowed": bool(cfg.get("allow_unknown", False)),
                        "reason": f"python -c inline code may mutate files: {func_name}",
                    }
                if (
                    not python_safety.is_safe_call(node)
                    or not all(python_safety.is_safe_inline_value(arg) for arg in node.args)
                    or not all(
                        python_safety.is_safe_inline_value(keyword.value)
                        for keyword in node.keywords
                    )
                ):
                    return {
                        "class": "unknown",
                        "cacheable": False,
                        "allowed": bool(cfg.get("allow_unknown", False)),
                        "reason": (
                            "python -c inline code has unverified call: "
                            f"{func_name or 'dynamic'}"
                        ),
                    }
            elif isinstance(node, ast.Import):
                if any(
                    alias.name.split(".", 1)[0] not in safe_std_modules
                    for alias in node.names
                ):
                    return {
                        "class": "unknown",
                        "cacheable": False,
                        "allowed": bool(cfg.get("allow_unknown", False)),
                        "reason": "python -c inline code imports module with unknown side effects",
                    }
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".", 1)[0]
                if module not in safe_std_modules:
                    return {
                        "class": "unknown",
                        "cacheable": False,
                        "allowed": bool(cfg.get("allow_unknown", False)),
                        "reason": "python -c inline code imports module with unknown side effects",
                    }
            elif isinstance(node, (ast.Assert, ast.Raise)):
                is_validation = True

    except SyntaxError:
        return {
            "class": "unknown",
            "cacheable": False,
            "allowed": bool(cfg.get("allow_unknown", False)),
            "reason": "python -c inline code contains invalid syntax",
        }

    if not is_validation:
        tokens_in_code = set(re.findall(r"\b\w+\b", source_lower))
        validation_keywords = {
            "test", "validate", "check", "audit", "doctor", "selftest", "report", "assert",
        }
        if validation_keywords & tokens_in_code:
            is_validation = True

    if is_validation:
        return {
            "class": "validation",
            "cacheable": True,
            "allowed": bool(cfg.get("allow_validation", True)),
            "replay_safe": True,
            "reason": "python inline validation",
        }
    return {
        "class": "read",
        "cacheable": True,
        "allowed": bool(cfg.get("allow_read", True)),
        "reason": "python inline read",
    }


def _get_call_chain(func_node: ast.AST) -> tuple[str, ...] | None:
    parts = []
    curr = func_node
    while isinstance(curr, ast.Attribute):
        if curr.attr.startswith("_"):
            return None
        parts.append(curr.attr)
        curr = curr.value
    if isinstance(curr, ast.Name):
        parts.append(curr.id)
        return tuple(reversed(parts))
    return None


def _literal_only(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        return _literal_only(node.operand)
    if isinstance(node, ast.BinOp):
        return _literal_only(node.left) and _literal_only(node.right)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_literal_only(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _literal_only(key) and _literal_only(value)
            for key, value in zip(node.keys, node.values)
        )
    return False


class PythonInlineCodeSafety:
    """Classify safe calls and values in inline Python using caller-built names."""

    def __init__(
        self,
        *,
        safe_builtin_calls: set[str],
        shadowed_names: set[str],
        defined_function_names: set[str],
        safe_module_calls: set[tuple[str, ...]],
        func_param_names: set[str],
        safe_method_names: set[str],
        safe_module_names: set[str],
        safe_value_names: set[str],
    ) -> None:
        self.safe_builtin_calls = safe_builtin_calls
        self.shadowed_names = shadowed_names
        self.defined_function_names = defined_function_names
        self.safe_module_calls = safe_module_calls
        self.func_param_names = func_param_names
        self.safe_method_names = safe_method_names
        self.safe_module_names = safe_module_names
        self.safe_value_names = safe_value_names

    def is_safe_call(self, call_node: ast.Call) -> bool:
        if isinstance(call_node.func, ast.Name):
            func_name_id = call_node.func.id
            if func_name_id in self.safe_builtin_calls and func_name_id not in self.shadowed_names:
                return True
            if func_name_id in self.defined_function_names:
                return True
        elif isinstance(call_node.func, ast.Attribute):
            chain = _get_call_chain(call_node.func)
            if (
                chain
                and chain in self.safe_module_calls
                and chain[0] not in self.shadowed_names
                and chain[0] not in self.func_param_names
            ):
                return True
            if call_node.func.attr in self.safe_method_names and not call_node.func.attr.startswith("_"):
                if chain and chain[0] in self.safe_module_names:
                    return False
                if self.is_safe_inline_value(call_node.func.value):
                    return True
        return False

    def is_safe_inline_value(self, node: ast.AST) -> bool:
        if _literal_only(node):
            return True
        if isinstance(node, ast.Name):
            return node.id in self.safe_value_names
        if isinstance(node, ast.UnaryOp):
            return self.is_safe_inline_value(node.operand)
        if isinstance(node, ast.BinOp):
            return self.is_safe_inline_value(node.left) and self.is_safe_inline_value(node.right)
        if isinstance(node, ast.BoolOp):
            return all(self.is_safe_inline_value(value) for value in node.values)
        if isinstance(node, ast.Compare):
            return self.is_safe_inline_value(node.left) and all(
                self.is_safe_inline_value(comparator) for comparator in node.comparators
            )
        if isinstance(node, ast.IfExp):
            return (
                self.is_safe_inline_value(node.test)
                and self.is_safe_inline_value(node.body)
                and self.is_safe_inline_value(node.orelse)
            )
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return all(self.is_safe_inline_value(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return all(
                key is not None and self.is_safe_inline_value(key) and self.is_safe_inline_value(value)
                for key, value in zip(node.keys, node.values)
            )
        if isinstance(node, ast.Subscript):
            return self.is_safe_inline_value(node.value) and self.is_safe_inline_value(node.slice)
        if isinstance(node, ast.Call):
            return self.is_safe_call(node) and all(
                self.is_safe_inline_value(argument) for argument in node.args
            ) and all(self.is_safe_inline_value(keyword.value) for keyword in node.keywords)
        if isinstance(node, ast.Attribute):
            chain = _get_call_chain(node)
            if chain and chain[0] in self.safe_module_names:
                return True
            if self.is_safe_inline_value(node.value) and not node.attr.startswith("_"):
                return True
        return False

    def propagate_safe_values(self, tree: ast.AST) -> None:
        for _ in range(5):
            added = 0
            for candidate in ast.walk(tree):
                targets: list[ast.AST] = []
                value: ast.AST | None = None
                if isinstance(candidate, ast.Assign):
                    targets, value = candidate.targets, candidate.value
                elif isinstance(candidate, ast.AnnAssign):
                    targets, value = [candidate.target], candidate.value
                elif isinstance(candidate, ast.NamedExpr):
                    targets, value = [candidate.target], candidate.value
                elif isinstance(candidate, (ast.For, ast.AsyncFor)):
                    targets = [candidate.target]
                    value = candidate.iter
                if value is not None and self.is_safe_inline_value(value):
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in self.safe_value_names:
                            self.safe_value_names.add(target.id)
                            added += 1
            if not added:
                break
