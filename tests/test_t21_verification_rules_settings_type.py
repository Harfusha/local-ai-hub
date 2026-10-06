from __future__ import annotations

from typing import get_type_hints

from local_ai_hub.verification_rules import evaluate_project_completion
from local_ai_hub.project_config import ProjectSettings


def test_evaluator_settings_annotation_resolves_to_project_settings() -> None:
    assert get_type_hints(evaluate_project_completion)["settings"] is ProjectSettings
