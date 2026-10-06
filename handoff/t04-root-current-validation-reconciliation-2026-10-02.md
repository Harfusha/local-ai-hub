# T04 root-current validation reconciliation — 2026-10-02

Scope: reconcile three validation attempts and package four independent owner patches. No tests run while preparing this receipt. No root files edited. HUB omitted per user instruction.

## Exact validation chronology

Command for Run 1, Run 2, and T20 broker attempt:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py`

Command text SHA-256: `93D27533CDE200B0A0CE4F409DC8B4F66230D9454C57F895AAB3B626207A915F`.

- Run 1, native, exit 1: 27 passed, 9 errors, 4.36s. Input hashes: `src/local_ai_hub/client.py` `0C3690E24499DEC22A4EC1295BAEA06FF52E54880021E7A432A4BD733D15BC1D`; `src/local_ai_hub/inprocess_transport.py` `4820102BE7AB5BF2E4F2C2F47CC45A500DA65F679FFCB67B7EB122D25C703982`; `tests/test_inprocess_transport.py` `D458FD0608CFC86A75FB984EA3C87A40E0A6A9CFE7651276369C5FAE9A213A1A`; `tests/test_client_transport.py` `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`; `src/local_ai_hub/operational_mode.py` `B72023ED7BD029EA747794A02B5C8F6783E6DC592B4BF67542BDEE63F5D1F5A1`. All 9 setup errors: test fixture passed mode/state_dir in reversed positional order against T13 API.
- Run 2, native, exit 1: 31 passed, 5 failed, 5.77s. Inputs same as Run 1 except `tests/test_inprocess_transport.py` was `F9E06F92FC3406E46AFD1122C41656C7102001806636AE587F3D8EDC81A8903A` after five T04 call-order fixes.
- Broker attempt, T20 authorized: same command and root cwd; reuse key `t04-root-current-transport-37-2026-10-02-r2`; request `req_0d535cb13abd`. Response `outcome_unknown=true`, `success=false`, error `request outcome is unknown after a transport failure`. Broker gave no execution receipt. Therefore command completion and exact input snapshot for this attempt are UNKNOWN; do not count as a third test result, do not retry.

## Five Run 2 failures — ownership and disposition

1. `test_inprocess_transport_preserves_request_identity_and_cancel_route`: stale fake Recovery API; it rejects Handler keyword arguments and returns no `claimed` result. Fixture patch adapts fake signature and return value.
2. `test_inprocess_transport_fails_closed_in_restricted_operational_mode`: T04 in-process mode rejection omitted additive semantic fields (`error_code`, `operational_mode`, `mode`, `action`). Mode-output patch normalizes response while retaining gate rejection.
3. `test_inprocess_transport_keeps_deterministic_read_allowed_in_restricted_mode`: expectation stale. T13 HTTP path gate denies `/api/repo/topology` in gaming. Path-gate patch changes test to assert denial and zero service dispatch; no gate bypass.
4. `test_inprocess_timeout_reports_uncertain_result_but_does_not_cancel_service`: same stale fake Recovery API prevented dispatch/start. Fixture patch addresses it.
5. `test_inprocess_timeout_before_admission_does_not_dispatch_later`: root-current HubClient checks only `_TransportFailure` type, misses `InProcessTransportFailure.request_not_sent`. Client patch checks the transport-neutral attribute at both refusal classification points.

## Four independent patch receipts

- fixture: `t04-root-current-fixture.patch`; patch SHA-256 `C9F35EB52EC54C56FA800DDBBDAF2F9AB165A71CE8B96339320357975FFBFAAC`.
- client: `t04-root-current-client.patch`; patch SHA-256 `55DD0E5282D35FF6EEBF439F2D9E280C72D1C75EFF5E9EDA7767C06CF03994FD`.
- mode output: `t04-root-current-mode-output.patch`; patch SHA-256 `1BF3D30437EFD5DE24EE687DC37874C813D8A7851FFDB86DA70EE017B151E7C6`.
- path gate: `t04-root-current-path-gate.patch`; patch SHA-256 `C08668B1A5BC3CCB7F0C04344799B8CA881DD9C326F28A68498E913DE10D6E40`.

Each patch passed `git apply --check` against current root. Pre/post SHA-256:
- Fixture, `tests/test_inprocess_transport.py`: `F9E06F92FC3406E46AFD1122C41656C7102001806636AE587F3D8EDC81A8903A` -> `4FBB55E28EB116B735FA355C91D56E02A5FEA7EE602B796C7C8B92BF2FAEAC81`.
- Client, `src/local_ai_hub/client.py`: `0C3690E24499DEC22A4EC1295BAEA06FF52E54880021E7A432A4BD733D15BC1D` -> `37D16B03BD6AC69D6519977B1750D1F276288C5D766D3212D3970ECDFCA2A429`.
- Mode output, `src/local_ai_hub/inprocess_transport.py`: current root preimage `AED6A4B8B3F04A3AC0977CFA6D1618FF316441D9ED0E8ED976E234BBF3250C38` -> `71EDAA66840AEF2E13C82D97D66665E277A840E4B1A2E8C5A3D89AA9463BB29E`.
- Path gate, `tests/test_inprocess_transport.py`: `F9E06F92FC3406E46AFD1122C41656C7102001806636AE587F3D8EDC81A8903A` -> `A80B5F6BC4B73BCE6571F067629EACFA84CE2EE059070C58E7A6AC860240D6F9`.

Chronology correction: validation receipt v1 records transport input `482010...` at both native runs. Later current-root inspection found transport at `AED6...`; intervening change provenance is unverified and not attributed to T04. Mode-output patch targets only this current preimage. Test-time inputs and present-root inputs must not be conflated.

Disposition: source patch packets ready for owner review/integration. Acceptance remains partial; no fresh post-patch validation. T20 serial test slot still required before any rerun.

## T20 acceptance handoff

T04-owned proposal hunks in this packet:
- Fixture patch: fake Recovery accepts Handler keyword context and returns `{"claimed": True}`; T04-owned mode setter calls use keyword arguments compatible with root T13 signature.
- Client patch: `HubClient` recognizes `request_not_sent` transport attribute in both refusal classification locations.
- Mode-output patch: in-process operational-mode denial retains gate result and adds normalized `error_code`, `operational_mode`, `mode`, and `action` fields.
- Path-gate patch: updates only stale gaming-mode test expectation; `/api/repo/topology` stays denied and service dispatch stays empty.

T20 next acceptance steps:
1. Keep root unchanged until patch ownership/preimages accepted. Apply only patches whose listed preimage SHA-256 still matches; fixture and path-gate intentionally share test-file preimage, so sequence/recompute postimage if both are selected.
2. Allocate a fresh exclusive serial test slot before validation. No rerun follows broker `outcome_unknown` without this allocation.
3. Rerun the exact affected transport selectors against accepted postimages; capture command, checkout HEAD, every full input SHA-256, output and process/side-effect evidence.
4. Rerun stale public API/conversation/operation/inventory selectors: recorded receipts refer to old candidate HEAD `f305ec6...`, not current T04 HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.
5. Resolve owner handoff for MCP path-hint chain. Current T04 audit found `local_ai_repo` public signature and `_local_ai_repo_impl` lack `path_hints`; search action does not serialize it. T03 owns public wrapper; T04 `mcp_server.py` contains T07-owned hunk, so T04 must not edit it without handoff. Existing client path-hint tests are stubbed and do not prove MCP-to-`/api/search` propagation.
6. Obtain T21-owned adapter/runtime evidence. T04 source/test audit found no proof for that acceptance slice; client stubs do not establish adapter/runtime behavior.

Evidence boundary: T04 assigned nine-file suite passed `132 passed` on recorded T04 candidate; exact failing selectors also passed in focused run. This does not cover stale selectors, MCP path-hint propagation, or T21 adapter/runtime acceptance. Root-current patches above remain proposals and are not applied. `/api/context/pack` untouched. HUB omitted per user instruction.
