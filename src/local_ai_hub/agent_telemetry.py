"""Cross-Agent Activity Telemetry with Configurable Modes (off, minimal, compact, full).

Records, tracks, and analyzes runtime actions, token economies,
and response profiles across all connected agents:
Antigravity, Codex, Claude Code, Cursor, OpenCode, Windsurf, Copilot.

Modes:
- "off": Zero overhead, no memory tracking, no disk writes.
- "minimal": Instant in-memory atomic counters, zero disk I/O, no payload dumping.
- "compact": In-memory tracking + disk writes for rejections, warnings, and summary lines.
- "full": Comprehensive tracing, full arguments & details logged to disk JSONL.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

def _resolve_telemetry_dir() -> Path:
    env_dir = os.environ.get("LOCAL_AI_TELEMETRY_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    hub_dir = os.environ.get("LOCAL_AI_HUB_DIR")
    if hub_dir:
        candidate = Path(hub_dir) / ".local-ai-hub" / "telemetry"
        return candidate.resolve()
    return (Path(".local-ai-hub") / "telemetry").resolve()


def _resolve_telemetry_file() -> Path:
    env_file = os.environ.get("LOCAL_AI_TELEMETRY_LOG")
    if env_file:
        return Path(env_file).resolve()
    return _resolve_telemetry_dir() / "agents.jsonl"


DEFAULT_TELEMETRY_DIR = _resolve_telemetry_dir()
DEFAULT_LOG_FILE = _resolve_telemetry_file()


def _resolve_default_mode() -> str:
    # 1. Environment variable
    env_mode = os.environ.get("LOCAL_AI_TELEMETRY_MODE")
    if env_mode:
        return env_mode.strip().lower()

    # 2. Config file check
    hub_dir = os.environ.get("LOCAL_AI_HUB_DIR")
    candidates = [
        Path("config.toml"),
        Path(".local-ai-hub/config.toml"),
        Path("defaults.toml"),
    ]
    if hub_dir:
        h = Path(hub_dir)
        candidates.extend([
            h / "config.toml",
            h / ".local-ai-hub" / "config.toml",
            h / "defaults.toml",
        ])
    for cfg_candidate in candidates:
        if cfg_candidate.is_file():
            try:
                import tomllib
                data = tomllib.loads(cfg_candidate.read_text(encoding="utf-8"))
                mode = data.get("telemetry", {}).get("mode")
                if mode and str(mode).strip().lower() in ("off", "minimal", "compact", "full"):
                    return str(mode).strip().lower()
            except Exception:
                pass
    return "minimal"


class AgentTelemetryRecorder:
    """Thread-safe event recorder supporting off, minimal, compact, and full modes."""

    def __init__(
        self,
        log_path: Path | str | None = None,
        mode: Optional[str] = None,
    ):
        self.log_path = Path(log_path if log_path is not None else _resolve_telemetry_file()).resolve()
        self.mode = (mode or _resolve_default_mode()).strip().lower()
        self._lock = threading.Lock()
        self._mem_buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=2000)

        # In-memory counters for minimal mode (O(1) memory and latency)
        self._total_events = 0
        self._total_tokens_est = 0
        self._total_tokens_saved_est = 0
        self._total_duration_ms = 0.0
        self._agents: dict[str, int] = collections.defaultdict(int)
        self._profiles: dict[str, int] = collections.defaultdict(int)
        self._outcomes: dict[str, int] = collections.defaultdict(int)

        if self.mode in ("compact", "full"):
            self._ensure_dir()

    def _ensure_dir(self) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def set_mode(self, mode: str) -> None:
        """Switch telemetry recording mode at runtime."""
        m = mode.strip().lower()
        if m in ("off", "minimal", "compact", "full"):
            self.mode = m
            if self.mode in ("compact", "full"):
                self._ensure_dir()

    def record(
        self,
        agent: str,
        tool: str,
        action: str = "",
        profile: str = "compact",
        outcome: str = "allow",
        duration_ms: float = 0.0,
        tokens_est: int = 0,
        tokens_saved_est: int = 0,
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record an agent action event according to active telemetry mode."""
        if self.mode == "off":
            return {"recorded": False, "mode": "off"}

        ag_name = agent or "unknown"
        dur = round(float(duration_ms), 3)
        tok = int(tokens_est)
        saved = int(tokens_saved_est)
        prof = profile or "compact"
        outc = outcome or "allow"

        with self._lock:
            # Atomic in-memory accounting (always active in minimal, compact, full)
            self._total_events += 1
            self._total_tokens_est += tok
            self._total_tokens_saved_est += saved
            self._total_duration_ms += dur
            self._agents[ag_name] += 1
            self._profiles[prof] += 1
            self._outcomes[outc] += 1

            event: dict[str, Any] = {
                "timestamp": time.time(),
                "time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "agent": ag_name,
                "tool": tool or "unknown",
                "action": action or "",
                "profile": prof,
                "outcome": outc,
                "duration_ms": dur,
                "tokens_est": tok,
                "tokens_saved_est": saved,
            }

            # In minimal mode: do not store details and do NOT write to disk
            if self.mode == "minimal":
                self._mem_buffer.append(event)
                return event

            # In compact or full mode: attach details
            if self.mode == "full":
                event["details"] = details or {}
            elif details and outc != "allow":
                # In compact mode, only attach details for warnings, rejections, or errors
                event["details"] = details

            self._mem_buffer.append(event)

            # Disk write for compact / full modes
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception as exc:
                logger.debug("Failed appending to agent telemetry log: %s", exc)

        return event

    def query(
        self,
        agent: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve recent events from memory buffer or file."""
        if self.mode == "off":
            return []

        with self._lock:
            events = list(self._mem_buffer)

        # Fallback to reading file if in full/compact mode and buffer has fewer items
        if self.mode in ("compact", "full") and len(events) < limit and self.log_path.is_file():
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                    disk_events = [json.loads(line) for line in f if line.strip()]
                events = disk_events[-2000:]
            except Exception:
                pass

        if agent:
            events = [e for e in events if e.get("agent", "").lower() == agent.lower()]

        return events[-limit:]

    def summary(self) -> dict[str, Any]:
        """Calculate aggregate metrics across recorded agent operations."""
        with self._lock:
            total = self._total_events
            if total == 0:
                return {
                    "mode": self.mode,
                    "total_events": 0,
                    "agents": {},
                    "profiles": {},
                    "outcomes": {},
                    "total_tokens_est": 0,
                    "total_tokens_saved_est": 0,
                    "avg_duration_ms": 0.0,
                }

            return {
                "mode": self.mode,
                "total_events": total,
                "agents": dict(self._agents),
                "profiles": dict(self._profiles),
                "outcomes": dict(self._outcomes),
                "total_tokens_est": self._total_tokens_est,
                "total_tokens_saved_est": self._total_tokens_saved_est,
                "avg_duration_ms": round(self._total_duration_ms / total, 2),
            }


_RECORDER: Optional[AgentTelemetryRecorder] = None


def get_agent_telemetry() -> AgentTelemetryRecorder:
    global _RECORDER
    if _RECORDER is None:
        _RECORDER = AgentTelemetryRecorder()
    return _RECORDER


def record_agent_event(
    agent: str,
    tool: str,
    action: str = "",
    profile: str = "compact",
    outcome: str = "allow",
    duration_ms: float = 0.0,
    tokens_est: int = 0,
    tokens_saved_est: int = 0,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Top-level helper to log an agent event."""
    rec = get_agent_telemetry()
    return rec.record(
        agent=agent,
        tool=tool,
        action=action,
        profile=profile,
        outcome=outcome,
        duration_ms=duration_ms,
        tokens_est=tokens_est,
        tokens_saved_est=tokens_saved_est,
        details=details,
    )
