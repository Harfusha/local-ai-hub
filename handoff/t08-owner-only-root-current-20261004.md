# T08 owner-only root-current handoff

Candidate HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
Patch: `handoff/t08-owner-only-root-current-20261004.patch`
Patch SHA-256: `e13c1e84bd90cfc5d281f755342317bd21169410ca5e9c94b16927527d9f0e36` (7,271 bytes)
Root `git apply --check --whitespace=error` against this patch: PASS; not applied. Root source/test files unchanged by T08 during handoff.

## Patch contents

Only three owner-reviewed test files; no production source hunks:

| Path | Root current SHA-256 | Candidate HEAD blob | Candidate working SHA-256 | Hunk | Review |
|---|---|---|---|---|---|
| `tests/test_agent_t08_durable_contract.py` | `2b75e1fbb4ef0dcbc7b82bdfa811de688e54b90a9d23d74f0d4a29bc1a9b2725` | absent | `82a22fec6ba55808e03367459cb10dd35fdae763747c3fde42e9412f9d3cbe66` | `-107,7 +107,16`; `-343,7 +352,8`; `-372,7 +382,8`; `-416,7 +427,8` | Four test-body updates for current root event-page representation and required `command_id` fixtures. |
| `tests/test_agent_t08_live_order.py` | `23472c0021dd415622882e2942f6dc99c153632d93cca5728808aac402f17bf9` | absent | `12c1d3432316c33f42f48a71824e45569a5c0f5a28ddba8e562757c62bd50f27` | `-1,4 +1,5`; `-122,6 +123,15`; `-402,3 +413,70` | Adds `replace` import, strengthens lock-order assertion, adds three publication rejection cases. |
| `tests/test_agent_incident_scope.py` | `bce7949947311d44f435b266d7cb74cea22e58fa5c7dd703c5d76450011e00c0` | absent | `7850e0acef12a7336763d8d3f8ca0987ca28d773ee0abd290a79067c718fe4b4` | `-120,3 +120,22` | Adds root/tenant attempt isolation test. |

All three test files already exist in root working tree as untracked files. Patch applies cleanly to those exact preimages. Their root preimage hashes are listed above.

## T08 production source comparison

| Path | Root current SHA-256 | Candidate HEAD blob | Candidate working SHA-256 | Root-current review |
|---|---|---|---|---|
| `src/local_ai_hub/agent_events.py` | `1b8e63a5ff329090801cd7f19e7df7a95e42ac0034465ac5fa06d566b279ccf4` | `d6000d3fe9eb4efe0d097814ce6b5ec7db7cacea46e88ab34bd31167902b5bbd` | `2102bcb71bb5521034355b3bad6d88d08003cc7509e7e39ce6c1580ca1055056` | `append_in_transaction` and `ordered_event_publication` bodies exact-match. `event_page` differs; root has newer behavior and `through_seq` bound. No transplant. |
| `src/local_ai_hub/agent_tasks.py` | `5ce57d0ef0b7a17992f604ab67390e481702b0f51393c375102623475fcf280a` | `46f0f79aa600031915e50404eebf378b9d070fef89e96fef917ab7fb112a4328` | `a86ff3b368c18eccead725cf30ed4bf793489324e209fe4a7ebf38820665c7ca` | `add_verification_receipt_in_transaction` and `transition` bodies exact-match. `_commit_update` differs; root has newer task-search-index transaction work. No transplant. |
| `src/local_ai_hub/agent_incidents.py` | `899092ff78a0297e2000fb3286de81d8b36cd6d3cb7b39f6ef5636aae39ef647` | `159eba8b2f440820b6cd71ef37621a8e5c69586d1d8c28a4d3f8bf6be91003c4` | `1ade1aa5b63f008ff9b7a930db06725054dda740f78279d1459e1ff3249c2a07` | Root already contains root/tenant scoping and non-positive limit guard. `capture` body exact-match. Candidate `find_negative_knowledge` SQL differs; no source transplant. |
| `src/local_ai_hub/leases.py` | `446959227d37e706bfa1511cee304c6d84fdd91da0ebfef5fbb88afaeeafd6ae` | `1d5ae261eaa1bd8e4528114502f3edda4d9053225ee410e2af5cd482e8ab0a13` | `08864c962783d530b255ebb6eeeb3154e496492af12d869cd8ca45ec45577f89` | No T08-only source hunk selected for transfer. |
| `src/local_ai_hub/sqlite_support.py` | `b181ed9ddb11d1a6a4959ad90175a6dfa03c69fd06b79cbacdca9ab4e04e39ec` | `e3ab1b3be9f9bdf1a85d423b13d8c96543c662ff7d8c0eff76d5ddc29563c666` | `7ac3f35553d57df84e1c5a82ac2ae35095c8d07bd8eada94b52f905b7449ca4b` | Durable backup/schema/quarantine helpers exact-match. Candidate `_migration*` functions are T05-owned; excluded. |
| `src/local_ai_hub/agent_blackboard.py` | `9222a5084bbb0a937cadb79a091134cabd4ca3a73b7a1321f0035db4dc78e2d1` | `90efcdf1c6004bf6e48f15090245cc8c046774bc0aa89011f70a70bfa171ccce` | `9222a5084bbb0a937cadb79a091134cabd4ca3a73b7a1321f0035db4dc78e2d1` | Candidate working file exactly equals root current. |
| `src/local_ai_hub/agent_context.py` | `24781a491cafa5483b2dd09f7a233e9f3365152b4cddfca8f31cedb55655fa0b` (CRLF; LF-normalized `D342606C73C497E86890DBAD89E6EF23142EA8D6C683E35269B995B354F1F1C2`) | `07a7b30b31621cdff5b1aec6a899f3e158c2f542228d80a6c815eb0478ba4811` | `fee97b4d16388337d046d0c0c4d04f3ec34b087011eeee0363a6f0dbf7099317` | No T08 source hunk transferred. T24 save/invalidate catches (candidate lines 299–306, 370–377) sit outside T14 memory helper/preload/active-memory hunks. Root T24 integration already present; focused root test previously passed 2/2. |
| `src/local_ai_hub/agent_memory.py` | `dfb76c298cf26015a8b8516c996f468d57d13b525bbebf78c881e9146d986e47` | `a4a4c0434bc74f106f758254ccd25cb2cbf0417cb54a8e51ca6bad5c29dcad5e` | `39eb33a440ea96d02cbe5d1a1e3d182b0f30a1b6487c881bd913ff23a9c68ab6` | T05/T14-owned. No T08 memory lifecycle source change transferred. |
| `src/local_ai_hub/commands.py` | `83cb8776b086167f1198f127e05c1271abc9e742ba1c0684772357a0bf28a279` | `9eadd896f38bf44566947d1b31b819bd789942e9c39e217ea5d7bc7efdff9939` | `4f96f79a1fcdc72889c7aa2e305b784684f2aefc8815eebd972c52d47e827577` | Root command capture already passes `repository_root=cwd, tenant=tenant`. Both call sites leave `find_negative_knowledge(query, limit=3)` unscoped; scoped incident lookup fails closed. No caller hunk transferred. |

## Related test ownership and exclusions

- `tests/test_agent_t08_crash_after_commit.py` root SHA `9c949a0cb2d9fc5f58fa7264ef1e8f5def13bb657328998591d0a97918849e8f`; candidate working SHA `aee9e6b7a74e3e16c7985bf5c7843b0ddc420f26d748da9881e33451c0bc8541`. Relevant selector bodies match; no patch hunk.
- `tests/test_agent_t08_cache_isolation.py` root SHA `c132ef4f7ca3ebd6fd072b10c4ac5835501ec6660d23d62f95690697561e8e75`; candidate working SHA `75a289cb3027a623f3d2cbec50e530dca801ebe15ed8fa09538d156e98127f4c`. Selector bodies match; cache-isolation lifecycle test already present. No memory source hunk; `agent_memory.py` is T05/T14-owned.
- `tests/test_agent_t08_event_page_snapshot.py` root SHA `32a481ed12f35d309a53e6a2203ffb278837ff6e71e432cff5ac5d582b74ed66`; candidate working SHA `5d5e6f946d8165f640f0798129f45c70ba27d396c0a90f2bca9846d01b3ca7da`. Selector bodies match; no patch hunk.
- `tests/test_agent_t08_receipt_transaction.py` candidate contains three CommandBroker-level tests; excluded because `commands.py` is T06-owned and file is outside current T08 selector plan. T08 helper-level atomicity test remains separately covered.
- `tests/test_agent_tasks.py`: root SHA `376ba4cdd0729da73f6104b247ba24b1ad2a702c44cc209fc08f1ef7d6000d09`; candidate HEAD `c012a6a44ce3f3b7a45bee92bfc0f16028b642b1324e14503aae2fd6b352b2c6`; working `c0db40cc9f9ed81a1d1221c3ed12b9f431ebe13ad4d7ce6b1dc2f0f2baaff8c1`. Shared selectors exist; bodies differ due newer T21/project context. No transplant.
- `tests/test_agent_crash_recovery.py`: root SHA `210b0c5b3ba41d836dfff5d30cbb5cea2639b4935c1613d294dbdb6ead371d9c`; candidate working SHA `957a5f2ebb64c17362d0888294581c300eed3beb6b509c51634f9e589eb91d76`. Shared selectors but changed bodies. No transplant.
- `tests/test_agent_verification.py` is T16/T09-owned and root version is newer; excluded.
- `tests/test_lease_atomic_deadlock.py`: root SHA `083ea21b0dab45bc590207acac54097dcaa47a1a013e35d1b709c08195e328f5`; candidate HEAD has same SHA; working SHA `f0a0768cbf17b8ac2a4c0dfa9b47003c79ec147b48060c5c727c699bd11c8a70`. Test function bodies exact-match; no T08 hunk selected.
- `tests/test_agent_context_cleanup_t24.py` root and candidate SHA both `1aef1034c366c82c037f029abe1747349693f06b5687b46a9a1a1f78a068ca3f`; root T24 test receipt 2/2 previously recorded.
- Cross-owner acceptance paths containing T21/T07/T18 hunks excluded from T08 patch.

Candidate 104-test T08 acceptance batch previously passed in 53.27s. This is candidate evidence only. Root integration review remains pending; no root validation run in this handoff.
