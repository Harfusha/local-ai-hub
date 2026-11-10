"""Host adapters, capability probes, and managed instruction injection for Superpowers & agents."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
import hashlib
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PLANNER_BLOCK_START = "<!-- BEGIN LOCAL AI HUB PLANNER -->"
PLANNER_BLOCK_END = "<!-- END LOCAL AI HUB PLANNER -->"

MANAGED_PLANNER_INSTRUCTIONS = f"""{PLANNER_BLOCK_START}
## LOCAL AI HUB FILE-BACKED PROJECT PLANNER & AGENT WORKFLOW
- **Authoritative Plans**: All project goals, tasks, dependencies, and deliverables are stored in `.local-ai-hub/plans/<plan-id>.plan.json`.
- **Single Source of Truth**: NEVER create secondary or competing Markdown plans (e.g., `PLAN.md`, `TODO.md`, `tasks.md`) for repository work. Always use the file-backed planner via `local_ai_coord(action="plan_*")`.
- **Pre-execution Resolution**: Always resolve the repository root before starting work. Adopt or reuse an existing plan and task rather than duplicating goals.
- **Contract & Clarifications**: Create or update the specification through Superpowers. For changed requirements, record the clarification on the task and call `plan_reconcile_steering` with a stable steering ID, current plan revision, current spec revision, spec path/content, summary, and acceptance criteria before dependent edits when exposed by the active MCP schema. If unavailable, use the Hub's supported project-plan interface or report the precise blocker; never edit plan storage directly.
- **Agent OS Checkpoint Sync**: Checkpoint progress through `local_ai_coord(action="task_checkpoint")`. Bound tasks automatically synchronize progress, phase, next action, and blockers to the plan file.
- **Checkpoint Recovery**: If a checkpoint persisted but plan sync failed, resolve the error, reread the plan revision, and call `plan_bind_task` again with the same task and session. `checkpoint_sync="reconciled"` confirms the pending projection was applied; `not_pending` does not prove the task and plan agree. Do not overwrite conflicting plan edits or repeat the persisted task mutation.
- **Kanban & Briefings**: Board views (`board_summary`, `board_item_list`) and `session_briefing` reflect the authoritative plan files.
- **Authentic Verification**: Use `plan_validate` for plan validity; it does not replace authentic per-criterion command receipts. Complete bound tasks through the receipt-gated Agent OS workflow.
- **Interruption & Resumption**: On interruption, preserve explicit blockers and next actions in the checkpoint rather than restarting with a blank plan.
{PLANNER_BLOCK_END}"""


@dataclass(frozen=True)
class HostCapabilityReport:
    """Named capability levels for an agent host."""
    host_name: str
    file_management: bool
    instructions_integrated: bool
    workflow_interception: bool
    support_level: str  # "enforced", "advisory", "unsupported"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HostVerificationStatus(str, Enum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    UNSUPPORTED = "unsupported"


class HostOperationStatus(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNSUPPORTED = "unsupported"
    UNCERTAIN = "uncertain"
    SHADOW_ONLY = "shadow_only"


class HostConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


def _contract_token(value: str, name: str, *, limit: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"invalid {name}")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError(f"invalid {name}")
    return value


def _contract_code(value: str, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value):
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class HostCapabilitySnapshot:
    """Evidence-backed capability state for one host-owned session surface."""

    host_name: str
    host_version: str
    surface: str
    session_type: str
    hub_managed: bool
    available_events: tuple[str, ...] = ()
    available_commands: tuple[str, ...] = ()
    available_permissions: tuple[str, ...] = ()
    permission_mode: str = "unknown"
    permissions_verified: bool = False
    would_be_denied: bool | None = None
    verification_status: HostVerificationStatus = HostVerificationStatus.NOT_VERIFIED
    connection_status: HostConnectionStatus = HostConnectionStatus.UNKNOWN

    def __post_init__(self) -> None:
        for name in ("host_name", "host_version", "surface", "session_type", "permission_mode"):
            _contract_token(getattr(self, name), name)
        if not isinstance(self.hub_managed, bool) or not isinstance(self.permissions_verified, bool):
            raise ValueError("host ownership and permission verification must be booleans")
        if self.would_be_denied is not None and not isinstance(self.would_be_denied, bool):
            raise ValueError("would_be_denied must be a boolean or None")
        try:
            state = HostVerificationStatus(self.verification_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid host verification status") from exc
        object.__setattr__(self, "verification_status", state)
        try:
            connection = HostConnectionStatus(self.connection_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid host connection status") from exc
        object.__setattr__(self, "connection_status", connection)
        for field_name in ("available_events", "available_commands", "available_permissions"):
            values = getattr(self, field_name)
            if not isinstance(values, (tuple, list)) or len(values) > 128:
                raise ValueError(f"invalid {field_name}")
            labels = tuple(_contract_token(item, field_name, limit=120) for item in values)
            if any(
                item.startswith("/") or "\\" in item or re.match(r"^[A-Za-z]:", item)
                for item in labels
            ):
                raise ValueError(f"{field_name} must contain names, not paths")
            object.__setattr__(self, field_name, labels)


@dataclass(frozen=True)
class HostShadowRequest:
    """Metadata-only proposal. No prompt, transcript, output, or source fields."""

    host_name: str
    host_version: str
    surface: str
    session_type: str
    session_id: str
    repository_id: str
    event_id: str
    event_type: str
    proposed_action: str
    reason_code: str
    task_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    mode: str = "shadow"
    token_usage: HostTokenUsage | None = None
    source_sequence: int | None = None
    source_stream_ref: str | None = None
    source_result: str | None = None
    proposal_status: str = "proposed"
    source_task_status: str | None = None
    source_has_blockers: bool | None = None
    source_has_next_action: bool | None = None

    def __post_init__(self) -> None:
        for name in ("host_name", "host_version", "surface", "session_type", "session_id", "event_id"):
            _contract_token(getattr(self, name), name)
        for name in ("event_type", "proposed_action", "reason_code"):
            _contract_token(getattr(self, name), name, limit=80)
        if not re.fullmatch(r"[a-f0-9]{64}", self.repository_id):
            raise ValueError("invalid repository_id")
        _contract_code(self.proposed_action, "proposed_action")
        _contract_code(self.reason_code, "reason_code")
        if self.proposal_status not in {"proposed", "not_proposed"}:
            raise ValueError("invalid proposal_status")
        if (self.proposal_status == "not_proposed") != (self.proposed_action == "none"):
            raise ValueError("proposal_status and proposed_action disagree")
        source_fields = (
            self.source_task_status,
            self.source_has_blockers,
            self.source_has_next_action,
        )
        if any(value is not None for value in source_fields):
            if (
                self.host_name != "local-ai-hub"
                or self.surface != "agent_os"
                or self.session_type != "task"
                or self.source_task_status not in {
                    "draft", "planned", "active", "verifying", "completed",
                    "waiting", "blocked", "failed", "cancelled", "abandoned",
                }
                or type(self.source_has_blockers) is not bool
                or type(self.source_has_next_action) is not bool
            ):
                raise ValueError("invalid task shadow signal metadata")
        if self.proposal_status == "not_proposed" and self.source_task_status is None:
            raise ValueError("not_proposed observations require task signal metadata")
        if self.task_id is not None:
            _contract_token(self.task_id, "task_id")
            if "/" in self.task_id or "\\" in self.task_id:
                raise ValueError("invalid task_id")
        if self.mode != "shadow":
            raise ValueError("only shadow mode is supported")
        if self.token_usage is not None and not isinstance(self.token_usage, HostTokenUsage):
            raise ValueError("invalid token usage metadata")
        if self.token_usage is not None and (self.host_name, self.surface) not in {
            ("antigravity", "cli_stream_json"),
            ("codex", "app_server"),
        }:
            raise ValueError("token usage is unsupported for this host surface")
        if self.source_sequence is not None and (
            type(self.source_sequence) is not int or not 0 <= self.source_sequence <= 1_000_000_000
        ):
            raise ValueError("invalid source sequence")
        if self.source_stream_ref is not None and not re.fullmatch(
            r"[a-f0-9]{32}", self.source_stream_ref
        ):
            raise ValueError("invalid source stream reference")
        if self.source_result is not None and (
            self.host_name != "codex"
            or self.surface != "app_server"
            or self.source_result not in {
                "completed", "interrupted", "failed", "inProgress",
                "notLoaded", "idle", "systemError", "active",
            }
        ):
            raise ValueError("invalid source result")
        if not isinstance(self.evidence_ids, (tuple, list)) or len(self.evidence_ids) > 64:
            raise ValueError("invalid evidence_ids")
        evidence_ids = tuple(_contract_token(item, "evidence_id") for item in self.evidence_ids)
        if any("/" in item or "\\" in item for item in evidence_ids):
            raise ValueError("invalid evidence_ids")
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True)
class HostOperationResult:
    status: HostOperationStatus
    reason: str
    host_name: str
    host_version: str
    surface: str
    session_type: str
    session_ref: str
    task_id: str | None
    evidence_ids: tuple[str, ...]
    proposed_action: str
    event_id: str | None = None
    recorded: bool = False
    duplicate: bool = False
    proposal_status: str = "proposed"


@dataclass(frozen=True)
class HostLaunchAuthorization:
    allowed: bool
    reason: str
    invocation_id: str
    reservation: Any | None = None


@dataclass(frozen=True)
class HostLaunchResult:
    """Result of one explicitly routed Antigravity CLI turn."""

    status: HostOperationStatus
    reason: str
    invocation_id: str
    response_text: str = ""
    observations: tuple[HostStreamObservation, ...] = ()
    budget_reserved: bool = False


_HOST_TOKEN_USAGE_FIELDS = (
    "input_tokens", "output_tokens", "thinking_tokens",
    "cache_read_tokens", "total_tokens",
)


@dataclass(frozen=True)
class HostTokenUsage:
    """Allowlisted aggregate token counters; no prompt or result content."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cache_read_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in _HOST_TOKEN_USAGE_FIELDS:
            value = getattr(self, name)
            if value is not None and (
                type(value) is not int or value < 0 or value > (2**53 - 1)
            ):
                raise ValueError(f"invalid token usage counter: {name}")

    @classmethod
    def from_payload(cls, value: Any) -> HostTokenUsage:
        if not isinstance(value, dict):
            raise ValueError("invalid token usage metadata")
        counters = {name: value[name] for name in _HOST_TOKEN_USAGE_FIELDS if name in value}
        if not counters:
            raise ValueError("invalid token usage metadata")
        return cls(**counters)

    def to_dict(self) -> dict[str, int]:
        return {
            name: value
            for name in _HOST_TOKEN_USAGE_FIELDS
            if (value := getattr(self, name)) is not None
        }


@dataclass(frozen=True)
class HostStreamObservation:
    """Sanitized metadata extracted from one supported host event."""

    host_name: str
    surface: str
    session_type: str
    session_ref: str
    event_id: str
    event_type: str
    sequence: int
    verification_status: HostVerificationStatus = HostVerificationStatus.NOT_VERIFIED
    token_usage: HostTokenUsage | None = None
    source_stream_ref: str | None = None
    source_result: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_antigravity_cli() -> Path | None:
    """Locate the Antigravity CLI without launching it or changing PATH."""
    candidates: list[Path] = []
    for command in ("agy", "agy.exe"):
        located = shutil.which(command)
        if located:
            candidates.append(Path(located))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        candidates.append(Path(local_app_data) / "agy" / "bin" / "agy.exe")

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_file():
            return resolved
    return None


def parse_antigravity_stream_event(
    line: str,
    *,
    sequence: int,
    stream_instance_id: str,
) -> HostStreamObservation:
    """Extract only bounded event metadata; never return stream content or IDs.

    The caller must separately prove that the process and conversation are
    Hub-owned before using this observation for a shadow write. Parsing a stream
    does not authenticate host delivery, permissions, or conversation ownership.
    ``stream_instance_id`` must be freshly generated by the Hub for each process;
    only its conversation-bound hash is returned, so restarts do not reuse event IDs.
    """
    if not isinstance(line, str) or not line or len(line) > 65536:
        raise ValueError("invalid Antigravity stream line")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence <= 1_000_000_000:
        raise ValueError("invalid Antigravity stream sequence")
    stream_instance_id = _contract_token(stream_instance_id, "stream_instance_id")
    try:
        message = json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Antigravity stream JSON") from exc
    if not isinstance(message, dict):
        raise ValueError("Antigravity stream event must be an object")

    event = message.get("event")
    token_usage = None
    if event == "init":
        payload = message.get("init")
        conversation_id = message.get("conversation_id")
        event_type = "session.initialized"
        if not isinstance(payload, dict):
            raise ValueError("invalid Antigravity init event")
    elif event == "step_update":
        payload = message.get("step_update")
        if not isinstance(payload, dict):
            raise ValueError("invalid Antigravity step update")
        conversation_id = payload.get("conversation_id")
        step_index = payload.get("step_index")
        state = payload.get("state")
        step_type = payload.get("step_type")
        if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 0:
            raise ValueError("invalid Antigravity step index")
        if state not in {"ACTIVE", "DONE"}:
            raise ValueError("unknown Antigravity step state")
        if step_type not in {"user_input", "agent_response", "tool", "checkpoint"}:
            raise ValueError("unknown Antigravity step type")
        if "usage" in payload:
            token_usage = HostTokenUsage.from_payload(payload["usage"])
        event_type = f"step_update.{step_type}.{state.lower()}"
    elif event == "result":
        payload = message.get("result")
        if not isinstance(payload, dict):
            raise ValueError("invalid Antigravity result event")
        conversation_id = payload.get("conversation_id")
        if "usage" in payload:
            token_usage = HostTokenUsage.from_payload(payload["usage"])
        event_type = (
            "session.result.success"
            if payload.get("status") == "SUCCESS"
            else "session.result.other"
        )
    else:
        raise ValueError("unsupported Antigravity stream event")

    conversation_id = _contract_token(conversation_id, "conversation_id", limit=200)
    session_ref = hashlib.sha256(
        f"antigravity\0{conversation_id}".encode("utf-8")
    ).hexdigest()[:32]
    source_stream_ref = hashlib.sha256(
        f"antigravity-stream\0{conversation_id}\0{stream_instance_id}".encode("utf-8")
    ).hexdigest()[:32]
    event_id = hashlib.sha256(
        f"antigravity\0{conversation_id}\0{source_stream_ref}\0{sequence}".encode("utf-8")
    ).hexdigest()
    return HostStreamObservation(
        host_name="antigravity",
        surface="cli_stream_json",
        session_type="conversation",
        session_ref=session_ref,
        event_id=event_id,
        event_type=event_type,
        sequence=sequence,
        token_usage=token_usage,
        source_stream_ref=source_stream_ref,
    )


def parse_antigravity_post_tool_use_event(
    payload: Any,
    *,
    expected_conversation_id: str,
    expected_workspace_root: str | Path,
) -> HostStreamObservation:
    """Sanitize a documented PostToolUse envelope without proving hook delivery.

    Conversation identity and workspace paths are checked in memory and never
    returned. Tool arguments, error details, transcript/artifact paths, and model
    names are discarded. A caller must separately verify Hub ownership before
    recording the observation through the shared shadow gate.
    """
    if not isinstance(payload, dict):
        raise ValueError("invalid Antigravity PostToolUse payload")
    expected_conversation_id = _contract_token(
        expected_conversation_id, "expected_conversation_id", limit=200
    )
    conversation_id = payload.get("conversationId")
    conversation_id = _contract_token(conversation_id, "conversation_id", limit=200)
    if conversation_id != expected_conversation_id:
        raise ValueError("Antigravity hook conversation identity mismatch")

    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        raise ValueError("invalid Antigravity PostToolUse tool call")
    _contract_token(tool_call.get("name"), "tool_name")
    if not isinstance(tool_call.get("args"), dict):
        raise ValueError("invalid Antigravity PostToolUse tool arguments")

    step_index = payload.get("stepIdx")
    if type(step_index) is not int or not 0 <= step_index <= 1_000_000_000:
        raise ValueError("invalid Antigravity PostToolUse step index")
    error = payload.get("error", "")
    if not isinstance(error, str) or len(error) > 65536:
        raise ValueError("invalid Antigravity PostToolUse error metadata")

    workspace_paths = payload.get("workspacePaths")
    if not isinstance(workspace_paths, list) or not workspace_paths or len(workspace_paths) > 64:
        raise ValueError("invalid Antigravity PostToolUse workspace metadata")
    try:
        from local_ai_hub.agent_tasks import _canonical_repository_root

        expected_root = _canonical_repository_root(str(expected_workspace_root))
        observed_roots = []
        for workspace_path in workspace_paths:
            if not isinstance(workspace_path, str) or not workspace_path:
                raise ValueError("invalid Antigravity workspace path")
            observed_roots.append(_canonical_repository_root(workspace_path))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("Antigravity hook workspace is not verifiable") from exc
    if expected_root not in observed_roots:
        raise ValueError("Antigravity hook workspace identity mismatch")

    session_ref = hashlib.sha256(
        f"antigravity-post-tool-use-session\\0{conversation_id}".encode("utf-8")
    ).hexdigest()[:32]
    source_stream_ref = hashlib.sha256(
        f"antigravity-post-tool-use\\0{conversation_id}".encode("utf-8")
    ).hexdigest()[:32]
    event_id = hashlib.sha256(
        f"antigravity-post-tool-use\\0{conversation_id}\\0{step_index}".encode("utf-8")
    ).hexdigest()
    return HostStreamObservation(
        host_name="antigravity",
        surface="antigravity_post_tool_use",
        session_type="conversation",
        session_ref=session_ref,
        event_id=event_id,
        event_type="tool.failed" if error else "tool.completed",
        sequence=step_index,
        verification_status=HostVerificationStatus.NOT_VERIFIED,
        source_stream_ref=source_stream_ref,
    )


def parse_codex_app_server_notification(
    line: str,
    *,
    sequence: int,
    repo_root: str | Path,
    expected_cli_version: str,
    expected_thread_id: str | None = None,
    stream_instance_id: str | None = None,
) -> HostStreamObservation:
    """Parse verified Codex thread-start and cumulative-usage metadata.

    The thread preview, path, and identifiers are used only for validation or
    pseudonym derivation and are never returned. Other notifications remain
    unsupported until their delivery and metadata contract are verified. Usage
    updates require the in-memory thread identity and a fresh Hub process nonce.
    """
    if not isinstance(line, str) or not line or len(line) > 65536:
        raise ValueError("invalid Codex app-server notification")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence <= 1_000_000_000:
        raise ValueError("invalid Codex app-server sequence")
    if not isinstance(expected_cli_version, str) or not expected_cli_version or expected_cli_version != expected_cli_version.strip():
        raise ValueError("invalid expected Codex CLI version")
    try:
        message = json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Codex app-server JSON") from exc
    if not isinstance(message, dict) or "id" in message:
        raise ValueError("unsupported Codex app-server notification")
    method = message.get("method")
    params = message.get("params")
    if method == "thread/tokenUsage/updated":
        if expected_thread_id is None or stream_instance_id is None:
            raise ValueError("Codex token usage requires expected thread identity and stream instance")
        expected_thread_id = _contract_token(expected_thread_id, "expected_thread_id")
        stream_instance_id = _contract_token(stream_instance_id, "stream_instance_id")
        if not isinstance(params, dict):
            raise ValueError("invalid Codex token usage notification")
        thread_id = params.get("threadId")
        token_usage = params.get("tokenUsage")
        if thread_id != expected_thread_id:
            raise ValueError("Codex thread identity mismatch")
        if (
            not isinstance(token_usage, dict)
            or not isinstance(token_usage.get("last"), dict)
            or not isinstance(token_usage.get("total"), dict)
        ):
            raise ValueError("invalid Codex token usage metadata")
        total = token_usage["total"]
        required = {
            "inputTokens", "outputTokens", "cachedInputTokens",
            "reasoningOutputTokens", "totalTokens",
        }
        if not required.issubset(total):
            raise ValueError("incomplete Codex cumulative token usage")
        usage = HostTokenUsage.from_payload({
            "input_tokens": total["inputTokens"],
            "output_tokens": total["outputTokens"],
            "cache_read_tokens": total["cachedInputTokens"],
            "thinking_tokens": total["reasoningOutputTokens"],
            "total_tokens": total["totalTokens"],
        })
        session_ref = hashlib.sha256(f"codex\0{thread_id}".encode("utf-8")).hexdigest()[:32]
        source_stream_ref = hashlib.sha256(
            f"codex-stream\0{thread_id}\0{stream_instance_id}".encode("utf-8")
        ).hexdigest()[:32]
        event_id = hashlib.sha256(
            f"codex\0{source_stream_ref}\0thread.token_usage.updated\0{sequence}".encode("utf-8")
        ).hexdigest()
        return HostStreamObservation(
            host_name="codex",
            surface="app_server",
            session_type="thread",
            session_ref=session_ref,
            event_id=event_id,
            event_type="thread.token_usage.updated",
            sequence=sequence,
            token_usage=usage,
            source_stream_ref=source_stream_ref,
        )
    if method == "thread/status/changed":
        if expected_thread_id is None or stream_instance_id is None:
            raise ValueError("Codex thread status requires expected thread identity and stream instance")
        expected_thread_id = _contract_token(expected_thread_id, "expected_thread_id")
        stream_instance_id = _contract_token(stream_instance_id, "stream_instance_id")
        if not isinstance(params, dict) or params.get("threadId") != expected_thread_id:
            raise ValueError("Codex thread identity mismatch")
        status = params.get("status")
        status_type = status.get("type") if isinstance(status, dict) else None
        if status_type not in {"notLoaded", "idle", "systemError", "active"}:
            raise ValueError("unsupported Codex thread status")
        session_ref = hashlib.sha256(
            f"codex\0{expected_thread_id}".encode("utf-8")
        ).hexdigest()[:32]
        source_stream_ref = hashlib.sha256(
            f"codex-stream\0{expected_thread_id}\0{stream_instance_id}".encode("utf-8")
        ).hexdigest()[:32]
        event_id = hashlib.sha256(
            f"codex\0{source_stream_ref}\0thread.status.changed\0{sequence}".encode("utf-8")
        ).hexdigest()
        return HostStreamObservation(
            host_name="codex",
            surface="app_server",
            session_type="thread",
            session_ref=session_ref,
            event_id=event_id,
            event_type="thread.status.changed",
            sequence=sequence,
            source_stream_ref=source_stream_ref,
            source_result=status_type,
        )
    if method in {"turn/started", "turn/completed"}:
        if expected_thread_id is None or stream_instance_id is None:
            raise ValueError("Codex turn event requires expected thread identity and stream instance")
        expected_thread_id = _contract_token(expected_thread_id, "expected_thread_id")
        stream_instance_id = _contract_token(stream_instance_id, "stream_instance_id")
        if not isinstance(params, dict) or params.get("threadId") != expected_thread_id:
            raise ValueError("Codex thread identity mismatch")
        turn = params.get("turn")
        if (
            not isinstance(turn, dict)
            or not isinstance(turn.get("id"), str)
            or not isinstance(turn.get("items"), list)
        ):
            raise ValueError("invalid Codex turn notification")
        turn_id = _contract_token(turn["id"], "turn_id")
        status = turn.get("status")
        if status not in {"completed", "interrupted", "failed", "inProgress"}:
            raise ValueError("unsupported Codex turn status")
        event_type = method.replace("/", ".")
        session_ref = hashlib.sha256(
            f"codex\0{expected_thread_id}".encode("utf-8")
        ).hexdigest()[:32]
        source_stream_ref = hashlib.sha256(
            f"codex-stream\0{expected_thread_id}\0{stream_instance_id}".encode("utf-8")
        ).hexdigest()[:32]
        event_id = hashlib.sha256(
            f"codex\0{source_stream_ref}\0{event_type}\0{turn_id}\0{sequence}".encode("utf-8")
        ).hexdigest()
        return HostStreamObservation(
            host_name="codex",
            surface="app_server",
            session_type="thread",
            session_ref=session_ref,
            event_id=event_id,
            event_type=event_type,
            sequence=sequence,
            source_stream_ref=source_stream_ref,
            source_result=status,
        )
    if method != "thread/started":
        raise ValueError("unsupported Codex app-server notification")
    thread = params.get("thread") if isinstance(params, dict) else None
    if not isinstance(thread, dict):
        raise ValueError("invalid Codex thread notification")
    thread_id = thread.get("id")
    cwd = thread.get("cwd")
    cli_version = thread.get("cliVersion")
    if not isinstance(thread_id, str) or not isinstance(cwd, str):
        raise ValueError("invalid Codex thread identity")
    thread_id = _contract_token(thread_id, "thread_id")
    if cli_version != expected_cli_version:
        raise ValueError("Codex CLI version mismatch")
    try:
        from local_ai_hub.agent_tasks import _canonical_repository_root

        actual_root = _canonical_repository_root(cwd)
        expected_root = _canonical_repository_root(str(repo_root))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("Codex thread root is not verifiable") from exc
    if actual_root != expected_root:
        raise ValueError("Codex thread repository mismatch")

    session_ref = hashlib.sha256(f"codex\0{thread_id}".encode("utf-8")).hexdigest()[:32]
    event_id = hashlib.sha256(
        f"codex\0{thread_id}\0thread.started\0{sequence}".encode("utf-8")
    ).hexdigest()
    return HostStreamObservation(
        host_name="codex",
        surface="app_server",
        session_type="thread",
        session_ref=session_ref,
        event_id=event_id,
        event_type="thread.started",
        sequence=sequence,
    )


def parse_codex_app_server_approval_request(
    line: str,
    *,
    sequence: int,
    expected_thread_id: str,
    stream_instance_id: str,
) -> HostStreamObservation:
    """Record only the existence and type of a Codex approval request."""
    if not isinstance(line, str) or not line or len(line) > 65536:
        raise ValueError("invalid Codex app-server request")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence <= 1_000_000_000:
        raise ValueError("invalid Codex app-server sequence")
    expected_thread_id = _contract_token(expected_thread_id, "expected_thread_id")
    stream_instance_id = _contract_token(stream_instance_id, "stream_instance_id")
    try:
        message = json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Codex app-server JSON") from exc
    approval_events = {
        "item/commandExecution/requestApproval": "approval.command_execution.requested",
        "item/fileChange/requestApproval": "approval.file_change.requested",
        "item/permissions/requestApproval": "approval.permissions.requested",
    }
    method = message.get("method") if isinstance(message, dict) else None
    if not isinstance(method, str) or method not in approval_events:
        raise ValueError("unsupported Codex app-server approval request")
    request_id = message.get("id")
    if type(request_id) is int:
        if request_id < 0 or request_id > (2**53 - 1):
            raise ValueError("invalid Codex approval request identity")
        request_identity = str(request_id)
    elif isinstance(request_id, str) and request_id:
        request_identity = _contract_token(request_id, "request_id")
    else:
        raise ValueError("invalid Codex approval request identity")
    params = message.get("params")
    if not isinstance(params, dict) or params.get("threadId") != expected_thread_id:
        raise ValueError("Codex thread identity mismatch")
    for name in ("turnId", "itemId"):
        if not isinstance(params.get(name), str):
            raise ValueError("invalid Codex approval request metadata")
    if method in {
        "item/commandExecution/requestApproval",
        "item/permissions/requestApproval",
    } and not isinstance(params.get("cwd"), str):
        raise ValueError("invalid Codex approval request metadata")
    if method == "item/commandExecution/requestApproval" and not isinstance(
        params.get("command"), str
    ):
        raise ValueError("invalid Codex approval request metadata")
    if method == "item/permissions/requestApproval" and (
        not isinstance(params.get("permissions"), list)
        or any(not isinstance(permission, str) for permission in params["permissions"])
    ):
        raise ValueError("invalid Codex approval request metadata")
    started_at = params.get("startedAtMs")
    if type(started_at) is not int or started_at < 0:
        raise ValueError("invalid Codex approval request metadata")

    session_ref = hashlib.sha256(f"codex\0{expected_thread_id}".encode("utf-8")).hexdigest()[:32]
    source_stream_ref = hashlib.sha256(
        f"codex-stream\0{expected_thread_id}\0{stream_instance_id}".encode("utf-8")
    ).hexdigest()[:32]
    event_id = hashlib.sha256(
        f"codex-approval\0{source_stream_ref}\0{method}\0{request_identity}\0{sequence}".encode("utf-8")
    ).hexdigest()
    return HostStreamObservation(
        host_name="codex",
        surface="app_server",
        session_type="thread",
        session_ref=session_ref,
        event_id=event_id,
        event_type=approval_events[method],
        sequence=sequence,
        source_stream_ref=source_stream_ref,
    )


def record_shadow_observation(
    request: HostShadowRequest,
    capability: HostCapabilitySnapshot,
    event_store: Any,
    *,
    event_stream_id: str | None = None,
) -> HostOperationResult:
    """Persist a shadow proposal only for an owned, verified session.

    The caller supplies the existing AgentStateStore. This function cannot send
    data to a host or execute the proposed action.
    """
    import hashlib
    import math
    import time

    session_ref = hashlib.sha256(
        f"{request.repository_id}\0{request.host_name}\0{request.session_id}".encode("utf-8")
    ).hexdigest()[:32]

    def result(status: HostOperationStatus, reason: str, **values: Any) -> HostOperationResult:
        return HostOperationResult(
            status=status, reason=reason, host_name=request.host_name,
            host_version=request.host_version, surface=request.surface,
            session_type=request.session_type, session_ref=session_ref,
            task_id=request.task_id, evidence_ids=request.evidence_ids,
            proposed_action=request.proposed_action,
            proposal_status=request.proposal_status, **values,
        )

    if request.mode != "shadow":
        return result(HostOperationStatus.REFUSED, "active_mode_not_enabled")
    if capability.verification_status is HostVerificationStatus.UNSUPPORTED:
        return result(HostOperationStatus.UNSUPPORTED, "host_surface_unsupported")
    if capability.verification_status is not HostVerificationStatus.VERIFIED:
        return result(HostOperationStatus.UNCERTAIN, "host_capability_not_verified")
    if (request.host_name, request.host_version, request.surface, request.session_type) != (
        capability.host_name, capability.host_version, capability.surface, capability.session_type
    ):
        return result(HostOperationStatus.UNCERTAIN, "capability_identity_mismatch")
    if not capability.hub_managed:
        return result(HostOperationStatus.REFUSED, "session_not_hub_managed")
    if capability.connection_status is HostConnectionStatus.DISCONNECTED:
        return result(HostOperationStatus.UNCERTAIN, "host_connection_lost")
    if capability.connection_status is not HostConnectionStatus.CONNECTED:
        return result(HostOperationStatus.UNCERTAIN, "host_connection_not_verified")
    if request.event_type not in capability.available_events:
        return result(HostOperationStatus.UNSUPPORTED, "event_not_available")
    if event_store is None or not getattr(event_store, "enabled", False):
        return result(HostOperationStatus.UNCERTAIN, "agent_event_store_unavailable")
    if event_stream_id is not None and (
        not request.task_id
        or event_stream_id != f"task:{request.task_id}"
        or request.host_name != "local-ai-hub"
        or request.surface != "agent_os"
        or request.session_type != "task"
    ):
        return result(HostOperationStatus.REFUSED, "invalid_shadow_event_stream_scope")

    event_digest = hashlib.sha256(
        f"{request.repository_id}\0{request.host_name}\0{request.session_id}\0{request.event_id}".encode("utf-8")
    ).hexdigest()
    would_be_denied = (
        capability.would_be_denied
        if capability.permissions_verified and request.proposal_status == "proposed"
        else None
    )
    permission_status = (
        "not_evaluated" if would_be_denied is None
        else "would_deny" if would_be_denied
        else "would_allow"
    )
    payload = {
        "schema": (
            "local-ai-hub.host-shadow-observation.v3"
            if request.source_task_status is not None
            else "local-ai-hub.host-shadow-observation.v2"
        ),
        "event_id": event_digest,
        "event_type": request.event_type,
        "observed_at": time.time(),
        "host": {
            "name": capability.host_name,
            "version": capability.host_version,
            "surface": capability.surface,
            "verification_status": capability.verification_status.value,
        },
        "session": {
            "session_id": session_ref,
            "type": capability.session_type,
            "hub_managed": True,
        },
        "repository_id": request.repository_id,
        "task_id": request.task_id,
        "capabilities": {
            "events": list(capability.available_events),
            "commands": list(capability.available_commands),
            "permissions": list(capability.available_permissions),
            "permission_mode": capability.permission_mode,
        },
        "proposal": {
            "action": request.proposed_action,
            "reason_code": request.reason_code,
            "status": request.proposal_status,
        },
        "outcome": "simulated" if request.proposal_status == "proposed" else "observed",
        "permission_check": {
            "status": permission_status,
            "would_be_denied": would_be_denied,
        },
        "evidence_ids": list(request.evidence_ids),
        "content_stored": False,
    }
    if request.source_task_status is not None:
        payload["source_state"] = {
            "task_status": request.source_task_status,
            "has_blockers": request.source_has_blockers,
            "has_next_action": request.source_has_next_action,
        }
    if request.token_usage is not None:
        payload["token_usage"] = request.token_usage.to_dict()
        payload["token_usage_scope"] = "session_cumulative"
    if request.source_sequence is not None:
        payload["source_sequence"] = request.source_sequence
    if request.source_stream_ref is not None:
        payload["source_stream_ref"] = request.source_stream_ref
    if request.source_result is not None:
        payload["source_result"] = request.source_result
    if not math.isfinite(payload["observed_at"]):
        return result(HostOperationStatus.UNCERTAIN, "invalid_observation_time")

    from local_ai_hub.agent_events import AgentEvent

    event = AgentEvent.create(
        stream_id=event_stream_id or f"host-shadow:{session_ref}",
        kind=(
            "host.shadow.observation.v3"
            if request.source_task_status is not None
            else "host.shadow.observation.v2"
        ),
        payload=payload,
        idempotency_key=f"host-shadow:{event_digest}",
        actor="host_shadow",
        correlation_id=event_digest,
    )
    try:
        appended = event_store.append(event)
    except Exception:
        return result(HostOperationStatus.UNCERTAIN, "shadow_event_store_write_uncertain")
    if appended.error or appended.retryable or appended.event is None:
        return result(HostOperationStatus.UNCERTAIN, "shadow_event_store_write_uncertain")
    if request.proposal_status == "not_proposed":
        status = HostOperationStatus.SHADOW_ONLY
        reason = "no_actionable_proposal_recorded"
    elif capability.permissions_verified and would_be_denied is True:
        status = HostOperationStatus.REFUSED
        reason = "existing_permissions_would_deny"
    elif not capability.permissions_verified:
        status = HostOperationStatus.SHADOW_ONLY
        reason = "proposal_recorded_permission_state_unknown"
    else:
        status = HostOperationStatus.SHADOW_ONLY
        reason = "proposal_recorded_without_host_action"
    return result(
        status, reason, event_id=appended.event.event_id,
        recorded=True, duplicate=bool(appended.duplicate),
    )


def record_agent_task_checkpoint_shadow(task: Any, source_event: Any, event_store: Any) -> HostOperationResult | None:
    """Record a client-neutral pause/continue proposal from one Agent OS checkpoint.

    Only typed task status and checkpoint presence bits inform the proposal. The
    source event payload, goal, blockers, next action, and checkpoint state are
    never copied into shadow telemetry. This function cannot mutate the task.
    """
    import re

    from local_ai_hub import __version__
    from local_ai_hub.agent_events import AgentEvent
    from local_ai_hub.agent_tasks import TaskState, TaskStatus

    if not isinstance(task, TaskState) or not isinstance(source_event, AgentEvent):
        return None
    if source_event.kind != "task.checkpointed" or source_event.stream_id != f"task:{task.task_id}":
        return None
    repository_id = task.context.repository_id
    if not isinstance(repository_id, str) or not re.fullmatch(r"[a-f0-9]{64}", repository_id):
        return None

    checkpoint = task.checkpoint
    if task.status is TaskStatus.BLOCKED:
        proposed_action = "recommend_pause"
        reason_code = "task_status_blocked"
        proposal_status = "proposed"
    elif checkpoint.has_blockers():
        proposed_action = "recommend_pause"
        reason_code = "checkpoint_has_blockers"
        proposal_status = "proposed"
    elif task.status is TaskStatus.ACTIVE and checkpoint.next_action:
        proposed_action = "recommend_continue"
        reason_code = "checkpoint_has_next_action"
        proposal_status = "proposed"
    else:
        proposed_action = "none"
        reason_code = "no_actionable_signal"
        proposal_status = "not_proposed"

    capability = HostCapabilitySnapshot(
        host_name="local-ai-hub",
        host_version=__version__,
        surface="agent_os",
        session_type="task",
        hub_managed=True,
        available_events=("task.checkpointed",),
        verification_status=HostVerificationStatus.VERIFIED,
        connection_status=HostConnectionStatus.CONNECTED,
    )
    request = HostShadowRequest(
        host_name=capability.host_name,
        host_version=capability.host_version,
        surface=capability.surface,
        session_type=capability.session_type,
        session_id=task.task_id,
        repository_id=repository_id,
        event_id=source_event.event_id,
        event_type=source_event.kind,
        proposed_action=proposed_action,
        reason_code=reason_code,
        task_id=task.task_id,
        evidence_ids=(source_event.event_id,),
        proposal_status=proposal_status,
        source_task_status=task.status.value,
        source_has_blockers=checkpoint.has_blockers(),
        source_has_next_action=bool(checkpoint.next_action),
    )
    return record_shadow_observation(
        request,
        capability,
        event_store,
        event_stream_id=f"task:{task.task_id}",
    )


def record_antigravity_shadow_event(
    observation: HostStreamObservation,
    *,
    repository_id: str,
    capability: HostCapabilitySnapshot,
    event_store: Any,
    task_id: str | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> HostOperationResult:
    """Record sanitized CLI event metadata through the shared shadow gate."""
    if not isinstance(observation, HostStreamObservation):
        raise ValueError("invalid Antigravity stream observation")
    if observation.host_name != "antigravity" or observation.surface != "cli_stream_json":
        raise ValueError("observation is not from the Antigravity CLI stream")
    request = HostShadowRequest(
        host_name=observation.host_name,
        host_version=capability.host_version,
        surface=observation.surface,
        session_type=observation.session_type,
        session_id=observation.session_ref,
        repository_id=repository_id,
        event_id=observation.event_id,
        event_type=observation.event_type,
        proposed_action="observe_event",
        reason_code="stream_event_metadata",
        task_id=task_id,
        evidence_ids=evidence_ids,
        token_usage=observation.token_usage,
        source_sequence=observation.sequence,
        source_stream_ref=observation.source_stream_ref,
    )
    return record_shadow_observation(request, capability, event_store)


def record_antigravity_hook_shadow_event(
    observation: HostStreamObservation,
    *,
    repository_id: str,
    capability: HostCapabilitySnapshot,
    event_store: Any,
    task_id: str | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> HostOperationResult:
    """Record sanitized PostToolUse metadata only through the shared shadow gate."""
    if not isinstance(observation, HostStreamObservation):
        raise ValueError("invalid Antigravity PostToolUse observation")
    if (
        observation.host_name != "antigravity"
        or observation.surface != "antigravity_post_tool_use"
        or observation.event_type not in {"tool.completed", "tool.failed"}
    ):
        raise ValueError("observation is not from Antigravity PostToolUse")
    request = HostShadowRequest(
        host_name=observation.host_name,
        host_version=capability.host_version,
        surface=observation.surface,
        session_type=observation.session_type,
        session_id=observation.session_ref,
        repository_id=repository_id,
        event_id=observation.event_id,
        event_type=observation.event_type,
        proposed_action="observe_event",
        reason_code="post_tool_use_metadata",
        task_id=task_id,
        evidence_ids=evidence_ids,
        source_sequence=observation.sequence,
        source_stream_ref=observation.source_stream_ref,
    )
    return record_shadow_observation(request, capability, event_store)


def record_codex_shadow_event(
    observation: HostStreamObservation,
    *,
    repository_id: str,
    capability: HostCapabilitySnapshot,
    event_store: Any,
    task_id: str | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> HostOperationResult:
    """Record sanitized Codex App Server metadata through the shared shadow gate."""
    if not isinstance(observation, HostStreamObservation):
        raise ValueError("invalid Codex app-server observation")
    if observation.host_name != "codex" or observation.surface != "app_server":
        raise ValueError("observation is not from Codex App Server")
    if observation.event_type not in {
        "thread.started", "thread.status.changed", "thread.token_usage.updated",
        "turn.started", "turn.completed",
        "approval.command_execution.requested", "approval.file_change.requested",
        "approval.permissions.requested",
    }:
        raise ValueError("unsupported Codex shadow event")
    request = HostShadowRequest(
        host_name=observation.host_name,
        host_version=capability.host_version,
        surface=observation.surface,
        session_type=observation.session_type,
        session_id=observation.session_ref,
        repository_id=repository_id,
        event_id=observation.event_id,
        event_type=observation.event_type,
        proposed_action=(
            "record_approval_notice"
            if observation.event_type.startswith("approval.")
            else "observe_event"
        ),
        reason_code=(
            "approval_request_metadata"
            if observation.event_type.startswith("approval.")
            else "app_server_event_metadata"
        ),
        task_id=task_id,
        evidence_ids=evidence_ids,
        token_usage=observation.token_usage,
        source_sequence=observation.sequence,
        source_stream_ref=observation.source_stream_ref,
        source_result=observation.source_result,
    )
    return record_shadow_observation(request, capability, event_store)


def authorize_antigravity_cli_turn(
    command_broker: Any,
    task_id: str,
) -> Any:
    """Authorize a CLI model turn at the existing command-broker boundary.

    This is an authorization decision only; it never launches the CLI or sends
    user input. The broker resolves the durable task, policy configuration, and
    explicit grant. Callers must preserve the returned approval/deny state and
    separately apply provider, budget, workspace, and process-lifecycle gates.
    """
    from local_ai_hub.agent_policy import PolicyDecision
    if command_broker is None or not callable(
        getattr(command_broker, "authorize_auxiliary_action", None)
    ):
        return PolicyDecision(
            allowed=False,
            reason="command_broker_unavailable",
            side_effect_class="model_execution",
        )
    if not isinstance(task_id, str) or not task_id.strip() or task_id != task_id.strip():
        return PolicyDecision(
            allowed=False,
            reason="task_identity_unavailable",
            side_effect_class="model_execution",
        )
    try:
        result = command_broker.authorize_auxiliary_action(
            "model_inference", endpoint="antigravity_cli", task_id=task_id
        )
    except Exception:
        return PolicyDecision(
            allowed=False,
            reason="command_broker_authorization_unavailable",
            side_effect_class="model_execution",
        )
    if (
        not isinstance(result, dict)
        or type(result.get("allowed")) is not bool
        or type(result.get("success")) is not bool
        or result["allowed"] != result["success"]
    ):
        return PolicyDecision(
            allowed=False,
            reason="command_broker_authorization_invalid",
            side_effect_class="model_execution",
        )
    return PolicyDecision(
        allowed=result["allowed"] and result.get("requires_approval") is not True,
        requires_approval=result.get("requires_approval") is True,
        reason=(
            "approval_required" if result.get("requires_approval") is True
            else str(result.get("reason") or result.get("error") or "")
        ),
        receipt_id=str(result.get("receipt_id") or ""),
        owner=str(result.get("owner") or "agent_policy"),
        side_effect_class=str(result.get("side_effect_class") or "model_execution"),
    )


def reserve_antigravity_cli_turn(
    command_broker: Any,
    task_id: str,
    invocation_id: str,
) -> HostLaunchAuthorization:
    """Authorize and durably reserve budget before a Hub-owned CLI launch."""
    decision = authorize_antigravity_cli_turn(command_broker, task_id)
    if not decision.allowed:
        return HostLaunchAuthorization(False, decision.reason or "policy_denied", invocation_id)

    policy_engine = getattr(command_broker, "policy_engine", None)
    reserve = getattr(policy_engine, "reserve_external_call", None)
    if not callable(reserve):
        return HostLaunchAuthorization(False, "durable_budget_reservation_unavailable", invocation_id)
    try:
        reservation = reserve(task_id, invocation_id)
    except Exception:
        return HostLaunchAuthorization(False, "durable_budget_reservation_failed", invocation_id)
    if (
        getattr(reservation, "task_id", None) != task_id
        or getattr(reservation, "invocation_id", None) != invocation_id
        or type(getattr(reservation, "reserved", None)) is not bool
        or type(getattr(reservation, "duplicate", None)) is not bool
        or type(getattr(reservation, "exhausted", None)) is not bool
    ):
        return HostLaunchAuthorization(False, "budget_reservation_invalid", invocation_id, reservation)
    if getattr(reservation, "duplicate", False):
        return HostLaunchAuthorization(False, "invocation_already_reserved", invocation_id, reservation)
    if getattr(reservation, "exhausted", False):
        return HostLaunchAuthorization(False, "external_call_budget_exhausted", invocation_id, reservation)
    if getattr(reservation, "reserved", False) is not True:
        return HostLaunchAuthorization(False, "budget_reservation_invalid", invocation_id, reservation)
    return HostLaunchAuthorization(True, "authorized_and_reserved", invocation_id, reservation)


def _antigravity_init_matches(line: str, *, repo_root: Path, model: str) -> bool:
    """Accept startup only for the pinned root/model and a tool-free CLI session."""
    try:
        message = json.loads(line)
        payload = message.get("init") if isinstance(message, dict) else None
        if not isinstance(message, dict) or message.get("event") != "init" or not isinstance(payload, dict):
            return False
        cwd = payload.get("cwd")
        tools = payload.get("tools")
        permission_mode = payload.get("permission_mode")
        if not isinstance(cwd, str) or not isinstance(tools, list) or tools:
            return False
        if any(not isinstance(tool, str) for tool in tools):
            return False
        if permission_mode != "request-review" or payload.get("model") != model:
            return False
        actual_root = Path(cwd).expanduser().resolve(strict=True)
        expected_root = repo_root.resolve(strict=True)
        return os.path.normcase(os.path.normpath(str(actual_root))) == os.path.normcase(
            os.path.normpath(str(expected_root))
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return False


def run_antigravity_cli_turn(
    *,
    command_broker: Any,
    task_store: Any,
    task_id: str,
    invocation_id: str,
    repo_root: str | Path,
    model: str,
    prompt: str,
    timeout_seconds: float = 300.0,
    event_store: Any | None = None,
    capability: HostCapabilitySnapshot | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> HostLaunchResult:
    """Keep live CLI turns unsupported until safe routing and cost limits exist."""
    return HostLaunchResult(
        HostOperationStatus.UNSUPPORTED,
        "enforceable_monetary_budget_unavailable",
        invocation_id,
    )


def get_managed_planner_instructions() -> str:
    """Return the canonical managed instruction block for Local AI Hub planner."""
    return MANAGED_PLANNER_INSTRUCTIONS.strip()


def inject_managed_instructions(content: str, block: str | None = None) -> str:
    """Inject or update the managed planner block in existing instruction content.

    If markers exist, replaces the content between markers.
    If markers do not exist, appends the block cleanly while preserving all user instructions.
    """
    block_to_insert = (block or get_managed_planner_instructions()).strip()
    pattern = re.compile(
        rf"{re.escape(PLANNER_BLOCK_START)}.*?{re.escape(PLANNER_BLOCK_END)}",
        re.DOTALL,
    )

    if pattern.search(content):
        return pattern.sub(block_to_insert, content)

    # Append to content
    trimmed = content.rstrip()
    if trimmed:
        return f"{trimmed}\n\n{block_to_insert}\n"
    return f"{block_to_insert}\n"


def remove_managed_instructions(content: str) -> str:
    """Remove the managed planner block from instructions if present."""
    pattern = re.compile(
        rf"\n*{re.escape(PLANNER_BLOCK_START)}.*?{re.escape(PLANNER_BLOCK_END)}\n*",
        re.DOTALL,
    )
    return pattern.sub("\n", content).strip() + "\n"


def detect_host_environment() -> str:
    """Detect current running host agent environment."""
    if os.environ.get("ANTIGRAVITY_ENV"):
        return "gemini_antigravity"
    if os.environ.get("GEMINI_CLI_HOME"):
        return "gemini_cli"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_ENV"):
        return "codex"
    if os.environ.get("CLAUDE_ENV") or os.environ.get("CLAUDE_BASE_DIR"):
        return "claude"
    if os.environ.get("CURSOR_PROJECT_DIR") or os.environ.get("CURSOR_ENV"):
        return "cursor"
    return "generic_mcp"


def probe_host_capabilities(
    host_name: str | None = None,
    repo_root: str | Path | None = None,
) -> HostCapabilityReport:
    """Probe capability levels of an agent host for a target workspace root."""
    resolved_host = host_name or detect_host_environment()
    root = Path(repo_root or ".").resolve()

    # 1. File management probe
    file_management = False
    try:
        if root.exists() and os.access(str(root), os.R_OK | os.W_OK):
            file_management = True
    except Exception:
        file_management = False

    # 2. Instructions integrated probe
    instructions_integrated = False
    agents_paths = [
        root / "AGENTS.md",
        root / ".gemini" / "AGENTS.md",
        root / ".gemini" / "GEMINI.md",
        root / ".codex" / "AGENTS.md",
        root / ".cursorrules",
    ]
    from .host_hooks import confined_path, read_bytes
    for ap in agents_paths:
        if ap.exists():
            try:
                confined_path(root, ap)
                txt = read_bytes(ap, max_bytes=65536).decode("utf-8", errors="ignore")
                if PLANNER_BLOCK_START in txt and PLANNER_BLOCK_END in txt:
                    instructions_integrated = True
                    break
            except (OSError, ValueError):
                pass

    # Configuration and local files cannot authenticate a host's event delivery,
    # trust decision, coverage or failure behavior. Never promote them to enforced.
    workflow_interception = False
    registration = {"configured": False, "reason": "unsupported_host"}
    if resolved_host in {"codex", "gemini_cli"}:
        from .host_hooks import ManagedHostInstallation
        try:
            preview = ManagedHostInstallation(root, resolved_host).preview()
            registration = {"configured": preview["installed"],
                            "config_path": preview["config_path"],
                            "reason": "host_trust_and_event_delivery_not_verified"}
        except (OSError, ValueError) as exc:
            registration = {"configured": False, "reason": str(exc)}

    # Determine support level
    if file_management and instructions_integrated and workflow_interception:
        support_level = "enforced"
    elif file_management and instructions_integrated:
        support_level = "advisory"
    else:
        support_level = "unsupported"

    return HostCapabilityReport(
        host_name=resolved_host,
        file_management=file_management,
        instructions_integrated=instructions_integrated,
        workflow_interception=workflow_interception,
        support_level=support_level,
        details={
            "repo_root": str(root),
            "instructions_checked": [str(p) for p in agents_paths if p.exists()],
            "hook_registration": registration,
            "host_event_verification": "not_verified",
            "enforcement_gap": "No authenticated host capability observation; local configuration is advisory.",
        },
    )


class SteeringManager:
    """Bounded private inbox; records are advisory, never host verification receipts."""

    MAX_RECORDS = 256

    def __init__(self, repo_root: str | Path) -> None:
        from .host_hooks import checked_root, confined_path
        self.repo_root = checked_root(repo_root)
        self.steering_dir = self.repo_root / ".local-ai-hub" / "local" / "steering"
        confined_path(self.repo_root, self.steering_dir)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        from .host_hooks import confined_path
        confined_path(self.repo_root, self.steering_dir)
        self.steering_dir.mkdir(parents=True, exist_ok=True)

    def capture_steering(
        self,
        session_id: str,
        message: str,
        *,
        task_id: str | None = None,
        author: str = "operator",
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Capture private local text; never copy operator text into tracked plans."""
        from .host_hooks import atomic_json, bounded_text, confined_path, read_json
        bounded_text(session_id, "session_id", 200)
        bounded_text(message, "message", 16384)
        bounded_text(author, "author", 100)
        if task_id is not None:
            bounded_text(task_id, "task_id", 200)
        if event_id is not None:
            bounded_text(event_id, "event_id", 300)
        self._ensure_dir()
        with self._locked():
            identity = json.dumps([session_id, task_id, event_id], ensure_ascii=True)
            suffix = hashlib.sha256(identity.encode()).hexdigest()[:24] if event_id else uuid.uuid4().hex[:24]
            steering_id = f"steer_{suffix}"
            file_path = confined_path(self.repo_root, self.steering_dir / f"{steering_id}.json")
            if file_path.exists():
                existing = read_json(file_path, max_bytes=32768)
                if any(existing.get(key) != value for key, value in {
                    "session_id": session_id, "task_id": task_id, "message": message,
                }.items()):
                    raise ValueError("event_id reused with different steering payload")
                return {"success": True, "steering_id": steering_id, "record": existing}
            if len(self._paths()) >= self.MAX_RECORDS:
                raise ValueError("steering capacity exceeded; reconcile and archive local records")
            record = {
                "steering_id": steering_id,
                "session_id": session_id,
                "task_id": task_id,
                "author": author,
                "message": message,
                "status": "pending",  # pending, reconciled, dismissed
                "created_at": time.time(),
            }
            atomic_json(self.repo_root, file_path, record)
            return {"success": True, "steering_id": steering_id, "record": record}

    @contextmanager
    def _locked(self):
        from .host_hooks import confined_path
        lock = confined_path(self.repo_root, self.steering_dir / ".inbox.lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise ValueError("steering inbox busy; do not retry an uncertain write") from exc
        try:
            os.close(descriptor)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _paths(self) -> list[Path]:
        from .host_hooks import confined_path
        confined_path(self.repo_root, self.steering_dir)
        paths = []
        with os.scandir(self.steering_dir) as entries:
            for index, entry in enumerate(entries):
                if index >= self.MAX_RECORDS + 16:
                    raise ValueError("steering capacity exceeded")
                if entry.name.endswith(".json"):
                    paths.append(confined_path(self.repo_root, Path(entry.path)))
        return paths

    def list_pending_steering(self, task_id: str | None = None, *, session_id: str | None = None) -> list[dict[str, Any]]:
        """List un-reconciled steering items."""
        if not self.steering_dir.exists():
            return []
        items = []
        from .host_hooks import read_json
        for p in self._paths():
            try:
                data = read_json(p, max_bytes=32768)
                if data.get("status") == "pending":
                    if (task_id is None or data.get("task_id") == task_id) and (session_id is None or data.get("session_id") == session_id):
                        items.append(data)
            except (OSError, ValueError) as exc:
                raise ValueError("invalid steering record") from exc
        return sorted(items, key=lambda x: str(x.get("created_at", "")))

    def mark_reconciled(self, steering_id: str, reconciliation_summary: str = "") -> bool:
        """Mark a steering item as reconciled."""
        from .host_hooks import atomic_json, bounded_text, confined_path, read_json
        if not isinstance(steering_id, str) or not re.fullmatch(r"steer_[a-f0-9]{12,32}", steering_id):
            raise ValueError("invalid steering_id")
        bounded_text(reconciliation_summary, "reconciliation_summary", 4096, allow_empty=True)
        target_file = confined_path(self.repo_root, self.steering_dir / f"{steering_id}.json")
        if not target_file.exists():
            return False
        try:
            with self._locked():
                data = read_json(target_file, max_bytes=32768)
                data["status"] = "reconciled"
                data["reconciliation_summary"] = reconciliation_summary
                atomic_json(self.repo_root, target_file, data)
                return True
        except Exception:
            return False

    def confirm_reconciled(
        self, steering_id: str, *, task_id: str, session_id: str,
        contract_revision: int, plan_revision: str, spec_revision: str,
        summary: str = "",
    ) -> bool:
        """Persist revisions after the bridge verifies the actual spec/plan/task.

        This is an internal storage primitive, not an evidence validator. Public
        routes must derive these revisions from authenticated stores, never from
        caller-provided acknowledgement strings.
        """
        from .host_hooks import atomic_json, bounded_text, confined_path, read_json
        if not isinstance(steering_id, str) or not re.fullmatch(r"steer_[a-f0-9]{12,32}", steering_id):
            raise ValueError("invalid steering_id")
        if isinstance(contract_revision, bool) or not isinstance(contract_revision, int) or contract_revision < 1:
            raise ValueError("invalid contract_revision")
        for name, value in {"task_id": task_id, "session_id": session_id, "plan_revision": plan_revision,
                            "spec_revision": spec_revision}.items():
            bounded_text(value, name, 200)
        bounded_text(summary, "summary", 4096, allow_empty=True)
        path = confined_path(self.repo_root, self.steering_dir / f"{steering_id}.json")
        if not path.exists():
            return False
        record = read_json(path, max_bytes=32768)
        if record.get("session_id") != session_id or record.get("task_id") not in {None, task_id}:
            raise ValueError("steering task/session scope mismatch")
        record.update(status="reconciled", task_id=task_id, reconciliation_summary=summary,
                      reconciliation={"contract_revision": contract_revision,
                                      "plan_revision": plan_revision, "spec_revision": spec_revision})
        atomic_json(self.repo_root, path, record)
        return True
