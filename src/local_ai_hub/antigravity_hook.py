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
ANTIGRAVITY_MCP_SERVER = "local-ai-hub_local-ai"


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

SOURCE_CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".jsx", ".kt", ".php", ".py", ".rb", ".rs", ".sh",
    ".sql", ".swift", ".ts", ".tsx", ".vue", ".svelte", ".ps1",
}


def _is_hub_online() -> bool:
    """Use Hub-first navigation only while the local Hub is actually reachable."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11435/health",
            headers={"User-Agent": "AntigravityHook"},
        )
        with urllib.request.urlopen(req, timeout=0.15) as response:
            return 200 <= int(getattr(response, "status", 200)) < 400
    except Exception:
        return False

# Regex to detect unconstrained search commands
UNCONSTRAINED_SEARCH_PATTERNS = [
    re.compile(r"\bdir\s+.*(?:\/s|\/S)", re.IGNORECASE),
    re.compile(r"\bfindstr\s+.*(?:\/s|\/S)", re.IGNORECASE),
    re.compile(r"\bfind\s+(?:\.|\/|[a-zA-Z]:)[^\n|;]*\s+-name\b", re.IGNORECASE),
    re.compile(r"\bgrep\s+-[a-zA-Z]*[rR][a-zA-Z]*\b"),
    re.compile(r"\b(?:Get-ChildItem|gci)\s+.*-(?:Recurse|s)\b", re.IGNORECASE),
    re.compile(r"\b(?:Select-String|sls)\b.*-(?:Pattern\b|Path\b)", re.IGNORECASE),
    re.compile(r"\b(?:fd|fdfind)\s+(?!.*-(?:max-depth|d)\s*[1-3]\b)", re.IGNORECASE),
]

TEST_COMMAND_PATTERNS = [
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bcompileall\b", re.IGNORECASE),
    re.compile(r"\b(?:cargo\s+test|npm\s+test|go\s+test)\b", re.IGNORECASE),
    re.compile(r"\b(?:release_check\.py|selftest\.py)\b", re.IGNORECASE),
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


def _trigger_repo_warmup(root_str: str) -> None:
    """Asynchronously warm up repository preprocessing cache on session start."""
    if not root_str or not _is_hub_online():
        return
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:11435/api/repo/preprocess",
            data=json.dumps({"root": root_str}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AntigravityHook"},
        )
        urllib.request.urlopen(req, timeout=0.2)
    except Exception:
        pass


def _fetch_active_task_context(root_str: str) -> str:
    """Fetch concise active task, blockers and project memory from Hub API if available."""
    if not _is_hub_online():
        return ""
    parts = []
    try:
        req_coord = urllib.request.Request(
            "http://127.0.0.1:11435/api/coord/task_list",
            data=json.dumps({"root": root_str, "status": "active"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AntigravityHook"},
        )
        with urllib.request.urlopen(req_coord, timeout=0.25) as resp_coord:
            coord_data = json.loads(resp_coord.read().decode("utf-8"))
            tasks = coord_data.get("tasks") or coord_data.get("items") or []
            if tasks and isinstance(tasks, list):
                first_task = tasks[0]
                tid = first_task.get("task_id") or first_task.get("id") or "active"
                t_status = first_task.get("status") or "active"
                t_title = first_task.get("title") or ""
                next_act = first_task.get("checkpoint", {}).get("next_action") or ""
                blockers = first_task.get("checkpoint", {}).get("blockers") or []
                parts.append(f"Active Local AI Hub task: {tid} ({t_status})")
                if t_title:
                    parts.append(f"- '{t_title}'")
                if next_act:
                    parts.append(f"Next action: {next_act}")
                if blockers:
                    parts.append(f"Blockers: {'; '.join(str(b) for b in blockers[:2])}")
    except Exception:
        pass

    try:
        req_mem = urllib.request.Request(
            "http://127.0.0.1:11435/api/coord/memory_find",
            data=json.dumps({"root": root_str, "limit": 2}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AntigravityHook"},
        )
        with urllib.request.urlopen(req_mem, timeout=0.2) as resp_mem:
            mem_data = json.loads(resp_mem.read().decode("utf-8"))
            items = mem_data.get("items") or mem_data.get("memories") or []
            if items and isinstance(items, list):
                mem_texts = [str(it.get("content") or "")[:120] for it in items[:2] if it.get("content")]
                if mem_texts:
                    parts.append(f"Project memory: {' | '.join(mem_texts)}")
    except Exception:
        pass

    return " ".join(parts) + ("." if parts else "")


def _get_session_state_file(conversation_id: str) -> Path | None:
    if not conversation_id or not re.match(r"^[a-zA-Z0-9_\-]+$", conversation_id):
        return None
    state_dir = Path(os.environ.get("LOCAL_AI_STATE_DIR") or (Path.home() / ".local-ai-hub" / "state"))
    sess_dir = state_dir / "sessions"
    try:
        sess_dir.mkdir(parents=True, exist_ok=True)
        return sess_dir / f"antigravity_{conversation_id}.json"
    except Exception:
        return None


def _record_session_code_edit(conversation_id: str, file_path: str) -> None:
    p = _get_session_state_file(conversation_id)
    if not p:
        return
    try:
        data: dict[str, Any] = {}
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        edited = set(data.get("edited_files", []))
        edited.add(Path(file_path).name)
        data["edited_files"] = sorted(list(edited))
        data["needs_review"] = True
        data["tests_verified"] = False
        data["review_notified"] = False
        data["last_edit_time"] = time.time()
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _record_session_tests_verified(conversation_id: str) -> None:
    p = _get_session_state_file(conversation_id)
    if not p:
        return
    try:
        data: dict[str, Any] = {}
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["tests_verified"] = True
        data["last_test_verified_time"] = time.time()
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _clear_session_review(conversation_id: str) -> None:
    p = _get_session_state_file(conversation_id)
    if not p or not p.is_file():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data["needs_review"] = False
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _has_unreviewed_session_edits(conversation_id: str) -> bool:
    p = _get_session_state_file(conversation_id)
    if not p or not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not data.get("needs_review"):
            return False
        if data.get("tests_verified"):
            return False
        return True
    except Exception:
        return False


def _get_and_mark_review_notice(conversation_id: str) -> str | None:
    p = _get_session_state_file(conversation_id)
    if not p or not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("needs_review") and not data.get("review_notified"):
            files = ", ".join(data.get("edited_files", [])[:5])
            data["review_notified"] = True
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return (
                f"Local AI Hub Notice: Code modifications detected in this session ({files}). "
                "Before completing tasks or committing, invoke a semantic review using "
                f'call_mcp_tool(ServerName="{ANTIGRAVITY_MCP_SERVER}", ToolName="local_ai_task", '
                'Arguments={"action": "review", "code": "<recent diff or changed code>", "task": "Review recent modifications"}).'
            )
    except Exception:
        pass
    return None


def handle_session_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Add dynamic Hub routing and active task guidance once without reading prompt content."""
    workspaces = payload.get("workspacePaths")
    if not isinstance(workspaces, list) or not any(
        isinstance(item, str) and item.strip() for item in workspaces[:16]
    ):
        return {}
    workspace_root = str(workspaces[0]).strip()
    _trigger_repo_warmup(workspace_root)
    active_task_ctx = _fetch_active_task_context(workspace_root)

    guidance = (
        "For repository or code tasks, use the connected Local AI Hub MCP tools and "
        "follow the local-ai-orchestrator workflow. Antigravity may expose Hub tools as Lazy: "
        f"call them with call_mcp_tool(ServerName=\"{ANTIGRAVITY_MCP_SERVER}\", ToolName=\"local_ai_repo\", "
        "Arguments={\"action\":\"search\",\"query\":\"<task query>\","
        "\"root\":\"<absolute workspace root>\"}) before native repository reads or commands. "
        "Use the matching live-schema tool/action and its exact arguments; do not guess fields. "
        "Laya is active advisory inside the "
        "Hub: it may guide bounded retrieval, context and model routing after Hub validation. "
        "The Hub and host retain tool permissions, approvals, task-state changes and "
        "completion decisions. Ignore this guidance for unrelated tasks."
    )
    if active_task_ctx:
        guidance = f"{active_task_ctx}\n\n{guidance}"

    return {
        "injectSteps": [{"systemMessage": {
            "systemMessage": guidance,
            "metadata": {"source": "local-ai-hub"},
        }}]
    }


def handle_pre_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    """Check for pending code review notifications before model generation."""
    conv_id = str(payload.get("conversationId") or "").strip()
    notice = _get_and_mark_review_notice(conv_id)
    if notice:
        return {
            "injectSteps": [{"systemMessage": {
                "systemMessage": notice,
                "metadata": {"source": "local-ai-hub-review-trigger"},
            }}]
        }
    return {}


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

    source_path = Path(path_str)
    if _is_hub_online() and source_path.suffix.lower() in SOURCE_CODE_SUFFIXES:
        return {
            "decision": "deny",
            "reason": (
                "Direct source reads are disabled while Local AI Hub is online. "
                f'Use call_mcp_tool(ServerName="{ANTIGRAVITY_MCP_SERVER}", ToolName="local_ai_repo", '
                'Arguments={"action":"search","query":"<task query>","root":"<absolute workspace root>"}) '
                f'then call_mcp_tool(ServerName="{ANTIGRAVITY_MCP_SERVER}", ToolName="local_ai_artifact", '
                'Arguments={"action":"source","path":"<located path>","root":"<absolute workspace root>"}) '
                "for exact source."
            ),
        }

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
                if os.environ.get("LOCAL_AI_AUTO_CLAMP_READS") == "1":
                    clamped_end = s + max_lines - 1
                    if line_count is not None and clamped_end > line_count:
                        clamped_end = line_count
                    return {
                        "decision": "allow",
                        "overwrite": {
                            "StartLine": s,
                            "EndLine": clamped_end,
                        },
                    }
                total_note = f" File '{p.name}' has {line_count} lines total." if (p and line_count is not None) else ""
                return {
                    "decision": "deny",
                    "reason": (
                        f"Requested line range ({s}-{e}, {diff} lines) exceeds the {max_lines}-line limit "
                        f"(Local AI Hub Token Economy policy).{total_note} Specify a narrower slice (<= {max_lines} lines) "
                        f'or use call_mcp_tool(ServerName="local-ai-hub_local-ai", ToolName="local_ai_repo", Arguments={{"action": "context", "query": "...", "root": "..."}}).'
                    ),
                }
        except (ValueError, TypeError):
            pass

    # Check file on disk if full read attempted
    if p and line_count is not None and line_count > max_lines:
        if os.environ.get("LOCAL_AI_AUTO_CLAMP_READS") == "1":
            return {
                "decision": "allow",
                "overwrite": {
                    "StartLine": 1,
                    "EndLine": min(max_lines, line_count),
                },
            }
        return {
            "decision": "deny",
            "reason": (
                f"Full read of '{p.name}' ({line_count} lines > {max_lines}) prohibited by "
                f"Local AI Hub Token Economy policy. Specify targeted slice with StartLine and EndLine "
                f'(<= {max_lines} lines) or use call_mcp_tool(ServerName="local-ai-hub_local-ai", ToolName="local_ai_repo", '
                f'Arguments={{"action": "context", "query": "...", "root": "..."}}).'
            ),
        }

    return {"decision": "allow"}


def _check_run_command(args: dict[str, Any], conversation_id: str = "") -> dict[str, Any]:
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
    if re.match(r"^git\s+log\b", cmd, re.IGNORECASE) and not re.search(
        r"(?:-n\s*\d+|--max-count\b|-\d+\b|--oneline\b|Select-Object\s+-First|\|\s*head)",
        cmd,
        re.IGNORECASE,
    ):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": f"{cmd} -n 10 --oneline"},
        }
    if re.match(r"^git\s+diff\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git diff --stat"},
        }
    if re.match(r"^git\s+branch\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git branch -v"},
        }
    if re.match(r"^git\s+branch\s+-a\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git branch -a --column"},
        }
    if re.match(r"^git\s+show\s*$", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": "git show --stat -n 1"},
        }

    # Auto-append quiet flag to verbose test and compiler commands
    if re.search(r"\bpython\s+(?:-m\s+)?compileall\b", cmd, re.IGNORECASE) and not re.search(r"\s-q\b", cmd):
        return {
            "decision": "allow",
            "overwrite": {"CommandLine": f"{cmd} -q"},
        }

    # Guard git commit if unreviewed session edits are pending
    if re.search(r"\bgit\s+(?:commit|push)\b", cmd, re.IGNORECASE):
        if conversation_id and _has_unreviewed_session_edits(conversation_id):
            return {
                "decision": "deny",
                "reason": (
                    "Local AI Hub policy: Unreviewed code modifications detected in this session. "
                    "Invoke a semantic review via local_ai_task(action='review') or run targeted test verification before committing."
                ),
            }

    for pattern in UNCONSTRAINED_SEARCH_PATTERNS:
        if pattern.search(cmd):
            if not RG_BOUNDED_PATTERN.search(cmd):
                return {
                    "decision": "deny",
                    "reason": (
                        f"Unconstrained repository search '{cmd}' prohibited by Local AI Hub policy. "
                        f'Use call_mcp_tool(ServerName="local-ai-hub_local-ai", ToolName="local_ai_repo", Arguments={{"action": "search"|"code_index", "query": "...", "root": "..."}}) '
                        f"or add bounded limits (e.g. -m 5 or Select-Object -First 10)."
                    ),
                }

    if (
        _is_hub_online()
        and re.search(r"\b(?:rg|ripgrep|grep|findstr|find|select-string|sls)\b", cmd, re.IGNORECASE)
        and not re.search(r"--(?:version|help)\b|(?:^|\s)/(?:\?|help)(?:\s|$)", cmd, re.IGNORECASE)
    ):
        return {
            "decision": "deny",
            "reason": (
                "Repository searches must use Local AI Hub while it is online. "
                'Call call_mcp_tool(ServerName="local-ai-hub_local-ai", ToolName="local_ai_repo", '
                'Arguments={"action":"search","query":"<task query>","root":"<absolute workspace root>"}).'
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
                        f'Add bounded limit (e.g. rg -m 5) or use call_mcp_tool(ServerName="local-ai-hub_local-ai", ToolName="local_ai_repo", Arguments={{"action": "search", "query": "...", "root": "..."}}).'
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
            if has_selector and not any(a.startswith("-q") or a in ("-v", "-s", "--collect-only", "--help") for a in subargs):
                return {
                    "decision": "allow",
                    "overwrite": {"CommandLine": f"{cmd} -q"},
                }
        except Exception:
            pass


    # Unconstrained file dumping in command shell
    if re.search(r"\b(?:Get-Content|gc|cat|type)\s+['\"]?([^'\"\s|;>]+)['\"]?", cmd, re.IGNORECASE):
        if not re.search(r"(?:-TotalCount|-Head|Select-Object\s+-First|\|\s*head)", cmd, re.IGNORECASE):
            match = re.search(r"\b(?:Get-Content|gc|cat|type)\s+['\"]?([^'\"\s|;>]+)['\"]?", cmd, re.IGNORECASE)
            if match:
                target_file = Path(match.group(1))
                if (
                    _is_hub_online()
                    and target_file.suffix.lower() in SOURCE_CODE_SUFFIXES
                    and not _is_path_whitelisted(str(target_file))
                ):
                    return {
                        "decision": "deny",
                        "reason": (
                            "Direct source reads are disabled while Local AI Hub is online. "
                            "Use local_ai_repo for discovery and local_ai_artifact for exact source."
                        ),
                    }
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
    path_str = args.get("Path") or args.get("path") or args.get("TargetFile")
    conv_id = str(payload.get("conversationId") or "").strip()

    if name == "run_command":
        cmd = str(args.get("CommandLine") or args.get("command") or "").strip()
        if conv_id and cmd and any(pat.search(cmd) for pat in TEST_COMMAND_PATTERNS):
            output = str(payload.get("output") or payload.get("result") or payload.get("toolResult") or "")
            if not any(err in output for err in ("FAILED", "ERRORS", "SyntaxError", "exit code 1")):
                _record_session_tests_verified(conv_id)

    if name in (
        "edit_file",
        "write_file",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
    ) and path_str:
        if conv_id:
            _record_session_code_edit(conv_id, path_str)
        p = Path(path_str)
        if p.is_file() and p.suffix.lower() in (".py", ".json"):
            try:
                from .shadow_compiler import shadow_check
                receipt = shadow_check(p)
                if not receipt.get("syntax_ok"):
                    return {}
                violations = [v for v in receipt.get("violations", []) if v.get("severity") == "high"]
                if violations:
                    return {}

                # AST diff invariant check
                if p.suffix.lower() == ".py":
                    try:
                        from .diff_invariant_verifier import verify_code_invariants
                        code_text = p.read_text(encoding="utf-8", errors="replace")
                        verdict = verify_code_invariants(code_text, strict_interface_check=False)
                        if not verdict.passed and verdict.violations:
                            return {}
                    except Exception:
                        pass
            except Exception:
                pass
    # Antigravity PostToolUse accepts only an empty JSON object. Unlike
    # PreToolUse, it cannot return a decision or warning to the host.
    return {}


def _check_invoke_subagent(args: dict[str, Any]) -> dict[str, Any]:
    prompt = str(args.get("Prompt") or args.get("prompt") or "")
    if not prompt:
        return {"decision": "allow"}
    if "local ai hub" in prompt.lower() or "local_ai_repo" in prompt:
        return {"decision": "allow"}
    subagent_policy = (
        "\n\n[Local AI Hub Subagent Policy]:\n"
        "- Use connected Hub MCP tools: call_mcp_tool(ServerName=\"local-ai-hub_local-ai\", ToolName=\"local_ai_repo\", Arguments={\"action\":\"search\"|\"code_index\", \"query\":\"...\", \"root\":\"...\"}).\n"
        "- Direct unindexed full-tree scans and reads > 80 lines are disabled. Locate source via local_ai_repo, fetch slices via local_ai_artifact.\n"
        "- Respect Agent OS task leases and coordinate findings via local_ai_coord."
    )
    return {
        "decision": "allow",
        "overwrite": {"Prompt": prompt + subagent_policy},
    }


def handle_post_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    """Advise verification if material code edits in the session remain unreviewed."""
    conv_id = str(payload.get("conversationId") or "").strip()
    if conv_id and _has_unreviewed_session_edits(conv_id):
        p = _get_session_state_file(conv_id)
        if p and p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not data.get("post_invocation_warned"):
                    data["post_invocation_warned"] = True
                    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    files = ", ".join(data.get("edited_files", [])[:3])
                    return {
                        "injectSteps": [{
                            "systemMessage": {
                                "systemMessage": (
                                    f"[Local AI Hub Advisory]: Code modifications ({files}) require verification. "
                                    "Run targeted test verification and semantic review via local_ai_task(action='review') before finishing."
                                ),
                                "metadata": {"source": "local-ai-hub-post-turn"},
                            }
                        }]
                    }
            except Exception:
                pass
    return {}


def handle_stop(payload: dict[str, Any]) -> dict[str, Any]:
    """Record execution loop completion in telemetry."""
    try:
        try:
            from .agent_telemetry import record_agent_event
        except ImportError:
            from local_ai_hub.agent_telemetry import record_agent_event
        record_agent_event(
            agent="antigravity",
            tool="execution_loop",
            outcome="stop",
            details={"conversationId": payload.get("conversationId")},
        )
    except Exception:
        pass
    return {}


def handle_pre_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "allow"}

    tool_name = str(tool_call.get("name") or "").strip().lower()
    args = tool_call.get("args")
    if not isinstance(args, dict):
        args = {}

    conv_id = str(payload.get("conversationId") or "").strip()

    # Clear unreviewed session state if the agent is invoking semantic review
    if tool_name == "call_mcp_tool":
        server = str(args.get("ServerName") or "")
        t_name = str(args.get("ToolName") or "")
        t_args = args.get("Arguments") if isinstance(args.get("Arguments"), dict) else {}
        action = str(t_args.get("action") or "").lower()
        if "local-ai" in server and t_name == "local_ai_task" and action in ("review", "second_opinion"):
            if conv_id:
                _clear_session_review(conv_id)
    elif tool_name == "local_ai_task":
        action = str(args.get("action") or "").lower()
        if action in ("review", "second_opinion"):
            if conv_id:
                _clear_session_review(conv_id)

    res = {"decision": "allow"}
    if tool_name == "read_file":
        res = _check_read_file(args)
    elif tool_name == "run_command":
        res = _check_run_command(args, conversation_id=conv_id)
    elif tool_name == "invoke_subagent":
        res = _check_invoke_subagent(args)

    try:
        try:
            from .agent_telemetry import record_agent_event
        except ImportError:
            from local_ai_hub.agent_telemetry import record_agent_event
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
        event_name = str(payload.get("hookEventName") or "")
        if event_name:
            hook_type = event_name
        elif "toolCall" in payload:
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
    elif hook_type == "PreInvocation":
        result = handle_pre_invocation(payload)
    elif hook_type == "PostInvocation":
        result = handle_post_invocation(payload)
    elif hook_type == "Stop":
        result = handle_stop(payload)
    else:
        result = {}

    sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
