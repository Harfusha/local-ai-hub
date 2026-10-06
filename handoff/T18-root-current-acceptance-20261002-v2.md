# T18 root-current status/telemetry/privacy acceptance — 2026-10-02 v2

## Scope and root safety

Read-only inspection and bounded tests against root `C:\Users\Adam\.local-ai-hub`. No root file was edited. Root remained HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Scoped `git status` before/after tests matched; current root source/test SHA-256 values are recorded below. Pytest cache disabled and Python bytecode disabled; temporary test databases used pytest temp paths.

## Root-current files and evidence

- `src/local_ai_hub/telemetry.py` — modified; SHA-256 `59A8F461CCF11C09526624EDEBD4D4FD99FB314935BE893BBFCE052CAF09281B`. T18 flush retry patch reverse-apply check: exit 0, patch SHA-256 `09BBC8E951F5DE8654C40F19E9120AE8C800D3621DDF6F902D411A49DBFE400F`. Safe error-class patch reverse-apply check: exit 0, patch SHA-256 `BF45D78C0215F14FE6E7E8AB91A501DFA205CC4E31AFDC8CECF9FE1625F0934B`.
- `src/local_ai_hub/http_server.py` — modified; SHA-256 `8443F8E178C717C92C063394C585C8C38721BD18F644DB053DB6EF81A5F0E047`. Current diff contains `_http_admin_action`, configured action-token scopes, and mode-control action mapping. Admin-auth source hunk reverse-check: exit 0, patch SHA-256 `A0335C3FF0B0319F840C794123525625B6DA84536D0669B96EC103D64B9D358B`. Admin-action auth selector passes in the 48-test root run.
- `src/local_ai_hub/dashboard.py` — modified; SHA-256 `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`. T18 operator-display source hunk reverse-check: exit 0, patch SHA-256 `C65C257D082B180B908F6DCAC49DB09CA0131BF05E290D353CD7D9F9DCB579CC`. Whole patch reverse-check is blocked by a divergent dashboard-test hunk; source-only check passes and root dashboard tests pass.
- Root test files present in the dirty worktree: `tests/test_telemetry_flush_retry_t18.py` SHA-256 `D1FFDFB7BDB48870286B697AC374F4C9E18B9F5ACFBAB627ABD6DFF3394A8A13`; `tests/test_telemetry_privacy.py` SHA-256 `481647E6F7E04CDFE47EF731A69EA3711023B893084DD9FD1306A83B256ADC19`; `tests/test_telemetry_error_metadata_privacy_t18.py` SHA-256 `77111EE980DDD164EBBC02C750506675812B7B0DE266132DCBB523D14B195B5A`; `tests/test_http_admin_action_auth_t18.py` SHA-256 `3C82151BB3C064E37BDA4CB052EE09CBF9E02B7A3144CBDDE065EDABE46BCC20`; `tests/test_http_operational_mode_t18.py` SHA-256 `EAAA8F6CB264E9F008A9843F38245C2E574665DA65E24F5AE0EE9F5B113A5268`; `tests/test_http_status_diagnostics_t18.py` SHA-256 `AE835F8F1521BF57AC34616D83117F3E8EC5D7813D0A4464BEE8D4174CAF966C`.

Telemetry preserves sanitized exception type and allowlisted reason. Only bounded integer `status_code`, `errno`, or `code` in `[-65535, 65535]` contributes to the error fingerprint. Tests check equal 503 fingerprints, distinct 504 fingerprints, and absence of prompt/source/token/path sentinels in persisted records.

## Root selectors and results

Root bounded acceptance selector, excluding T13 operational-mode source tests:

```text
C:\Python313\python.exe -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_flush_retry_t18.py tests/test_telemetry_privacy.py::test_error_telemetry_persists_classification_without_exception_text tests/test_telemetry_error_metadata_privacy_t18.py tests/test_telemetry_error_classification_t18.py tests/test_telemetry_error_diagnostics_t18.py tests/test_telemetry_sqlite_dashboard_t18.py tests/test_http_admin_action_auth_t18.py tests/test_http_status_diagnostics_t18.py tests/test_status_snapshot_quality.py tests/test_dashboard_operational_surfaces.py
48 passed in 10.31s
```

This includes original root privacy regression, safe type/code fingerprinting, action-token auth, status dependency degradation/stale reuse, and dashboard transition/error projection.

Operational-mode source gap, bounded reproduction:

```text
C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider --tb=short tests/test_http_operational_mode_t18.py::test_mode_get_is_loopback_only_auth_exception_and_returns_snapshot
1 failed in 0.40s
AttributeError: root local_ai_hub.http_server has no attribute `_operational_mode_api`
```

The larger selector including all `tests/test_http_operational_mode_t18.py` produced `56 passed, 22 failed in 10.55s`; all 22 failures are mode-source API expectations. Ownership map `T18-ownership-map-current-root-20261001-v1.md` assigns operational-mode production to T13 and excludes transplanting candidate mode source. Root GET `/api/mode` and mode transition acceptance remain a T13 integration dependency; no T18 source patch is supplied for that path.

## Result

Root-current T18 telemetry/privacy, admin action auth, status degradation/staleness, and dashboard failure-feedback selectors pass. Applied telemetry, auth, and operator-display source hunks have concrete reverse-diff evidence above. No root patch remains for those accepted hunks. Operational-mode production is the one uncovered root integration dependency, owned by T13. Root original privacy test now passes. T20 still owns overall release review.
