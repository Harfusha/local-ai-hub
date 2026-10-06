# T10 consumers against live root project config

Date: 2026-10-01. Candidate worktree remains `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub` at `7a36be3b8b69531dccd9215515ac793369da0a44`. No root files were written.

## Source pins

- Live root modules imported by the overlay: `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\project_config.py` and `services.py`.
- Root checkout HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; both imported root modules were dirty at test time. `project_config.py` HEAD preimage/live SHA-256: `03145095fac22f7a69454069d0c41b5206ac2c78a0508cf6c924339d0fd26d5e` / `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`. `services.py` HEAD preimage/live SHA-256: `7a3b9c73073d47f26e55af876b7f080565c32228a8e1aa281c442ab090777df2` / `a1ac60b4bf12cd656d8c5d277871b7ee6621e069c67af47f72793f72eecfb34f`.
- Candidate package tree SHA-256: latest `73573288ff18c002acafa7c357469836eb14acea55128f99b133fbf041f942db`.
- Candidate-scoped benchmark patch SHA-256: latest `631ad7224ebd55f7adac5636f26c5d65385f140d87bf4434c101a59c65cd6a0b` (356709 bytes). Consumer-source patch SHA-256, framed as `T10-PROJECT-CONFIG-CONSUMERS-PATCH-V1` over candidate diffs plus consumer regression file: latest `408693941819cdb5f3f061c347ba284df690a78ac92bee325d44397e98e706f2` (135885 bytes).
- Candidate preimage/current source SHA-256:

| File | HEAD preimage | Candidate worktree |
|---|---|---|
| `src/local_ai_hub/preprocess.py` | `612447e234049ebe395efa8d4415efbdb52daacbe6a22e0367b8944019ba5283` | `11b6aa346ef254736e894c0abc10f911355e48dd04604af65081e46b1e937e17` |
| `src/local_ai_hub/code_index.py` | `eb917da8f118d828cd11ab8cdf59a98090d60d3c7bc13615f8208dc443c16a1d` | `58083fba1d64e706ac14490f04754c0e2fc765c846678dfce3005a5c5325124f` |
| `src/local_ai_hub/treesitter_parser.py` | `f3c9061e9392d056b0b2508c73d99d0f70d1583b9a46e91514feb5d28c8610a9` | `11a7749a8b6855bba0ced07d077ca02504d1d9d2a8bd4af5d5f13fc7a8de3382` |
| `tests/test_t10_project_config_consumers.py` | absent at HEAD | `daaaf7ca36ff1c7ec1d289d9d44f6e6eca72470d26c85ecc689714f8c319518f` |

## Root API hunks used

Root-current symbol anchors in `src/local_ai_hub/project_config.py`:

- `ProjectSettings`: lines 87-135; consumer fields include preprocess excludes, text/binary extensions, maximum size, skipped phases, project type, solution path, and language overrides.
- `custom_extension_kind`: lines 459-480; recognizes configured text extensions by language.
- `resolve_project_context(root, state_dir)`: lines 855-872; resolves root config and creates context.
- `phase_is_allowed(settings, phase)`: lines 991-993.
- `path_is_allowed(root, path, settings, *, phase, ..., size_bytes=None)`: lines 1004-1050.
- `may_descend(root, directory, settings, *, phase, ...)`: lines 1161-1195.
- `LocalAIServices.repo_search`: root `services.py` line 2762; request hints are validated, then `path_is_allowed(..., phase="search")` gates hinted and returned paths before ranking.

Root-current signatures and policy entry points used by T10 consumers:

```python
def resolve_project_context(
    root: str | os.PathLike[str], state_dir: str | os.PathLike[str]
) -> ProjectContext:

def phase_is_allowed(settings: ProjectSettings, phase: str) -> bool:
    return isinstance(phase, str) and phase in _PHASES and phase not in settings.skip_phases

def path_is_allowed(
    root: str | os.PathLike[str],
    path: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    phase: str,
    soft_ignored: bool = False,
    hard_denied: bool = False,
    binary: bool = False,
    size_bytes: int | None = None,
) -> bool:

def may_descend(
    root: str | os.PathLike[str],
    directory: str | os.PathLike[str],
    settings: ProjectSettings,
    *,
    phase: str,
    soft_ignored: bool = False,
    hard_denied: bool = False,
) -> bool:
```

Candidate consumer anchors:

- `preprocess.py`: `_project_config_context` 663, `_project_profile` 676, `_project_path_allowed` 689, `_add_project_text_extensions` 696, `cache_fingerprint` 838, `_step` 1907, `_step_inventory` 2128, `_step_code_index` 2630, `_step_diagnostics` 3407.
- `code_index.py`: `_project_config_context` 1055, `_language_for_path` 1068; phase/path checks in `files_needing_reindex`, `update_file`, and `update_files_batch`.
- `treesitter_parser.py`: `language_for_path` 146.

The overlay copied candidate `src/local_ai_hub` to a temporary directory, then appended the root package directory to the candidate package search path. It asserted both candidate package origin and exact root `project_config.py` import origin before running consumers. Thus the tested resolver was the live root file above, not a stub or copy.

## Exact command and result

Run from the candidate worktree in PowerShell:

```powershell
$env:PYTHONPATH='src'
$env:T10_ROOT_REPOSITORY='C:\Users\Adam\.local-ai-hub'
python -B -m pytest -q -s -p no:cacheprovider --tb=short tests/test_t10_project_config_consumers.py tests/test_t10_benchmark.py::test_candidate_patch_fingerprint_includes_staged_changes tests/test_preprocessor_and_deterministic.py::test_code_index_phase_removes_deleted_files_instead_of_spinning tests/test_preprocessor_and_deterministic.py::test_code_index_phase_skips_ignored_refs_left_by_previous_inventory tests/test_t10_acceptance.py::test_preprocessor_queues_unchanged_files_after_analyzer_version_change tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges tests/test_performance.py::test_python_search_fallback_metric_is_separate_from_ripgrep_timeout tests/test_performance.py::test_ripgrep_timeout_cools_down_repo_and_keeps_search_bounded
```

Result: exit 0, **20 passed, 2 skipped in 12.53s**. Java and C++ Tree-sitter parser cases skipped because those parsers were unavailable; no parser-quality pass is claimed.

Overlay receipt:

```json
{"cache_digest_changed":true,"diagnostic_baseline":["fixture-command",0],"excluded_hint_denied":true,"excluded_hint_prioritized":true,"excluded_paths":["private/secret.py","shared/hidden.py"],"import_origin":"C:\\Users\\Adam\\.local-ai-hub\\src\\local_ai_hub\\project_config.py","indexed_custom_language":"python","path_hint_config_miss":true,"path_hint_revision_hit":true,"path_hint_revision_miss":true,"repository_search_hint_blocked":true,"root_module_sha256":"4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713","root_services_origin":"C:\\Users\\Adam\\.local-ai-hub\\src\\local_ai_hub\\services.py","root_services_sha256":"a1ac60b4bf12cd656d8c5d277871b7ee6621e069c67af47f72793f72eecfb34f","seeded_file_refs":3,"sources":["defaults","primary_project","project","worktree"]}
```

The test created an isolated real Git linked worktree, loaded primary-project plus linked-worktree configuration, proved a ranked excluded path hint is rejected by the root repository-search service, proved excludes held after cache seeding, indexed `.pyx` as Python, checked repository-revision and config-digest hint invalidation, confirmed config digest invalidated the preprocess fingerprint without changing generation/phase, advanced a skipped call-graph phase, and executed the diagnostics phase into its baseline table. The 100k benchmark remains unrun and requires its separately coordinated CPU slot.

## Latest consumer overlay rerun

The later scoped run passed **5 tests in 6.16s**. Root Services SHA-256 at execution was `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`. Added assertions prove an allowed current hint is targeted, stale revision/config hints are not targeted, custom `.pyx` watcher admission, stale excluded-ref deletion, config-file full-inventory fallback, and parent/linked Gemini diagnostic-seed preservation. Candidate `CodeIndex` and `ProjectPreprocessor` still run from the overlay; root integration is not proven.

Latest candidate pins after that patch: package tree `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6`; candidate-scoped patch `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc`; consumer-source patch `8e22bf549192e6164a13803e5917e4fb9c40403bb206288095462f451adb42f9`; consumer test SHA-256 `c96f0d74004fb4bf2ac36cc324100c78140977cc19b852ab690e0ae9bbbd703d`.

Final pins after full-inventory fallback test: package tree `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6`; candidate-scoped patch `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc`; consumer-source patch `8e22bf549192e6164a13803e5917e4fb9c40403bb206288095462f451adb42f9`; test SHA-256 `c96f0d74004fb4bf2ac36cc324100c78140977cc19b852ab690e0ae9bbbd703d`.

```json
{"allowed_hint_applied":true,"cache_digest_changed":true,"custom_extension_watcher_relevant":true,"diagnostic_baseline":["fixture-command",0],"excluded_hint_denied":true,"excluded_hint_prioritized":true,"excluded_paths":["private/secret.py","shared/hidden.py"],"incremental_excluded_ref_removed":true,"indexed_custom_language":"python","linked_seed_preserved":true,"parent_gemini_seed_preserved":true,"path_hint_config_miss":true,"path_hint_revision_hit":true,"path_hint_revision_miss":true,"repository_search_hint_blocked":true,"root_module_sha256":"4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713","root_services_sha256":"1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1","seeded_file_refs":3,"sources":["defaults","primary_project","project","worktree"],"stale_config_hint_rejected":true,"stale_revision_hint_rejected":true}
```

The final pinned suite also asserted `config_change_full_inventory_used=true`; combined command result: **21 passed, 2 skipped in 7.53s**.
