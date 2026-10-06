# T13 operational-mode resume reconciliation

Owned checkout: t13-operational-mode-resume-20261004/.local-ai-hub.
Original unfinished HEAD b0ade36a is retained by
refs/checkpoints/t13-opmode-resume-sync-original-20261006; pinned master a83e2770.
No stash, deletion of original work, new feature task, or root edit.

## Manual decisions

The historical operational_mode.py was a competing protocol: numeric timestamps,
no revision, no cross-process writer lock/replacement retry, degraded-state reads
allowed, and maintenance deterministic reads allowed. Current master has the
newer locked/revisioned state and stricter degraded/maintenance policy. Preserve
that current production implementation, without adding deprecated API shims.
The original 105-line source and 155-line test file are committed verbatim in
docs/integration/archive/t13-opmode-resume-*.txt for traceable future adoption;
the checkpoint also retains their executable original versions. They are not
discarded and their incompatible expectations are not claimed passing.

Restore historical early inference, preprocessing mutation and background-model
admission checks using the current operational_mode_gate_error protocol. Keep
current scheduler-time mode recheck and preprocessing pause/background checks.
Retain historical tiered managed-model unload and verification tests, current
no-autostart external-model behavior, and both sets of runtime fixture fields.

## Verification

python -B -m pytest -q -p no:cacheprovider tests/test_operational_mode.py
tests/test_tiered_ollama_runtime.py --tb=short --maxfail=4:
33 passed in 5.54 seconds.

After porting the remaining historical preprocess import and adding six
adoption checks: python -B -m pytest -q -p no:cacheprovider
tests/test_sync_opmode_resume.py tests/test_operational_mode.py
tests/test_tiered_ollama_runtime.py --tb=short --maxfail=4:
39 passed in 8.70 seconds. git diff --check passed.

## Unfinished acceptance

No live GPU unloading or concurrent inference proof. Historical tiered unload
only targets its smart backend and exact Hub-owned names, not every backend or
tag alias. Its unload_model call has no explicit remaining deadline parameter;
end-to-end duration is not proven by fake-runtime tests. Preserve this work but
do not claim complete gaming VRAM release or whole release acceptance.
Historical archived test contracts remain available; no old numeric-state
format migration or compatibility shim was added.
