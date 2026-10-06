# T21 root-current search policy acceptance r3

## Review finding closed

- r2's installed-ripgrep path used unsupported `--files-from -`; Windows ripgrep 15.2.0 reports `rg: unrecognized flag --files-from`. Earlier tests had passed through bounded Python fallback and did not assert the engine.
- r3 passes only the bounded policy-approved relative file list as explicit ripgrep path arguments, in batches of at most 192 files and at most 20,000 estimated command characters. All batches share the existing single ripgrep timeout budget. No whole-root traversal is delegated to ripgrep for project-aware search.
- Force-glob expansion now includes the zero-directory transition for `**`; ignore admission uses project_config's exact safe path glob matcher.

## Pinned root preimages

- `repo_tools.py`: `d6eae9a69059353b1d182a3d1a2d3af8cf61aa623ac8817b97a121ab9385d07d`.
- `services.py`: `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`.
- Unchanged `project_config.py`: `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`.
- Main-owned T21 test unchanged, SHA-256 `2d95eceb2b4f3c283af5006633ead8378669bf033bd0781312a50bf3e5de7c1b`.
- Patched overlay SHA-256: `repo_tools.py` `8da38ecbe3daa4c975ec8f14fedbc74d91d04ceeaf4cbb2c7155a3e554b6da65`; `services.py` `a06ae015085e4b4dc61bf09a99570332044d65d623b7521218e569c329554235`.

## Exact validation

- Command: `python -B handoff/run_t21_search_overlay_acceptance.py`.
- Result: exit 0; actual main-owned T21 selector **5 passed in 1.41s**. Runner asserts all three `__file__` imports resolve inside a temporary compatible overlay, verifies root preimages, applies this patch, and checks exact patched hashes.
- Installed ripgrep regression: engine asserted `ripgrep`; two explicit argv batches executed; the hit in `src/zz_batch_192.py` (second batch) was returned. Custom `.shader` and the gitignored zero-segment `node_modules/direct.shader` were found without request hints.
- Broad permitted paths: `node_modules/@my-org/button.dep`, `node_modules/direct.shader`, `src/button.shader`, `src/visible.py`, `src/zz_batch_192.py`.
- Targeted hints returned the three permitted custom/forced files. Exclude, configured binary, oversize, and outside-root candidates were denied.

## Patch

- Immutable patch: `handoff/t21-root-current-search-policy-v20261001-r3.patch`.
- Patch SHA-256: `2873b765178e686f0af27f82adc099a2f98b4c2fc273ec5babd58928f4bbb842`.
- r2 remains unchanged and is superseded. Root integration/review remains with T20; no root write or main-owned test edit occurred.
