# T03 live-wire test root-current patch receipt

Date: 2026-10-01 (Europe/Prague)
Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
Assigned candidate: `C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub`

## Scope pins

- Root preimage: `tests/test_mcp_live_wire_schema.py` **absent** at snapshot.
- Candidate postimage SHA-256: `18EEEFCDC44D370F8DEA214802619A3C70781948E65F5AF966395FC9D5680B62`.
- Patch: `T03-live-wire-root-current.patch`.
- Patch SHA-256: `E0137976016B81C93457E9CAE8FB542211B8833E090685FCEDECAC36E4F80175`.
- Patch stat: one added file, 313 lines. No other path included.

## Check

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t03-contracts-resume\.local-ai-hub\handoff\T03-live-wire-root-current.patch
```

Result: `PASS`. `git apply --stat` lists only `tests/test_mcp_live_wire_schema.py`; root remains unchanged.

Candidate tests (previous receipt): `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_mcp_live_wire_schema.py` => `3 passed in 17.53s`.
