#!/usr/bin/env python3
"""CLI utility for inspecting Local AI Hub Agent Telemetry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_hub.agent_telemetry import get_agent_telemetry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local AI Hub Agent Activity Telemetry")
    parser.add_argument("--summary", action="store_true", help="Display aggregate agent activity summary")
    parser.add_argument("--tail", type=int, default=0, help="Display the N most recent agent events")
    parser.add_argument("--agent", type=str, default=None, help="Filter events by agent name")
    parser.add_argument("--mode", action="store_true", help="Show current telemetry mode")
    parser.add_argument("--set-mode", choices=["off", "minimal", "compact", "full"], help="Change telemetry mode")
    parser.add_argument("--json", action="store_true", help="Output raw JSON format")
    args = parser.parse_args(argv)

    rec = get_agent_telemetry()

    if args.set_mode:
        rec.set_mode(args.set_mode)
        print(f"Agent telemetry mode updated to: {rec.mode}")
        return 0

    if args.mode:
        print(f"Current telemetry mode: {rec.mode}")
        return 0

    if args.summary or (args.tail == 0 and not args.json):
        s = rec.summary()
        if args.json:
            print(json.dumps(s, indent=2))
            return 0
        print("=" * 60)
        print("Local AI Hub Agent Telemetry Summary")
        print("=" * 60)
        print(f"Telemetry Mode:         {s.get('mode', 'minimal')}")
        print(f"Total Logged Events:    {s['total_events']}")
        print(f"Total Est. Tokens:      {s['total_tokens_est']}")
        print(f"Total Tokens Saved:     {s['total_tokens_saved_est']}")
        print(f"Avg Latency (ms):       {s['avg_duration_ms']}")
        print("-" * 60)
        print("Activity by Agent:")
        for ag, cnt in s["agents"].items():
            print(f"  - {ag:<20}: {cnt} events")
        print("-" * 60)
        print("Response Profiles:")
        for pr, cnt in s["profiles"].items():
            print(f"  - {pr:<20}: {cnt} events")
        print("-" * 60)
        print("Outcomes:")
        for out, cnt in s["outcomes"].items():
            print(f"  - {out:<20}: {cnt} events")
        print("=" * 60)
        return 0

    if args.tail > 0:
        events = rec.query(agent=args.agent, limit=args.tail)
        if args.json:
            print(json.dumps(events, indent=2))
            return 0
        print(f"Displaying {len(events)} events (agent={args.agent or 'all'}):")
        for e in events:
            t = e.get("time_iso", "")
            ag = e.get("agent", "")
            tl = e.get("tool", "")
            act = e.get("action", "")
            out = e.get("outcome", "")
            prof = e.get("profile", "")
            dur = e.get("duration_ms", 0.0)
            print(f"[{t}] [{ag:<12}] tool={tl:<15} act={act:<12} prof={prof:<8} out={out:<6} dur={dur:>6.1f}ms")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
