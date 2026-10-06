# T21/T09 completion project-root binding regression

Status: confirmed root-source RED; not fixed, not done.

Owner: orchestrator owns only `tests/test_t21_completion_root_binding.py` and this test-only handoff. T09 owns `verification_rules.py` production correction; T20 owns root integration and serialized root acceptance. Existing dirty work is excluded. No `/api/context/pack` edits.

Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
Root `verification_rules.py` SHA256: `157129234E47605307D208BB586E2D8351E619271E79720BA7D0555569FA61B3`.
Root `agent_verification.py` SHA256 at handoff: `FDE1CF9EBC4D76324C33FDAA78190FAADBCCD7E953D8BE9D292A7AFFD96FDC73`.

## Evidence

The test creates real TaskStore, VerificationStore, ArtifactStore and durable proof fixtures. The trusted task project requires test and lint receipts; only the valid test receipt exists. Evaluating its actual config reports missing lint. Supplying a different empty project as completion root nevertheless completes the task. Both physical repository identity and opaque repository identity variants fail with `DID NOT RAISE CompletionGateError`. A canonical alias of the correct task root completes successfully.

Exact executed command (PowerShell, candidate cwd `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`):

```powershell
@'
import importlib
import pathlib
import sys
root_src = pathlib.Path(r'C:\Users\Adam\.local-ai-hub\src').resolve()
sys.path.insert(0, str(root_src))
for name in ('project_config', 'verification_rules', 'agent_tasks', 'agent_events', 'agent_verification', 'artifacts', 'agent_identity'):
    module = importlib.import_module('local_ai_hub.' + name)
    origin = pathlib.Path(module.__file__).resolve()
    assert origin.is_relative_to(root_src), (name, origin)
    print('ROOT_IMPORT', name, origin)
import pytest
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short', 'tests/test_t21_completion_root_binding.py']))
'@ | python -B -
```

Actual result: **2 failed, 1 passed in 2.59s**, process exit 1; all seven asserted runtime module origins are root `src`. SQLite/config/proofs are temporary fixtures, not live Hub state. This does not prove a real runner executed; this regression tests completion root binding using valid persisted proof fixtures.

The earlier `-o pythonpath=...` invocation accidentally imported the older candidate adapter and had fixture/signature errors. Those errors are NOT regression evidence. Explicit root pre-import above establishes genuine RED.

## Required correction

Resolve completion config from the task's trusted physical project/worktree binding, not an unvalidated request root. Reject a mismatched supplied root before checkpoint writes or completion. Preserve task scope, owner, current revision and proof validation. Accept equivalent canonical paths. Do not replace an opaque repository identity with an arbitrary caller-selected path. Add missing-binding fail-closed policy according to current task contract; never silently adopt unrelated project config.

Integrate only the added test patch `handoff/T21-completion-root-binding-test.patch`; no production files included. T09 should run this regression with its actual candidate verifier/adapter and explicit import provenance, plus its HTTP completion matrix. T20 must perform post-integration root verification. Acceptance remains open until those results exist.
