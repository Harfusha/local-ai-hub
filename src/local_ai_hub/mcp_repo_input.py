from __future__ import annotations

from typing import Any


def _normalize_repo_search_path_hints(
    root: str, path_hints: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    from . import mcp_server as services_module
    if not isinstance(path_hints, list):
        return None, "path_hints must be an array"
    if len(path_hints) > 64:
        return None, "path_hints exceeds 64 items"
    canonical = services_module._client_root(root)
    windows_root = services_module.PureWindowsPath(canonical)
    normalized: list[dict[str, Any]] = []
    for index, hint in enumerate(path_hints):
        if not isinstance(hint, services_module.Mapping):
            return None, f"path_hints[{index}] must be an object"
        raw_path = hint.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None, f"path_hints[{index}].path must be a non-empty string"
        try:
            if windows_root.drive:
                raw_windows = services_module.PureWindowsPath(raw_path.strip())
                if raw_windows.drive and not raw_windows.is_absolute():
                    raise ValueError("drive-relative hint")
                if raw_windows.drive or raw_windows.root:
                    candidate_text = str(raw_windows)
                    if raw_windows.root and not raw_windows.drive:
                        candidate_text = windows_root.drive + candidate_text
                else:
                    candidate_text = services_module.ntpath.join(str(windows_root), str(raw_windows))
                root_text = services_module.ntpath.normpath(str(windows_root))
                candidate_text = services_module.ntpath.normpath(candidate_text)
                common = services_module.ntpath.commonpath((root_text, candidate_text))
                if services_module.ntpath.normcase(common) != services_module.ntpath.normcase(root_text):
                    raise ValueError("hint escapes repository root")
                if services_module.os.name == "nt":
                    relative = services_module.Path(candidate_text).resolve().relative_to(services_module.Path(root_text).resolve())
                    relative_text = relative.as_posix()
                else:
                    relative_text = services_module.ntpath.relpath(candidate_text, root_text).replace("\\", "/")
            else:
                if services_module.PureWindowsPath(raw_path).drive:
                    raise ValueError("foreign drive hint")
                root_path = services_module.Path(canonical).resolve()
                raw_candidate = services_module.Path(raw_path.replace("\\", "/")).expanduser()
                if services_module.is_rooted_path(raw_path) and not raw_candidate.is_absolute():
                    raise ValueError("foreign rooted hint")
                candidate = raw_candidate if raw_candidate.is_absolute() else root_path / raw_candidate
                relative = candidate.resolve().relative_to(root_path)
                relative_text = relative.as_posix()
        except (OSError, RuntimeError, ValueError):
            return None, f"path_hints[{index}].path must resolve within root"
        hint_copy = dict(hint)
        hint_copy["path"] = relative_text or "."
        normalized.append(hint_copy)
    return normalized, None

def _validate_search_summary_citations(
    summary_text: Any,
    sources: list[dict[str, Any]],
    *,
    total_matches: Any = None,
) -> dict[str, Any]:
    from . import mcp_server as services_module
    if not isinstance(summary_text, str) or not summary_text.strip():
        return {"status": "rejected", "reason": "missing_source_citation"}
    summary_lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
    bullet_pattern = services_module.re.compile(r"(?:[-*+•]|\d+[.)])\s+\S.*")
    if not 1 <= len(summary_lines) <= 3 or any(not bullet_pattern.fullmatch(line) for line in summary_lines):
        return {"status": "rejected", "reason": "invalid_summary_structure"}
    bullet_citation_pattern = services_module.re.compile(r"\[[^\[\]]+:\s*[1-9]\d*(?:-[1-9]\d*)?\]")
    if any(bullet_citation_pattern.search(line) is None for line in summary_lines):
        return {"status": "rejected", "reason": "missing_source_citation"}
    if type(total_matches) is int and total_matches >= 0:
        count_terms = r"(?:total\s+)?(?:result|match|search|hit)\s+count|number\s+of\s+(?:matches|results)"
        unknown_terms = r"unknown|unavailable|unclear|not\s+(?:known|provided|available)|cannot\s+be\s+(?:determined|known)"
        contradictory_count = services_module.re.search(
            rf"(?:\b(?:{count_terms})\b[^.!?\n]{{0,48}}\b(?:{unknown_terms})\b"
            rf"|\b(?:{unknown_terms})\b[^.!?\n]{{0,48}}\b(?:{count_terms})\b)",
            summary_text,
            services_module.re.IGNORECASE,
        )
        if contradictory_count is not None:
            return {"status": "rejected", "reason": "contradictory_coverage_claim"}
    citation_like_pattern = services_module.re.compile(
        r"(?:[A-Za-z0-9_.-]+[/\\])+[A-Za-z0-9_.-]+\.[A-Za-z0-9_-]{1,12}:[1-9]\d*(?:-[1-9]\d*)?"
    )
    for reference in citation_like_pattern.finditer(summary_text):
        if reference.start() == 0 or reference.end() >= len(summary_text):
            return {"status": "rejected", "reason": "unverified_source_citation"}
        if summary_text[reference.start() - 1] != "[" or summary_text[reference.end()] != "]":
            return {"status": "rejected", "reason": "unverified_source_citation"}
    source_ranges: dict[str, list[tuple[int, int]]] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        path = source.get("path")
        start = source.get("start_line")
        end = source.get("end_line", start)
        if (
            not isinstance(path, str) or not path.strip()
            or type(start) is not int or type(end) is not int
            or start < 1 or end < start
        ):
            continue
        source_ranges.setdefault(path.strip().replace("\\", "/"), []).append((start, end))

    bracket_values = services_module.re.findall(r"\[([^\[\]]+)\]", summary_text)
    citation_candidates = [value.strip() for value in bracket_values if services_module.re.search(r":\s*\d", value)]
    if not citation_candidates:
        return {"status": "rejected", "reason": "missing_source_citation"}

    citation_pattern = services_module.re.compile(r"(.+?):([1-9]\d*)(?:-([1-9]\d*))?")
    for candidate in citation_candidates:
        match = citation_pattern.fullmatch(candidate)
        if match is None:
            return {"status": "rejected", "reason": "unverified_source_citation"}
        path = match.group(1).strip().replace("\\", "/")
        first_line = int(match.group(2))
        last_line = int(match.group(3) or match.group(2))
        if last_line < first_line or not any(
            first_line >= source_start and last_line <= source_end
            for source_start, source_end in source_ranges.get(path, [])
        ):
            return {"status": "rejected", "reason": "unverified_source_citation"}
    return {"status": "source_bound", "reference_count": len(citation_candidates)}

def _bounded_search_summary_input(
    query: Any,
    root: str,
    matches: list[Any],
    *,
    total_matches: Any = None,
    has_more: Any = None,
) -> tuple[str, list[dict[str, Any]]]:
    from . import mcp_server as services_module
    root_fingerprint = services_module.hashlib.sha256(services_module._client_root(root).encode("utf-8", errors="replace")).hexdigest()
    query_tokens = {token.casefold() for token in services_module.re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(query or ""))}
    payload: dict[str, Any] = {
        "root_fingerprint": root_fingerprint,
        "coverage_note": "",
        "matches": [],
    }

    def coverage_note(excerpt_count: int) -> str:
        coverage = []
        if type(total_matches) is int and total_matches >= 0:
            coverage.append(f"Exact total_matches: {total_matches}.")
        else:
            coverage.append("Exact total_matches unavailable.")
        coverage.append(f"Results returned: {len(matches)}.")
        coverage.append(f"Supplied excerpts: {excerpt_count}.")
        if type(has_more) is bool:
            if has_more:
                coverage.append("The search reports additional matching results beyond this response.")
            else:
                coverage.append("The search reports no additional matching results beyond this response.")
        coverage.append("Do not infer counts beyond these exact values or describe unshown results.")
        return " ".join(coverage)

    payload["coverage_note"] = coverage_note(0)
    sources: list[dict[str, Any]] = []
    serialized = services_module.json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for match in matches[:8]:
        if not isinstance(match, dict):
            continue
        source = {
            key: match[key]
            for key in ("path", "start_line", "end_line", "evidence_id")
            if isinstance(match.get(key), (str, int)) and not isinstance(match.get(key), bool)
        }
        entry_text = str(match.get("text", match.get("snippet", "")))[:1200]
        if query_tokens:
            text_lines = entry_text.splitlines()
            for line_index, line in enumerate(text_lines):
                numbered = services_module.re.match(r"^\s*(\d+):\s?(.*)$", line)
                if numbered is None:
                    continue
                definition = services_module.re.match(
                    r"(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(|class\s+([A-Za-z_]\w*)\b",
                    numbered.group(2).strip(),
                )
                if definition is None:
                    continue
                symbol = definition.group(1) or definition.group(2)
                line_number = int(numbered.group(1))
                if (
                    symbol.casefold() in query_tokens
                    and type(source.get("start_line")) is int
                    and type(source.get("end_line")) is int
                    and source["start_line"] <= line_number <= source["end_line"]
                ):
                    source["start_line"] = line_number
                    entry_text = "\n".join(text_lines[line_index:])
                    break
        entry = {**source, "text": entry_text}
        candidate = {
            **payload,
            "coverage_note": coverage_note(len(payload["matches"]) + 1),
            "matches": [*payload["matches"], entry],
        }
        candidate_text = services_module.json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        if len(candidate_text) > 12000:
            original_text = entry["text"]
            low, high = 0, len(original_text)
            best: tuple[str, str] | None = None
            while low <= high:
                mid = (low + high) // 2
                entry["text"] = original_text[:mid]
                trial = services_module.json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
                if len(trial) <= 12000:
                    best = (entry["text"], trial)
                    low = mid + 1
                else:
                    high = mid - 1
            if best is None:
                continue
            entry["text"], candidate_text = best
        payload["matches"].append(entry)
        serialized = candidate_text
        if source:
            sources.append(source)
    payload["coverage_note"] = coverage_note(len(payload["matches"]))
    serialized = services_module.json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return serialized, sources
