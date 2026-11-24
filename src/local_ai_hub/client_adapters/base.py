"""BaseClientAdapter — shared contract and primitives for all AI coding agent hosts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from local_ai_hub.repo_plan.host_adapters import HostStreamObservation


class HookSupport(str, Enum):
    """Level of Local AI Hub hook coverage implemented for the client."""
    NONE = "none"              # No Hub hook adapter configured
    SESSION_START = "session_start"  # Session-start warmup only (Cursor)
    SESSION_PRE_TOOL = "session_pre_tool"  # Session warmup plus bounded pre-action checks
    SESSION_PRE_POST_TOOL = "session_pre_post_tool"  # Session warmup, bounded pre-action checks, and post-edit checks
    SESSION_TOOL = "session_tool"  # Session warmup plus bounded before/after-tool hooks (Gemini CLI)
    PRE_TOOL = "pre_tool"      # PreToolUse validation only (Antigravity)
    PRE_POST_TOOL = "pre_post_tool"  # Bounded pre-action checks and post-edit checks (Copilot, Windsurf, Devin)
    INVOCATION_TOOL = "invocation_tool"  # Invocation context plus before/after-tool hooks (Antigravity)
    FULL = "full"              # Session, prompt, subagent, pre/permission, and post-tool hooks (Codex)
    JS_PLUGIN = "js_plugin"    # Node.js / JavaScript plugin engine (OpenCode)


class InstructionTarget(str, Enum):
    """Target configuration file for client instructions."""
    AGENTS_MD     = "AGENTS.md"
    GEMINI_MD     = ".gemini/GEMINI.md"
    CLAUDE_MD     = "CLAUDE.md"
    CURSORRULES   = ".cursorrules"
    CURSOR_MDC    = ".cursor/rules/local-ai.mdc"
    WINDSURFRULES = ".windsurfrules"
    COPILOT_MD    = ".github/copilot-instructions.md"
    SYSTEM_PROMPT = "_system_prompt"  # Injected into session dynamically
    NONE          = "_none"


@dataclass(frozen=True)
class ClientCapabilities:
    """Declared capabilities and constraints for a specific client."""
    client_id:             str
    display_name:          str
    hook_support:          HookSupport
    instruction_targets:   tuple[InstructionTarget, ...]
    has_token_tracking:    bool   # Reports fine-grained token counts
    has_reasoning_tokens:  bool   # Slices reasoning/thinking tokens
    has_shadow_events:     bool   # Emits shadow observations to Agent OS
    has_goal_system:       bool   # Multi-turn goal lifecycle integration
    prompt_cache_shield:   bool = False  # Deterministic JSON key sorting for prompt caching
    tool_filter:           frozenset[str] = field(default_factory=frozenset)
    mcp_surface:           str = "stdio"
    extra:                 dict[str, Any] = field(default_factory=dict)
    hook_events:           tuple[str, ...] = ()  # Native events wired by the Hub integration


@dataclass(frozen=True)
class ClientContext:
    """Runtime context for an active client connection."""
    client_id:    str
    session_id:   str | None = None
    repo_root:    str | None = None
    agent_header: str | None = None
    request_id:   str | None = None
    extra:        dict[str, Any] = field(default_factory=dict)

    def with_extra(self, **kwargs: Any) -> "ClientContext":
        return ClientContext(
            client_id=self.client_id,
            session_id=self.session_id,
            repo_root=self.repo_root,
            agent_header=self.agent_header,
            request_id=self.request_id,
            extra={**self.extra, **kwargs},
        )


class BaseClientAdapter:
    """Base class for all host client adapters.

    Subclasses override specific hooks, instruction targets, and tool filters
    while inheriting shared validation, caching, and reporting logic.
    """
    client_id: str = "generic"
    capabilities: ClientCapabilities

    def get_instructions(self, target: InstructionTarget) -> str:
        """Compose instructions tailored for this target."""
        try:
            from local_ai_hub.repo_plan.host_adapters import get_managed_planner_instructions
            planner = get_managed_planner_instructions()
        except ImportError:
            planner = ""
        try:
            from local_ai_hub.caveman_instructions import get_caveman_instructions
            caveman = get_caveman_instructions(client_id=self.client_id)
        except Exception:
            caveman = ""
        parts = [p for p in (planner, caveman) if p]
        return "\n\n".join(parts)

    def filter_tools(self, tools: list[Any]) -> list[Any]:
        """Filter MCP tools list according to client capabilities."""
        if not self.capabilities.tool_filter:
            return list(tools)
        allowed = set(self.capabilities.tool_filter)
        res = []
        for t in tools:
            name = t.get("name") if isinstance(t, dict) else (getattr(t, "name", str(t)) if hasattr(t, "name") else str(t))
            if name in allowed:
                res.append(t)
        return res

    def mutate_tool_description(self, tool_name: str, description: str) -> str:
        """Optional per-client adaptation of tool descriptions."""
        return description

    def normalize_for_cache(self, payload: Any) -> Any:
        """Deterministic normalization for KV prompt caching stability."""
        from .prompt_cache_shield import normalize_for_prompt_cache
        return normalize_for_prompt_cache(payload)

    def parse_hook_event(self, raw: Any) -> "HostStreamObservation | None":
        """Parse incoming hook or stream event if supported."""
        return None

    def enrich_context(self, context: ClientContext, raw_event: Any = None) -> ClientContext:
        """Add client-specific metadata to runtime context."""
        return context

    def capability_report(self, repo_root: str | None = None) -> dict[str, Any]:
        """Generate structured capability and health report."""
        report = {
            "client_id": self.client_id,
            "display_name": self.capabilities.display_name,
            "hook_support": self.capabilities.hook_support.value,
            "hook_events": list(self.capabilities.hook_events),
            "instruction_targets": [t.value for t in self.capabilities.instruction_targets],
            "has_token_tracking": self.capabilities.has_token_tracking,
            "has_reasoning_tokens": self.capabilities.has_reasoning_tokens,
            "has_shadow_events": self.capabilities.has_shadow_events,
            "has_goal_system": self.capabilities.has_goal_system,
            "prompt_cache_shield": self.capabilities.prompt_cache_shield,
            "tool_filter": sorted(self.capabilities.tool_filter) or None,
            "mcp_surface": self.capabilities.mcp_surface,
            "adapter_version": "5.0-pragmatic",
        }
        try:
            from local_ai_hub.repo_plan.host_adapters import probe_host_capabilities
            host_rep = probe_host_capabilities(host_name=self.client_id, repo_root=repo_root)
            report["support_level"] = host_rep.support_level
            report["instructions_integrated"] = host_rep.instructions_integrated
        except Exception:
            report["support_level"] = "advisory"
            report["instructions_integrated"] = False
        return report
