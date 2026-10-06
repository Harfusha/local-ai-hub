from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest


@pytest.fixture(autouse=True)
def _test_owned_mutation_fence(request, monkeypatch):
    if request.module.__name__ not in {"test_command_rollback", "test_command_transaction_snapshot"}:
        return

    from local_ai_hub.commands import CommandBroker
    from fencing_lease_support import FakeFencingLeaseStore, install_test_work_attempt_fence

    original_init = CommandBroker.__init__

    def init_with_test_fence(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        install_test_work_attempt_fence(self, FakeFencingLeaseStore())

    monkeypatch.setattr(CommandBroker, "__init__", init_with_test_fence)
