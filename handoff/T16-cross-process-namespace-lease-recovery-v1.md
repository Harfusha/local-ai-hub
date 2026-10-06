# T16 cross-process namespace lease recovery acceptance v1

Patch: `T16-cross-process-namespace-lease-recovery-v1.patch`
Patch SHA-256: `69810ABC453800234A80464F44948DAC7D9E48EB5EA82ED53874D775358C6E70`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root preimage: `tests/test_t16_cross_process_namespace_lease_recovery.py` absent.
Candidate test SHA-256: `4E727AB7D2FF32A943912CE414A08015E6F719293440BD224C8165CF72310C1F`

Depends on namespace consumer v2. Separate child processes derive `coordination_id` from `resolve_project_context`; test supplies no client-selected identity. Real SQLite lease/fence stores cover A/B conflict, independent C isolation, persisted expiry/reclaim, monotonic attempt/fence tokens, stale write plus commit-receipt rejection, wrong-owner renew/release. `commit-receipt.json` is a test fixture; no production T07 journal code changed.

Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t16_cross_process_namespace_lease_recovery.py`
Result: `1 passed in 9.76s`, exit 0.
Full candidate batch receipt is in namespace v2 manifest. `git apply --check --whitespace=error`: exit 0. No root writes.
