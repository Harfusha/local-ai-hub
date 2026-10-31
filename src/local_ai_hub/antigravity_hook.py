"""Antigravity lifecycle hook handler for Local AI Hub.

Enforces Local AI Hub tool prioritization and Token Economy policy in Google Antigravity:
1. PreInvocation: Injects ephemeral instruction to prioritize local-ai MCP tools.
2. PreToolUse: Intercepts read_file (prohibiting full-file dumps > 80 lines) and
   run_command (prohibiting unconstrained broad repo searches), guiding the model
   to use local_ai_repo / local_ai_coord.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
import urllib.request

# Maximum file lines permitted for direct full reads in Antigravity
MAX_DIRECT_READ_LINES = 80

# Paths exempted from line limit (system, instructions, small configs, artifacts)
WHITELIST_PATH_PARTS = {
    ".gemini",
    "skills",
    "brain",
    ".system_generated",
    "artifacts",
}

WHITELIST_FILENAMES = {
    "agents.md",
    "gemini.md",
    "skill.md",
    ".local-ai.toml",
    ".local-ai.worktree.toml",
    "config.json",
    "settings.json",
    "hooks.json",
    "mcp_config.json",
    "pyproject.toml",
    "package.json",
    "cargo.toml",
    "go.mod",
    ".gitignore",
}

# Regex to detect unconstrained search commands
UNCONSTRAINED_SEARCH_PATTERNS = [
    re.compile(r"\bdir\s+.*(?:\/s|\/S)", re.IGNORECASE),
    re.compile(r"\bfindstr\s+.*(?:\/s|\/S)", re.IGNORECASE),
    re.compile(r"\bfind\s+(?:\.|\/|[a-zA-Z]:)[^\n|;]*\s+-name\b", re.IGNORECASE),
    re.compile(r"\bgrep\s+-[a-zA-Z]*[rR]\b"),
]

RG_BOUNDED_PATTERN = re.compile(
    r"(?:-m\s*\d+|-M\s*\d+|--max-count\b|Select-Object\s+-First|\|\s*head)",
    re.IGNORECASE,
)


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
        except Exception:
            pass
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _check_and_autostart_hub() -> bool:
    """If Local AI Hub is offline and supervisor is dead/not in error, trigger one-shot background start."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11435/health", headers={"User-Agent": "AntigravityHook"})
        with urllib.request.urlopen(req, timeout=0.8):
            return False
    except Exception:
        pass

    try:
        state_dir = Path(os.environ.get("LOCAL_AI_STATE_DIR") or (Path.home() / ".local-ai-hub" / "state"))
        if not state_dir.is_dir():
            return False

        if (state_dir / "service.disabled").is_file():
            return False

        cooldown_file = state_dir / ".hook_autostart_cooldown"
        now = time.time()
        if cooldown_file.is_file():
            try:
                last_ts = float(cooldown_file.read_text(encoding="utf-8").strip() or 0)
                if now - last_ts < 60.0:
                    return False
            except Exception:
                pass

        op_file = state_dir / "operational_mode.json"
        if op_file.is_file():
            try:
                op_data = json.loads(op_file.read_text(encoding="utf-8"))
                if op_data.get("degraded") is True or op_data.get("mode") in {"gaming", "maintenance"}:
                    return False
            except Exception:
                pass

        for marker in (state_dir / "supervisor.pid", state_dir / "supervisor.lock"):
            if marker.is_file():
                try:
                    text = marker.read_text(encoding="utf-8").strip()
                    if text.startswith("{"):
                        data = json.loads(text)
                        pid = int(data.get("pid") or 0)
                    else:
                        pid = int(text or 0)
                    if pid and _is_pid_alive(pid):
                        return False
                except PermissionError:
                    return False
                except Exception:
                    pass

        try:
            cooldown_file.write_text(str(now), encoding="utf-8")
        except Exception:
            pass

        repo_root = Path(__file__).resolve().parents[2]
        hubctl = repo_root / "tools" / "hubctl.py"
        if not hubctl.is_file():
            hubctl = Path.home() / ".local-ai-hub" / "tools" / "hubctl.py"

        if hubctl.is_file():
            flags = 0
            if sys.platform == "win32":
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(
                [sys.executable, str(hubctl), "start"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            return True
    except Exception:
        pass
    return False


def handle_pre_invocation(_payload: dict[str, Any]) -> dict[str, Any]:
    """Provide high-priority guidance to prioritize Local AI Hub MCP tools."""
    started = _check_and_autostart_hub()
    startup_note = "[Local AI Hub offline; auto-starting in background...]\n" if started else ""
    reminder = (
        startup_note +
        "[LOCAL AI HUB POLICY] Mandate: Prioritize local-ai MCP tools via "
        'call_mcp_tool(ServerName="local-ai", ToolName="<tool>", Arguments={...}).\n'
        '- Repository search / context / facts: call local_ai_repo(action="context"|"search"|"code_index"|"security_audit", root="...").\n'
        '- Task contracts, checkpoints, memory: call local_ai_coord(action="task_create"|"task_checkpoint"|"memory_record"|"memory_find", ...).\n'
        '- Code review, second opinion, reasoning: call local_ai_task(action="review"|"second_opinion"|"explore", ...).\n'
        '- Token economy: Never read full files >80 lines; use local_ai_repo or targeted line slices (StartLine/EndLine).'
    )
    return {
        "injectSteps": [
            {
                "ephemeralMessage": reminder
            }
        ]
    }


def _is_path_whitelisted(path_str: str) -> bool:
    try:
        norm = path_str.replace("\\", "/").lower()
        parts = set(norm.split("/"))
        if parts & WHITELIST_PATH_PARTS:
            return True
        filename = Path(norm).name
        if filename in WHITELIST_FILENAMES:
            return True
        if filename.endswith(".jsonl"):
            return True
    except Exception:
        pass
    return False


def _check_read_file(args: dict[str, Any]) -> dict[str, Any]:
    path_str = str(args.get("Path") or args.get("path") or "").strip()
    if not path_str:
        return {"decision": "allow"}

    if _is_path_whitelisted(path_str):
        return {"decision": "allow"}

    start_line = args.get("StartLine")
    end_line = args.get("EndLine")

    if start_line is not None and end_line is not None:
        try:
            s = int(start_line)
            e = int(end_line)
            if e >= s:
                diff = e - s + 1
                if diff <= MAX_DIRECT_READ_LINES:
                    return {"decision": "allow"}
                return {
                    "decision": "deny",
                    "reason": (
                        f"Requested line range ({s}-{e}, {diff} lines) exceeds the {MAX_DIRECT_READ_LINES}-line limit "
                        f"(Local AI Hub Token Economy policy). Specify a narrower slice (<= {MAX_DIRECT_READ_LINES} lines) "
                        f'or use call_mcp_tool(ServerName="local-ai", ToolName="local_ai_repo", Arguments={{"action": "context", "query": "...", "root": "..."}}).'
                    ),
                }
        except (ValueError, TypeError):
            pass

    # Check file on disk if full read attempted
    try:
        p = Path(path_str)
        if p.is_file():
            # Fast line count
            with open(p, "rb") as f:
                line_count = sum(1 for _ in f)
            if line_count > MAX_DIRECT_READ_LINES:
                return {
                    "decision": "deny",
                    "reason": (
                        f"Full read of '{p.name}' ({line_count} lines > {MAX_DIRECT_READ_LINES}) prohibited by "
                        f"Local AI Hub Token Economy policy. Specify targeted slice with StartLine and EndLine "
                        f'(<= {MAX_DIRECT_READ_LINES} lines) or use call_mcp_tool(ServerName="local-ai", ToolName="local_ai_repo", '
                        f'Arguments={{"action": "context", "query": "...", "root": "..."}}).'
                    ),
                }
    except Exception:
        pass

    return {"decision": "allow"}


def _check_run_command(args: dict[str, Any]) -> dict[str, Any]:
    cmd = str(args.get("CommandLine") or args.get("command") or "").strip()
    if not cmd:
        return {"decision": "allow"}

    for pattern in UNCONSTRAINED_SEARCH_PATTERNS:
        if pattern.search(cmd):
            return {
                "decision": "deny",
                "reason": (
                    f"Unconstrained repository search '{cmd}' prohibited by Local AI Hub policy. "
                    f'Use call_mcp_tool(ServerName="local-ai", ToolName="local_ai_repo", Arguments={{"action": "search"|"code_index", "query": "...", "root": "..."}}) '
                    f"or add bounded limits (e.g. -m 5)."
                ),
            }

    # ripgrep check
    if re.search(r"\b(?:rg|ripgrep)\b", cmd, re.IGNORECASE):
        if not RG_BOUNDED_PATTERN.search(cmd):
            # Check if it's just --version or --help
            if not re.search(r"--(?:version|help)\b", cmd):
                return {
                    "decision": "deny",
                    "reason": (
                        f"Unbounded ripgrep command '{cmd}' prohibited by Local AI Hub policy. "
                        f'Add bounded limit (e.g. rg -m 5) or use call_mcp_tool(ServerName="local-ai", ToolName="local_ai_repo", Arguments={{"action": "search", "query": "...", "root": "..."}}).'
                    ),
                }

    return {"decision": "allow"}


def handle_pre_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}

    tool_name = str(tool_call.get("name") or "").strip().lower()
    args = tool_call.get("args")
    if not isinstance(args, dict):
        args = {}

    if tool_name == "read_file":
        return _check_read_file(args)

    if tool_name == "run_command":
        return _check_run_command(args)

    return {"decision": "allow"}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    args = argv if argv is not None else sys.argv[1:]
    hook_type = args[0] if args else ""

    raw_input = ""
    try:
        raw_input = sys.stdin.read()
    except Exception:
        pass

    payload: dict[str, Any] = {}
    if raw_input.strip():
        try:
            parsed = json.loads(raw_input)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            pass

    if not hook_type:
        if "toolCall" in payload:
            hook_type = "PreToolUse"
        elif "invocationNum" in payload:
            hook_type = "PreInvocation"

    result: dict[str, Any]
    if hook_type == "PreInvocation":
        result = handle_pre_invocation(payload)
    elif hook_type == "PreToolUse":
        result = handle_pre_tool_use(payload)
    else:
        result = {"decision": "allow"}

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
