"""Bounded, one-hop file admission for the partial code index."""

from __future__ import annotations

import ast
import json
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any


_JS_IMPORT = re.compile(
    r"\b(?:import|export)\s+(?:(?:type\s+)?[^;\n]*?\s+from\s*)?['\"](\.{1,2}/[^'\"]+)['\"]"
)
_JS_DYNAMIC_IMPORT = re.compile(
    r"\b(?:import|require)\s*\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)"
)
_PHP_INCLUDE = re.compile(
    r"\b(?:require|include)(?:_once)?\s*(?:\(\s*)?(?:(?P<dir>__DIR__)\s*\.\s*)?['\"](?P<path>(?:\.{1,2}/|/)[^'\"]+)['\"]\s*\)?"
)
_PHP_USE = re.compile(
    r"^\s*use\s+([\\a-zA-Z0-9_]+)", re.MULTILINE
)
_RUBY_REQUIRE_RELATIVE = re.compile(
    r"\brequire_relative\s*['\"]([^'\"]+)['\"]"
)
_C_INCLUDE = re.compile(
    r'^\s*#\s*include\s*["\']([^"\']+)["\']', re.MULTILINE
)
_RUST_MOD = re.compile(
    r"\b(?:pub\s+)?mod\s+([a-zA-Z0-9_]+)\s*;", re.MULTILINE
)
_RUST_USE_CRATE = re.compile(
    r"\buse\s+(?:crate|self|super)::([a-zA-Z0-9_:]+)", re.MULTILINE
)
_CS_USING = re.compile(
    r"^\s*using\s+([A-Za-z0-9_.]+)\s*;", re.MULTILINE
)
_CS_NAMESPACE = re.compile(
    r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.]*)\s*(?:;|\{)", re.MULTILINE
)
_JAVA_IMPORT = re.compile(
    r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.]+)\s*;", re.MULTILINE
)
_GO_IMPORT_BLOCK = re.compile(
    r"import\s*\((.*?)\)", re.DOTALL
)
_GO_SINGLE_IMPORT = re.compile(
    r'import\s+(?:[a-zA-Z0-9_.]+\s+)?"([^"]+)"'
)
_GO_STRINGS = re.compile(
    r'"([^"]+)"'
)

_JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json")
_C_EXTENSIONS = (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh")


def _safe_inventory_file(base: Path, path: str, repo_tools: Any) -> bool:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    if repo_tools is None:
        target = (base / Path(path)).resolve()
        try:
            target.relative_to(base.resolve())
            return target.is_file()
        except (ValueError, OSError):
            return False
    try:
        return bool(repo_tools._inventory_path_safe(base, base / Path(path)))
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        return False


def _build_eligible_path_index(eligible: set[str]) -> dict[str, Any]:
    """Index the bounded eligible inventory once for polyglot import lookups."""
    by_dir: dict[str, list[str]] = {}
    by_stem: dict[str, list[str]] = {}
    by_ext: dict[str, list[str]] = {}
    by_basename: dict[str, list[str]] = {}
    for path in sorted(eligible):
        parsed = PurePosixPath(path)
        parent = parsed.parent.as_posix()
        by_dir.setdefault("" if parent == "." else parent, []).append(path)
        by_stem.setdefault(parsed.stem, []).append(path)
        by_ext.setdefault(parsed.suffix.lower(), []).append(path)
        by_basename.setdefault(parsed.name, []).append(path)
    return {
        "by_dir": by_dir,
        "by_stem": by_stem,
        "by_ext": by_ext,
        "by_basename": by_basename,
        "by_csharp_namespace": None,
    }


def _resolve_relative_module(
    base: Path,
    seed: str,
    specifier: str,
    eligible: set[str],
    repo_tools: Any,
    *,
    extensions: tuple[str, ...],
) -> str | None:
    normalized = specifier.replace("\\", "/")
    if not normalized.startswith(("./", "../")) or normalized.startswith("/"):
        return None
    parent = PurePosixPath(seed).parent.as_posix()
    target = posixpath.normpath(posixpath.join(parent, normalized))
    pure_target = PurePosixPath(target)
    if pure_target.is_absolute() or ".." in pure_target.parts or target in ("", "."):
        return None
    candidates = [target]
    if pure_target.suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        stem = target[:-len(pure_target.suffix)]
        # TypeScript NodeNext source imports commonly retain the emitted .js
        # suffix. Prefer its TypeScript source counterpart when it is indexed,
        # even if a generated .js file is also eligible.
        ts_candidates = [stem + ext for ext in (".ts", ".tsx") if ext in extensions]
        ts_matches = list(dict.fromkeys(path for path in ts_candidates if path in eligible))
        if len(ts_matches) == 1:
            return ts_matches[0] if _safe_inventory_file(base, ts_matches[0], repo_tools) else None
        if len(ts_matches) > 1:
            return None
        candidates.extend(stem + ext for ext in extensions if ext not in {".js", ".jsx", ".mjs", ".cjs"})
    elif not pure_target.suffix:
        candidates.extend(target + extension for extension in extensions)
        candidates.extend(
            (PurePosixPath(target) / ("index" + extension)).as_posix()
            for extension in extensions
        )
    matches = list(dict.fromkeys(path for path in candidates if path in eligible))
    if len(matches) != 1:
        return None
    return matches[0] if _safe_inventory_file(base, matches[0], repo_tools) else None


def _python_import_candidates(seed: str, tree: ast.AST, eligible: set[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add_module(prefix: PurePosixPath, parts: list[str]) -> None:
        module = prefix.joinpath(*parts)
        if ".." in module.parts:
            return
        choices = [module.as_posix() + ".py", (module / "__init__.py").as_posix()]
        matches = [path for path in choices if path in eligible]
        if len(matches) != 1:
            return
        path = matches[0]
        if path != seed and path not in seen:
            seen.add(path)
            found.append(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in (PurePosixPath(), PurePosixPath("src")):
                    add_module(prefix, alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent = PurePosixPath(seed).parent
                for _ in range(node.level - 1):
                    if not parent.parts:
                        parent = PurePosixPath("..")
                        break
                    parent = parent.parent
                prefixes = (parent,)
            else:
                prefixes = (PurePosixPath(), PurePosixPath("src"))
            parts = node.module.split(".") if node.module else []
            for prefix in prefixes:
                if parts:
                    add_module(prefix, parts)
                for alias in node.names:
                    if alias.name != "*":
                        add_module(prefix, [*parts, alias.name])
    return found


def _go_import_candidates(
    base: Path, source: str, eligible: set[str], eligible_index: dict[str, Any] | None = None,
) -> list[str]:
    found: list[str] = []
    module_name = ""
    go_mod = base / "go.mod"
    if go_mod.is_file():
        try:
            for line in go_mod.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("module "):
                    module_name = line.strip().split()[1]
                    break
        except Exception:
            module_name = ""

    index = eligible_index if eligible_index is not None else _build_eligible_path_index(eligible)
    import_paths: list[str] = []
    for block in _GO_IMPORT_BLOCK.findall(source):
        import_paths.extend(_GO_STRINGS.findall(block))
    for single in _GO_SINGLE_IMPORT.findall(source):
        import_paths.append(single)

    for imp in import_paths:
        target_dir = ""
        if module_name and imp == module_name:
            matches = [path for path in index["by_dir"].get("", ()) if path.endswith(".go")]
            found.extend(matches)
        elif module_name and imp.startswith(module_name + "/"):
            target_dir = imp[len(module_name) + 1:].strip("/")
        elif imp.startswith("./") or imp.startswith("../"):
            target_dir = posixpath.normpath(imp)
        if target_dir:
            matches = [path for path in index["by_dir"].get(target_dir, ()) if path.endswith(".go")]
            found.extend(matches)
    return found


def _rust_import_candidates(seed: str, source: str, eligible: set[str]) -> list[str]:
    found: list[str] = []
    parent = PurePosixPath(seed).parent
    seed_stem = PurePosixPath(seed).stem
    for mod_match in _RUST_MOD.finditer(source):
        mod_name = mod_match.group(1)
        candidates = [
            (parent / f"{mod_name}.rs").as_posix(),
            (parent / mod_name / "mod.rs").as_posix(),
        ]
        if seed_stem not in ("lib", "main", "mod"):
            candidates.extend([
                (parent / seed_stem / f"{mod_name}.rs").as_posix(),
                (parent / seed_stem / mod_name / "mod.rs").as_posix(),
            ])
        for c in candidates:
            if c in eligible:
                found.append(c)

    for use_match in _RUST_USE_CRATE.finditer(source):
        parts = [p for p in use_match.group(1).split("::") if p]
        if parts:
            for prefix in (PurePosixPath("src"), parent):
                mod_path = prefix.joinpath(*parts).as_posix()
                candidates = [
                    mod_path + ".rs",
                    (prefix.joinpath(*parts) / "mod.rs").as_posix(),
                ]
                if len(parts) > 1:
                    mod_parent = prefix.joinpath(*parts[:-1]).as_posix()
                    candidates.append(mod_parent + ".rs")
                    candidates.append((prefix.joinpath(*parts[:-1]) / "mod.rs").as_posix())
                for c in candidates:
                    if c in eligible:
                        found.append(c)
    return found


def _c_include_candidates(
    base: Path, seed: str, source: str, eligible: set[str], repo_tools: Any,
    eligible_index: dict[str, Any] | None = None,
) -> list[str]:
    found: list[str] = []
    index = eligible_index if eligible_index is not None else _build_eligible_path_index(eligible)
    for match in _C_INCLUDE.finditer(source):
        specifier = match.group(1)
        res = _resolve_relative_module(base, seed, "./" + specifier if not specifier.startswith((".", "/")) else specifier, eligible, repo_tools, extensions=_C_EXTENSIONS)
        if res:
            found.append(res)
            continue
        # Check direct lookup in eligible
        for candidate in index["by_basename"].get(PurePosixPath(specifier).name, ()):
            if candidate.endswith("/" + specifier) or candidate == specifier:
                found.append(candidate)
    return found


def _ruby_require_candidates(base: Path, seed: str, source: str, eligible: set[str], repo_tools: Any) -> list[str]:
    found: list[str] = []
    for match in _RUBY_REQUIRE_RELATIVE.finditer(source):
        spec = match.group(1)
        res = _resolve_relative_module(base, seed, "./" + spec if not spec.startswith((".", "/")) else spec, eligible, repo_tools, extensions=(".rb",))
        if res:
            found.append(res)
    return found


def _csharp_using_candidates(
    base: Path, source: str, eligible: set[str], repo_tools: Any,
    eligible_index: dict[str, Any] | None = None,
) -> list[str]:
    imported_namespaces = {match.group(1) for match in _CS_USING.finditer(source)}
    if not imported_namespaces:
        return []
    index = eligible_index if eligible_index is not None else _build_eligible_path_index(eligible)
    namespace_index = index.get("by_csharp_namespace")
    if namespace_index is None:
        namespace_index = {}
        for candidate in index["by_ext"].get(".cs", ()):
            if not _safe_inventory_file(base, candidate, repo_tools):
                continue
            target = base / Path(candidate)
            try:
                if repo_tools is not None:
                    _, lines = repo_tools._read_snapshot(target)
                    candidate_source = "\n".join(lines)
                else:
                    candidate_source = target.read_text(encoding="utf-8", errors="replace")
            except (OSError, RuntimeError, UnicodeError, TypeError, ValueError, AttributeError):
                continue
            for match in _CS_NAMESPACE.finditer(candidate_source):
                namespace_index.setdefault(match.group(1), []).append(candidate)
        index["by_csharp_namespace"] = namespace_index
    return list(dict.fromkeys(
        candidate
        for namespace in sorted(imported_namespaces)
        for candidate in namespace_index.get(namespace, ())
    ))


def _java_import_candidates(
    source: str, eligible: set[str], eligible_index: dict[str, Any] | None = None,
) -> list[str]:
    found: list[str] = []
    index = eligible_index if eligible_index is not None else _build_eligible_path_index(eligible)
    for match in _JAVA_IMPORT.finditer(source):
        fqn = match.group(1)
        rel_path = fqn.replace(".", "/") + ".java"
        for c in index["by_stem"].get(PurePosixPath(rel_path).stem, ()):
            if c.endswith(rel_path):
                found.append(c)
    return found


def _php_psr4_map(base: Path) -> dict[str, tuple[str, ...]]:
    composer = base / "composer.json"
    try:
        if not composer.is_file() or composer.stat().st_size > 1_000_000:
            return {}
        data = json.loads(composer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    mapping: dict[str, tuple[str, ...]] = {}
    for autoload_name in ("autoload", "autoload-dev"):
        autoload = data.get(autoload_name, {}) if isinstance(data, dict) else {}
        psr4 = autoload.get("psr-4", {}) if isinstance(autoload, dict) else {}
        if not isinstance(psr4, dict):
            continue
        for namespace, directories in psr4.items():
            if not isinstance(namespace, str):
                continue
            values = directories if isinstance(directories, list) else [directories]
            paths = tuple(
                path.replace("\\", "/").strip("/")
                for path in values
                if isinstance(path, str) and path.strip()
            )
            if paths:
                key = namespace.lstrip("\\")
                mapping[key] = tuple(dict.fromkeys((*mapping.get(key, ()), *paths)))
    return mapping


def _php_psr4_candidates(
    namespace: str,
    mapping: dict[str, tuple[str, ...]],
    eligible: set[str],
    base: Path,
    repo_tools: Any,
) -> tuple[bool, list[str]]:
    name = namespace.lstrip("\\")
    prefixes = [prefix for prefix in mapping if name.startswith(prefix)]
    if not prefixes:
        return False, []

    prefix = max(prefixes, key=len)
    relative_class = name[len(prefix):].lstrip("\\").replace("\\", "/")
    if not relative_class:
        return True, []

    suffix = relative_class + ".php"
    found: list[str] = []
    for directory in mapping[prefix]:
        candidate = posixpath.normpath(posixpath.join(directory, suffix))
        if candidate in eligible and _safe_inventory_file(base, candidate, repo_tools):
            found.append(candidate)
    return True, list(dict.fromkeys(found))


def _index_eligible_paths_by_basename(eligible: set[str]) -> dict[str, list[str]]:
    by_basename: dict[str, list[str]] = {}
    for path in eligible:
        by_basename.setdefault(PurePosixPath(path).name, []).append(path)
    return by_basename


def _direct_import_candidates_for_seed(
    base: Path,
    seed: str,
    eligible: set[str],
    repo_tools: Any,
    ingest_cache: Any = None,
    eligible_by_basename: dict[str, list[str]] | None = None,
    eligible_index: dict[str, Any] | None = None,
) -> list[str]:
    if seed not in eligible or not _safe_inventory_file(base, seed, repo_tools):
        return []
    suffix = PurePosixPath(seed).suffix.lower()
    target = base / Path(seed)
    try:
        source: str | None = None
        tree: ast.AST | None = None
        if ingest_cache is not None and hasattr(ingest_cache, "get"):
            get_ast = getattr(ingest_cache, "get_with_ast", None) if suffix == ".py" else None
            ingested = (get_ast if callable(get_ast) else ingest_cache.get)(seed, root=str(base))
            if ingested is not None:
                source = getattr(ingested, "text", None)
                tree = getattr(ingested, "ast_tree", None)

        if source is None:
            _, lines = repo_tools._read_snapshot(target)
            source = "\n".join(lines)
        candidates: list[str] = []

        if suffix == ".py":
            py_tree = tree if tree is not None else ast.parse(source)
            candidates = _python_import_candidates(seed, py_tree, eligible)
        elif suffix in _JS_EXTENSIONS and suffix != ".json":
            specifiers = [match.group(1) for match in _JS_IMPORT.finditer(source)]
            specifiers.extend(match.group(1) for match in _JS_DYNAMIC_IMPORT.finditer(source))
            candidates = [
                path for specifier in specifiers
                if (path := _resolve_relative_module(
                    base, seed, specifier, eligible, repo_tools, extensions=_JS_EXTENSIONS,
                )) is not None
            ]
        elif suffix == ".php":
            psr4_mapping = _php_psr4_map(base)
            for match in _PHP_INCLUDE.finditer(source):
                specifier = match.group("path")
                if specifier.startswith("/"):
                    if not match.group("dir"):
                        continue
                    specifier = "." + specifier
                path = _resolve_relative_module(
                    base, seed, specifier, eligible, repo_tools, extensions=(".php",),
                )
                if path is not None:
                    candidates.append(path)
            for use_match in _PHP_USE.finditer(source):
                ns = use_match.group(1).lstrip("\\")
                mapped, mapped_candidates = _php_psr4_candidates(
                    ns, psr4_mapping, eligible, base, repo_tools,
                )
                if mapped:
                    candidates.extend(mapped_candidates)
                    continue
                parts = ns.split("\\")
                if parts:
                    class_file = parts[-1] + ".php"
                    rel_path = "/".join(parts) + ".php"
                    by_basename = eligible_by_basename
                    if by_basename is None:
                        by_basename = _index_eligible_paths_by_basename(eligible)
                    for el in by_basename.get(class_file, ()):
                        if el.endswith("/" + rel_path) or el == rel_path or el.endswith("/" + class_file):
                            candidates.append(el)
        elif suffix == ".go":
            candidates = _go_import_candidates(base, source, eligible, eligible_index)
        elif suffix == ".rs":
            candidates = _rust_import_candidates(seed, source, eligible)
        elif suffix in _C_EXTENSIONS:
            candidates = _c_include_candidates(base, seed, source, eligible, repo_tools, eligible_index)
        elif suffix == ".rb":
            candidates = _ruby_require_candidates(base, seed, source, eligible, repo_tools)
        elif suffix == ".cs":
            candidates = _csharp_using_candidates(base, source, eligible, repo_tools, eligible_index)
        elif suffix == ".java":
            candidates = _java_import_candidates(source, eligible, eligible_index)
        return candidates
    except (OSError, RuntimeError, UnicodeError, SyntaxError, TypeError, ValueError, RecursionError):
        return []


def one_hop_related_files(
    root: Path, seeds: list[str], eligible: set[str], repo_tools: Any, *, limit: int = 64, ingest_cache: Any = None
) -> list[str]:
    """Resolve bounded direct local imports without executing or recursing.

    Polyglot support: Python, JavaScript/TypeScript, PHP, Go, Rust, C/C++, C#, Java, Ruby.
    """
    if type(limit) is not int or limit < 1 or limit > 256:
        raise ValueError("limit must be an integer between 1 and 256")
    base = Path(root).resolve(strict=True)
    eligible_index = _build_eligible_path_index(eligible)
    found: list[str] = []
    seen = set(seeds)
    eligible_by_basename = (
        eligible_index["by_basename"]
        if any(seed in eligible and PurePosixPath(seed).suffix.lower() == ".php" for seed in seeds[:128])
        else None
    )

    for seed in seeds[:128]:
        if len(found) >= limit:
            break
        for path in _direct_import_candidates_for_seed(
            base, seed, eligible, repo_tools,
            ingest_cache=ingest_cache,
            eligible_by_basename=eligible_by_basename,
            eligible_index=eligible_index,
        ):
            if path not in seen and len(found) < limit:
                seen.add(path)
                found.append(path)
    return found


def _score_candidate_path(path: str) -> float:
    stem = PurePosixPath(path).stem
    if stem.startswith("I") and len(stem) > 1 and stem[1].isupper():
        return 1.5
    stem_lower = stem.lower()
    if any(k in stem_lower for k in ("interface", "base", "types", "protocol", "abstract")):
        return 1.4
    return 1.0


def two_hop_weighted_files(
    root: Path,
    seeds: list[str],
    eligible: set[str],
    repo_tools: Any,
    *,
    limit: int = 64,
    hop1_limit: int = 32,
    decay: float = 0.5,
    ingest_cache: Any = None,
) -> list[tuple[str, float]]:
    """Resolve 2-hop local imports with depth decay and interface/base class weights."""
    if type(limit) is not int or limit < 1 or limit > 256:
        raise ValueError("limit must be an integer between 1 and 256")
    base = Path(root).resolve(strict=True)
    eligible_index = _build_eligible_path_index(eligible)
    weights: dict[str, float] = {}
    seeds_set = set(seeds)
    eligible_by_basename = (
        eligible_index["by_basename"]
        if any(seed in eligible and PurePosixPath(seed).suffix.lower() == ".php" for seed in seeds[:128])
        else None
    )

    # Hop 1
    for seed in seeds[:128]:
        candidates = _direct_import_candidates_for_seed(
            base, seed, eligible, repo_tools,
            ingest_cache=ingest_cache,
            eligible_by_basename=eligible_by_basename,
            eligible_index=eligible_index,
        )
        for cand in candidates:
            if cand in seeds_set:
                continue
            score = _score_candidate_path(cand)
            weights[cand] = max(weights.get(cand, 0.0), score)

    # Hop 2
    hop1_sorted = sorted(weights.keys(), key=lambda p: (-weights[p], p))[:hop1_limit]
    if eligible_by_basename is None and any(
        PurePosixPath(path).suffix.lower() == ".php" for path in hop1_sorted
    ):
        eligible_by_basename = eligible_index["by_basename"]
    for h1_file in hop1_sorted:
        h1_weight = weights[h1_file]
        h2_candidates = _direct_import_candidates_for_seed(
            base, h1_file, eligible, repo_tools,
            ingest_cache=ingest_cache,
            eligible_by_basename=eligible_by_basename,
            eligible_index=eligible_index,
        )
        for h2_cand in h2_candidates:
            if h2_cand in seeds_set:
                continue
            h2_score = _score_candidate_path(h2_cand) * h1_weight * decay
            weights[h2_cand] = max(weights.get(h2_cand, 0.0), h2_score)

    ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:limit]


def two_hop_related_files(
    root: Path,
    seeds: list[str],
    eligible: set[str],
    repo_tools: Any,
    *,
    limit: int = 64,
    hop1_limit: int = 32,
    decay: float = 0.5,
    ingest_cache: Any = None,
) -> list[str]:
    """Resolve 2-hop local imports, returning ranked unique file paths."""
    weighted = two_hop_weighted_files(
        root, seeds, eligible, repo_tools, limit=limit, hop1_limit=hop1_limit, decay=decay, ingest_cache=ingest_cache
    )
    return [p for p, _ in weighted]
