"""Antigravity hooks for static Laya context and bounded tool-use policy.

SessionStart injects bounded, prompt-independent Hub/Laya guidance. PreToolUse
enforces the shared deterministic read/search policy; normal Laya routing runs
through the shared Hub MCP pipeline.
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


def _get_max_direct_read_lines() -> int:
    import os
    env_val = os.environ.get('LOCAL_AI_MAX_READ_LINES')
    if env_val:
        try:
            return max(10, int(env_val))
        except ValueError:
            pass
    return MAX_DIRECT_READ_LINES

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
    re.compile(r"\bgrep\s+-[a-zA-Z]*[rR][a-zA-Z]*\b"),
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


def handle_session_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Add static Hub routing guidance once without reading prompt content."""
    workspaces = payload.get("workspacePaths")
    if not isinstance(workspaces, list) or not any(
        isinstance(item, str) and item.strip() for item in workspaces[:16]
    ):
        return {}
    return {
        "injectSteps": [{"systemMessage": {
            "systemMessage": (
                "For repository or code tasks, use the connected Local AI Hub MCP tools and "
                "follow the local-ai-orchestrator workflow. Laya is active advisory inside the "
                "Hub: it may guide bounded retrieval, context and model routing after Hub validation. "
                "The Hub and host retain tool permissions, approvals, task-state changes and "
                "completion decisions. Ignore this guidance for unrelated tasks."
            ),
            "metadata": {"source": "local-ai-hub"},
        }}]
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
    max_lines = _get_max_direct_read_lines()

    p = None
    line_count = None
    try:
        p = Path(path_str)
        if p.is_file():
            with open(p, "rb") as f:
                line_count = sum(1 for _ in f)
    except Exception:
        pass

    if start_line is not None and end_line is not None:
        try:
            s = int(start_line)
            e = int(end_line)
            if e >= s:
                diff = e - s + 1
                if diff <= max_lines:
                    return {"decision": "allow"}
                total_note = f" File '{p.name}' has {line_count} lines total." if (p and line_count is not None) else ""
                return {
                    "decision": "deny",
                    "reason": (
                        f"Requested line range ({s}-{e}, {diff} lines) exceeds the {max_lines}-line limit "
                        f"(Local AI Hub Token Economy policy).{total_note} Specify a narrower slice (<= {max_lines} lines) "
                        f'or use call_mcp_tool(ServerName="local-ai", ToolName="local_ai_repo", Arguments={{"action": "context", "query": "...", "root": "..."}}).'
                    ),
                }
        except (ValueError, TypeError):
            pass

    # Check file on disk if full read attempted
    if p and line_count is not None and line_count > max_lines:
        return {
            "decision": "deny",
            "reason": (
                f"Full read of '{p.name}' ({line_count} lines > {max_lines}) prohibited by "
                f"Local AI Hub Token Economy policy. Specify targeted slice with StartLine and EndLine "
                f'(<= {max_lines} lines) or use call_mcp_tool(ServerName="local-ai", ToolName="local_ai_repo", '
                f'Arguments={{"action": "context", "query": "...", "root": "..."}}).'
            ),
        }

    return {"decision": "allow"}


def _check_run_command(args: dict[str, Any]) -> dict[str, Any]:
    cmd = str(args.get("CommandLine") or args.get("command") or "").strip()
    if not cmd:
        return {"decision": "allow"}

    # Proactive context-saving overwrites for verbose CLI commands
    if re.match(r"^git\s+status\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git status -s"},
        }
    if re.match(r"^git\s+log\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git log --oneline -n 10"},
        }
    if re.match(r"^git\s+diff\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git diff --stat"},
        }

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

    # Bare unconstrained pytest check (preventing freezing across 17,500+ tests)
    if re.search(r"\b(?:python\s+(?:-m\s+)?pytest|pytest)\b", cmd, re.IGNORECASE):
        parts = cmd.split()
        try:
            pt_idx = next(i for i, part in enumerate(parts) if "pytest" in part.lower())
            subargs = parts[pt_idx + 1:]
            has_selector = any(not a.startswith("-") or a in ("-m", "-k", "--run-all") for a in subargs)
            if not has_selector and subargs in ([], ["-q"], ["-v"], ["-s"]):
                return {
                    "decision": "deny",
                    "reason": (
                        f"Unconstrained bare pytest '{cmd}' across 17,500+ tests is blocked to prevent session freeze. "
                        f"Use targeted selectors (e.g. -m 'fast', -m 'critical', or a specific test file path)."
                    ),
                }
        except Exception:
            pass

    # Unconstrained file dumping in command shell
    if re.search(r"\b(?:Get-Content|gc|cat|type)\s+['\"]?([^'\"\s|;>]+)['\"]?", cmd, re.IGNORECASE):
        if not re.search(r"(?:-TotalCount|-Head|Select-Object\s+-First|\|\s*head)", cmd, re.IGNORECASE):
            match = re.search(r"\b(?:Get-Content|gc|cat|type)\s+['\"]?([^'\"\s|;>]+)['\"]?", cmd, re.IGNORECASE)
            if match:
                target_file = Path(match.group(1))
                if target_file.is_file() and target_file.name.lower() not in WHITELIST_FILENAMES:
                    try:
                        with target_file.open("r", encoding="utf-8", errors="ignore") as f:
                            lines = sum(1 for _ in zip(f, range(90)))
                            if lines > 80:
                                return {
                                    "decision": "deny",
                                    "reason": (
                                        f"Direct unconstrained dump of '{target_file.name}' (> 80 lines) via '{cmd}' is blocked by Token Economy. "
                                        f"Use targeted slice (Select-Object -First 80) or local_ai_artifact(action='slice')."
                                    ),
                                }
                    except Exception:
                        pass

    return {"decision": "allow"}


def handle_post_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = payload.get("toolCall", {})
    name = str(tool_call.get("name") or "").strip().lower()
    args = tool_call.get("args") or {}
    path_str = args.get("Path") or args.get("path")
    if name in ("edit_file", "write_file") and path_str:
        p = Path(path_str)
        if p.is_file() and p.suffix.lower() in (".py", ".json"):
            try:
                from .shadow_compiler import shadow_check
                receipt = shadow_check(p)
                if not receipt.get("syntax_ok"):
                    return {
                        "decision": "warn",
                        "warning": f"SYNTAX ERROR in {p.name}: {receipt.get('error')}. Fix immediately.",
                    }
                violations = [v for v in receipt.get("violations", []) if v.get("severity") == "high"]
                if violations:
                    return {
                        "decision": "warn",
                        "warning": f"INVARIANT VIOLATION in {p.name}: {violations[0].get('message')}.",
                    }

                # AST diff invariant check
                if p.suffix.lower() == ".py":
                    try:
                        from .diff_invariant_verifier import verify_code_invariants
                        code_text = p.read_text(encoding="utf-8", errors="replace")
                        verdict = verify_code_invariants(code_text, strict_interface_check=False)
                        if not verdict.passed and verdict.violations:
                            return {
                                "decision": "warn",
                                "warning": f"INVARIANT GATE in {p.name}: {'; '.join(verdict.violations[:2])}",
                            }
                    except Exception:
                        pass
            except Exception:
                pass
    return {"decision": "allow"}


def handle_pre_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}

    tool_name = str(tool_call.get("name") or "").strip().lower()
    args = tool_call.get("args")
    if not isinstance(args, dict):
        args = {}

    res = {"decision": "allow"}
    if tool_name == "read_file":
        res = _check_read_file(args)
    elif tool_name == "run_command":
        res = _check_run_command(args)

    try:
        from .agent_telemetry import record_agent_event
        record_agent_event(
            agent="antigravity",
            tool=tool_name,
            outcome=str(res.get("decision", "allow")),
            details={"stepIdx": payload.get("stepIdx"), "args": list(args.keys())},
        )
    except Exception:
        pass

    return res


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
        elif "workspacePaths" in payload:
            hook_type = "SessionStart"

    result: dict[str, Any]
    if hook_type == "SessionStart":
        result = handle_session_start(payload)
    elif hook_type == "PreToolUse":
        result = handle_pre_tool_use(payload)
    elif hook_type == "PostToolUse":
        result = handle_post_tool_use(payload)
    else:
        result = {"decision": "allow"}

    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
