# T15 project config — root-current patch receipt

Date: 2026-10-02
Root: `C:\Users\Adam\.local-ai-hub`
Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`

## Patch artifact

`T15-project-config-root-current.patch` snapshots only the current root diff for:

- `src/local_ai_hub/project_config.py`
- `tests/test_project_config.py`
- `tests/test_project_config_service_integration.py`

Patch SHA-256: `0a3bfeb0fb5020895d9cd75ed9991003c09ebe1bec799d4d86faa773b70d8083` (36,700 bytes).

This is an export of the existing root working diff, not an applied patch. Root has unrelated dirty files; preserve them. `commands.py`, T21 adapters, and benchmark files are excluded.

## Verified root preimages and current bytes

Hashes computed from `git show HEAD:<path>` and current root files:

| Path | HEAD preimage SHA-256 | Current SHA-256 |
|---|---|---|
| `src/local_ai_hub/project_config.py` | `03145095fac22f7a69454069d0c41b5206ac2c78a0508cf6c924339d0fd26d5e` | `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713` |
| `tests/test_project_config.py` | `b113cda6549f4f4dbbfceb33c6240cef618cdebee9d6390335c087f4b3c084a9` | `90a66b610b84faddf178147321362db91139ffce0fdc680e01aad9fbd1866270` |
| `tests/test_project_config_service_integration.py` | `22da16f23ddd5cdb1aeb0a0dbb9a3af812a1bf85cebfe167df9f36487b3a40b8` | `a06522f19772744730045dfed9f46564bdaf26936e518082103798ff6b3d52a2` |

## Exact validation selector

Recorded T20 serial-slot receipt `C:\Users\Adam\.local-ai-hub\handoff\T20-CPU-SLOT-20261002-14\01-project-config-loader.receipt.json` reports selector `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config.py -k config_loader`: **5 passed, 69 deselected**. Input hashes before and after match the current source/test hashes above. No rerun here.

Prepared broader selector for the T15 scope, not run:

```powershell
python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_project_config.py tests/test_project_config_service_integration.py
```

`git diff --check` for the three owned paths exited 0. No benchmark run. Full project config and service integration acceptance remains unverified until its assigned serial slot.
