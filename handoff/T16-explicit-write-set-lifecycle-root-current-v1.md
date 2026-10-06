# T16 explicit write-set lease lifecycle root-current v1

Patch: `T16-explicit-write-set-lifecycle-root-current-v1.patch`
SHA-256: `EC8AFCB1BA84E9BC4D0604C633B6666C72DD2DDC4980B18D9205D55EB02F8ECE`
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Root test preimage: `tests/test_t16_explicit_write_set_lifecycle.py` absent.

Test is root-derived in isolated overlay, not copied from stale candidate source. Overlay module origin: `C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-1mha5kxb\src\local_ai_hub\work_fencing.py`; SHA-256 `4DA7E64370A1F08AED16F8C73C6DDA75C6A682F2A765839EC045FA2C356FD050`. Its SQLite helper `sqlite_support.py` SHA-256 `B181ED9DDB11D1A6A4959AD90175A6DFA03C69FD06B79CBACDCA9AB4E04E39EC`. Test SHA-256 `E65722445A82B18E83C97A5FC1E8DC266F5D030AB02623EE7037E8F535A6A3C1`.

Public lifecycle uses existing `FencingLeaseStore` SQLite database and explicit `coordination_id="team-shared"`. Three subprocesses acquire, expire/reacquire after reopen, then reload stale credentials. Checks reject out-of-scope explicit write set, stale attempt, stale file write, and stale fixture commit; successor attempt/lease tokens are monotonic. No new registry or production source edit. Fixture `commit-receipt.json` is not production T07 evidence.

Exact overlay launch: `PYTHONPATH=C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-1mha5kxb\src python -B -m pytest -q -p no:cacheprovider --tb=short C:\Users\Adam\AppData\Local\Temp\t16-explicit-write-overlay-1mha5kxb\tests\test_t16_explicit_write_set_lifecycle.py` from the overlay directory.

Receipt: `1 passed in 11.60s`. Root `git apply --check --whitespace=error`: pass. Root source was not modified or tested; T20 owns integration and root acceptance.
