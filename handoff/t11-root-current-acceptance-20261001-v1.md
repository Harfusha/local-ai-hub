# T11 root-current overlay handoff

Root remains read-only. Work and tests ran in isolated temp overlay.

## Root state

- Root: `C:\Users\Adam\.local-ai-hub` at `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root `rag.py` already loads `uncertain_retry_paths` in `index_step` (line 869). Root read-bounds tests already include same-metadata incremental retry (line 234). No production hunk needed.
- Root had pre-existing dirty/untracked state on inspected T11 paths; hashes below pin bytes tested. No root writes performed.

## Patch

- `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-acceptance-20261001-v1.patch`
- SHA-256: `afc9ba116de2e0486224984c37f6c0a3416e58cc0a969b5cc4b1192d9e229a9e`
- Delta: +34 lines, 0 removals, policy-consumer regression only.
- Strict `git apply --check` against actual root: exit 0.

## Root preimages and overlay hashes

| Path | Root preimage SHA-256 | Overlay SHA-256 |
|---|---|---|
| `src/local_ai_hub/rag.py` | `4c0ed5c52ec4cd9d82b41f0d6d2188812d607d1ce58c4ffea956d045fbb9048a` | `4c0ed5c52ec4cd9d82b41f0d6d2188812d607d1ce58c4ffea956d045fbb9048a` |
| `tests/test_rag_read_bounds.py` | `9d9f3ee9daad5306570d9a7c2674da1a4cf3342541a1a2b43abb1f798ec0d002` | `9d9f3ee9daad5306570d9a7c2674da1a4cf3342541a1a2b43abb1f798ec0d002` |
| `tests/test_rag_hybrid.py` | `5e8508f96b808a7369fa9e97617be359f7f23ea7a6213364eec71b99f5149160` | `5e8508f96b808a7369fa9e97617be359f7f23ea7a6213364eec71b99f5149160` |
| `tests/test_rag_fragment_cache.py` | `50be2a48a96a7edf403bc09a9eef9032c315b1b068ce6015f032636b28d46293` | `50be2a48a96a7edf403bc09a9eef9032c315b1b068ce6015f032636b28d46293` |
| `tests/test_t11_project_policy_consumers.py` | `356ca9710c313cc0eaf715d5608f7262ce4e003d9b0fc75db0c1d8184b3622db` | `d79c4748e277b5eae20be56921765709a7180eb54cd7874041a483b16d3ff6a4` |

## Validation

- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_read_bounds.py tests/test_rag_hybrid.py tests/test_rag_fragment_cache.py tests/test_t11_project_policy_consumers.py`
- CWD: `C:\Users\Adam\AppData\Local\Temp\t11-root-current-overlay-d7928301cbac435aa595dca5205221be`
- Result: `38 passed in 11.83s`; exit 0.
- Strict apply-check exit 0. No 100k benchmark, GPU, or live-model run.

Candidate f678 code remains unchanged. Prior candidate patch SHA-256: `a5f885cc87927b44e45fcced8d780417de74df7f042728e6aa5fe0c0db85d804`.
