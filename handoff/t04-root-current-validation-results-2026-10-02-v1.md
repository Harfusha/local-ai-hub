# T04 root-current validation receipt — 2026-10-02

State: VALIDATION FAILED / broker retry UNKNOWN. No further runs authorized or performed. Root production code not edited by T04 in this validation turn; the only T04 root edit was the five argument-order changes in the T04-owned test file.

## Revisions and inputs

- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- T04 worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1`.
- Root `src/local_ai_hub/client.py`: `0C3690E24499DEC22A4EC1295BAEA06FF52E54880021E7A432A4BD733D15BC1D`.
- Root `src/local_ai_hub/inprocess_transport.py`: `4820102BE7AB5BF2E4F2C2F47CC45A500DA65F679FFCB67B7EB122D25C703982`.
- Root `tests/test_client_transport.py`: `03000F1016075FC4B4025F9185CFFB471043663028F04496B0CD4F42D5EA06A0`.
- Root `src/local_ai_hub/operational_mode.py` (T13-owned): `B72023ED7BD029EA747794A02B5C8F6783E6DC592B4BF67542BDEE63F5D1F5A1`.
- In-process test before fixture adaptation: `D458FD0608CFC86A75FB984EA3C87A40E0A6A9CFE7651276369C5FAE9A213A1A`.
- In-process test after T04-only five call-site adaptation: `F9E06F92FC3406E46AFD1122C41656C7102001806636AE587F3D8EDC81A8903A`.
- T04 worktree source hashes unchanged: client.py `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098`; inprocess_transport.py `A5567CF4F86D848CA9034ECE886E497E3DB4AAFEFCA7EC81ABD772F64AEB5C75`; test_inprocess_transport.py `57EDD308C3BB85BDAA23575A67417FA79326A89BFE5E9E0E36BFF408623F1FE8`; test_client_transport.py `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`.

## Import assertion

Command:
`python -B -c "from local_ai_hub.client import HubClient; from local_ai_hub.inprocess_transport import InProcessTransport; assert HubClient and InProcessTransport; print('ROOT IMPORT ASSERTION PASS')"`

Result: exit 0, stdout `ROOT IMPORT ASSERTION PASS`.

## Run 1 — raw native, before fixture adaptation

Command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py`

Result: exit 1; 27 passed, 9 errors, 4.36s. All nine in-process tests failed at shared fixture setup line 116 because it called `set_operational_mode("active", state_dir)`; root T13 API is `set_operational_mode(state_dir, mode)`, and raised `ValueError: mode must be active, gaming, or maintenance`. Affected selectors:
- `test_inprocess_transport_routes_to_services_without_http_or_spawn`
- `test_inprocess_transport_lazily_creates_app_without_http_or_process`
- `test_inprocess_transport_preserves_request_identity_and_cancel_route`
- `test_inprocess_transport_keeps_http_rate_limit_across_requests`
- `test_inprocess_transport_preserves_auth_and_payload_validation`
- `test_inprocess_transport_fails_closed_in_restricted_operational_mode`
- `test_inprocess_transport_keeps_deterministic_read_allowed_in_restricted_mode`
- `test_inprocess_timeout_reports_uncertain_result_but_does_not_cancel_service`
- `test_inprocess_timeout_before_admission_does_not_dispatch_later`

T04 changed only those five argument-order call sites in `tests/test_inprocess_transport.py`. Static normalized comparison against T04 worktree confirms no other test-file difference.

## Run 2 — raw native, after fixture adaptation

Exact same command as Run 1. Result: exit 1; 31 passed, 5 failed, 5.77s:
- `test_inprocess_transport_preserves_request_identity_and_cancel_route`: request journal unavailable; mutation not dispatched.
- `test_inprocess_transport_fails_closed_in_restricted_operational_mode`: expected `error_code`, missing key.
- `test_inprocess_transport_keeps_deterministic_read_allowed_in_restricted_mode`: response blocked with `operational_mode_blocked`.
- `test_inprocess_timeout_reports_uncertain_result_but_does_not_cancel_service`: service-start event unset.
- `test_inprocess_timeout_before_admission_does_not_dispatch_later`: expected `request_not_sent`, missing key.

## Broker attempt and disposition

T20-authorized `local_ai_command(action="run")` used same exact pytest command, root cwd, reuse key `t04-root-current-transport-37-2026-10-02-r2`. Tool returned:
- `outcome_unknown=true`
- `success=false`
- request id `req_0d535cb13abd`
- error `request outcome is unknown after a transport failure`

No retry and no native fallback were attempted after this response, per instruction. Broker attempt output does not prove whether command started or completed; status is UNKNOWN.

## T13 contract and scope

Static source confirmation: T13-owned `operational_mode.py` defines `set_operational_mode(state_dir: str | Path, mode: str)` and accepts only `active`, `gaming`, `maintenance`. No T13 production file was modified. T04 production files were not edited in root; the sole root delta authored by T04 in this slot is the five T04-test call-site argument-order changes above.

## Slot

T20 allocated exclusive slot `T20-CPU-SLOT-20261002-07` to T04. This receipt records completion and release; next validator requires a new explicit T20 allocation. T15 may proceed only after T20 accepts the release.
