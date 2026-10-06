# T04 slot 32 validation receipt — 2026-10-02

- Slot: `T20-SERIAL-20261002-A` (exclusive, released by T20 for this run only).
- Worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
- HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`; branch `codex/t04-integration-2b33602`.
- Broker repository revision fingerprint: `240ac9c427f740e9c4b07e050d7f5ee208725bb9f0b50a99ff0e5bd037a9d869`.
- No source or test files edited during validation. Commands ran serially through `local_ai_command`; no native test fallback.

## Authorized import assertion

Command:
`python -B -c "from local_ai_hub.client import HubClient; from local_ai_hub.inprocess_transport import InProcessTransport; assert HubClient and InProcessTransport; print('ROOT IMPORT ASSERTION PASS')"`

Broker receipt: `success=true`, `exit_code=0`, stdout `ROOT IMPORT ASSERTION PASS`, `execution_id=a88704e4a94a4df1842e296b9bba70c0`, `request_id=req_c84e84699e49`, `duration_ms=246.5`, `log_chunks_dropped=0`, `log_dispatch_incomplete=false`. Broker also returned `allowed=false`, `class=unknown`, reason `python -c inline code imports module with unknown side effects`; this contradictory classification is preserved as reported. No retry.

## Authorized focused transport suite

Command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_inprocess_transport.py tests/test_client_transport.py`

Broker receipt: `allowed=true`, `class=validation`, `success=true`, `exit_code=0`, stdout `37 passed in 9.55s`, `execution_id=68e5564d86314f58949d2bc9308cca22`, `request_id=req_41eb9551319d`, `duration_ms=10506.7`, `log_chunks_dropped=0`, `log_dispatch_incomplete=false`. No retry.

## Direct source/test SHA-256 pins

Hashes before and after both commands matched:

| Path | Before = after SHA-256 |
|---|---|
| `src/local_ai_hub/client.py` | `338A2C40C982E2A079B99F2A9C7044630F70788082B6219AA6174F1EAAB82098` |
| `src/local_ai_hub/inprocess_transport.py` | `25528A07417E5FDA4D86A954A0A44B73C30145A1FABC5B5E6244D0C3CEE51B47` |
| `src/local_ai_hub/operational_mode.py` | `3A083FA9DFF1B42E634B434ECAB8519916EBDC825579920CCF448B84AEC8F145` |
| `tests/test_inprocess_transport.py` | `6993215113A42C8DE0077C5160FBCF537663C0E6E7DA347C94B643272FE74FEE` |
| `tests/test_client_transport.py` | `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3` |

T04 candidate transport acceptance now passes 37/37 on these exact direct-input pins. This does not by itself close outstanding MCP path-hint owner handoff or T21 adapter/runtime acceptance in the criterion audit.

## Slot release result

After validation, requested `local_ai_coord(action="release", lease_id="T20-SERIAL-20261002-A", root="C:\\Users\\Adam\\.local-ai-hub")`. Broker returned `success=true`, request `req_46bbddd6a491`, but `released_rows=0`; no matching Agent OS lease existed. No repeat attempted. The T04 validation work is finished; the external T20 serial-slot ledger still needs its owner to acknowledge/release the slot. This receipt does not claim that external slot state changed.

## T20 slot-A closeout amendment

T20 later confirmed slot `T20-SERIAL-20261002-A` was manually released and its ledger closed after this receipt's 37/37 run. This supersedes the earlier note that external slot state still needed owner acknowledgement; `local_ai_coord.release` itself still reports zero Hub lease rows.
