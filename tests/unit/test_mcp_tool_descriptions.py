from __future__ import annotations

from local_ai_hub.mcp_tool_descriptions import (
    describe_artifact,
    describe_coord,
    describe_rag,
    describe_repo,
    describe_status,
    describe_task,
    describe_work,
)


def test_work_description_keeps_enabled_submission_contract() -> None:
    def actions(tool: str, _features=None) -> tuple[str, ...]:
        assert tool == "local_ai_work"
        return ("submit", "status")

    description = describe_work(object(), True, actions, lambda tool: f" [trigger:{tool}]")

    assert description.startswith("Delegate one closed, low-risk work item")
    assert "Actions: submit, status." in description
    assert "task-specific model quality is evaluated" in description
    assert "[trigger:local_ai_work]" in description


def test_work_description_keeps_disabled_submission_contract() -> None:
    def actions(tool: str, _features=None) -> tuple[str, ...]:
        assert tool == "local_ai_work"
        return ("status",)

    description = describe_work(object(), True, actions, lambda _tool: "")

    assert description.startswith("Manage existing Local AI Hub work")
    assert "submitting a qualified" not in description
    assert "Actions: status." in description


def test_artifact_description_preserves_lean_and_full_contracts() -> None:
    def actions(tool: str) -> tuple[str, ...]:
        assert tool == "local_ai_artifact"
        return ("get", "slice", "source")

    lean = describe_artifact(True, actions, lambda tool: f" [trigger:{tool}]")
    full = describe_artifact(False, actions, lambda tool: f" [trigger:{tool}]")

    assert "Actions: get, slice, source." in lean
    assert "workspace-confined" in lean
    assert "[trigger:local_ai_artifact]" in lean
    assert "Evidence IDs start with E." in full
    assert "source or evidence text is required" in full


def test_task_description_keeps_feature_routing_contracts() -> None:
    class Features:
        tasks = True
        status = True
        subagents = False
        subagent_profiles = ()
        background_model = "prep-model"
        fast_model = "fast-model"
        smart_model = "smart-model"
        reasoning_model = "reasoning-model"

        @staticmethod
        def has_any_model() -> bool:
            return True

        @staticmethod
        def supported_task_actions() -> tuple[str, ...]:
            return ("review", "second_opinion", "compress")

    def actions_note(actions: tuple[str, ...]) -> str:
        return f" Actions: {', '.join(actions)}."

    def semantic_contract(enabled: bool, status_enabled: bool) -> str:
        return f" Semantic contract enabled={enabled}; status={status_enabled}."

    lean = describe_task(Features(), True, actions_note, semantic_contract, lambda _tool: " trigger")
    full = describe_task(Features(), False, actions_note, semantic_contract, lambda _tool: " trigger")

    assert "review, independent second opinions, semantic compression" in lean
    assert "Semantic contract enabled=True; status=True." in lean
    assert "Actions: review, second_opinion, compress." in lean
    assert "prep-model" in full and "reasoning-model" in full
    assert "trigger" in full


def test_rag_description_keeps_root_and_feature_contracts() -> None:
    class Features:
        rag = True

        @staticmethod
        def supported_rag_actions() -> tuple[str, ...]:
            return ("search", "index", "ingest_document")

    lean = describe_rag(Features(), True, lambda actions: f" Actions: {', '.join(actions)}.", lambda _tool: " trigger")
    full = describe_rag(Features(), False, lambda actions: f" Actions: {', '.join(actions)}.", lambda _tool: " trigger")
    disabled = describe_rag(FeaturesDisabled(), False, lambda _actions: "", lambda _tool: "")

    assert "root-bound workspace" in lean
    assert "RAG backend is disabled" in disabled
    assert "file-incremental and query-cached" in full
    assert "Actions: search, index, ingest_document." in full
    assert "trigger" in full


class FeaturesDisabled:
    rag = False

    @staticmethod
    def supported_rag_actions() -> tuple[str, ...]:
        return ()


def test_coord_description_keeps_agent_os_and_reservation_contracts() -> None:
    class Features:
        agent_os = True

        @staticmethod
        def supported_coord_actions() -> tuple[str, ...]:
            return (
                "gpu_reservation_status",
                "gpu_reservation_release",
                "gpu_reservation_release_authorized",
                "plan_list",
            )

    def actions_note(actions) -> str:
        return f" Actions: {', '.join(actions)}."

    description = describe_coord(
        Features(),
        True,
        actions_note,
        lambda: " Plan notes.",
        lambda tool: f" Trigger {tool}.",
    )

    assert description.startswith("Agent OS coordination for task contracts")
    assert "gpu_reservation_release_authorized requires explicit consent=true" in description
    assert "Malformed metadata and symlinks remain fail-closed." in description
    assert "Plan notes." in description
    assert "Trigger local_ai_coord." in description


def test_repo_description_keeps_disabled_and_lean_contracts() -> None:
    class DisabledFeatures:
        tasks = False
        status = False

        @staticmethod
        def has_any_model() -> bool:
            return False

    class LeanFeatures:
        tasks = True
        status = True
        fast_model = "fast-model"
        smart_model = "smart-model"
        reasoning_model = "reasoning-model"

        @staticmethod
        def has_any_model() -> bool:
            return True

        @staticmethod
        def has_semantic() -> bool:
            return True

        @staticmethod
        def semantic_hint() -> str:
            return "semantic-search"

        @staticmethod
        def supported_repo_actions() -> tuple[str, ...]:
            return ("code_index", "search", "solve")

    tier = lambda description: f"TIER[{description}]"
    actions = lambda values: f" Actions: {', '.join(values)}."
    semantic = lambda enabled, status: f" semantic={enabled},status={status}."
    specialized = lambda tool: f" trigger={tool}."

    disabled = describe_repo(DisabledFeatures(), False, tier, actions, semantic, specialized)
    lean = describe_repo(LeanFeatures(), True, tier, actions, semantic, specialized)

    assert "Local inference is disabled" in disabled
    assert "TIER[" in disabled
    assert "aggregate-bounded responses" in lean
    assert "adaptive context fuses deterministic/indexed evidence" in lean
    assert "Actions: search, code_index, context, solve, review_diff" in lean


def test_status_description_keeps_readiness_and_trigger_contract() -> None:
    description = describe_status(lambda tool: f" trigger={tool}.")

    assert description.startswith("Compact Hub and local-model readiness")
    assert "Use once when Hub or local inference availability affects the next action" in description
    assert "trigger=local_ai_status" in description
