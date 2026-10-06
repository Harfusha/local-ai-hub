# T13 root-current conversation route handoff — 2026-10-01

## Scope and tree state

Route/conversation handoff only. No root files edited. T20 owns the root checkout integration; T17 owns the current test slot. Do not run tests until reassigned.

Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

Root source snapshots at comparison:

- `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\http_server.py` — SHA-256 `2797956835473315EFDCE8D1571D86A766C6A8B1765DA2443CFE319F01D9855E`.
- `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\services.py` — SHA-256 `BAE60B898DB52E078265A2419DC29C3BC08C4311A391279B62C898F7D4C04922`.
- `C:\Users\Adam\.local-ai-hub\src\local_ai_hub\ollama.py` — SHA-256 `FBE21C79C1818B6037DAD5F409B308263DE88DE5EFAFF293DE6B44EC61779BDF`.

Candidate source snapshots:

- `src/local_ai_hub/http_server.py` — SHA-256 `762D005A5316AD8F06922BA07E4DEB7725BFAEA6848230295B8C82A5020969BB`.
- `src/local_ai_hub/services.py` — SHA-256 `E1529B6F60CBBF4B2104AFE9E203C7C66DA9CCC4D9372CADC171022F098BF59A`.
- `tests/test_conversation_continue_route_contract.py` — SHA-256 `D2D2D7F08EF19022E34B09B2E91D673D9176678DECB5FB57BB16036A65B66C03`.

## Root-current call sites and required port

Root `http_server.py` currently dispatches `/api/delegate` directly at line 2562 and `/api/conversations/continue` directly at line 2564. Gaming mode begins at line 2238 and calls the async-job cancellation hook before runtime unload. There is no active conversation registry or bounded conversation drain in that route.

Root `services.py` methods are `_generate()` at line 821, `_start_conversation()` at 1222, `continue_conversation()` at 1263, and `delegate()` at 1297. They have no cancellation event. The candidate adds a keyword-only event, routes it through both conversation entry paths, uses `request_interruptible()` when available, and discards/aborts reservations after cancellation so late output cannot be committed as a successful turn. Root runtime has interruptible methods in `ollama.py` and `tiered_ollama.py`.

Port these pieces as one ownership-reviewed change:

1. Add an active conversation registry and cancellable invocation wrapper in `http_server.py`.
2. Wrap `/api/delegate` only when `conversation=true`, and always wrap `/api/conversations/continue`.
3. On gaming transition, close conversation admission, signal active events, wait to a bounded deadline, and skip model unload while a conversation remains active. Reject reactivation while the registry still holds active work.
4. Thread `cancel_event` through `_generate()`, `_start_conversation()`, `continue_conversation()`, and conversation-mode `delegate()`. Return a terminal cancelled result and discard/abort the reserved turn after cancellation.

The existing root mode handler and services have concurrent owner changes. No broad candidate replacement patch is safe. Earlier patches `T13-conversation-route-guards-root-current.patch` and `T13-conversations-root-current.patch` fail `git apply --check` against current root contexts; their hashes and exact failures are in `T13-root-current-integration-status-2026-10-01.md`. This handoff records call sites and intended ownership only; it is not an applyable patch.

The root `AsyncJobManager` lacks candidate admission/release methods. This route handoff does not claim coverage for pre-admitted async jobs; integrate that lifecycle only with its owner.

## Pending evidence

Test selectors after slot release: `tests/test_conversation_continue_route_contract.py::test_gaming_cancels_active_conversation_before_unload` and `tests/test_conversation_continue_route_contract.py::test_gaming_skips_unload_when_conversation_ignores_cancellation`.

Runtime proof pending: live cancellable generation returns before unload; timeout path skips unload; late conversation output is not committed or returned as success.
