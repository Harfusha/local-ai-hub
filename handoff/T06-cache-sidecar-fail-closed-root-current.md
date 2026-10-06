# T06 cache sidecar fail-closed receipt

Root pin: current root working files copied read-only into a fresh temporary overlay. Root was not edited.

## Patch scope

- `src/local_ai_hub/cache.py`: if both atomic sidecar replacements fail, publish generation/quarantine through a direct write while holding the cross-process lock. Reader sees either complete state or malformed JSON and fails closed. Reject non-regular and multiply linked state files.
- `TieredCache.get_checked()` distinguishes coordination health; legacy `get()` keeps returning its value/miss contract.
- `src/local_ai_hub/commands.py`: suppression, success and failure cache reads discard unhealthy values. An unhealthy success namespace cannot fall through to stale failure cache; re-key lookup uses same helper.
- Regressions: cross-process L1 invalidation on atomic-replace failure; unhealthy cache read contract.

Excluded: `async_jobs.py`, T09 modules, rollback implementation.

## Exact hashes

| Path | Root preimage SHA-256 | Overlay postimage SHA-256 |
|---|---|---|
| `src/local_ai_hub/cache.py` | `C0549546064C44C6F71B3A4B5685571EB761B3FECB1936E7CF5226F274B11632` | `D26939199536E018E9A77D7D3761A674D0B3662F9052B37407C3CFBA21798A48` |
| `src/local_ai_hub/commands.py` | `9F7C4706839A23C79A9A46263CB34368CFF0E46F5C7D8D3E7CDFAAF07217C47F` | `3E348A6A955AA72E0ADBCCEAA94DC19ABED75B0F64B60FAAC701B741B81CED9F` |
| `tests/test_cache_invalidation.py` | `2EB71C09468F5225E455E520E016518E6EA3CCAAC404C49146F077B46796E7C2` | `2DED0DD86D8B85037B5D715D8FA86A19A659A3B7B9B1E3909E1CC5AC888E86FE` |
| `tests/test_t06_command_cache_read_fail_closed.py` | absent | `C3C1B2FBFD3C0A76A0243909683E78B6588F59C1A22488FB4B789E623554103E` |

Patch `T06-cache-sidecar-fail-closed-root-current.patch`, SHA-256 `61818513B5C1A59ABA46470AB2A22CB07B025AC0341C0CFF4BE939C566C75C45`. Fresh exact root-copy `git -c core.whitespace=cr-at-eol apply --check --whitespace=error <patch>` passed. Patch contains four paths above only.

## Focused validation

- Root-pinned overlay: cache invalidation + fail-closed contract tests, 17 passed, 1 skipped (POSIX advisory-lock test unavailable on Windows).
- Root-pinned overlay: `test_command_timeout_cache_contract.py`, 4 passed.
- Root-pinned overlay: `pyflakes src/local_ai_hub/cache.py src/local_ai_hub/commands.py`, passed.
- T06 candidate: corresponding cache/command tests, 22 passed, 1 skipped.

The prior broad rollback run is not part of this cache receipt. Root integration remains T20-owned.

## Root integration update

T20 reports the root already contains this cache producer/read behavior. Read-only hashes confirm root `cache.py` and `commands.py` equal the overlay postimages above, and the new `test_t06_command_cache_read_fail_closed.py` matches its postimage. Root `tests/test_cache_invalidation.py` hash is `3EC89EC2BEAD5455C461265C2814F373438340F8EBBE284A5D04510C5AF174A4`; it differs from overlay postimage but includes the cross-process atomic-replace regression. The v1 patch is historical and must not be reapplied. T20 is running current-root focused tests.

T06 remains open pending current-root rollback/write-set acceptance and TOCTOU review. Prior candidate broad run: 79 passed, 4 platform skips, 1 failure at `test_successful_short_command_creates_auditable_verification_evidence` (no artifact persisted); this remains untriaged. Do not infer cache completion receipt proves rollback or root acceptance.
