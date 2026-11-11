from local_ai_hub.command_policy import (
    DANGEROUS_EXES,
    KNOWN_PYTHON_MODULES,
    MUTATING_WORDS,
    POWERSHELL_DANGEROUS,
    POWERSHELL_MUTATING,
    POWERSHELL_READ_PREFIXES,
    POWERSHELL_VALIDATION_KEYWORDS,
    PURE_VALIDATORS,
    READ_FILTERS,
    READ_ONLY,
    SHELL_INTERPRETERS,
    VALIDATORS,
    VOLATILE_READS,
)
from local_ai_hub.command_git import classify_git_command
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


def test_extracted_shell_policy_retains_classification_terms():
    assert SHELL_INTERPRETERS == {"sh", "bash", "dash", "zsh", "fish", "cmd", "powershell", "pwsh"}
    assert "invoke-webrequest" in POWERSHELL_DANGEROUS
    assert "set-content" in POWERSHELL_MUTATING
    assert POWERSHELL_VALIDATION_KEYWORDS == {"test", "validate", "check", "audit", "-runtests", "pester"}
    assert "get-" in POWERSHELL_READ_PREFIXES


def test_extracted_git_classifier_preserves_read_and_mutation_policy():
    read = classify_git_command(["git", "status"], ["status"], {})
    mutating = classify_git_command(["git", "push"], ["push"], {})

    assert read == {
        "class": "read",
        "cacheable": True,
        "allowed": True,
        "reason": "read-only git status",
    }
    assert mutating == {
        "class": "mutating",
        "cacheable": False,
        "allowed": False,
        "reason": "git push may mutate",
    }


def test_extracted_git_classifier_rejects_external_execution_flags():
    result = classify_git_command(
        ["git", "--paginate", "status"], ["--paginate", "status"], {}
    )

    assert result == {
        "class": "unknown",
        "cacheable": False,
        "allowed": False,
        "reason": "git flags may execute a pager or external program",
    }


def test_extracted_git_classifier_respects_read_mutation_config():
    read = classify_git_command(["git", "status"], ["status"], {"allow_read": False})
    mutating = classify_git_command(
        ["git", "push"], ["push"], {"allow_mutating": True}
    )

    assert read["allowed"] is False
    assert mutating["allowed"] is True
