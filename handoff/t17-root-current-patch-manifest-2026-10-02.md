# T17 root-current patch manifest — 2026-10-02

## Workspaces and ownership

- Candidate: `C:\Users\Adam\.codex\worktrees\t17-multimodal-resume\.local-ai-hub`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`.
- T20 root inspected read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Existing dirty files preserved. Current root test file SHA is `D37CA57154D5323AD8BD55CC9DC23D2FB5C205E392FD2ED1D72F66D65CDBDAB5`.
- No production source changes needed in this checkpoint. `/api/context/pack` untouched. No patch applied to root.

## Transfer patch status against current dirty root

| Patch | SHA-256 | Current check | Scope |
|---|---|---|---|
| `t17-browser-active-tab-root-current-v5.patch` | `A5D82B2CE80FD0DB5015ABF45B2FE06992243D0E3C1077F893CBA333E5819AD6` | `git apply --reverse --check`: PASS; hunks already present | Browser background permission guard and owned browser fixture/tests |
| `t17-vision-bbox-root-current.patch` | `4E9274E0BFA1D464F82F091A1C4AA0A5A8967AAF02C0A94390FF8CCD402EC42C` | `git apply --reverse --check`: PASS; hunks already present | Vision bbox prompt convention and assertions |
| `t17-transcribe-stderr-root-current.patch` | `B976A325E5B77D42740AD0CF65CACE7E43F06CE8B0D183224A13CF67F685F2CB` | `git apply --reverse --check`: PASS; hunks already present | Whisper decode-skip stderr guard and regression test |
| `t17-transcribe-route-fixture-root-current-v1.patch` | `431656D385BE76E22E523DA37126ED1DF23A1C8366474F4EB5713BAFE9A08966` | `git apply --reverse --check`: PASS; hunk already present | One test-only fake signature change to accept handler `cancel_event=` keyword |

All four listed patch hunks are now present in current root; no patch should be applied again. Before T20 integration, route-fixture root preimage SHA-256 was `568616AC241D6B9E1C4F797542A9FFEF63384CB3FB6C56B9A27A3DEADC71E492`; candidate postimage SHA-256 is `FA73A2967BDC8088BD03E81943B8909EA5A095F97822EA29B8980E1BB34D263D`; current root test file SHA-256 is `D37CA57154D5323AD8BD55CC9DC23D2FB5C205E392FD2ED1D72F66D65CDBDAB5`. Root differs from candidate because it retains separate dirty test content; the scoped patch hunk is present. Keep patch v1 as historical transfer evidence only.

## Candidate verification and acceptance boundary

- Focused candidate command recorded in `t17-browser-vision-ownership-review.md`: **21 passed in 13.57 s** across browser expiry/replay/HTTP lifecycle, vision payload/cancellation/bounds, and transcription payload/unavailable/decode-skip/route behavior. Candidate `git diff --check`: **PASS** (line-ending warnings only).
- Existing candidate contract suite: **257 passed / 47.71 s**, predates one-line fixture compatibility edit; do not label it post-edit full-suite proof. Unique route selector after that edit: **1 passed / 4.54 s**. Root-source overlay after same fixture patch: **1 passed / 4.12 s**. Root-current browser overlay: **3 passed / 24.58 s**, registered-handler Edge harness **PASS**.
- Source/contracts only: actual interactive toolbar `activeTab` gesture, persistent live-daemon expiry/replay, natural multilingual Whisper WER, and live vision-model quality remain **NOT VERIFIED**. Hub skipped as unavailable. `/api/context/pack` excluded.
- Fresh restart acceptance receipt in the ownership review: 32 passed in 15.10 s across browser permission/provenance/replay/expiry, HTTP stage-commit, vision input/cancel/grounding/unavailable states, and transcription input/cancel/missing-CLI/decode-skip/HTTP route. The exact command is preserved there; source was unchanged.
- Bounded restart resource check: no audio corpus file found in the candidate repository using the `rg --files` media-extension query recorded in the ownership review. Only exposed screen-context tool is voice-chat-only; no interactive toolbar control available. No inference or benchmark performed.

## Additional root-current test-only proposal (2026-10-02)

- Candidate-only `tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output` covers event cancellation during `communicate()`, process-tree termination, and final stdout/stderr drain. Root's same file has a differently named `test_run_hidden_cancellation_terminates_process_tree` for `KeyboardInterrupt`; it does not cover the event-cancellation/drain path.
- Prepared patch: `handoff/t17-process-cancellation-drain-test-root-current-v1.patch`, SHA-256 `70F70A58FC57CCD319BF2FFD8ADC58D031CAB6D3A5F23EBB1692CD798B90C55B`; test-only, adds one import and one isolated test. Exact current root preimage `tests/test_process_utils.py` SHA-256 `F4ABB170C15FB9E687A20EE020467FAABBC867EF406EA9AB6DE80476693AD534`; candidate test-file SHA-256 `4062CB40DD1D76B4D574EF0FF9A16EC9E07D6FDDF512D9655F9E216ED83AF72C`. LF-normalized proposed postimage SHA-256 `4A22549D9031C648EFE994B47EDCEB7376D19D062A891EDCDC694CC66C06BD95`.
- Current-root `git apply --check`: PASS. Patch not applied; root remains T20-owned. Do not run its selector until T02 releases slot. Prepared command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_process_utils.py::test_run_hidden_cancellation_terminates_tree_and_drains_output`.
