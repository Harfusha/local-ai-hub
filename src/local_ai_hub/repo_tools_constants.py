from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]{1,80}")
MAX_EXACT_SEARCH_FILES = 8000
MAX_EXACT_GIT_PATHS = 128_000
MAX_EXACT_GIT_PATH_BYTES = 32 * 1024 * 1024
_IMPACT_SCAN_MAX_FILES = 8_000
_IMPACT_SCAN_TIMEOUT_SECONDS = 1.5
_IMPACT_RIPGREP_TIMEOUT_SECONDS = 1.5
_INSTALLATION_INTENT_TERMS = frozenset({
    "install", "installation", "setup", "configure", "configuration", "quickstart",
    "nainstalovat", "instalovat", "instalace", "nastavit", "nastavení", "spustit",
})
_GENERIC_SEARCH_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it",
    "of", "on", "or", "the", "to", "with", "implement", "implementation", "implementing", "missing",
    "change", "changes", "fix", "fixing", "add", "added", "update", "updated", "make", "ensure", "support",
})
_MAX_DIRECTORY_HINT_FILES = 64
_MAX_PATH_CONTROLS = 64
_HARD_SEARCH_DIRS = frozenset({".git", ".local-ai-hub", ".serena", ".codegraphcontext"})
_UNSET_GIT_INVENTORY = object()

_SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),
    re.compile(
        r"^\s*(?:public|private|protected|internal|static|final|virtual|override|abstract|sealed|partial|async|export|default|const|let|var|function|func|fn|type|interface|enum|struct|record|trait|impl|namespace|module)\s+(?:[\w<>,?\[\].]+\s+)*([A-Za-z_]\w*)"
    ),
]
