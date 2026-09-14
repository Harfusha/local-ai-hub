from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import __version__
from .budget import estimate_tokens
from .cache import SQLiteCache, TieredCache, stable_hash
from .normalizer import tokenize_query_terms


class LosslessTokenRouter:
    """Route oversized text/file context into exact raw line slices.

    The local model is allowed to choose line coordinates, but never to rewrite the
    evidence. If parsing/model inference fails, a deterministic lexical router is
    used. This mirrors the useful separation from token-router: cheap local triage,
    original evidence for the stronger agent.
    """

    def __init__(self, config: dict[str, Any], services: Any):
        self.config = config
        self.services = services
        cfg = config.get("lossless_router", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.max_ranges = max(1, int(cfg.get("max_ranges", 8)))
        self.context_lines = max(0, int(cfg.get("context_lines", 4)))
        self.max_output_tokens = max(128, int(cfg.get("selector_output_tokens", 450)))
        self.local_threshold_tokens = max(256, int(cfg.get("threshold_tokens", 1400)))
        self.deterministic_skip_score = float(cfg.get("deterministic_skip_score", 4.5))
        self.deterministic_skip_min_terms = int(cfg.get("deterministic_skip_min_terms", 1))
        self.max_scan_lines = max(200, int(cfg.get("max_scan_lines", 12000)))
        self.max_selector_chars = max(8000, int(cfg.get("max_selector_chars", 100000)))
        self.max_output_lines = max(20, int(cfg.get("max_output_lines", 140)))
        state_dir = Path(config["server"]["state_dir"])
        self.cache = TieredCache(
            SQLiteCache(state_dir / "cache.sqlite3", "lossless-router", int(cfg.get("ttl_seconds", 604800)), int(cfg.get("max_entries", 10000))),
            int(cfg.get("l1_entries", 256)), int(cfg.get("l1_ttl_seconds", 1800)),
        )
        self.hits = 0
        self.misses = 0
        self.fallbacks = 0

    @staticmethod
    def _terms(query: str) -> list[str]:
        return [t.lower() for t in tokenize_query_terms(query, min_len=2, max_terms=24)]

    @staticmethod
    def _infer_mode(text: str, path: str | None) -> str:
        suffix = Path(path).suffix.lower() if path else ""
        lower = text[:12000].lower()
        if suffix in {".log", ".out"} or any(x in lower for x in ("traceback", "stack trace", "fatal:", "exception:", "error:")):
            return "error_log"
        if path and Path(path).name.lower() in {"agents.md", "claude.md", "gemini.md", "instructions.md"}:
            return "agent_context"
        return "heavy_code"

    def _deterministic_ranges(self, lines: list[str], query: str, mode: str) -> list[tuple[int, int, float]]:
        terms = self._terms(query)
        scored: list[tuple[float, int]] = []
        if len(lines) <= self.max_scan_lines:
            scan_positions = range(len(lines))
        else:
            # Preserve a small header sample while always including newest log data.
            head = max(1, self.max_scan_lines // 4)
            tail = self.max_scan_lines - head
            scan_positions = [*range(head), *range(len(lines) - tail, len(lines))]
        for position in scan_positions:
            idx = position + 1
            line = lines[position]
            lower = line.lower()
            score = sum(3.0 if re.search(rf"\b{re.escape(t)}\b", lower) else 1.0 for t in terms if t in lower)
            if mode == "error_log":
                if any(x in lower for x in ("error", "fatal", "exception", "traceback", "failed", "timeout", "panic", "segfault")):
                    score += 2.5
                # Recent log evidence gets a gentle boost.
                score += 0.5 * (idx / max(1, len(lines)))
            elif mode == "agent_context":
                if line.lstrip().startswith("#") or any(x in lower for x in ("must", "never", "required", "security", "test", "workflow", "tool", "do not")):
                    score += 1.8
            else:
                if any(x in lower for x in ("todo", "fixme", "raise ", "assert ", "throw ", "except ", "catch ", "unsafe", "lock", "transaction")):
                    score += 1.2
                if re.match(r"^\s*(class|def|function|func|fn|interface|type|public|private|protected)\b", lower):
                    score += 0.5
            if score:
                scored.append((score, idx))
        if not scored:
            # Preserve a tiny beginning/end sample rather than inventing relevance.
            n = len(lines)
            ranges = [(1, min(n, 20), 0.0)]
            if n > 40:
                ranges.append((max(1, n - 19), n, 0.0))
            return ranges[: self.max_ranges]
        scored.sort(key=lambda x: (-x[0], x[1]))
        ranges: list[tuple[int, int, float]] = []
        for score, line_no in scored:
            start = max(1, line_no - self.context_lines)
            end = min(len(lines), line_no + self.context_lines)
            if any(not (end < a - 2 or start > b + 2) for a, b, _ in ranges):
                continue
            ranges.append((start, end, score))
            if len(ranges) >= self.max_ranges:
                break
        ordered = sorted(ranges, key=lambda x: x[0])
        bounded: list[tuple[int, int, float]] = []
        used = 0
        # In log mode keep stronger/newer ranges when the cloud-visible line cap is hit.
        candidates = sorted(ordered, key=lambda r: (r[2], r[1]), reverse=True) if mode == "error_log" else sorted(ordered, key=lambda r: r[2], reverse=True)
        for item in candidates:
            span = item[1] - item[0] + 1
            if used + span > self.max_output_lines:
                continue
            bounded.append(item); used += span
        return sorted(bounded or ordered[:1], key=lambda x: x[0])

    @staticmethod
    def _parse_ranges(text: str, max_line: int, max_ranges: int, context_lines: int) -> list[tuple[int, int, float]]:
        # Accept only a JSON object/array with integer start/end coordinates.
        match = re.search(r"(?:```json\s*)?(\{.*\}|\[.*\])(?:\s*```)?", text, flags=re.S)
        if not match:
            return []
        try:
            obj = json.loads(match.group(1))
        except Exception:
            return []
        items = obj.get("ranges", []) if isinstance(obj, dict) else obj
        out: list[tuple[int, int, float]] = []
        if not isinstance(items, list):
            return []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                start = max(1, min(max_line, int(item["start"])))
                end = max(start, min(max_line, int(item["end"])))
            except Exception:
                continue
            start = max(1, start - context_lines)
            end = min(max_line, end + context_lines)
            out.append((start, end, float(item.get("score", 1.0))))
            if len(out) >= max_ranges:
                break
        return out

    @staticmethod
    def _render(lines: list[str], ranges: list[tuple[int, int, float]], path: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        pieces: list[str] = []
        evidence: list[dict[str, Any]] = []
        for start, end, score in ranges:
            raw = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
            header = f"--- {path or 'input'}:{start}-{end} ---"
            pieces.append(header + "\n" + raw)
            evidence.append({"path": path or "input", "start_line": start, "end_line": end, "score": round(score, 3), "raw": raw})
        return "\n\n".join(pieces), evidence

    def route_text(self, text: str, query: str, tenant: str, *, path: str | None = None, force_local: bool = False) -> dict[str, Any]:
        lines = text.splitlines()
        if not self.enabled or not lines:
            return {"success": True, "context": text, "evidence": [], "routed": False, "estimated_tokens": estimate_tokens(text)}
        mode = self._infer_mode(text, path)
        scope = stable_hash({"text": stable_hash(text), "query": query, "path": path, "mode": mode, "app_version": __version__})
        cached = self.cache.get(scope)
        if isinstance(cached, dict):
            self.hits += 1
            result = dict(cached); result["cache_hit"] = True
            return result
        self.misses += 1

        baseline = self._deterministic_ranges(lines, query, mode)
        ranges = baseline
        local_used = False
        terms = self._terms(query)
        top_score = max((float(x[2]) for x in baseline), default=0.0)
        deterministic_sufficient = len(terms) >= self.deterministic_skip_min_terms and top_score >= self.deterministic_skip_score
        if force_local or (estimate_tokens(text) >= self.local_threshold_tokens and not deterministic_sufficient):
            # Send a numbered, bounded view to the cheap local selector. For huge input,
            # deterministic candidates are expanded into windows first to keep selector context bounded.
            if len(lines) > self.max_scan_lines or len(text) > self.max_selector_chars:
                candidate_ranges = baseline
                selector_parts = []
                for start, end, _ in candidate_ranges:
                    expand = max(20, self.context_lines * 4)
                    a = max(1, start - expand); b = min(len(lines), end + expand)
                    selector_parts.append("\n".join(f"{i}: {lines[i-1]}" for i in range(a, b + 1)))
                numbered = "\n...\n".join(selector_parts)[: self.max_selector_chars]
            else:
                numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(lines, start=1))[: self.max_selector_chars]
            selector_prompt = (
                "Select only exact line ranges needed to answer TASK. Do not answer the task and do not summarize. "
                f"Return JSON only: {{\"ranges\":[{{\"start\":N,\"end\":N,\"score\":0-1}}]}}; max {self.max_ranges} ranges.\n\n"
                f"TASK:\n{query}\n\nNUMBERED INPUT:\n{numbered}"
            )
            fast_model = str(self.config.get("models", {}).get("fast_code", "qwen2.5-coder:3b-instruct-q5_K_M"))
            local = self.services._generate(
                fast_model, selector_prompt,
                "You are a lossless context router. Your sole job is selecting relevant original line coordinates. JSON only.",
                self.max_output_tokens, 0.0, tenant, "lossless-route", 7,
                semantic_query="", semantic_context_fingerprint="", internal=True,
            )
            if local.get("success"):
                parsed = self._parse_ranges(str(local.get("text", "")), len(lines), self.max_ranges, self.context_lines)
                if parsed:
                    ranges = parsed
                    local_used = True
                else:
                    self.fallbacks += 1
            else:
                self.fallbacks += 1

        context, evidence = self._render(lines, ranges, path)
        result = {
            "success": True, "context": context, "evidence": evidence, "routed": True, "mode": mode,
            "local_selector_used": local_used, "deterministic_selector_sufficient": deterministic_sufficient, "input_tokens_est": estimate_tokens(text),
            "estimated_tokens": estimate_tokens(context), "reduction_ratio": round(1.0 - min(1.0, len(context) / max(1, len(text))), 5),
            "cache_hit": False,
        }
        self.cache.set(scope, result)
        return result

    def route_file(self, root: str, relative_path: str, query: str, tenant: str) -> dict[str, Any]:
        repo = Path(root).resolve()
        path = (repo / relative_path).resolve()
        try:
            path.relative_to(repo)
        except ValueError:
            return {"success": False, "error": "path escapes root"}
        if not path.is_file():
            return {"success": False, "error": f"file not found: {relative_path}"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"success": False, "error": str(exc)}
        return self.route_text(text, query, tenant, path=str(path.relative_to(repo)).replace("\\", "/"), force_local=False)

    def stats(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "hits": self.hits, "misses": self.misses, "fallbacks": self.fallbacks, "cache": self.cache.stats()}


LICENSE_RE = re.compile(
    r"^\s*(?://|#|/\*|\*)\s*.*?(?:copyright|license|all rights reserved|spdx-license-identifier|mit license|apache license|mozilla public license|author:).*?(?:\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
AUTOGEN_RE = re.compile(
    r"^\s*(?://|#|/\*|\*)\s*.*?(?:auto-generated|autogenerated|generated by|do not edit|code generated).*?(?:\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)

def strip_boilerplate(text: str) -> str:
    """Strip license headers, copyright notices and autogenerated headers from the beginning of a source file."""
    if not text or len(text) < 40:
        return text
    head = text[:2000]
    tail = text[2000:]
    cleaned_head = AUTOGEN_RE.sub("", head)
    cleaned_head = LICENSE_RE.sub("", cleaned_head)
    cleaned_head = cleaned_head.lstrip()
    return cleaned_head + tail


BANNER_COMMENT_RE = re.compile(
    r"^\s*(?://|#|/\*)\s*[-=~*#]{5,}\s*(?:\*/)?\s*$",
    re.MULTILINE,
)
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

def compact_whitespace(text: str) -> str:
    """Strip banner comments and compress multi-line blank gaps to save prompt tokens."""
    if not text:
        return ""
    cleaned = BANNER_COMMENT_RE.sub("", text)
    cleaned = MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def shrink_signatures(text: str, language: str = "csharp") -> str:
    """Replace method/function bodies with concise summaries for reference context."""
    if not text:
        return text
    
    lang = language.lower()
    if lang in ("csharp", "cs", "ts", "typescript", "js", "javascript", "java", "cpp", "c"):
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if text[i] == '{':
                start = i
                depth = 1
                j = i + 1
                in_str: str | None = None
                in_line_comment = False
                in_block_comment = False
                while j < n and depth > 0:
                    ch = text[j]
                    if in_line_comment:
                        if ch == '\n':
                            in_line_comment = False
                        j += 1
                        continue
                    if in_block_comment:
                        if ch == '*' and j + 1 < n and text[j + 1] == '/':
                            in_block_comment = False
                            j += 2
                            continue
                        j += 1
                        continue
                    if in_str:
                        if ch == '\\' and j + 1 < n:
                            j += 2
                            continue
                        if ch == in_str:
                            in_str = None
                        j += 1
                        continue
                    if ch == '/' and j + 1 < n:
                        next_ch = text[j + 1]
                        if next_ch == '/':
                            in_line_comment = True
                            j += 2
                            continue
                        if next_ch == '*':
                            in_block_comment = True
                            j += 2
                            continue
                    if ch in ('"', "'", '`'):
                        in_str = ch
                    elif ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                    j += 1
                if depth == 0 and (j - start) > 100:
                    body = text[start:j]
                    if "class " not in body and "namespace " not in body and "interface " not in body:
                        out.append("{\n    /* ... implementation ... */\n  }")
                        i = j
                        continue
            out.append(text[i])
            i += 1
        return "".join(out)
    
    if lang in ("py", "python"):
        lines = text.splitlines(keepends=True)
        out_lines: list[str] = []
        idx = 0
        num_lines = len(lines)
        def_re = re.compile(r"^([ \t]*)def\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*(?:->\s*[^:]+)?:\s*$")
        while idx < num_lines:
            line = lines[idx]
            m = def_re.match(line.rstrip("\r\n"))
            if m:
                base_indent = len(m.group(1).expandtabs(4))
                out_lines.append(line)
                idx += 1
                body_lines: list[str] = []
                while idx < num_lines:
                    next_line = lines[idx]
                    stripped = next_line.strip()
                    if not stripped:
                        body_lines.append(next_line)
                        idx += 1
                        continue
                    line_indent = len(next_line[: len(next_line) - len(next_line.lstrip())].expandtabs(4))
                    if line_indent > base_indent:
                        body_lines.append(next_line)
                        idx += 1
                    else:
                        break
                content_count = sum(1 for b in body_lines if b.strip())
                if content_count >= 3:
                    indent_str = m.group(1) + "    "
                    out_lines.append(f"{indent_str}...\n")
                    trailing_blanks: list[str] = []
                    while body_lines and not body_lines[-1].strip():
                        trailing_blanks.append(body_lines.pop())
                    out_lines.extend(reversed(trailing_blanks))
                else:
                    out_lines.extend(body_lines)
                continue
            out_lines.append(line)
            idx += 1
        return "".join(out_lines)
        
    return text


BINARY_ASSET_EXTENSIONS = {
    ".dll", ".exe", ".so", ".dylib", ".bin", ".fbx", ".obj", ".blend", ".max", ".3ds",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".tga", ".psd", ".tif", ".tiff",
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".mp4", ".mov", ".avi", ".webm",
    ".asset", ".prefab", ".mat", ".unity", ".meta", ".anim", ".controller", ".mask",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".pdf", ".ttf", ".otf", ".woff", ".woff2",
}

def is_binary_or_asset_file(path_or_name: str) -> bool:
    """Return True if the target path is a non-code binary, multimedia, or serialized engine asset."""
    suffix = Path(path_or_name).suffix.lower()
    return suffix in BINARY_ASSET_EXTENSIONS

def asset_metadata_card(path: str, size_bytes: int = 0) -> str:
    """Return a token-efficient 1-line metadata card for assets instead of dumping raw/binary content."""
    p = Path(path)
    ext = p.suffix.lower()
    size_kb = size_bytes // 1024 if size_bytes > 0 else 0
    return f"/* [Binary/Asset Shield] {p.name} ({ext}, {size_kb} KB) — content omitted to conserve prompt tokens. */"

def prune_symbol_context(code: str, keep_symbols: list[str], language: str = "csharp") -> str:
    """Extract only classes/functions relevant to keep_symbols, pruning other top-level blocks."""
    if not code or not keep_symbols:
        return code
    
    clean_keep = {s.lower() for s in keep_symbols if s}
    lang = language.lower()
    
    if lang in ("csharp", "cs", "java", "ts", "typescript", "cpp"):
        def _filter_class(m: re.Match[str]) -> str:
            cls_name = m.group(1)
            body = m.group(0)
            if cls_name.lower() in clean_keep or any(k in cls_name.lower() for k in clean_keep):
                return body
            return f"class {cls_name} {{ /* [Context Pruned: unused in query] */ }}"
            
        pattern = re.compile(r"\bclass\s+([A-Za-z0-9_]+)[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
        return pattern.sub(_filter_class, code)
        
    return code
