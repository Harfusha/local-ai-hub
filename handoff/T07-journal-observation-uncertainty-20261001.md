# T07 journal observation failure — genuine root-source RED

Owner: orchestrator owns only new `tests/test_t21_journal_observation_uncertainty.py` and this test-only patch/handoff. T07 owns HTTP/recovery production fix; T20 root integration/serialized acceptance. No edits to T07 production or context/pack.

Actual runtime imports preloaded and asserted under `C:\Users\Adam\.local-ai-hub\src`: `local_ai_hub.http_server`, `local_ai_hub.resilience`. Test cwd: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`.

Observed post-run source hashes (root remains under T20 concurrent integration, not a frozen release): `http_server.py` SHA256 `15BD92CE83A7FB472AAC4581F1A5FAD42ECF6E303C73C7DBC463E05A4528F57F`; `resilience.py` `88C16039AFC2919BB5E7F8DEAF2165AC09C2C064AD496BA15C1FD2FFAC2AC67E`.

The real temporary RecoveryJournal starts an original running mutation. Actual Handler._claim_recovery sees the existing running request and enters its observation branch. A controlled wait read failure occurs after the original owner writes a real file and, for two variants, persists a done/failed response. All three durable states (done, failed, still-running) and side-effect file remain intact. The duplicate response incorrectly claims `outcome_unknown=false` and `retryable=true` despite the original mutation having already happened. Existing `_journal_finished` must stay true to avoid rewriting another owner's terminal journal outcome.

Exact final test command:

```powershell
@'
import importlib
from pathlib import Path
import sys
root_src = Path(r'C:\Users\Adam\.local-ai-hub\src').resolve()
sys.path.insert(0, str(root_src))
for name in ('http_server', 'resilience'):
    module = importlib.import_module('local_ai_hub.' + name)
    origin = Path(module.__file__).resolve()
    assert origin.is_relative_to(root_src), (name, origin)
    print('ROOT_IMPORT', name, origin)
import pytest
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short', 'tests/test_t21_journal_observation_uncertainty.py']))
'@ | python -B -
```

Actual result: **3 failed in 0.57s**, exit 1, each at `assert result.get("outcome_unknown") is True`. Before that all real side-effect/journal-state assertions passed. No socket, live Hub, GPU or user state used. Earlier initial run had three fixture API errors (`lookup(payload=...)`); corrected to actual required `payload_fingerprint`. Those setup errors are not RED evidence; assertions and expectations were not weakened.

Required production correction: separate new, known-undispatched admission failure from failure while observing a pre-existing mutation. Observation failure must return structured terminal unknown (`outcome_unknown=true`, `terminal=true`, `retryable=false`) without dispatch, replay or overwrite of the original owner's durable response. Preserve request ID, identity/payload binding and auth/mode guards. T07 should validate this regression plus existing journal/mutation replay and bundle-import failure cases over current root source, not transplant obsolete candidate handler blocks.

Immutable artifact: `T07-journal-observation-test-r1.patch`, new test only. After handing it off, do not overwrite; later revisions need a distinct artifact filename/hash. Root release and full T07 acceptance remain OPEN.
