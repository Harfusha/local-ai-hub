from __future__ import annotations

import json as _json
import math as _math
from pathlib import Path as _Path
from typing import Any


def build_profile_digest(
    profile_path: str,
    top_n: int = 15,
    *,
    path_type: Any = _Path,
    json_module: Any = _json,
    math_module: Any = _math,
) -> dict[str, Any]:
    p = path_type(profile_path).expanduser().resolve(strict=False)
    if not p.exists():
        return {"success": False, "error": f"profile file not found: {profile_path}"}

    limit = max(1, min(int(top_n), 100))
    entries: list[dict[str, Any]] = []

    try:
        import pstats
        stats = pstats.Stats(str(p))
        stats.sort_stats("cumulative")
        sorted_items = sorted(stats.stats.items(), key=lambda kv: kv[1][3], reverse=True)
        for (fn_file, fn_line, fn_name), (cc, nc, tt, ct, _callers) in sorted_items[:limit]:
            entries.append({
                "function": fn_name,
                "filename": path_type(fn_file).name,
                "filepath": fn_file,
                "line": fn_line,
                "calls": nc,
                "primitive_calls": cc,
                "total_time_seconds": round(float(tt), 4),
                "cumulative_time_seconds": round(float(ct), 4),
                "time_per_call": round(float(ct) / max(1, nc), 6),
            })
        return {
            "success": True,
            "profile_path": str(p),
            "format": "cProfile_pstats",
            "total_functions_analyzed": len(stats.stats),
            "top_functions": entries,
        }
    except Exception:
        entries.clear()

    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        data = json_module.loads(raw)
        if isinstance(data, dict) and "traceEvents" in data:
            events = data.get("traceEvents", [])
            if not isinstance(events, list):
                return {
                    "success": False,
                    "error": "failed to parse profile: traceEvents must be a JSON array",
                }
            durations: dict[str, float] = {}
            counts: dict[str, int] = {}
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                name = ev.get("name", "")
                raw_duration = ev.get("dur", 0)
                if not isinstance(name, str) or not name.strip():
                    continue
                if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
                    continue
                duration = float(raw_duration)
                if not math_module.isfinite(duration) or duration <= 0:
                    continue
                total_duration = durations.get(name, 0.0) + duration
                if not math_module.isfinite(total_duration):
                    continue
                durations[name] = total_duration
                counts[name] = counts.get(name, 0) + 1
            sorted_events = sorted(durations.items(), key=lambda kv: kv[1], reverse=True)
            for name, total_dur in sorted_events[:limit]:
                entries.append({
                    "function": name,
                    "cumulative_time_microseconds": round(total_dur, 2),
                    "calls": counts.get(name, 1),
                })
            return {
                "success": True,
                "profile_path": str(p),
                "format": "chrome_trace",
                "top_functions": entries,
            }
    except Exception:
        entries.clear()

    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 5 and parts[0].replace(".", "").isdigit():
                entries.append({"summary": line.strip()})
                if len(entries) >= limit:
                    break
        if not entries:
            return {"success": False, "error": "failed to parse profile: no profile records found"}
        return {
            "success": True,
            "profile_path": str(p),
            "format": "text_profile",
            "top_functions": entries,
        }
    except Exception as exc:
        return {"success": False, "error": f"failed to parse profile: {exc}"}

