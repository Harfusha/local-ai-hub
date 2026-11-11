from __future__ import annotations

import re
from typing import Any


_TRACEBACK_RE = re.compile(
    r"(Traceback\s*(?:\(most recent call last\))?:\s*\n"
    r"(?:[ \t]+File\s+[^\n]+\n(?:[ \t]+[^\n]+\n)*)+"
    r"(?:[a-zA-Z_][a-zA-Z0-9_.]*(?::[^\n]*)?))",
    re.MULTILINE,
)


def cluster_stack_traces(text: str) -> dict[str, Any]:
    """Find and group repetitive stack traces into clusters."""
    if not isinstance(text, str) or not text:
        return {"total_traces": 0, "clusters": [], "unique_clusters": 0}

    matches = list(_TRACEBACK_RE.finditer(text))
    if not matches:
        return {"total_traces": 0, "clusters": [], "unique_clusters": 0}

    cluster_map: dict[str, dict[str, Any]] = {}
    for match in matches:
        tb_text = match.group(1).rstrip()
        lines = tb_text.splitlines()
        exception_line = lines[-1].strip() if lines else "Error"
        if ":" in exception_line:
            exc_type, exc_msg = exception_line.split(":", 1)
            exc_type = exc_type.strip()
            exc_msg = exc_msg.strip()
        else:
            exc_type = exception_line.strip()
            exc_msg = ""

        norm_frames: list[str] = []
        for line in lines[1:-1]:
            if "File " in line and "in " in line:
                norm_frames.append(re.sub(r", line \d+,", ",", line.strip()))
        signature = "\n".join(norm_frames + [exception_line])

        if signature not in cluster_map:
            cluster_map[signature] = {
                "signature": signature,
                "exception_type": exc_type,
                "exception_message": exc_msg,
                "count": 0,
                "representative": tb_text,
                "occurrences": [],
            }
        cluster_map[signature]["count"] += 1
        cluster_map[signature]["occurrences"].append((match.start(), match.end()))

    clusters = list(cluster_map.values())
    return {
        "total_traces": len(matches),
        "clusters": clusters,
        "unique_clusters": len(clusters),
    }


def deduplicate_stack_traces(
    text: str,
    max_repeats: int = 1,
) -> tuple[str, dict[str, Any]]:
    """Deduplicate repetitive stack traces, keeping first max_repeats occurrences per cluster."""
    if not isinstance(text, str) or not text:
        return text, {
            "clusters": [],
            "total_traces": 0,
            "total_collapsed": 0,
            "chars_saved": 0,
            "unique_clusters": 0,
        }

    clustered = cluster_stack_traces(text)
    clusters = clustered["clusters"]
    total_traces = clustered["total_traces"]

    if total_traces <= 1 or not any(c["count"] > max_repeats for c in clusters):
        return text, {
            "clusters": clusters,
            "total_traces": total_traces,
            "total_collapsed": 0,
            "chars_saved": 0,
            "unique_clusters": len(clusters),
        }

    to_replace: list[tuple[int, int, str]] = []
    total_collapsed = 0
    for idx, cluster in enumerate(clusters):
        count = cluster["count"]
        if count > max_repeats:
            for start, end in cluster["occurrences"][max_repeats:]:
                replacement = f"[... identical stack trace omitted (cluster #{idx + 1}, repeated {count} times) ...]"
                to_replace.append((start, end, replacement))
                total_collapsed += 1

    to_replace.sort(key=lambda item: item[0], reverse=True)
    compacted = text
    for start, end, replacement in to_replace:
        compacted = compacted[:start] + replacement + compacted[end:]

    chars_saved = max(0, len(text) - len(compacted))
    return compacted, {
        "clusters": clusters,
        "total_traces": total_traces,
        "total_collapsed": total_collapsed,
        "chars_saved": chars_saved,
        "unique_clusters": len(clusters),
    }
