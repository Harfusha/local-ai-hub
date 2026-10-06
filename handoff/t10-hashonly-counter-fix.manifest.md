# T10 hash-only revalidation counter diagnosis

- Root: $root; HEAD 98a9a1a7611af574caf20a88620c4aa3eb2e918a.
- Failure cause: _hash_file_only read bytes and detected new digest, but incremented snapshot_verified_rehashes only when cached_digest == digest. Changed content therefore returned the correct new digest with counter 0.
- Correct counter rule: increment when cached_digest is not None; any cached digest triggers a byte revalidation, match or mismatch. Candidate already uses this rule.
- Minimal one-line delta: 	10-hashonly-counter-fix.patch, SHA-256 $sha.
- Current root code has corrected rule. Reverse apply-check exit 0; forward check fails because correction is present.
- Root regression: 	ests/test_t10_snapshot_cache_revalidation.py::test_windows_snapshot_cache_revalidates_same_stat_rewrite[hash_only]; assertion remains snapshot_verified_rehashes >= 1.
- Candidate analogue command with PYTHONPATH=src: python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_acceptance.py::test_hash_only_revalidation_counts_same_stat_content_change.
- Candidate result: exit 0; 1 passed in 0.75s.
- Root test not run by T10. T20 owns root and root test slot.
- Cold first read has no cached digest, so counter stays 0. Same-stat changed content on later read increments counter and replaces cached digest.
