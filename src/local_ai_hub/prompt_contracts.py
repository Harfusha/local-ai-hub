"""Reusable, evidence-grounded prompt contracts for local model operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ModelCapability:
    model: str
    tier: str
    can: tuple[str, ...]
    cannot: tuple[str, ...]


@dataclass(frozen=True)
class PromptPackage:
    system: str
    user: str
    capability: ModelCapability
    operation: str


_CAPABILITIES = {
    "qwen2.5-coder:0.5b": ModelCapability(
        "qwen2.5-coder:0.5b", "background", ("preprocess", "extract", "classify", "compress"),
        ("root_cause", "cross_file_reasoning", "architecture", "security_decision", "apply_changes"),
    ),
    "qwen2.5-coder:1.5b": ModelCapability(
        "qwen2.5-coder:1.5b", "fast", ("extract", "classify", "compress", "single_file_explain", "checklist"),
        ("root_cause", "cross_file_reasoning", "architecture", "security_decision", "apply_changes"),
    ),
    "qwen2.5-coder:3b": ModelCapability(
        "qwen2.5-coder:3b", "smart", ("single_file_explain", "bounded_review", "test_plan", "simple_patch_plan", "compare"),
        ("architecture", "security_decision", "high_risk_migration", "apply_changes"),
    ),
    "qwen2.5-coder:7b": ModelCapability(
        "qwen2.5-coder:7b", "reasoning", ("bounded_review", "root_cause", "cross_file_reasoning", "test_plan", "patch_plan", "compare"),
        ("security_decision", "apply_changes", "final_verification"),
    ),
    "qwen3-vl:4b": ModelCapability(
        "qwen3-vl:4b", "vision", ("visual_review", "visual_issue_list", "accessibility_observation", "extract"),
        ("source_only_reasoning", "security_decision", "apply_changes", "final_verification"),
    ),
    "qwen3.5:9b": ModelCapability(
        "qwen3.5:9b", "heavy", ("bounded_review", "root_cause", "cross_file_reasoning", "patch_plan", "visual_review", "compare"),
        ("apply_changes", "security_decision", "final_verification"),
    ),
}

_OPERATION_GUIDANCE = {
    "delegate": "Answer the bounded task using the supplied evidence.",
    "explore": "Identify the smallest set of relevant facts, paths and symbols; do not invent missing context.",
    "reason": "Compare concrete hypotheses, select the strongest one, and explain what evidence supports or weakens it.",
    "review": "Find concrete correctness, regression, security or test risks in the supplied material.",
    "review_diff": (
        "Review only the changed hunk. Check regression risk, changed contracts, error handling, security/concurrency "
        "and missing tests. Report `None found` when the supplied diff contains no actionable defect."
    ),
    "second_opinion": "Challenge the candidate independently and state concrete corrections or reasons it survives review.",
    "compress": "Compress the supplied evidence while preserving paths, identifiers, numbers, decisions and uncertainty.",
    "speculative_draft": "Propose the smallest patch shape from the supplied evidence; never claim that it was applied.",
    "vision": "Describe only visible, evidence-backed UI or image findings and separate observation from inference.",
}


def capability_for(model: str, *, role: str = "") -> ModelCapability:
    """Return conservative capabilities for a configured or custom model."""

    normalized = str(model or "").strip().lower()
    known = _CAPABILITIES.get(normalized)
    if known is not None:
        if str(role).lower() == "vision" and "visual_review" not in known.can:
            return ModelCapability(known.model, known.tier, known.can + ("visual_review",), known.cannot)
        return known
    if "vl" in normalized or str(role).lower() == "vision":
        return ModelCapability(model, "vision", ("visual_review", "visual_issue_list", "extract"), ("source_only_reasoning", "apply_changes"))
    if any(size in normalized for size in ("9b", "13b", "14b", "32b")):
        return ModelCapability(model, "heavy", ("bounded_review", "root_cause", "cross_file_reasoning", "patch_plan", "compare"), ("apply_changes", "final_verification"))
    if "7b" in normalized:
        return _CAPABILITIES["qwen2.5-coder:7b"]
    if "3b" in normalized:
        return _CAPABILITIES["qwen2.5-coder:3b"]
    if "1.5b" in normalized or "1b" in normalized:
        return _CAPABILITIES["qwen2.5-coder:1.5b"]
    return _CAPABILITIES["qwen2.5-coder:0.5b"]


def _clip(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: max(0, limit - 24)] + "\n...[bounded]"


def _lines(values: Iterable[str], limit: int = 12) -> str:
    items = [str(value).strip() for value in values if str(value).strip()]
    return "\n".join(f"- {item}" for item in items[:limit]) or "- none supplied"


def build_prompt(
    *,
    operation: str,
    model: str,
    task: str,
    context: str = "",
    profile: str = "",
    changed_paths: Iterable[str] = (),
    evidence_ids: Iterable[str] = (),
    acceptance_criteria: Iterable[str] = (),
    repository_revision: str = "",
    static_facts: str = "",
    role: str = "",
) -> PromptPackage:
    """Build a compact static contract plus a bounded task-specific prompt."""

    operation_name = str(operation or "delegate").strip().lower()
    guidance = _OPERATION_GUIDANCE.get(operation_name, _OPERATION_GUIDANCE["delegate"])
    capability = capability_for(model, role=role)
    profile_name = str(profile or "auto").strip().lower()
    profile_rule = (
        "This is the integrated profile: use one focused pass, keep the evidence pack small, and do not broaden the search."
        if profile_name == "integrated" else
        "Use the selected hardware profile's context and latency budget; do not request unavailable tools."
    )
    system = _clip(
        f"You are a local AI Hub {operation_name} specialist. Advisory only: do not edit files, execute commands, "
        "or claim verification. Terse technical output only: zero conversational filler, but be concise and complete; "
        "never trade project-specific evidence for generic advice. "
        "Use only supplied repository facts and clearly label inference. If evidence is insufficient, state exactly "
        "what is missing. Preserve paths, symbols, identifiers, numbers and uncertainty. "
        "A generic restatement is not an answer: name the exact supplied operation, field, endpoint or model behavior; "
        "do not introduce unrelated hardware, software, frameworks, files or APIs merely because they are plausible. "
        "For diagnosis, separate OBSERVED from INFERENCE and give one falsifiable verification step. "
        "Never report a bare location such as 'line 42': attach every location to a supplied path as path:line. "
        "If TASK requests an exact output shape, follow that shape while retaining evidence and uncertainty. "
        f"Operation contract: {guidance} {profile_rule} "
        f"Model capability tier: {capability.tier}. Allowed strengths: {', '.join(capability.can)}. "
        f"Out of scope for this model: {', '.join(capability.cannot)}.",
        2100,
    )
    user = (
        f"{operation_name.upper()}\n"
        "OPERATION CONTRACT:\n" + guidance + "\n\n"
        "TASK:\n" + _clip(task, 3500) + "\n\n"
        "ACCEPTANCE CRITERIA:\n" + _lines(acceptance_criteria) + "\n\n"
        "AUTHORITATIVE EVIDENCE IDS:\n" + _lines(evidence_ids) + "\n\n"
        "CHANGED / ALLOWED PATHS:\n" + _lines(changed_paths) + "\n\n"
        f"REPOSITORY REVISION: {repository_revision or 'not supplied'}\n\n"
        "STATIC FACTS:\n" + _clip(static_facts, 1800) + "\n\n"
        "CONTEXT:\n" + _clip(context, 12500) + "\n\n"
        "REQUIRED RESPONSE:\n"
        "1. SUMMARY: one concrete conclusion for this task / Konkrétní závěr.\n"
        "2. EVIDENCE: cite supplied evidence IDs and paths.\n"
        "3. ANALYSIS: explain the project-specific reasoning, not generic best practices.\n"
        "4. LIMITATIONS: state unknowns instead of guessing.\n"
        "5. NEXT: one concrete next step, or `None found`.\n"
        "Nevymýšlej soubory, API, symboly, řádky ani výsledky testů. Každý řádek musí odkazovat na dodaný důkaz; "
        "holé 'line N' nepoužívej. Obecné rady bez vazby na dodaný context označ jako nedostatečné."
    )
    return PromptPackage(system=system, user=user, capability=capability, operation=operation_name)
