# Exact Repository Search Performance Plan

**Goal:** Keep exact repository search responsive on Windows installations with large ignored/generated directories.

**Architecture:** Restrict the ripgrep prefilter to directories that the repository search policy already ignores. Use its matching-path set to skip expensive validation and file reads for nonmatching files, while still processing explicitly force-included paths and retaining exact counts.

**Tech Stack:** Python 3.11+, ripgrep, pytest.

## Constraints

- Preserve exact match totals and pagination.
- Preserve project path policy, symlink confinement, and explicit force-include behavior.
- No dependency changes or commits.

## Steps

- [ ] Inspect exact-search candidate enumeration and existing focused tests.
- [ ] Update candidate filtering without weakening exactness or path checks.
- [ ] Run focused exact-search tests, then release check and installed doctor.
- [ ] Review active generated prompt/skill files for unsupported `local_ai_command` references.
