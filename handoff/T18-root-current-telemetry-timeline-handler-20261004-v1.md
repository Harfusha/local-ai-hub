# Root-current T18 telemetry timeline packet — 2026-10-04

## Immutable packet

Patch: `T18-root-current-telemetry-timeline-handler-20261004-v1.patch`

SHA-256: `DB1A93AA0F6187FAA8E57B04F4C33BE6D609EDA9A349816624D93AF5B91616DD`

Pinned base: root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; `src/local_ai_hub/http_server.py` preimage SHA-256 `C97AA26A4D84BE35FE7BFA1A18FDBB5AE9A5BA393F73D541D38E3F2DCB33D93D` (313821 bytes). New registry and focused test paths were absent at root.

## Packet files and postimages

| Path | Postimage SHA-256 | Ownership / delta |
|---|---|---|
| `src/local_ai_hub/http_server.py` | `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24` | T18 operation `op-e7c38a4c7425` only: import selector; add `_handle_post_telemetry_timeline`; dispatch its route ID inside existing post-recovery generic exception boundary; remove original inline timeline branch. |
| `src/local_ai_hub/http_route_registry.py` | `C245634F3131C37C49921C756DE81B6D377C0E3395DE5A3E8E0FF6C984F67436` | T18 only: one immutable POST route ID, `/api/telemetry/timeline`, plus named-handler mapping. Other 222 routes excluded. |
| `tests/test_http_post_telemetry_timeline_t18.py` | `EE0842F4F21B3FCB6140409218291C41867E5E61F84747E0AB0C5612D9BF3900` | T18 only: route selection, success status/body/arguments, exception propagation, and shared-gate/error-boundary order. |

## Preserved order and behavior

The root handler continues readiness and authorization, trace setup, admin-mode special handling, bundle-import raw-body fast path, JSON validation, mode rejection, telemetry-tool-accounting fast path, tenant/recovery claim, and debug-trace setup before the new named dispatch. The timeline handler preserves `limit` default 100, optional `before_id`, the existing telemetry service call and HTTP 200 body. Handler errors remain inside the same generic exception boundary. Unmatched routes fall through unchanged. `/api/context/pack` remains inline and is not registered.

## Integration and verification

- Root-current `git apply --check` before integration: exit 0 against the pinned root worktree bytes. `git apply --stat`: 3 files, 108 insertions, 4 deletions.
- Integrated in the root working tree per the T20 handoff. Root source remains byte-identical to packet postimage: SHA-256 `589C578EA5EB78C3192D3531FB776BF93FD703D9EFAB85B358B04A30891EFF24`. Current integrated registry SHA-256 `46AD21C6AFB648C2436D207E2BC83491CAFAF718B818F51707502738C372E4BA`; focused test SHA-256 `8E4E494005D883690D7F51D85EA064AFACB50570C50DA2388CCCE50B81B9FF11`.
- T20 one-shot receipt, forwarded in task: all-route test suite including this test — 118 passed in 3.33s. Not rerun here. Candidate isolated packet tests also passed: 3 passed in 0.35s.
- Slice status: **DONE**. Overall T18 remains **OPEN** for remaining 222 routes and full behavior parity. No runtime proof.

Root HEAD stayed `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`; integration is present in its dirty working tree. Any source byte change invalidates the packet base for future application.
