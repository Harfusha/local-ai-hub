# T10 Windows snapshot cache patch

- Audited root HEAD: $rootHead
- Patch SHA-256: $cacheSha
- Apply check against audited root: PASS (git apply --check --whitespace=error; prior audit receipt)
- Paths: src/local_ai_hub/repo_tools.py; 	ests/test_t10_snapshot_cache_revalidation.py
- Change: Windows snapshot cache revalidation for same-stat restored-mtime rewrites; adds decoded/hash-only regression cases.
- T21 overlap: epo_tools.py shared; cache hunk does not touch path-hint methods.
- Test command: python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_snapshot_cache_revalidation.py
- Test status: NOT RUN; shared T20 test slot reserved.
- Root write: none. Patch remains unapplied.

## T20 integration refresh (2026-10-01)

T20 reports the root Windows snapshot-cache selectors green: 2 passed. Root now contains the new regression test and an adapted cache implementation. Original candidate patch SHA remains `687979D38B18438C8DA18C0572ED091407D6A291DB36AFC33A31059E58655BBE`, but it no longer reverse- or forward-checks against integrated root `repo_tools.py`; do not apply. T10 did not run root tests or write root.
