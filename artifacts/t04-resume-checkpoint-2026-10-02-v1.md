# T04 resume checkpoint v1

Date: 2026-10-02 (Europe/Prague)
T04 worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`
Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`
Root HEAD: `01df56605ccf484ebfe2808ac60d696c4e81dffc`

## Restored acceptance checkpoint

Read existing T04 closeout `artifacts/t04-end-to-end-acceptance-closeout-2026-10-01-v2.md`. Recomputed candidate hashes and confirmed acceptance source/test pins still match that receipt. Root HEAD also remains the same as its 120-pass receipt. No test rerun was needed; no source change since those receipts.

Candidate pins:

- `client.py`: `DCDF8BB8FF150B5FCD4EDD3A25B53991DD6B87CDB9DDDEC0714A7F11B2FAE5B1`
- `http_server.py`: `840933FF8801832D4DDC4746853011AB1486338EA42BBA186E137393574156D7`
- `mcp_server.py`: `A6449D390F27ED56C89139AC56518AD0D57AB9285FFD7FAD05E7D000D6729F50`
- `conversations.py`: `46DBCC009505CC15C91D76B6BAECD9B7B6B0BE956CF0317402CE7500CBCC4E09`
- `test_client_transport.py`: `777CC424B651130DC96FE4D2EAC21FE6E4C152E1C19C46F18EAE380587F588F3`
- `test_t04_public_api_contracts.py`: `AAFA9BF5713002C32EFDDE7D0CA77CFD7CD11CA9D38220F95B40BC8BF226ADFB`

Integrated root pins from closeout v2:

- `client.py`: `5518706E0E81623E3FF0184274BD17F18C9BF7F43D9BC4DD37FD754586B0D056`
- `http_server.py`: `BDB4ECF50C149FCB144F3745EC9AB58FCE029F900A6ED83A41C5FAF1D2C9BECB`
- `mcp_server.py`: `5FF372AF25D78EDBB09B7F6D3AB6ECF5F8C9C593247F38A7B01C2CFF8E7929CE`
- `agent_tasks.py`: `79487FCE9F8A477A9DE888A6C7FEF77C3526F9B63151EF69FF0CE2019502BA45`

## Acceptance receipts

- Candidate assigned suite: **132 passed in 26.57s**; log SHA `7CC3BE41A4D4E4CD8471DDEE0287A3BD8FF5F3318D80E56D2A10277B70E03403`.
- Candidate API/conversation/query/inventory selectors: **39 passed in 43.83s**.
- Candidate path-hint client suite: **7 passed in 2.31s**.
- Root-current T04 integrated batch command and result are in closeout v2: **120 passed in 63.70s**, exit 0.
- T09 owner query suite: **8/8** in isolated overlay; both previously failing root query selectors passed in the 120-test batch.
- T21 accepted-hint route and adapter/runtime receipts were supplied and root path-hint E2E included in the 120-test batch.

No root writes, Hub retries, or source edits during checkpoint restoration. Existing mixed-owner dirty worktree preserved. `/api/context/pack` untouched.

The goal registry currently returns `goal: null`; no active goal record exists to update. This file and closeout v2 are the restored durable checkpoint. T20 retains overall release acceptance ownership.
