# T16 explicit write-set lease lifecycle root-current v2

Patch: `T16-explicit-write-set-lifecycle-root-current-v2.patch`
SHA-256: `5450DD3899805107F20721D7BB4FC600E9F58582B604847364BC719C1912AF83`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root test preimage: `tests/test_t16_explicit_write_set_lifecycle.py` absent.

Test is root-derived in isolated overlay. Overlay imports root `work_fencing.py`, origin `C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-v2-mwffpht_\src\local_ai_hub\work_fencing.py`, SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`. SQLite helper `sqlite_support.py` SHA-256 `B181ED9DDB11D1A6A4959AD90175A6DFA03C69FD06B79CBACDCA9AB4E04E39EC`. Candidate test SHA-256 `CA9021A1FC1B3619CC7FCE59A08C321354EDD39F576B7D991FF312D3C54B3A7A`.

Three spawned process lifetimes share existing SQLite store. Old holder claims under `team-shared` with 5-second attempt and path TTL. At deterministic time 106, successor reopens DB and reacquires expired scope, then commits guarded file and fixture receipt. Independent `team-isolated` namespace concurrently claims same path. Test rejects explicit out-of-scope write set; stale process reopens DB and fails attempt and commit guards. It verifies both fencing tokens are monotonic and prior file/receipt remain unchanged.

Exact tested command: `python -B -m pytest -q -p no:cacheprovider --tb=short C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-v2-mwffpht_\tests\test_t16_explicit_write_set_lifecycle.py` from `C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-v2-mwffpht_`; `PYTHONPATH` was `C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-v2-mwffpht_\src`.

Receipt: `1 passed in 0.46s`. The first harness attempt failed because it incorrectly parsed empty stdout from the old-holder setup process; runner was corrected and final isolated receipt passed. This was harness failure, not a product RED. Root `git apply --check --whitespace=error`: pass. Root source was not modified or tested. T20 retains integration and root acceptance.

`commit-receipt.json` is a test fixture, not proof of production T07 journal integration. Windows symlink `WinError 1314` is not covered by this selector and remains a platform gap.
