# T10 Python fallback-budget handoff — 2026-10-02

Root T20 HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Candidate HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Root untouched.

## Root-current comparison

Root already has T10 fallback-budget behavior: `python_fallback_max_files` cap, `python_fallback_files_scanned` and `python_fallback_file_limit` result metrics, independent `ripgrep_timeout_seconds`, matching defaults, matching focused test content. Exact base and current SHA-256 values are in [JSON receipt](t10-python-fallback-budget-root-current-20261002.json).

Root-current patch for clean T20 HEAD: [fallback-budget source/defaults/test patch](t10-fallback-budget-root-current-20261002.patch). SHA-256 `E5478A26A2B0B3BCA48116A459CB1397130D8EE938E9E27DABB7FA00466B8B94`. `git apply --check --whitespace=error` passed in temporary overlay built from root HEAD; patch then applied in overlay. Live root already has these changes; do not apply patch there. Candidate `repo_tools.py` SHA differs because root has later T20/T21 hunks. Do not apply candidate file or broad cherry-pick. Root focused test copy is untracked; preserve it.

## Validation

Candidate only: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_python_fallback_budget.py` — **1 passed in 0.11s**. No root tests run.

Performance acceptance stays **RED**. Paired 100k benchmark remains T02-owned; no benchmark run. Await T02/T15 exact validated command and slot.
