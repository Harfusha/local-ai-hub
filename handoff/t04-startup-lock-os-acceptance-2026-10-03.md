# T04 startup resilience handoff

- Worktree: `C:\Users\Adam\.codex\worktrees\t04-lock-recovery\.local-ai-hub`, detached at `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Root/current `client.py` preimage SHA-256: `75B07C21735B881ED58C03BFC80B450410C3778C248D662A7C8E675549180D4F`. It still uses age-based `_live_start_lock`; root has no startup resilience test module. Root was not modified.
- Portable patch applies to root/current client bytes and contains exactly `src/local_ai_hub/client.py` plus new `tests/test_client_startup_resilience.py`.
- Lock behavior: OS lock serializes marker changes throughout active startup, so age cannot release a live startup lock. Failed startup leaves bounded PID-marker cooldown; another live client can retry after expiry. Dead owner permits immediate recovery. Success clears marker without unlinking locked file.
- Tests: candidate worktree `tests/test_client_startup_resilience.py`: 4 passed in 2.75s. Root/current overlay using patched client: 4 passed in 2.60s. `git apply --check` against root/current passed; patch stat lists only the two scoped paths. Root hash stayed unchanged.
- No commit; root integration remains for orchestrator.

Hashes:

- Root/current client postimage: `C75F4ACD6AD443CEFAE1F6A92781CA0CB1BE7F24415EB1F5380FDFD1E7CF3E81`
- Candidate worktree `src/local_ai_hub/client.py`: `37DC826B429CCB6CFD74E90E4AC12583FA2C0EEB219E035000B16E366206FA61`
- `tests/test_client_startup_resilience.py`: `829801834BFF424C43CE3C6138EB7AFACAA153BE9A791DC132EFC3DD832727A2`
- `handoff/t04-startup-resilience-root-current.patch`: `CF137C126BEBED4D591D8CDADB69249AD00C94A5E4741D16F1CA43DE63076C4B`
