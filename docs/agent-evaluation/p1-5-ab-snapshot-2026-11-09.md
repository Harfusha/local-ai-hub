# P1-5 snapshot-bound A/B comparison — 2026-11-09

Two fresh clones of fixture commit `fcf33b90798bdc54a1fe9d8b424e9e2de4a76e23` ran sequentially with Codex `gpt-6.1-sol`, the same prompt and `python -m pytest -q`. The prompt explicitly authorized native access within each disposable fixture. The Hub arm additionally received an instruction to use `local_ai_repo` and an isolated MCP configuration. One synthetic task cannot establish a general performance or quality claim.

| Measurement | Native | Hub | Hub minus native |
| --- | ---: | ---: | ---: |
| Input tokens | 193,686 | 216,775 | +23,089 |
| Cached input, included above | 169,472 | 183,296 | +13,824 |
| Output tokens | 1,225 | 1,246 | +21 |
| Completed command calls | 5 | 6 | +1 |
| Completed MCP calls | 0 | 2 | +2 |
| MCP response envelopes, estimated tokens | 0 | 4,333 | +4,333 |
| Process elapsed time, monotonic stopwatch | 68,250 ms | 79,625 ms | +11,375 ms |
| Agent and independent pytest results | 22 passed | 23 passed | — |

The Hub `context` and `git_diff` responses reported 1,796 and 2,537 estimated envelope tokens. Their estimates overlap the reported model input usage and must not be added to it. No identical MCP request was repeated. A reproducible reanalysis used the verified `o200k_base` merge table (SHA-256 `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`). Exact identical complete command/MCP text-result bodies repeated zero times in either arm. Exact repeated nonblank complete lines across prior result bodies numbered six per arm and tokenized to 6 tokens per arm. A separate greedy `SequenceMatcher` scan of cross-response blocks of at least eight lexemes found 21 matched lexemes in Native and 115 in Hub; the selected raw substrings joined with newlines tokenize to 21 and 118 tokens respectively. A normalized lexical-token rendering of the MCP-only block matched 148 lexemes and tokenized to 189 tokens. These are distinct heuristic views and are not additive. Partial-match scans may capture coincidental text; all counts omit within-result repetitions, non-text MCP content and wire envelopes, and do not equal billed-token accounting. The event hashes remain `808789d4d2743814a532931347d60b5d7a73aab043fc171badcb522164d325f9` (Native) and `094df3c1af1e7b97f2d07ab783dec6cc49a71a6e0981c82e37117543401504a9` (Hub).

Both agents produced integer half-up arithmetic and input validation, with different error messages and regression suites. Both had one unsuccessful pytest attempt before the final passing attempt. Independent reruns passed as shown. These results do not prove equivalent coverage for all inputs. Both event streams recorded the same hook configuration parsing error before task execution.

The Hub loaded the copied runtime through `PYTHONPATH` from `runtime-snapshot-y3lwhqaq`, with content manifest SHA-256 `ff372135c7d73884878d0f66b68768ca79ad920bbda45f64a3e97a5d486e0f82`. All 306 manifest files matched their sizes and SHA-256 values before and after the pair. During copying, parent directories and file handles were pinned on Windows and reparse points rejected. The snapshot covers only the recorded Git-visible runtime scope; it does not establish that every possible runtime input was included. The original environment record lists Python, selected executable/config hashes and 155 package versions but did not hash package contents during the pair. Later post-run and pre-retest captures each hashed all 46,114 installed-distribution RECORD files (6,250,302,730 bytes) to the same entries digest `cd90c4e1476c5a64fa3e5589ecc36e09b90102192efb920229a06812c858e820`; the newer capture is `C:/Users/Adam/Documents/Codex/local-ai-hub-audit/2026-11-09/p1-5-git-pair-zgwgw3ge/venv-record-content-20261109-1705.json`. These later matching snapshots do not prove package contents at the historical A/B execution times, unrecorded venv files, Python standard library, drivers, or external service versions. A complete run-bound environment fingerprint is still unavailable.

The Hub ran on isolated loopback port `59006`, with a separate state directory, no Hub API token and Ollama management disabled. Its owned Hub and supervisor processes were stopped after the pair. A prior trial at `bound-pair-mmdcx2ka` is excluded: its native agent declined access when Hub was absent and did not run tests, despite process exit code 0.

Raw events, timing files, stderr, fixture trees, config and state are retained under `C:/Users/Adam/Documents/Codex/local-ai-hub-audit/2026-11-09/p1-5-git-pair-zgwgw3ge/bound-pair-authorized-o2drhg6z/`. Native thread: `01a1c08c-b33d-7b20-9d18-073e52450959`; Hub thread: `01a1c08e-08ec-7a32-975a-1ab9e62c5bd4`. The isolated config SHA-256 is `e0684f19fd0326774c42cedfc3095ce471cd729f952078a7a2844f0fde610446`.
