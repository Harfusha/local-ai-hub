"""Docs-only current source contracts; no Hub imports, execution or GPU proof.

Source origins (read-only current root checkout):
http_server.py:4490-4667 (pack controls/guards/task receipt),
project_config.py:178-259,805-884 (scoped overlays/hints),
client.py:313-330,690-724 (startup and hints),
operational_mode.py:116-141,183-205 (persisted modes and gating),
agent_context.py:747-859,963-1007 (memory selection/non-use IDs/budget),
agent_memory.py:1273-1315 (scope/status/sensitivity/expiry filtering),
mcp_server.py:800-875 (automatic task context), adoption_metrics.py:14-17,48-51.
Schema origin: T19 generator.py:858-943 and features.py:154-188;
phase origin: T19 agent_consistency.py:53-100; standalone: docs/INSTALLATION.md:30-32.
Module paths above are under src/local_ai_hub/. These assertions protect docs
parity; they do not import or validate root runtime behavior.

R2 source: current-root agent_tasks.py:229-242,414-429,500-518,568-643;
http_server.py:3294-3317,3406-3484,3531-3568 (checkpoint/record/delete).
"""

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md")


@pytest.mark.parametrize("name", PROMPTS)
def test_current_adaptive_pack_contract(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    for contract in (
        'local_ai_repo(action="context", mode="adaptive")',
        "### Adaptive context and supported capabilities",
        "`plan`, `discover`, `edit`, `implementation`, `review`, `test`, or `handoff`",
        "`/api/context/pack` defaults to `adaptive`",
        "`focus` and `changed_paths` are lists",
        "`guarded=true`, `task_id`, `phase`, or `session_id`",
        "`context_task_context_unavailable`",
        "reuse candidates",
    ):
        assert contract in prompt, f"{name}: missing source-backed contract: {contract}"


@pytest.mark.parametrize("name", PROMPTS)
def test_current_schema_and_autonomy_boundary(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    for contract in (
        "Feature-specific schemas expose only enabled tools/actions",
        "`dry_run` and `edits` require `features.batch_replacement`",
        "`local_ai_task` requires tasks plus a configured model",
        "CodeGraph remains optional external standalone tooling",
        "Cloud reasoning and planning are never blocked by mandatory local handoffs",
        "Source contracts do not establish physical GPU execution",
    ):
        assert contract in prompt, f"{name}: missing source-backed boundary: {contract}"


@pytest.mark.parametrize("name", PROMPTS)
def test_current_scoped_path_controls(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    for contract in (
        "`.local-ai.toml`", "`.local-ai.worktree.toml`", "`info/local-ai.toml`",
        "Cross-worktree Agent OS memory sharing remains HOLD",
        "`HubClient.post` accepts optional `request_id`, `path_hints`, `tenant`, and `cancel_event`. It bounds typed hints and forwards them to `/api/search` and `/api/command`; an explicit `path` removes those hints.",
        "HTTP `/api/context/pack` accepts `path_hints`, `directory_hints`, `exclude_paths`, and `force_include_paths` in `adaptive` mode and validates lists. T14 owns that contract.",
        "request hints remain subordinate to root containment and hard exclusions",
    ):
        assert contract in prompt, f"{name}: missing current path contract: {contract}"
    assert "`/api/context/pack` does not accept or use hints" not in prompt
    assert "forwards them to `/api/search` and `/api/command`" in prompt


@pytest.mark.parametrize("name", PROMPTS)
def test_current_operational_mode_boundary(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    for contract in (
        "`active`, `gaming`, and `maintenance`",
        "missing persisted state defaults to `active`",
        "invalid/unreadable state degrades to `maintenance`",
        "`gaming` permits non-heavy work",
        "`status`, `wait`, `result`, `cancel`, and `evaluation_report`",
        "`HubClient.ensure_server` does not auto-start an offline server",
        "`terminal=false`, `retryable=true`, and `retry_after_seconds=5`",
    ):
        assert contract in prompt, f"{name}: missing mode contract: {contract}"


@pytest.mark.parametrize("name", PROMPTS)
def test_current_memory_adoption_evidence_boundary(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    for contract in (
        "`local_ai_task(task_id=...)` automatically compiles task context",
        "Use IDs are selected `memory_record` elements' `element_id` values",
        "Non-use IDs are bounded diagnostics",
        "`stale_ids`, `quarantined_ids`, `rejected_ids`, and `superseded_ids`",
        "only normal-sensitivity, unexpired `active`/`confirmed` memory",
        "IDs show selection or exclusion, not proof that a model followed memory",
        "Do not invent an exhaustive adoption/non-use receipt",
        "`/api/adoption` stores low-cardinality aggregates",
        "fall through to fresh bounded repository evidence",
    ):
        assert contract in prompt, f"{name}: missing memory boundary: {contract}"


def test_both_prompts_share_current_contract_sections() -> None:
    sections = []
    for name in PROMPTS:
        prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
        start = prompt.index("### Adaptive context and supported capabilities")
        end = prompt.find("### Document and diagram ingestion", start)
        sections.append(prompt[start:end if end >= 0 else len(prompt)])
    assert sections[0] == sections[1]


@pytest.mark.parametrize("name", PROMPTS)
def test_r2_agent_memory_adoption_directives(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    for directive in (
        "Agents must consider supplied relevant memory",
        "verify volatile facts against current source before relying on them",
        "checkpoint `state_data.memory_audit`",
        "`used_ids` must be a list of IDs from server-managed `memory_context.items[].id`",
        "`not_used_reason` must be nonempty when `used_ids` is empty",
        "`source_checks` keyed by each used volatile record ID",
        "each check needs nonempty `source` or an `evidence_ids` list containing a nonempty string",
        "Do not invent IDs or copy `preload_memory_*` IDs into the audit",
        "Do not replace or modify server-managed `memory_context`",
        "Save only confirmed reusable findings",
        "Never store chat history, prompts, source text, model output, secrets, or personal data",
        "Use existing installed-schema memory actions",
        "preserve original source, provenance, evidence and prior-record linkage",
        "no new memory store or invented correction alias",
    ):
        assert directive in prompt, f"{name}: missing R2 directive: {directive}"
    assert "ignored_ids" not in prompt


@pytest.mark.parametrize("name", PROMPTS)
def test_r2_checkpoint_examples_match_documented_validator_shape(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    assert "### Memory adoption checkpoints" in prompt
    section = prompt.split("### Memory adoption checkpoints", 1)[1].split("### Document and diagram ingestion", 1)[0]
    examples = [
        json.loads(block.split("\n```", 1)[0])
        for block in section.split("```json\n")[1:]
    ]
    assert len(examples) == 3
    used, checked, unused = (example["state_data"]["memory_audit"] for example in examples)
    assert used == {"used_ids": ["supplied-record-id"]}
    assert checked["used_ids"] == ["supplied-volatile-id"]
    checks = checked["source_checks"]
    assert set(checks) == {"supplied-volatile-id"}
    assert checks["supplied-volatile-id"]["source"].strip()
    assert checks["supplied-volatile-id"]["evidence_ids"]
    assert unused["used_ids"] == [] and unused["not_used_reason"].strip()
    assert all("memory_context" not in example["state_data"] for example in examples)


@pytest.mark.parametrize("name", PROMPTS)
def test_maintenance_contract_is_not_redefined_as_gaming(name: str) -> None:
    prompt = (ROOT / "docs" / name).read_text(encoding="utf-8")
    assert "`maintenance` must reject every agent MCP/API action before Agent OS database access" in prompt
    assert "operator-only mode, health, and dashboard controls remain available" in prompt
    assert "both non-degraded paused modes allow" not in prompt
    assert "maintenance safe-job exception fix remains pending" in prompt
