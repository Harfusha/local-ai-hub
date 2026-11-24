"""Windsurf Cascade hooks for bounded command, read, MCP, and edit checks."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from local_ai_hub.repo_plan.host_hooks import _check_codex_tool_use

MAX_INPUT_BYTES = 65536
MAX_COMMAND_BYTES = 16000
MAX_PATH_BYTES = 4096


def _shadow_check(file_path: str) -> dict[str, Any]:
    from .shadow_compiler import shadow_check

    return shadow_check(file_path)


def _policy_decision(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or len(payload) > 64:
        raise ValueError("invalid Windsurf hook payload")
    event = payload.get("agent_action_name")
    info = payload.get("tool_info")
    if event not in {
        "pre_run_command", "pre_read_code", "pre_mcp_tool_use", "post_write_code",
    } or not isinstance(info, dict):
        raise ValueError("unsupported Windsurf hook event")
    if event == "pre_run_command":
        command = info.get("command_line")
        if not isinstance(command, str) or len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise ValueError("invalid Windsurf command payload")
        return _check_codex_tool_use("Bash", {"command": command})

    if event == "pre_mcp_tool_use":
        server_name = info.get("mcp_server_name")
        if not isinstance(server_name, str) or len(server_name.encode("utf-8")) > 128:
            raise ValueError("invalid Windsurf MCP server name")
        if server_name != "local-ai":
            return {}
        tool_name = info.get("mcp_tool_name")
        arguments = info.get("mcp_tool_arguments")
        if (
            not isinstance(tool_name, str)
            or len(tool_name) > 128
            or not isinstance(arguments, dict)
            or len(arguments) > 64
        ):
            raise ValueError("invalid Local AI Hub MCP call")
        from .operation_contracts import operation_contract, validate_operation_call

        if operation_contract(tool_name) is None:
            return {"decision": "deny", "reason": "Unknown Local AI Hub MCP tool."}
        try:
            validation_error = validate_operation_call(tool_name, arguments)
        except Exception as exc:
            raise ValueError("Local AI Hub MCP arguments could not be validated") from exc
        if validation_error is not None:
            status, _message = validation_error
            return {
                "decision": "deny",
                "reason": f"Invalid Local AI Hub MCP request (contract status {status}); correct its arguments before retrying.",
            }
        return {}

    file_path = info.get("file_path")
    if not isinstance(file_path, str) or len(file_path.encode("utf-8")) > MAX_PATH_BYTES:
        raise ValueError("invalid Windsurf file payload")
    if event == "post_write_code":
        if Path(file_path).suffix.lower() not in {".py", ".json"}:
            return {}
        try:
            receipt = _shadow_check(file_path)
        except Exception as exc:
            return {
                "decision": "warn",
                "warning": f"Local AI Hub could not check {Path(file_path).name}: {type(exc).__name__}.",
            }
        if not receipt.get("syntax_ok"):
            return {
                "decision": "warn",
                "warning": f"SYNTAX ERROR in {Path(file_path).name}: {receipt.get('error') or 'invalid syntax'}.",
            }
        violations = [
            v for v in receipt.get("violations", [])
            if isinstance(v, dict) and v.get("severity") == "high"
        ]
        if violations:
            return {
                "decision": "warn",
                "warning": f"INVARIANT VIOLATION in {Path(file_path).name}: {violations[0].get('message', 'high-severity invariant failed')}.",
            }
        return {}
    return _check_codex_tool_use("read_file", {"path": file_path})


def main() -> int:
    try:
        raw = sys.stdin.read(MAX_INPUT_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("Windsurf hook payload exceeds its limit")
        payload = json.loads(raw)
        decision = _policy_decision(payload)
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"Local AI Hub: Windsurf hook could not evaluate this request: {exc}", file=sys.stderr)
        return 2
    if decision.get("decision") == "deny":
        print(str(decision.get("reason") or "Blocked by Local AI Hub policy."), file=sys.stderr)
        return 2
    if decision.get("decision") == "warn":
        print(str(decision.get("warning") or "Local AI Hub static check reported a warning."), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
