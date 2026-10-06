# T10 defaults parity handoff — 2026-10-02

T10 owns `python_fallback_max_files`: T10's root-current receipt lists its independent Python fallback count cap/default as in-scope and explicitly separates it from ripgrep timeout.

`tools/release_check.py:154` compares root `defaults.toml` and packaged `src/local_ai_hub/defaults.toml` byte-for-byte. Current root diff has exactly one insertion: `python_fallback_max_files = 8000 # independent file-count budget; ripgrep has its own timeout`.

- Root `defaults.toml` preimage SHA-256: `D688F8546F616B872B2111C1F137C06964035E75C6DA8B2A2DD2F420400A039E
- Packaged defaults/postimage SHA-256: `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B
- One-line patch SHA-256: `4731B4DE2E68093018B136A96266FF656C569F3520386DD5D3899EB9FCD02665
- Patch target: root `defaults.toml` only. No root or packaged-source write performed.
- Root `git apply --check --whitespace=error` passed; stat is one insertion in `defaults.toml`. Root preimage SHA stayed unchanged after check. Adding the line makes root bytes equal packaged defaults. Release selector was inspected but not run; root was not edited.


## T20 root selector receipt

T20 applied the one-line patch. After integration, root and packaged defaults both hash to `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`. Process check found zero active pytest processes. Exact selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_release_hardening.py::test_release_gate_allows_the_live_installed_checkout` — **1 passed in 7.09s**. Root HEAD stayed `01df56605ccf484ebfe2808ac60d696c4e81dffc`; `build/` and `dist/` showed no Git status entries. `tests/test_release_hardening.py` appeared modified in root status and was preserved; this task did not edit it.


## Candidate parity continuation

In the assigned candidate worktree, applied the same one-line T10 setting to top-level `defaults.toml`. The pre-existing packaged defaults file had identical normalized text but LF endings on only lines 470–472. Converted only those three endings to CRLF; line text did not change. Candidate top-level and packaged defaults now have identical bytes and SHA-256 `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`. Candidate-only selector `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_python_fallback_budget.py::test_python_search_fallback_has_its_own_file_budget` passed **1 in 0.11s**. Candidate `git diff --check` passed; diff shows one added line per defaults file. All 16 inherited dirty paths remain; candidate count is 17 after adding top-level `defaults.toml`. Root was not touched or tested in this continuation.
