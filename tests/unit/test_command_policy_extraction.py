from local_ai_hub.command_policy import (
    DANGEROUS_EXES,
    KNOWN_PYTHON_MODULES,
    MUTATING_WORDS,
    PURE_VALIDATORS,
    READ_FILTERS,
    READ_ONLY,
    VALIDATORS,
    VOLATILE_READS,
)
from local_ai_hub.commands import CommandBroker


def test_command_broker_keeps_compatibility_aliases_for_extracted_policy():
    assert CommandBroker.READ_ONLY is READ_ONLY
    assert CommandBroker.READ_FILTERS is READ_FILTERS
    assert CommandBroker.VOLATILE_READS is VOLATILE_READS
    assert CommandBroker.VALIDATORS is VALIDATORS
    assert CommandBroker.PURE_VALIDATORS is PURE_VALIDATORS
    assert CommandBroker.KNOWN_PYTHON_MODULES is KNOWN_PYTHON_MODULES
    assert CommandBroker.MUTATING_WORDS is MUTATING_WORDS
    assert CommandBroker.DANGEROUS_EXES is DANGEROUS_EXES


def test_extracted_command_policy_retains_fail_closed_classification_sets():
    assert {"git", "rg", "pytest"} <= READ_ONLY | VALIDATORS
    assert {"install", "delete", "deploy"} <= MUTATING_WORDS
    assert {"rm", "rmdir", "shutdown"} <= DANGEROUS_EXES
    assert VOLATILE_READS <= READ_ONLY
    assert "pytest" in PURE_VALIDATORS
    assert "select-string" in READ_FILTERS
    assert "compileall" in KNOWN_PYTHON_MODULES
