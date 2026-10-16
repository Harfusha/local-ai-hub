from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient


def clear() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")


def _format_time(created_at: Any) -> str:
    try:
        val = float(created_at or 0)
        if not math.isfinite(val) or val <= 0:
            return "00:00:00"
        return time.strftime("%H:%M:%S", time.localtime(val))
    except (ValueError, OSError, OverflowError, TypeError):
        return "00:00:00"


def format_monitor_header(status: dict[str, Any] | None) -> str:
    if not isinstance(status, dict):
        status = {}
    h = status.get("headless") or {}
    hub_state = "UP" if status.get("hub_online") else "DOWN"
    ollama_state = "UP" if status.get("ollama_online") else "DOWN"
    sup_state = h.get("state", "unknown")
    restarts = h.get("restarts", 0)
    return f"Hub: {hub_state}  Ollama: {ollama_state}  Supervisor: {sup_state}  Restarts: {restarts}"


def format_event_line(e: dict[str, Any] | None) -> str:
    if not isinstance(e, dict):
        return ""
    ts = _format_time(e.get("created_at"))
    flags = (
        (" CACHE" if e.get("cache_hit") else "")
        + (" FALLBACK" if e.get("fallback_used") else "")
        + (" DEGRADED" if e.get("degraded") else "")
    )
    agent = str(e.get("agent") or e.get("kind", ""))[:10]
    stage = str(e.get("stage") or e.get("event_type", ""))[:12]
    model = str(e.get("model") or e.get("cache_layer", ""))[:22]
    action = str(e.get("action") or e.get("operation") or "")[:62]
    return f"{ts} {agent:10} {stage:12} {model:22} {action}{flags}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Realtime Local AI Hub monitor")
    ap.add_argument("--interval", type=float, default=0.75)
    ap.add_argument("--json-lines", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    c = HubClient(tenant="human-monitor", config_path=str(ROOT / "config.toml"))
    cursor = 0

    while True:
        try:
            status = c.get("/api/live/status")
            if not isinstance(status, dict):
                status = {}
        except Exception:
            status = {}

        try:
            live = c.get(f"/api/live?after={cursor}&limit=200")
            if not isinstance(live, dict):
                live = {}
        except Exception:
            live = {}

        cursor = int(live.get("cursor", cursor) or cursor)

        if a.json_lines:
            for e in live.get("events", []):
                if isinstance(e, dict):
                    print(json.dumps(e, ensure_ascii=False), flush=True)
        else:
            clear()
            q = status.get("scheduler") or {}
            o = status.get("observability") or {}
            p = status.get("preprocessing") or {}
            print("LOCAL AI HUB — REALTIME  (Ctrl+C to exit)")
            print(format_monitor_header(status))
            print(
                f"Model: {q.get('active_model') or 'idle'}  "
                f"Queue: {q.get('queued', 0) or 0}  "
                f"Inflight: {q.get('inflight', 0) or 0}  "
                f"Active requests: {o.get('active_request_count', 0) or 0}  "
                f"Background: {q.get('background_queued', 0) or 0}"
            )
            print(
                f"Cache hit: {100 * float(o.get('cache_hit_rate') or 0):.1f}%  "
                f"p95: {float(o.get('p95_duration_ms') or 0):.0f} ms  "
                f"Net cloud delta: {int(o.get('net_cloud_token_delta_est') or 0):,}  "
                f"Fallbacks: {o.get('fallback_count', 0) or 0}"
            )
            print(
                f"Token accounting: gross={int(o.get('gross_cloud_tokens_avoided_est') or 0):,}  "
                f"protocol={int(o.get('agent_protocol_tokens_est') or 0):,} "
                f"(call={int(o.get('agent_tool_request_tokens_est') or 0):,}, "
                f"read={int(o.get('agent_tool_response_tokens_est') or 0):,})  "
                f"schema≈{int(o.get('tool_schema_tokens_exposure_est') or 0):,}  "
                f"local-compute={int(o.get('local_compute_tokens_avoided_est') or 0):,}"
            )
            print(
                f"Preprocess: {'paused' if p.get('paused') else 'active'} · "
                f"steps={p.get('steps', 0) or 0} errors={p.get('errors', 0) or 0} "
                f"yields={p.get('yields', 0) or 0}"
            )
            for pr in p.get("projects") or []:
                if not isinstance(pr, dict):
                    continue
                tot = max(1, int(pr.get("files") or 0))
                rag_f = int(pr.get("rag_files") or 0)
                card_f = int(pr.get("file_cards") or 0)
                overall = float(pr.get("overall_progress_pct") or 0)
                p_idx = pr.get("phase_index", "?")
                p_tot = pr.get("total_phases", 11)
                phase_name = pr.get("phase", "idle")
                status_str = pr.get("status", "queued")
                print(
                    f"  • {pr.get('project')}: [{status_str.upper()}] Phase {p_idx}/{p_tot} "
                    f"({phase_name}) — overall: {overall:.1f}% | RAG: {rag_f}/{tot} "
                    f"({rag_f * 100 // tot}%) | Cards: {card_f}/{tot}"
                )
            print("\nRecent activity:")
            for e in list(live.get("events") or [])[-18:]:
                line = format_event_line(e)
                if line:
                    print(line)

        if a.once:
            return 0
        time.sleep(max(0.2, a.interval))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
