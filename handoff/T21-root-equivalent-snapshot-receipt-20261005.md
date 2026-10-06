# T21 isolated root-equivalent snapshot receipt

Date: 2026-10-05. Addendum; original packet and patch remain immutable.

## Snapshot procedure

- Copied only root-current `src/local_ai_hub/project_config.py`, `tests/test_project_config.py`, and `tests/test_project_path_hints.py` into a disposable temporary directory.
- Applied `T21-root-current-core-project-config-20261005.patch` in that snapshot. Apply exit: `0`.
- Confirmed all postimage SHA-256 values matched the original packet:
  - `src/local_ai_hub/project_config.py`: `1C004FA51B9D18737EFAF2EB63F3648814DB68B7FBF7FE348012917EDC07B641`
  - `tests/test_project_config.py`: `07E063C2EC00A94BE82A6D7F2C4ADAAD39BB117BAFB5873DEC904347F8AABDC9`
  - `tests/test_project_path_hints.py`: `237E00CF3E723A5EC010458277DF7810205196CD21DA0C448F5E59D915AC31C0`

## Test receipt

Command, with snapshot source on `PYTHONPATH`:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py`

Result: **101 passed, 1 failed in 2.27s**; exit `1`.

Failure: `tests/test_project_path_hints.py::test_request_path_hint_accepts_partial_optional_metadata`. Expected hinted path first, got original order: `('src/main.py', 'src/hinted.py')`.

## Status

Blocker: isolated root-current snapshot does not satisfy the partial request-hint regression. Test unchanged; no weakening or fix attempted. Original patch/manifest unchanged. Root and T21 candidate source/tests remain unchanged. Snapshot directory disposed. No Hub call.

Original patch SHA-256: `9307CB6025A881DC860A45C8560E9C7A1CF29FE89B98B483ACE936A4F08EDD33`.
Original manifest SHA-256: `2C0F1B49A92AEFC9D707032157FE4C5EA925A4209EDAAD1B62AAFDC12FBAE116`.
