# T19 SDK smoke r2 — actual integrated root snapshot

Owner: main orchestrátor; original bounded Bacon worker is closed. Only existing new SDK smoke test changed; r1 handoff preserved. Root production source not edited by this owner. T20 serialized test slot transferred to main for this batch, then returned.

## Real root RED and diagnosis

Source selector `T19_PACKAGE_SOURCE_ROOT=C:\Users\Adam\.local-ai-hub` with original test SHA `FDAED8791E9021C47B9C56F92A11115F7020F03ED833BFE61DBA16CFCA77F58F`:

`& 'C:\Users\Adam\.local-ai-hub\.venv\Scripts\python.exe' -I -B 'C:\Users\Adam\.codex\worktrees\t19-docs-rollout\.local-ai-hub\tests\test_t19_packaged_sdk_smoke.py'`

Actual result: **1 failed in 11.512s**, exit 1. Real build/install completed; installed schema probe compared raw Python metadata with a JSON roundtrip and failed.
Failed receipt retained: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-6_fm2s7_\receipt.json`.

Separate bounded diagnostic reused that actual fresh-venv installed package and original guarded probe. It proved JSON serialization succeeds; differences are tuples versus JSON arrays in `x-operation-contract.feature_requirements` and action `required/non_empty/requires` metadata. No missing fields or invalid wire schema established. Raw Python container identity was an incorrect test contract.

## Narrow fixture correction and added controls

Changed only `tests/test_t19_packaged_sdk_smoke.py` through `apply_patch`:

- Inspect actual JSON wire schema for all existing SDK/schema assertions, not raw Python tuple identity.
- Canonical JSON roundtrip must preserve bytes/fields; reject NaN/infinities with `allow_nan=False` and unsupported objects.
- Added a pure guard test: tuple metadata retained as arrays without mutating input; three non-finite controls and unsupported-object control rejected.
- No production/schema feature gate changed, no missing resources or network guard assertion removed, no skip/deselect introduced.

New test SHA `CF0889E223467D5606161270FF9831005971E4F1BFFF315D1201E50BD9F46144`.

## Actual GREEN on root bytes

Same exact invocation with root source selector; prior process environment value restored in `finally`.
Actual result: **2 tests passed in 13.131s**, exit 0; no skips.

Fresh receipt: `C:\Users\Adam\AppData\Local\Temp\t19-packaged-sdk-vjtt5vpp\receipt.json`, SHA `6E38D874EADF56ED354EAFE182C02A97A28B954A8FE657B6086FAB6F81B4097E`.

| Provenance | SHA-256 |
|---|---|
| Root selected source snapshot map | `42A4319D8CF6625E6B8F264BB494F6F239928D719192D3B1FD47FAF6CD78301C` |
| Actual sdist | `77B327D8C221C1BBDC373A7C9863B6897DA26DBA1050697FB22F28987ADF69B0` |
| Actual wheel built from that sdist | `7D67E5F4C9862A1E6F0126D953035EF9833754A74F8CD18286DBF090E8C0F7C8` |
| Installed actual JSON schemas | `BA4E44170001B3078353757EE63BD910F4A35703DA70896D1BD3EC69171100FB` |
| Root/selected repo_tools.py | `8DA38ECBE3DAA4C975EC8F14FEDBC74D91D04CEEAF4CBB2C7155A3E554B6DA65` |
| Root/selected services.py | `A06AE015085E4B4DC61BF09A99570332044D65D623B7521218E569C329554235` |

Real sdist, wheel, fresh venv, no-index/no-deps install, installed package origin/hash/resource/version 4.0.0 checks. Forbidden network/process events list empty. Hardware discovery substituted CPU-only. Six models-disabled tool schemas covered; no live MCP/model/GPU proof.

This is **current integrated-root snapshot capability**, not approval/publishing of the final release. Later production integrations require fresh final-snapshot package verification. Full pytest/static/release/hygiene gates and full T19/T01–T21 acceptance remain open. Hub was ignored under explicit human fallback instruction; no startup/health polling.
