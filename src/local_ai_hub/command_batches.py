"""Validate complete parallel batches before dispatching through the command broker."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable


_OPTIONS = frozenset({
    "cwd", "timeout", "force", "task_id", "criterion", "record_verification",
    "auto_fix", "fix_generator", "max_repair_attempts", "snapshot",
    "rollback_on_failure", "sandbox", "docker_image", "bypass_cache", "paths",
    "rollback_paths", "project_context", "env", "_environment_overrides",
    "_cache_context", "_transaction_context", "_work_attempt_fence",
    "_project_command_context", "request_cancel_event", "stdin", "input",
})


def run_parallel(
    run: Callable[..., dict[str, Any]], commands: list[dict[str, Any] | str], *,
    cwd: str | None, max_concurrency: int, timeout: int | None, multiplexer: Any,
) -> dict[str, Any]:
    def invalid(message: str) -> dict[str, Any]:
        return {"success": False, "error": message, "results": {}, "preflight": True,
                "request_not_sent": True, "terminal": True, "retryable": False}

    if not isinstance(commands, list) or not 1 <= len(commands) <= 64:
        return invalid("commands must contain between 1 and 64 entries")
    if type(max_concurrency) is not int or not 1 <= max_concurrency <= 32:
        return invalid("max_concurrency must be an integer between 1 and 32")
    normalized = []
    ids = set()
    for index, item in enumerate(commands):
        options: dict[str, Any] = {}
        identity = f"cmd-{index + 1}"
        if isinstance(item, str):
            command = item
        elif isinstance(item, dict):
            if set(item) - (_OPTIONS | {"id", "cmd", "command"}):
                return invalid("parallel command contains unsupported options")
            if ("cmd" in item) == ("command" in item):
                return invalid("parallel command requires exactly one command field")
            identity = item.get("id", identity)
            command = item.get("command") if "command" in item else item.get("cmd")
            options = {key: value for key, value in item.items() if key in _OPTIONS}
        else:
            return invalid("parallel command must be a string or object")
        if not isinstance(identity, str) or not identity or identity != identity.strip() or "\0" in identity or len(identity) > 128:
            return invalid("parallel command id must be a bounded canonical string")
        if identity in ids:
            return invalid("parallel command ids must be unique")
        if not isinstance(command, str) or not command.strip() or "\0" in command:
            return invalid("parallel command text must be a nonempty string")
        ids.add(identity)
        normalized.append((identity, command, options))

    def execute(identity: str, command: str, options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        forwarded = {"cwd": cwd or ".", "timeout": timeout, **options}
        forwarded["log_callback"] = lambda stream, chunk: multiplexer.write(identity, stream, chunk)
        try:
            result = run(command, **forwarded)
            if not isinstance(result, dict) or type(result.get("success")) is not bool:
                result = {"success": False, "error": "parallel command returned an invalid result"}
        except Exception as exc:
            result = {"success": False, "error": f"parallel command failed ({type(exc).__name__})",
                      "terminal": True, "retryable": False}
        return identity, result

    results = {}
    with ThreadPoolExecutor(max_workers=min(max_concurrency, len(normalized))) as executor:
        futures = [executor.submit(execute, *entry) for entry in normalized]
        for future in as_completed(futures):
            identity, result = future.result()
            results[identity] = result
    multiplexer.flush()
    return {
        "success": len(results) == len(normalized) and all(row.get("success") is True for row in results.values()),
        "results": results, "commands_requested": len(normalized), "commands_completed": len(results),
        "multiplexed_output": multiplexer.format_unified(tag_prefix=True),
        "events": [event.to_dict() for event in multiplexer.get_events()],
    }
