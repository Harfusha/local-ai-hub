# T10 root-current symbol handoff

Date: 2026-10-01 (Europe/Prague)

## Ownership and preservation

- Root checkout `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`, remains T20-owned. T10 made no root writes.
- Root `preprocess.py` contains T13 pause/cancel work. Preserve live SHA-256 `14cdd83395263470de8468a907045c083c9da54127490ced4b81c5696716ad69`; HEAD preimage SHA-256 `cefb56b0e0ba226689b19869934401a30091a18c91170728f3f95b3f1f949d9b`.
- Keep Gemini seed and diagnostics intact. T10 overlay loaded root `project_config.py` and `services.py` by their root paths and asserted their live hashes.

## Root-current source pins and hunk anchors

| Root file | Live SHA-256 | HEAD preimage SHA-256 | Current symbol anchor |
|---|---|---|---|
| `src/local_ai_hub/preprocess.py` | `14cdd83395263470de8468a907045c083c9da54127490ced4b81c5696716ad69` | `cefb56b0e0ba226689b19869934401a30091a18c91170728f3f95b3f1f949d9b` | `cache_fingerprint` 717-748; `_step` 1859-1896; `_step_inventory` 2064-2176; `_step_code_index` 2551-2604; `_step_diagnostics` 3321-3411 |
| `src/local_ai_hub/code_index.py` | `6391647e32a21e0a20a0caa253f80eb62fe6e009158272cb08090fb1cc12a3a4` | `226a0eeb88ce4b88e851af01e3cdf8b1500159805ae7f6a710a0c43627337b76` | `files_needing_reindex` 544-561; `update_file` 563-606; `update_files_batch` 608-724 |
| `src/local_ai_hub/treesitter_parser.py` | `23c5f647ec3ba3fd545b7f8e8b5ae59b781f317287b1b539fe8e0a06345cc57f` | `8397d3d58da7baffd3b4917d331fcd54ba61688d62e2028a811ae2d11599d906` | No root `language_for_path` symbol |
| `src/local_ai_hub/project_config.py` | `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713` | `03145095fac22f7a69454069d0c41b5206ac2c78a0508cf6c924339d0fd26d5e` | Overlay import origin asserted |
| `src/local_ai_hub/services.py` | `a1ac60b4bf12cd656d8c5d277871b7ee6621e069c67af47f72793f72eecfb34f` | `7a3b9c73073d47f26e55af876b7f080565c32228a8e1aa281c442ab090777df2` | Overlay import origin and excluded search hint asserted |

## Candidate consumer hunks

Latest overlay rerun observed root `services.py` SHA-256 `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`; this supersedes the earlier live hash above.

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`.

- Candidate `preprocess.py`: `_project_config_context` 663-674, `_project_profile` 676-686, `_project_path_allowed` 689-694, `_add_project_text_extensions` 696-737, `cache_fingerprint` 795-829, `_step` 1864-1916, `_step_inventory` 2085-2212, `_step_code_index` 2587-2650, `_step_diagnostics` 3364-3454.
- Candidate `code_index.py`: `_project_config_context` 1055-1065, `_language_for_path` 1068-1071, `files_needing_reindex` 1571-1606, `update_file` 1608-1676, `update_files_batch` 1678-1893.
- Candidate `treesitter_parser.py`: `language_for_path` 146-155. Candidate source hashes and focused receipts are in `artifacts/t10-root-current-config-overlay-acceptance-20261001.md`.

These anchors map T10 consumer additions onto current root files; they do not authorize overwriting root files. T20 owns reconciliation. Apply only reviewed function hunks, preserve root-only T13 pause/cancel and Gemini changes, then rerun integration validation in T20's slot.

## No-Hub harness smoke

Ran `python -B tools/benchmark_t10_repository.py --files 100 --parser-backend fallback --cold-repeats 1 --warm-repeats 1 --graph-repeats 1 --lookup-repeats 1 --concurrency-levels 1 --concurrency-repeats 1 --max-files 100 --output <temp-json>` from candidate worktree. Exit 0; 100 files and 100 caller edges covered. Harness reports fallback parser, capped Python fallback search, and no Hub/external backend invocation. Temporary output removed. This smoke does not satisfy 100k paired benchmark acceptance.
