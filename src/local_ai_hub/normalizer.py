from __future__ import annotations

import re
import unicodedata
from typing import Any

BOUNDARY_PUNCTUATION_CHARS = " \t\r\n-_.,:;!?¿¡'\"`~^/\\|#*+=()[]{}<>"

def _trim_boundary_punctuation(text: str) -> str:
    start = 0
    end = len(text)
    while start < end and text[start] in BOUNDARY_PUNCTUATION_CHARS:
        start += 1
    while end > start and text[end - 1] in BOUNDARY_PUNCTUATION_CHARS:
        end -= 1
    return text[start:end]

# Universal tag extractor for <think>, <thought>, <reasoning>, <scratchpad>, <plan>, <reflection>, etc.
GENERIC_TAG_RE = re.compile(
    r"<(?P<tag>think|thought|reasoning|scratchpad|plan|reflection|inner_monologue)>(?P<content>.*?)</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)

# Chat stop tokens emitted by raw LLM runtimes
STOP_TOKENS_RE = re.compile(
    r"(?:<\|im_end\|>|<\|endoftext\|>|<\|im_start\|>|<\|fim_prefix\|>|<\|fim_suffix\|>|<\|fim_middle\|>|</s>|\[DONE\]|<\|eot_id\|>|<\|end_of_text\|>)",
    re.IGNORECASE,
)

# Language-agnostic structural preamble pattern:
# A short introductory line (< 140 chars) ending with a colon or newline directly preceding a code block or list
STRUCTURAL_PREAMBLE_RE = re.compile(
    r"^[^\n`#]{1,140}:\s*\n+(?=(?:```|~~~|[-*+]\s|\d+\.\s))",
    re.DOTALL,
)

# Conversational preamble pattern:
# Openers like "Sure! Here is the fix:", "Certainly, ...", "Okay, here are ...", "Hello! ..."
CONVERSATIONAL_PREAMBLE_RE = re.compile(
    r"^(?:(?:sure|certainly|of course|here is|here are|hello|hi|okay|ok)[^\n]{0,120}(?::|\.|\!)\s*\n+)+(?=(?:```|~~~|[-*+]\s|\d+\.\s|[A-Z0-9_]{2,}:))",
    re.IGNORECASE | re.DOTALL,
)

# Conversational postamble / closing pleasantries pattern:
# Closings like "Hope this helps!", "Let me know if you need any further assistance!", etc.
CONVERSATIONAL_POSTAMBLE_RE = re.compile(
    r"(?:\n+(?:hope (?:this|that) helps[^\n]*|let me know if you (?:need|have)[^\n]*|feel free to ask[^\n]*|if you have any (?:other )?questions[^\n]*))+\Z",
    re.IGNORECASE,
)


def normalize_query(
    query: str,
    *,
    strip_punctuation: bool = True,
    normalize_paths: bool = True,
    normalize_unicode: bool = True,
) -> str:
    """Universal language-agnostic query normalizer.
    
    Operates purely on structural and Unicode properties:
    1. Normalizes Unicode character representation (NFKC) so accents/diacritics and symbols are consistent.
    2. Normalizes path separators from backslashes to forward slashes.
    3. Trims boundary punctuation across all human alphabets and scripts.
    4. Collapses multiple whitespace characters (including non-breaking and CJK spaces).
    """
    if not query:
        return ""

    text = str(query).strip()

    if normalize_unicode:
        # NFKC canonicalizes equivalent Unicode forms universally
        text = unicodedata.normalize("NFKC", text)

    if normalize_paths:
        text = text.replace("\\", "/")

    if strip_punctuation:
        text = _trim_boundary_punctuation(text).strip()

    # Collapse all unicode whitespace categories
    text = " ".join(text.split())
    return text


def tokenize_query_terms(
    query: str,
    min_len: int = 2,
    max_terms: int = 24,
    custom_stop_words: set[str] | None = None,
) -> list[str]:
    """Language-agnostic, code-aware token extractor.
    
    Extracts identifiers and terms using structural casing rules:
    - Splits CamelCase, PascalCase, snake_case, kebab-case, and dot-notation.
    - Preserves the full identifier alongside its component words.
    - Works identically across all programming languages and natural languages.
    """
    clean = normalize_query(query, strip_punctuation=True, normalize_paths=False)
    raw_tokens = re.findall(r"[\w$@.:/-]{2,}", clean, re.UNICODE)
    
    stop = custom_stop_words if custom_stop_words is not None else set()
    terms: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        t_clean = t.strip("._-:/@$")
        if len(t_clean) >= min_len:
            low = t_clean.lower()
            if low not in stop and low not in seen:
                seen.add(low)
                terms.append(t_clean)

    for token in raw_tokens:
        add(token)
        # Structural delimiter split (snake_case, kebab-case, paths, namespaces)
        if any(c in token for c in ("_", "-", ".", ":", "/", "\\", "@", "$")):
            for part in re.split(r"[\_\-.:/\\@$]+", token):
                add(part)
        
        # Structural case transition split (camelCase / PascalCase)
        sub_tokens = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z0-9]|\b)|[\w]+", token, re.UNICODE)
        if len(sub_tokens) > 1:
            for st in sub_tokens:
                add(st)
        if len(terms) >= max_terms:
            break

    return terms[:max_terms]


def postprocess_model_output(
    text: str,
    *,
    role: str = "general",
    strip_preamble: bool = True,
    repair_fences: bool = True,
) -> tuple[str, str | None]:
    """Universal language-agnostic postprocessor for LLM outputs.
    
    1. Extracts and isolates <think>, <thought>, <reasoning>, <scratchpad> blocks into `thinking`.
    2. Strips raw runtime stop tokens (<|im_end|>, etc.).
    3. Structurally strips non-code introductory preambles for technical roles.
    4. Automatically balances and closes unclosed Markdown code blocks.
    5. Normalizes line endings to clean \n.
    """
    if not text:
        return "", None

    raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
    
    # 1. Extract generic thinking tags regardless of model architecture
    thinking_parts: list[str] = []
    for match in GENERIC_TAG_RE.finditer(raw):
        content = match.group("content").strip()
        if content:
            thinking_parts.append(content)
    
    thinking: str | None = "\n\n".join(thinking_parts) if thinking_parts else None
    cleaned = GENERIC_TAG_RE.sub("", raw).strip()

    # 2. Strip runtime stop tokens
    cleaned = STOP_TOKENS_RE.sub("", cleaned).strip()

    # 3. Structural and conversational preamble/postamble removal for technical roles
    role_lower = str(role or "general").lower()
    is_technical_role = (
        role_lower in {"code", "review", "patch", "critic", "second-opinion", "fast", "smart", "drafter", "explorer", "reasoning", "general"}
        or "qwen-" in role_lower
        or "profile" in role_lower
    )
    if strip_preamble and is_technical_role:
        cleaned = CONVERSATIONAL_PREAMBLE_RE.sub("", cleaned).strip()
        cleaned = STRUCTURAL_PREAMBLE_RE.sub("", cleaned).strip()
        cleaned = CONVERSATIONAL_POSTAMBLE_RE.sub("", cleaned).strip()

    # 4. Universal Markdown fence balance repair
    if repair_fences:
        code_fence_count = cleaned.count("```")
        if code_fence_count % 2 != 0:
            cleaned = cleaned + "\n```"

    # 5. Deduplicate excessive consecutive newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned, thinking


def postprocess_patch(diff_text: str) -> str:
    """Ensure clean unified diff headers and valid line endings."""
    if not diff_text:
        return ""
    lines = str(diff_text).replace("\r\n", "\n").replace("\r", "\n").splitlines()
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
            start_idx = i
            break
    cleaned_lines = lines[start_idx:]
    return "\n".join(cleaned_lines).rstrip() + "\n"
