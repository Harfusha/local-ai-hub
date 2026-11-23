from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from .normalizer import tokenize_query_terms
from .repo_tools_constants import _INSTALLATION_INTENT_TERMS
from .search_modes import prefers_lexical_precision


def _record_security_inventory_issue(
    status: dict[str, Any] | None,
    root: Path,
    reason: str,
    path: Path | None = None,
) -> None:
    if status is None:
        return
    status["complete"] = False
    if reason not in status["reasons"]:
        status["reasons"].append(reason)
    if path is None:
        return
    try:
        relative = path.relative_to(root)
        if not relative.parts or any(part in {".", ".."} for part in relative.parts):
            return
        value = relative.as_posix()
    except ValueError:
        return
    examples = status.setdefault("examples", {}).setdefault(reason, [])
    if value in examples:
        return
    if len(examples) < 3:
        examples.append(value)
    else:
        status["examples_truncated"] = True


@lru_cache(maxsize=1024)
def _intent_query_terms(query: str) -> frozenset[str]:
    return frozenset(term.casefold() for term in tokenize_query_terms(query))


def _is_installation_intent(query_terms: frozenset[str]) -> bool:
    if query_terms.intersection(_INSTALLATION_INTENT_TERMS):
        return True
    if {"set", "up"}.issubset(query_terms):
        return True
    return any(term.startswith(("install", "instal", "nainstal")) for term in query_terms)


@lru_cache(maxsize=8192)
def _intent_path_adjustment(query: str, relative_path: str) -> float:
    """Prefer user-facing install guides over tests for natural how-to queries."""
    if prefers_lexical_precision(query):
        return 0.0
    query_terms = _intent_query_terms(query)
    if not _is_installation_intent(query_terms):
        return 0.0
    path = relative_path.casefold().replace("\\", "/").strip("/")
    if not path or any(part in {"plans", "specs", "superpowers"} for part in path.split("/")):
        return 0.0
    name = path.rsplit("/", 1)[-1]
    if "prompt" in name and not query_terms.intersection({"prompt", "prompts"}):
        return 0.0
    if path.startswith("tests/") or "/tests/" in path:
        return -8.0
    if path in {"readme.md", "docs/readme.md"}:
        return 24.0
    if path == "docs/installation.md":
        return 72.0
    install_intent = _is_installation_intent(query_terms)
    setup_intent = query_terms.intersection({"setup", "quickstart", "spustit"}) or {
        "set",
        "up",
    }.issubset(query_terms)
    configuration_intent = query_terms.intersection({"configure", "configuration", "nastavit", "nastavení"})
    documentation_entrypoint = (
        (install_intent and name.startswith(("install", "setup", "getting_started", "getting-started", "quickstart")))
        or (setup_intent and name.startswith(("setup", "getting_started", "getting-started", "quickstart")))
        or (configuration_intent and name.startswith(("configure", "configuration", "setup")))
    )
    if path.startswith("docs/") and name.endswith(".md") and documentation_entrypoint:
        return 56.0
    return 0.0


@lru_cache(maxsize=16_384)
def is_root_archive_path(relative: str | Path) -> bool:
    """Identify audit overlays and archived source copies, not ordinary docs."""
    parts = tuple(
        part.casefold()
        for part in str(relative).replace("\\", "/").strip("/").split("/")
        if part not in {"", "."}
    )
    if not parts:
        return False
    if parts[0] == ".validation":
        return True
    if parts[:3] == ("docs", "integration", "archive") and re.search(
        r"\.(?:py|pyi|js|jsx|ts|tsx|cs|go|rs|java|c|cc|cpp|h|hpp)(?:\.txt)?$", parts[-1]
    ):
        return True
    if parts[0] in {
        "handoff",
        ".handoff",
        ".merge-checks",
        ".sync-checks",
        ".system_generated",
        ".t17-merge-tmp",
    }:
        return True
    if len(parts) > 1 and parts[:2] == ("artifacts", "handoff"):
        return True
    if len(parts) > 1 and parts[0] == "artifacts" and "-overlay-" in parts[1]:
        return True
    if len(parts) > 1 and parts[0] == "artifacts":
        artifact_name = parts[1]
        if artifact_name == "generated.py" or artifact_name.startswith("generated"):
            return True
        if re.fullmatch(r"t\d+-.+", artifact_name) and (
            parts[2:4] == ("src", "local_ai_hub")
            or parts[2:3] in {("tests",), ("tools",)}
        ):
            return True
        if re.match(r"t\d+-ast-check-", artifact_name):
            return True
        if re.fullmatch(
            r"t\d+-root-current-.+(?:-preimage(?:\.[^/]*)?|-replay\.py|-memory-transition\.py)",
            artifact_name,
        ):
            return True
    if (
        len(parts) >= 6
        and parts[0] == ".validation"
        and re.fullmatch(r"t\d+-.+", parts[1]) is not None
        and parts[2] == "package-pytest"
        and parts[3].startswith("test_")
        and "generated" in parts[4:]
    ):
        return True
    root_name = parts[0].lstrip(".")
    return (
        "-root-overlay-" in parts[0]
        or "-root-current-check-" in parts[0]
        or "-root-current-overlay" in parts[0]
        or re.match(r"t\d+-review-artifacts-", root_name) is not None
        or re.match(r"t\d+-(?:sync-checks|main-preflight-overlay)(?:-|$)", root_name) is not None
    )


@lru_cache(maxsize=1)
def _unicode_lower_expansions() -> tuple[frozenset[str], frozenset[str]]:
    """Source and output characters of multi-character lowercase mappings."""
    sources: set[str] = set()
    expanded: set[str] = set()
    for codepoint in range(0x110000):
        source = chr(codepoint)
        lowered = source.lower()
        if len(lowered) > 1:
            sources.add(source)
            expanded.update(lowered)
    return frozenset(sources), frozenset(expanded)


def _lower_expansion_characters() -> frozenset[str]:
    """Characters emitted by multi-character Unicode lowercase mappings."""
    return _unicode_lower_expansions()[1]


@lru_cache(maxsize=1)
def _windows_file_api():
    import ctypes
    from ctypes import wintypes

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    return _FileBasicInfo, kernel32, create_file, get_info, close_handle, ctypes.c_void_p(-1).value
