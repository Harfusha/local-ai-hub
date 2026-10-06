# T10 root acceptance handoff — 2026-10-02

## Scope and decision

Candidate **30/30** does not establish root acceptance. This is a read-only, hash-bound handoff for T20. T10 made **no root writes** and ran **no tests** while other serial work was active.

No new source patch is issued: root already contains the T10 behavior alongside owner-specific changes. Several existing root-current patches were generated against older hashes and are stale. Do not apply candidate source wholesale; it would overwrite root changes in `code_index.py`, `repo_tools.py`, `preprocess.py`, and `retrieval.py`.

## Root snapshot

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Exact source hashes, ten root test-module hashes, test function counts, and scoped dirty statuses are in the JSON manifest. Defaults are byte-identical across root and candidate (`418B6299…A502D57B`). Root's path-hint test has an extra positive default-scope test: **5 test functions**, vs candidate **4**. Other T10 test files are newline-normalized equal to candidate, but their raw hashes differ.

Root source hashes differ from candidate: `code_index.py` includes the scoped analyzer-version key, `repo_tools.py` and `preprocess.py` include owner changes, and root `retrieval.py` is modified. Exact root bytes, not candidate receipts, must be validated.

## T10 acceptance matrix

The project plan's T10 gates remain: adaptive-retrieval ownership; scan/parse/SQL/graph freshness and incremental invalidation; backend/deadline/fallback/coverage/evidence contracts; language/framework fixtures; built-in/Serena/CodeGraph on/off/crash/timeout plus latency/coverage; and CodeGraph standalone/clean-host release checks. Root test/source receipts are pinned but **not executed in this handoff**.

T02's latest diagnostics have no valid paired 100k receipt: outputs `-02` and `-03` each contain 128 files; `-03` timing was contaminated. No clean p95 or separate memory receipt exists. T19/T20 clean-host and integrated release gates remain open.

## T20 root validation command

Run only after an exclusive serial slot is available and after rehashing all manifest paths. Assert package import resolves to root `src/local_ai_hub`; then run the exact command in `root_command_for_T20_after_serial_slot` in the JSON manifest. This handoff did not run it.


## Current serial-slot gate — 2026-10-02

T02 owns the sole test/benchmark slot. Its first baseline matrix is still running (about five minutes elapsed; 3600-second timeout; CPU time growing). T10 launched no tests or benchmark. Wait for T02's explicit release, then rehash all 16 root paths and verify root import before T20 runs the prepared root selector.


## Read-only source recheck — 2026-10-02

AST parse passed for 14 pinned root Python source/test paths; both root defaults TOML files parsed and are byte-identical. No imports or tests ran. Root HEAD still matches the handoff snapshot, with 16 pinned path hashes and 0 drift at recheck. T02 holds the exclusive benchmark/test slot; T10 did not start tests.


## Additional static contract review

Root source markers confirm: schema column/guard in `code_index.py`; forced snapshot reindex; `repo_tools.py` exposes a separate `python_fallback_max_files` cap and `python_fallback_files_scanned` metric; preprocess invalidates snapshots on change evidence; packaged/top-level defaults share the independent fallback default. No T10 source patch is indicated by this review. Root runtime acceptance still needs the prepared exclusive selector run and owner performance/release receipts.


Latest slot check: T02 baseline matrix remains active after about 19 minutes without phase change; CPU grows and the owner keeps its one-hour timeout. No explicit release was reported. T10 continues to hold tests.


Current coordination: T02 says -04 ended incomplete and -05 is a proposal awaiting T20 approval. T11 requests slot 11. T20 idle is not a T10 slot grant. T10 has requested T02 guidance on the missing impact stage; no new T10 tests/benchmark ran.


T20 slot queue: T11 11, T05 12, T03 13, T08 at/after 14, T10 after that pending prioritization. T02 owns planned `hub_impact_latency`; T10 does not modify its harness. No T10 slot granted.


Resume recheck: root HEAD and 16 pinned path hashes are unchanged. Current T20 queue: T11 11 (awaiting broker/fresh pins), T05 next pending, T03 13, T08 14+, T10 after queue/prioritization. No T10 tests/benchmark run.


Slot update: T11 reports an off-route native pass and incomplete/UNKNOWN stopped suite; T20 requests receipt and immediate release. T10 slot not granted.
