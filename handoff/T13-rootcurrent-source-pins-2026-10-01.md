# T13 root-current narrow patch handoff — 2026-10-01

Root checkout: `C:\Users\Adam\.local-ai-hub` (T20-owned; read-only from T13).
Root revision: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
Patch: `handoff/T13-rootcurrent-fresh-overlay.patch`
Patch SHA-256: `95D33076B5BC61A61D5A59C54B5FF21DDA7C271EABAA6544B9DEA499FF38895A`

## Pinned root source (preimage SHA-256)

- `src/local_ai_hub/operational_mode.py`: `D2B510D1ED2A7C7819E0FC063376BB6256C57D6BFFDDE63D872E27D0E758BFD1`
- `src/local_ai_hub/http_server.py`: `F7AB1A374F15718FFF09E9016552EAF766023F7D1F007E9CB730B0547800F6F5`
- `src/local_ai_hub/mcp_server.py`: `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`
- `src/local_ai_hub/app.py`: `F7360F3A7B266030FF0A79E5C1EA46780D5F3E28E96D2AD89254070656C53A60`

## Overlay source (postimage SHA-256)

- `src/local_ai_hub/operational_mode.py`: `50FA2F56E0B0FDECED08EA1603C78D81DB2E4451BDEFA4E1D6D219D0FD60E8F9`
- `src/local_ai_hub/http_server.py`: `CCB912FE56D153B9E8D38DD240170F6B4EDA1734BF8788A2E41B508672552770`
- `src/local_ai_hub/mcp_server.py`: `DE6D3C684D9E4E0AED8D18F990A510B855458E20E46A56BF1710EBC9DA6E1AD4`
- `src/local_ai_hub/app.py`: `F87ECDD9871EE49AFA11D3DDED67FFF83EA6CA0CE00697C85251EAD2F0DED6ED`

## Scope

- Central gate allows deterministic existing-job actions only in gaming; maintenance denies them. Gaming permits cheap deterministic reads. MCP health/status remains operator-visible and does not enter tool accounting on rejection.
- HTTP existing-job controls now pass only active/gaming; maintenance denies before handler/DB work. Async job action extraction honors `action` where `job_action` is absent.
- Gaming transition reserves resource release under the reentrant mode guard; active resume checks the reservation. Runtime/model unload and accelerator cleanup execute after the guard exits. Reservation ends after cleanup, or after inference/transcription/conversation drain callbacks.
- Async batch children with explicit nonblank `root` or `cwd` keep that workspace; parent context is inherited only when child has neither.
- Patch touches only the four listed source files. No T05/T09/T16 files included.

## Verification receipts

- `python -m py_compile` on the four overlay modules: passed.
- `git apply --check` against an isolated copy of the four pinned root preimages: exit 0.
- Focused candidate regression tests: 8 passed in 3.27s:
  - operational deterministic-read gate
  - HTTP cleanup outside guard and reservation held
  - reservation before mode exposure; resume blocked during release
  - MCP safe-job maintenance/gaming behavior
  - async batch workspace inheritance
- Root checkout was not modified by T13.

The regression tests ran against the T13 candidate, while the fresh root-current overlay received syntax compilation and apply-check. T20 should rerun tests after applying to its integrated checkout.
