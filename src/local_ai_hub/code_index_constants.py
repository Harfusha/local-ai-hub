from __future__ import annotations

import re

from . import __version__

_PARSER_ANALYZER_VERSION = f"{__version__}:call-edges-v18-lexical-scope-doc-tool-postings"

MAX_IMPACT_DEPENDENTS = 100_000

IDENT = re.compile(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b")
GENERIC_DEF = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|final|async|export|abstract|virtual|override|sealed|readonly)\s+)*(class|interface|trait|enum|struct|record|function|func|fn|def|type)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
)
IMPORT = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w./@-]+)|(?:use|require_once|include_once|require|include|using)\b\s*\(?\s*[\'\"]?([^\'\";]+)[\'\"]?\s*\)?)"
)
ARROW_DEF = re.compile(
    r"^\s*(?:(?:export|default|public|private|protected|internal|static|readonly|const|let|var)\s+)*([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>"
)
INLINE_ARROW_DEF = re.compile(
    r"(?<![\w$])(?:(?:export|default|public|private|protected|internal|static|readonly|const|let|var)\s+)*([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>"
)
GO_METHOD = re.compile(r"^\s*func\s*(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
TYPED_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|final|async|virtual|override|abstract|sealed|synchronized|native)\s+)*(?:[A-Za-z_$][\w.$<>,?\[\]]*\s+)+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^;{}]*)\)\s*(?:\{|=>|throws\b|where\b)"
)
JS_METHOD = re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^)]*)\)\s*\{")
TRAILING_CALL_AFTER_CLOSE = re.compile(r"}\s*;?\s*(?:[A-Za-z_$][\w$]*\s*\??\.\s*)*[A-Za-z_$][A-Za-z0-9_$]*\s*\(")
_CONTROL_NAMES = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "new",
    "throw",
    "using",
    "lock",
    "foreach",
    "typeof",
    "sizeof",
    "default",
}

_DECLARATION_CALL_PATTERNS = (
    re.compile(r"\b(?:function|func|fn|def)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
    re.compile(
        r"\b(?:(?:public|private|protected|internal|static|final|async|virtual|override|abstract|sealed|synchronized|native)\s+)*(?:[A-Za-z_$][\w.$<>,?\[\]]*\s+)+([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^;{}]*\)\s*(?:\{|=>|throws\b|where\b)"
    ),
)


def _declaration_call_spans(line: str) -> set[tuple[int, int]]:
    return {
        match.span(1)
        for pattern in _DECLARATION_CALL_PATTERNS
        for match in pattern.finditer(line)
    }
