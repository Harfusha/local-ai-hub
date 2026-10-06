# T01 root selector run request — 2026-10-02

**Gate:** wait for explicit T20 root-slot release. Do not execute before release.

- Root checkout: `C:\Users\Adam\.local-ai-hub`
- Selector list: `C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub\handoff\T01-root-current-selector-list-20261002.txt`
- List SHA256: `E5F04C4E59A17FEB086D3101658E7EE534AB0F2AB6B3614D6B5081B49E1019C1`
- Exact list count: 63 unique selectors; lines are sorted and deduplicated.
- Prior T01 candidate result: 63 passed in 25.96s. Candidate evidence only; do not count as root-green.

Run from the root checkout only after T20 release:

```powershell
$selectorFile = 'C:\Users\Adam\.codex\worktrees\t01-coverage-main-verify\.local-ai-hub\handoff\T01-root-current-selector-list-20261002.txt'
$selectors = Get-Content -LiteralPath $selectorFile
if ($selectors.Count -ne 63) { throw "Expected 63 selectors; got $($selectors.Count)" }
python -B -m pytest -q -p no:cacheprovider --tb=short $selectors
```

The final receipt must pin the root HEAD and hashes of all six test files before execution. Stop without tests if T20 has changed the list, root preimages, or slot allocation; reconcile those pins first.
