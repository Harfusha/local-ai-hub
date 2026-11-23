from dataclasses import FrozenInstanceError, is_dataclass

import pytest

from local_ai_hub.command_models import CommandInvocation as ExtractedCommandInvocation
from local_ai_hub.command_transactions import (
    PatchFileSnapshot as ExtractedPatchFileSnapshot,
    PatchTargetsSnapshot as ExtractedPatchTargetsSnapshot,
    RollbackFileSnapshot as ExtractedRollbackFileSnapshot,
    RollbackPostimage as ExtractedRollbackPostimage,
    RollbackSnapshot as ExtractedRollbackSnapshot,
)
from local_ai_hub.command_broker import CommandInvocation
from local_ai_hub.command_broker import (
    PatchFileSnapshot,
    PatchTargetsSnapshot,
    RollbackFileSnapshot,
    RollbackPostimage,
    RollbackSnapshot,
)


def test_commands_reexports_extracted_invocation_model():
    assert CommandInvocation is ExtractedCommandInvocation
    assert is_dataclass(CommandInvocation)

    invocation = CommandInvocation(argv=["python", "-m", "pytest"], cwd="repo")
    assert invocation.argv == ["python", "-m", "pytest"]
    assert invocation.cwd == "repo"
    assert invocation.shell is False
    with pytest.raises(FrozenInstanceError):
        invocation.cwd = "other"


def test_commands_reexports_transaction_snapshot_models():
    assert RollbackFileSnapshot is ExtractedRollbackFileSnapshot
    assert RollbackSnapshot is ExtractedRollbackSnapshot
    assert RollbackPostimage is ExtractedRollbackPostimage
    assert PatchFileSnapshot is ExtractedPatchFileSnapshot
    assert PatchTargetsSnapshot is ExtractedPatchTargetsSnapshot
