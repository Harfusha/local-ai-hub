import pytest
from src.local_ai_hub.laya_edit_intent import (
    LayaEditIntentClassifier,
    EditIntent,
    BlastRadius,
    ValidationLevel,
)


def test_intent_classification():
    classifier = LayaEditIntentClassifier()

    # 1. Performance optimization across system
    res_perf = classifier.classify(
        instruction="Optimize zero-copy mmap shared memory buffer pool across files",
        affected_paths=["src/pool.py", "src/ipc.py", "src/engine.py"],
    )
    assert res_perf.intent == EditIntent.PERFORMANCE
    assert res_perf.blast_radius == BlastRadius.CROSS_FILE_ARCHITECTURE
    assert res_perf.validation_level == ValidationLevel.FULL_INVARIANT_GATE

    # 2. Local typing fix
    res_type = classifier.classify(
        instruction="Add type annotation to helper function in math_utils.py",
        affected_paths=["src/math_utils.py"],
    )
    assert res_type.intent == EditIntent.TYPING_DOCS
    assert res_type.blast_radius == BlastRadius.LOCAL_FUNCTION
    assert res_type.validation_level == ValidationLevel.SYNTAX_ONLY

    # 3. Bugfix in single module
    res_bug = classifier.classify(
        instruction="Fix KeyError crash when key is missing in config",
        affected_paths=["src/config.py"],
    )
    assert res_bug.intent == EditIntent.BUGFIX
    assert res_bug.validation_level in (ValidationLevel.LOCAL_UNIT_TEST, ValidationLevel.SYNTAX_ONLY)
