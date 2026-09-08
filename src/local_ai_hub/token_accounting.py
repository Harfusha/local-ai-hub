from __future__ import annotations

"""Conservative token-efficiency accounting.

The module deliberately separates *measured protocol overhead* from *estimated
cloud-context avoidance*.  It never stores prompts/source/model output; callers
pass only already-computed token counts or bounded result metadata.

Accounting rules:
- Tool request/output costs are estimated from the exact JSON visible at the MCP
  boundary. These are subtracted from gross cloud-context savings.
- Savings signals that can describe the same transformation are not summed. The
  largest measured source-context baseline is selected. Response compaction is
  tracked independently and becomes the headline baseline only when no stronger
  input-side baseline exists. This prevents raw->packed->projected double counting.
- Tool schema exposure is reported separately because hosts differ in whether/how
  often schemas are injected. It is not subtracted from the default net metric.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from .budget import estimate_tokens


_PRIVATE_KEY = "_token_accounting"


def json_tokens(value: Any) -> int:
    """Estimate tokens for the exact compact JSON representation of ``value``.

    Use the JSON encoder incrementally instead of materialising a second full copy
    of potentially large tool output. This keeps accounting memory-bounded on the
    foreground MCP path while preserving the same UTF-8-byte token estimate.
    """
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), default=str)
        byte_count = 0
        for chunk in encoder.iterencode(value):
            byte_count += len(chunk.encode("utf-8"))
        if byte_count <= 0:
            return 0
        # Keep this exactly aligned with budget.estimate_tokens (ceil(bytes / 3.4))
        # without allocating the complete serialized JSON string.
        return max(1, (byte_count * 10 + 33) // 34)
    except Exception:
        return max(0, estimate_tokens(str(value)))


def tool_request_tokens(tool_name: str, arguments: Mapping[str, Any]) -> int:
    # This mirrors the semantic payload a tool-capable model emits: tool name + args.
    return json_tokens({"name": str(tool_name), "arguments": dict(arguments)})


def tool_response_tokens(value: Any) -> int:
    return json_tokens(value)




_ACCOUNTING_NOISE_KEYS = {
    _PRIVATE_KEY, "token_saving", "prompt_budget", "semantic_similarity", "coalesced",
    "load_duration_ns", "eval_count", "prompt_eval_count", "prompt_eval_duration_ns",
    "eval_duration_ns", "total_duration_ns", "workspace_cache",
}

def _strip_accounting_noise(value: Any, *, depth: int = 0) -> Any:
    """Remove Hub-internal diagnostics before measuring response compaction.

    Counting bytes that were never intended for the agent would inflate savings.
    Keep the transformation bounded because this runs on the MCP foreground path.
    """
    if depth > 5:
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in list(value.items())[:128]:
            if str(key) in _ACCOUNTING_NOISE_KEYS or str(key).startswith("_lah_"):
                continue
            out[str(key)] = _strip_accounting_noise(child, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_strip_accounting_noise(v, depth=depth + 1) for v in value[:128]]
    return value


def _nonneg_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass
class SavingsSignals:
    input_candidates: dict[str, int] = field(default_factory=dict)
    output_candidates: dict[str, int] = field(default_factory=dict)
    local_compute_candidates: dict[str, int] = field(default_factory=dict)

    def add_input(self, source: str, tokens: int) -> None:
        tokens = _nonneg_int(tokens)
        if tokens:
            self.input_candidates[source] = max(tokens, self.input_candidates.get(source, 0))

    def add_output(self, source: str, tokens: int) -> None:
        tokens = _nonneg_int(tokens)
        if tokens:
            self.output_candidates[source] = max(tokens, self.output_candidates.get(source, 0))

    def add_local(self, source: str, tokens: int) -> None:
        tokens = _nonneg_int(tokens)
        if tokens:
            self.local_compute_candidates[source] = max(tokens, self.local_compute_candidates.get(source, 0))

    def summary(self) -> dict[str, Any]:
        input_source, input_saved = max(self.input_candidates.items(), key=lambda kv: kv[1], default=("", 0))
        output_source, output_saved = max(self.output_candidates.items(), key=lambda kv: kv[1], default=("", 0))
        local_source, local_saved = max(self.local_compute_candidates.items(), key=lambda kv: kv[1], default=("", 0))

        # End-to-end baseline selection is deliberately conservative. A packed tool
        # response is commonly derived from the same repository/source context as an
        # input-side saving signal. Adding raw->packed and packed->projected deltas
        # would count one context chain twice. Prefer the strongest source-context
        # baseline; use response compaction as the baseline only when no independent
        # input baseline exists. The visible response is charged exactly once later.
        gross = input_saved if input_saved else output_saved
        selected_source = input_source if input_saved else output_source
        breakdown: dict[str, int] = {selected_source: gross} if gross and selected_source else {}
        return {
            "gross_cloud_tokens_avoided_est": gross,
            "gross_input_tokens_avoided_est": input_saved,
            "gross_output_tokens_avoided_est": output_saved,
            "local_compute_tokens_avoided_est": local_saved,
            "savings_breakdown": breakdown,
            "input_savings_source": input_source,
            "output_savings_source": output_source,
            "local_compute_source": local_source,
        }


def _scan(value: Any, signals: SavingsSignals, *, depth: int = 0, seen: set[int] | None = None) -> None:
    if depth > 6:
        return
    if seen is None:
        seen = set()
    if isinstance(value, (dict, list)):
        ident = id(value)
        if ident in seen:
            return
        seen.add(ident)
    if isinstance(value, list):
        for item in value[:64]:
            _scan(item, signals, depth=depth + 1, seen=seen)
        return
    if not isinstance(value, dict):
        return

    saving = value.get("token_saving")
    if isinstance(saving, dict):
        signals.add_input("delegated_context", saving.get("delegated_cloud_context_tokens_avoided_est", 0))
        signals.add_output("response_compaction", saving.get("compact_output_tokens_avoided_est", 0))
        signals.add_local("cache_or_local_reuse", saving.get("local_compute_tokens_avoided_est", 0))

    original = _nonneg_int(value.get("original_estimated_tokens"))
    packed = _nonneg_int(value.get("estimated_tokens"))
    if original and original > packed:
        # `original` is the counterfactual source/context volume. `packed` is part
        # of the actual tool response and is charged at the MCP boundary, so using
        # (original-packed) here would subtract the visible response twice.
        signals.add_input("context_compaction", original)
    routed_input = _nonneg_int(value.get("input_tokens_est"))
    if routed_input and routed_input > packed:
        signals.add_input("deterministic_routing", routed_input)

    original_diff = _nonneg_int(value.get("original_diff_tokens"))
    local_diff = _nonneg_int(value.get("local_diff_tokens"))
    if original_diff and original_diff > local_diff:
        signals.add_input("diff_compaction", original_diff)

    raw = _nonneg_int(value.get("raw_tokens"))
    outline = _nonneg_int(value.get("outline_tokens"))
    if raw and raw > outline:
        signals.add_input("deterministic_outline", raw)

    # Explicit private metadata lets deterministic/retrieval layers report a measured
    # baseline without exposing accounting chatter to the agent.
    private = value.get(_PRIVATE_KEY)
    if isinstance(private, dict):
        explicit_breakdown = private.get("savings_breakdown")
        if isinstance(explicit_breakdown, dict):
            for source, tokens in explicit_breakdown.items():
                signals.add_input(str(source)[:64], tokens)
        signals.add_input("measured_context", private.get("gross_input_tokens_avoided_est", 0))
        signals.add_output("response_compaction", private.get("gross_output_tokens_avoided_est", 0))
        signals.add_local("local_compute", private.get("local_compute_tokens_avoided_est", 0))

    for key, child in list(value.items())[:96]:
        if key == _PRIVATE_KEY:
            continue
        if isinstance(child, (dict, list)):
            _scan(child, signals, depth=depth + 1, seen=seen)


def measure_savings(value: Any) -> dict[str, Any]:
    signals = SavingsSignals()
    _scan(value, signals)
    return signals.summary()


def attach_accounting(value: Any) -> Any:
    """Attach private measured savings metadata before agent-facing projection."""
    if not isinstance(value, dict):
        return value
    measured = measure_savings(value)
    if measured.get("gross_cloud_tokens_avoided_est") or measured.get("local_compute_tokens_avoided_est"):
        value = dict(value)
        value[_PRIVATE_KEY] = measured
    return value


def pop_accounting(value: Any) -> tuple[Any, dict[str, Any]]:
    """Remove private metadata from a tool response and return it separately.

    When private accounting metadata is present it is already the authoritative
    pre-projection measurement. Avoid rescanning the whole response a second time;
    large evidence/diff payloads otherwise paid avoidable foreground CPU cost.
    """
    if not isinstance(value, dict):
        return value, measure_savings(value)
    clean = dict(value)
    private = clean.pop(_PRIVATE_KEY, None)
    if isinstance(private, dict):
        measured = {
            "gross_cloud_tokens_avoided_est": _nonneg_int(private.get("gross_cloud_tokens_avoided_est")),
            "gross_input_tokens_avoided_est": _nonneg_int(private.get("gross_input_tokens_avoided_est")),
            "gross_output_tokens_avoided_est": _nonneg_int(private.get("gross_output_tokens_avoided_est")),
            "local_compute_tokens_avoided_est": _nonneg_int(private.get("local_compute_tokens_avoided_est")),
            "savings_breakdown": dict(private.get("savings_breakdown", {})) if isinstance(private.get("savings_breakdown"), dict) else {},
            "input_savings_source": str(private.get("input_savings_source", ""))[:64],
            "output_savings_source": str(private.get("output_savings_source", ""))[:64],
            "local_compute_source": str(private.get("local_compute_source", ""))[:64],
        }
        return clean, measured
    return clean, measure_savings(clean)


def account_projection(raw_value: Any, projected_value: Any) -> Any:
    """Account for last-mile tool-output projection without exposing metadata.

    The raw service result is the output a cloud agent could otherwise have had to
    inspect. The projected MCP result is what the agent actually sees. The measured
    delta is output-side savings and competes (max, not sum) with any existing
    response-compaction signal so the same reduction is never double counted.
    """
    if not isinstance(projected_value, dict):
        return projected_value
    try:
        raw_tokens = json_tokens(_strip_accounting_noise(raw_value))
        clean, measured = pop_accounting(projected_value)
        visible_tokens = json_tokens(clean)
        projected_saved = max(0, raw_tokens - visible_tokens)
        previous_output = _nonneg_int(measured.get("gross_output_tokens_avoided_est"))
        output_saved = max(previous_output, projected_saved)
        input_saved = _nonneg_int(measured.get("gross_input_tokens_avoided_est"))
        if output_saved:
            measured["gross_output_tokens_avoided_est"] = output_saved
            measured["output_savings_source"] = "response_compaction"
            breakdown = measured.get("savings_breakdown") if isinstance(measured.get("savings_breakdown"), dict) else {}
            breakdown = dict(breakdown)
            breakdown["response_compaction"] = max(_nonneg_int(breakdown.get("response_compaction")), output_saved)
            measured["savings_breakdown"] = breakdown
        measured["gross_cloud_tokens_avoided_est"] = input_saved if input_saved else output_saved
        # Keep the attribution breakdown additive-safe as well. Output compaction
        # remains visible through gross_output_tokens_avoided_est but is not added
        # on top of an upstream source-context baseline.
        selected_source = str(measured.get("input_savings_source", "")) if input_saved else str(measured.get("output_savings_source", ""))
        if selected_source and measured["gross_cloud_tokens_avoided_est"]:
            measured["savings_breakdown"] = {selected_source: measured["gross_cloud_tokens_avoided_est"]}
        if measured.get("gross_cloud_tokens_avoided_est") or measured.get("local_compute_tokens_avoided_est"):
            clean[_PRIVATE_KEY] = measured
        return clean
    except Exception:
        return projected_value


def finalize_tool_accounting(
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    response: Any,
    measured: Mapping[str, Any] | None = None,
    schema_tokens_est: int = 0,
) -> dict[str, Any]:
    measured = dict(measured or {})
    request_tokens = tool_request_tokens(tool_name, arguments)
    response_tokens = tool_response_tokens(response)
    gross = _nonneg_int(measured.get("gross_cloud_tokens_avoided_est"))
    protocol = request_tokens + response_tokens
    schema = _nonneg_int(schema_tokens_est)

    # Signed delta is the source of truth — a tool call that saves no context
    # but costs 120 protocol tokens shows -120, not an artificial 0.
    net_delta = gross - protocol
    schema_adjusted_delta = net_delta - schema
    return {
        "tool": str(tool_name)[:80],
        "gross_cloud_tokens_avoided_est": gross,
        "gross_input_tokens_avoided_est": _nonneg_int(measured.get("gross_input_tokens_avoided_est")),
        "gross_output_tokens_avoided_est": _nonneg_int(measured.get("gross_output_tokens_avoided_est")),
        "input_savings_source": str(measured.get("input_savings_source", ""))[:64],
        "output_savings_source": str(measured.get("output_savings_source", ""))[:64],
        "agent_tool_request_tokens_est": request_tokens,
        "agent_tool_response_tokens_est": response_tokens,
        "agent_protocol_tokens_est": protocol,
        "tool_schema_tokens_est": schema,
        "net_cloud_token_delta_est": net_delta,
        "cloud_token_overhead_est": max(0, -net_delta),
        "net_after_schema_token_delta_est": schema_adjusted_delta,
        "schema_adjusted_overhead_est": max(0, -schema_adjusted_delta),
        "local_compute_tokens_avoided_est": _nonneg_int(measured.get("local_compute_tokens_avoided_est")),
        "savings_breakdown": measured.get("savings_breakdown", {}) if isinstance(measured.get("savings_breakdown"), dict) else {},
    }
