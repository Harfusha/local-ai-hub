# T08 unused request ID lint fix

Scope: remove only unused `_request_id = self._replay_request_id(stored_payload)` in async-job execution path. Replay behavior unchanged; `_replay_request_id` remains used by retry/recovery logic.

T06 worktree `src/local_ai_hub/async_jobs.py` did not contain this finding, so it was left untouched. Fix was prepared in a fresh temporary copy of current root source; root was not edited.

- Root-current preimage SHA-256: `77F33CA01FF72B22C2D4E3E080A28767259A02713AD6F7CFE84DA1BE5E2AD5B8`
- Expected postimage SHA-256: `44E785388753C39E03FE650288EA0CE0F0576BCCADEA00A7FF2F24E69685021F`
- Current root remained at preimage hash after verification.
- Patch: `T08-unused-request-id-root-current.patch`, SHA-256 `0EEA1290C3964ED3849FAFBBAE796B76BF6437E1E7CB46B70947BF8DE2896891`; one line removed.
- Fresh root-copy `git -c core.whitespace=cr-at-eol apply --check --whitespace=error <patch>` passed.
- Focused async-job tests: 41 passed across reliability contract, core jobs, and tasks.
- `pyflakes src/local_ai_hub/async_jobs.py`: passed. Ruff unavailable; project dev dependencies declare pyflakes.
