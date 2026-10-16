"""treesitter_parser.py — Tree-Sitter AST symbol and reference extractor.

Provides robust, syntax-aware AST extraction for C#, TypeScript/TSX,
JavaScript, Python, Go, and Rust. Falls back when grammars are missing.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PARSERS: dict[str, Any] = {}
_LANGUAGES: dict[str, Any] = {}
_INIT_ATTEMPTED = False
_PARSER_LOCK = threading.RLock()
_LAZY_LANGUAGE_PACKS = {"java": "java", "cpp": "cpp"}

_IN_WORKER = False
_WORKER_POOL: ProcessPoolExecutor | None = None
_WORKER_POOL_LOCK = threading.Lock()
_WORKER_DISPATCH_LOCK = threading.Lock()
_WORKER_DISABLED_CAUSE: str | None = None
_WER_FAULT_REPORTING_NO_UI = 0x0020
_WER_ERROR_NOT_FOUND_HRESULT = 0x80070490
_TREE_CACHE: OrderedDict[tuple[str, str], tuple[bytes, Any, int]] = OrderedDict()
_TREE_CACHE_BYTES = 0
_TREE_CACHE_MAX_ENTRIES = 32
_TREE_CACHE_MAX_BYTES = 8 * 1024 * 1024
_TREE_CACHE_MAX_SOURCE_BYTES = 2 * 1024 * 1024


def _discard_tree(source_key: str | None, language: str) -> None:
    global _TREE_CACHE_BYTES
    previous = _TREE_CACHE.pop((source_key, language), None)
    if previous is not None:
        _TREE_CACHE_BYTES -= len(previous[0])


def _byte_point(source: bytes, offset: int) -> tuple[int, int]:
    return source.count(b"\n", 0, offset), offset - source.rfind(b"\n", 0, offset) - 1


def _source_edit(before: bytes, after: bytes) -> dict[str, Any]:
    """Describe one contiguous UTF-8 edit; points use byte columns, not characters."""
    start, shared = 0, min(len(before), len(after))
    while start + 4096 <= shared and before[start:start + 4096] == after[start:start + 4096]:
        start += 4096
    while start < shared and before[start] == after[start]:
        start += 1
    old_end, new_end = len(before), len(after)
    while old_end - start >= 4096 and new_end - start >= 4096 and before[old_end - 4096:old_end] == after[new_end - 4096:new_end]:
        old_end -= 4096
        new_end -= 4096
    while old_end > start and new_end > start and before[old_end - 1] == after[new_end - 1]:
        old_end -= 1
        new_end -= 1
    while start > 0 and ((start < len(before) and before[start] & 0xC0 == 0x80)
                         or (start < len(after) and after[start] & 0xC0 == 0x80)):
        start -= 1
    while old_end < len(before) and new_end < len(after) and before[old_end] & 0xC0 == 0x80:
        old_end += 1
        new_end += 1
    return {"start_byte": start, "old_end_byte": old_end, "new_end_byte": new_end,
            "start_point": _byte_point(before, start), "old_end_point": _byte_point(before, old_end),
            "new_end_point": _byte_point(after, new_end)}


def _parse_tree(parser: Any, source: bytes, language: str, source_key: str | None) -> tuple[Any, dict[str, Any]]:
    """Use worker-local native Trees; caller holds _PARSER_LOCK for the whole walk."""
    global _TREE_CACHE_BYTES
    key = (source_key, language) if isinstance(source_key, str) and 0 < len(source_key) <= 256 else None
    previous = _TREE_CACHE.pop(key, None) if key is not None else None
    if previous is not None:
        _TREE_CACHE_BYTES -= len(previous[0])
    report: dict[str, Any] = {"incremental": False, "tree_cache_hit": previous is not None}
    tree = None
    if previous is not None and previous[2] == id(parser):
        old_source, old_tree, _ = previous
        if old_source == source:
            tree = old_tree
            report.update(incremental=True, tree_reused=True)
        else:
            try:
                edit = _source_edit(old_source, source)
                old_tree.edit(**edit)
                tree = parser.parse(source, old_tree)
                if tree is None:
                    raise RuntimeError("incremental parser returned no tree")
                report.update(incremental=True, edit=edit)
            except Exception as exc:
                # An edited tree must never be retained after an unsuccessful parse.
                report["incremental_fallback"] = type(exc).__name__
                reset = getattr(parser, "reset", None)
                if callable(reset):
                    try:
                        reset()
                    except Exception:
                        pass
    if tree is None:
        tree = parser.parse(source)
        if tree is None:
            raise RuntimeError("parser returned no tree")
    if key is not None and len(source) <= _TREE_CACHE_MAX_SOURCE_BYTES:
        _TREE_CACHE[key] = (source, tree, id(parser))
        _TREE_CACHE_BYTES += len(source)
        while len(_TREE_CACHE) > _TREE_CACHE_MAX_ENTRIES or _TREE_CACHE_BYTES > _TREE_CACHE_MAX_BYTES:
            _, discarded = _TREE_CACHE.popitem(last=False)
            _TREE_CACHE_BYTES -= len(discarded[0])
    return tree, report


def _get_worker_pool() -> ProcessPoolExecutor:
    global _WORKER_POOL
    with _WORKER_POOL_LOCK:
        if _WORKER_DISABLED_CAUSE is not None:
            raise RuntimeError("isolated Tree-sitter worker is disabled")
        if _WORKER_POOL is None:
            _WORKER_POOL = ProcessPoolExecutor(
                max_workers=1,
                initializer=_initialize_isolated_worker,
            )
        return _WORKER_POOL


def _load_worker_windows_api() -> Any:
    import ctypes

    return ctypes.WinDLL("kernel32", use_last_error=True)


def _worker_runtime_is_windows() -> bool:
    return os.name == "nt"


def _initialize_isolated_worker() -> None:
    """Disable fault-dialog UI in this worker before loading native parsers."""
    if not _worker_runtime_is_windows():
        return

    import ctypes

    api = _load_worker_windows_api()
    handle_type = ctypes.c_void_p
    dword_type = ctypes.c_uint32
    hresult_type = ctypes.c_int32

    # Cover critical-error and general-protection dialogs as well as WER UI.
    # This initializer runs only in the owned worker; parent/operator flags
    # stay untouched, and existing child error-mode bits remain set.
    get_error_mode = api.GetErrorMode
    get_error_mode.argtypes = []
    get_error_mode.restype = dword_type
    set_error_mode = api.SetErrorMode
    set_error_mode.argtypes = [dword_type]
    set_error_mode.restype = dword_type
    set_error_mode(get_error_mode() | 0x0001 | 0x0002)

    get_current_process = api.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = handle_type
    process = get_current_process()
    if not process:
        raise OSError("GetCurrentProcess returned a null process handle")

    get_flags = api.WerGetFlags
    get_flags.argtypes = [handle_type, ctypes.POINTER(dword_type)]
    get_flags.restype = hresult_type
    flags = dword_type()
    result = get_flags(process, ctypes.byref(flags))
    if result < 0:
        hresult = result & 0xFFFFFFFF
        if hresult != _WER_ERROR_NOT_FOUND_HRESULT:
            raise OSError(f"WerGetFlags failed with HRESULT 0x{hresult:08X}")
        flags.value = 0

    set_flags = api.WerSetFlags
    set_flags.argtypes = [dword_type]
    set_flags.restype = hresult_type
    updated_flags = flags.value | _WER_FAULT_REPORTING_NO_UI
    result = set_flags(updated_flags)
    if result < 0:
        raise OSError(f"WerSetFlags failed with HRESULT 0x{result & 0xFFFFFFFF:08X}")


def _disable_worker_pool(cause: str) -> bool:
    """Trip the process-lifetime breaker before attempting worker cleanup."""
    global _WORKER_DISABLED_CAUSE
    with _WORKER_POOL_LOCK:
        if _WORKER_DISABLED_CAUSE is None:
            _WORKER_DISABLED_CAUSE = cause
    return _reset_worker_pool()


def _worker_disabled_result() -> dict[str, Any] | None:
    with _WORKER_POOL_LOCK:
        cause = _WORKER_DISABLED_CAUSE
    if cause is None:
        return None
    return {
        "result": None,
        "status": "unavailable",
        "fallback_reason": "worker_disabled",
        "worker_disabled_cause": cause,
        "syntax_error_count": 0,
    }


def _reset_worker_pool() -> bool:
    global _WORKER_POOL
    with _WORKER_POOL_LOCK:
        pool = _WORKER_POOL
        _WORKER_POOL = None
        if pool is None:
            return True
        confirmed = True
        try:
            workers = list(dict(getattr(pool, "_processes", None) or {}).values())
        except Exception:
            workers = []
            confirmed = False
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            confirmed = False
        for worker in workers:
            try:
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=0.5)
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=0.5)
                confirmed = not worker.is_alive() and confirmed
            except Exception:
                confirmed = False
        return confirmed


def _use_isolated_worker() -> bool:
    return os.name == "nt" and sys.version_info >= (3, 13)


def _init_treesitter() -> bool:
    with _PARSER_LOCK:
        return _init_treesitter_once()


def _init_treesitter_once() -> bool:
    global _INIT_ATTEMPTED
    if _INIT_ATTEMPTED:
        return bool(_PARSERS)
    _INIT_ATTEMPTED = True

    # A supervised Windows/Python 3.13 process crashed in native Node.children
    # traversal even with language-pack parsing serialized by _PARSER_LOCK.
    # The language pack is not a safe escape from the native binding guard.
    # When running outside of an isolated worker on Windows Python 3.13+, fall back
    # so access violations in native code cannot take down the Hub daemon.
    if not _IN_WORKER and _use_isolated_worker():
        logger.warning("Tree-sitter disabled in main process on Windows Python 3.13+; isolated worker pool will be used")
        return False

    try:
        import tree_sitter_language_pack as tslp
        mapping = {
            "csharp": "c_sharp",
            "typescript": "typescript",
            "tsx": "tsx",
            "javascript": "javascript",
            "python": "python",
            "go": "go",
            "rust": "rust",
            "java": "java",
            "cpp": "cpp",
        }
        for internal_key, tslp_key in mapping.items():
            try:
                if tslp.has_language(tslp_key):
                    _LANGUAGES[internal_key] = tslp.get_language(tslp_key)
                    _PARSERS[internal_key] = tslp.get_parser(tslp_key)
            except Exception as e:
                logger.debug("Failed loading %s via tree_sitter_language_pack: %s", tslp_key, e)
        if _PARSERS:
            return True
    except Exception as exc:
        logger.debug("tree_sitter_language_pack unavailable: %s", exc)

    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return False

    # C#
    try:
        import tree_sitter_c_sharp as tscs
        lang = Language(tscs.language())
        _LANGUAGES["csharp"] = lang
        _PARSERS["csharp"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter C# grammar unavailable: %s", exc)

    # TypeScript
    try:
        import tree_sitter_typescript as tsts
        lang_ts = Language(tsts.language_typescript())
        _LANGUAGES["typescript"] = lang_ts
        _PARSERS["typescript"] = Parser(lang_ts)
        lang_tsx = Language(tsts.language_tsx())
        _LANGUAGES["tsx"] = lang_tsx
        _PARSERS["tsx"] = Parser(lang_tsx)
    except Exception as exc:
        logger.debug("Tree-sitter TypeScript grammar unavailable: %s", exc)

    # JavaScript
    try:
        import tree_sitter_javascript as tsjs
        lang = Language(tsjs.language())
        _LANGUAGES["javascript"] = lang
        _PARSERS["javascript"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter JavaScript grammar unavailable: %s", exc)

    # Python
    try:
        import tree_sitter_python as tspy
        lang = Language(tspy.language())
        _LANGUAGES["python"] = lang
        _PARSERS["python"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter Python grammar unavailable: %s", exc)

    # Go
    try:
        import tree_sitter_go as tsgo
        lang = Language(tsgo.language())
        _LANGUAGES["go"] = lang
        _PARSERS["go"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter Go grammar unavailable: %s", exc)

    # Rust
    try:
        import tree_sitter_rust as tsrs
        lang = Language(tsrs.language())
        _LANGUAGES["rust"] = lang
        _PARSERS["rust"] = Parser(lang)
    except Exception as exc:
        logger.debug("Tree-sitter Rust grammar unavailable: %s", exc)

    return bool(_PARSERS)


def _load_lazy_language_pack(language: str) -> bool:
    pack_language = _LAZY_LANGUAGE_PACKS.get(language)
    if not pack_language:
        return False
    with _PARSER_LOCK:
        if language in _PARSERS:
            return True
        try:
            import tree_sitter_language_pack as tslp

            if not tslp.has_language(pack_language):
                return False
            parsed_language = tslp.get_language(pack_language)
            parser = tslp.get_parser(pack_language)
        except Exception as exc:
            logger.debug("Tree-sitter %s grammar unavailable: %s", pack_language, exc)
            return False
        _LANGUAGES[language] = parsed_language
        _PARSERS[language] = parser
        return True


_KNOWN_LANGUAGES = {
    "csharp": "csharp", "cs": "csharp",
    "typescript": "typescript", "ts": "typescript",
    "tsx": "tsx",
    "javascript": "javascript", "js": "javascript", "jsx": "javascript",
    "python": "python", "py": "python",
    "go": "go", "golang": "go",
    "rust": "rust", "rs": "rust",
    "java": "java",
    "cpp": "cpp", "c++": "cpp", "c": "cpp",
}
_KNOWN_EXTENSIONS = (
    ".c", ".cc", ".cpp", ".cs", ".cxx", ".go", ".h", ".hpp",
    ".java", ".js", ".jsx", ".py", ".rs", ".ts", ".tsx",
)


def supported_languages() -> list[str]:
    return sorted(set(_KNOWN_LANGUAGES.values()))


def is_supported_language(lang: Any) -> bool:
    if not isinstance(lang, str):
        return False
    norm = lang.replace("\x00", "").strip().lower()
    return norm in _KNOWN_LANGUAGES


def supported_extensions() -> list[str]:
    return sorted(_KNOWN_EXTENSIONS)


def is_treesitter_available(lang: str) -> bool:
    if not isinstance(lang, str):
        return False
    norm = lang.replace("\x00", "").strip().lower()
    if not norm:
        return False
    if not _INIT_ATTEMPTED:
        _init_treesitter()
    lazy_language = "cpp" if norm in ("c++", "c") else norm
    if lazy_language in _LAZY_LANGUAGE_PACKS:
        _load_lazy_language_pack(lazy_language)
    if norm in ("cs", "csharp"):
        return "csharp" in _PARSERS
    if norm in ("ts", "typescript"):
        return "typescript" in _PARSERS
    if norm == "tsx":
        return "tsx" in _PARSERS or "typescript" in _PARSERS
    if norm in ("js", "javascript", "jsx"):
        return "javascript" in _PARSERS
    if norm in ("py", "python"):
        return "python" in _PARSERS
    if norm in ("go", "golang"):
        return "go" in _PARSERS
    if norm in ("rs", "rust"):
        return "rust" in _PARSERS
    if norm == "java":
        return "java" in _PARSERS
    if norm in ("cpp", "c++", "c"):
        return "cpp" in _PARSERS
    return False


def language_for_path(path: str, fallback_language: str, settings: Any | None = None) -> str:
    """Resolve project-configured extensions to parser language names."""
    fallback = str(fallback_language or "").strip().lower()
    if not isinstance(path, (str, Path)):
        return fallback
    try:
        clean_path = str(path).replace("\x00", "").strip()
        if not clean_path:
            return fallback
        suffix = Path(clean_path).suffix.lower()
    except Exception:
        return fallback
    overrides = getattr(settings, "language_overrides", {}) if settings is not None else {}
    if isinstance(overrides, dict) or hasattr(overrides, "items"):
        for language, override in overrides.items():
            extensions = override.get("text_extensions", ()) if hasattr(override, "get") else ()
            if suffix in {str(extension).lower() for extension in extensions}:
                return str(language).strip().lower()
    return fallback


def parse_treesitter(
    text: str, language: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Return syntax data while retaining the tuple API."""
    return parse_treesitter_with_status(text, language)["result"]


def _parse_treesitter_internal(text: str, language: str, *, source_key: str | None = None) -> dict[str, Any]:
    """Internal synchronous parser execution."""
    if not text or not text.strip():
        return {"result": ([], [], []), "status": "empty", "parser": "tree_sitter", "syntax_error_count": 0}

    if not _INIT_ATTEMPTED:
        _init_treesitter()

    norm = language.lower().strip()
    key = {
        "cs": "csharp", "csharp": "csharp",
        "ts": "typescript", "typescript": "typescript",
        "tsx": "tsx" if "tsx" in _PARSERS else "typescript",
        "js": "javascript", "jsx": "javascript", "javascript": "javascript",
        "py": "python", "python": "python",
        "go": "go", "golang": "go",
        "rs": "rust", "rust": "rust",
        "java": "java", "cpp": "cpp", "c++": "cpp",
    }.get(norm)

    if key in _LAZY_LANGUAGE_PACKS and key not in _PARSERS:
        _load_lazy_language_pack(key)

    if not key or key not in _PARSERS:
        return {"result": None, "status": "unavailable", "parser": "tree_sitter", "fallback_reason": "parser_unavailable", "syntax_error_count": 0}

    parser = _PARSERS[key]
    source_bytes = text.encode("utf-8", errors="replace")
    # Keep native parsing, syntax walk and extraction in one critical section.
    with _PARSER_LOCK:
        try:
            # Parser instances are mutable in the native Tree-sitter bindings and are
            # shared per language. Serialize calls so concurrent preprocessing cannot
            # corrupt parser state and crash the Python process.
            tree, incremental = _parse_tree(parser, source_bytes, key, source_key)
        except Exception as exc:
            logger.debug("Tree-sitter parse failed for %s: %s", language, exc)
            return {"result": None, "status": "failed", "parser": key, "fallback_reason": "parser_error", "error_type": type(exc).__name__, "syntax_error_count": 0}

        lines = text.splitlines()
        root = tree.root_node
        has_syntax_errors = bool(getattr(root, "has_error", False))
        error_count = 0
        error_count_truncated = False
        if has_syntax_errors:
            pending = [root]
            visited = 0
            while pending and visited < 10000:
                node = pending.pop()
                visited += 1
                if bool(getattr(node, "is_error", False)) or bool(getattr(node, "is_missing", False)):
                    error_count += 1
                    if error_count >= 64:
                        error_count_truncated = bool(pending or getattr(node, "child_count", 0))
                        break
                try:
                    pending.extend(reversed(node.children))
                except Exception:
                    continue
            if pending and visited >= 10000:
                error_count_truncated = True
            # Tree-sitter reports root.has_error for recovery cases where a grammar
            # does not expose an explicit ERROR or missing node in the bounded walk.
            if error_count == 0:
                error_count = 1
                error_count_truncated = True

        try:
            if key == "csharp":
                result = _extract_csharp(root, lines, source_bytes)
            elif key in ("typescript", "tsx", "javascript"):
                result = _extract_js_ts(root, lines, source_bytes)
            elif key == "python":
                result = _extract_python(root, lines, source_bytes)
            elif key == "go":
                result = _extract_go(root, lines, source_bytes)
            elif key == "rust":
                result = _extract_rust(root, lines, source_bytes)
            elif key == "java":
                result = _extract_java(root, lines, source_bytes)
            elif key == "cpp":
                result = _extract_cpp(root, lines, source_bytes)
            else:
                return {"result": None, "status": "unavailable", "parser": key, "fallback_reason": "parser_unavailable", "syntax_error_count": 0}
        except Exception as exc:
            logger.debug("Tree-sitter extraction failed for %s: %s", language, exc)
            _discard_tree(source_key, key)
            return {"result": None, "status": "failed", "parser": key, "fallback_reason": "parser_error", "error_type": type(exc).__name__, "syntax_error_count": 0}

        return {
            "result": result,
            "status": "syntax_error" if has_syntax_errors else "ok",
            "parser": key,
            "syntax_error_count": error_count,
            "syntax_error_count_truncated": error_count_truncated,
            **incremental,
        }


def _worker_parse(text: str, language: str, source_key: str | None = None) -> dict[str, Any]:
    """Entrypoint executed in isolated worker subprocess."""
    global _IN_WORKER, _INIT_ATTEMPTED
    if not _IN_WORKER:
        _IN_WORKER = True
        _INIT_ATTEMPTED = False
    _init_treesitter()
    try:
        return (_parse_treesitter_internal(text, language, source_key=source_key)
                if source_key is not None else _parse_treesitter_internal(text, language))
    except Exception as exc:
        return {
            "result": None,
            "status": "failed",
            "fallback_reason": "worker_error",
            "error_type": type(exc).__name__,
            "syntax_error_count": 0,
        }


def parse_treesitter_with_status(text: str, language: str, *, source_key: str | None = None) -> dict[str, Any]:
    """Return extracted syntax data and an explicit, bounded parser outcome."""
    if not isinstance(text, str) or not text.strip():
        return {"result": ([], [], []), "status": "empty", "parser": "tree_sitter", "syntax_error_count": 0}
    if not isinstance(language, str) or not language.replace("\x00", "").strip():
        return {"result": None, "status": "unavailable", "parser": "tree_sitter", "fallback_reason": "invalid_language", "syntax_error_count": 0}

    disabled = _worker_disabled_result()
    if disabled is not None:
        return disabled

    if _use_isolated_worker():
        if not _WORKER_DISPATCH_LOCK.acquire(timeout=12.0):
            disabled = _worker_disabled_result()
            if disabled is not None:
                return disabled
            return {
                "result": None,
                "status": "failed",
                "fallback_reason": "worker_dispatch_busy",
                "syntax_error_count": 0,
            }
        try:
            disabled = _worker_disabled_result()
            if disabled is not None:
                return disabled
            pool = _get_worker_pool()
            future = (pool.submit(_worker_parse, text, language, source_key)
                      if source_key is not None else pool.submit(_worker_parse, text, language))
            result = future.result(timeout=10.0)
            if isinstance(result, dict) and result.get("fallback_reason") == "worker_error":
                cleanup = _disable_worker_pool(
                    f"worker_error:{result.get('error_type', 'unknown')}"
                )
                result["worker_cleanup_confirmed"] = cleanup
            return result
        except BrokenProcessPool as exc:
            logger.warning("Tree-sitter worker pool broke: %s", exc)
            cleanup = _disable_worker_pool(f"worker_crash:{type(exc).__name__}")
            return {
                "result": None,
                "status": "failed",
                "fallback_reason": "worker_crash",
                "worker_cleanup_confirmed": cleanup,
                "error_type": type(exc).__name__,
                "syntax_error_count": 0,
            }
        except TimeoutError as exc:
            logger.warning("Tree-sitter worker timed out: %s", exc)
            cleanup = _disable_worker_pool(f"worker_timeout:{type(exc).__name__}")
            return {
                "result": None,
                "status": "failed",
                "fallback_reason": "worker_timeout",
                "worker_cleanup_confirmed": cleanup,
                "error_type": type(exc).__name__,
                "syntax_error_count": 0,
            }
        except Exception as exc:
            logger.warning("Tree-sitter worker execution failed: %s", exc)
            cleanup = _disable_worker_pool(f"worker_error:{type(exc).__name__}")
            return {
                "result": None,
                "status": "failed",
                "fallback_reason": "worker_error",
                "error_type": type(exc).__name__,
                "worker_cleanup_confirmed": cleanup,
                "syntax_error_count": 0,
            }
        finally:
            _WORKER_DISPATCH_LOCK.release()

    return (_parse_treesitter_internal(text, language, source_key=source_key)
            if source_key is not None else _parse_treesitter_internal(text, language))


def _node_text(node: Any, source_bytes: bytes) -> str:
    if node is None:
        return ""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _first_line_sig(node: Any, lines: list[str]) -> str:
    # Use tuple access for native Points. In tree-sitter 0.26.0 the row/column
    # property getters return borrowed references, corrupting larger row ints.
    start_row = node.start_point[0]
    if 0 <= start_row < len(lines):
        line = lines[start_row].strip()
        # strip trailing open brace
        return re.sub(r"\s*\{?\s*$", "", line)[:120]
    return ""


def _extract_csharp(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    stack: list[str] = []
    curr_namespace = ""

    def visit(node: Any) -> None:
        nonlocal curr_namespace
        ntype = node.type

        if ntype == "using_directive":
            target = ""
            for c in node.children:
                if c.type in ("qualified_name", "identifier"):
                    target = _node_text(c, source_bytes)
                    break
            if not target:
                name_node = node.child_by_field_name("name")
                if name_node:
                    target = _node_text(name_node, source_bytes)
            if target:
                edges.append({
                    "src": "<module>",
                    "dst": target,
                    "kind": "imports",
                    "line": node.start_point[0] + 1,
                })
            return

        if ntype == "namespace_declaration" or ntype == "file_scoped_namespace_declaration":
            ns_name_node = node.child_by_field_name("name")
            if ns_name_node:
                curr_namespace = _node_text(ns_name_node, source_bytes)
            for child in node.children:
                if child.type != "name":
                    visit(child)
            return

        is_type_decl = ntype in (
            "class_declaration", "interface_declaration", "struct_declaration",
            "enum_declaration", "record_declaration",
        )
        if is_type_decl:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                kind = ntype.replace("_declaration", "")
                container = "/".join(filter(None, [curr_namespace] + stack))
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                # Inheritance
                base_list = next((c for c in node.children if c.type == "base_list"), None)
                if base_list:
                    base_str = _node_text(base_list, source_bytes).lstrip(":").strip()
                    for base_item in base_str.split(","):
                        bname = base_item.strip().split("<")[0].strip()
                        if bname:
                            edges.append({
                                "src": name_path,
                                "dst": bname,
                                "kind": "inherits",
                                "line": node.start_point[0] + 1,
                            })

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(filter(None, [curr_namespace] + stack))
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "method" if stack else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })
                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype == "property_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(filter(None, [curr_namespace] + stack))
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "property",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

        if ntype == "invocation_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point[0] + 1,
                        "kind": "call",
                    })
                    curr_scope = "/".join(filter(None, [curr_namespace] + stack)) or "<module>"
                    edges.append({
                        "src": curr_scope,
                        "dst": leaf_name,
                        "kind": "calls",
                        "line": node.start_point[0] + 1,
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_java(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    containers: list[str] = []
    current_function = ""
    type_kinds = {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
    }

    def visit(node: Any) -> None:
        nonlocal current_function
        ntype = node.type

        if ntype in type_kinds:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(containers)
                name_path = f"{container}/{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": type_kinds[ntype],
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                containers.append(name)
                for child in node.children:
                    visit(child)
                containers.pop()
                return

        if ntype in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(containers)
                name_path = f"{container}/{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": "constructor" if ntype == "constructor_declaration" else "method",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                previous_function = current_function
                current_function = name_path
                for child in node.children:
                    visit(child)
                current_function = previous_function
                return

        if ntype == "method_invocation":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name and re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                refs.append({"name": name, "line": node.start_point[0] + 1, "kind": "call"})
                edges.append({
                    "src": current_function or "<module>",
                    "dst": name,
                    "kind": "calls",
                    "line": node.start_point[0] + 1,
                })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _cpp_declarator_name(node: Any, source_bytes: bytes) -> str:
    if node.type in ("identifier", "field_identifier", "operator_name"):
        return _node_text(node, source_bytes)
    if node.type == "qualified_identifier":
        name_node = node.child_by_field_name("name")
        return _cpp_declarator_name(name_node, source_bytes) if name_node else _node_text(node, source_bytes).split("::")[-1]
    declarator = node.child_by_field_name("declarator")
    if declarator:
        return _cpp_declarator_name(declarator, source_bytes)
    for child in node.children:
        name = _cpp_declarator_name(child, source_bytes)
        if name:
            return name
    return ""


def _extract_cpp(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    containers: list[str] = []
    class_containers: list[str] = []
    current_function = ""
    container_kinds = {
        "namespace_definition": "namespace",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
    }

    def visit(node: Any) -> None:
        nonlocal current_function
        ntype = node.type

        if ntype in container_kinds:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "::".join(containers)
                name_path = f"{container}::{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": container_kinds[ntype],
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                containers.append(name)
                if ntype in ("class_specifier", "struct_specifier"):
                    class_containers.append(name)
                for child in node.children:
                    visit(child)
                if ntype in ("class_specifier", "struct_specifier"):
                    class_containers.pop()
                containers.pop()
                return

        if ntype == "function_definition":
            declarator = node.child_by_field_name("declarator")
            name = _cpp_declarator_name(declarator, source_bytes) if declarator else ""
            if name:
                container = "::".join(containers)
                name_path = f"{container}::{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": "method" if class_containers else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                previous_function = current_function
                current_function = name_path
                for child in node.children:
                    visit(child)
                current_function = previous_function
                return

        if ntype == "call_expression":
            function_node = node.child_by_field_name("function")
            call_text = _node_text(function_node, source_bytes) if function_node else ""
            name = re.split(r"::|->|\.", call_text)[-1]
            if name and re.fullmatch(r"[A-Za-z_][\w]*", name):
                refs.append({"name": name, "line": node.start_point[0] + 1, "kind": "call"})
                edges.append({
                    "src": current_function or "<module>",
                    "dst": name,
                    "kind": "calls",
                    "line": node.start_point[0] + 1,
                })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_js_ts(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    stack: list[str] = []

    def visit(node: Any) -> None:
        ntype = node.type

        if ntype == "import_statement":
            src_node = node.child_by_field_name("source")
            if src_node:
                raw_src = _node_text(src_node, source_bytes).strip("'\"")
                edges.append({
                    "src": "<module>",
                    "dst": raw_src,
                    "kind": "imports",
                    "line": node.start_point[0] + 1,
                })
            return

        if ntype in ("class_declaration", "interface_declaration", "type_alias_declaration"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                kind = "class" if ntype == "class_declaration" else "interface" if ntype == "interface_declaration" else "type"
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                # Inheritance
                heritage = next((c for c in node.children if c.type == "class_heritage"), None)
                if heritage:
                    heritage_str = _node_text(heritage, source_bytes)
                    for clause in re.split(r"\b(?:extends|implements)\b", heritage_str):
                        clause = clause.strip()
                        if clause:
                            for item in clause.split(","):
                                bname = item.strip().split("<")[0].strip()
                                if bname and bname[0].isalpha():
                                    edges.append({
                                        "src": name_path,
                                        "dst": bname,
                                        "kind": "inherits",
                                        "line": node.start_point[0] + 1,
                                    })

                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })

                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name and value_node and value_node.type == "arrow_function":
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": "method" if stack else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                stack.append(name)
                for child in value_node.children:
                    visit(child)
                stack.pop()
                return

        if ntype in ("function_declaration", "method_definition"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(stack)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "method" if stack else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public",
                    "docstring": "",
                })
                stack.append(name)
                for child in node.children:
                    visit(child)
                stack.pop()
                return

        if ntype == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point[0] + 1,
                        "kind": "call",
                    })
                    edges.append({
                        "src": "/".join(stack) or "<module>",
                        "dst": leaf_name,
                        "kind": "calls",
                        "line": node.start_point[0] + 1,
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_python(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    pending: list[tuple[Any, tuple[str, ...]]] = [(root, ())]

    while pending:
        node, scope = pending.pop()
        ntype = node.type

        if ntype in ("import_statement", "import_from_statement"):
            module = ""
            if ntype == "import_from_statement":
                mod_node = node.child_by_field_name("module_name")
                if mod_node:
                    module = _node_text(mod_node, source_bytes)
            targets = {module} if module else set()
            for imported in node.children_by_field_name("name"):
                if imported.type == "aliased_import":
                    imported = imported.child_by_field_name("name")
                if imported is None:
                    continue
                name = _node_text(imported, source_bytes)
                if not name or name == "*":
                    continue
                separator = "" if not module or module.endswith(".") else "."
                targets.add(f"{module}{separator}{name}")
            for dst in sorted(targets):
                edges.append({
                    "src": "<module>",
                    "dst": dst,
                    "kind": "imports",
                    "line": node.start_point[0] + 1,
                })
            continue

        child_scope = scope

        if ntype == "class_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(scope)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                # Inheritance
                arg_list = next((c for c in node.children if c.type == "argument_list"), None)
                if arg_list:
                    arg_str = _node_text(arg_list, source_bytes).strip("()")
                    for item in arg_str.split(","):
                        bname = item.strip().split("[")[0].strip()
                        if bname and bname[0].isalpha():
                            edges.append({
                                "src": name_path,
                                "dst": bname,
                                "kind": "inherits",
                                "line": node.start_point[0] + 1,
                            })

                syms.append({
                    "name": name,
                    "kind": "class",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not name.startswith("_") else "private",
                    "docstring": "",
                })
                child_scope = (*scope, name)

        if ntype == "function_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(scope)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)

                syms.append({
                    "name": name,
                    "kind": "method" if scope else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if not name.startswith("_") else "private",
                    "docstring": "",
                })
                child_scope = (*scope, name)

        if ntype == "call":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point[0] + 1,
                        "kind": "call",
                    })
                    edges.append({
                        "src": "/".join(scope) or "<module>",
                        "dst": leaf_name,
                        "kind": "calls",
                        "line": node.start_point[0] + 1,
                    })

        pending.extend((child, child_scope) for child in reversed(node.children))

    return syms, refs, edges


def _extract_go(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    curr_pkg = ""
    curr_func = ""

    def visit(node: Any) -> None:
        nonlocal curr_pkg, curr_func
        ntype = node.type

        if ntype == "package_clause":
            for c in node.children:
                if c.type == "package_identifier":
                    curr_pkg = _node_text(c, source_bytes)
            return

        if ntype == "import_declaration":
            for c in node.children:
                if c.type == "import_spec":
                    p_node = c.child_by_field_name("path")
                    if p_node:
                        p_text = _node_text(p_node, source_bytes).strip('"')
                        edges.append({
                            "src": "<module>",
                            "dst": p_text,
                            "kind": "imports",
                            "line": c.start_point[0] + 1,
                        })
            return

        if ntype == "type_declaration":
            for c in node.children:
                if c.type == "type_spec":
                    name_node = c.child_by_field_name("name")
                    type_node = c.child_by_field_name("type")
                    name = _node_text(name_node, source_bytes) if name_node else ""
                    if name:
                        t_type = type_node.type if type_node else ""
                        kind = "struct" if "struct" in t_type else ("interface" if "interface" in t_type else "type")
                        name_path = f"{curr_pkg}/{name}" if curr_pkg else name
                        sig = _first_line_sig(c, lines)
                        syms.append({
                            "name": name,
                            "kind": kind,
                            "line": c.start_point[0] + 1,
                            "end_line": c.end_point[0] + 1,
                            "container": curr_pkg,
                            "name_path": name_path,
                            "signature": sig,
                            "access": "public" if name[0].isupper() else "private",
                            "docstring": "",
                        })
            return

        if ntype == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                name_path = f"{curr_pkg}/{name}" if curr_pkg else name
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": curr_pkg,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if name[0].isupper() else "private",
                    "docstring": "",
                })
                old_func = curr_func
                curr_func = name_path
                for child in node.children:
                    visit(child)
                curr_func = old_func
                return

        if ntype == "method_declaration":
            name_node = node.child_by_field_name("name")
            recv_node = node.child_by_field_name("receiver")
            name = _node_text(name_node, source_bytes) if name_node else ""
            recv_text = _node_text(recv_node, source_bytes) if recv_node else ""
            recv_clean = re.sub(r"[()*& ]", "", recv_text).split()[-1] if recv_text else ""
            if name:
                container = f"{curr_pkg}/{recv_clean}" if (curr_pkg and recv_clean) else (recv_clean or curr_pkg)
                name_path = f"{container}/{name}" if container else name
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": "method",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if name[0].isupper() else "private",
                    "docstring": "",
                })
                old_func = curr_func
                curr_func = name_path
                for child in node.children:
                    visit(child)
                curr_func = old_func
                return

        if ntype == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split(".")[-1]
                if leaf_name and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point[0] + 1,
                        "kind": "call",
                    })
                    edges.append({
                        "src": curr_func or "<module>",
                        "dst": leaf_name,
                        "kind": "calls",
                        "line": node.start_point[0] + 1,
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _extract_rust(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    curr_impl = ""
    curr_func = ""

    def visit(node: Any) -> None:
        nonlocal curr_impl, curr_func
        ntype = node.type

        if ntype in ("struct_item", "enum_item", "trait_item", "type_item"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                kind = "struct" if ntype == "struct_item" else ("enum" if ntype == "enum_item" else ("trait" if ntype == "trait_item" else "type"))
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": kind,
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": "",
                    "name_path": name,
                    "signature": sig,
                    "access": "public" if "pub" in sig.split()[:2] else "private",
                    "docstring": "",
                })

        if ntype == "impl_item":
            type_node = node.child_by_field_name("type")
            trait_node = node.child_by_field_name("trait")
            t_name = _node_text(type_node, source_bytes) if type_node else ""
            tr_name = _node_text(trait_node, source_bytes) if trait_node else ""
            if t_name and tr_name:
                edges.append({
                    "src": t_name,
                    "dst": tr_name,
                    "kind": "implements",
                    "line": node.start_point[0] + 1,
                })
            old_impl = curr_impl
            curr_impl = t_name
            for child in node.children:
                visit(child)
            curr_impl = old_impl
            return

        if ntype == "function_item":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = curr_impl
                name_path = f"{container}::{name}" if container else name
                sig = _first_line_sig(node, lines)
                syms.append({
                    "name": name,
                    "kind": "method" if container else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": sig,
                    "access": "public" if "pub" in sig.split()[:2] else "private",
                    "docstring": "",
                })
                old_func = curr_func
                curr_func = name_path
                for child in node.children:
                    visit(child)
                curr_func = old_func
                return

        if ntype in ("call_expression", "macro_invocation"):
            fn_node = node.child_by_field_name("function") or node.child_by_field_name("macro")
            if fn_node:
                fn_text = _node_text(fn_node, source_bytes)
                leaf_name = fn_text.split("::")[-1].split(".")[-1].rstrip("!")
                if leaf_name and leaf_name[0].isalpha():
                    refs.append({
                        "name": leaf_name,
                        "line": node.start_point[0] + 1,
                        "kind": "call",
                    })
                    edges.append({
                        "src": curr_func or "<module>",
                        "dst": fn_text.rstrip("!"),
                        "kind": "calls",
                        "line": node.start_point[0] + 1,
                    })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges

def _extract_java(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    containers: list[str] = []
    current_function = ""
    type_kinds = {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
    }

    def visit(node: Any) -> None:
        nonlocal current_function
        ntype = node.type

        if ntype in type_kinds:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(containers)
                name_path = f"{container}/{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": type_kinds[ntype],
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                containers.append(name)
                for child in node.children:
                    visit(child)
                containers.pop()
                return

        if ntype in ("method_declaration", "constructor_declaration"):
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "/".join(containers)
                name_path = f"{container}/{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": "constructor" if ntype == "constructor_declaration" else "method",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                previous_function = current_function
                current_function = name_path
                for child in node.children:
                    visit(child)
                current_function = previous_function
                return

        if ntype == "method_invocation":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name and re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                refs.append({"name": name, "line": node.start_point[0] + 1, "kind": "call"})
                edges.append({
                    "src": current_function or "<module>",
                    "dst": name,
                    "kind": "calls",
                    "line": node.start_point[0] + 1,
                })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges


def _cpp_declarator_name(node: Any, source_bytes: bytes) -> str:
    if node.type in ("identifier", "field_identifier", "operator_name"):
        return _node_text(node, source_bytes)
    if node.type == "qualified_identifier":
        name_node = node.child_by_field_name("name")
        return _cpp_declarator_name(name_node, source_bytes) if name_node else _node_text(node, source_bytes).split("::")[-1]
    declarator = node.child_by_field_name("declarator")
    if declarator:
        return _cpp_declarator_name(declarator, source_bytes)
    for child in node.children:
        name = _cpp_declarator_name(child, source_bytes)
        if name:
            return name
    return ""


def _extract_cpp(
    root: Any, lines: list[str], source_bytes: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    syms: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    containers: list[str] = []
    class_containers: list[str] = []
    current_function = ""
    container_kinds = {
        "namespace_definition": "namespace",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
    }

    def visit(node: Any) -> None:
        nonlocal current_function
        ntype = node.type

        if ntype in container_kinds:
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else ""
            if name:
                container = "::".join(containers)
                name_path = f"{container}::{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": container_kinds[ntype],
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                containers.append(name)
                if ntype in ("class_specifier", "struct_specifier"):
                    class_containers.append(name)
                for child in node.children:
                    visit(child)
                if ntype in ("class_specifier", "struct_specifier"):
                    class_containers.pop()
                containers.pop()
                return

        if ntype == "function_definition":
            declarator = node.child_by_field_name("declarator")
            name = _cpp_declarator_name(declarator, source_bytes) if declarator else ""
            if name:
                container = "::".join(containers)
                name_path = f"{container}::{name}" if container else name
                syms.append({
                    "name": name,
                    "kind": "method" if class_containers else "function",
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "container": container,
                    "name_path": name_path,
                    "signature": _first_line_sig(node, lines),
                    "access": "public",
                    "docstring": "",
                })
                previous_function = current_function
                current_function = name_path
                for child in node.children:
                    visit(child)
                current_function = previous_function
                return

        if ntype == "call_expression":
            function_node = node.child_by_field_name("function")
            call_text = _node_text(function_node, source_bytes) if function_node else ""
            name = re.split(r"::|->|\.", call_text)[-1]
            if name and re.fullmatch(r"[A-Za-z_][\w]*", name):
                refs.append({"name": name, "line": node.start_point[0] + 1, "kind": "call"})
                edges.append({
                    "src": current_function or "<module>",
                    "dst": name,
                    "kind": "calls",
                    "line": node.start_point[0] + 1,
                })

        for child in node.children:
            visit(child)

    visit(root)
    return syms, refs, edges
