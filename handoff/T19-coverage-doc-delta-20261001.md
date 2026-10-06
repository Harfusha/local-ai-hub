# T19 generated API coverage delta

**SUPERSEDED — DO NOT APPLY.** T01 removed the duplicated route/action findings block in its owned worktree after this snapshot. Current expected root coverage is 685 rows, not 1,192. T20 has the T01 source and docs patches. This T19 patch remains only as evidence of the earlier renderer state.

Update: root now has 685 data rows and one `GET /api/context/pack` row owned by T01. Root document bytes SHA-256 is `bae4ff38048635ad00e895b1b0bc5d55f9cd9a742b0a0a6fa0336579facb21af`; generated LF renderer bytes SHA-256 is `807730ae78da3599548acfab0606c5fe213cc3ad6799ee63a8ede7318a77f3cd`. Line contents match after newline normalization; root has CRLF and renderer emits LF. T01's document patch is already present in content, so its old apply-check no longer applies.

Generated against root worktree at HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root remains unmodified by T19.

## Artifacts and verification

- Current source `tools/surface_inventory.py` SHA-256: `075c5727062a701dbddde00dd135d253a2247c71ecfd7af4447b04c7660c8c36`.
- Existing `docs/API_COVERAGE.md` SHA-256: `6514d599533028de3470bcc626132cfe19c6277fbd6d01efb4049c835cc2c0f8` (668 data rows).
- Rendered document SHA-256: `b88f9e88bbf9ce7562f4f16f70915039ae9cd664cfb02cceac7475e700a01fc4` (1,192 data rows).
- Scoped patch: `handoff/T19-API_COVERAGE-current-root.patch`; SHA-256 `2e16a7e73d0b28996822705e13502df4eaceee0715d42a38190946ec2b55d09b`.
- `git apply --stat`: `docs/API_COVERAGE.md | 1880 ++++++++++++++++++++++++++++++++------------------`, 1,202 insertions, 678 deletions.
- `git apply --check --verbose` passed against the current dirty root document (exit 0). Patch changes only `docs/API_COVERAGE.md`.
- Inventory drift was empty. Render used `collect_inventory(root)` and `render_coverage(inventory)` without writing to root.

## Owner review note

Rendered current root contains two identical `HTTP GET /api/context/pack` rows: one carries `owner_task=T01`, the other `owner_task=unassigned`. Root `_findings` currently emits duplicate HTTP findings; its later duplicate loop omits `owner_task` propagation. The generated document preserves both rows because it mirrors the current renderer. T20 should resolve or explicitly accept this metadata duplication before applying the document patch. It does not add a route or change route behavior.
