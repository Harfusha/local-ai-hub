# T02 Measurement Runner Packet v2 — 2026-10-04

## Scope and ownership

- Candidate: `C:\Users\Adam\.codex\worktrees\t02-quality-baseline-resume\.local-ai-hub`
- Candidate HEAD: `ad974c54e150d5f2c9bdada8179bc02457147549` (detached).
- Root: `C:\Users\Adam\.local-ai-hub`
- Root HEAD/base and merge-base: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Candidate commits after base are prior documentation/checkpoint commits: `f8024d8` benchmark checkpoint, followed by four T02 evidence commits through `ad974c5`. No new commit created for this packet.
- Owned source patch changes exactly two previously absent paths; no existing source/test hunks.

| Owned path | Base/root state | Candidate SHA-256 |
|---|---|---|
| `tools/run_t02_matrix.py` | absent | `95357BE1D1F228AECE342AB62208DA4B0F6C525B57C19B87364B9F5C44570783` |
| `tests/test_t02_matrix_runner.py` | absent | `CB71E7424D20B2A14A268193978E6E459F1B056DFE4451BC598C28FBC8E4BEEF` |

Immutable integration artifacts:

- Patch: `artifacts/t02-matrix-runner-integration-20261004-v2.patch`
- Patch SHA-256: `F5120E382DB764DC5206394009F809DAD000762EC95F9AAA0CA1EEDDD7C7CC84`
- Patch is exactly 2 new files, 599 insertions; `git apply --check` passed against current root. It was not applied.
- Manifest: `artifacts/t02-matrix-runner-manifest-20261004-v2.json`
- Manifest SHA-256: `002CAA6869836D1BFD9D1C386D1451403C8F8332378CBF9C5DEACF637B22242E`

## What runner now does

- Six file/RAG workloads × four concurrency settings (1, 4, 16, 32), with acceptance settings of 1,000 light and 30 paired repetitions.
- Keeps benchmark records, scratch, checkpoint, and manifest outside the repository.
- Forces Hugging Face/Transformers offline and disables telemetry.
- Saves exact command, exit code, record/checkpoint paths and SHA-256 in each completed case.
- Resume skips only records under the chosen evidence directory whose file digest and record contract still validate.
- After all six measured workload records exist, it emits a 24-cell aggregate with queue metrics and per-workload synthetic quality/golden evidence.
- Labels aggregate `complete_synthetic_matrix`; real-input quality remains explicitly `blocked_real_input_evidence`.

## Candidate checks and actual smoke measurement

1. `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_t02_matrix_runner.py` → **9 passed in 0.28s**. Unit/contract coverage only; does not assert that performance acceptance passed.
2. `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_benchmarks.py::test_benchmark_checkpoint_resumes_completed_stages_and_incomplete_progress` → **1 passed in 0.13s** in the candidate.
3. Smoke command (candidate, native fallback after `local_ai_command` returned `terminal=true`, `retryable=false` because the worktree was not registered as task-owned):

   `python -B tools/benchmark_surfaces.py --state-dir C:\Users\Adam\.codex\worktrees\t02-evidence-20261004\state --scratch-dir C:\Users\Adam\.codex\worktrees\t02-evidence-20261004\scratch\files-100-rag-10000 --files 100 --rag-chunks 10000 --repetitions 3 --light-repetitions 10 --paired-repetitions 3 --concurrency 1 4 16 32 --full --checkpoint C:\Users\Adam\.codex\worktrees\t02-evidence-20261004\checkpoints\files-100-rag-10000.json --checkpoint-batch-size 25`

   Result: **exit 0**, 46,770.644 ms, one workload only; record `C:\Users\Adam\.codex\worktrees\t02-evidence-20261004\state\surface-benchmark-1791131666250847500.json`, SHA-256 `F00B458DF9EBDCB839CEB93A64B8ECC64BBF7B20B111804CC38EF56D8EFFA927`. Summary receipt `artifacts/t02-smoke-100-10000-20261004-v1.json`, SHA-256 `A4C801E5B5EFFCE746B882601F67FD934796D2FC6EF4D70CED7565FBF0D5627A`.

   All measured benchmark stages passed with zero errors. Queue admission: 530 samples, p50 987.085 ms, p95 5,899.735 ms. Transport p50/p95 0.326/0.393 ms; Hub health 0.832/0.961 ms; validation 88.316/88.665 ms; SQLite index 54.410/75.679 ms; DB read 1.357/1.425 ms; code index 108.670/115.949 ms; context pack 169.476/481.326 ms. Synthetic setup 47.208 ms. `baseline_readiness=per_case`, not acceptance: only 10 light and 3 paired samples; single workload; no completed matrix; required goldens incomplete.

   The tool reports synthetic quality score 100%, but only two supported checks scored (`symbols`, `context_pack`). Graph, affected tests, retrieval relevance, code generation, vision, and speech were unavailable/not measured. This is not real-input quality evidence.

4. Root selector previously authorized once by T20: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_benchmarks.py::test_full_matrix_persists_cases_and_compares_each_size_pair` → **5 passed in 15.00s**. Root post-hashes matched. This tests root matrix persistence with fake benchmark records; it does not execute the 24-cell workload.
5. Older T20-authorized root repeat-runner selector: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_t02_repeat_pytest.py` → **3 passed in 0.15s**. Root bytes differ from candidate; not included in owned patch.
6. Earlier candidate selector typo `tests/test_surface_benchmarks.py::test_full_matrix_persists_cases_and_compares_each_size_pair` was absent from candidate test module: exit 4, no tests ran. Correct candidate checkpoint-resume selector above passed.

## Root/inherited state excluded

- Root now lacks both new matrix-runner paths; current root preflight confirmed them absent. Patch apply-check passed; no root edits or tests in this continuation.
- Root `tools/benchmark_surfaces.py` and `tests/test_surface_benchmarks.py` are modified dirty paths owned by T20 integration. Their current root SHA-256 values: `DCAED06CF711090E692D4B44555C6E76FF37F06093275B63C121D7CCE0AD3DE0` and `F4E0D299384B3B3C9443390EC1001ED6B6F38D5606C0B45D8D774DED816DCF00`. They are not in our patch.
- Repeat runner/tests and T02 docs already exist as root untracked files, but their hashes differ from candidate copies; none are in this patch. See exact per-path hashes in the JSON manifest.
- T18 used the root slot; T20 reported its 8/9 root acceptance failure and released the slot. This task did not consume another root slot.

## Remaining blockers

- No 24-cell acceptance run: all six combinations at concurrency 1/4/16/32, each with 1,000 light and 30 paired repetitions, remain unmeasured. Earlier high-sample work exceeded ten minutes and was interrupted. This packet has one low-sample smoke case only.
- No complete aggregate of actual case records exists yet. The runner code writes it only after six validated workload records.
- Real-input retrieval quality remains blocked by absent approved corpus/query labels and acceptance thresholds. The existing plan explicitly requires T20 scope approval. Synthetic checks cannot substitute.
- No paired baseline/candidate comparison, inference, GPU/VRAM, or live runtime-quality evidence.