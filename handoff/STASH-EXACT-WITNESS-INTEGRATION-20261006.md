# STASH EXACT WITNESS — integration review, 2026-10-06

## Outcome and ownership

SOURCE REVIEW PARTIAL. Preservation is not functional acceptance; no release verdict. Source adoption remains unfinished. No stash applied, dropped, deleted or rewritten. Only this new document is authorized for write and commit.

Assigned checkout: C:/Users/Adam/.codex/worktrees/t13-lifecycle-8429/.local-ai-hub; existing branch codex/sync-t13-lifecycle-8429-20261006. Entry HEAD b3b4d0b93c933c3e73a3f56dbbfd9563e2612e87. Master pinned ONCE to 7c932b6f31d81a5c6e331e7537d687fb0c8d9c12 and merged with git -c core.hooksPath=NUL merge --ff-only PIN --quiet. No conflicts; branch/HEAD became the pin. No manual source edits, root worktree reads/writes or master-ref writes. Later master drift outside scope.

Input: immutable 7c932b6f31d81a5c6e331e7537d687fb0c8d9c12:docs/STASH_COVERAGE_20261006.md. Its previous comparator 4891878b7cd887132cfaa8fc3d26f0bca3840702 and owner packet 0e4c62c296d59bdd318342a094ebf0d64f2efe76 are witnesses, not automatic integration receipts.

All 653 exactcovered T/I occurrences independently verified against original stash/index and base trees: 637 tracked + 16 index. ZERO provenance mismatches, ZERO false same-path checkpoint witnesses, ZERO mode mismatches in accepted reconciliations. Dedup path+original mode/blob: 587 versions. Keeping distinct bases: 589 original deltas, 8537 original hunk intervals. Repeated occurrences share rows; different bases remain explicit.

Disposition (unique original deltas): 96 integrated-current; 114 merged-reconciled-with-concretehunkproof; 379 preserved-only-needs-integration. Active src/tests/tools: 84 / 109 / 334. Browser/config/docs deltas are also retained below. Documentation content NEVER proves functional behavior; archived duplicates count only as preservation.

Excluded ownership: 32 unmatched tracked/index versions, 22 direct untracked candidates, 382 archive overlays. No closure/fixes for other-agent queue. All 45 stash identities inventoried; original 31 “no manual queue” stashes are NOT marked fully applied. U/artifact/runtime coverage is inherited metadata, not acceptance or revalidation here.

## Actual checks, proof rules and limitations

User supplied terminal Hub failure and native-fallback authority reused; no Hub retry/poll/preprocess/model call. token-economizer read-only policy followed; ensure-tools script was missing earlier, no installs/PATH writes. Native delegation attempt hit thread limit; no duplicate scope launched. Audit reads immutable Git objects with standard-library Python AST/difflib; Node standard-library zlib decodes audit in memory. No project imports, tests, builds, runtime calls, dependencies, caches or generated source artifacts.

Provenance uses git show, ls-tree -r -z, cat-file blob, rev-list, first-parent merge graph. Original intervals use base-to-version difflib opcodes (autojunk disabled). AST symbols ignore locations/comments only. Qualified class/function must fully contain changed original interval; pure deletion also must fall in corresponding base symbol. Exact AST equality proves retained structure, not runtime interaction.

Non-AST proof requires new interval plus three adjacent original lines in a contiguous matching block. Replacement old contextual block must be absent. Deletion requires new flanking anchor present and old contextual block absent. No semantic similarity, name-only match, model guesses or ancestry-only closure. Relocated/changed hunks or ambiguous anchors remain unproven.

integrated-current: same-path current mode/blob equals original, including exact absence.
merged-reconciled-with-concretehunkproof: EVERY original interval proven, plus an exact same-path witness entering actual first-parent side merge (ancestor of side parent but not first parent).
preserved-only-needs-integration: exact preservation verified, but some interval unproven OR qualifying side-merge evidence absent. This is NOT a claim every such interval is definitely missing. No unsafe re-adoption justified.

Legend: B whole current blob exact; A exact qualified AST symbol; L exact contextual lines/absence; U unproven original interval. Intervals -oldStart,oldLength+newStart,newLength refer to ORIGINAL base/version, not current line positions. Symbol-group lists exhaust original hunks. <module/text> means no wholly containing qualified Python symbol. Witness syntax: target ID / immutable witness commit / verified same-path exact / source side-merge SHA or none. Root reviewed merge SHA always 7c932b6f31d81a5c6e331e7537d687fb0c8d9c12. A merge SHA is not a runtime receipt.

## Priority source dispositions — no fixes

P1: stash 26 agent_verification.py original blob 11d7eb50bca0c858233f3a3663885922e2476539. Missing original VerificationStore._validate_receipt name is NOT missing validation. Its three task_id/criterion/passed-evidence_id guards are present verbatim INLINE in pinned VerificationStore.record_in_transaction AND record, followed by newer trusted-evidence/shared-database checks. Supplemental concrete proof closes those guards only; full version retains per-hunk U statuses. Do not overwrite master with old packet.

P1: stash 16 agent_context.py blob 751cbc1c271c6c25c01ec1954f27226307e69743. Original _context_scope_digest/request_scope_digest not exact retained. Concrete replacement: request_identity_digest feeds CompiledContext.etag, history stores (request_identity_digest, tuple(final_elements)), and previous record identity is checked before delta filtering. Not blanket equivalence for every original scope dimension; full original delta stays open where unproven.

P1: stash 32 client.py blob 688b789d65e7a35f55ccad326dd5387ed17c1e4a: _live_start_lock, _try_start_lock_guard, _release_start_lock_guard and nested launcher/metadata symbols absent under original names. Requires concrete relocated-helper/behavior disposition, NOT missing-name semantic guess. Stash 17 app admission binding and stash 12 command process-group/log-dispatch hunks also require owner review. Preserve newer ownership/safety while integrating old functional deltas.

P2: all U groups below, especially active src/tests/tools. Checkpoint or ancestry alone does not close them. Prior handoff/T13-central-review-20261006.md is a separate review against 90e6f295; its findings not silently revalidated against changing root source.

## Immutable stash provenance and per-stash disposition

B/R/P counts are covered T/I occurrences only. Original no-queue flag is preservation classification, NOT applied verdict. Cases with only U entries remain outside this scope, not blindly done.

| Original label | Stash SHA | Base SHA | Index SHA | U SHA | Original no queue | Covered T/I current disposition |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `f05d3603072c63ff38857649db95e299cb341b76` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `0be5d8d155cab50decb8ed6346b4e14575ef4e0a` | `ce6d252ea3c9cf6ab1707f3eb07bddf6b5d44f57` | yes — NOT applied verdict | {"B":1,"R":0,"P":9} |
| 1 | `382a17cbec4f557584264bd7199dbe3f91349f47` | `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` | `66fb8eec18903d489d31ab197760af696e147a6e` | `1df74e679e10b5423d014fac90f673338ff43f46` | yes — NOT applied verdict | {"B":0,"R":2,"P":16} |
| 2 | `77a09517d3fb3d8cd81e94550c6b2a081d11c487` | `8c945bdeb5f92270613e53b307b6f646a4f0e21b` | `ca668705c7fa7848edcba0aa32c4c03d9e84ea4b` | `a3abe53039f1fcad980259b0d1d3e5c99280516a` | yes — NOT applied verdict | no covered T/I; U outside scope |
| 3 | `c6918ee7e8eaf032cb9acd22924fbb2b3cffe758` | `2b33602adef0d030fea66cdcc04ca742c60b2e32` | `5f2ee8b6ea93684c88502d24be180a1ea2874b39` | `f27c865e4712738602cbc6515b198d5476bb7c76` | yes — NOT applied verdict | {"B":14,"R":8,"P":29} |
| 4 | `e4fdc272b9fbcbc7ac3d58f1b9b4ded55de830c6` | `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f` | `6159ff060d4991205d800c211fe10b85f97e36a4` | `5478f0ebca29738fe2d4d11342d001b2de2e398c` | no — separate queue | {"B":1,"R":0,"P":20} |
| 5 | `12beabe20f72bae37ca4c82b7c2443b5d5c80a6f` | `ec0a79cf9ec92cb4af8bff7ed802f0d64f9307bc` | `d75de1090e3b70b7cbdfc2f80856ee4f8b3885f0` | `c3c7ef5a72d10fa91ca131ad27fc4a5af4731aa9` | yes — NOT applied verdict | {"B":2,"R":5,"P":12} |
| 6 | `001d5c3227fde5136cb3453c4bb36ec8622b03fa` | `2b33602adef0d030fea66cdcc04ca742c60b2e32` | `349aaa765ce1549ffa65a0d36779a87f23904b0a` | `22e3e57fd7b7eca954e74fed6d6fc43e5bf0e43d` | yes — NOT applied verdict | {"B":0,"R":1,"P":9} |
| 7 | `ef2709e29cf3f1f5e7d3ee964d9bf4862cd080fc` | `2b33602adef0d030fea66cdcc04ca742c60b2e32` | `422ba4eb964a93768b4dc5550c0aa9e7d8c8ce02` | `d3328cc62f551e8c6ce868adf4135b1eafe9be47` | no — separate queue | {"B":10,"R":7,"P":23} |
| 8 | `97d2d9fed7cf42cfd28fbfae7e770bcceb575a43` | `2418035e8c1dfa44e2b82ca437b4b94b86415041` | `a6aaa75b6ce8ed42c1a0854016b99dbe63ae3307` | `e009e04d0427936f8e12906b6b97dd07289219e0` | yes — NOT applied verdict | {"B":1,"R":1,"P":3} |
| 9 | `ab172d846888d2984959a06ac7272f5907abb533` | `d63153a20efea83a16f3b5ca213a1d9777ebcca2` | `22dea3b0b0c640a8114756218b232d3095ed7cd8` | `aa7e9ac34a5fd18a72742f23aa6b73fcb0e84d3b` | yes — NOT applied verdict | no covered T/I; U outside scope |
| 10 | `c0a198821d1b4cac811303740c0511b093f22149` | `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` | `7003efea533cad259b1e6f213f2663681d0e0fc4` | `f8e551de2352c0d3aeedad77f5fdedc8e8d80313` | yes — NOT applied verdict | {"B":0,"R":1,"P":5} |
| 11 | `2d7a7a3e68117419f1d4d25603fb173ac663c127` | `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` | `a7cfe4308cb6376ff067e1ff8d2ba6d0e6640595` | `31d252900952ae544c61d607c0fae8ea57a59092` | yes — NOT applied verdict | {"B":0,"R":1,"P":15} |
| 12 | `5aad8c4301bbc1b311c1d6ca36faf4ced245d337` | `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` | `2bb4121eba94b4f794988c57f8c6d82d2f5d9b59` | `83614888a2ae98262f5d14271440c36ff8dd8106` | no — separate queue | {"B":0,"R":2,"P":6} |
| 13 | `64a794a60a0c5198de571e1163fe96d18f44fda0` | `8c945bdeb5f92270613e53b307b6f646a4f0e21b` | `331bf493cc6c77f4018f439c4f3f6def8804ba8b` | `db13e57914b3bc178b315715ac563aeaf243060d` | yes — NOT applied verdict | {"B":0,"R":0,"P":1} |
| 14 | `6545a24f28655982ad3907b87b04c87ef5dea100` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `eddde0f45849b8bae12e3f8ebcc734e2c43fd461` | `99768268d85ccd35db0e743f89efe8941bd3359a` | yes — NOT applied verdict | {"B":0,"R":0,"P":1} |
| 15 | `bafb739b3c31c2204b243b4691970bf750388612` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `59187872cf6da5443027ef18b921a717e4ecc1aa` | `c42c59fec0118fd12befeaeaa2936f9230cb808d` | yes — NOT applied verdict | {"B":0,"R":0,"P":2} |
| 16 | `ac0b245438a975ab465266bbed892674100f4dd6` | `8c945bdeb5f92270613e53b307b6f646a4f0e21b` | `07dad45a29727150ccad559ef0f8a37c8f52fac5` | `32a71db2d176db18a9f5e56c14e6597d856c9cb8` | yes — NOT applied verdict | {"B":0,"R":1,"P":9} |
| 17 | `f6037b1b8f5bbbb23fb4b69bba7552612a6135f6` | `6050c41ce5510a6de3eaeb674a180560ea404f24` | `8d17fcf41b07b87341009a476b9071af14696989` | `948d59fb901a8dbc0d146a625ddc421758ad6fec` | yes — NOT applied verdict | {"B":1,"R":2,"P":27} |
| 18 | `3e4f81d95b896a43ab4a5f72774a0f2e0f8e8df3` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `8e279237fe4d81e4fd591d673c40dee179d9d89b` | `5f553137c772236108c6a617e95364854aeaab3d` | yes — NOT applied verdict | {"B":0,"R":0,"P":4} |
| 19 | `75a8ff394d29fb0ad76cd6e73ab2111956b9658d` | `e9d6d82e535f5d5ca87018b89b33c2665084b77b` | `4cd5ca60fdeadd052f0f5b568241ff11cf9d374d` | `eab68c48b6f90c1b404919d137ca0b92db19701c` | no — separate queue | {"B":4,"R":4,"P":10} |
| 20 | `824700cac31a1d19f00cf4b24a2a43b1b020b11e` | `5749965cb3e7ce3e18905d4576958cc7e05348c7` | `9aafbd1ceafc5623967a66a8220b833d1ba4242f` | `cce5f8809386e2087cd606a839e0237d5eba2dc2` | yes — NOT applied verdict | {"B":0,"R":3,"P":2} |
| 21 | `2a1b3f1f8e53deb4db949d5808bdda10d8c05c58` | `7a36be3b8b69531dccd9215515ac793369da0a44` | `cfe0ac600caa6ac94bbf7f4f2cab3510c1db649f` | `bd8f6168af444f21497fc691ac4c2160e054afa1` | yes — NOT applied verdict | {"B":5,"R":3,"P":21} |
| 22 | `2030eb9d3e04cbbf17720d5d0f5f5ea3aae7f320` | `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11` | `600e99daa71d82f1b25f583b775d7b60df7388d7` | `78381b63bbb8c13fc7358a5c6a12e1414797e482` | yes — NOT applied verdict | {"B":3,"R":4,"P":6} |
| 23 | `f98585be9d7f7951cb3a1c2bc4dd52bc207ba7bd` | `2d01623daf63b27fdd25634d9fca859328c3f2e2` | `26fe34268c0b8e930dfa86504bfa287fc79fa6e8` | `e4ce6bba4dee181d75b4bf74414fcc0ab5463c57` | yes — NOT applied verdict | {"B":0,"R":0,"P":1} |
| 24 | `16269603f281615ba125f5c80cc38c04a7acca98` | `2b33602adef0d030fea66cdcc04ca742c60b2e32` | `957026c375f44f3161f86eecf3a5780a033fb3fe` | `b1c61ebb03082b189d4647b1c62602575a9e598c` | no — separate queue | {"B":1,"R":0,"P":0} |
| 25 | `b5ba0c89d548447b9293d4d5085d01919e0f92a0` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `8d461da1cfa7f44d6cd52bb4cf7e1b2f2aa29ae4` | `6100d4a79c7b3a636e8bce6d35bf03bf78e88836` | yes — NOT applied verdict | {"B":0,"R":1,"P":3} |
| 26 | `6c6c6c9d524855d57c0d71f8b40cbf1c3e5a1ae8` | `2b33602adef0d030fea66cdcc04ca742c60b2e32` | `e8c826747e8245caf8771fc54181fa48ea8c1d83` | `05880eb9928a513af3d6dad2cd1e3ef12b6365ff` | yes — NOT applied verdict | {"B":4,"R":9,"P":27} |
| 27 | `18008cd3d2d4191399ad5eebc21e9e74a6983359` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `86d9d60db81ab02404f815893870717e68fd94dd` | `a87d167aa59f76ab45735dcdd3b94c6c70cb5929` | yes — NOT applied verdict | {"B":0,"R":0,"P":3} |
| 28 | `2f3c83021780e97ebd7d6103155b948b0e9f7638` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `825cf3bf9b9ee05a465d88fefb70ecec2ecb394f` | `6275414f0715aa621bff5e3d4684067cea272d9c` | yes — NOT applied verdict | {"B":0,"R":0,"P":3} |
| 29 | `4a1c242bffdbb969cec19f364775a206be8312c6` | `94337de7309b66c63ff427cce8cd3a49e6414d73` | `bd9b942ecbb48b788531d55735b8c79f78ae644a` | `dffe86fb4da97987fd9ce64eb130ba41183f24b0` | no — separate queue | {"B":4,"R":7,"P":13} |
| 30 | `4948724725da96c9141da6d7ae83d9fbf1d9536c` | `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4` | `ae77412df338621c544115476ff263f86b6f4806` | `875b6da8ad28a2121488f5a91a8e1d2c7a98466e` | no — separate queue | {"B":5,"R":0,"P":0} |
| 31 | `1977b2a9d7b40a8e2502ea4555d4bbdc75708d6f` | `3658d5056354849ddf17883ed04f807f16cc44c1` | `79aff77c86528b3d0dd1efe4a4ef29b87fee1f3a` | `13817e76902ba62ea6d36c58287c5fe42a0cd149` | yes — NOT applied verdict | {"B":0,"R":0,"P":2} |
| 32 | `26ece570afb5af2f853b91aeb6d8136618c32312` | `3658d5056354849ddf17883ed04f807f16cc44c1` | `102137f1b94e128be1ad46845bf1b46e52fa81c5` | `b1cbc1ca6aef7638ef93d4e5ac3fbadad36dbd8d` | yes — NOT applied verdict | {"B":3,"R":1,"P":6} |
| 33 | `c9c8720a8e885c06618b6b345e6f63ee8b74206a` | `ad622f8a90a81e349e94d3402f297f2995e733b2` | `cf0c750be9e4b96e4d1b8ce1b8cd51674053afba` | `da42aa9b076ec017ea6cfac4377ca032728df5c1` | yes — NOT applied verdict | {"B":0,"R":3,"P":15} |
| 34 | `8e236830ca52f231e47d9c3b963a8b9c0bb38c4b` | `f3b1063449b509dd404ea60036cabf2049423f78` | `c070ffae624d439aaf3cd6a30287c692adcd19c1` | `abbc01fe8ea386c42162f33e29b57a432bba35f6` | no — separate queue | no covered T/I; U outside scope |
| 35 | `a9d199006a82f2448f348cc5ec5717257e58ee91` | `689165fbe18101feacf5f489847a4890fc27ed1f` | `b730ae71f61d1bc2ec18f3a93968bfdaf1809fa2` | `4021e040601d6aa2350137fe0254190045b2a7f0` | no — separate queue | no covered T/I; U outside scope |
| 36 | `6ddc114366c0a0b8c7bb3db6ed05dd3dd0e3b134` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `030de29cf30bdf819ddf448b6a5ee6a6523166c9` | `192dcc408aaaed86f08addae92a673e6413842bc` | no — separate queue | no covered T/I; U outside scope |
| 37 | `0e3b712ed0a9df1182bf862166faeec54c39218b` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `e5932a67cd3da67c9772cdd06cd12b84bc9ea730` | `dbc83435850cf441a238a84889b8367d180e6fd1` | yes — NOT applied verdict | no covered T/I; U outside scope |
| 38 | `032f0414b19103998196acb030106ec77e734f12` | `a7b0868ac964fd14e160001024e6e0ecaaf4e9db` | `7e07a8c5b899e644abc9800728d14712be3517bc` | `b69ce3602b6a36ec8f2a16019cf73e65061e282c` | no — separate queue | {"B":0,"R":1,"P":5} |
| 39 | `57ffaded43a46e0021008959021b828e1e955ecb` | `17d9f93f9d5eded85eee3a19dc7cb62dc554fd97` | `cfbdb635d53bee1cfc535e47aeba221b18f276dd` | `dbf736fa846d15b927de5861218a158fc37b7508` | yes — NOT applied verdict | {"B":0,"R":1,"P":0} |
| 40 | `4b54e7af38f10c676acf03b066162064db40bd13` | `a49addf6465548b9dd3c86a4581392d9426ff8d3` | `12c7bb956d0feda1898cd43584d8cf17f11aa810` | `60e16d31b9929690e36a9c0cdc40a4476723e7b9` | yes — NOT applied verdict | no covered T/I; U outside scope |
| 41 | `9148573ab1e7c51b1f18c7d988b61d92cf7c66cb` | `9a5a6e2cb977a58bb86c9eb2d44d719a7d8e9379` | `d25bff084b426afb5dadd95cab7266e8f2cfbfd6` | `869741564e5da872f9ac92d9ec74a897772d91f6` | no — separate queue | no covered T/I; U outside scope |
| 42 | `4e48862b9a0e2664e4ed1f83911b9d9feaa24e10` | `933c0129079fcc0c894a71fe842cbbb5e6ad7285` | `9a5650b564d79520ff740b1f4825f621f0e929d8` | `88f1297cd3be3e3796a3a181c73dc649d98b2dbb` | no — separate queue | {"B":10,"R":8,"P":13} |
| 43 | `3634e724f9c0184d0a46bc8b774ed85a048ddf6d` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `a069139e399172f9233f653c4171219013165ada` | `22f34739d6bbea31bc85c32d184cdf8ac48c3952` | yes — NOT applied verdict | {"B":48,"R":44,"P":95} |
| 44 | `4a492099b133e2b295e9ddf690f409fb8e78a222` | `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf` | `7c4dc8e69c2a0f69fe128dbe581ad99ce593b46a` | `61b2f25ee11549d9981615e29d9b043a7b469a6f` | no — separate queue | no covered T/I; U outside scope |

## Exhaustive original-delta / witness / hunk ledger


### D001 AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:29a49a58a68329933422f69f433bf32f2e780bd0`; original `100644:3696945f98792ca3e901e325c2522046960d2144`; pinned-current `100644:d94d4893cc9263b74e5488e2271aa7ce77f6b47d`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-22,1+22,1`, `-54,1+55,9`, `-65,1+74,1`
- L | <module/text>: `-48,0+48,1`

### D002 AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:29a49a58a68329933422f69f433bf32f2e780bd0`; original `100644:37deb811b32e74c425570963eb9b1a1048949970`; pinned-current `100644:d94d4893cc9263b74e5488e2271aa7ce77f6b47d`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-22,1+22,1`

### D003 AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:eb8ef0e70ad0210721c251fbf5e40a0949dc3d29`; original `100644:5656ffc58f33fb5184fcbd9032ef7c45e234dd1e`; pinned-current `100644:d94d4893cc9263b74e5488e2271aa7ce77f6b47d`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-10,0+10,1`, `-11,1+12,1`, `-13,0+14,1`, `-14,0+16,11`, `-19,0+32,2`, `-39,1+54,2`, `-41,1+57,1`, `-43,4+59,1`
- U | <module/text>: `-24,1+39,1`, `-54,1+67,1`, `-56,2+69,13`, `-68,1+92,1`

### D004 CONTRIBUTING.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:71b17beb821fe8c80f528cb7bdf131cb308ad997`; original `100644:f4de9e9cfe7b6b628a264fd0b702e286ff17d174`; pinned-current `100644:bdea69dfb4b0bf353c6b364dc46fa73262539fd2`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-38,1+38,1`, `-61,1+61,1`

### D005 FEATURES.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5bae13beb8a7eb8a990b82cc3e9fb9abfafc9080`; original `100644:30fb2b47fbfa3f64e5f5341f7f0944cf6b0b6a52`; pinned-current `100644:0c608c1265452ce9fcba29ff6ec5bdd361eca4c2`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,1+6,1`, `-10,3+10,2`

### D006 MANIFEST.in

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f1a531a407ad20c60d80735fb75612598ac5fde9`; original `100644:971a88e397cb22e9b57a3daab24a2fde75d5d71c`; pinned-current `100644:971a88e397cb22e9b57a3daab24a2fde75d5d71c`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-29,0+29,1`

### D007 README.md

Disposition: `integrated-current`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4595ae5f2fabdae4ad8033cde6811b87b8f29ec7`; original `100644:13aeb2e2c2c9af3ec76fc9d1d66ef6146aa265f5`; pinned-current `100644:13aeb2e2c2c9af3ec76fc9d1d66ef6146aa265f5`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-47,1+47,1`

### D008 THIRD_PARTY.md

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:07b66fef7c70c02413f137ac750cc6965332a331`; original `100644:d1ed2925cfab7df83ae53e2ca371db205e20505c`; pinned-current `100644:ebe44f2e20694e88ce6f3ac5ad61b3bc7b772de3`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-9,1+9,0`

### D009 browser_bridge/background.js

Disposition: `integrated-current`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a10a1e1b5b459139f13ed4b90c0ac344ddb7f58d`; original `100644:5602b36a67dbbbd510d8c94eb08128ec790b2c57`; pinned-current `100644:5602b36a67dbbbd510d8c94eb08128ec790b2c57`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-34,1+34,20`, `-54,0+73,5`, `-109,0+133,1`, `-237,1+262,1`, `-243,1+268,28`, `-245,0+297,3`

### D010 browser_bridge/background.js

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a10a1e1b5b459139f13ed4b90c0ac344ddb7f58d`; original `100644:d61429992115528f5b6896018f38c2cc48c34bed`; pinned-current `100644:5602b36a67dbbbd510d8c94eb08128ec790b2c57`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-34,1+34,15`, `-243,1+263,28`
- L | <module/text>: `-54,0+68,5`, `-109,0+128,1`, `-237,1+257,1`, `-245,0+292,3`

### D011 config.toml.example

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7c85c34b30bcaec840c5bec6f810b344b0cc990b`; original `100644:153fb9665809a1ab12df673e2a5e288370e52506`; pinned-current `100644:9aa3e5e3f7f55109429ef66a945f070e67c8fcba`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-52,1+52,1`, `-55,1+55,0`
- L | <module/text>: `-60,0+59,6`, `-61,1+66,2`, `-82,1+88,2`, `-84,2+91,1`, `-102,1+108,1`

### D012 config.toml.example

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7c85c34b30bcaec840c5bec6f810b344b0cc990b`; original `100644:900b0a10e989ff6c6821d17cfe4fb3a5a84ef2a5`; pinned-current `100644:9aa3e5e3f7f55109429ef66a945f070e67c8fcba`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-52,1+52,1`, `-55,1+55,0`
- L | <module/text>: `-102,1+101,1`

### D013 defaults.toml

Disposition: `integrated-current`. Occurrences: 22:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:762dd2faaa30688af2df88f69c966107c5364e64`; original `100644:db7bbadececfa087b7eca575998986a7137ce07b`; pinned-current `100644:db7bbadececfa087b7eca575998986a7137ce07b`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-471,0+471,1`

### D014 docs/API_COVERAGE.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c33ce4d3f4ce2e0e2fcdc5789bbb813ac416e6c1`; original `100644:b63c341bb1a56085673e37f0a42bc4c8c0c361a6`; pinned-current `100644:d4094ee94b806ab3ed3b77981a2fd29be8046a6d`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,2+3,2`
- U | <module/text>: `-6,1+6,1`, `-8,661+8,687`

### D015 docs/API_COVERAGE.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c33ce4d3f4ce2e0e2fcdc5789bbb813ac416e6c1`; original `100644:e098f850f21584476872dc56df565a80e15211db`; pinned-current `100644:d4094ee94b806ab3ed3b77981a2fd29be8046a6d`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,2+3,2`, `-6,663+6,667`

### D016 docs/ARCHITECTURE.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4d17f511ef1289c7da667dd725a6fdeb3477fbe6`; original `100644:2184d5397cae3e1062bfb72615d9847a9d4ad353`; pinned-current `100644:60e6e94ee8fe74c7fa284cef9660f285159bcba2`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-10,1+10,1`

### D017 docs/ARCHITECTURE.md

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4d17f511ef1289c7da667dd725a6fdeb3477fbe6`; original `100644:60e6e94ee8fe74c7fa284cef9660f285159bcba2`; pinned-current `100644:60e6e94ee8fe74c7fa284cef9660f285159bcba2`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-10,1+10,1`

### D018 docs/DASHBOARD.md

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:769574c57276088035cd35821db4ead05538d24b`; original `100644:39707d772874020b6f16844d838cad337a2e3219`; pinned-current `100644:987f102a5e46559cfb5a71d4d40bed4295663cb8`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,1+5,1`

### D019 docs/DASHBOARD.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:769574c57276088035cd35821db4ead05538d24b`; original `100644:ccad476cf0458f08fb12b35036be025d6039c9e1`; pinned-current `100644:987f102a5e46559cfb5a71d4d40bed4295663cb8`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,1+5,1`

### D020 docs/DASHBOARD.md

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9aade640969d4fa36a5dc1a9d9a9ce5cd8040ea1`; original `100644:a7eeb6fe32c31b4941916ba57bdad2e9321a71ed`; pinned-current `100644:987f102a5e46559cfb5a71d4d40bed4295663cb8`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,0+12,2`

### D021 docs/FEATURE_AUDIT_V4.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2538cdd0a9a5a592ead18160f3bdaf28642c7082`; original `100644:67e07bd51f4c0ccc5ba3ab5057a66e7a5daecbdb`; pinned-current `100644:2246ac593d06eed588fac00e60ceb4d79b7aafcf`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-25,2+25,2`
- U | <module/text>: `-98,1+98,1`

### D022 docs/FEATURE_AUDIT_V4.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2538cdd0a9a5a592ead18160f3bdaf28642c7082`; original `100644:766a935ebdc5170d172468291bf654de8c4fbc8e`; pinned-current `100644:2246ac593d06eed588fac00e60ceb4d79b7aafcf`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-26,1+26,1`
- L | <module/text>: `-98,1+98,1`

### D023 docs/FEATURE_AUDIT_V4.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2538cdd0a9a5a592ead18160f3bdaf28642c7082`; original `100644:8a98ab1ef51d79ddfba03f6876f21384f38d7fae`; pinned-current `100644:2246ac593d06eed588fac00e60ceb4d79b7aafcf`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-26,1+26,0`, `-98,1+97,1`

### D024 docs/HTTP_API.md

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0949ebfee923d1e99389bffd79da5b830d23d362`; original `100644:040270258d90c437e9cdecd973fc9f16096b1c2e`; pinned-current `100644:19aa510529e30040b6aef41498177614496ea985`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-11,0+11,4`
- L | <module/text>: `-41,1+45,5`

### D025 docs/HTTP_API.md

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0949ebfee923d1e99389bffd79da5b830d23d362`; original `100644:1b4c936f9501aff506925d9e2aa84bfeb5e18663`; pinned-current `100644:19aa510529e30040b6aef41498177614496ea985`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,1`, `-11,0+12,2`

### D026 docs/HTTP_API.md

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0949ebfee923d1e99389bffd79da5b830d23d362`; original `100644:49eef3736311944d1a1193278e4ac1df0343ed37`; pinned-current `100644:19aa510529e30040b6aef41498177614496ea985`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,1+6,1`, `-8,1+8,1`, `-11,0+11,2`, `-45,0+47,1`

### D027 docs/HTTP_API.md

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0949ebfee923d1e99389bffd79da5b830d23d362`; original `100644:5f9699927ab5d4219484b68dae7be90079b95c9b`; pinned-current `100644:19aa510529e30040b6aef41498177614496ea985`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-45,2+45,2`

### D028 docs/INSTALLATION.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7f77082376ee24e55aef5ea0041e635754a6f8d5`; original `100644:195fe8dc702a38cbc807c42c2fc951eeaa5bbf69`; pinned-current `100644:79b9cc87cab1b781c5de2842bb6efd6a74dec124`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-18,1+18,1`, `-29,7+29,7`, `-39,1+39,1`, `-41,1+41,1`, `-52,2+52,2`, `-56,1+56,1`

### D029 docs/INSTALLATION.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7f77082376ee24e55aef5ea0041e635754a6f8d5`; original `100644:8229ceeed58f9186864a7f30ae9f32a30628bbe9`; pinned-current `100644:79b9cc87cab1b781c5de2842bb6efd6a74dec124`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-9,0+9,4`, `-18,1+22,5`, `-29,7+37,7`, `-39,1+47,1`, `-41,1+49,1`, `-52,2+60,2`, `-56,1+64,1`
- L | <module/text>: `-14,1+18,1`

### D030 docs/INSTALLATION.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7f77082376ee24e55aef5ea0041e635754a6f8d5`; original `100644:d5d858e1457df4fc48ce4de454e3d8a97b17077e`; pinned-current `100644:79b9cc87cab1b781c5de2842bb6efd6a74dec124`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-30,23+30,3`

### D031 docs/INSTALL_PROMPT.md

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3a46076e8a2528f4ff8f1d5efb8911ea59fe37c4`; original `100644:143380ce60e665357395531441a8ab31ef5d8810`; pinned-current `100644:1536a03b12b73a9abb5f6303e8a96db9f05dc302`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-242,1+242,1`, `-244,1+244,1`, `-252,1+252,1`

### D032 docs/INSTALL_PROMPT.md

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ae95f87fc2cb0ff38a202492ad75278dfb7e49c0`; original `100644:4bedc078b3e1c1440b3f7a70a2011758debdfa15`; pinned-current `100644:1536a03b12b73a9abb5f6303e8a96db9f05dc302`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-114,0+114,1`, `-115,1+116,1`, `-117,0+118,1`, `-118,0+120,11`, `-123,0+136,2`, `-128,1+143,1`, `-145,1+161,1`, `-147,4+163,1`, `-160,2+173,13`, `-172,1+196,1`
- L | <module/text>: `-143,1+158,2`, `-158,1+171,1`

### D033 docs/INSTALL_PROMPT.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e23d4b77acb91179edae437488e6a98ad01ec076`; original `100644:24389b1d2deda778c80e4fe7dc4fbb8f5235454e`; pinned-current `100644:1536a03b12b73a9abb5f6303e8a96db9f05dc302`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,6`, `-36,1+44,5`, `-53,0+67,10`, `-114,1+141,1`, `-117,0+144,2`, `-125,1+154,1`, `-146,1+175,1`, `-161,1+190,2`, `-234,1+266,87`
- L | <module/text>: `-32,0+38,2`, `-42,1+54,1`, `-46,1+58,1`, `-51,0+63,2`, `-54,0+78,2`, `-60,1+86,1`, `-109,0+135,1`, `-127,1+156,1`, `-167,1+197,1`, `-178,1+208,1`, `-207,0+237,2`

### D034 docs/MCP_AND_AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:288d47ab18b11a74373176fd98762fbfa32bdb07`; original `100644:bfd09ff36b001f1b5cf45cf926280e9f2b2fc889`; pinned-current `100644:f2c0ae38231d69fbc8e42792c3d1f40507f73d79`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-44,1+44,1`
- U | <module/text>: `-62,1+62,1`

### D035 docs/MCP_AND_AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:288d47ab18b11a74373176fd98762fbfa32bdb07`; original `100644:f033d512ae82faa45fb5af5b16009fdb0f07aea2`; pinned-current `100644:f2c0ae38231d69fbc8e42792c3d1f40507f73d79`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-44,1+44,1`, `-62,1+62,1`

### D036 docs/MCP_AND_AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:288d47ab18b11a74373176fd98762fbfa32bdb07`; original `100644:f07d61fc1a771574b43176f3775146147c42ef57`; pinned-current `100644:f2c0ae38231d69fbc8e42792c3d1f40507f73d79`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,1+3,7`, `-44,1+50,1`, `-62,1+68,1`
- L | <module/text>: `-66,1+72,1`, `-85,0+91,10`

### D037 docs/MCP_AND_AGENTS.md

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:de8bd521b75a56e8a863d9e600c9afe62e12b808`; original `100644:8dd9094de633579f3653a164ed076e68103bcb3b`; pinned-current `100644:f2c0ae38231d69fbc8e42792c3d1f40507f73d79`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`
- L | <module/text>: `-46,1+47,1`, `-54,1+55,1`

### D038 docs/MODEL_CAPABILITIES.md

Disposition: `integrated-current`. Occurrences: 3:T/M, 42:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:51dce37c8f94941f5cdefe77ee8ba973f31e6d5f`; original `100644:a8d204000cd99edf038e54e95ecb264f2d095e88`; pinned-current `100644:a8d204000cd99edf038e54e95ecb264f2d095e88`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-18,1+18,1`, `-20,3+20,3`, `-25,2+25,3`

### D039 docs/OPERATIONS.md

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:61b2708255ff04af711781768d610cc2df66b84f`; original `100644:50654f33d04e888f3cd26591a5a5b1756c521a69`; pinned-current `100644:50654f33d04e888f3cd26591a5a5b1756c521a69`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,1+3,1`, `-5,1+5,74`, `-29,1+102,1`, `-42,0+115,36`

### D040 docs/PROJECT_CONFIGURATION.md

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7ce402be2a4ceb2d5b7c773872bda947ffc24f60`; original `100644:2303c8ad9d907a17e13061321be39e4d846ab1c5`; pinned-current `100644:c1c1060d5be9c16ea6f79b01f94a8fb1ee13a6f3`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,1+3,1`, `-6,3+6,6`
- U | <module/text>: `-22,1+25,1`, `-54,2+57,1`, `-65,1+67,1`, `-101,1+103,1`, `-103,1+105,5`, `-107,1+113,1`

### D041 docs/PROJECT_CONFIGURATION.md

Disposition: `preserved-only-needs-integration`. Occurrences: 12:T/M, 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7ce402be2a4ceb2d5b7c773872bda947ffc24f60`; original `100644:3a76e6837e5d8774f2f8dbdcc3c16f109a388450`; pinned-current `100644:c1c1060d5be9c16ea6f79b01f94a8fb1ee13a6f3`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,3+6,6`, `-20,2+23,2`, `-66,0+68,2`, `-103,1+107,1`
- L | <module/text>: `-54,2+57,1`, `-93,1+97,1`, `-107,1+111,1`

### D042 docs/PROJECT_CONFIGURATION.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7ce402be2a4ceb2d5b7c773872bda947ffc24f60`; original `100644:bd7efa18c8fef931f154a4fb01526bc69c0f6487`; pinned-current `100644:c1c1060d5be9c16ea6f79b01f94a8fb1ee13a6f3`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,3+6,6`, `-66,0+68,4`, `-103,1+109,1`
- L | <module/text>: `-20,3+23,3`, `-54,2+57,1`, `-93,1+99,1`, `-107,1+113,1`

### D043 docs/SECURITY_MODEL.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:90b5578af957b5d11945c5de6d2f5606b34874f9`; original `100644:bc584589127cd4a46be559c58182554aae51ca7f`; pinned-current `100644:4b5554696ef1ea704c8c634135c32ab9b8f35472`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,1+3,1`, `-7,1+7,1`
- U | <module/text>: `-9,1+9,1`, `-11,1+11,1`, `-13,1+13,1`, `-17,1+17,1`

### D044 docs/TROUBLESHOOTING.md

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c279d471b05599514790c140a861233af702cd00`; original `100644:247fd8dc4847080779aca3a9560759dbd32bbf18`; pinned-current `100644:247fd8dc4847080779aca3a9560759dbd32bbf18`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-4,1+4,1`, `-6,1+6,6`, `-16,1+21,1`

### D045 docs/UPDATE_PROMPT.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ba1311f5576bf23f489db7b14a5eba5b0d63cead`; original `100644:44eeb55efba49157e4664d210e7f827bffd4a204`; pinned-current `100644:45ecad014ed41bfaa3aff2007255ec67005e4c8a`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,1+5,6`, `-43,1+50,5`, `-56,1+67,1`, `-58,10+69,15`, `-106,1+123,2`, `-109,1+127,1`, `-138,1+156,89`
- L | <module/text>: `-20,1+25,3`, `-28,3+35,3`, `-33,2+40,3`, `-36,2+44,1`, `-47,1+58,1`, `-51,1+62,1`, `-71,2+87,2`, `-81,0+97,1`

### D046 docs/UPDATE_PROMPT.md

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d4a2288cb0c37459f8b10756745d54fb170a3e65`; original `100644:ae13143fe7dd92aaea666c3788e884abcb8cb8ee`; pinned-current `100644:45ecad014ed41bfaa3aff2007255ec67005e4c8a`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-107,1+107,1`, `-150,0+150,1`, `-151,1+152,1`, `-153,0+154,1`, `-154,0+156,11`, `-159,0+172,2`, `-164,1+179,1`, `-179,1+194,2`, `-181,1+197,1`, `-183,4+199,1`, `-194,1+207,1`, `-196,2+209,13`, `-208,1+232,1`

### D047 docs/UPDATE_PROMPT.md

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e1d3daab214b9e7d741d91d33955a6a04ffe8274`; original `100644:4f5fec97b139b4073e771e56287d28147f0da705`; pinned-current `100644:45ecad014ed41bfaa3aff2007255ec67005e4c8a`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-144,1+144,1`, `-146,1+146,1`, `-154,1+154,1`

### D048 docs/superpowers/plans/2026-09-21-hub-audit-hardening.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0684f79bf673f5f9f9df339939e34d2d73b6b2b9`; original `100644:c334273dab445bc7fd016ea2670176abbd744573`; pinned-current `100644:6d0e3a4b04f851ff39911272b1f11f288097daa5`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-32,1+32,1`

### D049 docs/superpowers/plans/2026-09-21-v4-perfection-hardening.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bb2bcb6ec0a6bb1ac4c26eec00b21f139b55a078`; original `100644:cf9c1840fe2c6bc7b6504983761dfd7871cd2fa4`; pinned-current `100644:354b1842f1bbf394bc9721b5aa9d2e699e357462`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-45,1+45,1`

### D050 docs/superpowers/plans/2026-09-22-adaptive-retrieval-orchestrator.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:be35b9ec1987ab76c0e00f315ef8f0dc2b98a90c`; original `100644:bb9d172cb00fa9e2fe4a8eecd95e3fcec777dd31`; pinned-current `100644:27773672a4503d6f78fe4ae2e4b2c9fa2c038359`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-2,0+2,2`
- L | <module/text>: `-7,1+9,1`, `-23,1+25,1`, `-75,1+77,1`, `-106,1+108,1`

### D051 docs/superpowers/plans/2026-09-22-adaptive-retrieval-orchestrator.md

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:be35b9ec1987ab76c0e00f315ef8f0dc2b98a90c`; original `100644:d6364b6a15ccd64963e144cc91851d21ce6f7c7b`; pinned-current `100644:27773672a4503d6f78fe4ae2e4b2c9fa2c038359`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-2,0+2,2`

### D052 docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e97baed966fa692f2303d302a4e62da39b04798`; original `100644:9e86879098214dc5c472f703d55d564cd170e298`; pinned-current `100644:a7d6cb1e5cc44d11d0f24ecaaf38499fc9ecb92a`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-9,1+9,1`, `-46,3+46,4`, `-54,0+55,1`, `-56,0+58,93`, `-120,1+215,1`, `-123,0+218,2`, `-125,1+222,1`, `-130,0+227,2`, `-138,0+237,1`, `-159,0+263,3`, `-174,0+289,9`, `-186,0+310,1`, `-188,0+313,8`, `-196,0+329,1`, `-201,0+335,6`, `-223,1+363,10`, `-248,1+397,1`, `-251,0+400,2`, `-271,0+426,1`, `-290,0+446,8`, `-312,0+480,2`, `-327,0+497,5`, `-340,0+515,4`, `-350,0+529,2`, `-368,1+549,1`, `-373,0+554,2`, `-377,0+560,10`, `-393,1+586,1`, `-423,2+632,2`, `-459,1+668,2`, `-466,0+676,1`, `-468,0+679,1`
- U | <module/text>: `-153,0+253,4`, `-164,0+271,8`, `-263,0+414,4`, `-302,0+466,4`, `-391,1+584,1`, `-395,10+588,14`, `-406,1+603,13`, `-471,1+683,1470`

### D053 docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md

Disposition: `preserved-only-needs-integration`. Occurrences: 38:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f4113c10e36bb690ce37053670301835fb3f4fe1`; original `100644:10f8c35f2b47f087d8e5a561faf890a086cb64b2`; pinned-current `100644:a7d6cb1e5cc44d11d0f24ecaaf38499fc9ecb92a`.

Exact checkpoint/owner witnesses: `S002 / 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-152,0+152,2`

### D054 docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f4113c10e36bb690ce37053670301835fb3f4fe1`; original `100644:bbdc4d9a841a3d9cb1926631337693eebf2e99b3`; pinned-current `100644:a7d6cb1e5cc44d11d0f24ecaaf38499fc9ecb92a`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-9,1+9,1`, `-248,1+248,1`, `-359,1+359,1`

### D055 docs/superpowers/plans/2026-09-26-t04-end-to-end.md

Disposition: `integrated-current`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:75127a1dadf770b00eea133ed49b7312df1a6cf8`; original `100644:69e63ef50a589f46c6c169fe25d8721308c7e3e1`; pinned-current `100644:69e63ef50a589f46c6c169fe25d8721308c7e3e1`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-77,1+77,1`, `-92,1+92,1`, `-110,0+110,129`

### D056 docs/superpowers/specs/2026-09-25-t21-adapter-handoff.md

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ec3aa0bd185a4e06196888802e2d0564b35a0bbf`; original `100644:19b6d17db4558a68701f605dd535f46d92389bf4`; pinned-current `100644:de0abad21083bf99a7b4f1668f6c26430dc17c2b`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,1+3,3`, `-71,1+79,8`, `-74,0+89,6`, `-137,1+160,1`, `-173,0+198,106`
- U | <module/text>: `-52,0+54,6`, `-83,0+104,2`, `-87,2+110,2`, `-109,1+132,1`, `-132,1+155,1`, `-151,3+174,4`, `-159,0+183,1`

### D057 docs/superpowers/specs/2026-09-25-t21-adapter-handoff.md

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ec3aa0bd185a4e06196888802e2d0564b35a0bbf`; original `100644:917fee4d162cb89387724d6038dd72793c234b60`; pinned-current `100644:de0abad21083bf99a7b4f1668f6c26430dc17c2b`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-25,1+25,19`, `-39,1+57,1`, `-43,1+61,1`, `-67,1+85,1`, `-95,3+123,4`, `-99,4+128,5`, `-116,3+148,2`, `-127,1+158,1`, `-144,1+174,1`
- U | <module/text>: `-50,1+68,1`, `-54,1+72,1`, `-71,1+89,7`, `-81,2+105,4`, `-85,1+111,2`, `-87,0+114,1`, `-106,1+136,1`, `-111,1+141,3`, `-129,1+160,1`, `-131,8+162,7`, `-149,1+179,1`, `-152,2+182,2`, `-157,1+187,1`, `-161,1+191,1`, `-173,0+203,38`

### D058 install.ps1

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:599e56f263819681ca24e795e24cc2d726f0f10a`; original `100644:ae70ac61dd6b9ffb4a21e851c84fdf74e996dd71`; pinned-current `100644:ae70ac61dd6b9ffb4a21e851c84fdf74e996dd71`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,3`, `-17,0+20,10`, `-68,1+81,1`

### D059 install.sh

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f811dd763bd0819ad869c73acb500776b87af139`; original `100644:939e80f438fa44eda157e459039201dd7301b536`; pinned-current `100644:939e80f438fa44eda157e459039201dd7301b536`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-6,0+6,1`, `-11,0+12,1`, `-14,1+16,1`, `-18,0+20,15`, `-80,1+97,1`

### D060 pyproject.toml

Disposition: `integrated-current`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9c9942b50fd40c449ce7d1008ce6884c06f54850`; original `100644:cae6f8588369c4748d9eabba937e06ede8c79511`; pinned-current `100644:cae6f8588369c4748d9eabba937e06ede8c79511`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-30,0+30,1`

### D061 skills/tool-orchestration/SKILL.md

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:dce5ff838c6e60706627da028e00699cd9d6bce1`; original `100644:3a3165bed2790c599b39ebe251267382d2a8f211`; pinned-current `100644:5b0ac69e2009b5d43a9a5203247a35dae138f15d`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-22,1+22,1`

### D062 skills/tool-orchestration/SKILL.md

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:dce5ff838c6e60706627da028e00699cd9d6bce1`; original `100644:d3e601e8d3fc6e3a44cabea23ce3aa343875b473`; pinned-current `100644:5b0ac69e2009b5d43a9a5203247a35dae138f15d`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-64,0+64,8`

### D063 src/local_ai_hub/agent_blackboard.py

Disposition: `integrated-current`. Occurrences: 26:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:02a837466c11e4024e800e9602e2c53b8635798c`; original `100644:a85be25c2fe6481afff52100ee3423fc60a40e06`; pinned-current `100644:a85be25c2fe6481afff52100ee3423fc60a40e06`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-5,0+5,1`, `-9,1+10,1`, `-14,1+15,2`
- B | BlackboardStore.__init__: `-90,1+92,1`, `-92,0+94,1`
- B | BlackboardStore._connect: `-97,2+100,1`
- B | BlackboardStore._ensure_schema: `-106,0+108,2`, `-107,0+111,9`, `-108,1+121,8`, `-123,3+143,4`
- B | BlackboardStore.update: `-137,0+158,3`, `-138,1+162,1`, `-143,0+167,5`
- B | BlackboardStore.update._do_update: `-146,5+175,15`
- B | BlackboardStore: `-152,3+191,64`
- B | BlackboardStore._update_in_transaction: `-156,2+256,31`, `-159,9+288,8`, `-169,5+297,61`, `-175,35+359,26`
- B | BlackboardStore.merge._do_merge: `-279,0+454,1`, `-281,0+457,2`, `-325,0+503,20`, `-326,2+524,9`
- B | BlackboardStore.merge: `-329,1+534,10`
- B | BlackboardStore.delete._do_delete: `-338,0+552,1`, `-339,14+554,47`, `-358,0+606,2`
- B | BlackboardStore.delete: `-359,1+609,11`

### D064 src/local_ai_hub/agent_consistency.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2cf16682457271286b14246f0033b73dd1728a02`; original `100644:2de44d75df3e25acc702ca551260895839b95e83`; pinned-current `100644:c7d80da95ac742b38ea9b84c8fd45cd245556023`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | ConsistencyRequest: `-278,0+278,1`
- L | ConsistencyRequest.__post_init__: `-296,0+297,8`
- U | ConsistencyRequest.to_dict: `-307,0+316,1`

### D065 src/local_ai_hub/agent_consistency.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2cf16682457271286b14246f0033b73dd1728a02`; original `100644:53d12751dbbd0c8481a766e038308b78d45328f3`; pinned-current `100644:c7d80da95ac742b38ea9b84c8fd45cd245556023`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | AgentConsistencyGuard.record_validation: `-733,0+733,1`
- U | AgentConsistencyGuard.record_validation: `-750,0+751,9`, `-757,10+767,8`

### D066 src/local_ai_hub/agent_consistency.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2cf16682457271286b14246f0033b73dd1728a02`; original `100644:c7d80da95ac742b38ea9b84c8fd45cd245556023`; pinned-current `100644:c7d80da95ac742b38ea9b84c8fd45cd245556023`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-19,1+19,1`, `-132,0+132,72`
- B | ConsistencyRequest: `-273,0+345,4`, `-278,0+354,1`
- B | ConsistencyRequest.__post_init__: `-291,0+368,4`, `-296,0+377,8`
- B | ConsistencyRequest.to_dict: `-305,1+394,4`, `-307,0+399,1`
- B | AgentConsistencyGuard.record_validation: `-733,0+826,1`, `-750,0+844,16`, `-757,10+867,0`

### D067 src/local_ai_hub/agent_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0150eaf9deebd86628fdca005e7b2de3853f9d7e`; original `100644:6e7234b0f9f774feab364eec4d3691496944d660`; pinned-current `100644:977592f55bda98d32bff6d5827edfd4f74199821`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | ContextRequest: `-41,0+41,1`
- L | ContextCompiler.compile: `-860,2+861,5`

### D068 src/local_ai_hub/agent_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0150eaf9deebd86628fdca005e7b2de3853f9d7e`; original `100644:6ec3b7167889f82a2290600dc4deed9a2891ecde`; pinned-current `100644:977592f55bda98d32bff6d5827edfd4f74199821`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,1`, `-18,0+19,6`, `-155,0+173,18`
- U | ContextRequest: `-41,0+48,3`
- L | CompiledContext: `-90,0+100,1`
- U | CompiledContext.etag: `-98,0+109,1`, `-99,2+111,8`
- A | ContextCompiler.__init__: `-178,1+214,1`
- U | ContextCompiler.link._do_save: `-261,1+297,6`, `-264,2+305,6`
- U | ContextCompiler.invalidate._do_invalidate: `-330,1+375,6`, `-333,2+383,6`
- L | ContextCompiler: `-376,0+430,3`, `-388,0+445,15`
- A | ContextCompiler._preload_settings: `-381,1+438,1`
- A | ContextCompiler._load_preloads: `-484,1+556,2`, `-491,17+564,30`
- L | ContextCompiler.compile: `-558,0+644,30`, `-684,1+800,1`, `-701,0+826,5`, `-720,0+850,1`, `-870,1+1001,6`, `-878,2+1014,4`, `-946,0+1091,1`, `-961,1+1107,6`, `-979,1+1130,1`
- U | ContextCompiler.compile: `-687,9+803,18`, `-881,0+1019,7`

### D069 src/local_ai_hub/agent_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0150eaf9deebd86628fdca005e7b2de3853f9d7e`; original `100644:751cbc1c271c6c25c01ec1954f27226307e69743`; pinned-current `100644:977592f55bda98d32bff6d5827edfd4f74199821`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-41,0+41,21`
- U | CompiledContext: `-90,0+111,1`
- U | CompiledContext.etag: `-96,0+118,1`
- A | ContextCompiler.__init__: `-178,1+201,1`
- U | ContextCompiler.compile: `-946,0+969,1`, `-963,14+987,20`, `-979,1+1009,1`

### D070 src/local_ai_hub/agent_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0150eaf9deebd86628fdca005e7b2de3853f9d7e`; original `100644:89d6472f67e403ea5e328e8972c39d7c4b7501df`; pinned-current `100644:977592f55bda98d32bff6d5827edfd4f74199821`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,1`
- U | ContextRequest: `-41,0+42,1`
- U | CompiledContext.etag: `-98,0+100,8`, `-99,2+109,2`
- L | <module/text>: `-154,0+164,28`
- A | ContextCompiler.link._do_save: `-261,5+299,7`
- A | ContextCompiler.invalidate._do_invalidate: `-330,5+370,7`
- L | ContextCompiler._load_preloads: `-484,1+526,2`
- U | ContextCompiler._load_preloads: `-493,0+536,7`
- U | ContextCompiler.compile: `-684,1+734,1`, `-691,0+741,1`, `-694,0+745,1`
- L | ContextCompiler.compile: `-701,0+753,5`, `-720,0+777,1`, `-870,1+928,6`, `-878,2+941,4`, `-881,0+946,7`, `-883,2+955,6`

### D071 src/local_ai_hub/agent_events.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:58739d20da0cfb43ad06121a5f49a2ab97d3bc03`; original `100644:4d4eab3997c4901afd9baf09aa8d1fd784a18c64`; pinned-current `100644:27f67f26b1ce668a4ed816d3c6f9604368d27ed4`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AgentStateStore: `-292,0+292,73`
- U | AgentStateStore.event_page: `-350,1+423,1`, `-369,1+442,1`, `-372,0+445,2`, `-380,2+455,27`, `-385,1+485,1`, `-388,1+488,0`, `-390,1+489,19`, `-401,0+518,2`

### D072 src/local_ai_hub/agent_events.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a828a898759b0d3a2a13c6ca7306e9c4f00764b6`; original `100644:27e122ef3f88746a8568c12d42bb9b250ccf8b09`; pinned-current `100644:27f67f26b1ce668a4ed816d3c6f9604368d27ed4`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AgentStateStore.__init__: `-238,1+238,1`
- L | AgentStateStore._preflight_schema_read_only: `-444,1+444,1`
- L | AgentStateStore._classify_schema: `-456,1+456,1`, `-533,0+546,3`
- U | AgentStateStore._classify_schema: `-512,0+512,13`

### D073 src/local_ai_hub/agent_events.py

Disposition: `preserved-only-needs-integration`. Occurrences: 25:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a828a898759b0d3a2a13c6ca7306e9c4f00764b6`; original `100644:8f7af66b350b7f57fb9d44b6497281ea240b1bce`; pinned-current `100644:27f67f26b1ce668a4ed816d3c6f9604368d27ed4`.

Exact checkpoint/owner witnesses: `S017 / 281cf99b1d7bf265d06a315bbadf168bef4d1ac5 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AgentStateStore: `-210,0+210,3`
- L | AgentStateStore._preflight_schema_read_only: `-444,1+447,1`
- L | AgentStateStore._classify_schema: `-456,1+459,1`, `-533,0+549,3`
- U | AgentStateStore._classify_schema: `-512,0+515,13`

### D074 src/local_ai_hub/agent_events.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:aca718201f0f8975e5b5ee94251e3ae800a6111e`; original `100644:2e56bc226e69d7cc9250a4a360c6af6bc53277e1`; pinned-current `100644:27f67f26b1ce668a4ed816d3c6f9604368d27ed4`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,2+3,2`, `-6,0+6,1`, `-7,0+8,4`, `-12,1+17,1`, `-14,2+19,8`
- U | AgentStateStore: `-120,0+131,100`, `-212,1+379,777`, `-348,1+1409,32`
- U | AgentStateStore.__init__: `-131,0+242,5`
- A | AgentStateStore._ensure_schema: `-150,12+266,18`, `-164,1+286,4`, `-166,12+291,6`, `-180,13+299,13`, `-194,2+313,8`, `-197,7+322,7`, `-205,1+330,43`
- A | AgentStateStore.append: `-215,1+1158,0`, `-221,1+1163,0`, `-283,4+1186,5`
- A | AgentStateStore.append._do_append: `-225,2+1166,0`, `-230,37+1169,2`, `-269,2+1173,1`
- A | AgentStateStore._publish: `-311,0+1215,58`, `-312,8+1274,3`, `-322,0+1279,3`
- U | AgentStateStore.event_page: `-330,1+1290,23`, `-332,3+1314,11`, `-344,1+1369,37`, `-346,1+1407,1`
- L | AgentStateStore.event_page: `-336,1+1326,36`, `-340,1+1365,1`
- A | AgentStateStore.cleanup._do_cleanup: `-427,2+1519,47`
- L | SwarmPubSub: `-495,1+1632,1`, `-543,2+1676,67`, `-580,18+1888,0`
- A | SwarmPubSub.get_default: `-512,1+1649,1`
- A | SwarmPubSub.subscribe: `-517,1+1654,0`, `-522,3+1658,1`
- A | SwarmPubSub.unsubscribe: `-528,1+1662,0`
- A | SwarmPubSub._prune_expired_locked: `-539,3+1672,3`
- U | SwarmPubSub.publish: `-548,0+1746,50`
- L | SwarmPubSub.publish: `-549,1+1797,1`, `-554,0+1802,2`, `-556,9+1806,4`, `-566,0+1811,14`
- U | SwarmPubSub.poll: `-567,12+1826,61`, `-601,1+1891,4`
- L | SwarmPubSub.poll: `-605,2+1898,14`

### D075 src/local_ai_hub/agent_events.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:aca718201f0f8975e5b5ee94251e3ae800a6111e`; original `100644:8f7af66b350b7f57fb9d44b6497281ea240b1bce`; pinned-current `100644:27f67f26b1ce668a4ed816d3c6f9604368d27ed4`.

Exact checkpoint/owner witnesses: `S017 / 281cf99b1d7bf265d06a315bbadf168bef4d1ac5 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,6`, `-12,1+20,1`
- L | <module/text>: `-6,0+12,1`, `-7,0+14,1`
- U | AgentStateStore: `-120,0+128,100`, `-212,1+344,813`, `-329,0+1234,156`
- U | AgentStateStore.__init__: `-130,0+238,5`
- U | AgentStateStore._ensure_schema: `-155,7+268,1`, `-164,0+271,3`, `-166,1+276,4`, `-173,5+286,11`, `-206,0+325,13`
- A | AgentStateStore.append: `-215,1+1159,0`, `-221,1+1164,0`, `-283,4+1187,5`
- A | AgentStateStore.append._do_append: `-225,2+1167,0`, `-230,37+1170,2`, `-269,2+1174,1`
- U | AgentStateStore.cleanup._do_cleanup: `-429,0+1490,7`

### D076 src/local_ai_hub/agent_events.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:aca718201f0f8975e5b5ee94251e3ae800a6111e`; original `100644:fe6b6a234e990c05b471f84a3f637db02b4c71dd`; pinned-current `100644:27f67f26b1ce668a4ed816d3c6f9604368d27ed4`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AgentStateStore._publish: `-304,0+304,1`, `-305,13+306,1`, `-320,0+309,77`, `-322,7+388,3`
- U | AgentStateStore: `-349,0+411,91`

### D077 src/local_ai_hub/agent_incidents.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b4c4abf618a5a533a983e2b90f2b95fc3c5dc00`; original `100644:882fa9fcda05ee79440029780d9c9d3373687931`; pinned-current `100644:fae29711a82c3e145ca1c7788aa6eac1c3753f65`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-13,0+14,1`, `-17,0+19,13`
- A | ToolOutcome: `-54,0+69,2`
- A | IncidentRecord: `-75,0+92,2`
- A | IncidentRecord.to_dict: `-102,0+121,4`
- A | IncidentStore._init_table: `-250,4+273,0`, `-271,0+290,2`, `-272,3+293,12`, `-294,1+324,3`, `-314,0+346,6`
- A | IncidentStore.capture: `-342,0+380,6`, `-396,0+442,2`, `-424,0+472,2`
- A | IncidentStore.capture._fetch_existing: `-363,1+407,2`, `-366,0+411,1`, `-368,1+414,1`
- A | IncidentStore.resolve: `-468,0+518,2`
- A | IncidentStore.get._fetch_record: `-618,1+670,2`
- A | IncidentStore.list_incidents._fetch_list: `-653,1+706,1`, `-655,1+708,1`, `-657,1+710,1`, `-664,1+717,2`
- A | IncidentStore._save_record._do_save: `-706,2+760,3`, `-720,1+775,3`, `-740,0+797,2`
- A | IncidentStore._row_to_record: `-774,0+833,2`, `-798,0+859,2`
- L | IncidentStore.find_negative_knowledge: `-866,1+929,10`, `-870,0+942,9`, `-909,1+996,1`
- U | IncidentStore.find_negative_knowledge: `-873,1+954,1`, `-878,1+959,2`, `-881,0+963,1`, `-884,0+967,1`, `-886,1+970,2`, `-889,0+974,1`, `-891,0+977,1`, `-920,1+1007,7`

### D078 src/local_ai_hub/agent_incidents.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b4c4abf618a5a533a983e2b90f2b95fc3c5dc00`; original `100644:9650f64cebe9b5d1d85bc546a75d3aeb0baf0286`; pinned-current `100644:fae29711a82c3e145ca1c7788aa6eac1c3753f65`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-13,0+14,1`, `-17,0+19,13`
- A | ToolOutcome: `-54,0+69,2`
- A | IncidentRecord: `-75,0+92,2`
- A | IncidentRecord.to_dict: `-102,0+121,4`
- L | IncidentStore._init_table: `-250,4+273,0`, `-271,0+290,2`, `-294,1+324,3`, `-314,0+346,6`
- U | IncidentStore._init_table: `-272,3+293,12`
- A | IncidentStore.capture: `-342,0+380,6`, `-396,0+442,2`, `-424,0+472,2`
- A | IncidentStore.capture._fetch_existing: `-363,1+407,2`, `-366,0+411,1`, `-368,1+414,1`
- A | IncidentStore.resolve: `-468,0+518,2`
- A | IncidentStore.get._fetch_record: `-618,1+670,2`
- A | IncidentStore.list_incidents._fetch_list: `-653,1+706,1`, `-655,1+708,1`, `-657,1+710,1`, `-664,1+717,2`
- A | IncidentStore._save_record._do_save: `-706,2+760,3`, `-720,1+775,3`, `-740,0+797,2`
- A | IncidentStore._row_to_record: `-774,0+833,2`, `-798,0+859,2`
- A | IncidentStore.find_regressions: `-814,1+877,3`
- L | IncidentStore.find_negative_knowledge: `-866,1+931,10`, `-878,1+959,1`, `-880,1+961,1`, `-884,0+965,1`, `-886,1+968,2`, `-889,0+972,1`, `-890,1+974,2`, `-909,1+994,1`, `-920,1+1005,6`
- U | IncidentStore.find_negative_knowledge: `-870,0+944,7`

### D079 src/local_ai_hub/agent_incidents.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d24ea5d5549e23d049939db2e7a46cb0ef8b526a`; original `100644:eb7cd52611f84a6f27a2dbb385dd597b99a8e1f9`; pinned-current `100644:fae29711a82c3e145ca1c7788aa6eac1c3753f65`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | IncidentStore.resolve_all: `-508,0+508,1`, `-534,1+535,1`, `-537,1+538,1`, `-553,0+554,1`, `-554,3+556,4`

### D080 src/local_ai_hub/agent_memory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c53e05b814e46bbac63b2f65aa87fab5d29fbca0`; original `100644:04c974c3ac9f542ab623dcc08104be92556322f4`; pinned-current `100644:e14fa4a4fa373d484213a1cba0f745992a7ea3f7`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-9,0+10,1`, `-118,0+168,14`, `-396,0+493,103`
- U | <module/text>: `-54,0+56,27`
- A | _memory_matches_request_scope: `-66,0+95,1`, `-72,4+102,8`, `-77,1+111,12`, `-79,1+124,6`
- A | _memory_conflict_context_matches: `-103,3+153,3`
- U | _context_scope_sql: `-136,0+200,1`, `-140,1+205,8`, `-147,17+220,41`
- L | _context_scope_sql: `-142,4+214,5`
- A | MemoryRecord.from_dict: `-386,1+483,1`
- A | MemoryStore.record: `-569,0+769,1`, `-570,1+771,0`, `-580,0+780,1`
- A | MemoryStore._record_event_and_save._do_record: `-598,14+799,9`, `-613,4+809,2`, `-618,1+812,1`, `-620,5+814,50`, `-626,42+865,2`
- A | MemoryStore._record_event_and_save: `-677,0+876,1`, `-682,2+882,0`
- L | MemoryStore.promote: `-771,0+969,10`, `-772,1+980,15`, `-775,3+997,0`
- U | MemoryStore.quarantine: `-797,0+1016,8`, `-798,2+1025,12`
- L | MemoryStore.quarantine: `-801,0+1038,5`, `-802,7+1044,66`, `-810,2+1111,0`
- A | MemoryStore.mark_stale_for_revision._mark_batch: `-915,4+1214,5`, `-920,59+1220,14`, `-980,4+1235,3`, `-986,9+1240,8`, `-997,3+1250,29`
- A | MemoryStore.mark_stale_for_revision: `-1010,3+1289,1`
- U | MemoryStore.diagnostic_summary: `-1022,0+1299,1`
- L | MemoryStore.diagnostic_summary: `-1040,1+1318,1`, `-1056,0+1334,1`
- L | MemoryStore.get: `-1116,0+1395,1`, `-1118,0+1398,14`, `-1136,0+1430,1`, `-1153,0+1448,9`
- L | MemoryStore.find_for_context: `-1166,0+1470,1`, `-1180,0+1485,1`
- U | MemoryStore.find_for_context: `-1188,1+1494,1`
- L | MemoryStore.find: `-1232,0+1538,1`, `-1309,2+1616,1`, `-1340,3+1646,9`, `-1363,0+1675,3`, `-1370,6+1685,19`, `-1377,0+1705,15`, `-1407,1+1750,1`, `-1447,1+1790,1`, `-1452,2+1795,1`
- L | MemoryStore: `-1481,0+1823,16`
- A | MemoryStore.reap_expired: `-1525,2+1883,2`, `-1528,9+1886,41`, `-1538,1+1928,1`, `-1540,1+1930,1`, `-1542,9+1932,19`, `-1553,1+1953,2`
- A | MemoryStore._save_record_row: `-1589,0+1990,1`, `-1635,9+2037,11`
- A | MemoryStore._row_to_record: `-1676,1+2080,1`
- L | MemoryStore.delete: `-1687,1+2091,59`
- U | MemoryStore.delete: `-1691,14+2153,100`
- L | MemoryStore.compact: `-1720,1+2268,21`, `-1728,1+2296,1`, `-1730,1+2298,2`, `-1735,1+2304,1`, `-1743,1+2312,12`, `-1765,0+2345,1`, `-1768,0+2349,1`
- U | MemoryStore.compact: `-1773,1+2355,74`, `-1775,25+2430,0`

### D081 src/local_ai_hub/agent_memory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c53e05b814e46bbac63b2f65aa87fab5d29fbca0`; original `100644:689d91b6dc151075d8b97eb4cc42c4b65c56b770`; pinned-current `100644:e14fa4a4fa373d484213a1cba0f745992a7ea3f7`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`
- U | <module/text>: `-56,0+57,18`
- L | _context_scope_sql: `-136,0+155,1`, `-139,0+159,1`, `-140,1+161,8`, `-142,4+170,5`
- U | _context_scope_sql: `-147,17+176,59`
- A | MemoryStore._init_table: `-417,0+488,32`
- U | MemoryStore._record_event_and_save._do_record: `-611,0+714,5`, `-625,0+733,3`, `-628,0+739,2`, `-641,23+754,2`, `-665,0+757,4`, `-667,1+763,1`
- U | MemoryStore._record_event_and_save: `-677,7+773,8`
- A | MemoryStore._auto_link_record: `-723,1+820,1`, `-725,4+822,4`, `-731,31+828,0`
- U | MemoryStore: `-764,0+830,25`, `-1587,0+1717,66`
- L | MemoryStore.promote: `-771,0+862,10`, `-775,3+891,0`
- U | MemoryStore.promote: `-772,1+873,16`, `-787,3+900,1`
- U | MemoryStore.quarantine: `-807,1+918,1`, `-810,3+921,1`
- U | MemoryStore.mark_stale_for_revision._mark_batch: `-965,33+1074,5`
- U | MemoryStore.mark_stale_for_revision: `-1010,3+1091,4`
- L | MemoryStore.diagnostic_summary: `-1021,0+1103,1`, `-1056,0+1139,1`
- U | MemoryStore.diagnostic_summary: `-1040,1+1123,1`
- L | MemoryStore.find_for_context: `-1166,0+1250,1`, `-1169,0+1254,1`, `-1180,0+1266,1`, `-1183,0+1270,1`
- U | MemoryStore.find: `-1340,1+1428,2`, `-1370,1+1459,3`
- U | MemoryStore.reap_expired: `-1525,2+1616,3`, `-1528,4+1620,19`, `-1533,2+1640,16`, `-1536,1+1657,1`, `-1538,13+1659,18`, `-1553,1+1679,5`
- U | MemoryStore.delete: `-1687,1+1883,55`, `-1691,14+1941,80`
- U | MemoryStore.compact: `-1728,1+2044,5`, `-1730,1+2050,7`, `-1735,1+2061,1`, `-1743,1+2069,5`, `-1771,0+2102,5`, `-1773,12+2109,19`, `-1786,3+2129,3`, `-1799,1+2142,88`
- L | MemoryStore.compact: `-1765,0+2095,1`
- A | MemoryStore.record_relation: `-1823,15+2253,0`, `-1844,1+2259,34`

### D082 src/local_ai_hub/agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fbc602e20158d5f852498f3ce77c2e6b6a4565c5`; original `100644:812c01e1ef2974e9a9f5f2f1b4e97b0823cff6d1`; pinned-current `100644:c95e6e69f62684922a8b8a57578e56f2ff135bc4`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,4`, `-8,0+12,1`, `-10,1+15,1`, `-18,0+23,5`, `-214,0+224,119`
- A | GoalContract: `-81,0+91,1`
- A | GoalContract.__post_init__: `-87,0+98,1`
- A | GoalContract.to_dict: `-100,0+112,1`
- A | GoalContract.from_dict: `-110,10+123,6`, `-126,0+135,1`
- U | TaskStore.__init__: `-225,0+354,3`
- U | TaskStore: `-228,0+360,412`, `-248,0+792,20`
- L | TaskStore._init_projection_table: `-293,0+857,1`
- A | TaskStore.create: `-307,0+872,1`, `-312,0+878,10`, `-317,1+893,13`, `-320,0+908,3`, `-322,0+913,13`
- L | TaskStore: `-367,1+971,123`, `-419,5+1216,68`, `-437,8+1297,177`, `-550,0+1620,60`
- A | TaskStore.list_tasks: `-369,1+1095,1`, `-372,1+1098,15`, `-395,1+1146,32`, `-397,3+1179,1`
- A | TaskStore.list_tasks._fetch_tasks: `-379,1+1119,1`, `-382,0+1122,12`, `-389,1+1141,0`, `-391,3+1142,3`
- A | TaskStore.add_verification_receipt: `-416,2+1196,19`
- A | TaskStore.add_verification_receipt_in_transaction: `-432,1+1292,1`, `-435,1+1295,1`
- A | TaskStore.transition: `-454,0+1483,3`, `-459,0+1491,20`, `-460,1+1512,12`, `-538,1+1601,1`, `-541,0+1604,3`, `-549,0+1615,4`
- A | TaskStore.checkpoint: `-659,0+1789,4`
- U | TaskStore.resume: `-781,0+1915,52`
- L | TaskStore.resume: `-786,1+1972,3`
- L | TaskStore.cleanup_worktree: `-828,1+2016,7`, `-835,0+2029,6`
- U | TaskStore.cleanup_worktree: `-836,5+2036,84`
- A | TaskStore.reap_expired_heartbeats: `-844,1+2123,14`, `-867,0+2159,14`, `-875,0+2181,7`
- A | TaskStore.recover_zombie_tasks: `-881,1+2194,8`, `-883,1+2203,7`
- A | TaskStore._save_projection._do_save: `-932,0+2258,1`
- A | TaskStore._commit_create: `-945,1+2272,1`, `-949,6+2276,0`, `-963,0+2284,1`, `-1020,6+2352,3`
- A | TaskStore._commit_create._do_commit: `-964,2+2286,2`, `-968,3+2290,7`, `-972,1+2298,14`, `-994,19+2333,11`, `-1014,0+2345,1`
- A | TaskStore._commit_update: `-1032,0+2361,2`, `-1033,1+2364,8`, `-1036,7+2374,8`, `-1050,8+2389,0`, `-1082,0+2413,1`, `-1141,6+2481,3`
- A | TaskStore._commit_update._do_commit: `-1083,2+2415,2`, `-1087,0+2419,29`, `-1102,31+2463,3`, `-1134,0+2467,6`, `-1135,0+2474,1`
- A | TaskStore._row_to_state: `-1164,4+2501,0`, `-1169,1+2502,9`
- A | TaskStore.curate_training_dataset: `-1201,0+2542,4`, `-1203,1+2548,6`, `-1205,0+2555,1`, `-1219,1+2570,1`, `-1227,1+2578,7`, `-1229,1+2586,8`, `-1231,0+2595,3`, `-1233,1+2600,1`, `-1235,3+2602,4`

### D083 src/local_ai_hub/agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 25:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fbc602e20158d5f852498f3ce77c2e6b6a4565c5`; original `100644:9085577ca0c4b9622ef68f084a5fd42608c8898d`; pinned-current `100644:c95e6e69f62684922a8b8a57578e56f2ff135bc4`.

Exact checkpoint/owner witnesses: `S017 / 281cf99b1d7bf265d06a315bbadf168bef4d1ac5 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,4`, `-8,0+12,1`, `-10,1+15,1`, `-18,0+23,5`, `-214,0+224,119`
- A | GoalContract: `-81,0+91,1`
- A | GoalContract.__post_init__: `-87,0+98,1`
- A | GoalContract.to_dict: `-100,0+112,1`
- A | GoalContract.from_dict: `-110,10+123,6`, `-126,0+135,1`
- U | TaskStore.__init__: `-225,0+354,3`
- U | TaskStore: `-228,0+360,406`, `-419,5+1199,68`, `-437,8+1280,169`
- L | TaskStore._init_projection_table: `-293,0+831,1`
- U | TaskStore.create: `-312,0+851,8`
- L | TaskStore.create: `-317,1+864,13`, `-320,0+879,3`, `-322,0+884,13`
- L | TaskStore: `-367,1+942,123`, `-550,0+1595,60`
- A | TaskStore.list_tasks: `-369,1+1066,1`, `-372,1+1069,15`, `-395,1+1117,32`, `-397,3+1150,1`
- A | TaskStore.list_tasks._fetch_tasks: `-379,1+1090,1`, `-382,0+1093,12`, `-389,1+1112,0`, `-391,3+1113,3`
- U | TaskStore.add_verification_receipt: `-416,2+1167,31`
- A | TaskStore.add_verification_receipt_in_transaction: `-432,1+1275,1`, `-435,1+1278,1`
- A | TaskStore.transition: `-454,0+1458,3`, `-459,0+1466,20`, `-460,1+1487,12`, `-538,1+1576,1`, `-541,0+1579,3`, `-549,0+1590,4`
- A | TaskStore.checkpoint: `-659,0+1764,4`
- U | TaskStore.resume: `-781,0+1890,52`
- L | TaskStore.resume: `-786,1+1947,3`
- L | TaskStore.cleanup_worktree: `-828,1+1991,7`, `-835,0+2004,6`
- U | TaskStore.cleanup_worktree: `-836,5+2011,84`
- A | TaskStore.reap_expired_heartbeats: `-844,1+2098,14`, `-867,0+2134,14`, `-875,0+2156,7`
- A | TaskStore.recover_zombie_tasks: `-881,1+2169,8`, `-883,1+2178,7`
- A | TaskStore._save_projection._do_save: `-932,0+2233,1`
- L | TaskStore._commit_create: `-945,1+2247,1`, `-949,6+2251,0`
- U | TaskStore._commit_create: `-963,0+2259,1`, `-1022,1+2329,0`, `-1024,2+2330,5`
- U | TaskStore._commit_create._do_commit: `-964,1+2261,1`, `-968,3+2265,7`, `-972,1+2273,14`, `-994,19+2308,11`, `-1014,0+2320,1`
- L | TaskStore._commit_update: `-1032,0+2341,2`, `-1033,1+2344,8`, `-1036,7+2354,8`, `-1050,8+2369,0`
- U | TaskStore._commit_update: `-1082,0+2393,2`, `-1143,1+2464,0`, `-1145,2+2465,5`
- U | TaskStore._commit_update._do_commit: `-1087,0+2400,29`, `-1134,0+2448,6`, `-1135,0+2455,1`
- L | TaskStore._commit_update._do_commit: `-1102,31+2444,3`
- A | TaskStore._row_to_state: `-1164,4+2487,0`, `-1169,1+2488,9`
- A | TaskStore.curate_training_dataset: `-1201,0+2528,4`, `-1203,1+2534,6`, `-1205,0+2541,1`, `-1219,1+2556,1`, `-1227,1+2564,7`, `-1229,1+2572,8`, `-1231,0+2581,3`, `-1233,1+2586,1`, `-1235,3+2588,4`

### D084 src/local_ai_hub/agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fbc602e20158d5f852498f3ce77c2e6b6a4565c5`; original `100644:9e90056dec15b97c8392c1b7d557d84d4af817b2`; pinned-current `100644:c95e6e69f62684922a8b8a57578e56f2ff135bc4`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,3`, `-10,1+13,1`, `-18,0+21,2`, `-214,0+219,115`, `-1246,0+2295,1`
- A | TaskStore.__init__: `-225,0+345,4`
- U | TaskStore: `-231,0+355,555`
- L | TaskStore._init_projection_table: `-258,0+937,17`
- U | TaskStore.create: `-312,0+1008,9`, `-320,0+1025,3`
- L | TaskStore.create: `-322,0+1030,13`
- L | TaskStore: `-415,0+1136,20`, `-419,5+1178,68`, `-550,0+1406,60`
- A | TaskStore.add_verification_receipt: `-416,2+1157,20`
- A | TaskStore.add_verification_receipt_in_transaction: `-432,1+1254,1`, `-435,1+1257,1`, `-437,8+1259,1`
- A | TaskStore.transition: `-454,0+1269,3`, `-459,0+1277,20`, `-460,1+1298,12`, `-538,1+1387,1`, `-541,0+1390,3`, `-549,0+1401,4`
- A | TaskStore.checkpoint: `-659,0+1575,4`
- A | TaskStore.resume: `-781,0+1701,52`, `-786,1+1758,3`
- A | TaskStore.reap_expired_heartbeats: `-844,1+1818,14`, `-867,0+1854,14`, `-875,0+1876,7`
- A | TaskStore.recover_zombie_tasks: `-881,1+1889,8`, `-883,1+1898,7`
- L | TaskStore._commit_create: `-945,1+1966,1`, `-949,6+1970,0`
- U | TaskStore._commit_create._write: `-963,3+1978,1`, `-968,3+1981,7`, `-994,19+2024,11`, `-1014,0+2036,1`
- L | TaskStore._commit_create._write: `-972,1+1989,14`
- U | TaskStore._commit_create: `-1020,3+2043,0`, `-1024,2+2044,1`
- L | TaskStore._commit_update: `-1032,0+2051,2`, `-1033,1+2054,8`, `-1036,7+2064,8`, `-1050,8+2079,0`
- U | TaskStore._commit_update._write: `-1082,3+2103,2`, `-1087,0+2107,28`, `-1102,31+2150,2`, `-1134,0+2153,6`, `-1135,0+2160,1`
- U | TaskStore._commit_update: `-1141,3+2167,0`, `-1145,2+2168,1`
- A | TaskStore.curate_training_dataset: `-1201,0+2223,4`, `-1203,1+2229,6`, `-1205,0+2236,1`, `-1219,1+2251,1`, `-1227,1+2259,7`, `-1229,1+2267,8`, `-1231,0+2276,3`, `-1233,1+2281,1`, `-1235,3+2283,4`

### D085 src/local_ai_hub/agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fbc602e20158d5f852498f3ce77c2e6b6a4565c5`; original `100644:cf658ca9ab79026b15b70dbf1cde9bceaac88dc7`; pinned-current `100644:c95e6e69f62684922a8b8a57578e56f2ff135bc4`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,4`, `-8,0+12,1`, `-10,1+15,1`, `-18,0+23,5`, `-214,0+224,119`
- A | GoalContract: `-81,0+91,1`
- A | GoalContract.__post_init__: `-87,0+98,1`
- A | GoalContract.to_dict: `-100,0+112,1`
- A | GoalContract.from_dict: `-110,10+123,6`, `-126,0+135,1`
- U | TaskStore.__init__: `-225,0+354,3`
- U | TaskStore: `-228,0+360,409`, `-248,0+789,20`, `-437,8+1291,169`
- L | TaskStore._init_projection_table: `-293,0+854,1`
- U | TaskStore.create: `-312,0+874,8`
- L | TaskStore.create: `-317,1+887,13`, `-320,0+902,3`, `-322,0+907,13`
- L | TaskStore: `-367,1+965,123`, `-419,5+1210,68`, `-550,0+1606,60`
- A | TaskStore.list_tasks: `-369,1+1089,1`, `-372,1+1092,15`, `-395,1+1140,32`, `-397,3+1173,1`
- A | TaskStore.list_tasks._fetch_tasks: `-379,1+1113,1`, `-382,0+1116,12`, `-389,1+1135,0`, `-391,3+1136,3`
- A | TaskStore.add_verification_receipt: `-416,2+1190,19`
- A | TaskStore.add_verification_receipt_in_transaction: `-432,1+1286,1`, `-435,1+1289,1`
- A | TaskStore.transition: `-454,0+1469,3`, `-459,0+1477,20`, `-460,1+1498,12`, `-538,1+1587,1`, `-541,0+1590,3`, `-549,0+1601,4`
- A | TaskStore.checkpoint: `-659,0+1775,4`
- U | TaskStore.resume: `-781,0+1901,52`
- L | TaskStore.resume: `-786,1+1958,3`
- L | TaskStore.cleanup_worktree: `-828,1+2002,7`, `-835,0+2015,6`
- U | TaskStore.cleanup_worktree: `-836,5+2022,84`
- A | TaskStore.reap_expired_heartbeats: `-844,1+2109,14`, `-867,0+2145,14`, `-875,0+2167,7`
- A | TaskStore.recover_zombie_tasks: `-881,1+2180,8`, `-883,1+2189,7`
- A | TaskStore._save_projection._do_save: `-932,0+2244,1`
- A | TaskStore._commit_create: `-945,1+2258,1`, `-949,6+2262,0`, `-963,0+2270,1`, `-1020,6+2338,3`
- A | TaskStore._commit_create._do_commit: `-964,2+2272,2`, `-968,3+2276,7`, `-972,1+2284,14`, `-994,19+2319,11`, `-1014,0+2331,1`
- A | TaskStore._commit_update: `-1032,0+2347,2`, `-1033,1+2350,8`, `-1036,7+2360,8`, `-1050,8+2375,0`, `-1082,0+2399,1`, `-1141,6+2467,3`
- A | TaskStore._commit_update._do_commit: `-1083,2+2401,2`, `-1087,0+2405,29`, `-1102,31+2449,3`, `-1134,0+2453,6`, `-1135,0+2460,1`
- A | TaskStore._row_to_state: `-1164,4+2487,0`, `-1169,1+2488,9`
- A | TaskStore.curate_training_dataset: `-1201,0+2528,4`, `-1203,1+2534,6`, `-1205,0+2541,1`, `-1219,1+2556,1`, `-1227,1+2564,7`, `-1229,1+2572,8`, `-1231,0+2581,3`, `-1233,1+2586,1`, `-1235,3+2588,4`

### D086 src/local_ai_hub/agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fbc602e20158d5f852498f3ce77c2e6b6a4565c5`; original `100644:d551bf0a5375ac8ec5f0fd9b4654f460e5b56355`; pinned-current `100644:c95e6e69f62684922a8b8a57578e56f2ff135bc4`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,1`
- U | TaskStore.create: `-317,1+318,13`
- L | TaskStore.cleanup_worktree: `-828,1+841,7`, `-835,0+854,6`
- U | TaskStore.cleanup_worktree: `-836,5+861,84`

### D087 src/local_ai_hub/agent_verification.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:dfa3f4655ecc1fa8d8cf3bf0fc285eee65082ede`; original `100644:11d7eb50bca0c858233f3a3663885922e2476539`; pinned-current `100644:2e8f12c124ed224c6d176f6fd93c88cb21efcebf`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,1`, `-108,0+130,30`
- U | VerificationReceipt: `-30,0+31,3`
- U | VerificationReceipt.__post_init__: `-33,0+37,6`
- U | VerificationReceipt.create: `-46,0+56,3`, `-69,0+82,3`
- U | VerificationReceipt.to_dict: `-91,0+107,3`
- U | VerificationReceipt.from_dict: `-105,1+124,1`, `-107,0+126,3`
- L | VerificationStore._init_tables: `-339,0+391,36`
- U | VerificationStore._init_tables: `-416,15+504,0`
- U | VerificationStore: `-436,0+509,26`, `-442,1+541,10`
- U | VerificationStore.record_in_transaction: `-450,44+558,40`, `-495,10+599,6`
- U | VerificationStore.record_change: `-517,1+617,9`, `-551,0+673,2`
- U | VerificationStore.record_change._do_save: `-523,0+631,7`, `-540,0+655,7`
- L | VerificationStore.record_change._do_save: `-525,1+640,1`
- U | VerificationStore.record_outcome: `-564,1+688,9`, `-597,0+743,2`
- U | VerificationStore.record_outcome._do_save: `-570,0+702,7`, `-586,0+725,7`
- L | VerificationStore.record_outcome._do_save: `-572,1+711,1`
- U | VerificationStore.completion: `-629,0+777,1`, `-633,0+782,2`, `-653,0+804,1`, `-664,1+816,4`, `-685,0+840,5`, `-686,1+846,2`

### D088 src/local_ai_hub/agent_verification.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M, 25:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e5d3b2d17bb4eb525f43e1785f13e6ec9c7837d0`; original `100644:3c7b354c375b0928b7f64f2f272df27b70b5d739`; pinned-current `100644:2e8f12c124ed224c6d176f6fd93c88cb21efcebf`.

Exact checkpoint/owner witnesses: `S017 / 281cf99b1d7bf265d06a315bbadf168bef4d1ac5 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,4`
- L | <module/text>: `-16,0+20,7`
- A | classify_verification_command: `-31,1+42,1`, `-33,1+44,6`, `-35,6+51,18`
- A | VerificationReceipt.create: `-99,2+127,0`, `-128,1+154,1`
- A | VerificationReceipt.from_dict: `-172,1+198,1`
- L | evaluate_completion_receipts: `-394,1+420,3`, `-399,2+441,4`, `-402,9+446,15`, `-412,1+462,1`, `-414,1+464,4`, `-416,8+469,7`, `-425,0+477,11`, `-430,0+493,6`, `-433,4+502,2`, `-438,0+505,3`, `-439,1+509,7`, `-443,1+519,4`, `-445,1+524,1`, `-448,1+527,3`, `-456,1+547,1`, `-458,1+549,7`, `-468,0+565,1`, `-470,1+568,5`
- U | evaluate_completion_receipts: `-396,0+424,8`, `-398,0+434,6`, `-450,0+531,10`, `-452,2+543,2`
- U | _receipt_evidence_matches: `-484,0+586,8`, `-485,0+595,1`
- L | _receipt_evidence_matches: `-487,1+598,1`, `-489,1+600,8`, `-491,1+609,5`, `-495,1+617,2`, `-497,1+620,2`, `-508,3+632,4`, `-514,0+639,165`, `-518,4+808,8`, `-525,2+819,4`
- U | VerificationStore.__init__: `-541,0+837,2`
- L | VerificationStore.__init__: `-542,1+840,5`
- L | VerificationStore: `-546,0+848,6`
- L | VerificationStore._init_tables: `-586,0+894,16`
- U | VerificationStore: `-651,1+975,196`
- L | VerificationStore.record: `-654,1+1173,1`, `-672,0+1191,1`, `-679,7+1199,1`, `-724,0+1223,19`, `-727,1+1245,1`, `-729,1+1247,1`, `-731,7+1249,5`
- A | VerificationStore.record._save_transaction: `-687,2+1201,1`, `-691,25+1204,2`, `-717,0+1207,8`, `-718,0+1216,1`
- L | VerificationStore.completion: `-844,1+1360,3`, `-846,0+1364,4`, `-872,0+1392,29`, `-894,2+1443,5`, `-900,1+1452,1`, `-905,2+1457,2`, `-915,5+1467,4`, `-921,6+1472,1`, `-930,1+1476,1`, `-934,0+1480,1`, `-935,1+1482,1`, `-945,3+1500,3`, `-961,1+1516,1`, `-977,1+1532,1`
- U | VerificationStore.completion: `-864,1+1386,0`, `-866,1+1387,0`, `-938,0+1485,8`, `-940,1+1495,1`

### D089 src/local_ai_hub/agent_verification.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e5d3b2d17bb4eb525f43e1785f13e6ec9c7837d0`; original `100644:bf15cbb9b52b7cff8f39faaa86e8489595bf1a6f`; pinned-current `100644:2e8f12c124ed224c6d176f6fd93c88cb21efcebf`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,4`
- L | <module/text>: `-16,0+20,7`
- A | classify_verification_command: `-31,1+42,1`, `-33,1+44,6`, `-35,6+51,18`
- A | VerificationReceipt.create: `-99,2+127,0`, `-128,1+154,1`
- A | VerificationReceipt.from_dict: `-172,1+198,1`
- L | evaluate_completion_receipts: `-394,1+420,3`, `-399,2+441,4`, `-402,9+446,15`, `-412,1+462,1`, `-414,1+464,4`, `-416,8+469,7`, `-425,0+477,11`, `-430,0+493,6`, `-433,4+502,2`, `-438,0+505,3`, `-439,1+509,7`, `-443,1+519,4`, `-445,1+524,1`, `-448,1+527,3`, `-456,1+547,1`, `-458,1+549,7`, `-468,0+565,1`, `-470,1+568,5`
- U | evaluate_completion_receipts: `-396,0+424,8`, `-398,0+434,6`, `-450,0+531,10`, `-452,2+543,2`
- U | _receipt_evidence_matches: `-484,0+586,8`, `-485,0+595,1`, `-514,0+639,165`
- L | _receipt_evidence_matches: `-487,1+598,1`, `-489,1+600,8`, `-491,1+609,5`, `-495,1+617,2`, `-497,1+620,2`, `-508,3+632,4`, `-518,4+808,8`, `-525,2+819,4`
- U | VerificationStore.__init__: `-541,0+837,2`
- L | VerificationStore.__init__: `-542,1+840,5`
- L | VerificationStore: `-546,0+848,6`
- L | VerificationStore._init_tables: `-586,0+894,16`
- U | VerificationStore: `-651,1+975,196`
- L | VerificationStore.record: `-654,1+1173,1`, `-672,0+1191,1`, `-679,7+1199,1`, `-724,0+1223,19`, `-727,1+1245,1`, `-729,1+1247,1`, `-731,7+1249,5`
- A | VerificationStore.record._save_transaction: `-687,2+1201,1`, `-691,25+1204,2`, `-717,0+1207,8`, `-718,0+1216,1`
- U | VerificationStore.record_change: `-752,2+1268,0`, `-786,0+1307,20`
- U | VerificationStore.record_change._do_save: `-758,0+1272,7`
- U | VerificationStore.record_outcome: `-799,2+1340,0`
- U | VerificationStore.record_outcome._do_save: `-805,0+1344,7`
- L | VerificationStore.completion: `-844,1+1390,3`, `-846,0+1394,4`, `-872,0+1422,29`, `-894,2+1473,5`, `-900,1+1482,1`, `-905,2+1487,2`, `-915,5+1497,4`, `-921,6+1502,1`, `-930,1+1506,1`, `-934,0+1510,1`, `-935,1+1512,1`, `-945,3+1530,3`, `-961,1+1546,1`, `-977,1+1562,1`
- U | VerificationStore.completion: `-864,1+1416,0`, `-866,1+1417,0`, `-938,0+1515,8`, `-940,1+1525,1`

### D090 src/local_ai_hub/app.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:148b4af588bbd6f3755507a8d6a68f5141603507`; original `100644:211b68594e6a20329d432930db41d88426a9787a`; pinned-current `100644:33fef98e2c02f59736507d18f3baecf094701e13`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LocalAIApp.__init__: `-266,0+266,1`
- U | LocalAIApp: `-423,0+424,4`
- U | LocalAIApp._execute_async_task: `-424,23+429,65`
- U | LocalAIApp.realtime_status: `-578,0+625,17`, `-580,0+644,1`, `-621,1+686,1`
- U | LocalAIApp.status: `-707,0+772,17`, `-709,0+791,1`

### D091 src/local_ai_hub/app.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:148b4af588bbd6f3755507a8d6a68f5141603507`; original `100644:24b64d0b0eb5869d924caf2a72b793cb0875079f`; pinned-current `100644:33fef98e2c02f59736507d18f3baecf094701e13`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-45,0+45,1`
- L | LocalAIApp.__init__: `-172,0+173,1`, `-232,1+234,1`, `-251,0+253,10`, `-286,1+298,1`
- U | LocalAIApp.__init__: `-242,1+244,1`
- A | LocalAIApp._watchdog_loop: `-383,1+395,1`, `-386,1+398,1`, `-389,2+401,0`
- U | LocalAIApp.export_bundle: `-831,1+841,7`, `-843,1+859,12`

### D092 src/local_ai_hub/app.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5fcf4dba47be3eda1aa1ccbf82ab85213038a1ad`; original `100644:3e96745d55bc5d5a286cb8e99e55e1d8f8cb93a1`; pinned-current `100644:33fef98e2c02f59736507d18f3baecf094701e13`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-112,1+112,7`
- U | _status_dependency: `-114,0+120,7`, `-117,1+130,5`, `-123,0+140,1`, `-146,0+164,1`, `-151,0+170,1`, `-154,0+174,1`
- L | _status_dependency: `-143,1+161,1`
- U | LocalAIApp.realtime_status: `-591,1+612,1`, `-595,2+616,3`, `-598,1+620,24`, `-600,1+645,0`, `-609,11+653,2`, `-623,10+658,1`, `-635,6+661,4`, `-649,11+673,29`, `-661,1+703,3`, `-681,1+725,1`, `-686,1+730,1`, `-690,1+734,1`, `-692,1+736,1`, `-694,4+738,4`, `-708,12+752,1`, `-721,1+754,4`
- A | LocalAIApp.status.dependency: `-732,1+768,1`, `-742,0+778,1`
- U | LocalAIApp.status: `-749,3+786,2`, `-754,0+790,1`, `-757,1+794,3`, `-759,0+798,6`, `-761,1+806,11`, `-801,2+856,3`

### D093 src/local_ai_hub/app.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:792bd14b3dfdc2e9f18fb3461e4826383bdd76b2`; original `100644:e23243499f69d4a43bd8c884c4d68f787a6fe383`; pinned-current `100644:33fef98e2c02f59736507d18f3baecf094701e13`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | LocalAIApp.__init__: `-301,0+301,1`

### D094 src/local_ai_hub/app.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:86ef600b8308afc974ca9bbf02f0b3c28222faf7`; original `100644:402edc01877b1761bbcb22d3532da963c69e1fe0`; pinned-current `100644:33fef98e2c02f59736507d18f3baecf094701e13`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-15,1+15,1`
- L | LocalAIApp.__init__: `-351,0+351,10`, `-365,0+375,1`, `-369,0+380,3`, `-401,0+415,1`
- L | LocalAIApp: `-525,0+540,6`
- A | LocalAIApp._execute_async_task_admitted: `-527,0+548,2`, `-530,1+553,3`, `-532,1+557,3`, `-538,1+565,3`, `-540,1+569,3`, `-542,1+573,3`, `-544,1+577,19`
- L | LocalAIApp.status: `-834,0+885,1`, `-845,0+897,1`, `-850,0+903,1`, `-855,0+909,1`
- A | LocalAIApp.export_bundle: `-1147,1+1202,8`, `-1159,1+1221,25`
- A | LocalAIApp.import_bundle.create_import_intent: `-1399,1+1485,1`, `-1403,1+1489,1`
- A | LocalAIApp.import_bundle.mark_import_phase: `-1438,1+1524,1`
- A | LocalAIApp.import_bundle.finish_import_intent: `-1446,1+1532,1`
- A | LocalAIApp.import_bundle: `-1668,1+1754,3`

### D095 src/local_ai_hub/app.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:deefed06ae4d4d19f838bd62a5d5050312f3676e`; original `100644:09723e0a0fc0eddac78a05b353a256f7b7e6a71f`; pinned-current `100644:33fef98e2c02f59736507d18f3baecf094701e13`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-11,0+11,1`
- L | LocalAIApp.realtime_status: `-546,1+547,26`
- U | LocalAIApp.realtime_status: `-549,4+575,1`
- U | LocalAIApp.status: `-707,1+730,25`, `-711,4+758,1`
- L | LocalAIApp: `-780,0+824,17`

### D096 src/local_ai_hub/artifacts.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:030d9ff4ab95a9bac7f816ac016930b82b350eb2`; original `100644:64bdb2a9ee071a0cf39582457b3e61c57a14d7d5`; pinned-current `100644:6a569d8ce0a01c403cdad062dbb700deb9377e3b`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | ArtifactStore.list: `-558,2+558,2`

### D097 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 38:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4999700e51214e3bdf84f83fd3810e5907a30e`; original `100644:3bfe6c12f9d2f8ded106c69effd0faea3f6ae3e0`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S002 / 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AsyncJobManager._init_db: `-79,1+79,1`, `-84,1+84,5`, `-92,1+96,2`, `-95,0+100,1`
- U | AsyncJobManager.submit: `-227,0+233,1`, `-228,0+235,1`, `-266,1+274,1`
- L | AsyncJobManager.submit: `-280,1+288,0`
- U | AsyncJobManager._dispatch: `-306,1+313,2`, `-308,1+316,5`, `-310,0+322,2`
- U | AsyncJobManager.cancel: `-558,1+572,1`
- U | AsyncJobManager.recover: `-580,1+594,1`, `-584,1+598,1`
- U | AsyncJobManager.tick: `-615,1+629,1`, `-625,1+639,1`
- L | AsyncJobManager.tick: `-630,2+644,2`

### D098 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4999700e51214e3bdf84f83fd3810e5907a30e`; original `100644:9a4a561057be1d6a635b78a07165e52e645201de`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AsyncJobManager.submit: `-228,0+228,2`, `-268,0+270,5`, `-280,8+287,1`

### D099 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4999700e51214e3bdf84f83fd3810e5907a30e`; original `100644:9ff115aacd07038a5d5b44d78afc835ee51ef0ee`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-11,1+11,2`
- U | <module/text>: `-13,1+14,1`
- L | AsyncJobManager: `-26,0+27,7`, `-27,0+35,1`, `-116,0+145,19`, `-161,0+209,403`, `-477,0+1028,16`
- A | AsyncJobManager.__init__: `-54,0+63,12`
- A | AsyncJobManager._init_db: `-79,1+100,1`, `-81,17+102,25`
- A | AsyncJobManager._safe_payload: `-104,1+133,1`
- L | AsyncJobManager.submit: `-221,1+672,15`, `-258,11+726,17`, `-280,1+754,0`
- U | AsyncJobManager.submit: `-224,2+689,1`, `-228,0+692,4`
- A | AsyncJobManager._dispatch: `-301,9+774,31`, `-311,8+806,8`
- U | AsyncJobManager: `-320,1+815,10`
- U | AsyncJobManager._release_for_retry: `-324,18+828,30`, `-348,1+864,5`
- U | AsyncJobManager._execute: `-351,0+871,1`, `-381,1+910,1`, `-393,0+922,1`
- L | AsyncJobManager._execute: `-363,2+884,10`, `-407,0+937,12`, `-452,2+994,9`, `-475,0+1024,2`
- A | AsyncJobManager.status: `-478,0+1045,1`
- A | AsyncJobManager.result: `-528,0+1096,1`
- U | AsyncJobManager.cancel: `-545,1+1114,1`, `-549,1+1118,0`
- L | AsyncJobManager.cancel: `-563,1+1131,4`
- U | AsyncJobManager.recover: `-577,2+1148,2`, `-582,1+1153,1`
- U | AsyncJobManager.tick: `-618,2+1189,2`, `-621,2+1192,1`, `-631,1+1201,1`

### D100 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4999700e51214e3bdf84f83fd3810e5907a30e`; original `100644:c52af9869732d415242d944371508450fb503804`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-11,1+11,2`
- U | <module/text>: `-13,1+14,1`
- L | AsyncJobManager: `-26,0+27,7`, `-27,0+35,1`, `-297,1+754,0`
- A | AsyncJobManager.__init__: `-54,0+63,12`
- U | AsyncJobManager: `-63,0+84,412`, `-116,0+549,12`, `-327,0+799,1`, `-350,0+823,16`
- A | AsyncJobManager._safe_payload: `-104,1+537,1`
- U | AsyncJobManager.submit: `-221,1+666,8`, `-224,2+676,0`, `-227,0+677,1`, `-228,2+679,3`, `-258,0+710,4`, `-266,1+722,3`
- L | AsyncJobManager.submit: `-232,1+684,1`, `-280,1+738,0`
- U | AsyncJobManager._dispatch: `-301,9+757,25`
- U | AsyncJobManager._release_for_retry: `-335,1+808,1`
- L | AsyncJobManager._execute: `-363,2+852,10`
- U | AsyncJobManager._execute: `-381,1+878,1`, `-393,0+890,1`, `-407,0+905,12`, `-475,0+985,2`
- U | AsyncJobManager.recover: `-576,0+1088,1`, `-577,2+1090,2`, `-582,1+1095,1`, `-586,0+1099,3`
- U | AsyncJobManager.tick: `-621,1+1137,1`

### D101 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4999700e51214e3bdf84f83fd3810e5907a30e`; original `100644:fc2d76ea147e7e25f2797bc56f9c7067192cc901`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-11,1+11,1`
- U | AsyncJobManager: `-26,0+26,1`, `-162,0+164,121`, `-477,0+610,28`
- U | AsyncJobManager.__init__: `-54,0+55,1`
- U | AsyncJobManager.submit: `-228,0+351,2`, `-258,11+383,17`
- U | AsyncJobManager._dispatch: `-301,0+432,1`
- U | AsyncJobManager._execute: `-351,0+483,1`, `-381,1+514,1`
- A | AsyncJobManager.status: `-478,0+639,1`
- A | AsyncJobManager.result: `-528,0+690,1`

### D102 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:83f67fa98e5dbf85c4ede5934b8c5d309bf3f523`; original `100644:11254aeaa247905a4602d7c3560d14550f017f29`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-16,1+16,0`
- L | <module/text>: `-18,1+17,0`
- L | AsyncJobManager.submit: `-434,1+432,4`
- U | AsyncJobManager._release_for_retry: `-524,1+525,1`, `-526,1+527,1`
- L | AsyncJobManager._execute: `-560,2+561,0`, `-653,1+651,6`
- U | AsyncJobManager._execute: `-573,1+572,0`

### D103 src/local_ai_hub/async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d5e92e266f12d90743cd588305d214a66c80a197`; original `100644:e80291c1ff58bc9c3446d08b5a12d1d04d8b7754`; pinned-current `100644:2fdd7a2fcdba9f130e3e19a1131bb49196d3dfb4`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-11,1+11,2`
- U | <module/text>: `-13,1+14,1`
- U | AsyncJobManager: `-25,0+26,1`, `-26,0+28,7`, `-178,0+207,407`
- U | AsyncJobManager.__init__: `-61,0+70,12`
- A | AsyncJobManager._init_db: `-86,1+107,1`, `-88,17+109,25`
- U | AsyncJobManager.submit: `-239,0+675,1`, `-244,1+681,3`, `-249,0+688,1`, `-250,1+690,4`, `-280,12+723,20`
- L | AsyncJobManager.submit: `-303,1+754,0`
- U | AsyncJobManager._dispatch: `-324,9+774,26`, `-343,6+810,6`
- L | AsyncJobManager._dispatch: `-334,8+801,8`
- L | AsyncJobManager._release_for_retry: `-353,6+820,2`
- U | AsyncJobManager._release_for_retry: `-360,23+823,30`
- U | AsyncJobManager._execute: `-393,0+863,1`, `-395,0+866,3`, `-397,0+871,1`, `-402,0+877,1`, `-403,1+879,30`, `-405,1+910,8`, `-423,1+935,1`, `-437,0+949,1`, `-438,0+951,1`, `-441,1+955,1`, `-458,1+972,1`, `-460,1+974,1`, `-489,0+1003,12`, `-494,2+1020,9`, `-500,1+1033,1`, `-502,1+1035,1`, `-513,1+1046,5`
- L | AsyncJobManager._execute: `-517,0+1054,2`
- L | AsyncJobManager: `-519,0+1058,16`
- L | AsyncJobManager.status: `-520,0+1075,1`
- L | AsyncJobManager.result: `-573,0+1129,1`
- U | AsyncJobManager.cancel: `-591,0+1148,1`, `-606,1+1164,1`
- U | AsyncJobManager.recover: `-627,0+1185,1`, `-628,1+1187,1`, `-631,1+1190,1`, `-633,1+1192,1`, `-635,1+1194,1`, `-637,1+1196,1`, `-639,0+1198,3`, `-640,1+1202,1`
- U | AsyncJobManager.tick: `-678,1+1240,1`, `-686,2+1248,2`
- L | AsyncJobManager.tick: `-681,1+1243,1`
- L | AsyncJobManager.close: `-718,0+1280,1`, `-730,1+1294,1`
- U | AsyncJobManager.close: `-719,0+1282,1`, `-720,1+1284,1`

### D104 src/local_ai_hub/background_gpu.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:28cb329d65e6ffe703fcbbcd3e63530fc8483c39`; original `100644:18d5d041c1188d8b5ad698ed0746a60a4eab85f4`; pinned-current `100644:ecbe9078e350555f1ad51332d121daffcc1156df`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | IdleGPUWorker._generate_one: `-344,0+344,21`

### D105 src/local_ai_hub/background_gpu.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:28cb329d65e6ffe703fcbbcd3e63530fc8483c39`; original `100644:ecbe9078e350555f1ad51332d121daffcc1156df`; pinned-current `100644:ecbe9078e350555f1ad51332d121daffcc1156df`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | IdleGPUWorker._generate_one: `-344,0+344,9`

### D106 src/local_ai_hub/benchmark.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:366a3864928e4c13c87c5e1671cbee1f8b5524bc`; original `100644:07c31ccebc74de06abb781e686cc0336f207b973`; pinned-current `100644:07c31ccebc74de06abb781e686cc0336f207b973`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-7,0+7,1`, `-9,1+10,15`
- B | HardwareBenchmarkRunner.__init__: `-25,0+40,1`, `-30,0+46,1`
- B | HardwareBenchmarkRunner: `-33,0+50,590`
- B | HardwareBenchmarkRunner.get_latest_summary: `-224,1+831,10`

### D107 src/local_ai_hub/benchmark.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d3fa14d5186b88cdb6e49104fc9a6fea4851601b`; original `100644:dd2778c375041eb9cdf1a023421bb80bf0607899`; pinned-current `100644:07c31ccebc74de06abb781e686cc0336f207b973`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-16,0+16,1`
- A | HardwareBenchmarkRunner.run_t12_case.record_backend_metrics: `-142,0+143,8`
- L | HardwareBenchmarkRunner.run_t12_case: `-268,0+277,3`, `-282,0+294,47`, `-305,2+364,10`, `-308,0+375,3`, `-309,1+379,8`, `-321,0+398,2`, `-333,0+412,3`, `-422,1+504,11`

### D108 src/local_ai_hub/browser_bridge.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:df3c325dc0325ea471d763551535abb73216614c`; original `100644:1d41cf07791cb1b4434f024c16793a120b330960`; pinned-current `100644:1d41cf07791cb1b4434f024c16793a120b330960`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | capture_to_artifacts: `-711,1+711,1`

### D109 src/local_ai_hub/cache.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b798056cde9a02721776711550c0a8166bd8e33`; original `100644:857c80f98b3c97700415d11b6edd09ff990128a4`; pinned-current `100644:a1dd4d318163aa26a9dbfc08717311aff7bb53de`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-8,0+9,1`, `-9,0+11,1`, `-11,1+14,1`, `-13,1+16,1`, `-21,0+24,3`
- U | <module/text>: `-26,0+32,160`
- A | SQLiteCache.__init__: `-235,0+401,3`
- A | SQLiteCache: `-413,1+582,9`, `-418,1+595,9`
- A | TieredCache.__init__: `-469,0+654,2`
- A | TieredCache: `-473,1+660,51`, `-484,1+721,4`
- A | TieredCache.get_checked: `-477,1+714,1`, `-480,0+717,1`, `-481,2+719,1`
- A | TieredCache.set: `-487,0+727,16`
- A | TieredCache.delete: `-490,1+746,1`, `-492,1+748,18`
- A | TieredCache.clear: `-496,0+769,14`

### D110 src/local_ai_hub/cache.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b798056cde9a02721776711550c0a8166bd8e33`; original `100644:92b0216bfbf97f1a93a4233be10705d88a6a1cf3`; pinned-current `100644:a1dd4d318163aa26a9dbfc08717311aff7bb53de`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-8,0+9,1`, `-9,0+11,1`, `-11,1+14,1`, `-13,1+16,1`, `-21,0+24,3`, `-26,0+32,159`
- A | SQLiteCache.__init__: `-235,0+400,3`
- A | SQLiteCache: `-413,1+581,9`, `-418,1+594,9`
- A | TieredCache.__init__: `-469,0+653,2`
- U | TieredCache: `-473,1+659,48`
- L | TieredCache.get_checked: `-477,1+710,1`, `-480,0+713,1`, `-481,2+715,1`
- L | TieredCache: `-484,1+717,4`
- A | TieredCache.set: `-487,0+723,16`
- A | TieredCache.delete: `-490,1+742,1`, `-492,1+744,18`
- A | TieredCache.clear: `-496,0+765,14`

### D111 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:32610a921ccd1c7718e0378406bedca7b21c995b`; original `100644:38d11e4bbc92acdc282811447c2bfc6c9cd53266`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-8,0+8,1`, `-19,1+21,1`
- L | <module/text>: `-11,0+12,1`, `-63,0+66,5`, `-67,0+75,1`
- A | _InProcessTransport.open: `-52,0+54,1`
- A | _TransportFailure.__init__: `-60,1+63,1`
- A | _write_start_lock_owner: `-94,1+103,8`
- A | _acquire_start_lock: `-125,1+141,9`
- A | HubClient._pooled_open: `-221,1+245,12`, `-225,1+260,3`, `-230,0+267,24`, `-231,1+292,3`, `-235,5+298,3`, `-246,0+307,4`, `-249,0+314,4`, `-253,1+322,2`, `-256,0+326,1`
- A | HubClient._open: `-266,2+337,7`, `-270,0+346,1`, `-273,5+350,26`
- L | HubClient: `-321,0+419,16`
- L | HubClient._transport_failure_response: `-327,4+441,4`
- A | HubClient._singleflight: `-344,1+458,9`, `-365,4+487,13`, `-372,1+503,4`
- L | HubClient.ensure_server: `-489,18+623,45`
- U | HubClient.ensure_server: `-525,0+686,5`
- U | HubClient.request: `-564,0+730,1`, `-565,0+732,1`, `-674,0+858,4`
- L | HubClient.request: `-580,0+748,2`, `-675,1+863,5`
- U | HubClient.request.once: `-594,0+764,1`
- U | HubClient.request.execute: `-604,0+775,1`, `-606,0+778,2`, `-622,0+796,1`, `-627,1+802,6`, `-658,0+840,2`
- L | HubClient.request.execute: `-632,0+812,2`, `-633,2+815,0`, `-645,0+825,2`
- A | HubClient.stream_events: `-1144,0+1336,13`, `-1148,2+1353,1`, `-1155,2+1359,1`, `-1189,1+1392,3`

### D112 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 31:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3efbfc395bf512f3cc7b9d713ee3d1a665288eb5`; original `100644:075db8456c8e916772049930167c7d8ef40b47db`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S047 / b81b75a784f7bed45745bb709ba15d4bc018911b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,1`, `-26,0+27,8`, `-37,2+46,12`
- U | _acquire_start_lock: `-40,2+59,20`, `-43,3+80,13`
- U | HubClient._pooled_open: `-116,0+163,4`, `-118,0+169,18`, `-121,1+190,1`, `-123,1+192,7`
- U | HubClient: `-158,1+233,34`
- L | HubClient._singleflight: `-162,1+270,1`
- U | HubClient._singleflight: `-180,1+288,3`
- U | HubClient.ensure_server: `-240,0+350,1`, `-242,1+353,3`, `-244,1+357,0`, `-246,6+358,4`, `-286,0+383,2`, `-288,0+387,1`, `-312,0+412,1`
- L | HubClient.ensure_server: `-254,29+364,16`, `-314,1+415,3`, `-316,1+419,9`
- U | HubClient.request: `-337,1+448,17`, `-344,1+471,1`, `-410,2+552,2`, `-417,1+559,5`
- U | HubClient.request.execute: `-385,2+512,2`, `-388,1+515,4`, `-392,2+522,8`, `-395,1+531,1`, `-397,0+533,5`, `-398,2+539,3`, `-402,2+544,2`
- U | HubClient.post: `-504,1+650,8`, `-506,1+659,1`

### D113 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3efbfc395bf512f3cc7b9d713ee3d1a665288eb5`; original `100644:688b789d65e7a35f55ccad326dd5387ed17c1e4a`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,2`, `-7,0+9,1`, `-24,0+28,48`, `-37,0+89,15`, `-46,0+110,102`
- L | <module/text>: `-10,0+13,1`, `-16,1+20,1`, `-18,2+22,2`
- U | _live_start_lock: `-40,2+107,0`, `-43,1+108,0`
- A | HubClient.__init__: `-49,1+215,8`, `-59,1+232,2`, `-62,0+236,1`
- A | HubClient.close: `-95,0+270,5`
- A | HubClient._pooled_open: `-115,1+295,18`, `-118,0+315,46`, `-121,1+364,5`, `-123,1+370,9`
- U | HubClient: `-130,0+385,42`, `-147,0+444,14`, `-158,1+469,49`, `-337,1+827,208`
- A | HubClient._singleflight: `-162,1+521,1`, `-179,2+538,13`, `-184,1+554,4`
- L | HubClient.ensure_server: `-209,0+582,7`, `-211,0+591,11`, `-212,1+603,0`, `-223,9+615,5`
- A | HubClient.ensure_server.live_supervisor: `-216,6+606,8`
- U | HubClient.ensure_server: `-237,1+625,1`, `-239,0+627,9`, `-240,0+637,1`, `-249,15+642,27`, `-266,1+671,23`, `-271,12+698,28`, `-290,0+733,10`, `-295,6+748,4`, `-303,1+754,2`, `-306,9+758,17`, `-316,1+776,31`
- U | HubClient.ensure_server.publish_lock_pid: `-241,7+639,2`
- U | HubClient.request: `-339,1+1036,0`, `-417,1+1192,1`
- L | HubClient.request: `-344,1+1040,3`, `-408,1+1175,5`, `-410,2+1181,6`
- A | HubClient.request.once: `-348,1+1046,1`, `-351,0+1049,2`, `-353,1+1053,22`
- L | HubClient.request.execute: `-357,1+1078,4`
- L | HubClient.request.execute.request_until_terminal: `-359,0+1083,5`, `-373,1+1102,5`, `-375,0+1108,1`
- U | HubClient.request.execute: `-381,0+1115,3`, `-385,1+1122,7`, `-388,1+1131,9`, `-392,4+1143,11`, `-397,0+1155,8`, `-398,2+1164,3`, `-401,1+1168,1`
- L | HubClient.get: `-420,1+1195,14`, `-423,0+1211,2`, `-424,1+1214,0`, `-428,0+1217,2`, `-461,2+1280,6`
- A | HubClient.get.once: `-432,2+1223,20`
- L | HubClient.get.execute: `-443,0+1252,5`, `-444,1+1258,4`, `-448,1+1265,1`
- U | HubClient.get.execute: `-451,1+1268,1`, `-453,1+1270,1`, `-455,1+1272,1`
- U | HubClient.get: `-459,1+1276,3`, `-468,1+1291,1`
- U | HubClient._post_replay_safe: `-476,0+1299,1`
- U | HubClient.post: `-504,3+1328,53`
- U | HubClient.create_task: `-676,1+1550,9`, `-685,0+1567,2`
- A | HubClient.get_task: `-687,2+1571,5`
- A | HubClient.list_tasks: `-695,0+1582,1`, `-697,0+1585,2`
- A | HubClient.complete_task: `-703,2+1593,5`
- A | HubClient.fail_task: `-706,2+1599,5`
- U | HubClient.checkpoint_task: `-709,1+1605,9`, `-718,0+1622,2`
- A | HubClient.find_memory: `-731,1+1637,8`, `-733,0+1646,2`
- L | HubClient.stream_events: `-786,1+1701,2`, `-788,1+1704,1`, `-824,2+1754,1`, `-831,2+1760,1`, `-863,1+1791,3`
- U | HubClient.stream_events: `-820,0+1736,14`

### D114 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:300bb98c11ab44e3718259800c68ecbe8419bd99`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,1`, `-18,2+20,2`, `-24,0+26,44`
- L | <module/text>: `-10,0+11,1`, `-40,2+86,52`
- A | _stop_owned_child: `-37,2+83,2`
- A | _acquire_start_lock: `-43,3+139,21`
- L | HubClient.__init__: `-49,1+163,8`
- U | HubClient.__init__: `-62,0+183,1`
- U | HubClient: `-96,0+218,6`, `-147,0+391,14`, `-158,1+416,48`, `-337,1+676,30`
- A | HubClient._pooled_open: `-115,1+243,18`, `-118,0+263,46`, `-121,1+312,5`, `-123,1+318,9`
- A | HubClient._open: `-131,0+334,41`
- A | HubClient._singleflight: `-162,1+467,1`, `-179,2+484,13`, `-184,1+500,4`
- L | HubClient.ensure_server: `-209,0+528,7`, `-237,1+564,1`, `-240,0+567,1`, `-241,2+569,2`, `-244,1+572,0`, `-246,6+573,4`, `-254,29+579,16`, `-286,0+598,2`, `-295,6+609,3`, `-303,1+614,1`, `-314,1+643,3`, `-316,1+647,9`
- U | HubClient.ensure_server: `-211,0+537,9`, `-212,1+547,0`, `-215,7+549,0`, `-229,1+556,1`, `-306,4+617,21`, `-312,0+640,1`
- L | HubClient.request: `-344,1+712,3`, `-400,4+818,0`, `-410,2+828,6`, `-417,1+839,5`
- U | HubClient.request.once: `-353,1+723,14`
- U | HubClient.request.execute: `-357,0+740,1`, `-359,0+743,2`, `-375,0+761,1`, `-380,1+767,6`, `-392,2+794,8`, `-395,1+803,1`, `-397,0+805,7`, `-398,1+813,4`
- L | HubClient.request.execute: `-385,2+777,4`, `-388,1+782,7`, `-390,0+790,2`
- U | HubClient.request: `-409,0+823,4`
- U | HubClient.get: `-420,1+846,5`, `-461,2+904,2`
- U | HubClient.get.once: `-432,2+862,11`
- U | HubClient.get.execute: `-441,1+880,1`, `-444,1+883,4`, `-454,1+896,2`, `-456,2+899,2`
- L | HubClient.get: `-468,1+911,5`
- U | HubClient.post: `-504,3+951,36`
- L | HubClient.coord: `-620,0+1100,1`
- U | HubClient.list_tasks: `-690,1+1171,6`, `-694,0+1180,2`
- A | HubClient.stream_events: `-779,1+1267,2`, `-781,1+1270,1`, `-813,0+1302,13`, `-817,2+1319,1`, `-824,2+1325,1`, `-844,0+1344,2`, `-856,1+1358,3`

### D115 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:6acfef8eadc2189ee11858725b18f8aef2a3df9e`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | HubClient._post_replay_safe: `-473,1+473,1`
- U | HubClient._post_replay_safe: `-475,0+475,6`
- L | HubClient: `-734,1+740,51`
- A | HubClient.continue_conversation: `-739,9+795,3`

### D116 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:7410dbb063b17ce799a191c3a9f8c04e4d19ac80`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | HubClient.request.execute: `-398,1+398,2`, `-402,2+403,2`

### D117 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:93513db42a11454ceee50efc38ffdd54778cb35c`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-18,1+18,1`
- U | HubClient.ensure_server: `-314,1+314,15`

### D118 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:be8d42d1c76225bc760922c49eac8fd439645b04`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-24,0+24,1`
- U | HubClient._singleflight: `-158,1+159,1`, `-180,1+181,3`
- L | HubClient._singleflight: `-162,1+163,1`
- U | HubClient.request: `-337,1+340,1`, `-344,1+347,4`, `-410,2+420,3`, `-416,0+427,3`, `-417,1+431,1`
- U | HubClient.request.execute: `-403,0+409,4`
- U | HubClient.get: `-461,2+475,3`, `-468,1+483,1`
- U | HubClient.post: `-504,1+519,1`, `-506,1+521,3`

### D119 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:f29fdf0fc307c02154aba4f2dd458933803512dd`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-19,1+19,1`, `-24,0+24,23`
- U | HubClient: `-337,1+360,26`
- U | HubClient.request: `-344,1+392,1`
- U | HubClient.post: `-504,3+552,51`
- L | HubClient.stream_events: `-779,1+875,2`, `-781,1+878,1`

### D120 src/local_ai_hub/client.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:667925e221905fb02baea07c6e7fcd41b6638246`; original `100644:f62252a56d9ad9e8d4f9ece4d51c0ac33518ea40`; pinned-current `100644:5851323a81190a063feb3795b7c5f83b10ced558`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-24,0+24,1`, `-28,0+29,6`
- U | HubClient._singleflight: `-158,1+165,1`, `-180,1+187,1`
- L | HubClient._singleflight: `-162,1+169,1`
- U | HubClient.request: `-337,1+344,9`, `-344,1+359,7`, `-410,2+431,2`, `-417,1+438,4`
- U | HubClient.request.execute: `-398,1+419,1`, `-402,2+423,2`
- U | HubClient.get: `-461,2+485,2`, `-468,1+492,1`
- U | HubClient.post: `-504,1+528,8`, `-506,1+537,9`

### D121 src/local_ai_hub/code_index.py

Disposition: `preserved-only-needs-integration`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1bb1b9108b58b2202099b45a2570925b39d397dd`; original `100644:605cc79123c859efdb464ce0b8f692f9292d77f7`; pinned-current `100644:bc03447d67c7557a150469ea5dc665db86b64cbb`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-34,0+34,4`
- L | CodeIndex._schema: `-64,0+68,1`
- U | CodeIndex._schema: `-122,0+127,5`
- L | CodeIndex._lang: `-161,0+171,1`
- L | CodeIndex: `-296,0+307,27`
- L | CodeIndex._parse_csharp: `-320,0+358,1`, `-335,0+374,1`
- U | CodeIndex._parse_csharp: `-368,1+408,4`, `-416,0+459,2`, `-420,1+465,1`, `-422,1+467,1`
- L | CodeIndex._parse_generic: `-481,0+526,2`
- U | CodeIndex._parse_generic: `-484,1+531,1`, `-486,1+533,1`
- U | CodeIndex.update_file: `-550,0+597,2`, `-552,1+601,1`, `-581,0+630,2`
- U | CodeIndex.update_files_batch: `-601,0+652,1`, `-608,0+660,1`, `-620,1+673,1`, `-687,0+740,4`, `-695,0+752,1`
- L | CodeIndex.update_files_batch: `-681,1+734,1`
- U | CodeIndex.find_callers: `-1358,0+1416,1`, `-1361,1+1420,2`, `-1363,1+1423,1`
- U | CodeIndex.find_callees: `-1377,0+1437,1`, `-1380,1+1441,2`, `-1382,1+1444,1`

### D122 src/local_ai_hub/code_index.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1bb1b9108b58b2202099b45a2570925b39d397dd`; original `100644:c0976617d5e6f19db3d9884154cb03636f83b95f`; pinned-current `100644:bc03447d67c7557a150469ea5dc665db86b64cbb`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-19,0+19,2`
- L | CodeIndex._schema: `-64,0+66,1`
- L | CodeIndex: `-122,1+125,6`
- L | CodeIndex._lang: `-161,0+169,1`
- U | CodeIndex: `-296,0+305,27`, `-537,0+582,19`
- L | CodeIndex._parse_csharp: `-320,0+356,1`, `-335,0+372,1`
- U | CodeIndex._parse_csharp: `-368,1+406,4`, `-416,0+457,2`, `-420,1+463,1`, `-422,1+465,1`
- L | CodeIndex._parse_generic: `-481,0+524,2`
- U | CodeIndex._parse_generic: `-484,1+529,1`, `-486,1+531,1`
- U | CodeIndex._parse_blob_get: `-507,1+552,1`, `-513,1+558,1`
- U | CodeIndex._parse_blob_put: `-525,1+570,1`, `-530,1+575,1`
- U | CodeIndex.update_file: `-550,0+614,2`, `-552,1+618,1`, `-555,2+621,2`, `-581,0+647,2`
- L | CodeIndex.update_file: `-572,1+638,1`
- U | CodeIndex.update_files_batch: `-597,1+665,4`, `-601,0+672,1`, `-608,0+680,1`, `-611,1+684,1`, `-620,1+693,1`, `-624,1+697,1`, `-695,0+773,1`
- L | CodeIndex.update_files_batch: `-640,1+713,1`, `-676,1+749,1`, `-681,1+754,1`, `-687,0+760,5`, `-690,1+768,1`
- U | CodeIndex.update_files_batch._parse_candidate: `-660,1+733,1`
- U | CodeIndex.impact: `-1172,1+1251,1`, `-1229,0+1308,47`, `-1263,0+1389,1`
- U | CodeIndex.find_callers: `-1358,0+1485,1`, `-1361,1+1489,2`, `-1363,1+1492,1`
- U | CodeIndex.find_callees: `-1377,0+1506,1`, `-1380,1+1510,2`, `-1382,1+1513,1`

### D123 src/local_ai_hub/code_index.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8e3cff316e9a257b6246229d501fba954edfe527`; original `100644:22af4167b1575c47f27263f84426261c2be13d03`; pinned-current `100644:bc03447d67c7557a150469ea5dc665db86b64cbb`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-13,1+13,0`, `-119,0+122,570`
- U | <module/text>: `-24,0+23,2`, `-28,0+29,1`, `-31,0+33,1`, `-32,1+35,1`
- A | _mask_non_code: `-160,1+733,3`, `-169,1+744,1`, `-194,0+769,3`, `-206,1+784,1`, `-209,1+787,14`, `-214,0+805,3`, `-228,1+822,15`, `-255,0+863,15`
- A | CodeIndex.__init__: `-289,0+912,4`
- L | CodeIndex: `-290,0+917,6`, `-418,0+1054,30`
- L | CodeIndex._schema: `-349,0+982,1`, `-362,0+996,1`
- A | CodeIndex._lang: `-407,1+1042,1`, `-412,0+1047,1`
- L | CodeIndex._parse_csharp: `-619,1+1285,10`, `-627,2+1302,3`, `-631,0+1307,2`
- U | CodeIndex._parse_csharp: `-667,0+1345,6`, `-679,1+1363,6`, `-681,0+1370,2`
- L | CodeIndex._parse_generic: `-702,2+1393,1`, `-705,2+1395,1`, `-711,2+1400,1`, `-714,1+1402,8`, `-734,1+1429,14`, `-736,0+1444,4`, `-752,0+1469,2`
- U | CodeIndex._parse_generic: `-750,1+1462,6`
- L | CodeIndex.files_needing_reindex: `-857,0+1576,4`, `-862,0+1585,1`, `-864,1+1588,1`, `-868,5+1592,15`
- L | CodeIndex.update_file: `-881,0+1615,15`, `-892,2+1642,2`
- U | CodeIndex.update_file: `-886,0+1635,1`, `-890,1+1640,1`, `-921,0+1671,1`
- L | CodeIndex.update_files_batch: `-940,0+1691,6`, `-945,0+1702,1`, `-947,1+1705,1`, `-964,1+1733,1`, `-977,1+1744,1`, `-989,2+1771,2`
- U | CodeIndex.update_files_batch: `-952,1+1710,1`, `-954,0+1712,2`, `-961,0+1721,1`, `-962,1+1723,9`, `-967,5+1736,3`, `-981,0+1748,2`, `-988,0+1757,13`, `-1007,0+1789,4`, `-1008,1+1794,14`, `-1034,5+1833,4`, `-1084,0+1882,1`
- A | CodeIndex.query: `-1236,1+2035,2`, `-1317,1+2117,1`
- A | CodeIndex.prune: `-1728,0+2528,1`
- L | CodeIndex.impact: `-1738,1+2539,1`, `-1740,1+2541,29`, `-1747,0+2576,1`, `-1755,1+2585,2`, `-1757,2+2588,12`, `-1766,0+2607,3`, `-1770,1+2614,1`, `-1772,1+2616,3`, `-1783,1+2629,1`, `-1785,1+2631,3`, `-1795,0+2643,154`, `-1796,2+2798,2`, `-1799,1+2801,3`, `-1816,1+2842,9`, `-1818,3+2852,9`
- U | CodeIndex.impact: `-1801,1+2805,23`, `-1829,0+2869,14`, `-1830,0+2884,2`
- U | CodeIndex.find_callers: `-1924,0+2980,1`, `-1925,8+2982,24`
- L | CodeIndex.find_callers: `-1935,1+3008,1`, `-1937,1+3010,11`
- U | CodeIndex.find_callees: `-1945,0+3028,1`, `-1946,8+3030,24`
- L | CodeIndex.find_callees: `-1956,1+3056,1`, `-1958,1+3058,11`

### D124 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 27:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:72d6bc2cf4fd8efef3f469eac594a241837325c3`; original `100644:5401eb9cf5c6ee9a8f545700747ac6d6ca390021`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S061 / c041d450a685c0c2f225270c7113c075aec585ae / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | CommandBroker.repair_loop: `-3414,0+3414,19`

### D125 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 12:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:72d6bc2cf4fd8efef3f469eac594a241837325c3`; original `100644:5ee8aeec0645841b9b09021b12cf188b9036a0ec`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S081 / 388086357ab954fbf208def00ba1ce5a60170598 / true / fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-7,0+8,1`, `-13,0+15,2`, `-24,1+28,1`, `-48,0+52,32`, `-85,1+136,84`, `-788,0+930,175`
- U | _RecoveredDaemonProcess.__init__: `-68,1+104,6`, `-71,0+112,1`
- U | _RecoveredDaemonProcess.poll: `-73,1+115,10`
- U | _stop_daemon_tree: `-592,0+726,8`
- U | CommandBroker.__init__: `-1070,0+1387,2`
- L | CommandBroker.__init__: `-1093,3+1412,48`
- U | CommandBroker._load_daemon_registry: `-1574,1+1938,1`, `-1576,0+1940,1`, `-1586,0+1951,1`, `-1594,1+1960,0`, `-1597,0+1962,16`, `-1598,4+1979,12`, `-1631,1+2020,5`, `-1634,0+2027,3`
- U | CommandBroker._persist_daemon_registry: `-1675,0+2071,1`, `-1685,1+2082,1`
- U | CommandBroker._key: `-2244,1+2641,8`, `-2246,1+2650,2`, `-2248,1+2653,1`, `-2251,1+2656,16`
- U | CommandBroker._attempt_key: `-2254,1+2674,1`, `-2257,1+2677,2`, `-2261,1+2682,16`
- U | CommandBroker._execute: `-2314,0+2750,3`, `-2315,0+2754,1`, `-2316,2+2756,3`, `-2344,0+2785,2`, `-2347,1+2790,0`, `-2370,0+2812,44`, `-2467,0+2967,2`, `-2490,0+2992,2`
- U | CommandBroker._execute._reader: `-2375,0+2861,5`, `-2376,2+2867,2`, `-2379,1+2870,4`, `-2384,1+2878,1`, `-2387,1+2881,1`, `-2389,4+2883,1`, `-2394,1+2885,1`, `-2399,4+2890,5`, `-2404,4+2896,1`, `-2415,0+2904,11`
- U | CommandBroker: `-2682,0+3186,184`
- U | CommandBroker.run: `-2684,1+3372,1`, `-2702,0+3390,2`, `-2705,0+3395,76`, `-2752,1+3518,5`, `-2770,1+3540,1`, `-2782,1+3552,1`, `-2803,1+3573,6`, `-2813,1+3588,1`, `-2817,1+3592,1`, `-2901,1+3676,13`, `-2985,1+3772,1`, `-2998,1+3785,1`, `-3018,0+3805,6`
- L | CommandBroker.run: `-2791,1+3561,1`, `-2799,1+3569,1`
- L | CommandBroker.preflight: `-3334,1+4127,0`
- U | CommandBroker.preflight: `-3338,2+4130,2`, `-3342,1+4134,1`
- U | CommandBroker.spawn_daemon: `-3838,0+4630,1`

### D126 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:72d6bc2cf4fd8efef3f469eac594a241837325c3`; original `100644:768e5500c43d439713b1ba8fbd324c4fc5d7f4a7`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,3`, `-7,0+10,1`, `-8,0+12,1`, `-24,1+30,1`, `-32,0+39,7`, `-65,0+111,31`, `-415,1+687,69`, `-419,15+759,57`, `-492,2+925,231`, `-1034,0+2231,18`
- U | <module/text>: `-13,0+18,1`, `-26,1+32,2`, `-48,0+62,32`, `-107,0+200,171`, `-386,0+650,8`, `-705,0+1358,189`, `-788,0+1803,182`
- U | _RecoveredDaemonProcess.__init__: `-68,1+145,4`, `-71,0+151,2`
- U | _RecoveredDaemonProcess.poll: `-73,1+155,13`
- A | _RecoveredDaemonProcess.kill: `-84,2+178,1`
- A | _acquire_rollback_root: `-464,1+846,12`, `-466,3+859,43`
- A | _restore_windows_atime: `-501,14+1163,0`, `-516,7+1164,0`, `-527,28+1168,5`
- U | _stop_daemon_tree: `-571,1+1189,1`, `-585,11+1207,8`
- L | _stop_daemon_tree: `-573,0+1191,3`, `-576,1+1197,2`
- A | _snapshot_rollback_scope: `-607,0+1226,1`, `-612,1+1232,1`, `-614,0+1234,1`, `-622,1+1243,1`, `-624,1+1245,0`, `-626,1+1246,6`, `-628,1+1253,10`, `-631,1+1265,1`, `-636,11+1270,13`, `-648,9+1284,0`, `-658,0+1285,13`, `-659,1+1299,4`, `-674,1+1317,1`, `-686,1+1329,3`, `-695,1+1340,4`, `-697,0+1345,5`
- L | _restore_rollback_scope: `-710,2+1552,13`, `-713,0+1566,2`, `-718,13+1735,5`, `-732,1+1741,1`, `-736,7+1745,14`, `-744,1+1760,3`, `-746,25+1764,21`, `-772,4+1786,2`, `-778,1+1790,4`
- U | _restore_rollback_scope: `-716,1+1571,163`
- A | CommandBroker.__init__: `-1070,0+2285,2`, `-1090,0+2307,4`, `-1093,3+2314,48`, `-1119,0+2385,1`
- L | CommandBroker: `-1126,0+2393,98`, `-1223,0+2597,74`, `-1655,1+3362,0`, `-1703,1+3427,0`, `-3057,0+6586,1`
- A | CommandBroker._require_task_worktree: `-1197,0+2562,2`, `-1220,1+2587,8`
- U | CommandBroker: `-1337,0+2785,77`, `-2261,0+4078,36`, `-2262,0+4115,52`, `-2666,0+4647,990`, `-2682,0+5653,214`, `-3933,1+7728,0`, `-4023,1+7817,18`
- A | CommandBroker._record_command_verification: `-1350,0+2875,7`, `-1351,1+2883,5`, `-1356,1+2892,5`, `-1359,1+2899,1`, `-1361,0+2901,65`, `-1376,0+2981,1`, `-1385,0+2991,14`, `-1410,1+3030,2`, `-1412,0+3033,31`
- A | CommandBroker._expire_daemon: `-1540,1+3192,1`
- L | CommandBroker._load_daemon_registry: `-1574,1+3226,8`, `-1594,1+3254,0`, `-1598,4+3293,4`, `-1607,0+3302,2`, `-1615,0+3312,2`, `-1622,0+3321,2`, `-1626,0+3327,2`
- U | CommandBroker._load_daemon_registry: `-1586,0+3245,1`, `-1597,0+3256,36`, `-1631,1+3334,1`, `-1633,0+3336,3`, `-1635,0+3341,1`
- U | CommandBroker._persist_daemon_registry: `-1671,0+3377,12`, `-1675,0+3393,2`, `-1677,0+3397,1`, `-1685,1+3406,4`
- L | CommandBroker.classify: `-1840,1+3563,1`, `-1845,1+3568,2`, `-1849,1+3573,10`, `-1867,1+3600,7`
- U | CommandBroker._classify_single: `-1886,1+3625,1`, `-1910,1+3649,3`
- L | CommandBroker._classify_single: `-1908,1+3647,1`, `-2004,1+3745,1`, `-2020,1+3761,1`, `-2041,0+3782,13`, `-2050,0+3804,21`, `-2062,1+3837,1`, `-2075,1+3850,1`, `-2077,1+3852,1`, `-2085,2+3860,16`, `-2089,2+3878,6`, `-2098,1+3891,1`, `-2100,1+3893,1`, `-2109,1+3902,1`, `-2113,1+3906,1`, `-2117,1+3910,1`, `-2127,1+3920,1`, `-2132,1+3925,1`, `-2148,1+3941,1`, `-2157,1+3950,1`, `-2166,1+3959,1`, `-2175,1+3968,1`, `-2186,1+3979,1`, `-2196,1+3989,1`
- U | CommandBroker._key: `-2244,1+4037,8`, `-2246,1+4046,2`, `-2248,1+4049,1`, `-2251,1+4052,16`
- U | CommandBroker._attempt_key: `-2254,1+4070,1`, `-2257,1+4073,2`
- L | CommandBroker._execute: `-2309,1+4214,1`, `-2317,1+4236,3`
- U | CommandBroker._execute: `-2314,0+4219,3`, `-2315,1+4223,12`, `-2344,0+4265,2`, `-2347,1+4270,0`, `-2370,0+4292,44`, `-2440,0+4419,1`, `-2441,1+4421,1`, `-2443,15+4423,12`, `-2467,0+4444,2`, `-2490,0+4469,2`
- U | CommandBroker._execute._reader: `-2375,0+4341,9`, `-2384,1+4363,1`, `-2387,1+4366,1`, `-2389,4+4368,1`, `-2394,1+4370,1`, `-2399,4+4375,5`, `-2404,4+4381,1`, `-2415,0+4389,5`
- L | CommandBroker._execute._reader: `-2376,2+4351,3`, `-2379,1+4355,4`
- L | CommandBroker.run: `-2684,1+5869,1`, `-2692,0+5877,1`, `-2703,0+5895,41`, `-2732,1+6078,34`, `-2752,21+6131,0`, `-2791,1+6149,1`, `-2799,1+6157,1`, `-2813,1+6176,1`, `-2834,0+6214,7`, `-2837,1+6224,1`, `-2839,0+6226,1`, `-2861,1+6273,22`, `-2864,0+6297,18`, `-2920,2+6406,4`, `-2940,1+6432,5`, `-2943,0+6439,2`, `-2945,1+6443,4`, `-2947,0+6448,3`, `-2987,12+6495,20`, `-3007,1+6523,4`, `-3032,0+6556,5`
- U | CommandBroker.run: `-2701,0+5887,1`, `-2702,0+5889,5`, `-2705,0+5938,99`, `-2708,11+6040,0`, `-2722,2+6043,27`, `-2782,1+6140,1`, `-2785,1+6143,1`, `-2803,1+6161,6`, `-2816,3+6179,20`, `-2840,6+6228,30`, `-2901,1+6352,35`, `-2917,0+6402,1`, `-2934,1+6422,5`, `-2985,1+6489,5`, `-3016,2+6535,7`
- L | CommandBroker.patch_and_verify: `-3066,0+6596,1`, `-3069,0+6600,3`, `-3071,1+6605,1`, `-3115,6+6719,20`, `-3236,0+6857,3`, `-3241,1+6870,6`, `-3243,1+6877,0`, `-3272,1+6905,1`
- U | CommandBroker.patch_and_verify: `-3074,9+6608,14`, `-3095,0+6634,65`, `-3173,1+6791,0`, `-3177,2+6794,2`, `-3191,1+6808,5`, `-3237,0+6861,2`, `-3239,1+6865,4`, `-3278,1+6911,5`, `-3287,2+6924,8`
- U | CommandBroker.patch_and_verify._do_rollback: `-3150,1+6768,1`
- L | CommandBroker.preflight: `-3334,1+6977,0`
- U | CommandBroker.preflight: `-3338,2+6980,2`, `-3342,1+6984,1`
- U | CommandBroker.repair_loop: `-3412,0+7054,19`
- L | CommandBroker.spawn_daemon: `-3741,1+7402,1`, `-3793,0+7454,1`, `-3795,1+7457,1`, `-3797,1+7459,1`, `-3802,0+7464,34`, `-3807,0+7528,65`, `-3812,0+7598,2`, `-3823,0+7611,3`, `-3833,20+7624,0`, `-3873,2+7644,1`, `-3876,1+7646,7`, `-3881,0+7657,1`, `-3882,0+7659,17`, `-3889,1+7683,1`, `-3906,1+7700,1`, `-3915,1+7709,1`
- U | CommandBroker.spawn_daemon: `-3803,0+7499,25`, `-3932,0+7726,1`
- L | CommandBroker._stop_daemon: `-4029,0+7840,12`
- A | CommandBroker.stash_save: `-4477,1+8300,7`, `-4480,1+8309,10`
- A | CommandBroker.stash_restore: `-4488,1+8326,1`, `-4491,1+8329,10`
- A | CommandBroker.diff_hunk_stage: `-4579,1+8426,1`, `-4584,0+8431,9`, `-4589,2+8445,1`, `-4601,2+8456,2`

### D127 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 28:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:72d6bc2cf4fd8efef3f469eac594a241837325c3`; original `100644:cd50bc3847a426374ea20739b64251fd05ee6329`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S060 / f8deb79389c263ccff9d0b961bf0017791fd9570 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | CommandBroker._mark_rollback_outcome_unknown: `-2682,0+2682,24`
- U | CommandBroker.run: `-2920,2+2944,1`, `-2985,1+3008,1`, `-2998,1+3021,1`, `-3007,1+3030,2`, `-3016,2+3040,1`
- U | CommandBroker.spawn_daemon: `-3740,3+3763,1`

### D128 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:72d6bc2cf4fd8efef3f469eac594a241837325c3`; original `100644:eac5590c7bd1bcb898872c131296c94b8a04a33b`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,3`, `-7,0+10,1`, `-8,0+12,1`, `-24,1+30,1`, `-32,0+39,7`, `-65,0+111,31`, `-415,1+687,69`, `-419,15+759,57`, `-492,2+925,231`, `-1034,0+2231,18`
- U | <module/text>: `-13,0+18,1`, `-26,1+32,2`, `-48,0+62,32`, `-107,0+200,171`, `-386,0+650,8`, `-705,0+1358,189`, `-788,0+1803,182`
- U | _RecoveredDaemonProcess.__init__: `-68,1+145,4`, `-71,0+151,2`
- U | _RecoveredDaemonProcess.poll: `-73,1+155,13`
- A | _RecoveredDaemonProcess.kill: `-84,2+178,1`
- A | _acquire_rollback_root: `-464,1+846,12`, `-466,3+859,43`
- A | _restore_windows_atime: `-501,14+1163,0`, `-516,7+1164,0`, `-527,28+1168,5`
- U | _stop_daemon_tree: `-571,1+1189,1`, `-585,11+1207,8`
- L | _stop_daemon_tree: `-573,0+1191,3`, `-576,1+1197,2`
- A | _snapshot_rollback_scope: `-607,0+1226,1`, `-612,1+1232,1`, `-614,0+1234,1`, `-622,1+1243,1`, `-624,1+1245,0`, `-626,1+1246,6`, `-628,1+1253,10`, `-631,1+1265,1`, `-636,11+1270,13`, `-648,9+1284,0`, `-658,0+1285,13`, `-659,1+1299,4`, `-674,1+1317,1`, `-686,1+1329,3`, `-695,1+1340,4`, `-697,0+1345,5`
- L | _restore_rollback_scope: `-710,2+1552,13`, `-713,0+1566,2`, `-718,13+1735,5`, `-732,1+1741,1`, `-736,7+1745,14`, `-744,1+1760,3`, `-746,25+1764,21`, `-772,4+1786,2`, `-778,1+1790,4`
- U | _restore_rollback_scope: `-716,1+1571,163`
- A | CommandBroker.__init__: `-1070,0+2285,2`, `-1090,0+2307,4`, `-1093,3+2314,48`, `-1119,0+2385,1`
- L | CommandBroker: `-1126,0+2393,98`, `-1223,0+2597,74`, `-1655,1+3362,0`, `-1703,1+3427,0`, `-3057,0+6559,1`
- A | CommandBroker._require_task_worktree: `-1197,0+2562,2`, `-1220,1+2587,8`
- U | CommandBroker: `-1337,0+2785,77`, `-2261,0+4070,36`, `-2262,0+4107,52`, `-2666,0+4639,971`, `-2682,0+5626,214`, `-3933,1+7701,0`, `-4023,1+7790,18`
- A | CommandBroker._record_command_verification: `-1350,0+2875,7`, `-1351,1+2883,5`, `-1356,1+2892,5`, `-1359,1+2899,1`, `-1361,0+2901,65`, `-1376,0+2981,1`, `-1385,0+2991,14`, `-1410,1+3030,2`, `-1412,0+3033,31`
- A | CommandBroker._expire_daemon: `-1540,1+3192,1`
- L | CommandBroker._load_daemon_registry: `-1574,1+3226,8`, `-1594,1+3254,0`, `-1598,4+3293,4`, `-1607,0+3302,2`, `-1615,0+3312,2`, `-1622,0+3321,2`, `-1626,0+3327,2`
- U | CommandBroker._load_daemon_registry: `-1586,0+3245,1`, `-1597,0+3256,36`, `-1631,1+3334,1`, `-1633,0+3336,3`, `-1635,0+3341,1`
- U | CommandBroker._persist_daemon_registry: `-1671,0+3377,12`, `-1675,0+3393,2`, `-1677,0+3397,1`, `-1685,1+3406,4`
- L | CommandBroker.classify: `-1840,1+3563,1`, `-1845,1+3568,2`, `-1849,1+3573,10`, `-1867,1+3600,7`
- U | CommandBroker._classify_single: `-1886,1+3625,1`, `-1910,1+3649,3`, `-2085,2+3860,8`
- L | CommandBroker._classify_single: `-1908,1+3647,1`, `-2004,1+3745,1`, `-2020,1+3761,1`, `-2041,0+3782,13`, `-2050,0+3804,21`, `-2062,1+3837,1`, `-2075,1+3850,1`, `-2077,1+3852,1`, `-2089,2+3870,6`, `-2098,1+3883,1`, `-2100,1+3885,1`, `-2109,1+3894,1`, `-2113,1+3898,1`, `-2117,1+3902,1`, `-2127,1+3912,1`, `-2132,1+3917,1`, `-2148,1+3933,1`, `-2157,1+3942,1`, `-2166,1+3951,1`, `-2175,1+3960,1`, `-2186,1+3971,1`, `-2196,1+3981,1`
- U | CommandBroker._key: `-2244,1+4029,8`, `-2246,1+4038,2`, `-2248,1+4041,1`, `-2251,1+4044,16`
- U | CommandBroker._attempt_key: `-2254,1+4062,1`, `-2257,1+4065,2`
- L | CommandBroker._execute: `-2309,1+4206,1`, `-2317,1+4228,3`
- U | CommandBroker._execute: `-2314,0+4211,3`, `-2315,1+4215,12`, `-2344,0+4257,2`, `-2347,1+4262,0`, `-2370,0+4284,44`, `-2440,0+4411,1`, `-2441,1+4413,1`, `-2443,15+4415,12`, `-2467,0+4436,2`, `-2490,0+4461,2`
- U | CommandBroker._execute._reader: `-2375,0+4333,9`, `-2384,1+4355,1`, `-2387,1+4358,1`, `-2389,4+4360,1`, `-2394,1+4362,1`, `-2399,4+4367,5`, `-2404,4+4373,1`, `-2415,0+4381,5`
- L | CommandBroker._execute._reader: `-2376,2+4343,3`, `-2379,1+4347,4`
- L | CommandBroker.run: `-2684,1+5842,1`, `-2692,0+5850,1`, `-2703,0+5868,41`, `-2732,1+6026,34`, `-2791,1+6122,1`, `-2799,1+6130,1`, `-2813,1+6149,1`, `-2834,0+6187,7`, `-2837,1+6197,1`, `-2839,0+6199,1`, `-2861,1+6246,22`, `-2864,0+6270,18`, `-2920,2+6379,4`, `-2940,1+6405,5`, `-2943,0+6412,2`, `-2945,1+6416,4`, `-2947,0+6421,3`, `-2987,12+6468,20`, `-3007,1+6496,4`, `-3032,0+6529,5`
- U | CommandBroker.run: `-2701,0+5860,1`, `-2702,0+5862,5`, `-2705,0+5911,99`, `-2708,11+6013,0`, `-2722,2+6016,2`, `-2752,4+6079,8`, `-2770,1+6101,1`, `-2782,1+6113,1`, `-2785,1+6116,1`, `-2803,1+6134,6`, `-2816,3+6152,20`, `-2840,6+6201,30`, `-2901,1+6325,35`, `-2917,0+6375,1`, `-2934,1+6395,5`, `-2985,1+6462,5`, `-3016,2+6508,7`
- L | CommandBroker.patch_and_verify: `-3066,0+6569,1`, `-3069,0+6573,3`, `-3071,1+6578,1`, `-3115,6+6692,20`, `-3236,0+6830,3`, `-3241,1+6843,6`, `-3243,1+6850,0`, `-3272,1+6878,1`
- U | CommandBroker.patch_and_verify: `-3074,9+6581,14`, `-3095,0+6607,65`, `-3173,1+6764,0`, `-3177,2+6767,2`, `-3191,1+6781,5`, `-3237,0+6834,2`, `-3239,1+6838,4`, `-3278,1+6884,5`, `-3287,2+6897,8`
- U | CommandBroker.patch_and_verify._do_rollback: `-3150,1+6741,1`
- L | CommandBroker.preflight: `-3334,1+6950,0`
- U | CommandBroker.preflight: `-3338,2+6953,2`, `-3342,1+6957,1`
- U | CommandBroker.repair_loop: `-3412,0+7027,19`
- L | CommandBroker.spawn_daemon: `-3741,1+7375,1`, `-3793,0+7427,1`, `-3795,1+7430,1`, `-3797,1+7432,1`, `-3802,0+7437,34`, `-3807,0+7501,65`, `-3812,0+7571,2`, `-3823,0+7584,3`, `-3833,20+7597,0`, `-3873,2+7617,1`, `-3876,1+7619,7`, `-3881,0+7630,1`, `-3882,0+7632,17`, `-3889,1+7656,1`, `-3906,1+7673,1`, `-3915,1+7682,1`
- U | CommandBroker.spawn_daemon: `-3803,0+7472,25`, `-3932,0+7699,1`
- L | CommandBroker._stop_daemon: `-4029,0+7813,12`
- A | CommandBroker.stash_save: `-4477,1+8273,7`, `-4480,1+8282,10`
- A | CommandBroker.stash_restore: `-4488,1+8299,1`, `-4491,1+8302,10`
- A | CommandBroker.diff_hunk_stage: `-4579,1+8399,1`, `-4584,0+8404,9`, `-4589,2+8418,1`, `-4601,2+8429,2`

### D129 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7b5c85016140c9451667da5dca900ff93449ec68`; original `100644:5cb8044d533bb24c563156d92ac01b003cf93018`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | CommandBroker.repair_loop: `-2787,0+2787,12`

### D130 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7b5c85016140c9451667da5dca900ff93449ec68`; original `100644:da1e36d57584977df86a1345aef9a43a14e6b43a`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | CommandBroker.__init__: `-746,3+746,3`
- U | CommandBroker.run: `-2351,0+2351,2`

### D131 src/local_ai_hub/commands.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8d688eed4deabf9ec7295c9afcf9a7d02b28eacf`; original `100644:0f4be75a06d11c4c88359ccbcf459f8d8fb4382e`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-8,0+9,1`, `-26,1+28,2`, `-32,0+35,5`, `-33,0+41,1`, `-107,0+163,171`, `-386,0+613,45`
- L | <module/text>: `-65,0+74,31`, `-415,1+687,69`, `-419,15+759,57`, `-492,2+925,231`, `-705,0+1358,218`, `-1034,0+2101,18`
- U | _RecoveredDaemonProcess.__init__: `-68,1+108,4`, `-71,0+114,2`
- U | _RecoveredDaemonProcess.poll: `-73,1+118,13`
- A | _RecoveredDaemonProcess.kill: `-84,2+141,1`
- A | _acquire_rollback_root: `-464,1+846,12`, `-466,3+859,43`
- A | _restore_windows_atime: `-501,14+1163,0`, `-516,7+1164,0`, `-527,28+1168,5`
- U | _stop_daemon_tree: `-571,1+1189,1`, `-585,11+1207,8`
- L | _stop_daemon_tree: `-573,0+1191,3`, `-576,1+1197,2`
- A | _snapshot_rollback_scope: `-607,0+1226,1`, `-612,1+1232,1`, `-614,0+1234,1`, `-622,1+1243,1`, `-624,1+1245,0`, `-626,1+1246,6`, `-628,1+1253,10`, `-631,1+1265,1`, `-636,11+1270,13`, `-648,9+1284,0`, `-658,0+1285,13`, `-659,1+1299,4`, `-674,1+1317,1`, `-686,1+1329,3`, `-695,1+1340,4`, `-697,0+1345,5`
- A | _restore_rollback_scope: `-710,2+1581,13`, `-713,0+1595,2`, `-716,1+1600,186`, `-718,13+1787,5`, `-732,1+1793,1`, `-736,7+1797,14`, `-744,1+1812,3`, `-746,25+1816,21`, `-772,4+1838,2`, `-778,1+1842,4`
- L | CommandBroker.__init__: `-1090,0+2175,4`, `-1119,0+2208,1`
- U | CommandBroker: `-1126,0+2216,24`, `-1223,0+2371,73`, `-1337,0+2558,80`, `-2243,0+3859,72`, `-2646,0+4354,1104`, `-2662,0+5474,19`
- U | CommandBroker.authorize_auxiliary_action: `-1162,0+2276,30`, `-1176,0+2320,1`, `-1178,1+2323,1`
- U | CommandBroker._require_task_worktree: `-1220,0+2365,3`
- L | CommandBroker._record_command_verification: `-1344,0+2645,1`, `-1371,1+2771,1`
- U | CommandBroker._record_command_verification: `-1348,0+2650,3`, `-1349,0+2654,1`, `-1350,1+2656,6`, `-1357,0+2668,67`, `-1358,1+2736,2`, `-1360,0+2739,1`, `-1362,0+2742,2`, `-1363,1+2745,1`, `-1365,0+2747,2`, `-1368,0+2752,16`, `-1369,1+2769,1`, `-1376,8+2776,13`, `-1388,1+2793,10`, `-1390,0+2804,30`
- A | CommandBroker._expire_daemon: `-1520,1+2964,1`
- L | CommandBroker._load_daemon_registry: `-1554,1+2998,8`, `-1574,1+3026,0`, `-1578,4+3065,4`, `-1587,0+3074,2`, `-1595,0+3084,2`, `-1602,0+3093,2`, `-1606,0+3099,2`
- U | CommandBroker._load_daemon_registry: `-1566,0+3017,1`, `-1577,0+3028,36`, `-1611,1+3106,1`, `-1613,0+3108,3`, `-1615,0+3113,1`
- U | CommandBroker._persist_daemon_registry: `-1651,0+3150,12`, `-1655,0+3166,2`, `-1657,0+3170,1`, `-1665,1+3179,4`
- L | CommandBroker.classify: `-1820,1+3337,1`, `-1825,1+3342,2`, `-1829,1+3347,10`, `-1847,1+3374,7`
- L | CommandBroker._classify_single: `-1888,1+3421,1`, `-1984,1+3519,1`, `-2000,1+3535,1`, `-2055,1+3664,1`, `-2057,1+3666,1`, `-2069,2+3681,6`
- U | CommandBroker._classify_single: `-1890,1+3423,3`, `-2021,0+3556,38`, `-2023,0+3596,2`, `-2030,0+3605,32`, `-2042,1+3649,3`, `-2065,2+3674,5`
- L | CommandBroker._execute: `-2289,1+3977,1`
- U | CommandBroker._execute: `-2295,1+3983,15`, `-2297,1+3999,1`, `-2420,0+4122,1`, `-2421,1+4124,3`, `-2423,15+4128,18`
- L | CommandBroker.run: `-2672,0+5503,1`, `-2894,1+5857,9`, `-2896,0+5867,1`, `-2913,1+5887,6`, `-2985,1+5981,4`, `-2991,0+5990,1`
- U | CommandBroker.run: `-2681,0+5513,1`, `-2682,0+5515,2`, `-2685,0+5520,11`, `-2688,11+5534,0`, `-2702,1+5537,1`, `-2712,2+5547,19`, `-2716,1+5568,2`, `-2720,2+5573,11`, `-2734,2+5596,2`, `-2798,1+5660,1`, `-2803,11+5665,14`, `-2822,1+5687,1`, `-2840,1+5705,20`, `-2843,0+5727,30`, `-2880,1+5794,50`, `-2899,2+5871,4`, `-2919,1+5898,5`, `-2924,1+5907,4`, `-2926,8+5912,12`, `-2964,1+5954,5`, `-2966,11+5960,13`, `-2994,2+5994,9`, `-3010,0+6017,3`, `-3027,0+6037,1`, `-3030,0+6041,2`
- L | CommandBroker: `-3035,0+6048,1`, `-4001,1+7406,18`
- L | CommandBroker.patch_and_verify: `-3044,0+6058,1`, `-3093,6+6182,20`, `-3214,0+6320,3`, `-3215,0+6324,3`, `-3217,1+6329,4`, `-3250,1+6370,1`
- U | CommandBroker.patch_and_verify: `-3047,0+6062,3`, `-3049,1+6067,1`, `-3052,9+6070,14`, `-3073,0+6096,66`, `-3151,1+6254,0`, `-3155,2+6257,2`, `-3169,1+6271,5`, `-3219,1+6334,6`, `-3256,1+6376,5`, `-3265,2+6389,8`
- U | CommandBroker.patch_and_verify._do_rollback: `-3128,1+6231,1`
- L | CommandBroker.repair_loop: `-3371,0+6501,4`, `-3378,1+6512,49`, `-3381,1+6563,4`, `-3425,1+6647,2`, `-3427,1+6650,17`, `-3431,6+6670,15`, `-3441,8+6689,0`, `-3451,1+6691,7`, `-3537,8+6783,0`
- U | CommandBroker.repair_loop: `-3390,0+6575,37`
- A | CommandBroker.format: `-3572,0+6810,3`, `-3577,0+6818,8`, `-3617,1+6866,12`
- A | CommandBroker.lint_fix: `-3628,0+6888,3`, `-3633,0+6896,8`, `-3673,1+6944,12`
- U | CommandBroker.spawn_daemon: `-3718,3+7000,1`, `-3781,0+7096,25`
- L | CommandBroker.spawn_daemon: `-3771,0+7051,1`, `-3773,1+7054,1`, `-3775,1+7056,1`, `-3780,0+7061,34`, `-3785,0+7125,65`, `-3790,0+7195,2`, `-3801,0+7208,3`, `-3811,20+7221,0`, `-3851,2+7241,1`, `-3854,1+7243,7`, `-3859,0+7254,1`, `-3860,0+7256,17`, `-3867,1+7280,1`, `-3884,1+7297,1`, `-3893,1+7306,1`, `-3910,0+7323,1`
- A | CommandBroker.daemon_status: `-3912,1+7326,3`, `-3918,1+7334,1`, `-3922,1+7338,0`, `-3925,3+7340,0`, `-3938,3+7350,0`, `-3951,0+7360,1`, `-3962,1+7372,0`, `-3964,0+7373,2`, `-3968,3+7379,0`, `-3977,1+7385,0`, `-3982,1+7389,0`, `-3988,0+7394,1`, `-3997,2+7404,0`
- A | CommandBroker._stop_daemon: `-4007,0+7429,12`, `-4020,5+7454,2`, `-4039,1+7470,6`, `-4050,1+7486,6`
- L | CommandBroker.stash_save: `-4455,1+7896,7`
- U | CommandBroker.stash_save: `-4458,1+7905,10`
- L | CommandBroker.stash_restore: `-4466,1+7922,1`
- U | CommandBroker.stash_restore: `-4469,1+7925,10`
- L | CommandBroker.diff_hunk_stage: `-4557,1+8022,1`, `-4567,2+8041,1`, `-4579,2+8052,2`
- U | CommandBroker.diff_hunk_stage: `-4562,0+8027,9`

### D132 src/local_ai_hub/commands.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 39:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a9e927362f21fd3b381c30d771dd0059a124937f`; original `100644:5fc5c1144574b74523816c4bba76ec8b751907b2`; pinned-current `100644:0dda384530164a2a26ab985be9a0fdd7e8d8899f`.

Exact checkpoint/owner witnesses: `S051 / da3d594519e72544279d47123bf550d5ac78e101 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | _snapshot_patch_targets: `-359,0+359,3`, `-363,2+366,0`, `-369,2+370,0`

### D133 src/local_ai_hub/config.py

Disposition: `integrated-current`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2637d066a8f1df2cd3b48bb94babdfea9b69ac28`; original `100644:f25929dbf07595eba0a3ccc086030ddf2a566d89`; pinned-current `100644:f25929dbf07595eba0a3ccc086030ddf2a566d89`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | validate_config: `-74,1+74,1`, `-134,0+134,3`, `-241,7+244,33`

### D134 src/local_ai_hub/context_ledger.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:934ca6a39b000598fb7fafd2cfd241020d4d2430`; original `100644:769c930c48e81f22990514b87a9f5270413c7ed5`; pinned-current `100644:769c930c48e81f22990514b87a9f5270413c7ed5`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-7,0+7,1`, `-8,0+9,1`, `-9,0+11,8`, `-109,1+262,69`
- B | ContextLedger.__init__: `-14,2+24,3`, `-18,0+29,2`, `-19,0+32,2`
- B | ContextLedger.record: `-29,0+44,6`, `-33,0+54,7`, `-36,3+64,8`, `-45,1+78,11`, `-51,1+94,11`
- B | ContextLedger.compile: `-85,0+138,2`, `-86,0+141,9`, `-87,6+151,40`, `-94,1+192,26`, `-96,2+219,27`, `-99,1+247,6`, `-104,1+257,1`, `-106,1+259,1`

### D135 src/local_ai_hub/conversations.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 20:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:61886fc327436ccb5867212378b337ddaa4643db`; original `100644:77286f74c41f702673b1aa4293ec6d847aa28e33`; pinned-current `100644:522390fccd8f7cea9111bfcd228700c48965815b`.

Exact checkpoint/owner witnesses: `S071 / 9b1b40906612634df8a0a3bedbb217a337c67cb4 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | ConversationStore: `-42,0+42,7`
- A | ConversationStore._start: `-47,0+54,1`

### D136 src/local_ai_hub/conversations.py

Disposition: `integrated-current`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:acc2be1e7e853098805e355ab030dbc6b18e0077`; original `100644:522390fccd8f7cea9111bfcd228700c48965815b`; pinned-current `100644:522390fccd8f7cea9111bfcd228700c48965815b`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | ConversationStore: `-42,0+42,7`
- B | ConversationStore._start: `-47,0+54,1`

### D137 src/local_ai_hub/conversations.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e68d8e9a802d46d45750d495217703af795601c8`; original `100644:522390fccd8f7cea9111bfcd228700c48965815b`; pinned-current `100644:522390fccd8f7cea9111bfcd228700c48965815b`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | ConversationStore: `-41,1+41,8`
- B | ConversationStore._start: `-47,0+54,1`, `-52,1+60,8`
- B | ConversationStore.complete: `-74,0+89,2`, `-82,1+99,1`
- B | ConversationStore.abort: `-87,0+104,2`, `-91,1+110,1`
- B | <module/text>: `-115,11+134,0`

### D138 src/local_ai_hub/dashboard.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5d925fb03ff7beb7b98eef8a061db04499c0d47b`; original `100644:893a0de3af7be687e2cfc8e49c5133c948a07577`; pinned-current `100644:8c2b1615c154af30603e3e1a6638c28609821dbe`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5126,1+5126,1`

### D139 src/local_ai_hub/dashboard.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5d925fb03ff7beb7b98eef8a061db04499c0d47b`; original `100644:cffd432d97b9a2e990a85a2cf2553f59b7cc0e26`; pinned-current `100644:8c2b1615c154af30603e3e1a6638c28609821dbe`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-2,0+2,2`, `-424,0+432,1`, `-590,1+609,1`, `-603,1+622,2`, `-771,2+791,2`, `-774,40+794,1`, `-1244,1+1225,1`, `-1350,2+1331,2`, `-2697,1+2678,2`, `-2700,0+2682,1`, `-2701,1+2684,1`, `-3689,1+3672,1`, `-3750,1+3733,1`, `-3784,1+3767,1`, `-4606,2+4667,2`, `-4708,1+4773,1`, `-4733,1+4798,1`, `-4905,1+4970,4`, `-5004,1+5072,1`, `-5068,1+5136,1`, `-5122,0+5190,1`, `-5126,1+5195,3`, `-5187,1+5258,1`, `-5191,1+5262,1`, `-5194,1+5265,0`, `-5525,0+5595,64`, `-5527,4+5661,1`, `-5532,0+5663,2`, `-5535,0+5668,2`, `-5536,31+5671,3`
- L | <module/text>: `-267,0+269,1`, `-281,0+284,5`, `-520,1+529,1`, `-585,0+594,10`, `-3942,0+3925,1`, `-4515,0+4499,77`, `-4613,0+4674,4`, `-5036,1+5104,1`

### D140 src/local_ai_hub/dashboard.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b0c641edbe5e4c2ec14baad9018384c5c2d44259`; original `100644:701a6cc0697762fc01698bb14f7e15da2d5e770e`; pinned-current `100644:8c2b1615c154af30603e3e1a6638c28609821dbe`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-267,0+267,1`, `-281,0+282,5`, `-520,1+526,1`, `-834,1+840,1`, `-3952,0+3958,1`, `-4525,0+4532,77`, `-4623,0+4707,4`, `-5047,1+5135,1`
- U | <module/text>: `-5133,0+5221,1`, `-5138,0+5227,1`, `-5198,1+5288,1`, `-5202,1+5292,1`, `-5205,1+5295,1`

### D141 src/local_ai_hub/dashboard.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d1fc1bef05e11b26ecf209cc8891a978c5cf4752`; original `100644:df993f17fb55cfe808ed809a2bcc8ec273ad7431`; pinned-current `100644:8c2b1615c154af30603e3e1a6638c28609821dbe`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-1668,0+1668,2`, `-1676,1+1678,4`, `-1686,0+1691,4`, `-1697,0+1706,2`, `-1899,1+1910,1`, `-2774,5+2785,7`, `-2780,2+2793,3`, `-2783,6+2797,10`, `-2790,1+2808,2`, `-4535,1+4554,1`, `-5185,1+5204,15`, `-5255,1+5294,2`, `-5273,1+5313,18`, `-5275,1+5332,2`, `-5279,1+5337,3`, `-5281,4+5341,0`, `-5612,1+5668,1`, `-5621,1+5677,2`, `-5624,4+5681,18`, `-5630,1+5701,1`, `-5635,2+5706,1`, `-5638,1+5708,111`, `-5640,3+5820,4`, `-5645,1+5826,1`, `-5647,3+5828,15`, `-5651,1+5844,8`
- U | <module/text>: `-5208,0+5241,6`, `-5211,1+5250,1`

### D142 src/local_ai_hub/debug_traces.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c0fc14dc7c46360d4387ec0eb9f82c1cebec991c`; original `100644:75e227203dc3f1c2e7a20af7d8f26b4528f53ef6`; pinned-current `100644:e7a5ace34accf3a59a71b1f3073a2f8a9a2d96e9`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | DebugTraceStore.list: `-794,6+794,10`

### D143 src/local_ai_hub/debug_traces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d61ee8410a82c75f8208dfc220af39a5ed334f30`; original `100644:65d3d74ca3a69df3b38bf2ff3f786da7c4152629`; pinned-current `100644:e7a5ace34accf3a59a71b1f3073a2f8a9a2d96e9`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-25,0+25,6`
- A | DebugTraceStore.__init__: `-34,1+40,12`
- U | DebugTraceStore.detail: `-353,1+370,21`, `-362,4+399,13`, `-367,0+413,6`, `-370,1+422,13`, `-372,2+436,144`
- U | DebugTraceStore.stats: `-456,1+662,1`, `-458,1+664,7`

### D144 src/local_ai_hub/debug_traces.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d61ee8410a82c75f8208dfc220af39a5ed334f30`; original `100644:71c56b16e236916ddf850610b85cf838476deb16`; pinned-current `100644:e7a5ace34accf3a59a71b1f3073a2f8a9a2d96e9`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | DebugTraceStore.__init__: `-34,1+34,12`
- A | DebugTraceStore.detail: `-362,1+373,5`, `-373,1+388,1`
- A | DebugTraceStore.stats: `-456,1+471,1`

### D145 src/local_ai_hub/defaults.toml

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:762dd2faaa30688af2df88f69c966107c5364e64`; original `100644:20b83731c8426489e6bf6561313f3f6de3074354`; pinned-current `100644:55c7a44fb893f5b27293901f131fd25dfd5d594a`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-463,0+463,2`

### D146 src/local_ai_hub/defaults.toml

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 22:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:762dd2faaa30688af2df88f69c966107c5364e64`; original `100644:db7bbadececfa087b7eca575998986a7137ce07b`; pinned-current `100644:55c7a44fb893f5b27293901f131fd25dfd5d594a`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-471,0+471,1`

### D147 src/local_ai_hub/deterministic.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:09635ae79d93cf37958939b34c0305a2c957cd8f`; original `100644:cdf451f72249ef7ea83915936b105e8c82b5d16e`; pinned-current `100644:c35d4fa96511b0b336068cdf3b88bb309b8b1031`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | DeterministicEngine.test_matrix: `-4150,1+4150,1`

### D148 src/local_ai_hub/deterministic.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ba36b2d9d9b3e4a061f392425f80ad553b716331`; original `100644:03fb62bf2d6b7cd6137d1b791e89a72635356445`; pinned-current `100644:c35d4fa96511b0b336068cdf3b88bb309b8b1031`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-25,0+25,1`
- A | DeterministicEngine.query: `-1985,0+1986,16`, `-1986,0+2003,5`
- A | DeterministicEngine.render_answer: `-2703,0+2725,3`
- L | DeterministicEngine.affected_tests: `-4239,1+4264,5`
- U | DeterministicEngine.affected_tests: `-4241,1+4270,16`
- A | DeterministicEngine.code_invariants: `-4775,1+4819,1`, `-4778,0+4822,20`, `-4781,1+4845,24`, `-4783,1+4870,15`, `-4785,1+4886,9`, `-4792,0+4901,3`, `-4793,3+4905,1`, `-4797,0+4907,2`, `-4847,0+4959,1`, `-4848,1+4961,0`, `-4851,3+4963,6`, `-4855,0+4970,11`, `-4856,0+4982,1`, `-4857,1+4984,2`, `-4860,0+4988,6`
- A | DeterministicEngine.extract_api_spec: `-5960,1+6094,1`, `-5967,1+6101,5`, `-5969,1+6107,1`, `-5980,1+6118,1`, `-6009,0+6147,8`, `-6010,0+6156,2`, `-6022,0+6170,2`, `-6033,0+6183,2`, `-6047,0+6199,2`, `-6058,0+6212,2`, `-6077,1+6233,6`

### D149 src/local_ai_hub/deterministic.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d1fb60a8d68cde08f2983d46aaa6eb5e459336b6`; original `100644:95979178c2d2c56f3df6102094fa05b6640102e4`; pinned-current `100644:c35d4fa96511b0b336068cdf3b88bb309b8b1031`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | DeterministicEngine.__init__: `-152,1+152,1`

### D150 src/local_ai_hub/deterministic.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 8:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d1fb60a8d68cde08f2983d46aaa6eb5e459336b6`; original `100644:a8e5b705609df85ca61db2509251a8f108ac1d36`; pinned-current `100644:c35d4fa96511b0b336068cdf3b88bb309b8b1031`.

Exact checkpoint/owner witnesses: `S037 / 5b16828e44f5ca0b09c265b2a5a034fe94bbddea / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`
- A | DeterministicEngine.profile_digest: `-4979,0+4980,5`, `-4982,0+4988,2`, `-4983,4+4991,13`

### D151 src/local_ai_hub/embeddings.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e05138b9f03569eb15a460f4ad7e048670604bc6`; original `100644:d2f99ecc33439cace857e359046ab4f14c594123`; pinned-current `100644:a1d8939c897515f3680c102e1d6edff3be0c766f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-17,0+17,1`
- L | EmbeddingModel: `-64,0+65,32`, `-85,0+118,55`, `-92,0+180,74`, `-251,0+430,21`, `-267,0+467,7`
- A | EmbeddingModel._embedding_cache_key: `-103,15+265,11`, `-123,3+281,3`
- A | EmbeddingModel.embedding_space_id: `-132,1+290,1`, `-134,0+292,5`
- A | EmbeddingModel._load_candidate: `-183,0+346,4`, `-201,11+368,2`, `-213,1+371,1`, `-215,8+373,27`, `-227,0+404,2`
- A | EmbeddingModel._ensure_model: `-252,1+452,1`
- A | EmbeddingModel._encode_st_batch_locked: `-273,0+480,13`, `-282,1+502,1`, `-288,7+508,9`, `-312,1+534,2`
- A | EmbeddingModel.encode: `-387,0+610,1`
- A | EmbeddingModel._encode_uncached: `-411,7+635,11`, `-419,1+647,1`, `-421,0+649,1`, `-423,5+652,2`, `-429,3+655,3`, `-456,0+682,1`, `-488,1+715,1`, `-497,1+724,15`, `-504,1+745,1`, `-516,0+757,1`, `-519,0+761,1`, `-520,2+763,10`, `-544,0+795,1`, `-555,1+807,6`, `-574,1+831,1`, `-585,1+842,1`, `-593,0+850,45`, `-597,2+899,6`

### D152 src/local_ai_hub/embeddings.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e05138b9f03569eb15a460f4ad7e048670604bc6`; original `100644:d4250c8019fae771cc14b88c61864f0b0072bdc1`; pinned-current `100644:a1d8939c897515f3680c102e1d6edff3be0c766f`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | EmbeddingModel.__init__: `-48,1+48,1`

### D153 src/local_ai_hub/embeddings.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e05138b9f03569eb15a460f4ad7e048670604bc6`; original `100644:ed0d44841003a8257f38f65d16d6b13e527eaac5`; pinned-current `100644:a1d8939c897515f3680c102e1d6edff3be0c766f`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-8,0+8,1`
- U | EmbeddingModel.__init__: `-40,0+41,1`
- U | EmbeddingModel: `-267,0+269,4`, `-325,0+332,38`, `-398,0+443,4`
- U | EmbeddingModel._encode_st_batch_locked: `-270,0+276,1`

### D154 src/local_ai_hub/evidence.py

Disposition: `integrated-current`. Occurrences: 30:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:28363c0b78b7566c59ed2ea02160a9bd30214864`; original `100644:30dfb5bdbc1633a6de0833b3384b22e99679137a`; pinned-current `100644:30dfb5bdbc1633a6de0833b3384b22e99679137a`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-12,0+12,21`
- B | EvidenceStore: `-156,0+177,24`

### D155 src/local_ai_hub/external_tools.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f9aa0ad2c7c446ffb58a8c9f46785a5da16fdc10`; original `100644:05ada85eed94b460fa2bff6939f921a806b9b897`; pinned-current `100644:fb4d25cc0fbc149a164b8a9fc6e72d71d3164e33`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | MCPStdioClient._request: `-181,0+181,5`, `-186,5+191,0`, `-217,1+217,1`
- A | MCPStdioClient._stop_process: `-288,1+288,1`
- A | MCPStdioClient: `-302,0+302,21`
- A | MCPStdioClient._cleanup_process: `-303,2+324,3`, `-308,1+330,6`, `-315,1+342,1`

### D156 src/local_ai_hub/external_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f9aa0ad2c7c446ffb58a8c9f46785a5da16fdc10`; original `100644:3fb44d5ad4cde738de84992d67ded98ebdf4671e`; pinned-current `100644:fb4d25cc0fbc149a164b8a9fc6e72d71d3164e33`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,1+6,0`
- A | MCPStdioClient._request: `-181,0+180,5`, `-186,5+190,0`, `-217,1+216,1`
- A | MCPStdioClient._stop_process: `-288,1+287,1`
- A | MCPStdioClient: `-302,0+301,17`
- A | MCPStdioClient._cleanup_process: `-303,2+319,3`, `-308,1+325,6`, `-315,1+337,1`
- L | ExternalCodeIntelligence: `-353,12+375,1`, `-454,1+459,0`, `-793,21+795,0`
- A | ExternalCodeIntelligence.__init__: `-373,1+384,0`, `-390,4+400,0`, `-396,3+402,3`, `-401,1+407,1`, `-412,1+418,1`, `-419,1+425,0`
- A | ExternalCodeIntelligence._resolve_command: `-428,0+433,2`, `-436,2+443,0`
- A | ExternalCodeIntelligence._git_ignored_directory_names: `-505,1+509,1`
- A | ExternalCodeIntelligence._prune_sessions_locked: `-509,1+513,1`, `-511,2+515,2`
- A | ExternalCodeIntelligence._touch_session_locked: `-531,3+535,3`
- U | ExternalCodeIntelligence._record_failure: `-611,3+615,0`
- A | ExternalCodeIntelligence._backend_enabled: `-642,1+643,1`
- A | ExternalCodeIntelligence._package_spec: `-650,0+651,2`, `-656,1+659,1`
- L | ExternalCodeIntelligence._repair_backend: `-700,1+703,1`, `-707,1+710,1`, `-739,1+742,1`
- A | ExternalCodeIntelligence._needs_package_repair: `-749,1+752,1`
- A | ExternalCodeIntelligence._recover_backend: `-758,1+761,1`, `-761,1+764,1`, `-772,1+775,1`
- A | ExternalCodeIntelligence._startup_preflight: `-779,7+782,6`
- A | ExternalCodeIntelligence._run_index: `-883,1+864,1`
- L | ExternalCodeIntelligence.index: `-916,2+897,0`
- A | ExternalCodeIntelligence.backend_available: `-923,2+902,0`, `-932,1+909,1`, `-938,1+915,1`
- A | ExternalCodeIntelligence._serena_session: `-969,18+946,1`
- L | ExternalCodeIntelligence._query_serena_locked: `-1093,1+1053,1`
- U | ExternalCodeIntelligence: `-1121,37+1081,0`
- A | ExternalCodeIntelligence.query: `-1160,13+1083,3`
- A | ExternalCodeIntelligence.reset_sessions: `-1211,1+1124,1`, `-1213,2+1126,0`, `-1217,1+1128,1`, `-1219,15+1130,13`
- A | ExternalCodeIntelligence.status: `-1244,1+1153,1`, `-1246,1+1155,0`, `-1287,1+1195,0`
- A | ExternalCodeIntelligence.close: `-1302,2+1209,0`, `-1305,2+1210,1`

### D157 src/local_ai_hub/external_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f9aa0ad2c7c446ffb58a8c9f46785a5da16fdc10`; original `100644:a4b24c77b9c115bbfd0d0b99dbfd22de17cd02c5`; pinned-current `100644:fb4d25cc0fbc149a164b8a9fc6e72d71d3164e33`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,1+6,0`
- L | ExternalCodeIntelligence: `-353,12+352,1`, `-454,1+436,0`, `-793,21+772,0`
- A | ExternalCodeIntelligence.__init__: `-373,1+361,0`, `-390,4+377,0`, `-396,3+379,3`, `-401,1+384,1`, `-412,1+395,1`, `-419,1+402,0`
- A | ExternalCodeIntelligence._resolve_command: `-428,0+410,2`, `-436,2+420,0`
- A | ExternalCodeIntelligence._git_ignored_directory_names: `-505,1+486,1`
- A | ExternalCodeIntelligence._prune_sessions_locked: `-509,1+490,1`, `-511,2+492,2`
- A | ExternalCodeIntelligence._touch_session_locked: `-531,3+512,3`
- U | ExternalCodeIntelligence._record_failure: `-611,3+592,0`
- A | ExternalCodeIntelligence._backend_enabled: `-642,1+620,1`
- A | ExternalCodeIntelligence._package_spec: `-650,0+628,2`, `-656,1+636,1`
- L | ExternalCodeIntelligence._repair_backend: `-700,1+680,1`, `-707,1+687,1`, `-739,1+719,1`
- A | ExternalCodeIntelligence._needs_package_repair: `-749,1+729,1`
- A | ExternalCodeIntelligence._recover_backend: `-758,1+738,1`, `-761,1+741,1`, `-772,1+752,1`
- A | ExternalCodeIntelligence._startup_preflight: `-779,7+759,6`
- A | ExternalCodeIntelligence._run_index: `-883,1+841,1`
- L | ExternalCodeIntelligence.index: `-916,2+874,0`
- A | ExternalCodeIntelligence.backend_available: `-923,2+879,0`, `-932,1+886,1`, `-938,1+892,1`
- A | ExternalCodeIntelligence._serena_session: `-969,18+923,1`
- L | ExternalCodeIntelligence._query_serena_locked: `-1093,1+1030,1`
- U | ExternalCodeIntelligence: `-1121,37+1058,0`
- A | ExternalCodeIntelligence.query: `-1160,13+1060,3`
- A | ExternalCodeIntelligence.reset_sessions: `-1211,1+1101,1`, `-1213,2+1103,0`, `-1217,1+1105,1`, `-1219,15+1107,13`
- A | ExternalCodeIntelligence.status: `-1244,1+1130,1`, `-1246,1+1132,0`, `-1287,1+1172,0`
- A | ExternalCodeIntelligence.close: `-1302,2+1186,0`, `-1305,2+1187,1`

### D158 src/local_ai_hub/features.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e102c2f50eca4e89a6d52b17c2dc9040a0df6191`; original `100644:ba951c3b7e8e8c8feb1f3eec766b2aac4a399dd4`; pinned-current `100644:ba951c3b7e8e8c8feb1f3eec766b2aac4a399dd4`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-11,0+11,2`
- B | FeatureSet.enabled_tools: `-125,18+127,1`
- B | FeatureSet.disabled_tools: `-147,4+132,1`
- B | FeatureSet.supported_repo_actions: `-156,38+138,1`
- B | FeatureSet.supported_task_actions: `-197,12+142,1`
- B | FeatureSet.supported_coord_actions: `-212,19+146,1`
- B | FeatureSet.supported_rag_actions: `-234,3+150,1`
- B | FeatureSet: `-241,13+155,13`

### D159 src/local_ai_hub/frontend_review.py

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b0bec840ec8abf7cda28a956c24e3d2ebc3a481c`; original `100644:112ee02ebc94b10e56569cc1820994bb6fdffca3`; pinned-current `100644:af370f97c008fe5839ad728ab08d43dd630d402c`.

Exact checkpoint/owner witnesses: `S001 / 0e4c62c296d59bdd318342a094ebf0d64f2efe76 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,1`
- U | FrontendModelContext: `-62,0+63,33`

### D160 src/local_ai_hub/frontend_review.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b0bec840ec8abf7cda28a956c24e3d2ebc3a481c`; original `100644:fc89e795defb1b42e0619d4fdf4088d25544136b`; pinned-current `100644:af370f97c008fe5839ad728ab08d43dd630d402c`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,1`
- U | FrontendModelContext: `-62,0+63,38`
- A | project_live_dom: `-187,1+226,5`
- A | build_coder_context: `-346,1+389,4`, `-403,1+449,4`

### D161 src/local_ai_hub/generator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5b3185da327a661dc44eba95a5a49925c2158b4f`; original `100644:63b0151e75d08dd17196d8b61bb9855159232af4`; pinned-current `100644:3fac6b3df5c0b52cc9d9d5e596d84e98280168a4`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,1+12,0`, `-749,0+759,6`
- U | <module/text>: `-18,0+17,6`
- U | context_economy_contract: `-95,1+100,5`, `-104,1+113,2`
- L | generate_skill_markdown: `-372,1+382,1`, `-383,1+393,1`, `-399,1+409,1`
- L | generate_global_policy: `-633,1+643,1`
- A | generate_token_economy_policy: `-780,0+796,6`
- A | _apply_response_budget_schema: `-814,6+836,1`, `-821,4+838,0`
- A | generate_mcp_tool_schemas: `-835,2+848,3`, `-839,1+853,1`, `-843,9+857,1`, `-854,1+860,1`, `-864,38+870,1`, `-903,5+872,0`, `-909,1+873,1`, `-914,57+878,1`, `-973,1+881,1`, `-978,12+886,1`, `-992,1+889,1`, `-997,20+894,1`, `-1019,1+897,1`, `-1028,30+906,1`, `-1060,1+909,1`, `-1064,21+913,1`, `-1087,1+916,3`, `-1090,13+921,3`, `-1104,0+925,6`

### D162 src/local_ai_hub/generator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5b3185da327a661dc44eba95a5a49925c2158b4f`; original `100644:71561ea9270adf3224c3b68e4f0d99a947144394`; pinned-current `100644:3fac6b3df5c0b52cc9d9d5e596d84e98280168a4`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,1+12,0`, `-17,0+16,21`, `-18,0+38,6`, `-749,0+789,6`
- U | context_economy_contract: `-95,1+121,5`, `-104,1+134,2`
- L | generate_skill_markdown: `-372,1+403,1`, `-383,1+414,1`, `-399,1+430,1`, `-403,0+434,8`
- U | generate_global_policy: `-581,0+620,1`
- L | generate_global_policy: `-633,1+673,1`
- A | generate_token_economy_policy: `-780,0+826,6`
- A | _apply_response_budget_schema: `-814,6+866,1`, `-821,4+868,0`
- A | generate_mcp_tool_schemas: `-835,2+878,3`, `-839,1+883,1`, `-843,9+887,1`, `-854,1+890,1`, `-864,38+900,1`, `-903,5+902,0`, `-909,1+903,1`, `-914,57+908,1`, `-973,1+911,1`, `-978,12+916,1`, `-992,1+919,1`, `-997,20+924,1`, `-1019,1+927,1`, `-1028,30+936,1`, `-1060,1+939,1`, `-1064,21+943,1`, `-1087,1+946,3`, `-1090,13+951,3`, `-1104,0+955,6`

### D163 src/local_ai_hub/generator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5b3185da327a661dc44eba95a5a49925c2158b4f`; original `100644:779023490614f878d25c0fec07fcda07ba84cd25`; pinned-current `100644:3fac6b3df5c0b52cc9d9d5e596d84e98280168a4`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-16,0+16,21`
- L | generate_skill_markdown: `-403,0+424,8`
- U | generate_global_policy: `-581,0+610,1`

### D164 src/local_ai_hub/generator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5b3185da327a661dc44eba95a5a49925c2158b4f`; original `100644:922d3b27dd5822c8eb98102ad02990aee049be43`; pinned-current `100644:3fac6b3df5c0b52cc9d9d5e596d84e98280168a4`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | generate_mcp_tool_schemas: `-836,0+836,3`, `-846,1+849,1`

### D165 src/local_ai_hub/generator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5b3185da327a661dc44eba95a5a49925c2158b4f`; original `100644:c371f615d93908562bb305b3c812c99bd875cbcb`; pinned-current `100644:3fac6b3df5c0b52cc9d9d5e596d84e98280168a4`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | generate_global_policy: `-580,0+580,2`

### D166 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:1cb3bebfe4de96fb9d02171ee525cd4c99e94099`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-4,0+5,2`, `-53,0+57,4`, `-58,1+66,1`, `-62,0+70,344`, `-66,0+418,165`
- L | <module/text>: `-24,0+27,1`
- L | Handler._handle_db_query: `-568,0+1085,1`, `-572,0+1090,1`, `-573,0+1092,11`, `-576,1+1106,0`, `-578,2+1107,15`, `-590,0+1132,4`
- U | Handler._authorized: `-815,1+1361,1`, `-817,4+1363,15`
- U | Handler: `-825,1+1382,57`, `-1120,0+1745,24`
- U | Handler._require_authorized: `-890,1+1503,10`, `-892,0+1514,3`
- U | Handler._send: `-1215,0+1864,1`
- U | Handler._stream_agent_events: `-1345,9+1995,15`, `-1355,1+2011,1`, `-1359,0+2015,22`, `-1365,1+2043,1`
- U | Handler.do_GET: `-1425,0+2103,12`, `-1426,5+2116,0`, `-1433,0+2118,4`, `-1437,1+2126,1`, `-1441,11+2130,21`, `-1455,0+2154,2`, `-1461,1+2162,1`, `-1466,1+2167,1`, `-1469,1+2170,6`, `-1617,2+2323,1`, `-1620,4+2325,48`, `-1656,4+2405,0`, `-1665,0+2410,4`, `-1668,1+2417,21`, `-1670,2+2439,3`, `-1681,2+2451,2`, `-1689,2+2459,12`, `-1693,0+2473,2`, `-1694,1+2476,12`, `-1795,1+2588,1`, `-1797,6+2590,2`, `-1805,3+2594,1`
- U | Handler.do_POST: `-1960,1+2747,2`, `-1976,1+2764,71`, `-2038,1+2896,5`, `-2056,1+2918,1`, `-2094,1+2956,1`, `-2120,1+2982,1`, `-2139,1+3001,1`, `-2157,1+3019,1`, `-2175,1+3037,1`, `-2177,1+3039,1`, `-2179,1+3041,1`, `-2192,1+3054,1`, `-2205,1+3067,1`, `-2410,1+3272,1`, `-2693,1+3555,1`, `-2772,1+3634,1`, `-2826,1+3688,1`, `-2964,1+3826,1`, `-3014,1+3876,1`, `-3020,1+3882,1`, `-3050,1+3912,1`, `-3062,1+3924,1`, `-3071,1+3933,1`, `-3078,1+3940,1`, `-3086,1+3948,1`, `-3088,1+3950,1`, `-3090,1+3952,1`, `-3092,1+3954,1`, `-3094,1+3956,1`, `-3096,1+3958,1`, `-3098,1+3960,1`, `-3100,1+3962,1`, `-3102,1+3964,1`, `-3104,1+3966,1`, `-3107,1+3969,1`, `-3110,1+3972,1`, `-3114,1+3976,1`, `-3121,1+3983,1`, `-3130,1+3992,1`, `-3139,1+4001,1`, `-3146,1+4008,1`, `-3157,1+4019,1`, `-3167,1+4029,1`, `-3176,1+4038,1`, `-3185,1+4047,1`, `-3194,1+4056,1`, `-3202,1+4064,1`, `-3211,1+4073,1`, `-3218,1+4080,1`, `-3226,1+4088,1`, `-3233,1+4095,1`, `-3244,1+4106,1`, `-3253,1+4115,1`, `-3261,1+4123,1`, `-3271,1+4133,1`, `-3279,1+4141,1`, `-3285,1+4147,1`, `-3288,1+4150,1`, `-3292,1+4154,1`, `-3295,1+4157,1`, `-3298,1+4160,1`, `-3303,1+4165,1`, `-3313,1+4175,1`, `-3319,1+4181,1`, `-3325,1+4187,1`, `-3331,1+4193,1`, `-3337,1+4199,1`, `-3342,1+4204,1`, `-3351,1+4213,1`, `-3354,1+4216,1`, `-3356,1+4218,1`, `-3361,1+4223,1`, `-3367,1+4229,1`, `-3376,1+4238,1`, `-3387,1+4249,1`, `-3398,1+4260,1`, `-3406,1+4268,1`, `-3421,1+4283,1`, `-3423,1+4285,1`, `-3425,1+4287,1`, `-3427,1+4289,1`, `-3429,1+4291,1`, `-3431,1+4293,1`, `-3439,1+4301,1`, `-3444,1+4306,1`, `-3446,1+4308,1`, `-3455,1+4317,1`, `-3457,1+4319,1`, `-3463,1+4325,1`, `-3605,1+4467,1`, `-3610,1+4472,1`, `-3612,1+4474,1`, `-3615,1+4477,1`, `-3617,1+4479,1`, `-3620,1+4482,1`, `-3622,1+4484,1`, `-3624,1+4486,1`, `-3629,1+4491,1`, `-3631,1+4493,1`, `-3633,1+4495,1`, `-3635,1+4497,1`, `-3637,1+4499,1`, `-3642,1+4504,1`, `-3645,1+4507,1`, `-3647,1+4509,1`, `-3652,1+4514,1`, `-3654,1+4516,1`, `-3656,5+4518,1`, `-3664,1+4522,1`, `-3671,1+4529,1`, `-3679,1+4537,1`, `-3686,1+4544,1`, `-3693,1+4551,1`, `-3703,1+4561,1`, `-3705,1+4563,1`, `-3709,1+4567,1`, `-3713,1+4571,1`, `-3717,1+4575,1`, `-3722,4+4580,1`, `-3727,1+4582,1`, `-3729,1+4584,1`, `-3731,1+4586,1`, `-3733,1+4588,1`, `-3735,1+4590,1`, `-3737,1+4592,1`, `-3739,1+4594,1`, `-3742,1+4597,1`, `-3750,1+4605,1`, `-3752,1+4607,1`, `-3754,1+4609,1`, `-3756,1+4611,1`, `-3758,1+4613,1`, `-3760,1+4615,1`, `-3762,1+4617,1`, `-3764,1+4619,1`, `-3766,1+4621,1`, `-3768,1+4623,1`, `-3770,1+4625,1`, `-3772,1+4627,1`, `-3774,1+4629,1`, `-3776,1+4631,1`, `-3778,1+4633,1`, `-3780,1+4635,1`, `-3785,1+4640,1`, `-3787,1+4642,1`, `-3789,1+4644,1`, `-3791,1+4646,1`, `-3793,1+4648,1`, `-3795,1+4650,1`, `-3797,1+4652,1`, `-3799,1+4654,1`, `-3801,1+4656,1`, `-3811,1+4666,1`, `-3813,1+4668,1`, `-3815,1+4670,1`, `-3820,1+4675,1`

### D167 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:279505e7e829d203773aca792fe908e0bf60c416`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`, `-45,0+47,1`, `-59,0+62,1`, `-66,0+70,50`
- L | <module/text>: `-13,0+14,1`
- U | Handler: `-680,0+734,7`
- A | Handler._reconcile_debug_trace: `-755,1+816,6`
- L | Handler._validate_payload: `-989,0+1055,13`, `-1044,0+1123,4`
- U | Handler._stream_agent_events: `-1347,3+1430,19`, `-1351,8+1450,20`
- U | Handler.do_GET: `-1438,0+1549,3`
- U | Handler.do_POST: `-1957,0+2071,1`, `-1959,0+2074,53`, `-2019,2+2187,13`, `-2023,1+2202,1`, `-2025,1+2204,8`, `-2029,0+2215,15`, `-2031,1+2232,1`, `-2033,2+2234,7`, `-2036,1+2242,8`, `-2777,1+2990,5`
- L | Handler.do_POST: `-2785,1+3002,1`

### D168 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:4398cf01087614165ec3e96ffafc4985ce60d0b4`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-53,0+53,42`
- L | Handler._handle_db_query: `-551,2+593,2`
- U | Handler._stream_agent_events: `-1344,2+1386,27`, `-1347,12+1414,36`, `-1364,6+1455,8`, `-1390,0+1501,1`, `-1392,1+1504,1`, `-1396,1+1508,1`
- L | Handler._stream_agent_events: `-1373,1+1466,18`, `-1375,0+1485,1`, `-1377,0+1488,4`, `-1379,6+1494,2`
- U | Handler.do_GET: `-1501,2+1613,5`, `-1556,2+1671,5`
- L | Handler.do_POST: `-2289,0+2407,4`, `-2296,0+2418,1`, `-2344,0+2467,2`, `-2635,0+2844,2`, `-2785,1+3000,1`, `-2831,1+3046,5`, `-3550,1+3769,1`, `-3767,1+3991,1`
- U | Handler.do_POST: `-2445,0+2570,7`, `-2448,3+2580,3`, `-2479,0+2611,11`, `-2502,2+2645,5`, `-2545,1+2691,33`, `-2560,2+2738,5`, `-2627,0+2808,18`, `-2631,0+2830,10`, `-2777,1+2988,5`, `-3561,1+3780,6`

### D169 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 27:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:551e4d9a0c1523c6f3f504285fe57d183e35023a`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S061 / c041d450a685c0c2f225270c7113c075aec585ae / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`
- U | Handler._send: `-1215,0+1216,7`, `-1216,0+1224,3`
- U | Handler: `-1951,0+1962,96`
- U | Handler.do_POST: `-1959,0+2066,7`, `-1980,0+2099,2`, `-2016,21+2137,2`
- L | Handler.do_POST: `-1968,0+2082,5`

### D170 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:61965a52bcf83e9c1a4dbb3d9a4c1b5031cbff66`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | Handler._send: `-1215,0+1215,10`

### D171 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:643134c821f8b43a9f45394f8bdf4250176320fb`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`
- U | Handler.do_POST: `-1956,0+1957,11`, `-1968,1+1980,5`, `-1971,27+1987,6`, `-2019,2+2014,13`, `-2023,1+2029,1`, `-2025,1+2031,8`, `-2029,0+2042,15`, `-2031,1+2059,1`, `-2033,2+2061,7`, `-2036,1+2069,30`
- L | Handler.do_POST: `-3745,1+3807,1`, `-3747,1+3809,1`, `-3749,1+3811,3`

### D172 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:6fa959d404f8d714080f253fa4e7692fdd9e01dc`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,16`, `-4,0+20,2`, `-22,2+40,1`, `-35,0+52,1`, `-57,1+75,1`, `-62,0+80,13`
- L | <module/text>: `-221,0+252,41`, `-3859,5+4587,18`
- A | LocalAIHTTPServer: `-314,1+386,3`, `-338,0+412,8`
- U | Handler: `-426,1+508,1`, `-793,4+859,488`, `-815,1+1373,25`
- A | Handler._begin_trace: `-676,1+758,1`
- A | Handler._safe_debug_trace_request: `-682,1+764,1`, `-685,24+767,1`
- A | Handler._finish_debug_trace: `-718,1+777,1`, `-721,0+780,2`
- L | Handler: `-791,1+852,6`
- A | Handler._tenant_binding_allowed: `-803,0+1353,8`
- U | Handler._authorized: `-817,0+1399,1`, `-818,5+1401,6`, `-825,1+1409,22`
- U | Handler._require_authorized: `-887,1+1492,1`, `-890,2+1495,3`
- L | Handler.do_GET: `-1422,0+2028,26`, `-1455,13+2112,1`, `-1476,0+2121,2`, `-1478,3+2125,3`, `-1524,0+2174,5`, `-1627,1+2287,1`, `-1839,1+2499,4`
- U | Handler.do_GET: `-1432,0+2064,25`, `-1490,1+2137,4`, `-1599,0+2254,5`
- U | Handler.do_POST: `-1976,0+2639,24`, `-2394,4+3123,0`, `-2407,1+3132,4`, `-2545,0+3283,2`, `-2603,0+3343,5`, `-2625,0+3370,5`, `-2628,1+3378,1`, `-2639,0+3389,3`, `-2641,1+3394,1`, `-2648,12+3401,1`, `-2778,0+3497,6`, `-3561,0+4291,1`
- L | Handler.do_POST: `-2211,0+2898,51`, `-2381,9+3119,0`, `-2460,0+3188,5`, `-2525,0+3258,5`, `-2661,2+3403,1`, `-2664,7+3405,1`, `-2672,13+3407,1`, `-2686,5+3409,1`, `-2799,0+3524,2`, `-3307,1+4034,4`
- A | validate_network_security: `-3854,4+4585,1`
- A | serve: `-3873,0+4614,2`, `-3892,1+4635,8`

### D173 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:719c7e543f91dd269d1c353464e2f92cf14d3bcc`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,3`, `-54,0+57,150`, `-58,1+211,1`, `-62,0+215,73`
- U | Handler._authorized: `-815,1+1041,3`, `-817,6+1045,7`
- U | Handler: `-825,1+1054,135`, `-1952,0+2357,15`, `-1956,1+2376,0`
- U | Handler._require_authorized: `-890,2+1253,4`
- U | Handler._validate_payload: `-989,1+1354,4`
- U | Handler._send: `-1215,0+1583,10`, `-1274,0+1652,2`
- U | Handler.do_GET: `-1441,0+1821,26`, `-1795,1+2201,1`, `-1798,2+2204,1`, `-1802,1+2207,1`
- U | Handler._do_POST_request: `-1959,0+2378,13`, `-1968,1+2400,29`, `-1971,0+2431,4`, `-1976,22+2440,3`, `-2016,1+2461,5`, `-2019,2+2468,37`, `-2022,15+2506,28`, `-2038,0+2535,215`, `-2131,1+2843,5`, `-2176,0+2892,5`, `-2178,1+2899,4`, `-2182,1+2906,2`, `-3726,1+4451,41`
- U | validate_network_security: `-3855,9+4620,2`

### D174 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:767e28e18a98d9eeb12ee09623b4f267f740bdd4`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,3`, `-24,0+28,1`, `-27,0+32,1`, `-28,0+34,2`, `-35,0+43,2`, `-54,0+69,160`, `-60,0+235,1`, `-62,0+238,178`, `-66,0+420,100`
- L | <module/text>: `-13,0+16,1`, `-45,0+55,5`
- A | _journal_outcome_success: `-244,0+698,2`
- L | Handler._handle_db_query: `-568,0+1024,1`, `-572,0+1029,1`, `-573,0+1031,11`, `-576,1+1045,0`, `-578,2+1046,15`, `-590,0+1071,4`
- L | Handler: `-597,1+1082,0`
- U | Handler: `-679,0+1163,7`, `-798,0+1289,19`, `-825,1+1346,57`, `-1120,0+1711,5`, `-1951,0+2679,96`
- U | Handler._authorized: `-815,1+1325,1`, `-817,4+1327,15`
- U | Handler._require_authorized: `-890,1+1467,18`, `-892,0+1486,3`
- U | Handler._validate_payload: `-989,7+1586,1`
- A | Handler._async_delivery: `-1188,0+1784,3`
- U | Handler._send: `-1214,1+1813,9`, `-1216,0+1823,3`
- L | Handler._send: `-1274,0+1884,2`
- L | Handler._stream_agent_events: `-1340,0+1952,2`, `-1355,1+1985,1`, `-1358,0+1988,2`, `-1390,0+2047,2`, `-1391,0+2050,3`, `-1392,1+2054,2`, `-1396,1+2059,1`
- U | Handler._stream_agent_events: `-1347,7+1961,23`, `-1359,0+1991,24`, `-1365,1+2021,1`, `-1369,1+2025,2`
- L | Handler.do_GET: `-1425,1+2088,0`, `-1617,2+2304,3`, `-1620,4+2308,24`, `-1670,2+2399,3`, `-1701,1+2431,2`, `-1798,2+2529,1`, `-1802,1+2532,1`, `-1805,3+2535,1`
- U | Handler.do_GET: `-1431,0+2093,5`, `-1438,0+2105,3`, `-1455,0+2125,2`, `-1461,1+2133,1`, `-1466,1+2138,1`, `-1490,2+2162,11`, `-1500,3+2181,6`, `-1555,3+2239,6`, `-1668,1+2376,22`, `-1795,1+2526,1`
- L | Handler.do_POST: `-1956,1+2780,0`, `-1961,0+3029,4`, `-1968,0+3040,5`, `-1971,0+3048,8`, `-1980,0+3070,2`, `-1998,0+3090,3`, `-2006,12+3101,13`, `-2019,19+3115,5`, `-2176,0+3258,3`, `-2178,1+3263,2`, `-2289,0+3381,4`, `-2296,0+3392,1`, `-2344,0+3475,2`, `-2448,3+3604,3`, `-2471,1+3627,18`, `-2473,2+3646,1`, `-3132,1+4345,1`, `-3470,0+4683,1`, `-3473,2+4687,4`, `-3476,5+4692,7`, `-3482,0+4700,3`, `-3488,1+4750,9`, `-3490,1+4760,5`, `-3499,0+4773,6`, `-3504,0+4784,5`, `-3533,0+4818,5`, `-3534,6+4824,18`, `-3542,1+4844,0`, `-3619,1+4939,3`, `-3722,3+5046,0`, `-3726,1+5047,20`, `-3736,1+5076,1`
- U | Handler.do_POST: `-1959,0+2782,245`, `-1976,0+3061,4`, `-1978,1+3067,2`, `-2182,1+3268,7`, `-2302,2+3399,36`, `-2393,1+3526,1`, `-2407,2+3540,18`, `-2445,0+3594,7`, `-2501,3+3673,6`, `-2545,1+3720,36`, `-2559,3+3769,6`, `-3485,0+4706,41`, `-3561,1+4862,6`, `-3598,4+4904,18`, `-3636,1+4958,3`, `-3747,1+5087,1`

### D175 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 10:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:8b7358ecbed79461beb125e1fb2fe7fdcf7017a8`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S031 / c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3 / true / f99619a4658692b2d15d40a07f2176891c72cffa`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-28,0+28,2`, `-53,0+55,11`
- L | Handler.do_GET: `-1701,1+1714,2`
- L | Handler.do_POST: `-3619,1+3633,3`

### D176 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:99aad7a0297eb7fe753c942464b7dd165dd97e18`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | Handler.do_POST: `-2302,6+2302,46`
- L | Handler.do_POST: `-3470,0+3510,1`

### D177 src/local_ai_hub/http_server.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:da30738fba3e5782176063b3a959058cfd26f57c`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | Handler.do_POST: `-3814,1+3814,1`

### D178 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2`; original `100644:df40b6d8cb298a7c19090d214f0d3254b1cea281`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,3`, `-35,0+43,2`, `-54,0+69,160`, `-60,0+235,1`, `-62,0+238,290`
- L | <module/text>: `-13,0+16,1`, `-24,0+28,1`, `-27,0+32,1`, `-28,0+34,2`, `-45,0+55,5`, `-66,0+532,101`
- A | _journal_outcome_success: `-244,0+811,2`
- L | Handler._handle_db_query: `-568,0+1137,1`, `-572,0+1142,1`, `-573,0+1144,11`, `-576,1+1158,0`, `-578,2+1159,15`, `-590,0+1184,4`
- L | Handler: `-597,1+1195,0`, `-1120,0+1831,19`, `-1951,0+2909,106`
- U | Handler: `-679,0+1276,7`, `-798,0+1402,26`, `-825,1+1466,57`
- U | Handler._authorized: `-815,1+1445,1`, `-817,4+1447,15`
- U | Handler._require_authorized: `-890,1+1587,18`, `-892,0+1606,3`
- U | Handler._validate_payload: `-989,7+1706,1`
- A | Handler._async_delivery: `-1188,0+1918,3`
- U | Handler._send: `-1214,1+1947,9`, `-1216,0+1957,3`
- L | Handler._send: `-1274,0+2018,2`
- L | Handler._stream_agent_events: `-1340,0+2086,2`, `-1355,1+2152,1`, `-1358,0+2155,2`, `-1390,0+2238,2`, `-1391,0+2241,3`, `-1392,1+2245,2`, `-1396,1+2250,1`
- U | Handler._stream_agent_events: `-1347,7+2095,56`, `-1359,0+2158,48`, `-1365,1+2212,1`, `-1369,1+2216,2`
- L | Handler.do_GET: `-1425,1+2279,0`, `-1429,1+2282,9`, `-1438,0+2308,19`, `-1441,11+2330,0`, `-1617,2+2526,3`, `-1620,4+2530,24`, `-1666,1+2596,9`, `-1668,1+2606,22`, `-1670,2+2629,3`, `-1701,1+2661,2`, `-1798,2+2759,1`, `-1802,1+2762,1`, `-1805,3+2765,1`
- U | Handler.do_GET: `-1431,0+2292,5`, `-1433,0+2299,4`, `-1455,0+2333,2`, `-1461,1+2341,1`, `-1466,1+2346,1`, `-1490,2+2370,11`, `-1500,3+2389,13`, `-1555,3+2454,13`, `-1600,1+2509,1`, `-1606,1+2515,1`, `-1795,1+2756,1`
- L | Handler.do_POST: `-1956,1+3020,0`, `-1959,0+3022,294`, `-1961,0+3318,4`, `-1968,0+3329,5`, `-1971,0+3337,8`, `-1980,0+3359,2`, `-1998,0+3379,3`, `-2006,12+3390,13`, `-2019,19+3404,5`, `-2176,0+3547,3`, `-2178,1+3552,2`, `-2182,1+3557,7`, `-2289,0+3670,4`, `-2296,0+3681,1`, `-2302,2+3688,45`, `-2344,0+3773,2`, `-2448,3+3909,3`, `-2473,2+3952,1`, `-2553,1+4082,2`, `-2610,1+4150,1`, `-3132,1+4692,1`, `-3409,1+4969,1`, `-3470,0+5030,1`, `-3473,2+5034,4`, `-3476,5+5039,7`, `-3482,0+5047,3`, `-3485,0+5053,96`, `-3488,1+5152,9`, `-3490,1+5162,5`, `-3499,0+5175,6`, `-3504,0+5186,5`, `-3533,0+5220,5`, `-3534,6+5226,18`, `-3542,1+5246,0`, `-3598,4+5306,21`, `-3619,1+5344,3`, `-3722,3+5451,0`, `-3726,1+5452,20`
- U | Handler.do_POST: `-1976,0+3350,4`, `-1978,1+3356,2`, `-2393,1+3824,1`, `-2407,2+3838,18`, `-2445,0+3892,14`, `-2471,1+3932,19`, `-2501,3+3979,13`, `-2545,1+4033,42`, `-2559,3+4089,13`, `-2604,1+4144,1`, `-2625,1+4165,5`, `-2631,0+4175,8`, `-2644,0+4196,8`, `-3561,1+5264,6`, `-3636,1+5363,3`, `-3747,1+5492,1`

### D179 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9d83f45764cf1055a2baa2a3046b8939daef22f9`; original `100644:65d920368cb7c12ba41a02414255bd7083b61673`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-27,0+27,1`
- L | Handler._stream_agent_events: `-1334,0+1335,2`, `-1384,0+1390,2`, `-1385,0+1393,3`, `-1386,1+1397,2`, `-1390,1+1402,1`
- U | Handler._stream_agent_events: `-1352,0+1355,2`, `-1363,1+1368,2`
- U | Handler.do_POST: `-1962,0+1974,8`

### D180 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:aceaabdb138f7f37e695c99dbc0d053353e2ee81`; original `100644:e8a5ae468c615ea1feca01c99e3dd7ee6861d7ef`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | Handler.do_POST: `-3445,1+3445,1`, `-3447,4+3447,1`, `-3454,2+3451,2`

### D181 src/local_ai_hub/http_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b8e071945d4cbcfdc237ed9319dac674900fc19f`; original `100644:5d5567e8b1ab1397b9bc75b4ab7f25ecbefc94cc`; pinned-current `100644:1b97076f3bbb9a0489bcc97b4b1f0ddcf1e296c9`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-17,1+17,1`
- L | <module/text>: `-58,0+58,23`
- A | Handler._handle_models_action: `-745,1+768,35`, `-747,0+804,8`, `-749,0+814,8`
- U | Handler._audit_admin_action: `-1042,1+1115,1`, `-1045,1+1118,1`, `-1048,2+1121,1`, `-1051,1+1123,1`, `-1054,1+1126,1`, `-1061,1+1133,8`
- U | Handler._send: `-1382,1+1461,7`
- L | Handler._stream_agent_events: `-1487,1+1572,8`
- U | Handler._stream_agent_events: `-1491,0+1583,14`, `-1515,13+1621,155`, `-1535,1+1783,2`, `-1543,2+1792,0`, `-1547,0+1794,6`, `-1548,0+1801,2`, `-1549,2+1804,0`, `-1552,1+1805,1`
- U | Handler.do_GET: `-1653,1+1906,1`, `-1807,4+2060,57`, `-1877,1+2190,1`
- L | Handler.do_GET: `-1833,1+2139,1`, `-1835,1+2141,8`
- L | Handler.do_POST: `-2213,1+2526,12`

### D182 src/local_ai_hub/inprocess_transport.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e205c63916dfc521f6ae0f0d54e501c43b40ab09`; original `100644:5dc1ba116830ec4d8228b85fbb473c2012442a5e`; pinned-current `100644:e2f1007eff8f0a7a8686cfd6881e831ff6adf0c3`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,1`
- A | InProcessTransportFailure: `-20,1+21,1`
- A | InProcessTransportFailure.__init__: `-22,1+23,4`
- A | InProcessTransport.open: `-222,0+226,1`, `-280,8+285,22`

### D183 src/local_ai_hub/leases.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c4a32cd13c20811212541facb98024138d1bc79c`; original `100644:17ceb1557270b1854d28943d57d67329980be332`; pinned-current `100644:a0fb7f9c7c0d9862439f70b1bf0071db6b09fb00`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`
- U | <module/text>: `-12,0+13,3`
- U | ScopeLeaseStore._init_db: `-99,12+103,38`
- A | ScopeLeaseStore._root: `-121,1+151,6`
- A | ScopeLeaseStore.claim: `-124,1+159,10`, `-138,1+182,10`
- A | ScopeLeaseStore.claim.write: `-149,4+202,11`, `-222,1+282,1`
- A | ScopeLeaseStore.claim_batch: `-232,1+292,10`, `-234,1+303,8`
- A | ScopeLeaseStore.release.write: `-240,1+316,1`, `-243,1+319,1`, `-246,1+322,1`, `-252,0+328,5`, `-254,10+335,12`
- A | ScopeLeaseStore.list: `-295,1+378,6`
- A | ScopeLeaseStore.list.read: `-299,0+387,2`, `-300,1+390,8`, `-302,2+399,12`
- A | ScopeLeaseStore.waits: `-315,1+422,6`
- A | ScopeLeaseStore.waits.read: `-319,0+431,2`, `-320,1+434,9`, `-322,2+444,12`

### D184 src/local_ai_hub/leases.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c4a32cd13c20811212541facb98024138d1bc79c`; original `100644:87cce07a53516e84f5276281cecaa3cd71fb2ce9`; pinned-current `100644:a0fb7f9c7c0d9862439f70b1bf0071db6b09fb00`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-13,1+13,7`
- L | <module/text>: `-63,0+69,129`
- A | ScopeLeaseStore.__init__: `-67,1+202,0`, `-69,0+203,1`
- U | ScopeLeaseStore._init_db: `-84,0+219,19`, `-111,0+265,15`

### D185 src/local_ai_hub/leases.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c4a32cd13c20811212541facb98024138d1bc79c`; original `100644:a0beaa83ffdf29680614a99e99d9066b25edafc5`; pinned-current `100644:a0fb7f9c7c0d9862439f70b1bf0071db6b09fb00`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`
- U | <module/text>: `-12,0+13,3`
- U | ScopeLeaseStore._init_db: `-99,12+103,33`
- A | ScopeLeaseStore._root: `-121,1+146,6`
- A | ScopeLeaseStore.claim: `-124,1+154,10`, `-138,1+177,10`
- A | ScopeLeaseStore.claim.write: `-149,4+197,11`, `-222,1+277,1`
- A | ScopeLeaseStore.claim_batch: `-232,1+287,10`, `-234,1+298,8`
- A | ScopeLeaseStore.release.write: `-240,1+311,1`, `-243,1+314,1`, `-246,1+317,1`, `-252,0+323,5`, `-254,10+330,12`
- A | ScopeLeaseStore.list: `-295,1+373,6`
- A | ScopeLeaseStore.list.read: `-299,0+382,2`, `-300,1+385,8`, `-302,2+394,12`
- A | ScopeLeaseStore.waits: `-315,1+417,6`
- A | ScopeLeaseStore.waits.read: `-319,0+426,2`, `-320,1+429,9`, `-322,2+439,12`

### D186 src/local_ai_hub/leases.py

Disposition: `preserved-only-needs-integration`. Occurrences: 10:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c4a32cd13c20811212541facb98024138d1bc79c`; original `100644:cc57c8d47a3949f057cf06d132e58b444e7fc7a8`; pinned-current `100644:a0fb7f9c7c0d9862439f70b1bf0071db6b09fb00`.

Exact checkpoint/owner witnesses: `S031 / c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3 / true / f99619a4658692b2d15d40a07f2176891c72cffa`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,3`
- U | ScopeLeaseStore._init_db: `-99,12+102,35`
- A | ScopeLeaseStore.claim: `-124,1+150,10`, `-138,1+173,10`
- A | ScopeLeaseStore.claim.write: `-149,4+193,11`, `-222,1+273,1`
- A | ScopeLeaseStore.claim_batch: `-232,1+283,10`, `-234,1+294,8`
- A | ScopeLeaseStore.release.write: `-240,1+307,1`, `-243,1+310,1`, `-246,1+313,1`, `-252,0+319,5`, `-254,10+326,12`
- A | ScopeLeaseStore.list: `-295,1+369,6`
- A | ScopeLeaseStore.list.read: `-299,0+378,2`, `-300,1+381,8`, `-302,2+390,12`
- A | ScopeLeaseStore.waits: `-315,1+413,6`
- A | ScopeLeaseStore.waits.read: `-319,0+422,2`, `-320,1+425,9`, `-322,2+435,12`

### D187 src/local_ai_hub/llama_cpp.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:506734a1160bd011d3071391203635a455bbf62b`; original `100644:2b661981c3800d436c599f5ab71888dd85a8b4ca`; pinned-current `100644:b363fb0fd5adba8bd61534f6d7418e5150fd60f0`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-10,0+10,2`, `-11,0+13,2`, `-12,0+16,1`, `-14,0+19,3`, `-16,2+24,2`, `-19,0+27,480`
- A | LlamaCppRouter._healthy: `-74,1+562,7`, `-76,0+570,5`, `-83,1+582,4`, `-87,0+589,2`
- A | LlamaCppRouter._model_info: `-91,1+595,10`, `-93,0+606,7`, `-95,1+615,1`, `-100,7+620,28`
- A | LlamaCppRouter.ready_for_model: `-111,1+652,7`, `-116,1+663,1`, `-119,1+666,1`
- A | LlamaCppRouter.ensure_model: `-121,1+668,18`, `-126,1+690,9`, `-129,1+701,4`, `-139,0+714,3`, `-141,2+719,2`, `-147,8+725,6`, `-156,1+732,3`, `-163,1+741,1`
- A | LlamaCppRouter.available_models: `-166,1+744,6`, `-172,0+755,2`, `-175,1+760,1`, `-177,1+762,1`
- U | LlamaCppRouter.loaded_model_inventory: `-184,1+769,7`, `-186,0+777,3`, `-187,7+781,10`
- U | LlamaCppRouter: `-195,13+792,74`
- A | LlamaCppRouter.unload_model: `-243,1+901,8`, `-245,1+910,25`, `-247,2+936,3`, `-252,2+942,14`
- A | LlamaCppRouter._openai_payload: `-305,1+1007,4`
- A | LlamaCppRouter.request_stream: `-334,0+1039,1`, `-349,2+1055,43`, `-352,0+1099,3`, `-362,1+1112,0`, `-369,2+1118,17`, `-372,8+1136,4`, `-429,0+1189,7`, `-431,0+1198,4`

### D188 src/local_ai_hub/llama_cpp.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:506734a1160bd011d3071391203635a455bbf62b`; original `100644:a6ddd23d370f621541b87a895ba56b9b2eee3dc9`; pinned-current `100644:b363fb0fd5adba8bd61534f6d7418e5150fd60f0`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LlamaCppRouter.unload_model: `-243,1+243,1`, `-252,1+252,2`

### D189 src/local_ai_hub/llama_cpp.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:79165b858976e5bd6f0ce8b9158e33a76f3a78dd`; original `100644:4fa3d87b4381770884b869758e695914ebf53aa2`; pinned-current `100644:b363fb0fd5adba8bd61534f6d7418e5150fd60f0`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-13,0+13,1`, `-88,0+194,23`
- L | <module/text>: `-18,1+19,1`, `-44,0+45,98`
- U | _resolve_interruptibly: `-58,0+157,7`
- A | _http_proxy_for_url: `-90,1+219,2`, `-92,0+222,4`
- L | _open_interruptible_response: `-220,1+354,1`, `-222,0+356,1`, `-223,0+358,2`, `-242,1+379,4`
- L | LlamaCppRouter._model_info: `-434,0+574,3`, `-440,0+583,2`, `-443,1+588,1`, `-459,0+613,2`
- U | LlamaCppRouter._model_info: `-453,5+598,14`
- A | LlamaCppRouter.loaded_model_details: `-586,0+742,1`
- L | LlamaCppRouter: `-587,0+744,22`
- A | LlamaCppRouter.loaded_model_inventory: `-588,0+767,3`, `-589,3+771,17`, `-593,7+789,3`, `-601,13+793,46`
- A | LlamaCppRouter.unload_model: `-653,0+878,1`, `-657,1+883,25`, `-659,2+909,3`
- A | LlamaCppRouter._openai_payload: `-729,1+980,4`

### D190 src/local_ai_hub/logging_setup.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a91933597b0c8c34d3b4d30edaa662a6ef0a5451`; original `100644:244a608a044a1f1d3c3fb09badc744c0bec68fcf`; pinned-current `100644:244a608a044a1f1d3c3fb09badc744c0bec68fcf`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-12,0+12,1`
- B | configure_logging: `-43,1+44,1`, `-48,1+49,0`, `-54,0+54,1`, `-59,0+60,3`
- B | shutdown_logging: `-79,1+83,1`, `-96,0+100,3`

### D191 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 20:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:145e1dea89ebe308a74ecacfd121eb4b92102cf0`; original `100644:41d29c2da3d9755ddc809b05a8ed4e39a894b034`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S071 / 9b1b40906612634df8a0a3bedbb217a337c67cb4 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | local_ai_task: `-1351,0+1351,6`

### D192 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:17883c18c2512a622af96a4e6a25de7a43219aca`; original `100644:a3811306b569e73641c3bdd7f3e83ffd43e93808`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | local_ai_task: `-1255,0+1255,1`, `-1355,1+1356,1`
- U | _local_ai_repo_impl: `-1744,0+1745,1`, `-1810,1+1812,1`
- L | _local_ai_repo_impl: `-1773,1+1775,1`
- U | local_ai_repo: `-2206,0+2208,1`, `-2214,1+2217,1`

### D193 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b4317b3457bfcf5995da1758a3ae229d4a00ba8`; original `100644:f3d11bee4d7ae8bd63f46bc7ea23f8d5b1043645`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-20,0+20,6`, `-50,0+56,5`, `-497,1+582,1`, `-2782,1+2924,1`
- U | <module/text>: `-87,0+98,73`, `-89,2+173,3`, `-915,5+1000,0`, `-957,0+1037,21`, `-2708,2+2844,2`, `-2724,0+2860,1`, `-2781,0+2918,5`
- L | _ProtocolAccountingReporter: `-836,1+921,0`
- A | _ProtocolAccountingReporter._send: `-856,0+940,1`, `-857,2+942,0`, `-861,1+944,1`, `-870,0+953,2`
- U | _instrumented_tool.decorator.wrapped: `-963,0+1064,23`
- L | _instrumented_tool.decorator.wrapped: `-980,0+1104,3`, `-1001,0+1128,1`
- U | _local_ai_repo_impl: `-1721,0+1849,1`, `-1785,0+1914,6`, `-1787,1+1922,1`
- U | local_ai_repo: `-2183,0+2318,1`, `-2191,1+2327,1`

### D194 src/local_ai_hub/mcp_server.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9d275efc3353a4377e7469bb138996531db210bc`; original `100644:145e1dea89ebe308a74ecacfd121eb4b92102cf0`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | _async_job_lifecycle_contract: `-239,1+239,1`
- A | _task_delivery_contract: `-259,1+259,1`

### D195 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9d275efc3353a4377e7469bb138996531db210bc`; original `100644:9bce06005252fdda463b1dc2748e1fafeb84d86a`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-167,0+167,25`
- U | _instrumented_tool.decorator.wrapped: `-1045,0+1070,10`
- U | local_ai_task: `-1351,0+1386,7`
- U | _local_ai_repo_impl: `-1827,0+1869,4`
- U | local_ai_rag: `-2323,0+2369,8`

### D196 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:624947e63e997638649ef2d901a8e078cf44fef4`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-41,0+41,1`, `-681,0+682,78`
- U | _telemetry_status_projection: `-695,8+774,8`, `-705,1+784,1`
- U | local_ai_status: `-1164,1+1243,6`, `-1169,0+1253,1`, `-1172,1+1257,4`

### D197 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:6b039d680ac754825b38cdec8a04320a6f9f4945`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | _desc_repo: `-289,1+289,1`
- L | _desc_repo: `-300,1+300,1`
- U | <module/text>: `-430,1+430,1`
- L | _local_ai_repo_impl: `-1814,3+1814,3`
- U | local_ai_artifact: `-2668,1+2668,5`

### D198 src/local_ai_hub/mcp_server.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:89f1c16bbee0ed7640ff8539923ce01e1fcb9132`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | local_ai_task: `-1499,3+1499,8`

### D199 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:df5377cc6ba6f21ed0cd67d92ec7a12c45f258ac`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-15,0+15,1`, `-126,0+127,59`
- U | _local_ai_repo_impl: `-1743,0+1803,1`, `-1807,0+1868,17`, `-1809,1+1887,1`
- U | local_ai_repo: `-2205,0+2283,1`, `-2213,1+2292,1`

### D200 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:e8e9190e6ef7235fc2890e8807a8198242c8381d`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-8,0+8,1`, `-78,0+100,74`, `-80,2+176,3`, `-423,26+576,15`, `-450,24+592,0`, `-475,2+593,2`, `-520,0+638,8`, `-2717,0+3121,16`, `-2718,0+3138,11`, `-2733,0+3164,21`
- L | <module/text>: `-15,1+16,2`, `-20,0+22,6`, `-38,0+46,9`, `-41,0+58,5`, `-126,0+223,55`, `-524,1+650,1`, `-526,1+652,1`, `-536,1+662,4`, `-1088,8+1283,8`, `-2743,0+3195,5`, `-2744,1+3201,1`
- U | _desc_repo: `-289,2+441,2`, `-292,2+444,2`
- L | _desc_repo: `-295,2+447,2`, `-300,1+452,1`
- U | _desc_artifact: `-415,1+567,2`
- L | _compact: `-656,1+785,26`, `-664,5+829,5`
- U | _compact: `-658,1+812,12`
- A | _ProtocolAccountingReporter: `-858,1+1023,0`
- A | _ProtocolAccountingReporter._send: `-878,0+1042,1`, `-879,2+1044,0`, `-883,1+1046,1`, `-892,0+1055,2`
- A | _ProtocolAccountingReporter.close: `-937,1+1102,2`, `-939,1+1105,1`
- L | _instrumented_tool.decorator.wrapped: `-994,0+1160,25`, `-1002,0+1193,3`, `-1023,0+1217,1`
- U | local_ai_status: `-1143,1+1338,1`
- U | local_ai_task: `-1299,0+1494,20`
- L | local_ai_task: `-1499,3+1714,8`
- A | _validate_context_pack_inputs: `-1559,0+1779,6`, `-1565,0+1791,2`, `-1590,0+1818,4`, `-1592,1+1824,5`, `-1596,0+1832,2`
- L | _context_pack_projection: `-1634,0+1872,1`, `-1652,0+1891,31`
- L | _local_ai_repo_impl: `-1743,0+2013,4`, `-1772,1+2046,1`, `-1814,3+2094,3`, `-1823,0+2103,27`, `-1828,0+2135,3`, `-1831,1+2141,7`, `-1858,0+2174,13`
- U | _local_ai_repo_impl: `-1807,0+2081,6`, `-1809,1+2089,1`
- L | local_ai_repo: `-2205,0+2534,4`, `-2207,0+2540,34`, `-2213,1+2580,1`
- U | local_ai_rag: `-2253,0+2620,5`, `-2254,1+2626,1`
- L | local_ai_rag: `-2277,0+2649,7`, `-2278,1+2657,4`, `-2281,0+2663,7`, `-2283,2+2672,3`
- L | local_ai_coord: `-2449,0+2839,2`, `-2610,1+3002,1`
- A | local_ai_artifact: `-2668,2+3060,2`, `-2671,0+3063,14`, `-2673,2+3079,0`, `-2680,1+3084,1`

### D201 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:eb2663cee48f457e4581c682a2bd4410f4ceaf92`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-474,0+474,3`
- U | local_ai_status: `-1143,1+1146,1`

### D202 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a6dd1223bf397250529090e459523be771c79382`; original `100644:f9e756df34ca0f1ec56022dcf4cf3247cb08e61d`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,2`, `-8,0+10,2`, `-15,1+19,2`, `-20,0+25,6`, `-23,0+34,1`, `-38,0+50,9`, `-41,0+62,5`, `-126,0+242,55`, `-512,0+649,1`, `-524,1+670,1`, `-526,1+672,1`, `-536,1+682,4`, `-979,0+1165,25`, `-1088,8+1320,8`, `-2743,0+3535,5`, `-2744,1+3541,1`
- U | <module/text>: `-34,1+46,1`, `-78,0+104,89`, `-80,2+195,3`, `-423,26+595,15`, `-450,24+611,0`, `-475,2+612,2`, `-520,0+658,8`, `-2710,0+3154,15`, `-2717,0+3176,258`, `-2718,0+3435,46`, `-2719,19+3482,48`
- U | _desc_repo: `-289,2+460,2`, `-292,2+463,2`
- L | _desc_repo: `-295,2+466,2`, `-300,1+471,1`
- U | _desc_artifact: `-415,1+586,2`
- L | _compact: `-656,1+805,26`, `-664,5+849,5`
- U | _compact: `-658,1+832,12`
- A | _ProtocolAccountingReporter: `-858,1+1043,0`
- A | _ProtocolAccountingReporter._send: `-878,0+1062,1`, `-879,2+1064,0`, `-883,1+1066,1`, `-892,0+1075,2`
- A | _ProtocolAccountingReporter.close: `-937,1+1122,2`, `-939,1+1125,1`
- A | _instrumented_tool.decorator.wrapped: `-994,0+1205,25`, `-1002,0+1238,3`, `-1023,0+1262,1`, `-1049,5+1289,6`, `-1055,14+1296,5`
- U | local_ai_status: `-1143,1+1375,1`
- U | local_ai_task: `-1299,0+1531,20`
- L | local_ai_task: `-1499,3+1751,8`
- A | _validate_context_pack_inputs: `-1559,0+1816,6`, `-1565,0+1828,2`, `-1590,0+1855,4`, `-1592,1+1861,5`, `-1596,0+1869,2`
- L | _context_pack_projection: `-1634,0+1909,1`, `-1645,1+1921,4`, `-1652,0+1931,31`
- L | _local_ai_repo_impl: `-1743,0+2053,4`, `-1772,1+2086,1`, `-1814,3+2134,3`, `-1823,0+2143,27`, `-1828,0+2175,3`, `-1831,1+2181,7`, `-1858,0+2214,13`
- U | _local_ai_repo_impl: `-1807,0+2121,6`, `-1809,1+2129,1`
- L | local_ai_repo: `-2205,0+2574,4`, `-2207,0+2580,34`, `-2213,1+2620,1`
- U | local_ai_rag: `-2253,0+2660,5`, `-2254,1+2666,1`
- L | local_ai_rag: `-2277,0+2689,7`, `-2278,1+2697,4`, `-2281,0+2703,7`, `-2283,2+2712,3`
- L | local_ai_coord: `-2449,0+2879,2`
- A | local_ai_artifact: `-2668,2+3100,2`, `-2671,0+3103,14`, `-2673,2+3119,0`, `-2680,1+3124,1`

### D203 src/local_ai_hub/mcp_server.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b8539eba80276f3d9f9da549dbb9d7aa1f42b4bc`; original `100644:64327e146dbfe3edc01c435de60c84c19a03729d`; pinned-current `100644:1519a91617504d1f2b3628704af763b8f73fc07f`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | _instrumented_tool.decorator.wrapped: `-1062,0+1062,5`
- L | _context_pack_projection: `-1649,1+1654,4`, `-1696,1+1744,1`, `-1699,0+1747,6`
- U | _context_pack_projection: `-1680,0+1688,5`, `-1681,0+1694,10`, `-1691,0+1714,25`
- U | _local_ai_repo_impl: `-1838,1+1892,1`

### D204 src/local_ai_hub/memory.py

Disposition: `integrated-current`. Occurrences: 30:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6a40ddf7165207b27067622e975e1075cc3f06a7`; original `100644:f8d4cc8cf413c015ad7746741d09b056ee23d6e1`; pinned-current `100644:f8d4cc8cf413c015ad7746741d09b056ee23d6e1`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | WorkspaceMemoryStore.delete: `-332,1+332,1`, `-337,0+337,15`

### D205 src/local_ai_hub/model_policy.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:703bff0afdf5367a6a662790997c9c131d1226c8`; original `100644:a6f90c60d3e4f9b8768f0d6c2a772daf53ecd8ef`; pinned-current `100644:7b031ae1a7b2ac507feda504f0d3d2124d90af8e`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | ModelExecutionPolicy: `-207,0+207,84`

### D206 src/local_ai_hub/model_policy.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:703bff0afdf5367a6a662790997c9c131d1226c8`; original `100644:b67d6c373e61d4d09559f2917d9df743fa4de1a3`; pinned-current `100644:7b031ae1a7b2ac507feda504f0d3d2124d90af8e`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | ModelExecutionPolicy: `-207,0+207,84`

### D207 src/local_ai_hub/ollama.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:34b2c7d7bedb4bd026562eeb0a8338e370345307`; original `100644:d1ef00a641229e89aed816fb3e4255ce74264db4`; pinned-current `100644:113720472265832272575b0cca572224ca074407`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`
- U | OllamaRuntime.loaded_model_details: `-850,0+851,6`, `-855,1+862,1`
- U | OllamaRuntime.unload_model: `-953,1+960,1`, `-955,1+962,3`, `-963,1+972,5`
- U | OllamaRuntime: `-968,0+981,163`

### D208 src/local_ai_hub/ollama.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:34b2c7d7bedb4bd026562eeb0a8338e370345307`; original `100644:f227f8bed3979dcbfc466bbce8f24add16a33c9f`; pinned-current `100644:113720472265832272575b0cca572224ca074407`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,1`, `-4,0+5,1`, `-10,0+12,1`, `-176,0+193,15`
- U | <module/text>: `-16,2+19,5`, `-19,0+25,11`
- L | OllamaRuntime.request: `-203,1+235,9`, `-205,1+245,3`, `-235,1+281,1`, `-238,1+284,1`, `-250,1+296,1`, `-265,1+311,1`, `-270,1+316,1`
- U | OllamaRuntime.request: `-229,0+271,4`
- L | OllamaRuntime: `-272,1+318,111`, `-403,1+657,709`, `-834,0+1847,39`, `-929,0+2077,7`
- A | OllamaRuntime.request_stream: `-275,1+431,10`, `-284,0+449,4`, `-288,0+457,4`, `-289,0+462,4`, `-295,2+472,1`, `-298,0+474,1`, `-299,1+476,1`, `-301,0+478,1`, `-305,0+483,1`, `-309,2+488,44`, `-313,0+534,1`, `-314,2+536,7`, `-318,1+545,1`, `-331,2+558,4`, `-341,2+570,4`, `-358,0+589,2`, `-385,1+618,1`, `-390,0+623,2`, `-392,0+627,1`, `-394,0+630,4`, `-395,0+635,1`, `-397,0+638,4`, `-399,0+644,1`, `-400,1+646,9`
- A | OllamaRuntime.request_interruptible: `-412,0+1374,1`, `-428,0+1391,10`, `-432,1+1405,2`, `-436,0+1410,5`, `-443,0+1422,4`, `-445,0+1428,4`, `-452,2+1439,1`, `-459,2+1445,22`, `-463,5+1469,2`, `-497,1+1500,1`, `-500,0+1503,5`, `-501,0+1509,6`, `-502,5+1516,4`
- A | OllamaRuntime.loaded_model_details: `-838,1+1890,7`, `-840,1+1898,5`, `-842,1+1904,5`, `-844,0+1910,9`
- A | OllamaRuntime.prepare_model: `-874,1+1949,9`, `-884,0+1967,16`, `-886,1+1985,11`, `-888,0+1997,1`, `-892,0+2002,1`, `-894,1+2005,2`, `-900,0+2012,1`, `-901,1+2014,1`, `-903,0+2016,1`, `-910,1+2024,23`, `-915,1+2051,5`, `-924,1+2064,9`
- A | OllamaRuntime.unload_model: `-953,3+2108,15`, `-963,1+2130,1`
- U | OllamaRuntime: `-969,1+2136,303`
- A | OllamaRuntime.generate: `-977,0+2446,4`, `-981,0+2454,3`
- A | OllamaRuntime.chat: `-983,1+2459,10`, `-988,0+2473,3`

### D209 src/local_ai_hub/ollama.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:34b2c7d7bedb4bd026562eeb0a8338e370345307`; original `100644:f780537d455fe1bddd0a1bf798706c8a4b9c8c22`; pinned-current `100644:113720472265832272575b0cca572224ca074407`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-19,0+20,2`
- U | OllamaRuntime: `-969,0+972,146`

### D210 src/local_ai_hub/ollama.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:85deabb8678801be51fe7b3fdd7b0bb8f3c635c2`; original `100644:c5dda6f5a69a739b2b8560f4af6304bbf885afce`; pinned-current `100644:113720472265832272575b0cca572224ca074407`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-26,0+26,1`, `-196,0+197,9`
- A | OllamaRuntime.request: `-254,0+264,4`, `-256,1+270,1`
- L | OllamaRuntime.run_benchmark_scenario: `-689,0+703,2`, `-692,0+708,4`, `-750,0+770,1`, `-917,1+955,0`, `-922,4+959,0`, `-964,1+997,4`, `-1034,18+1070,18`, `-1085,7+1121,9`, `-1110,2+1148,9`, `-1123,6+1168,2`, `-1131,3+1172,3`, `-1137,2+1178,3`, `-1222,1+1264,6`, `-1240,0+1287,4`, `-1273,1+1324,2`
- U | OllamaRuntime.run_benchmark_scenario.run_item: `-803,0+824,1`
- A | OllamaRuntime.run_benchmark_scenario.run_item.execute: `-821,1+843,1`, `-834,0+856,4`, `-836,0+862,13`, `-838,6+877,1`
- L | OllamaRuntime.run_benchmark_scenario.run_item: `-887,0+921,3`, `-898,0+935,1`
- A | OllamaRuntime.prepare_model: `-1884,0+1936,1`, `-1914,0+1967,5`, `-1949,1+2007,21`
- L | OllamaRuntime: `-1981,0+2059,7`, `-2033,1+2118,480`
- A | OllamaRuntime.generate: `-2049,0+2613,3`
- A | OllamaRuntime.chat: `-2051,1+2618,10`, `-2056,0+2632,3`

### D211 src/local_ai_hub/ollama_subagents.py

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ee05cc7fe379c5223eff423f4d2969a753785b72`; original `100644:5508473e7485cec7ff35305c46f4495aeee0d4a4`; pinned-current `100644:5508473e7485cec7ff35305c46f4495aeee0d4a4`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | OllamaSubagentCatalog.system_contract: `-121,1+121,1`

### D212 src/local_ai_hub/operation_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2ef2b0a3e574e3f88d040cb332059e4deccfa933`; original `100644:bbee5bf01ffb17a4a5506574237c7e3ad75935f9`; pinned-current `100644:16a8e86e9bcfdf0b69ea0ff766259dc405e4f459`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-89,0+89,9`, `-202,0+215,19`, `-203,0+235,1`, `-249,0+282,9`, `-279,0+321,7`, `-338,0+388,6`, `-360,0+416,4`, `-364,1+424,1`, `-367,0+427,18`, `-423,0+503,187`, `-559,0+857,205`
- L | <module/text>: `-185,0+194,4`, `-298,0+347,1`, `-388,2+466,2`, `-418,0+496,2`, `-936,0+1507,13`
- U | operation_input_schema: `-471,0+738,2`, `-475,0+744,1`
- L | operation_tool_input_schema: `-487,1+757,1`
- U | operation_tool_input_schema: `-511,0+781,9`, `-520,2+799,6`
- U | operation_output_schema: `-538,0+821,6`, `-545,0+834,11`, `-550,1+850,1`, `-552,6+852,4`
- A | _status_output_variants: `-628,0+1131,50`
- U | operation_tool_output_schema: `-708,1+1261,1`, `-712,14+1265,3`, `-729,3+1271,2`
- U | _validate_output_schema: `-742,0+1283,4`
- U | validate_operation_output: `-765,1+1310,1`, `-767,9+1312,12`
- U | operation_parameters_schema: `-874,0+1422,19`
- A | _matches_json_type: `-926,1+1493,5`
- U | _validate_nested_schema: `-974,0+1558,5`, `-977,1+1566,1`
- U | validate_operation_arguments: `-1011,0+1600,2`, `-1053,0+1647,15`
- L | validate_operation_arguments: `-1019,0+1610,3`

### D213 src/local_ai_hub/pipeline.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:081bdefb942806622dc37016b25e2a8a2517432b`; original `100644:7b4c8879077f3822951ed118097424e747cf8518`; pinned-current `100644:8e82beba087b25a51a6711a7399873c3415a2466`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,1+6,0`

### D214 src/local_ai_hub/pipeline.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:081bdefb942806622dc37016b25e2a8a2517432b`; original `100644:9b17826197ce6c00ab80af35ebc3e8d8f5617df8`; pinned-current `100644:8e82beba087b25a51a6711a7399873c3415a2466`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | LocalAgentPipeline.__init__: `-68,1+68,1`

### D215 src/local_ai_hub/preprocess.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24bdf600220917e1a0ab518640d12a9efb6380fb`; original `100644:25d843a54ca91c2de907d3732338f35656d20902`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-19,0+19,6`
- U | ProjectPreprocessor: `-1144,0+1150,76`
- U | ProjectPreprocessor._step: `-1740,0+1822,10`
- L | ProjectPreprocessor._step_incremental_inventory: `-1770,0+1862,1`, `-1803,0+1896,7`, `-1890,0+1990,1`
- L | ProjectPreprocessor._step_inventory: `-1927,0+2028,2`, `-1975,1+2092,6`, `-1978,1+2100,5`
- U | ProjectPreprocessor._step_inventory: `-1944,1+2047,14`, `-1972,0+2088,1`
- A | ProjectPreprocessor.candidate_paths: `-2663,0+2789,4`, `-2685,2+2815,15`, `-2689,1+2832,12`

### D216 src/local_ai_hub/preprocess.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24bdf600220917e1a0ab518640d12a9efb6380fb`; original `100644:272692c7f859d0f4cc9ac7b3f6f36058fea81df2`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | ProjectPreprocessor: `-235,0+235,8`, `-259,0+271,10`
- U | ProjectPreprocessor._run_project_step: `-250,0+258,2`, `-256,0+266,2`
- U | ProjectPreprocessor.status: `-1155,0+1177,1`, `-1436,1+1459,1`
- L | ProjectPreprocessor.status: `-1158,1+1181,1`, `-1451,1+1474,1`, `-1457,1+1480,1`
- U | ProjectPreprocessor._cpu_loop: `-1561,3+1584,2`, `-1566,2+1588,1`, `-1571,2+1592,1`, `-1578,2+1598,1`, `-1589,1+1608,1`
- U | ProjectPreprocessor._gpu_loop: `-1615,3+1634,2`, `-1620,2+1638,1`, `-1625,2+1642,1`, `-1632,2+1648,1`, `-1641,1+1656,1`, `-1645,1+1660,1`
- U | ProjectPreprocessor._yield: `-1648,1+1663,1`
- U | ProjectPreprocessor._gpu_yield: `-1655,1+1670,6`
- U | ProjectPreprocessor._run_background_generate.execute: `-2764,0+2784,9`

### D217 src/local_ai_hub/preprocess.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24bdf600220917e1a0ab518640d12a9efb6380fb`; original `100644:4d4ccc421ec3c179e7a6ffd770f82bf299c73faa`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S010 / ab60c0a1d39753965dc87842e04638f10bae6e83 / true / 04ff61ebc4fb00005b786dc6f123cc12ce3871eb`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | ProjectPreprocessor.status: `-1390,5+1390,0`
- A | ProjectPreprocessor._external_error_is_revision_scoped: `-2651,1+2646,0`

### D218 src/local_ai_hub/preprocess.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24bdf600220917e1a0ab518640d12a9efb6380fb`; original `100644:6ffeeefd77ef33def5c715587887f6b88df09d64`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | ProjectPreprocessor._step_incremental_inventory._content_identity: `-1820,1+1820,5`
- A | ProjectPreprocessor._step_hash._hash_one: `-2101,1+2105,6`

### D219 src/local_ai_hub/preprocess.py

Disposition: `preserved-only-needs-integration`. Occurrences: 18:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24bdf600220917e1a0ab518640d12a9efb6380fb`; original `100644:72e49183037d6cc24ecaaba6c8c569102f6bb936`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S023 / b0ade36afca1bceeb6756fe76eeb0ca90758e64a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | ProjectPreprocessor._run_project_step: `-249,0+249,7`
- U | ProjectPreprocessor._run_background_generate: `-2739,0+2746,7`

### D220 src/local_ai_hub/preprocess.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24bdf600220917e1a0ab518640d12a9efb6380fb`; original `100644:e538bb78880e69b67d942ea01149a3c29c6d8775`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-8,0+8,1`
- A | ProjectPreprocessor._run_project_step: `-249,0+250,2`
- A | ProjectPreprocessor.notify_path_changed: `-663,0+666,2`
- A | ProjectPreprocessor._seed_from_parent: `-844,1+849,1`, `-846,1+851,1`, `-849,5+854,66`, `-855,6+921,1`, `-863,13+924,34`, `-877,1+959,0`
- L | ProjectPreprocessor.status: `-1155,0+1236,1`, `-1158,1+1240,1`, `-1390,5+1472,0`, `-1451,1+1528,1`, `-1457,1+1534,1`
- A | ProjectPreprocessor._cpu_loop: `-1565,0+1642,4`
- A | ProjectPreprocessor._gpu_loop: `-1619,0+1700,4`
- A | ProjectPreprocessor._yield: `-1648,1+1733,1`
- L | ProjectPreprocessor: `-1654,0+1739,25`
- A | ProjectPreprocessor._gpu_yield: `-1655,1+1765,6`
- A | ProjectPreprocessor._fs_watcher_loop._Handler.on_any_event: `-1677,0+1792,2`
- A | ProjectPreprocessor._fs_watcher_loop: `-1697,1+1814,0`, `-1699,0+1815,15`, `-1725,0+1856,6`
- L | ProjectPreprocessor._step: `-1732,0+1869,4`
- A | ProjectPreprocessor._step_incremental_inventory._content_identity: `-1820,1+1961,5`
- A | ProjectPreprocessor._step_incremental_inventory._apply: `-1857,0+2002,6`, `-1867,0+2018,1`, `-1873,1+2025,1`
- A | ProjectPreprocessor._step_hash._hash_one: `-2101,1+2253,6`
- L | ProjectPreprocessor._step_code_index: `-2439,2+2596,7`, `-2442,2+2604,1`
- A | ProjectPreprocessor._external_error_is_revision_scoped: `-2651,1+2812,0`
- A | ProjectPreprocessor._run_background_generate.execute: `-2764,0+2924,3`
- L | ProjectPreprocessor._step_diagnostics: `-3199,2+3362,11`, `-3210,0+3382,17`, `-3211,1+3400,1`

### D221 src/local_ai_hub/preprocess.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6f3efedb919105b1eda049e505404d06ccd490ea`; original `100644:6241073143caddab7650669a0c8cab1445fbd853`; pinned-current `100644:2069443ffa4babb5cad7db96bdf18ff326b593de`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | ProjectPreprocessor._watch_relevant: `-652,0+652,2`, `-653,1+655,20`
- U | ProjectPreprocessor: `-661,0+682,76`, `-1649,0+1759,25`
- A | ProjectPreprocessor.notify_path_changed: `-663,0+760,2`
- A | ProjectPreprocessor.cache_fingerprint: `-734,0+833,2`, `-737,1+838,1`, `-743,1+844,2`
- U | ProjectPreprocessor._cpu_loop: `-1560,0+1662,4`
- U | ProjectPreprocessor._gpu_loop: `-1614,0+1720,4`
- A | ProjectPreprocessor._fs_watcher_loop._Handler.on_any_event: `-1672,0+1807,2`
- A | ProjectPreprocessor._fs_watcher_loop: `-1692,1+1829,0`, `-1694,0+1830,15`, `-1720,0+1871,6`
- L | ProjectPreprocessor._step: `-1727,0+1884,4`
- U | ProjectPreprocessor._step: `-1735,0+1896,15`
- L | ProjectPreprocessor._step_incremental_inventory: `-1769,0+1945,3`
- U | ProjectPreprocessor._step_incremental_inventory: `-1786,0+1965,1`, `-1798,0+1978,7`
- U | ProjectPreprocessor._step_inventory: `-1939,1+2126,12`, `-1967,0+2165,4`
- U | ProjectPreprocessor._step_code_index: `-2419,1+2621,8`, `-2422,1+2631,1`, `-2424,0+2633,3`
- A | ProjectPreprocessor._step_project: `-3041,1+3253,1`
- L | ProjectPreprocessor._step_diagnostics: `-3186,1+3398,1`

### D222 src/local_ai_hub/process_utils.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; original `100644:497073e55861e180cdd0a39317bbe0af6413ad44`; pinned-current `100644:3262eeb65f8d71689d2727166b3d323dcecdccc6`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-877,0+1043,22`, `-919,1+1204,0`
- U | <module/text>: `-13,0+14,1`, `-20,0+22,33`
- L | run_hidden: `-430,0+465,2`, `-461,0+498,2`
- U | run_hidden: `-485,1+524,38`
- U | _terminate_and_drain: `-517,1+593,5`, `-519,1+599,3`, `-521,0+603,1`, `-522,1+605,2`, `-524,1+608,1`, `-529,1+613,1`, `-539,1+623,1`, `-555,1+639,1`, `-565,1+649,17`
- L | create_git_worktree: `-841,0+941,6`, `-849,0+955,2`, `-850,1+958,17`, `-852,0+976,1`, `-853,2+978,1`, `-856,1+980,8`, `-867,0+999,19`, `-870,0+1021,1`, `-874,0+1026,5`, `-876,0+1033,9`
- U | create_git_worktree: `-859,0+990,1`
- L | remove_git_worktree: `-884,0+1072,7`, `-891,3+1096,12`, `-895,2+1109,11`, `-898,5+1121,22`, `-904,0+1144,45`, `-905,2+1190,2`, `-916,0+1200,1`
- U | remove_git_worktree: `-885,1+1080,1`, `-890,0+1085,10`, `-909,1+1194,0`

### D223 src/local_ai_hub/process_utils.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; original `100644:5ac7f798e059e51d04d953e389c4215703146e3d`; pinned-current `100644:3262eeb65f8d71689d2727166b3d323dcecdccc6`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | terminate_tree.group_alive: `-312,1+312,1`
- U | terminate_tree: `-319,0+319,14`, `-321,9+335,1`, `-332,1+338,2`, `-334,0+341,2`, `-337,0+346,2`, `-338,5+349,3`, `-344,1+353,1`
- L | <module/text>: `-836,0+845,51`
- L | create_git_worktree: `-841,0+901,6`, `-849,0+915,2`, `-850,1+918,17`, `-852,0+936,1`, `-853,2+938,1`, `-870,0+1000,1`
- U | create_git_worktree: `-856,1+940,8`, `-860,1+951,1`, `-867,0+958,39`, `-874,0+1005,5`
- U | remove_git_worktree: `-884,0+1020,3`, `-885,1+1024,1`, `-887,1+1026,4`, `-890,0+1032,4`, `-892,2+1038,16`, `-895,2+1055,19`, `-898,5+1075,26`, `-906,3+1104,9`, `-912,1+1116,1`, `-916,0+1120,1`
- A | list_git_worktrees: `-927,1+1132,1`
- A | prune_git_worktrees: `-970,1+1175,1`
- U | <module/text>: `-1104,0+1309,1`

### D224 src/local_ai_hub/process_utils.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; original `100644:63308722d63dda01f83adef5dd7944a66477d975`; pinned-current `100644:3262eeb65f8d71689d2727166b3d323dcecdccc6`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-11,0+11,1`
- L | <module/text>: `-26,0+27,27`, `-41,3+69,0`, `-59,0+84,34`, `-94,0+127,40`, `-119,0+194,239`
- A | _windows_process_identity_from_handle: `-38,1+66,1`
- A | _windows_process_identity: `-61,1+120,0`, `-66,26+124,1`
- A | process_identity: `-103,0+176,2`

### D225 src/local_ai_hub/process_utils.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; original `100644:98bd2b72b4c089c8cbde25a0c35b2d30d188ec2f`; pinned-current `100644:3262eeb65f8d71689d2727166b3d323dcecdccc6`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-20,0+20,32`
- L | run_hidden: `-430,0+462,2`, `-461,0+495,2`
- U | run_hidden: `-485,1+521,38`
- U | _terminate_and_drain: `-517,1+590,5`, `-519,1+596,3`, `-521,0+600,1`, `-522,1+602,2`, `-524,1+605,1`, `-529,1+610,1`, `-539,1+620,1`, `-555,1+636,1`, `-565,1+646,17`

### D226 src/local_ai_hub/process_utils.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d0488b75c3fb5c589d6d79afe362c228c7a69ee5`; original `100644:b0bacbed2fcd6d0f44d82aaa0f7053e1e96feacd`; pinned-current `100644:3262eeb65f8d71689d2727166b3d323dcecdccc6`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-20,0+20,12`
- L | run_hidden: `-430,0+442,2`, `-461,0+475,2`
- U | run_hidden: `-485,1+501,35`
- U | _terminate_and_drain: `-517,1+567,4`, `-519,1+572,3`

### D227 src/local_ai_hub/project_config.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`; original `100644:22e3fd49176e330a72e006e1b59cd14b6a60ba42`; pinned-current `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,1`, `-1124,0+1262,6`
- A | ProjectContext: `-192,0+193,12`
- A | ProjectContext.prioritize_paths: `-229,1+242,5`, `-240,0+257,1`
- L | <module/text>: `-313,0+331,67`
- L | _normalize: `-471,1+556,3`, `-542,0+629,8`
- A | _read_layer: `-647,1+742,3`, `-649,5+746,21`, `-662,0+775,8`
- A | _safe_config_file: `-667,1+788,1`, `-669,1+790,9`, `-671,1+800,1`
- A | _resolve_project_config: `-696,0+825,1`, `-698,1+828,6`, `-709,1+844,2`, `-711,1+847,2`
- A | validate_path_hint: `-766,0+903,2`
- A | prioritize_paths_with_hints: `-823,0+962,1`, `-841,1+981,1`
- U | path_is_allowed: `-934,5+1074,4`
- L | path_is_allowed: `-940,1+1079,1`
- U | may_descend: `-1078,4+1217,3`
- L | may_descend: `-1092,1+1230,1`, `-1094,1+1232,1`
- L | _path_override_for_paths: `-1126,0+1270,1`
- U | ProjectPathHintStore._connect: `-1274,2+1419,8`
- U | ProjectPathHintStore.find: `-1352,19+1503,32`

### D228 src/local_ai_hub/project_config.py

Disposition: `preserved-only-needs-integration`. Occurrences: 10:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`; original `100644:31b3adcbac3f4c87b54216e99605eb6ba25d233a`; pinned-current `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`.

Exact checkpoint/owner witnesses: `S031 / c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3 / true / f99619a4658692b2d15d40a07f2176891c72cffa`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | ProjectContext: `-191,0+191,7`

### D229 src/local_ai_hub/project_config.py

Disposition: `preserved-only-needs-integration`. Occurrences: 12:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`; original `100644:3ebbb2c9b1ebd12c4e757d35b6378a100084f80a`; pinned-current `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`.

Exact checkpoint/owner witnesses: `S081 / 388086357ab954fbf208def00ba1ce5a60170598 / true / fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,1`
- L | <module/text>: `-315,0+316,67`, `-1124,0+1241,6`
- A | _normalize: `-471,1+539,3`, `-542,0+612,8`, `-569,0+647,2`
- A | _read_layer: `-647,1+727,3`, `-649,5+731,21`, `-662,0+760,6`
- L | _safe_config_file: `-667,1+771,1`, `-671,1+781,1`
- U | _safe_config_file: `-669,1+773,7`
- L | _resolve_project_config: `-696,0+806,1`, `-698,1+809,6`
- U | _resolve_project_config: `-709,1+825,2`, `-711,1+828,2`
- A | path_is_allowed: `-934,5+1052,4`, `-940,1+1057,1`
- A | _path_override_for_candidates: `-1126,0+1249,1`
- A | ProjectPathHintStore: `-1256,2+1380,14`, `-1273,4+1409,0`
- A | ProjectPathHintStore.find: `-1352,19+1484,34`

### D230 src/local_ai_hub/project_config.py

Disposition: `preserved-only-needs-integration`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`; original `100644:67c901b92302f992fbffdf0c8c414d3ada119ba8`; pinned-current `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-315,0+315,67`, `-1124,0+1206,6`
- U | _normalize: `-542,0+609,8`
- L | _normalize: `-569,0+644,2`
- L | _resolve_project_config: `-696,0+773,1`, `-698,1+776,6`
- A | path_is_allowed: `-934,5+1017,4`, `-940,1+1022,1`
- A | _path_override_for_candidates: `-1126,0+1214,1`
- A | ProjectPathHintStore: `-1256,2+1345,14`, `-1273,4+1374,0`
- A | ProjectPathHintStore.find: `-1352,19+1449,34`

### D231 src/local_ai_hub/project_config.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 11:T/M, 25:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`; original `100644:769d2bfd609be5c1cf9039e1cf5ff88cde1338c7`; pinned-current `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`.

Exact checkpoint/owner witnesses: `S017 / 281cf99b1d7bf265d06a315bbadf168bef4d1ac5 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-10,0+10,1`, `-313,0+326,67`, `-1124,0+1259,6`
- L | ProjectContext: `-192,0+193,12`
- A | _normalize: `-471,1+551,3`, `-542,0+624,8`, `-569,0+659,2`
- A | _read_layer: `-647,1+739,3`, `-649,5+743,21`, `-662,0+772,8`
- A | _safe_config_file: `-667,1+785,1`, `-669,1+787,9`, `-671,1+797,1`
- A | _resolve_project_config: `-696,0+822,1`, `-698,1+825,6`, `-709,1+841,2`, `-711,1+844,2`
- A | validate_path_hint: `-766,0+900,2`
- A | path_is_allowed: `-934,5+1070,4`, `-940,1+1075,1`
- A | _path_override_for_candidates: `-1126,0+1267,1`
- A | ProjectPathHintStore: `-1256,2+1398,14`, `-1273,4+1427,0`
- A | ProjectPathHintStore.find: `-1352,19+1502,34`

### D232 src/local_ai_hub/project_config.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7bf849ce6948d7f54876fe4ea779dfd45b0f6c`; original `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`; pinned-current `100644:b64d839d071921163e61d6b1369d8f882b8bba5d`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-10,0+10,1`, `-313,0+331,67`, `-1124,0+1264,6`
- B | ProjectContext: `-192,0+193,12`
- B | ProjectContext.prioritize_paths: `-229,1+242,5`, `-240,0+257,1`
- B | _normalize: `-471,1+556,3`, `-542,0+629,8`, `-569,0+664,2`
- B | _read_layer: `-647,1+744,3`, `-649,5+748,21`, `-662,0+777,8`
- B | _safe_config_file: `-667,1+790,1`, `-669,1+792,9`, `-671,1+802,1`
- B | _resolve_project_config: `-696,0+827,1`, `-698,1+830,6`, `-709,1+846,2`, `-711,1+849,2`
- B | validate_path_hint: `-766,0+905,2`
- B | prioritize_paths_with_hints: `-823,0+964,1`, `-841,1+983,1`
- B | path_is_allowed: `-934,5+1076,4`, `-940,1+1081,1`
- B | may_descend: `-1078,4+1219,3`, `-1092,1+1232,1`, `-1094,1+1234,1`
- B | _path_override_for_candidates: `-1126,0+1272,1`
- B | ProjectPathHintStore: `-1256,2+1403,14`, `-1273,4+1432,0`
- B | ProjectPathHintStore.find: `-1352,19+1507,34`

### D233 src/local_ai_hub/projection.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a0cc5e8b9469550a882452f0953e62fa3ef6e8b5`; original `100644:24ed5cfb47b698acd4340cebeddda5f8e5f79536`; pinned-current `100644:651f563a4b578e4b0316408edcdd82a26c403e7e`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | AgentProjector._project: `-379,1+379,8`

### D234 src/local_ai_hub/projection.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a0cc5e8b9469550a882452f0953e62fa3ef6e8b5`; original `100644:651f563a4b578e4b0316408edcdd82a26c403e7e`; pinned-current `100644:651f563a4b578e4b0316408edcdd82a26c403e7e`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | AgentProjector._project: `-177,1+177,1`
- B | AgentProjector._clean_empty: `-384,1+384,1`

### D235 src/local_ai_hub/rag.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:19dc6bee0d37eea39627f7696616e1fc51b8d1bc`; original `100644:21539a95133fe1e20cd15af311db4d0a6c12c4d8`; pinned-current `100644:72de25bf60042ca859b55375a76566cc05a3fa10`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-24,0+24,7`
- U | RAGStore: `-275,1+282,7`, `-511,0+540,115`
- U | RAGStore._iter_files: `-280,0+293,3`, `-283,0+299,5`, `-300,0+321,5`, `-301,1+327,4`
- U | RAGStore._index_locked: `-595,0+739,4`, `-596,0+744,3`, `-615,1+766,1`
- A | RAGStore.prune_missing: `-813,0+964,6`, `-824,0+981,2`, `-825,1+984,1`
- U | RAGStore.index_paths_step: `-871,0+1030,7`, `-877,0+1043,3`, `-879,0+1048,1`, `-896,0+1066,20`, `-909,1+1099,4`
- U | RAGStore.index_step: `-1083,0+1276,7`, `-1085,0+1285,3`
- L | RAGStore.index_step: `-1105,1+1308,1`
- A | RAGStore.revision: `-1309,1+1512,1`, `-1311,0+1514,2`, `-1313,1+1518,1`, `-1320,1+1525,1`, `-1326,1+1531,1`

### D236 src/local_ai_hub/rag.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:19dc6bee0d37eea39627f7696616e1fc51b8d1bc`; original `100644:d648b819a41db98aafb083a11f35bc06e7958d29`; pinned-current `100644:72de25bf60042ca859b55375a76566cc05a3fa10`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | RAGStore.__init__: `-158,1+158,1`
- L | RAGStore._search_uncached: `-1719,1+1719,1`

### D237 src/local_ai_hub/rag.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:19dc6bee0d37eea39627f7696616e1fc51b8d1bc`; original `100644:e836dd25c80cc565269848385170e50698b34528`; pinned-current `100644:72de25bf60042ca859b55375a76566cc05a3fa10`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,1`, `-10,0+11,1`, `-31,0+33,8`, `-112,0+122,8`
- L | RAGStore.__init__: `-150,0+168,5`
- A | RAGStore._init_db: `-208,0+231,14`, `-254,1+291,1`, `-258,0+295,4`, `-262,0+303,4`, `-264,0+309,1`
- L | RAGStore: `-275,1+321,54`, `-511,0+640,322`, `-1373,1+2087,22`
- A | RAGStore._iter_files: `-280,0+379,4`, `-283,0+386,5`, `-286,0+394,3`, `-292,1+403,5`, `-300,0+415,6`, `-301,2+422,7`, `-304,0+430,3`
- A | RAGStore._embedding_space_id: `-515,1+966,1`, `-524,1+975,2`, `-532,3+984,4`, `-536,1+989,0`
- A | RAGStore.index: `-582,1+1034,4`
- A | RAGStore._index_locked: `-590,4+1045,25`, `-596,1+1072,2`, `-599,0+1076,1`, `-608,0+1086,11`, `-610,1+1099,2`, `-612,0+1102,3`, `-615,1+1108,5`, `-622,0+1119,3`, `-626,0+1126,14`, `-631,1+1145,4`, `-635,0+1152,3`, `-638,0+1158,1`, `-642,1+1163,0`, `-647,0+1167,4`, `-651,1+1175,5`, `-653,1+1181,1`, `-657,0+1185,1`, `-685,1+1214,0`, `-689,1+1217,10`, `-701,1+1238,1`, `-710,1+1247,0`, `-720,1+1256,0`, `-722,1+1257,0`, `-725,1+1259,0`, `-727,20+1260,36`, `-804,0+1373,1`, `-805,0+1375,1`
- A | RAGStore._index_locked.publish: `-754,1+1303,6`, `-758,1+1312,1`, `-760,2+1314,0`, `-769,0+1321,8`, `-773,0+1333,9`
- A | RAGStore.prune_missing: `-813,0+1384,6`, `-824,0+1401,2`, `-825,1+1404,1`
- A | RAGStore.index_paths_step: `-863,0+1442,1`, `-871,0+1451,7`, `-872,1+1459,1`, `-877,0+1464,71`, `-879,0+1537,5`, `-881,0+1544,1`, `-889,1+1553,1`, `-891,0+1555,7`, `-896,0+1567,19`, `-898,2+1588,5`, `-902,1+1595,4`, `-907,0+1603,1`, `-909,1+1606,6`, `-911,0+1613,14`, `-913,0+1629,2`, `-914,0+1632,1`, `-929,1+1648,1`, `-962,1+1681,1`, `-984,1+1703,1`, `-992,21+1711,47`, `-1032,14+1777,43`, `-1047,12+1821,5`, `-1062,0+1829,2`, `-1064,0+1833,1`
- A | RAGStore.index_step: `-1073,0+1843,1`, `-1082,0+1853,7`, `-1085,0+1863,6`, `-1098,0+1882,6`, `-1105,1+1895,1`, `-1116,0+1906,2`, `-1117,2+1909,15`, `-1130,1+1935,8`, `-1140,147+1952,0`
- A | RAGStore.search: `-1365,4+2030,53`
- A | RAGStore._search_fts_candidates: `-1381,0+2116,2`, `-1382,0+2119,1`, `-1385,1+2123,1`, `-1388,1+2126,1`, `-1390,1+2128,1`, `-1394,1+2132,1`, `-1397,1+2135,1`, `-1399,1+2137,1`
- A | RAGStore._search_token_overlap: `-1411,1+2149,5`, `-1416,0+2158,2`, `-1417,0+2161,1`, `-1420,2+2165,2`, `-1425,2+2170,2`
- L | RAGStore._search_uncached: `-1443,0+2188,6`, `-1465,1+2216,5`, `-1467,1+2222,5`, `-1483,1+2242,3`, `-1487,0+2248,4`, `-1488,0+2253,2`, `-1493,1+2260,5`, `-1533,0+2306,1`, `-1538,2+2312,4`, `-1581,1+2357,2`, `-1587,6+2364,23`, `-1609,0+2403,24`, `-1611,0+2429,13`, `-1624,1+2455,3`, `-1707,1+2540,1`, `-1754,0+2587,1`
- A | RAGStore._search_uncached.offer: `-1511,0+2282,2`
- A | RAGStore.docset_index: `-1770,1+2604,3`
- A | RAGStore.docset_search: `-1775,1+2611,3`
- A | RAGStore.ingest_document: `-1787,1+2625,12`, `-1792,1+2641,2`, `-1796,1+2646,15`, `-1798,1+2662,1`, `-1811,7+2675,17`, `-1819,4+2693,6`, `-1837,4+2715,21`, `-1842,12+2737,9`, `-1855,0+2747,2`, `-1860,1+2754,4`
- A | RAGStore.ingest_document.publish_document: `-1828,8+2704,10`
- A | RAGStore.ingest_diagram: `-1881,1+2778,1`, `-1884,0+2781,1`, `-1886,1+2784,17`, `-1888,1+2802,2`, `-1890,1+2805,5`, `-1894,2+2813,0`, `-1905,1+2822,1`, `-1907,0+2824,2`

### D238 src/local_ai_hub/repo_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:35b6ec45b40abeb6c18c32368454727d537b9923`; original `100644:3703f98c83de26b85ba629b5fea5978f70556f18`; pinned-current `100644:0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,1`
- L | <module/text>: `-29,0+30,30`
- L | RepositoryTools.__init__: `-94,1+125,1`, `-113,0+144,1`, `-127,1+159,2`, `-129,1+162,1`, `-133,1+166,1`
- U | RepositoryTools: `-226,0+259,15`
- L | RepositoryTools._iter_files_with_stat: `-279,8+327,3`
- U | RepositoryTools._iter_files_with_stat: `-289,1+332,2`, `-294,1+338,1`
- U | RepositoryTools._read_snapshot: `-296,1+340,1`, `-298,1+342,3`, `-303,1+357,1`
- L | RepositoryTools._read_snapshot: `-301,0+347,8`, `-315,1+369,4`, `-330,1+387,1`
- A | RepositoryTools._windows_change_time: `-348,1+405,0`, `-351,26+407,1`
- L | RepositoryTools: `-412,0+443,7`
- A | RepositoryTools._hash_file_only: `-420,1+458,11`, `-434,1+482,1`, `-439,0+487,4`, `-449,1+501,2`, `-452,1+505,1`, `-454,1+507,1`, `-456,1+509,4`
- L | RepositoryTools.snapshot_stats: `-788,0+844,1`
- A | RepositoryTools._git_grep_pathspecs: `-830,1+887,0`, `-833,0+889,2`
- A | RepositoryTools._git_grep_command: `-838,1+896,1`
- U | RepositoryTools._ripgrep_candidates: `-849,0+907,6`, `-855,0+919,5`, `-862,0+931,2`
- U | RepositoryTools.search: `-993,4+1064,9`, `-998,0+1074,9`, `-1009,0+1094,6`, `-1040,0+1131,4`
- L | RepositoryTools.search_paths: `-1684,1+1779,1`
- U | RepositoryTools.search_paths: `-1686,0+1781,2`
- A | RepositoryTools.file_inventory: `-1825,1+1922,1`, `-1827,1+1924,0`, `-1834,1+1930,1`

### D239 src/local_ai_hub/repo_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 13:T/M, 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3dd3b82937cd715294bc5cb20580b5f1419e5409`; original `100644:5d781080f214ee12fc6dc933bbb2c9e6b4901714`; pinned-current `100644:0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f`.

Exact checkpoint/owner witnesses: `S026 / 9a40aeca4c84d28cdbe56243f45bfa410d6f216e / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | RepositoryTools: `-1517,0+1517,56`
- U | RepositoryTools.context_pack_paths: `-1521,27+1577,1`
- A | RepositoryTools.context_pack: `-1613,29+1643,1`

### D240 src/local_ai_hub/repo_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 23:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:accf9f0252e60fd8f038120dcc97a7332a337d2e`; original `100644:d7d5163f53b3bdbbc66d251fccec5b2b3eddcc8b`; pinned-current `100644:0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f`.

Exact checkpoint/owner witnesses: `S066 / 6224ec2038e26d49646ce6ea9992a03904dd07c2 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | RepositoryTools.__init__: `-94,1+94,1`

### D241 src/local_ai_hub/repo_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bde9d8e8a31f2237ce75ec1f3b7096b0ee219de9`; original `100644:c20fa74acc80897d9817b8966abddb4fbf2480c3`; pinned-current `100644:0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-14,1+15,1`
- L | <module/text>: `-24,0+25,3`
- U | RepositoryTools.__init__: `-94,1+98,1`, `-127,1+134,1`
- L | RepositoryTools.__init__: `-106,0+110,3`, `-138,0+145,1`
- U | RepositoryTools.iter_files: `-224,1+232,3`, `-226,0+236,3`
- U | RepositoryTools._read_snapshot: `-295,1+308,1`, `-299,0+312,2`, `-301,1+316,0`, `-304,2+318,4`, `-308,0+324,8`, `-314,1+340,1`, `-316,1+342,2`
- L | RepositoryTools._read_snapshot: `-311,0+335,2`
- U | RepositoryTools: `-324,0+351,72`, `-1561,2+1945,157`
- U | RepositoryTools._hash_file_only: `-333,1+432,2`, `-343,2+446,5`, `-354,0+460,8`, `-355,0+469,1`
- L | RepositoryTools._hash_file_only: `-338,2+438,5`
- L | RepositoryTools: `-358,0+473,9`, `-876,1+1050,193`
- A | RepositoryTools._ripgrep_candidates: `-739,1+863,4`, `-742,13+869,0`, `-757,1+871,43`, `-759,1+915,9`, `-761,20+925,30`
- U | RepositoryTools.search: `-885,0+1251,1`, `-886,1+1253,7`, `-890,1+1263,1`, `-933,1+1306,8`, `-935,0+1315,1`, `-976,0+1357,3`
- U | RepositoryTools.search_paths: `-1564,0+2103,70`, `-1570,2+2179,1`, `-1575,7+2183,0`
- U | RepositoryTools.context_pack_paths: `-1622,2+2223,12`

### D242 src/local_ai_hub/repo_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bde9d8e8a31f2237ce75ec1f3b7096b0ee219de9`; original `100644:c6adb1933e8a48ab630a268a00846eddcbb3ca89`; pinned-current `100644:0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-14,1+15,1`, `-24,0+25,1`
- U | RepositoryTools.__init__: `-94,1+96,1`, `-106,0+108,7`
- U | RepositoryTools.search: `-876,1+885,5`, `-885,0+898,2`, `-886,2+901,12`, `-890,1+915,1`, `-933,1+958,12`, `-960,0+996,8`, `-976,0+1020,6`
- U | RepositoryTools: `-1561,0+1611,131`, `-1621,0+1900,20`
- U | RepositoryTools.search_paths: `-1563,0+1744,3`, `-1564,0+1748,41`, `-1570,1+1795,3`, `-1575,1+1802,0`, `-1577,0+1803,1`, `-1578,1+1805,1`, `-1581,0+1808,45`
- L | RepositoryTools.search_paths: `-1605,1+1877,8`

### D243 src/local_ai_hub/repo_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bde9d8e8a31f2237ce75ec1f3b7096b0ee219de9`; original `100644:c7def20cf06156f1d597163402d0ee96af3bad23`; pinned-current `100644:0624be3f187a3c90d7fd0c2d8e7f8ce4a5f14d7f`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | RepositoryTools.__init__: `-106,0+106,3`
- U | RepositoryTools._read_snapshot: `-295,1+298,1`, `-302,1+305,1`
- L | RepositoryTools: `-358,0+361,9`
- U | RepositoryTools.search: `-885,0+897,1`, `-933,0+946,1`, `-934,0+948,2`, `-935,0+951,1`, `-976,0+993,3`

### D244 src/local_ai_hub/reranker.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:050d06fcf50f6eb37169698f0c31a0efd73ecf95`; original `100644:07b89a8ff11b61808644f73a2dd0518e2abf0223`; pinned-current `100644:7f37071713dbf667dec6ebce43320ea5a0674531`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | Reranker.__init__: `-30,1+30,1`
- U | Reranker: `-151,17+151,54`, `-170,0+207,4`

### D245 src/local_ai_hub/reranker.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:050d06fcf50f6eb37169698f0c31a0efd73ecf95`; original `100644:73b3db187d5e4f63d08b5ca4801300aea84c223d`; pinned-current `100644:7f37071713dbf667dec6ebce43320ea5a0674531`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,1`, `-12,0+13,1`
- A | Reranker._execution_identity: `-65,1+67,7`
- A | Reranker._load_candidate: `-119,1+127,5`
- L | Reranker: `-149,0+161,18`, `-174,0+209,19`
- A | Reranker._predict: `-151,1+181,1`, `-153,0+183,2`, `-156,1+188,4`
- A | Reranker._rerank_uncached: `-194,2+248,6`, `-210,0+268,6`, `-214,1+278,8`

### D246 src/local_ai_hub/reranker.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:050d06fcf50f6eb37169698f0c31a0efd73ecf95`; original `100644:a9403dc710cdde915872348fdbba3281cbfa98a5`; pinned-current `100644:7f37071713dbf667dec6ebce43320ea5a0674531`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | Reranker.__init__: `-39,1+39,1`

### D247 src/local_ai_hub/resilience.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:75b439f7103bef5fb8caed63995274d2d23b87ad`; original `100644:44b147152ea529817357bfa7323f24ec61074d00`; pinned-current `100644:bcdd2b69babf71d4aacd408b3541f273f5020662`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-9,0+10,1`, `-86,0+88,4`
- A | RecoveryJournal.__init__: `-115,0+121,1`
- U | RecoveryJournal: `-125,0+132,47`
- U | RecoveryJournal._create_schema: `-126,0+180,2`, `-134,6+190,2`
- U | RecoveryJournal._init_db: `-142,0+194,2`, `-145,1+199,9`
- L | RecoveryJournal._init_db: `-153,0+215,1`
- A | RecoveryJournal.begin: `-190,1+253,2`

### D248 src/local_ai_hub/resilience.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:75b439f7103bef5fb8caed63995274d2d23b87ad`; original `100644:d7e135b10b87fdb204e139f9a86f607c13b7c859`; pinned-current `100644:bcdd2b69babf71d4aacd408b3541f273f5020662`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | RecoveryJournal._create_schema: `-125,1+125,1`, `-127,0+127,9`, `-134,5+143,0`, `-140,0+144,1`
- U | RecoveryJournal._init_db: `-143,1+148,8`

### D249 src/local_ai_hub/resilience.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:75b439f7103bef5fb8caed63995274d2d23b87ad`; original `100644:e79d30227a4c8a54b4d2b99fc2a726f06bb4cfd0`; pinned-current `100644:bcdd2b69babf71d4aacd408b3541f273f5020662`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | RecoveryJournal.wait_for: `-335,1+335,5`

### D250 src/local_ai_hub/response_budget.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:facbfa2be6b27c4510f462b9ed4ddbe932931b96`; original `100644:2de602a9015fcc2c5ddc9c6872180b263f332682`; pinned-current `100644:c6796084b33935cb7b9e11e3de7daa86923347d9`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-11,0+11,2`, `-29,1+31,1`, `-31,0+33,37`, `-171,1+444,52`, `-201,0+525,21`
- U | <module/text>: `-35,1+74,2`, `-37,0+77,15`
- A | _bounded_pointer_item: `-50,1+105,1`
- A | _pointer_envelope: `-77,0+132,21`, `-78,1+154,1`
- A | _fit_to_tokens: `-95,1+171,1`, `-105,1+181,5`, `-107,1+187,1`, `-111,0+191,8`, `-113,1+201,1`
- A | _with_budget_meta: `-129,0+217,1`, `-136,0+225,1`, `-138,0+228,1`, `-139,1+230,30`, `-141,2+261,46`
- U | _budget_rejection: `-145,1+309,3`, `-147,18+313,118`
- A | _bounded_result: `-167,1+433,8`
- L | budget_response: `-211,0+556,1`, `-215,0+561,20`, `-221,1+587,1`, `-223,0+589,1`, `-228,1+595,1`, `-230,0+597,1`, `-231,1+599,3`, `-233,1+603,23`, `-252,1+644,1`, `-262,1+655,1`, `-264,0+657,1`, `-267,2+661,4`, `-282,1+679,1`, `-284,0+681,1`, `-285,1+683,3`
- U | budget_response: `-256,0+648,1`, `-276,1+672,1`, `-278,0+674,1`

### D251 src/local_ai_hub/response_budget.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:facbfa2be6b27c4510f462b9ed4ddbe932931b96`; original `100644:d6c4bcefbab4e304735b8e7f44a5503c8f0f7517`; pinned-current `100644:c6796084b33935cb7b9e11e3de7daa86923347d9`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-35,1+35,2`, `-44,0+45,8`, `-145,1+158,57`
- U | _with_budget_meta: `-141,1+150,5`
- U | _budget_rejection: `-147,17+216,71`
- U | _bounded_result: `-167,1+290,8`, `-171,1+301,6`
- U | budget_response: `-231,1+366,7`, `-246,3+387,2`, `-250,2+390,0`, `-253,0+391,23`, `-268,1+429,7`, `-285,1+452,7`

### D252 src/local_ai_hub/response_protocol.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d6efa2dc9388011dc650095daf4b8df8ce16a5bd`; original `100644:c887343e5bb430632d0070be005725252fa2ac00`; pinned-current `100644:c887343e5bb430632d0070be005725252fa2ac00`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-6,1+6,0`

### D253 src/local_ai_hub/retrieval.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9333f70b1a9a7aa1553065c0207b53cbea89600c`; original `100644:22572473020750056299975ea87fb6b1b34c25bc`; pinned-current `100644:9ffe7564c1bbea7ff17eda272a31240c8c2a13e7`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`
- L | fuse_ranked_paths: `-12,0+13,1`, `-18,1+20,1`, `-22,1+24,0`
- U | fuse_ranked_paths: `-27,0+28,11`, `-30,1+42,1`

### D254 src/local_ai_hub/retrieval.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9333f70b1a9a7aa1553065c0207b53cbea89600c`; original `100644:e4065835e18df1927106d82e5f4f2494e424a210`; pinned-current `100644:9ffe7564c1bbea7ff17eda272a31240c8c2a13e7`.

Exact checkpoint/owner witnesses: `S010 / ab60c0a1d39753965dc87842e04638f10bae6e83 / true / 04ff61ebc4fb00005b786dc6f123cc12ce3871eb`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | fuse_ranked_paths: `-22,1+22,0`

### D255 src/local_ai_hub/retrieval.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e4065835e18df1927106d82e5f4f2494e424a210`; original `100644:a52882d0a311571d74f66106658da28d0f7d1bca`; pinned-current `100644:9ffe7564c1bbea7ff17eda272a31240c8c2a13e7`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | fuse_ranked_paths: `-28,1+28,3`

### D256 src/local_ai_hub/router.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:678acc08c8ae8b9e0250b8886b282a75a5846b8d`; original `100644:fbbb9292c2d1f1af67d96b4c24dcefd5a934a63b`; pinned-current `100644:fbbb9292c2d1f1af67d96b4c24dcefd5a934a63b`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | ModelRouter.apply_model_override: `-132,1+132,1`, `-151,1+151,7`

### D257 src/local_ai_hub/scheduler.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:21e5d852bc1587fde73a86d5cf501b161008b771`; original `100644:56ba2d2862d560d777479c47dd3aa0d24aefd7ee`; pinned-current `100644:56ba2d2862d560d777479c47dd3aa0d24aefd7ee`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,2`, `-5,1+7,1`, `-12,0+14,45`, `-76,0+128,11`
- B | Job: `-35,0+82,5`
- B | AffinityScheduler.__init__: `-123,0+186,1`, `-127,0+191,1`, `-161,0+226,16`
- B | AffinityScheduler: `-172,0+253,109`, `-192,1+382,125`, `-668,1+1147,18`
- B | AffinityScheduler._admission: `-195,0+509,64`, `-201,2+579,11`, `-205,0+592,1`, `-206,0+594,15`, `-207,1+610,1`, `-212,0+615,1`, `-213,0+617,4`
- B | AffinityScheduler.submit: `-240,0+648,1`, `-248,0+657,1`, `-265,1+675,1`, `-276,1+686,5`, `-308,13+722,40`, `-326,1+767,15`, `-331,0+786,1`, `-335,0+791,3`
- B | AffinityScheduler._dispatch_loop: `-538,1+997,4`
- B | AffinityScheduler._choose_job_for_active_model: `-660,0+1122,7`, `-666,1+1134,12`
- B | AffinityScheduler._choose_job_for_active_model.score: `-661,2+1130,1`, `-664,1+1132,1`
- B | AffinityScheduler._perform_switch: `-670,0+1166,2`, `-671,0+1169,1`, `-672,8+1171,55`, `-682,0+1228,2`, `-684,0+1232,24`, `-686,1+1258,33`, `-710,1+1314,1`
- B | AffinityScheduler._run_job: `-729,9+1333,12`
- B | AffinityScheduler.close: `-849,0+1456,5`

### D258 src/local_ai_hub/scheduler.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b57756f3eb10a5100d67b45f0a9af94fafc55d6`; original `100644:3e4b5ae9051c19925da922e324632e6c3c4481b7`; pinned-current `100644:56ba2d2862d560d777479c47dd3aa0d24aefd7ee`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | Job: `-84,0+84,3`
- A | AffinityScheduler.__init__: `-183,0+186,1`, `-221,0+225,16`
- A | AffinityScheduler._observe_model_vram_bytes: `-378,0+398,5`
- L | AffinityScheduler: `-412,0+437,69`
- A | AffinityScheduler._admission: `-430,0+524,5`, `-445,0+544,2`, `-465,1+566,1`, `-468,3+569,4`, `-483,0+585,1`, `-496,0+599,9`
- A | AffinityScheduler.submit: `-655,1+767,15`, `-660,0+786,1`, `-664,0+791,3`
- A | AffinityScheduler._choose_job_for_active_model.effective_priority: `-992,1+1122,1`
- A | AffinityScheduler._choose_job_for_active_model: `-997,1+1127,4`, `-1001,1+1134,12`
- A | AffinityScheduler._choose_job_for_active_model.score: `-999,1+1132,1`
- A | AffinityScheduler._perform_switch: `-1022,0+1166,1`, `-1024,0+1169,1`, `-1026,0+1172,2`, `-1030,0+1178,5`, `-1031,0+1184,13`, `-1033,1+1199,5`, `-1039,1+1209,8`, `-1055,0+1232,24`, `-1074,0+1275,13`, `-1100,1+1314,1`
- A | AffinityScheduler._run_job: `-1119,9+1333,12`
- A | AffinityScheduler.close: `-1239,0+1456,5`

### D259 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:15a739af88c6570bf0b3656f736c8e2de8b80155`; original `100644:ddbb20658892e1c04d32808b5e0d6c4da5c1fb02`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`
- U | <module/text>: `-8,0+9,1`
- U | LocalAIServices.adaptive_context_pack: `-3606,1+3608,4`
- U | LocalAIServices._hybrid_context: `-3780,1+3785,5`, `-3827,2+3836,10`
- U | LocalAIServices._hybrid_context_uncached: `-3843,1+3860,5`, `-3855,0+3876,1`, `-3858,2+3880,1`, `-3861,0+3882,17`, `-3866,6+3904,8`, `-3883,1+3923,2`, `-3890,1+3931,79`, `-3958,1+4077,1`, `-3964,0+4083,4`
- U | LocalAIServices.delegate_repo: `-3982,1+4105,7`

### D260 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6529532559b3dab2a11fbeae913af45d59e9b2d7`; original `100644:191b7b405b53012aca198198b2fe33820824b1f8`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-43,6+43,0`, `-50,1+44,0`, `-54,0+47,2`, `-55,1+50,0`, `-57,2+51,0`
- A | LocalAIServices.speculative_draft: `-1522,1+1514,20`, `-1524,1+1535,1`, `-1535,1+1546,6`, `-1567,0+1583,1`
- A | LocalAIServices.task_scaffold: `-1642,1+1659,12`, `-1645,0+1673,10`, `-1652,0+1690,1`
- U | LocalAIServices.vision: `-1654,1+1693,7`, `-1665,0+1710,27`, `-1702,380+1774,16`, `-2089,18+1797,10`, `-2108,22+1808,5`, `-2147,0+1830,2`, `-2152,0+1837,2`, `-2220,0+1907,2`, `-2221,0+1910,2`, `-2297,0+2009,1`, `-2349,0+2061,2`
- L | LocalAIServices.vision: `-2288,0+1979,10`, `-2289,1+1990,11`, `-2294,0+2005,1`, `-2301,10+2014,9`
- L | LocalAIServices.transcribe: `-2361,2+2075,21`, `-2364,1+2097,13`, `-2366,3+2111,37`, `-2384,0+2194,2`, `-2385,2+2197,0`
- U | LocalAIServices.transcribe: `-2371,7+2150,39`, `-2379,2+2190,1`, `-2388,11+2198,89`
- A | LocalAIServices.complete_code.compute: `-4952,3+4840,14`

### D261 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6529532559b3dab2a11fbeae913af45d59e9b2d7`; original `100644:7c0a067a9eb1add157b16e4e964ad37f23219e85`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S088 / 7951ebff15e335ac4a0f9634dd6596152cb10704 / true / 0aebfbd954c8ebdd11a25860053db4f8a5778d59`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-52,0+52,1`
- U | LocalAIServices: `-1654,1+1655,200`
- L | LocalAIServices.vision: `-1665,0+1865,13`, `-2288,0+2455,10`, `-2289,1+2466,11`, `-2294,0+2481,1`, `-2349,0+2538,2`
- U | LocalAIServices.vision: `-2083,0+2296,2`, `-2103,1+2318,3`, `-2106,1+2323,8`, `-2108,4+2332,5`, `-2113,4+2338,4`, `-2121,1+2346,0`, `-2127,1+2351,1`, `-2147,0+2371,2`, `-2152,68+2378,7`, `-2221,0+2386,2`, `-2297,0+2485,1`
- L | LocalAIServices.transcribe: `-2361,2+2552,21`, `-2364,1+2574,13`, `-2366,3+2588,37`, `-2384,0+2671,2`, `-2385,2+2674,0`
- U | LocalAIServices.transcribe: `-2371,7+2627,39`, `-2379,2+2667,1`, `-2388,11+2675,89`

### D262 src/local_ai_hub/services.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6529532559b3dab2a11fbeae913af45d59e9b2d7`; original `100644:7e00d647ca563cf302896ac097c7195881bcbb6f`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-389,0+389,11`
- A | LocalAIServices.__init__: `-460,1+471,1`, `-472,1+483,1`, `-486,1+497,1`, `-502,1+513,1`
- A | LocalAIServices.set_agent_state: `-567,0+578,2`
- A | LocalAIServices.pubsub_publish: `-3258,1+3271,1`
- A | LocalAIServices.pubsub_poll: `-3260,1+3273,7`, `-3262,1+3281,3`
- A | LocalAIServices._context_preload_source: `-3436,1+3457,1`
- A | LocalAIServices.optimize_databases: `-5571,1+5592,1`
- A | LocalAIServices.purge_stale_cache: `-5597,1+5618,1`
- A | LocalAIServices.run_doctor: `-5678,1+5699,1`

### D263 src/local_ai_hub/services.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6eca84739fc882c6cadcd4ba67e0278d81ac46db`; original `100644:cd2ae0256ba0f067e4f5c794667a72b2f7d8b5a5`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | LocalAIServices.daemon_status: `-3094,1+3094,3`, `-3097,1+3099,14`
- A | LocalAIServices.stop_daemon: `-3099,1+3114,1`, `-3102,1+3117,1`
- L | LocalAIServices: `-5210,0+5225,37`
- L | LocalAIServices.command: `-5222,0+5274,7`, `-5338,1+5397,11`, `-5340,1+5409,4`

### D264 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7cc20ac9cb168b9d19a6d19aea84ea810970d3c5`; original `100644:c1f2b26caa86034e33fc002dd849b8ec452b0e72`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | generation_cache_key: `-353,0+353,2`, `-354,1+356,1`, `-368,1+370,5`
- U | LocalAIServices._generate: `-835,0+841,6`, `-836,0+848,9`
- L | LocalAIServices._generate: `-888,0+909,3`, `-889,1+913,1`, `-892,1+916,8`
- U | LocalAIServices._generate.compute_inner: `-979,1+1010,4`
- U | LocalAIServices._start_conversation: `-1296,0+1330,1`, `-1302,1+1337,1`, `-1308,1+1343,1`
- U | LocalAIServices.continue_conversation: `-1343,0+1378,1`
- U | LocalAIServices: `-1355,0+1391,24`
- U | LocalAIServices.delegate: `-1363,0+1423,24`, `-1398,1+1493,8`, `-1400,1+1502,1`, `-1402,0+1504,1`
- L | LocalAIServices.delegate: `-1374,0+1458,11`, `-1408,0+1511,6`, `-1411,1+1520,1`
- A | LocalAIServices.batch_delegate: `-5622,0+5731,1`, `-5625,0+5735,2`

### D265 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:82dbce424fe7f90554d67a2eac0a8976dcc0443f`; original `100644:205699d5bb20b3d869ad37e844d54326178214b8`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LocalAIServices: `-818,0+818,10`, `-1219,0+1284,13`, `-2413,1+2554,0`
- U | LocalAIServices._generate: `-835,0+845,2`
- U | LocalAIServices._generate.compute_inner: `-935,0+947,15`, `-952,2+979,35`, `-962,0+1022,5`
- U | LocalAIServices._start_conversation: `-1230,0+1308,1`, `-1231,0+1310,2`, `-1233,1+1314,1`, `-1246,1+1324,2`
- L | LocalAIServices._start_conversation: `-1240,3+1321,0`, `-1254,0+1333,3`
- U | LocalAIServices.continue_conversation: `-1263,1+1345,7`, `-1284,1+1374,2`, `-1292,0+1383,3`
- L | LocalAIServices.continue_conversation: `-1270,0+1358,2`
- U | LocalAIServices.delegate: `-1301,1+1395,7`, `-1348,1+1448,1`
- U | LocalAIServices.speculative_draft: `-1508,1+1608,1`
- U | LocalAIServices.speculative_lint: `-1586,1+1686,1`
- U | LocalAIServices.transcribe: `-2375,1+2475,7`, `-2386,1+2492,3`, `-2388,11+2496,44`
- U | LocalAIServices.command: `-5321,1+5461,1`

### D266 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 20:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:82dbce424fe7f90554d67a2eac0a8976dcc0443f`; original `100644:5a1feb49243986911e92d31d4c153b9b710ec274`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S071 / 9b1b40906612634df8a0a3bedbb217a337c67cb4 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LocalAIServices._start_conversation: `-1233,1+1233,1`
- L | LocalAIServices._start_conversation: `-1240,3+1240,0`

### D267 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 18:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:0560286f3e30469f14445e55f60c6bfc224d851d`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S023 / b0ade36afca1bceeb6756fe76eeb0ca90758e64a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LocalAIServices._generate: `-836,0+836,7`
- U | LocalAIServices.preprocess: `-5346,0+5353,10`, `-5348,2+5365,0`

### D268 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:337c2969de090a87496e58716cb3919a5e27ff32`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S086 / fbe44e0cda222cdbee06227b57f3b5d6f2bfd80f / true / 16f20b4dcb65cd03941390a575df7ab61642dddd`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-43,6+43,0`, `-50,1+44,0`, `-52,0+45,1`, `-54,6+48,5`
- U | LocalAIServices.vision: `-1656,10+1649,3`, `-1668,33+1654,3`, `-1702,8+1658,15`, `-1711,396+1674,9`, `-2108,38+1684,6`, `-2152,68+1696,3`, `-2221,39+1700,3`, `-2288,0+1723,16`, `-2289,1+1740,9`, `-2295,0+1754,1`, `-2297,1+1757,2`
- L | LocalAIServices.vision: `-2261,8+1704,0`, `-2301,10+1762,9`
- U | LocalAIServices.transcribe: `-2363,0+1823,2`, `-2364,1+1826,1`, `-2370,3+1832,25`, `-2376,2+1860,11`, `-2379,2+1872,4`, `-2383,1+1878,0`, `-2385,14+1879,28`

### D269 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:4b6c78378450524d53a40d0f1a1a8c643d77cb44`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S083 / 1240bce13b18eb14d1b0be359834b0989dc1c194 / true / 1fa8c6f1655e58c79bc002f11778ef07a919488f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,1`, `-9,0+10,1`, `-43,6+45,0`, `-50,1+46,0`, `-52,0+47,1`
- L | <module/text>: `-55,1+51,0`, `-57,2+52,0`, `-60,0+53,4`
- A | generation_cache_key: `-353,0+350,2`, `-354,1+353,1`, `-368,1+367,5`
- U | LocalAIServices._generate: `-835,0+838,7`, `-836,0+846,10`
- L | LocalAIServices._generate: `-885,0+905,3`, `-886,1+909,1`, `-889,1+912,8`, `-1087,0+1200,2`
- U | LocalAIServices._generate.compute_inner: `-927,0+957,9`, `-952,7+1002,9`, `-961,1+1022,51`
- L | LocalAIServices._generate.compute_inner: `-935,0+974,11`, `-960,0+1012,9`, `-1028,0+1139,2`
- L | LocalAIServices: `-1219,0+1334,9`, `-1289,1+1437,27`
- A | LocalAIServices._start_conversation: `-1230,0+1354,2`, `-1231,0+1357,2`, `-1233,2+1361,4`, `-1238,1+1368,2`, `-1242,1+1373,2`, `-1250,1+1382,8`
- A | LocalAIServices.continue_conversation: `-1255,1+1394,3`, `-1262,0+1403,2`, `-1277,0+1420,2`, `-1284,0+1429,3`
- A | LocalAIServices.delegate: `-1297,0+1471,24`, `-1298,0+1496,4`, `-1308,0+1510,11`, `-1323,0+1536,1`, `-1332,1+1546,7`, `-1334,1+1554,2`, `-1336,0+1557,1`, `-1342,0+1564,6`, `-1345,1+1573,1`
- U | LocalAIServices.vision: `-1656,10+1884,3`, `-1668,33+1889,3`, `-1702,8+1893,15`, `-1711,396+1909,9`, `-2108,38+1919,6`, `-2152,68+1931,3`, `-2221,39+1935,3`, `-2288,0+1958,16`, `-2289,1+1975,9`, `-2295,0+1989,1`, `-2297,1+1992,2`
- L | LocalAIServices.vision: `-2261,8+1939,0`, `-2301,10+1997,9`
- L | LocalAIServices.transcribe: `-2361,2+2056,21`, `-2364,1+2078,13`, `-2366,3+2092,37`, `-2384,0+2175,2`, `-2385,2+2178,0`
- U | LocalAIServices.transcribe: `-2371,7+2131,39`, `-2379,2+2171,1`, `-2388,11+2179,91`
- A | LocalAIServices.repo_search: `-2559,1+2430,10`, `-2571,0+2451,76`, `-2594,0+2550,82`, `-2637,1+2781,14`
- A | LocalAIServices.repo_search.compute: `-2595,0+2633,15`, `-2596,12+2649,39`, `-2609,1+2689,66`, `-2612,1+2757,0`
- U | LocalAIServices: `-3033,0+3190,7`
- A | LocalAIServices.test_matrix: `-3034,1+3198,1`
- A | LocalAIServices.affected_tests: `-3103,2+3267,1`, `-3106,0+3269,2`, `-3107,1+3272,0`, `-3124,0+3288,64`, `-3135,1+3363,2`, `-3199,0+3428,11`
- A | LocalAIServices.worktree_release: `-3234,1+3474,1`, `-3236,1+3476,1`
- A | LocalAIServices.stop_daemon: `-3265,1+3505,1`, `-3268,1+3508,1`
- U | LocalAIServices.adaptive_context_pack: `-3811,0+4051,39`, `-3831,0+4112,4`, `-3850,0+4137,5`
- L | LocalAIServices.adaptive_context_pack: `-3819,0+4098,2`, `-3837,0+4122,2`
- U | LocalAIServices._hybrid_context: `-4102,0+4394,5`, `-4116,0+4413,58`, `-4157,0+4512,3`
- L | LocalAIServices._hybrid_context: `-4175,0+4533,5`
- U | LocalAIServices._hybrid_context_uncached: `-4319,0+4682,5`, `-4412,2+4780,63`, `-4418,2+4861,1`, `-4422,1+4864,1`, `-4427,0+4869,5`, `-4535,0+4997,3`
- L | LocalAIServices._hybrid_context_uncached: `-4417,0+4846,14`, `-4452,1+4899,16`
- L | LocalAIServices.command: `-5436,0+5901,4`, `-5440,0+5909,1`, `-5446,0+5916,1`, `-5456,0+5927,13`
- U | LocalAIServices.command: `-5510,1+5994,4`
- A | LocalAIServices.batch_delegate: `-5741,0+6228,1`, `-5744,0+6232,2`

### D270 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:731ab97c07561315e45eaeb1b177dd4c512a04e7`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LocalAIServices.repo_search: `-2559,1+2559,10`, `-2571,0+2580,75`
- U | LocalAIServices.repo_search.compute: `-2595,0+2679,16`, `-2596,12+2696,58`
- L | LocalAIServices.repo_search.compute: `-2609,1+2755,34`, `-2612,1+2791,0`
- L | LocalAIServices.repo_search: `-2637,1+2815,14`

### D271 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 12:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:88a14b8c32ca2ace0279657775298a3d897868f6`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S081 / 388086357ab954fbf208def00ba1ce5a60170598 / true / fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-9,0+9,1`
- L | LocalAIServices.affected_tests: `-3124,0+3125,64`, `-3135,1+3200,2`, `-3199,0+3265,11`
- L | LocalAIServices.command: `-5456,0+5533,13`

### D272 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:9d4d5f20bff978b8ab67dd03e85fd5c4c653fb5e`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,1`, `-9,0+10,1`, `-43,6+45,0`, `-50,1+46,0`, `-52,0+47,1`, `-57,2+52,0`, `-60,0+53,4`
- L | <module/text>: `-55,1+51,0`
- A | generation_cache_key: `-353,0+350,2`, `-354,1+353,1`, `-368,1+367,5`
- U | LocalAIServices._generate: `-835,0+838,7`, `-836,0+846,10`
- L | LocalAIServices._generate: `-885,0+905,3`, `-886,1+909,1`, `-889,1+912,8`, `-1087,0+1200,2`
- U | LocalAIServices._generate.compute_inner: `-927,0+957,9`, `-952,7+1002,9`, `-961,1+1022,51`
- L | LocalAIServices._generate.compute_inner: `-935,0+974,11`, `-960,0+1012,9`, `-1028,0+1139,2`
- L | LocalAIServices: `-1219,0+1334,9`, `-1289,1+1437,27`
- A | LocalAIServices._start_conversation: `-1230,0+1354,2`, `-1231,0+1357,2`, `-1233,2+1361,4`, `-1238,1+1368,2`, `-1242,1+1373,2`, `-1250,1+1382,8`
- A | LocalAIServices.continue_conversation: `-1255,1+1394,3`, `-1262,0+1403,2`, `-1277,0+1420,2`, `-1284,0+1429,3`
- A | LocalAIServices.delegate: `-1297,0+1471,24`, `-1298,0+1496,4`, `-1308,0+1510,11`, `-1323,0+1536,1`, `-1332,1+1546,7`, `-1334,1+1554,2`, `-1336,0+1557,1`, `-1342,0+1564,6`, `-1345,1+1573,1`
- U | LocalAIServices.vision: `-1656,10+1884,3`, `-1668,33+1889,3`, `-1702,8+1893,15`, `-1711,396+1909,9`, `-2108,38+1919,6`, `-2152,68+1931,3`, `-2221,39+1935,3`, `-2288,0+1958,14`, `-2289,1+1973,9`, `-2295,0+1987,1`, `-2297,1+1990,2`
- L | LocalAIServices.vision: `-2261,8+1939,0`, `-2301,10+1995,9`
- L | LocalAIServices.transcribe: `-2361,2+2054,21`, `-2364,1+2076,13`, `-2366,3+2090,37`, `-2384,0+2173,2`, `-2385,2+2176,0`
- U | LocalAIServices.transcribe: `-2371,7+2129,39`, `-2379,2+2169,1`, `-2388,11+2177,89`
- A | LocalAIServices.repo_search: `-2559,1+2426,10`, `-2571,0+2447,76`, `-2594,0+2546,82`, `-2637,1+2777,14`
- A | LocalAIServices.repo_search.compute: `-2595,0+2629,15`, `-2596,12+2645,39`, `-2609,1+2685,66`, `-2612,1+2753,0`
- U | LocalAIServices: `-3033,0+3186,7`
- A | LocalAIServices.test_matrix: `-3034,1+3194,1`
- A | LocalAIServices.affected_tests: `-3103,2+3263,1`, `-3106,0+3265,2`, `-3107,1+3268,0`, `-3124,0+3284,64`, `-3135,1+3359,2`, `-3199,0+3424,11`
- A | LocalAIServices.stop_daemon: `-3265,1+3501,1`, `-3268,1+3504,1`
- U | LocalAIServices.adaptive_context_pack: `-3811,0+4047,39`, `-3831,0+4108,4`, `-3850,0+4133,5`
- L | LocalAIServices.adaptive_context_pack: `-3819,0+4094,2`, `-3837,0+4118,2`
- U | LocalAIServices._hybrid_context: `-4102,0+4390,5`, `-4116,0+4409,58`, `-4157,0+4508,3`
- L | LocalAIServices._hybrid_context: `-4175,0+4529,5`
- U | LocalAIServices._hybrid_context_uncached: `-4319,0+4678,5`, `-4412,2+4776,63`, `-4418,2+4857,1`, `-4422,1+4860,1`, `-4427,0+4865,5`, `-4535,0+4993,3`
- L | LocalAIServices._hybrid_context_uncached: `-4417,0+4842,14`, `-4452,1+4895,16`
- L | LocalAIServices.command: `-5436,0+5897,4`, `-5440,0+5905,1`, `-5446,0+5912,1`, `-5456,0+5923,13`
- U | LocalAIServices.command: `-5510,1+5990,4`
- A | LocalAIServices.batch_delegate: `-5741,0+6224,1`, `-5744,0+6228,2`

### D273 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:abc41882237bef87752672c25c57454daa0e7b04`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-8,0+8,1`
- U | LocalAIServices.repo_search: `-2559,1+2560,9`, `-2594,0+2603,211`, `-2637,1+2971,17`
- U | LocalAIServices.repo_search.compute: `-2595,0+2815,8`, `-2604,5+2832,109`, `-2610,0+2942,2`

### D274 src/local_ai_hub/services.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 10:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:d1df7ee8b41e321ecb81628423f967d30e085562`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S031 / c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3 / true / f99619a4658692b2d15d40a07f2176891c72cffa`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | LocalAIServices: `-3033,0+3033,8`
- A | LocalAIServices.test_matrix: `-3034,1+3042,1`
- L | LocalAIServices.affected_tests: `-3103,2+3111,1`, `-3106,0+3113,2`, `-3107,1+3116,0`
- L | LocalAIServices.command: `-5436,0+5444,4`, `-5440,0+5452,1`, `-5446,0+5459,1`

### D275 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 14:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:ddd35131ce881af262224714dcc0ae85c805ad30`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S078 / 3524b558cc560bbf58425f56f98f74dd6cda8675 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | LocalAIServices._hybrid_context_uncached: `-4494,0+4494,27`

### D276 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 15:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9e37b5b99991a668987d3811fe3f6decad37d0c2`; original `100644:e0ce93b195ccb259d15f47bc733066a7245e426b`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S025 / 3b35d5d46e53b8b23a84a27c4e0aaa779290ec1d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-8,0+9,1`, `-9,0+11,1`, `-55,1+52,0`
- U | <module/text>: `-43,6+46,0`, `-50,1+47,0`, `-52,0+48,1`, `-57,2+53,0`, `-60,0+54,4`
- A | generation_cache_key: `-353,0+351,2`, `-354,1+354,1`, `-368,1+368,5`
- U | LocalAIServices._generate: `-835,0+839,7`, `-836,0+847,10`
- L | LocalAIServices._generate: `-885,0+906,3`, `-886,1+910,1`, `-889,1+913,8`, `-1087,0+1201,2`
- U | LocalAIServices._generate.compute_inner: `-927,0+958,9`, `-952,7+1003,9`, `-961,1+1023,51`
- L | LocalAIServices._generate.compute_inner: `-935,0+975,11`, `-960,0+1013,9`, `-1028,0+1140,2`
- L | LocalAIServices: `-1219,0+1335,9`, `-1289,1+1438,27`
- A | LocalAIServices._start_conversation: `-1230,0+1355,2`, `-1231,0+1358,2`, `-1233,2+1362,4`, `-1238,1+1369,2`, `-1242,1+1374,2`, `-1250,1+1383,8`
- A | LocalAIServices.continue_conversation: `-1255,1+1395,3`, `-1262,0+1404,2`, `-1277,0+1421,2`, `-1284,0+1430,3`
- A | LocalAIServices.delegate: `-1297,0+1472,24`, `-1298,0+1497,4`, `-1308,0+1511,11`, `-1323,0+1537,1`, `-1332,1+1547,7`, `-1334,1+1555,2`, `-1336,0+1558,1`, `-1342,0+1565,6`, `-1345,1+1574,1`
- U | LocalAIServices.vision: `-1656,10+1885,3`, `-1668,33+1890,3`, `-1702,8+1894,15`, `-1711,396+1910,9`, `-2108,38+1920,6`, `-2152,68+1932,3`, `-2221,39+1936,3`, `-2288,0+1959,14`, `-2289,1+1974,9`, `-2295,0+1988,1`, `-2297,1+1991,2`
- L | LocalAIServices.vision: `-2261,8+1940,0`, `-2301,10+1996,9`
- L | LocalAIServices.transcribe: `-2361,2+2055,21`, `-2364,1+2077,13`, `-2366,3+2091,37`, `-2384,0+2174,2`, `-2385,2+2177,0`
- U | LocalAIServices.transcribe: `-2371,7+2130,39`, `-2379,2+2170,1`, `-2388,11+2178,89`
- A | LocalAIServices.repo_search: `-2559,1+2427,10`, `-2571,0+2448,76`, `-2594,0+2547,82`, `-2637,1+2778,14`
- A | LocalAIServices.repo_search.compute: `-2595,0+2630,15`, `-2596,12+2646,39`, `-2609,1+2686,66`, `-2612,1+2754,0`
- U | LocalAIServices: `-3033,0+3187,7`
- A | LocalAIServices.test_matrix: `-3034,1+3195,1`
- A | LocalAIServices.affected_tests: `-3103,2+3264,1`, `-3106,0+3266,2`, `-3107,1+3269,0`, `-3124,0+3285,64`, `-3135,1+3360,2`, `-3199,0+3425,11`
- A | LocalAIServices.stop_daemon: `-3265,1+3502,1`, `-3268,1+3505,1`
- A | LocalAIServices.adaptive_context_pack: `-3811,0+4048,43`, `-3819,0+4099,2`, `-3831,0+4113,4`, `-3837,0+4123,2`, `-3850,0+4138,7`
- A | LocalAIServices._hybrid_context: `-4102,0+4397,7`, `-4116,0+4418,60`, `-4157,0+4519,4`, `-4175,0+4541,5`
- U | LocalAIServices._hybrid_context_uncached: `-4319,0+4690,7`, `-4412,0+4790,172`, `-4413,1+4963,23`, `-4417,0+4989,4`, `-4418,2+4994,1`, `-4535,0+5130,3`
- L | LocalAIServices._hybrid_context_uncached: `-4421,2+4996,2`, `-4427,0+5002,5`, `-4452,1+5032,16`
- L | LocalAIServices.command: `-5436,0+6034,4`, `-5440,0+6042,1`, `-5446,0+6049,1`, `-5456,0+6060,13`
- U | LocalAIServices.command: `-5510,1+6127,4`
- A | LocalAIServices.batch_delegate: `-5741,0+6361,1`, `-5744,0+6365,2`

### D277 src/local_ai_hub/services.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ba533fd75b78729747a62014d805d4f9845180d0`; original `100644:a77033804690456ab05aca6fd50953f6c7b0fdaa`; pinned-current `100644:2c043615e7f42c64c6aeeeb7e73fef2410229f44`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | LocalAIServices._external_candidate_paths: `-4026,0+4026,15`
- A | LocalAIServices._external_candidate_paths.visit: `-4034,12+4049,1`, `-4047,0+4051,6`
- A | LocalAIServices._external_context_candidates: `-4065,0+4075,2`, `-4070,0+4082,3`
- L | LocalAIServices._hybrid_context_uncached: `-4210,3+4225,2`, `-4292,1+4306,3`, `-4454,0+4463,5`, `-4464,0+4479,1`, `-4467,0+4483,1`, `-4484,0+4501,1`, `-4486,1+4504,1`, `-4491,0+4509,1`, `-4498,0+4517,1`, `-4499,0+4519,1`, `-4514,0+4535,3`, `-4515,0+4539,1`, `-4527,0+4552,49`, `-4541,0+4615,3`
- U | LocalAIServices._hybrid_context_uncached: `-4337,2+4353,0`, `-4340,17+4354,4`, `-4420,0+4421,8`, `-4459,0+4473,1`

### D278 src/local_ai_hub/sqlite_support.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:361e52fd254373259175d92bf05cd30c518f8d7e`; original `100644:90d67f94cafba48fdbdbcfe09620995e0114e3d5`; pinned-current `100644:bd76dcc16a80f987b550840722f4d20de377c390`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-78,0+78,140`

### D279 src/local_ai_hub/sqlite_support.py

Disposition: `integrated-current`. Occurrences: 24:T/M, 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:361e52fd254373259175d92bf05cd30c518f8d7e`; original `100644:bd76dcc16a80f987b550840722f4d20de377c390`; pinned-current `100644:bd76dcc16a80f987b550840722f4d20de377c390`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,2`, `-4,0+6,1`, `-6,0+9,2`, `-78,0+83,390`

### D280 src/local_ai_hub/supervisor.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:840e2166c4dbf8738c239fbbf6163f284bf005ce`; original `100644:6a4c3c8e8b20957007fb54e2887b7a6e670bbd87`; pinned-current `100644:7e0fb14f71236ddf06910dd40c3f69220a85dde7`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,1+5,0`

### D281 src/local_ai_hub/supervisor.py

Disposition: `integrated-current`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:840e2166c4dbf8738c239fbbf6163f284bf005ce`; original `100644:7e0fb14f71236ddf06910dd40c3f69220a85dde7`; pinned-current `100644:7e0fb14f71236ddf06910dd40c3f69220a85dde7`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-7,1+7,0`, `-11,0+10,1`, `-20,1+20,11`
- B | atomic_json: `-23,1+33,1`, `-30,1+40,1`, `-34,0+44,1`, `-35,1+46,1`
- B | Supervisor.__init__: `-46,0+57,1`, `-47,0+59,1`, `-48,0+61,2`, `-52,0+67,3`, `-57,1+75,2`
- B | Supervisor.log: `-61,8+80,4`
- B | Supervisor._append_bounded_log: `-72,2+87,5`
- B | Supervisor: `-75,17+93,26`, `-115,1+123,3`, `-117,1+127,17`, `-121,0+147,121`, `-140,0+292,26`, `-200,0+373,6`, `-209,2+390,25`
- B | Supervisor._drain_hub_stderr: `-93,20+120,1`
- B | Supervisor.hub_online: `-122,0+269,2`, `-130,1+279,1`, `-132,1+281,4`
- B | Supervisor.write_status: `-142,15+320,19`, `-158,8+340,1`, `-170,0+345,3`
- B | Supervisor.spawn_hub: `-189,5+367,0`, `-195,1+368,1`
- B | Supervisor._persist_hub_owner: `-201,7+380,9`
- B | Supervisor.terminate_child: `-213,26+417,9`, `-242,6+429,5`, `-249,5+435,4`
- B | Supervisor.run: `-263,0+448,3`, `-269,3+457,3`, `-293,1+481,4`, `-298,1+489,1`, `-313,1+504,5`, `-323,1+518,1`, `-338,1+533,2`, `-343,1+539,1`, `-345,1+541,5`, `-352,5+552,2`

### D282 src/local_ai_hub/swarm.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:347c1a9aec8af773cca7b483e44a92d8187495ff`; original `100644:6e890ba10cc86cd066f5c4c6d84091c956183738`; pinned-current `100644:6e890ba10cc86cd066f5c4c6d84091c956183738`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-5,0+5,1`, `-10,0+11,1`, `-15,0+17,1`, `-17,1+20,10`, `-27,0+39,4`
- B | SwarmCoordinator.__init__: `-41,0+57,1`, `-46,0+63,14`, `-47,0+78,1`
- B | SwarmCoordinator._init_db: `-53,1+85,19`, `-55,13+105,18`
- B | SwarmCoordinator: `-69,1+124,46`, `-72,0+197,51`, `-182,6+381,104`, `-314,7+697,87`
- B | SwarmCoordinator._recover_swarm_state: `-71,0+171,25`
- B | SwarmCoordinator.dispatch: `-80,1+256,1`, `-83,26+259,13`, `-112,2+275,3`, `-116,10+280,2`, `-128,0+284,21`, `-129,0+306,10`, `-132,1+319,1`, `-135,0+322,1`
- B | SwarmCoordinator.get_status: `-141,1+329,2`, `-146,1+335,0`, `-149,1+337,0`, `-157,5+344,7`
- B | SwarmCoordinator._release_all_leases: `-164,6+353,8`
- B | SwarmCoordinator.step: `-177,0+368,3`, `-178,3+372,8`
- B | SwarmCoordinator._step_transaction: `-189,1+486,159`, `-192,1+647,4`, `-194,0+652,2`, `-195,83+655,3`, `-283,0+663,1`, `-285,2+666,4`
- B | SwarmCoordinator.cancel: `-322,18+785,14`, `-341,1+800,42`

### D283 src/local_ai_hub/swarm.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:347c1a9aec8af773cca7b483e44a92d8187495ff`; original `100644:c9efe80c62b65c2a5ca4c43fb7db0841b73e521f`; pinned-current `100644:6e890ba10cc86cd066f5c4c6d84091c956183738`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-10,0+11,1`, `-15,0+17,1`, `-17,1+20,10`, `-27,0+39,4`
- A | SwarmCoordinator.__init__: `-41,0+57,1`, `-46,0+63,14`, `-47,0+78,1`
- A | SwarmCoordinator._init_db: `-53,1+85,19`, `-55,13+105,18`
- L | SwarmCoordinator: `-69,1+124,46`, `-72,0+197,51`, `-182,6+381,104`, `-314,7+697,87`
- A | SwarmCoordinator._recover_swarm_state: `-71,0+171,25`
- A | SwarmCoordinator.dispatch: `-80,1+256,1`, `-83,26+259,13`, `-112,2+275,3`, `-116,10+280,2`, `-128,0+284,21`, `-129,0+306,10`, `-132,1+319,1`, `-135,0+322,1`
- A | SwarmCoordinator.get_status: `-141,1+329,2`, `-146,1+335,0`, `-149,1+337,0`, `-157,5+344,7`
- A | SwarmCoordinator._release_all_leases: `-164,6+353,8`
- A | SwarmCoordinator.step: `-177,0+368,3`, `-178,3+372,8`
- U | SwarmCoordinator._step_transaction: `-189,1+486,159`
- L | SwarmCoordinator._step_transaction: `-192,1+647,4`, `-194,0+652,2`, `-195,83+655,3`, `-283,0+663,1`, `-285,2+666,4`
- A | SwarmCoordinator.cancel: `-322,18+785,14`, `-341,1+800,42`

### D284 src/local_ai_hub/task_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d35d491a939526dae6df6bf60a20753fb4f95cb5`; original `100644:188f3e5e81229d6b3444f253557e8a5404b214cc`; pinned-current `100644:8f0a45bac726fc3409bd06176598a0eb6009148e`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`
- U | build_context_request: `-32,1+33,6`, `-46,1+66,1`
- L | build_context_request: `-41,0+47,14`, `-53,0+73,3`

### D285 src/local_ai_hub/task_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d35d491a939526dae6df6bf60a20753fb4f95cb5`; original `100644:71ac8dfb82ab38e43fd110769b35e7ff62914e9e`; pinned-current `100644:8f0a45bac726fc3409bd06176598a0eb6009148e`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | build_context_request: `-60,0+60,1`

### D286 src/local_ai_hub/task_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d35d491a939526dae6df6bf60a20753fb4f95cb5`; original `100644:91fc22da04c3f5bbb78b957dba74986e1ed9c1d9`; pinned-current `100644:8f0a45bac726fc3409bd06176598a0eb6009148e`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,1+5,3`, `-8,0+10,7`, `-9,0+18,10`, `-61,0+124,103`
- L | build_context_request: `-32,2+51,10`, `-36,0+63,33`, `-46,1+106,1`, `-48,0+108,1`
- U | build_context_request: `-60,0+121,2`
- A | _repository_projection: `-68,0+234,1`

### D287 src/local_ai_hub/telemetry.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0360933c3a8686d355b8a1c86d08a29b15691111`; original `100644:822889538e2297c9be982f69ff851fd8a6a7857c`; pinned-current `100644:0cabdc6f4f4ae16f13b21f106b764b146baf7b3c`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | _safe_error_message: `-104,0+104,6`
- A | TelemetryStore._enqueue: `-571,1+577,1`, `-573,2+579,1`, `-581,5+586,4`, `-588,0+592,5`
- A | TelemetryStore.record: `-720,1+729,1`, `-725,1+734,1`
- A | TelemetryStore.record_tool_accounting: `-735,1+744,1`, `-743,1+752,1`, `-746,1+755,1`, `-756,1+765,1`, `-783,0+792,1`
- A | TelemetryStore.record_system: `-784,1+794,1`, `-786,1+796,1`

### D288 src/local_ai_hub/telemetry.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:457ae7e184b4b5dfa72eb8fde7fa7c63970e9932`; original `100644:7c7319ffbfad2d9bd646ba1dd73228a55a40614a`; pinned-current `100644:0cabdc6f4f4ae16f13b21f106b764b146baf7b3c`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,2`, `-26,0+28,1`, `-27,0+30,3`, `-39,0+45,78`
- U | _safe_error_message: `-107,2+191,24`
- U | _safe_metadata: `-119,1+225,1`, `-135,0+242,9`
- L | _safe_metadata: `-129,0+235,1`
- U | _safe_metadata.redact_posix: `-132,1+239,1`
- U | TelemetryStore._clean_event: `-501,0+617,2`, `-503,1+621,1`, `-508,1+626,1`, `-512,1+630,1`
- A | TelemetryStore._writer_loop: `-1203,5+1321,6`, `-1232,1+1351,3`
- A | TelemetryStore.report: `-1675,1+1796,4`, `-1684,0+1808,6`, `-1720,5+1850,42`, `-1791,1+1958,1`, `-1855,0+2022,19`, `-1889,0+2075,1`
- U | TelemetryStore: `-1948,0+2135,55`

### D289 src/local_ai_hub/telemetry.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:989d252302371924b125e9997d42cbcbf9f14f6d`; original `100644:c0df88b2ff6c55c50565b6e2854dacb7cd30c35d`; pinned-current `100644:0cabdc6f4f4ae16f13b21f106b764b146baf7b3c`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-7,0+8,2`, `-26,1+29,9`, `-34,0+45,79`, `-131,0+254,17`
- A | _percentile: `-68,0+158,3`
- A | _safe_error_message: `-99,5+192,33`
- A | _error_fingerprint: `-106,4+227,5`
- A | _safe_metadata: `-123,0+245,1`
- U | TelemetryStore.record_error: `-804,0+944,7`, `-805,1+952,1`, `-807,2+954,2`
- L | TelemetryStore.record_error: `-814,2+961,3`
- A | TelemetryStore._writer_loop: `-1172,5+1320,6`, `-1201,1+1350,3`
- A | TelemetryStore.report: `-1644,1+1795,4`, `-1653,0+1807,6`, `-1689,5+1849,42`, `-1760,1+1957,1`, `-1824,0+2021,19`, `-1858,0+2074,1`
- L | TelemetryStore: `-1917,0+2134,46`

### D290 src/local_ai_hub/tiered_ollama.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a958825231d12840d23b04590898e77b7838d30a`; original `100644:2aa3426ca7d3e04e87887c15869a620258756ecb`; pinned-current `100644:9ea3c1d5adfc7aa5e500d6e4073d773e6f733fe3`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`
- A | TieredOllamaRuntime.__init__: `-36,0+37,9`
- L | TieredOllamaRuntime: `-75,2+85,24`, `-179,0+228,10`, `-186,0+245,82`, `-207,0+348,72`
- A | TieredOllamaRuntime._unload_peer: `-83,1+115,10`, `-85,1+126,1`
- A | TieredOllamaRuntime._handoff: `-89,4+130,0`, `-95,1+132,4`, `-101,0+141,6`
- A | TieredOllamaRuntime.prepare_model: `-170,0+216,1`, `-176,0+223,2`

### D291 src/local_ai_hub/tiered_ollama.py

Disposition: `preserved-only-needs-integration`. Occurrences: 18:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c6fe6a09c1de3eebf2e496111773ca1fae577df9`; original `100644:2023b3fdea7d4000634cdf2ad7426b8bb4d7486b`; pinned-current `100644:9ea3c1d5adfc7aa5e500d6e4073d773e6f733fe3`.

Exact checkpoint/owner witnesses: `S023 / b0ade36afca1bceeb6756fe76eeb0ca90758e64a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | TieredOllamaRuntime: `-195,0+195,48`

### D292 src/local_ai_hub/tiered_ollama.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c6fe6a09c1de3eebf2e496111773ca1fae577df9`; original `100644:990fed2d2337aa9a5d42f7026b8a74e0dc21c0c4`; pinned-current `100644:9ea3c1d5adfc7aa5e500d6e4073d773e6f733fe3`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,1+6,1`
- A | TieredOllamaRuntime.request_interruptible: `-132,1+132,9`, `-139,1+147,1`
- A | TieredOllamaRuntime.prepare_model: `-141,1+149,9`
- L | TieredOllamaRuntime: `-144,1+160,16`, `-192,0+223,17`

### D293 src/local_ai_hub/token_economy.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7eefe9182e997ade6a70087927f2feda691fc40c`; original `100644:6114f57d829205cb5765eb813a7a81d9b643eb02`; pinned-current `100644:6114f57d829205cb5765eb813a7a81d9b643eb02`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | tokcount_main: `-96,1+96,0`, `-148,1+147,0`

### D294 src/local_ai_hub/token_router.py

Disposition: `integrated-current`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e6dc705e08b2d84471b1a4e9a23ea56016320ecc`; original `100644:7a3f2fce1303d2d99c79620cd9d239c751d0932a`; pinned-current `100644:7a3f2fce1303d2d99c79620cd9d239c751d0932a`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | LosslessTokenRouter.__init__: `-39,1+39,1`

### D295 src/local_ai_hub/tool_agent.py

Disposition: `integrated-current`. Occurrences: 22:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e47bb9bdc55f01692ac63641059f1f69ef8d99ae`; original `100644:9ce1e43148c0f85aab6dcb490bb06dda91827211`; pinned-current `100644:9ce1e43148c0f85aab6dcb490bb06dda91827211`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | ToolAwareLocalAgent._execute_tool: `-216,12+216,11`

### D296 src/local_ai_hub/treesitter_parser.py

Disposition: `preserved-only-needs-integration`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4f41ca5427e4b01cb5084001f37153803f78a3de`; original `100644:4f0482fd3f99f3e34e809f182f08c438d5dea861`; pinned-current `100644:9c8dc2e592009aeb906dcf61a1dad4e4e45fa25d`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-24,0+24,5`, `-367,0+381,192`
- U | _init_treesitter_once: `-54,3+59,3`
- A | is_treesitter_available: `-144,0+149,4`
- U | parse_treesitter: `-169,0+178,2`, `-176,0+187,1`, `-177,3+189,4`, `-182,0+195,14`, `-183,1+210,1`, `-185,13+212,0`

### D297 src/local_ai_hub/treesitter_parser.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:69f7aa970c3d061422506ea958389a01f7093ee4`; original `100644:c3ea1cf996d74ec5b9b77df52c3140a70c9eaa6b`; pinned-current `100644:9c8dc2e592009aeb906dcf61a1dad4e4e45fa25d`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,2+3,2`, `-13,0+13,1`
- U | _init_treesitter: `-39,2+40,0`
- U | <module/text>: `-145,0+144,12`
- A | _extract_js_ts.visit: `-479,0+490,24`

### D298 src/local_ai_hub/treesitter_parser.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c01556d58d6b15cd3e5ac120d8f5806b645f8126`; original `100644:98eb6b3bbef28b8452b9f800709511971ae2fb62`; pinned-current `100644:9c8dc2e592009aeb906dcf61a1dad4e4e45fa25d`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | is_treesitter_available: `-144,0+144,4`
- U | parse_treesitter: `-169,0+173,2`, `-194,0+200,4`
- L | <module/text>: `-861,0+871,191`

### D299 src/local_ai_hub/vision_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 11:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4a8c252d463cbd329f8434684c0c621c3f74f9`; original `100644:1fa61013e1a1dae63bba3114b452544338058d2d`; pinned-current `100644:b7db77c4bbd985a09b8215460c341dd6aae0449f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-40,0+40,71`
- U | VisionFinding: `-141,0+212,1`
- U | parse_vision_result: `-238,1+310,7`, `-244,0+322,2`, `-248,0+328,7`, `-278,0+365,2`, `-284,0+373,2`, `-296,0+387,8`, `-306,0+405,69`, `-312,1+480,1`, `-316,1+484,1`, `-322,0+490,1`
- L | parse_vision_result: `-253,1+340,1`

### D300 src/local_ai_hub/vision_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 8:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4a8c252d463cbd329f8434684c0c621c3f74f9`; original `100644:a66f60397ed25123fbb275e88206b51e6a47bd49`; pinned-current `100644:b7db77c4bbd985a09b8215460c341dd6aae0449f`.

Exact checkpoint/owner witnesses: `S037 / 5b16828e44f5ca0b09c265b2a5a034fe94bbddea / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-8,1+8,1`
- L | build_coder_packet: `-414,0+414,9`, `-418,0+427,1`, `-477,1+487,1`
- U | build_coder_packet: `-447,1+457,1`

### D301 src/local_ai_hub/vision_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f4a8c252d463cbd329f8434684c0c621c3f74f9`; original `100644:cd3f630bc6f5a65c5b95e6da98e5c75d51748ba8`; pinned-current `100644:b7db77c4bbd985a09b8215460c341dd6aae0449f`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-38,1+38,17`, `-223,0+249,48`
- L | <module/text>: `-126,0+142,8`
- A | VisionFinding: `-133,0+157,1`
- A | VisionParseResult: `-149,0+174,1`
- L | parse_vision_result: `-238,1+312,7`, `-240,0+320,2`, `-244,0+326,6`, `-248,0+336,11`, `-278,0+377,15`, `-282,2+396,2`, `-296,0+410,8`, `-302,0+424,4`, `-312,1+549,1`, `-314,0+551,1`, `-316,1+554,1`, `-318,1+556,1`, `-339,2+577,2`, `-347,0+585,1`
- U | parse_vision_result: `-306,0+432,111`
- L | build_coder_packet: `-436,1+675,2`, `-481,1+724,3`
- U | build_coder_packet: `-444,1+684,4`

### D302 src/local_ai_hub/vram_balancer.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:172b56f7388fbe886b84556e9792b4af1398730d`; original `100644:525632bcb5901513df3a672b07975aaa776a4ce0`; pinned-current `100644:108e54134f28b6a728131716eebb06f82f57b62d`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | VRAMBalancer.__init__: `-21,0+21,3`, `-23,0+26,1`
- A | VRAMBalancer.status: `-27,2+31,3`
- U | VRAMBalancer: `-32,1+37,112`
- A | VRAMBalancer._status_from_telemetry: `-104,0+220,1`
- L | VRAMBalancer: `-110,0+227,6`
- A | VRAMBalancer.pin_model: `-115,0+238,1`
- A | VRAMBalancer.get_pinned_model: `-126,0+250,2`
- A | VRAMBalancer.unpin_model: `-134,0+260,1`

### D303 src/local_ai_hub/vram_balancer.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3192d65f695a55e12520b77b5cb650716ff118f4`; original `100644:c1fbc3c3be07128f6d240e2d101312d5725ba772`; pinned-current `100644:108e54134f28b6a728131716eebb06f82f57b62d`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | VRAMBalancer.__init__: `-21,0+21,3`, `-23,0+26,1`
- L | VRAMBalancer.status: `-27,2+31,3`
- U | VRAMBalancer: `-32,1+37,87`
- A | VRAMBalancer._status_from_telemetry: `-104,0+195,1`
- L | VRAMBalancer: `-105,0+197,10`
- A | VRAMBalancer.pin_model: `-111,0+213,1`
- A | VRAMBalancer.get_pinned_model: `-122,0+225,2`
- A | VRAMBalancer.unpin_model: `-130,0+235,1`

### D304 src/local_ai_hub/work_orchestrator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 10:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0e50af8bc3679838bb225b23c612070088bad964`; original `100644:44b039c88fddb1d69b22c84d96aad0079348214c`; pinned-current `100644:e1b3603abb73de1739af62619918604f21b584f0`.

Exact checkpoint/owner witnesses: `S031 / c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3 / true / f99619a4658692b2d15d40a07f2176891c72cffa`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,1`
- L | <module/text>: `-16,1+17,1`, `-24,0+25,9`
- A | _JournalEntry: `-282,0+292,8`
- A | WorkOrchestrator.__init__: `-293,1+311,6`, `-315,0+338,4`, `-316,0+343,5`, `-323,0+355,2`, `-324,0+358,1`, `-328,1+363,0`
- L | WorkOrchestrator: `-334,0+368,6`, `-398,2+494,56`, `-423,23+726,28`, `-874,0+1569,53`, `-1025,1+1854,0`
- A | WorkOrchestrator._persist_journal: `-368,1+408,13`
- A | WorkOrchestrator._load_journal: `-392,1+444,45`
- A | WorkOrchestrator._recover: `-402,0+552,1`, `-405,1+556,1`, `-410,0+561,7`, `-412,0+570,2`, `-413,0+573,3`, `-415,2+578,54`, `-419,1+634,28`, `-422,0+664,61`
- A | WorkOrchestrator.submit: `-516,0+824,20`
- A | WorkOrchestrator.cancel: `-608,0+936,1`, `-609,3+938,7`
- A | WorkOrchestrator.continue_work: `-625,2+958,6`
- U | WorkOrchestrator: `-641,4+978,24`, `-651,0+1008,114`, `-813,0+1287,48`
- A | WorkOrchestrator._loop: `-689,1+1160,4`
- U | WorkOrchestrator._rollback: `-815,0+1337,2`, `-816,0+1340,37`
- A | WorkOrchestrator._rollback_transaction: `-826,1+1387,4`, `-828,1+1392,1`, `-830,8+1394,50`
- A | WorkOrchestrator._apply_patch: `-839,1+1445,5`, `-842,0+1452,2`, `-847,0+1459,2`, `-851,1+1465,8`, `-854,5+1475,15`, `-860,4+1491,58`, `-866,5+1551,4`, `-872,0+1556,11`
- A | WorkOrchestrator._execute_fenced: `-877,0+1625,4`, `-924,2+1738,4`, `-929,1+1745,4`, `-932,2+1751,5`, `-936,0+1758,1`, `-939,1+1762,1`, `-942,1+1765,4`, `-963,1+1789,1`, `-972,1+1798,1`, `-976,2+1802,2`, `-981,1+1807,1`, `-985,1+1811,1`, `-1009,1+1835,1`, `-1012,1+1838,4`, `-1019,1+1848,1`, `-1022,1+1851,1`, `-1043,0+1871,82`, `-1050,3+1960,9`, `-1054,1+1970,1`, `-1057,1+1973,1`, `-1061,1+1977,1`, `-1070,1+1986,2`, `-1072,1+1989,3`
- A | WorkOrchestrator._execute_fenced.run_validations: `-889,1+1641,7`, `-895,2+1653,26`, `-898,0+1680,31`
- A | WorkOrchestrator._execute_fenced.repair: `-900,1+1713,1`, `-916,1+1729,1`, `-918,1+1731,2`
- A | WorkOrchestrator.close: `-1080,0+1999,5`

### D305 src/local_ai_hub/work_orchestrator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0e50af8bc3679838bb225b23c612070088bad964`; original `100644:cdf98ab98066eaa4815c1c56678314f9b87c6d34`; pinned-current `100644:e1b3603abb73de1739af62619918604f21b584f0`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,1`, `-24,0+25,4`
- L | <module/text>: `-16,1+17,1`
- A | _JournalEntry: `-282,0+287,8`
- A | WorkOrchestrator.__init__: `-293,1+306,6`, `-315,0+333,4`, `-316,0+338,5`, `-323,0+350,2`, `-324,0+353,1`, `-328,1+358,0`
- L | WorkOrchestrator: `-334,0+363,6`, `-398,2+489,56`, `-423,23+721,28`, `-651,0+994,123`, `-813,0+1282,48`, `-874,0+1578,53`, `-1025,1+1863,0`
- A | WorkOrchestrator._persist_journal: `-368,1+403,13`
- A | WorkOrchestrator._load_journal: `-392,1+439,45`
- A | WorkOrchestrator._recover: `-402,0+547,1`, `-405,1+551,1`, `-410,0+556,7`, `-412,0+565,2`, `-413,0+568,3`, `-415,2+573,54`, `-419,1+629,28`, `-422,0+659,61`
- A | WorkOrchestrator.submit: `-516,0+819,20`
- A | WorkOrchestrator.cancel: `-608,0+931,1`, `-609,3+933,7`
- A | WorkOrchestrator.continue_work: `-625,2+953,6`
- A | WorkOrchestrator._set_state: `-641,4+973,15`
- A | WorkOrchestrator._loop: `-689,1+1155,4`
- U | WorkOrchestrator._rollback: `-815,0+1332,31`
- L | WorkOrchestrator._rollback: `-816,1+1364,23`, `-818,2+1388,2`, `-822,1+1392,1`
- A | WorkOrchestrator._rollback_transaction: `-826,1+1396,4`, `-828,1+1401,1`, `-830,8+1403,50`
- A | WorkOrchestrator._apply_patch: `-839,1+1454,5`, `-842,0+1461,2`, `-847,0+1468,2`, `-851,1+1474,8`, `-854,5+1484,15`, `-860,4+1500,58`, `-866,5+1560,4`, `-872,0+1565,11`
- A | WorkOrchestrator._execute_fenced: `-877,0+1634,4`, `-924,2+1747,4`, `-929,1+1754,4`, `-932,2+1760,5`, `-936,0+1767,1`, `-939,1+1771,1`, `-942,1+1774,4`, `-963,1+1798,1`, `-972,1+1807,1`, `-976,2+1811,2`, `-981,1+1816,1`, `-985,1+1820,1`, `-1009,1+1844,1`, `-1012,1+1847,4`, `-1019,1+1857,1`, `-1022,1+1860,1`, `-1043,0+1880,82`, `-1050,3+1969,9`, `-1054,1+1979,1`, `-1057,1+1982,1`, `-1061,1+1986,1`, `-1070,1+1995,2`, `-1072,1+1998,3`
- A | WorkOrchestrator._execute_fenced.run_validations: `-889,1+1650,7`, `-895,2+1662,26`, `-898,0+1689,31`
- A | WorkOrchestrator._execute_fenced.repair: `-900,1+1722,1`, `-916,1+1738,1`, `-918,1+1740,2`
- A | WorkOrchestrator.close: `-1080,0+2008,5`

### D306 tests/conftest.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fdcbc1fe0b0e07f1d53ead7d660533468e2548e0`; original `100644:a779625445899d046273c4f37e561b48fc5d010c`; pinned-current `100644:a779625445899d046273c4f37e561b48fc5d010c`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-10,0+10,20`

### D307 tests/fixtures/browser_bridge/current_tab_harness.js

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:52040fa0a5c5b97ad000ef2a2767e84d5bcd51e0`; original `100644:0dc7f7abc718db77b162a41c0e526c937dd617ea`; pinned-current `100644:fc086ae23281df0c172b7abb138db7ad533c51e9`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-126,1+126,1`, `-131,0+131,1`, `-133,0+134,1`, `-148,0+150,3`, `-169,1+174,7`, `-240,1+258,1`, `-243,0+261,6`, `-268,0+292,5`, `-276,2+305,4`, `-281,1+312,6`, `-284,1+320,1`
- U | <module/text>: `-193,3+204,10`

### D308 tests/fixtures/browser_bridge/current_tab_harness.js

Disposition: `integrated-current`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:52040fa0a5c5b97ad000ef2a2767e84d5bcd51e0`; original `100644:fc086ae23281df0c172b7abb138db7ad533c51e9`; pinned-current `100644:fc086ae23281df0c172b7abb138db7ad533c51e9`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-126,1+126,1`, `-131,0+131,1`, `-133,0+134,1`, `-148,0+150,3`, `-169,1+174,7`, `-193,3+204,10`, `-240,1+258,1`, `-243,0+261,6`, `-268,0+292,5`, `-276,2+305,4`, `-281,1+312,6`, `-284,1+320,1`

### D309 tests/test_adaptive_retrieval.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a084f9e7227b8fc6b82fda91a613f1a4d8f80c14`; original `100644:178ed527e4f72d29723100a859925c83a19d78ef`; pinned-current `100644:51ee313321e0a6a8fe8d227fe8330089fce4e002`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_fusion_prefers_agreement_and_keeps_file_diversity: `-17,1+17,0`
- A | test_concurrent_context_requests_bound_serena_workers: `-167,1+166,1`, `-171,2+170,2`

### D310 tests/test_adaptive_retrieval.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a084f9e7227b8fc6b82fda91a613f1a4d8f80c14`; original `100644:e00646c933e85efb2b0c5f9103c6dba9d53f90c7`; pinned-current `100644:51ee313321e0a6a8fe8d227fe8330089fce4e002`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_fusion_prefers_agreement_and_keeps_file_diversity: `-17,1+17,0`
- L | <module/text>: `-26,0+25,94`
- A | test_concurrent_context_requests_bound_serena_workers: `-167,1+260,1`, `-171,2+264,2`
- L | test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage: `-430,0+523,2`, `-477,1+578,2`, `-487,0+589,3`
- A | test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage.FakeRepoTools: `-431,0+526,4`
- A | test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage.FakeRepoTools.context_pack_paths: `-436,1+535,2`
- A | test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage.FakeRag.search: `-463,0+563,1`

### D311 tests/test_adaptive_retrieval.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c0afe3cba82fd7abb6d210f08d93028ea6ee694d`; original `100644:629a45bf7e4547a66dbc860e5a08f21e08747245`; pinned-current `100644:51ee313321e0a6a8fe8d227fe8330089fce4e002`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_lexical_command_is_path_bounded: `-60,0+60,1`
- L | <module/text>: `-133,0+134,49`, `-242,0+292,24`, `-512,0+586,330`
- A | test_rag_exception_degrades_and_keeps_evidence_traceable.FakeRepoTools.context_pack: `-253,1+327,1`
- A | test_rag_malformed_chunk_is_skipped_without_failing_context.FakeRepoTools.context_pack: `-305,1+379,1`
- A | test_incomplete_evidence_receipt_fails_closed.FakeRepoTools.context_pack: `-381,1+455,1`
- U | test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage.FakeRepoTools.context_pack: `-436,1+510,1`
- L | test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage: `-483,1+557,1`

### D312 tests/test_affected_tests.py

Disposition: `integrated-current`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:eef41997edde6354c42be0bc2062793d1ab3ec47`; original `100644:d095825d86cf3adfaf68f777c0dc72fb232927f2`; pinned-current `100644:d095825d86cf3adfaf68f777c0dc72fb232927f2`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-5,0+5,1`, `-40,0+41,25`

### D313 tests/test_agent_consistency.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:356abff4008ab731e64960c10e0cf3b6f2b87995`; original `100644:20764fb2589144bed5288e8e2c6c83d0ff8e0a37`; pinned-current `100644:185378f0064660c61deb8c684b38028d564344aa`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_guard_records_unknown_and_validation_receipt: `-714,1+714,3`, `-718,1+720,3`
- A | test_record_validation_verifier_true_records_matching_passed_receipt: `-762,1+766,1`
- L | <module/text>: `-772,0+776,63`, `-863,0+930,20`

### D314 tests/test_agent_consistency.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:356abff4008ab731e64960c10e0cf3b6f2b87995`; original `100644:b6cf872f8b03a2a5f27d4c2b77481aa2d20a1a56`; pinned-current `100644:185378f0064660c61deb8c684b38028d564344aa`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_guard_records_unknown_and_validation_receipt: `-714,1+714,3`, `-718,1+720,3`
- A | test_record_validation_verifier_true_records_matching_passed_receipt: `-762,1+766,1`
- U | <module/text>: `-772,0+776,16`

### D315 tests/test_agent_consistency.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:356abff4008ab731e64960c10e0cf3b6f2b87995`; original `100644:f7ba3c02887de3d9332fe34dfbcfd3a24510b329`; pinned-current `100644:185378f0064660c61deb8c684b38028d564344aa`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-57,0+57,20`

### D316 tests/test_agent_context.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:339f42159b466437b30fd9bcb08730ec7940eaef`; original `100644:4d25e0fb0b7d34bd0d20d661c97d9ecc83ce86a8`; pinned-current `100644:a7290d3f53b26c13746c026518162a4dba38d4eb`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-152,0+153,54`

### D317 tests/test_agent_context.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a8bf089f2af2b060ca90a41e62f680f5141d5201`; original `100644:038c68c43ba6b8aa6a9162b8bb7125157e56d60b`; pinned-current `100644:a7290d3f53b26c13746c026518162a4dba38d4eb`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | compiler: `-37,0+37,1`
- L | test_authoritative_memory_is_root_and_task_session_scoped: `-615,1+616,1`

### D318 tests/test_agent_context.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a8bf089f2af2b060ca90a41e62f680f5141d5201`; original `100644:d00de7c1c401adafbcdf685121eed3dfead366e0`; pinned-current `100644:a7290d3f53b26c13746c026518162a4dba38d4eb`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-16,0+16,1`, `-117,0+119,118`
- A | compiler: `-37,0+38,1`
- A | test_phase_pack_prioritizes_reuse_for_edit: `-120,0+240,1`, `-126,0+247,1`, `-134,0+256,1`, `-137,1+260,3`
- A | test_context_compile_marks_changed_repository_memory_stale: `-189,1+314,1`, `-199,1+324,1`, `-214,5+339,10`
- A | test_stale_memory_is_excluded_from_authoritative_context: `-269,1+399,1`, `-274,1+404,1`
- A | test_stale_memory_remains_visible_as_diagnostic: `-293,1+423,1`, `-298,1+428,4`
- A | test_memory_diagnostics_are_repository_scoped: `-318,1+451,1`, `-328,1+461,1`, `-333,1+466,4`
- A | test_legacy_rootless_memory_is_not_included_without_root: `-342,1+478,1`, `-353,1+489,1`, `-358,1+494,1`, `-360,1+496,2`, `-363,1+500,4`
- A | test_authoritative_memory_is_root_and_task_session_scoped: `-563,0+703,1`, `-573,0+714,1`, `-583,0+725,1`, `-593,0+736,1`, `-602,0+746,1`, `-611,0+756,1`, `-615,1+761,1`

### D319 tests/test_agent_event_drop_metrics.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:36f6a1969fea749327f136b8b2702987d82c9271`; original `100644:156925cd457933716c8c1615ed5d42557db8bc07`; pinned-current `100644:36f6a1969fea749327f136b8b2702987d82c9271`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_publish_reports_exact_per_stream_ranges_for_queue_overflow: `-4,1+4,1`, `-7,3+7,3`, `-13,1+13,1`, `-15,3+15,10`
- U | <module/text>: `-19,0+26,40`

### D320 tests/test_agent_events.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f4b678caaf02b0b9cb5476a9eaa157f0bed4c3da`; original `100644:577dae3fd7cb352b26cb340c43c1b4317ddb260e`; pinned-current `100644:577dae3fd7cb352b26cb340c43c1b4317ddb260e`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,1`, `-7,0+8,34`

### D321 tests/test_agent_memory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c96309b1a4b57eec3f360faa51493e90234f87ec`; original `100644:171ffbe1cbc540b185c2d4cb4eccb2ba2e5e7ee1`; pinned-current `100644:00bec02327491f3c4b7163ffe07ec1ea7e45a304`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,1`, `-19,0+20,6`, `-50,0+58,236`, `-95,0+342,85`, `-99,0+431,80`
- U | confirmed_repository_record: `-47,0+54,1`
- L | test_legacy_unscoped_lookup_rejects_nonempty_task_and_session_context: `-57,0+301,1`, `-69,0+314,1`, `-93,1+340,1`
- U | test_legacy_unscoped_lookup_rejects_nonempty_task_and_session_context: `-82,0+328,1`, `-86,4+333,4`
- U | test_memory_find_enforces_root_repository_and_tenant_identity: `-107,1+519,1`, `-114,1+526,1`, `-121,1+533,1`
- L | test_memory_find_enforces_root_repository_and_tenant_identity: `-151,0+563,1`, `-154,1+567,1`, `-158,4+571,5`, `-165,0+579,1`, `-175,0+590,1`
- A | test_global_promotion_succeeds_with_user_approval: `-227,1+643,7`
- A | test_record_idempotency_reuses_existing_record: `-374,1+796,1`
- U | test_evidence_memory_persists_revision_metadata_and_is_idempotent: `-391,0+813,1`
- L | test_evidence_memory_persists_revision_metadata_and_is_idempotent: `-401,0+824,1`, `-404,1+828,7`
- A | test_record_idempotency_is_atomic_under_concurrency: `-435,1+865,1`
- A | test_repository_revision_is_preserved_in_provenance: `-476,0+906,1`, `-484,1+915,6`
- A | test_mark_stale_for_revision_preserves_metadata_and_emits_event: `-503,0+939,1`, `-511,1+948,6`, `-517,3+959,3`
- A | test_mark_stale_for_revision_guards_revision_paths_root_and_repeats: `-532,0+974,1`, `-551,1+994,3`, `-553,1+998,6`
- A | test_mark_stale_for_revision_matches_beyond_100k_rows: `-574,1+1024,1`, `-597,1+1047,1`, `-620,1+1070,1`
- A | test_mark_stale_for_revision_matches_relative_and_absolute_roots: `-634,0+1084,1`, `-641,1+1092,1`
- A | test_mark_stale_for_revision_deduplicates_and_caps_changed_paths: `-654,0+1105,1`, `-664,1+1116,1`
- A | test_mark_stale_batch_rolls_back_and_repeats_idempotently: `-683,0+1135,1`, `-704,1+1157,1`
- U | <module/text>: `-718,0+1171,145`

### D322 tests/test_agent_memory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c96309b1a4b57eec3f360faa51493e90234f87ec`; original `100644:50ac82433783858e7e60a5c504cc1bae1e106cca`; pinned-current `100644:00bec02327491f3c4b7163ffe07ec1ea7e45a304`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | confirmed_repository_record: `-39,0+39,1`, `-47,0+48,1`
- U | <module/text>: `-184,0+186,52`
- U | test_global_promotion_succeeds_with_user_approval: `-227,1+281,8`
- L | <module/text>: `-230,0+291,13`, `-718,0+792,23`

### D323 tests/test_agent_os_enhancements.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:20d714d3d2f99338f2c6d8c94d6159b6188a7714`; original `100644:9e850736d09613fc51fd2d6262558a79c1c8e89e`; pinned-current `100644:41c4de6bc82f56d7443a090cf88f91a6e9d1c2d5`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_generic_command_does_not_auto_register_verification_receipt: `-96,1+96,1`, `-140,7+140,1`, `-148,3+142,2`

### D324 tests/test_agent_os_enhancements.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:20d714d3d2f99338f2c6d8c94d6159b6188a7714`; original `100644:a0ddda781e7c05a5a3489ddbb3d2dec1da658fbb`; pinned-current `100644:41c4de6bc82f56d7443a090cf88f91a6e9d1c2d5`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-400,10+400,0`

### D325 tests/test_agent_os_enhancements.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:57eab0d931b21dd0557e95330fe91e2825a2bfc9`; original `100644:8873ba4947f2a681dd1d2d5e5bf0a8e18bd13b2e`; pinned-current `100644:41c4de6bc82f56d7443a090cf88f91a6e9d1c2d5`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-442,11+442,0`

### D326 tests/test_agent_policy.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3fef9cefc9210a3e8684bb61f80315dc52d440dd`; original `100644:ee841368ca24c59c4b1ad95551667f59ab150f2c`; pinned-current `100644:ee841368ca24c59c4b1ad95551667f59ab150f2c`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-74,0+74,16`

### D327 tests/test_agent_state_e2e.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8e266a15ffd923bb3a96afc8512c5db2475499ae`; original `100644:18b8c204e4f126d27b7de5f6aec25c6055c7f27d`; pinned-current `100644:7ea911671171992ba3f35773272daf0cce0994c3`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,2`, `-6,0+8,1`, `-37,1+40,35`, `-159,0+302,98`
- L | test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command: `-40,2+77,5`
- U | test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command: `-44,1+84,9`, `-47,1+95,22`, `-52,1+121,4`
- L | test_e2e_completion_gate_enforcement: `-105,1+177,6`, `-108,2+185,5`, `-111,0+191,10`
- U | test_e2e_completion_gate_enforcement: `-117,2+207,31`, `-125,2+244,26`

### D328 tests/test_agent_state_e2e.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f93bc9ea37d2bacc31bde75de704b02ddb503d96`; original `100644:b0cbed6fcc57c33cc9aaf0e32f9cbc3b1c0c84fd`; pinned-current `100644:7ea911671171992ba3f35773272daf0cce0994c3`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_interrupted_task_resumes_with_fresh_evidence_and_no_duplicate_command: `-49,0+49,1`, `-57,1+58,1`, `-69,0+70,1`
- L | test_e2e_completion_gate_enforcement: `-136,0+138,1`, `-144,1+147,1`, `-151,1+154,2`, `-165,1+169,1`, `-172,1+176,2`
- U | <module/text>: `-206,0+211,74`

### D329 tests/test_agent_state_operations.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:79cd4523cd025211ef3dda51256d7dda5671af65`; original `100644:8351343c1a7790cf5aecb44ae0dc4d25a7e74e05`; pinned-current `100644:33d17053fa03ac95c84677df5de17fb6dd7097f5`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-90,0+90,19`, `-457,0+530,49`
- L | test_selective_export_and_import_valid_records: `-114,0+133,1`, `-116,1+136,4`, `-124,1+147,7`
- U | test_selective_bundle_roundtrips_memory_metadata: `-133,0+162,1`, `-163,1+196,5`
- L | test_selective_bundle_roundtrips_memory_metadata: `-150,1+180,1`, `-158,1+188,4`, `-169,1+206,1`
- A | test_project_bundle_roundtrips_agent_state_memory_metadata: `-184,0+221,1`, `-201,1+239,1`, `-209,1+247,4`, `-214,1+255,5`, `-223,1+268,1`, `-229,1+274,1`
- A | test_project_bundle_rejects_foreign_repository_memory: `-239,1+284,1`, `-254,1+299,4`
- A | test_project_bundle_rejects_repository_memory_without_root: `-273,1+321,4`
- A | test_project_bundle_import_rejects_repository_memory_without_root: `-292,1+343,1`, `-296,1+347,4`
- A | test_project_bundle_rejects_tampered_agent_state_records: `-337,1+391,1`, `-341,1+395,4`
- A | test_project_bundle_rejects_removed_agent_state_integrity_data: `-371,1+428,1`, `-375,1+432,4`
- A | test_standalone_bundle_honors_json_and_compressed_limits: `-403,0+463,1`, `-408,1+469,4`, `-412,1+476,4`
- A | test_bundle_requires_exact_current_application_version: `-425,0+492,1`, `-427,1+495,4`
- A | test_app_status_includes_agent_state_summary: `-442,1+513,1`, `-444,0+515,2`

### D330 tests/test_agent_state_operations.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:79cd4523cd025211ef3dda51256d7dda5671af65`; original `100644:8f14d9e13fe8add86213a04a26e0f53ab8789aaf`; pinned-current `100644:33d17053fa03ac95c84677df5de17fb6dd7097f5`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,1+12,0`
- L | test_selective_export_and_import_valid_records: `-106,0+105,2`
- U | test_selective_export_and_import_valid_records: `-114,0+115,1`, `-116,1+118,3`, `-123,2+127,7`
- U | test_selective_bundle_roundtrips_memory_metadata: `-131,0+140,2`, `-132,1+143,2`, `-158,1+170,3`, `-163,1+177,6`, `-165,1+184,4`
- L | test_project_bundle_roundtrips_agent_state_memory_metadata: `-184,0+206,1`
- U | test_project_bundle_roundtrips_agent_state_memory_metadata: `-209,1+232,3`, `-214,1+239,6`
- U | <module/text>: `-228,4+258,0`
- A | test_app_status_includes_agent_state_summary: `-442,1+468,1`, `-444,0+470,2`

### D331 tests/test_agent_state_operations.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 38:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:79cd4523cd025211ef3dda51256d7dda5671af65`; original `100644:ebb06bb193b8525a898dd0f7611c818e59172295`; pinned-current `100644:33d17053fa03ac95c84677df5de17fb6dd7097f5`.

Exact checkpoint/owner witnesses: `S002 / 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_app_status_includes_agent_state_summary: `-442,1+442,1`, `-444,0+444,2`

### D332 tests/test_agent_state_reliability.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9de78f6d29c2e708598665ebd9889d542d93b0cb`; original `100644:11e301fc4f8431cd20e6a786bef00678f3f776d1`; pinned-current `100644:ecc9fac021fbc76955a892b216985cb2a99da531`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-26,0+26,2`
- A | test_memory_expiration_and_reap: `-35,1+37,1`, `-42,1+44,1`, `-50,1+52,1`
- L | test_task_heartbeat_and_extended_reap: `-91,1+93,2`, `-101,1+104,1`, `-104,1+107,1`, `-108,1+111,1`, `-124,1+129,1`
- U | test_task_heartbeat_and_extended_reap: `-112,1+115,1`, `-115,0+118,2`

### D333 tests/test_agent_state_reliability.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9de78f6d29c2e708598665ebd9889d542d93b0cb`; original `100644:4e1b591d424755681d9a8e14a4b6b45bddb868eb`; pinned-current `100644:ecc9fac021fbc76955a892b216985cb2a99da531`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-20,0+20,1`
- L | test_task_heartbeat_and_extended_reap: `-91,1+92,2`, `-101,1+103,1`, `-104,1+106,1`, `-108,1+110,1`, `-124,1+127,1`
- U | test_task_heartbeat_and_extended_reap: `-112,1+114,1`, `-115,0+117,1`

### D334 tests/test_agent_state_reliability.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9de78f6d29c2e708598665ebd9889d542d93b0cb`; original `100644:ebf7e33089d864055514210c305afb62b5836472`; pinned-current `100644:ecc9fac021fbc76955a892b216985cb2a99da531`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_event_store_schema_and_publish_overflow: `-192,1+192,1`, `-197,3+197,10`

### D335 tests/test_agent_state_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d66e2f25160044760f9e333295a5902672137e31`; original `100644:0664b12178500049b53278ad0d2e5ac476e9ea23`; pinned-current `100644:793c6916c7e7ab6b9fbb3fa1fae502c8db8f98e3`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-597,0+597,52`
- L | <module/text>: `-935,0+987,61`

### D336 tests/test_agent_state_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d66e2f25160044760f9e333295a5902672137e31`; original `100644:697cf20d6ad7e5235f00c3a666462c467e136c71`; pinned-current `100644:793c6916c7e7ab6b9fbb3fa1fae502c8db8f98e3`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | running_app_client: `-42,1+42,1`
- L | test_http_memory_get_is_scope_and_root_isolated: `-416,0+416,1`, `-465,0+466,19`
- U | test_http_memory_get_is_scope_and_root_isolated: `-588,0+608,41`

### D337 tests/test_agent_state_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d66e2f25160044760f9e333295a5902672137e31`; original `100644:be0e69a424b869c415b5ae18e9f7b3a70dd0d6ef`; pinned-current `100644:793c6916c7e7ab6b9fbb3fa1fae502c8db8f98e3`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | running_app_client: `-42,1+42,1`
- L | <module/text>: `-52,0+52,45`, `-935,0+1000,61`
- L | test_http_memory_get_is_scope_and_root_isolated: `-419,0+464,1`, `-465,0+511,19`

### D338 tests/test_agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:088308fb45a0b2ea15e32816af34864e34e5803b`; original `100644:8338ef80d444094c65539d750c91ade487b93916`; pinned-current `100644:a7c9fae0b2cf1876583e3ef103e84163fa039da6`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,3`, `-40,0+44,2`, `-126,2+132,220`
- L | <module/text>: `-7,1+10,2`, `-221,0+482,353`
- A | test_expired_active_task_becomes_abandoned_with_checkpoint: `-135,1+359,1`
- L | test_resume_abandoned_task: `-144,2+368,8`, `-147,1+377,20`
- U | test_resume_abandoned_task: `-151,0+400,12`

### D339 tests/test_agent_tasks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7b65159b4939341f51329e9c6ea943314272fcaa`; original `100644:d9bf99d40c098da8dcc857082802359bf28d5ef5`; pinned-current `100644:a7c9fae0b2cf1876583e3ef103e84163fa039da6`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-20,0+24,2`
- U | <module/text>: `-5,0+6,3`, `-7,1+11,1`, `-38,0+44,55`, `-78,0+139,183`, `-98,2+381,350`
- L | test_completed_succeeds_when_verified: `-86,1+330,4`
- U | test_completed_succeeds_when_verified: `-90,0+337,10`, `-92,1+349,3`, `-94,0+353,24`
- A | test_expired_active_task_becomes_abandoned_with_checkpoint: `-107,1+738,5`
- U | test_resume_abandoned_task: `-116,2+751,11`, `-119,1+763,5`, `-123,0+771,17`

### D340 tests/test_agent_verification.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:74d493741e56348471b03a90d98a82e173a15605`; original `100644:ff0dca520808e832b07357d4b1d08b1abe3e716c`; pinned-current `100644:69c25af0507c40d672b24d5bee5923feda4e7e27`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-43,0+43,52`
- L | <module/text>: `-96,0+148,16`

### D341 tests/test_agent_verification.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fc3d07736bba7eeb6202e6b0408f73195fe89e11`; original `100644:60132d02ef5f0348c6290586052ee26315662d3e`; pinned-current `100644:69c25af0507c40d672b24d5bee5923feda4e7e27`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,6`, `-10,1+16,1`, `-17,0+23,1`, `-468,0+498,1378`
- A | receipt_for: `-44,0+51,2`, `-47,2+56,1`, `-51,1+59,1`, `-58,1+66,1`, `-61,1+69,1`, `-68,1+76,1`, `-76,1+84,1`
- A | test_generic_benchmark_receipt_without_project_binding_satisfies_completion: `-102,0+110,22`

### D342 tests/test_all_advanced_improvements.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bccf2b98ed0ce542c810782f82185f03fef88ce7`; original `100644:63be4a974dd056c8ec0a32194ee06dcaf12dd6f3`; pinned-current `100644:36a66d0ee36099adb82bb1f0146ea2fe5c13e8c6`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-16,0+16,1`
- U | test_zombie_task_watchdog_and_recovery: `-59,1+60,3`, `-67,1+70,3`

### D343 tests/test_all_advanced_improvements.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bccf2b98ed0ce542c810782f82185f03fef88ce7`; original `100644:86a46bf7d2fa8e1f19e3e41ce138679c2c18f7ae`; pinned-current `100644:36a66d0ee36099adb82bb1f0146ea2fe5c13e8c6`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-20,0+20,2`
- A | test_zombie_task_watchdog_and_recovery: `-59,1+61,5`, `-67,1+73,1`
- A | test_auto_worktree_task_lifecycle: `-103,1+109,1`

### D344 tests/test_all_advanced_improvements.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bccf2b98ed0ce542c810782f82185f03fef88ce7`; original `100644:d937004a4b633468fdf5d8e50ac23f94c0309065`; pinned-current `100644:36a66d0ee36099adb82bb1f0146ea2fe5c13e8c6`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_auto_worktree_task_lifecycle: `-103,1+103,1`

### D345 tests/test_all_categories_expanded.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:18dc325c845ca0699047fceb8a03b56ebdcd3f39`; original `100644:31ac69a4704aa8671db62186f2fb9aa35dc9e7f4`; pinned-current `100644:983d440e6b17c60978a3cdaf9825de3ec2ef7aa7`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-26,0+26,2`
- A | test_curate_training_dataset: `-214,1+216,5`, `-223,1+229,1`

### D346 tests/test_all_categories_expanded.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:18dc325c845ca0699047fceb8a03b56ebdcd3f39`; original `100644:f4867f37523893c183a87a09f052739b67ae33c0`; pinned-current `100644:983d440e6b17c60978a3cdaf9825de3ec2ef7aa7`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-14,0+14,1`
- U | test_curate_training_dataset: `-214,1+215,3`, `-223,1+226,3`

### D347 tests/test_architectural_extensions.py

Disposition: `integrated-current`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:769e883450d6bad1cfc40b1e190e656c7fcebfe9`; original `100644:2bddbb6344d3a72bfb595e486abb5bb92d5c62b1`; pinned-current `100644:2bddbb6344d3a72bfb595e486abb5bb92d5c62b1`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-1,1+1,0`, `-8,1+7,0`
- B | test_command_broker_webhook_replay_bounds_response_body.Response: `-146,1+144,1`
- B | test_command_broker_webhook_replay_bounds_response_body.Response.read: `-149,1+147,1`
- B | test_command_broker_webhook_replay_bounds_response_body.Response.getheaders: `-152,2+150,2`
- B | test_command_broker_webhook_replay_bounds_response_body: `-155,2+153,1`, `-158,2+155,19`, `-165,0+179,1`
- B | test_command_broker_webhook_replay_bounds_error_response_body.Response: `-168,2+183,5`
- B | test_command_broker_webhook_replay_bounds_error_response_body.Response.read: `-173,1+191,1`
- B | test_command_broker_webhook_replay_bounds_error_response_body: `-175,4+193,24`, `-182,1+220,1`

### D348 tests/test_architectural_extensions.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:769e883450d6bad1cfc40b1e190e656c7fcebfe9`; original `100644:b0b4100a61c71824e0aa1a014971641fe5fcb292`; pinned-current `100644:2bddbb6344d3a72bfb595e486abb5bb92d5c62b1`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_command_broker_webhook_replay_bounds_response_body.Response: `-146,1+146,1`
- A | test_command_broker_webhook_replay_bounds_response_body.Response.read: `-149,1+149,1`
- A | test_command_broker_webhook_replay_bounds_response_body.Response.getheaders: `-152,2+152,2`
- A | test_command_broker_webhook_replay_bounds_response_body: `-155,2+155,1`, `-158,2+157,19`, `-165,0+181,1`
- A | test_command_broker_webhook_replay_bounds_error_response_body.Response: `-168,2+185,5`
- A | test_command_broker_webhook_replay_bounds_error_response_body.Response.read: `-173,1+193,1`
- A | test_command_broker_webhook_replay_bounds_error_response_body: `-175,4+195,24`, `-182,1+222,1`

### D349 tests/test_async_coordination_reliability.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e768e1e22513484ad2513b88037ffd38d10431a9`; original `100644:33db64c8bf8354e0974438faa0ffbaab8ec35218`; pinned-current `100644:33db64c8bf8354e0974438faa0ffbaab8ec35218`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_async_jobs_retry_on_execution_failure: `-48,0+48,1`, `-62,1+64,1`, `-70,0+72,1`, `-76,0+79,1`
- B | test_async_jobs_retry_on_execution_failure._fail_first: `-52,0+53,1`
- B | test_async_jobs_tick_reclaims_stuck_running_job: `-106,1+110,1`

### D350 tests/test_async_coordination_reliability.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e768e1e22513484ad2513b88037ffd38d10431a9`; original `100644:7c835ab3eb4ddcaf01bc520a5b3b4f8cb9c92c42`; pinned-current `100644:33db64c8bf8354e0974438faa0ffbaab8ec35218`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_async_jobs_retry_on_execution_failure: `-62,1+62,1`
- U | test_async_jobs_tick_reclaims_stuck_running_job: `-106,1+106,1`, `-113,1+113,1`

### D351 tests/test_async_job_reliability_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:203fb54779dd964cedb9880ea5c1d1efd348f659`; original `100644:c19b565fe052813dfecea80bb37425f1c0338ddb`; pinned-current `100644:e1446406233b4f3c5f754959544f3c04460edc8c`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,2`, `-7,0+9,1`, `-8,0+11,13`, `-156,0+172,1`, `-286,0+312,54`
- U | test_retryable_executor_failure_requeues_only_with_safe_action_identity: `-177,0+194,9`
- U | test_restart_does_not_replay_running_job_without_request_id: `-301,0+381,5`

### D352 tests/test_async_job_reliability_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e15fa3bb45987a11ffec1d15035d88b378565b90`; original `100644:975d6eed9f0356ef6cacc53423b2bc06cccbd910`; pinned-current `100644:e1446406233b4f3c5f754959544f3c04460edc8c`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,4`, `-216,0+271,40`, `-240,0+335,107`
- A | manager_factory: `-37,1+41,1`
- A | manager_factory.create: `-50,0+54,11`
- L | test_retryable_executor_failure_requeues_only_with_request_id: `-158,2+173,5`, `-164,1+182,2`
- U | <module/text>: `-166,0+185,36`
- U | test_unhandled_execution_interruption_requires_caller_request_id: `-171,1+226,1`
- A | test_restart_does_not_replay_running_job_without_request_id: `-195,1+250,1`

### D353 tests/test_async_job_reliability_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e15fa3bb45987a11ffec1d15035d88b378565b90`; original `100644:d1ec7462440e5325e707558f0ff304dbecfafeb0`; pinned-current `100644:e1446406233b4f3c5f754959544f3c04460edc8c`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-240,0+328,31`
- A | manager_factory: `-37,1+38,1`
- A | manager_factory.create: `-50,0+51,11`
- L | test_retryable_executor_failure_requeues_only_with_request_id: `-158,2+170,5`, `-164,1+179,2`, `-166,0+182,1`
- U | test_retryable_executor_failure_requeues_only_with_request_id: `-170,0+187,5`
- L | <module/text>: `-177,0+199,66`

### D354 tests/test_async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4b036279db9b5b54fec534bc70fd670ffc008c7a`; original `100644:314d814694331b0a72e3e2f4db22b998a03e0649`; pinned-current `100644:97ef49a6d2b887009df5bb368abde95df5731507`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-320,0+320,41`

### D355 tests/test_async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4b036279db9b5b54fec534bc70fd670ffc008c7a`; original `100644:c4e52cbeb070953b2902f53c9bb3fcc61f80b7c6`; pinned-current `100644:97ef49a6d2b887009df5bb368abde95df5731507`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-8,0+9,1`, `-58,13+60,37`, `-245,0+278,61`, `-440,0+608,30`
- A | test_async_jobs_rejects_non_current_schema_without_deleting_rows: `-49,1+51,1`
- A | test_recovery_requeues_persisted_job_once: `-148,0+174,5`, `-152,1+183,1`, `-158,0+189,1`
- L | test_recovered_async_job_reopens_terminal_trace: `-212,1+244,1`, `-229,1+261,1`, `-235,0+267,1`
- A | test_async_jobs_tick_evicts_terminal_events: `-249,1+343,1`, `-252,1+346,1`
- U | <module/text>: `-316,0+410,74`

### D356 tests/test_async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 38:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4b036279db9b5b54fec534bc70fd670ffc008c7a`; original `100644:ee96e0b7bd41f8089da65b8ba61f545bee840b0d`; pinned-current `100644:97ef49a6d2b887009df5bb368abde95df5731507`.

Exact checkpoint/owner witnesses: `S002 / 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_recovery_requeues_persisted_job_once: `-152,1+152,1`
- U | <module/text>: `-158,0+158,22`
- U | test_recovered_async_job_reopens_terminal_trace: `-225,1+247,1`, `-229,1+251,1`
- U | test_async_jobs_tick_evicts_terminal_events: `-249,1+271,1`
- L | <module/text>: `-426,0+448,29`

### D357 tests/test_async_jobs.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ccd67c5f70624a421d042f96cf521945b78f235f`; original `100644:d2a893f7be6f75f66646ce0b26029a7333d4c68d`; pinned-current `100644:97ef49a6d2b887009df5bb368abde95df5731507`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-7,0+8,1`, `-8,0+10,2`, `-37,0+41,32`, `-46,0+82,188`, `-83,13+307,45`, `-639,0+895,181`, `-857,0+1294,765`
- U | test_async_jobs_rejects_unknown_schema_without_modifying_database: `-74,1+298,1`
- U | test_submit_returns_before_slow_async_execution: `-196,1+452,1`

### D358 tests/test_async_jobs_tasks.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:629328f7b4f025d1f45ea5db22645296a4f7909d`; original `100644:19ae8b54e9a5a8f1d8ef94327bab3f27ce1116e0`; pinned-current `100644:19ae8b54e9a5a8f1d8ef94327bab3f27ce1116e0`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-74,0+74,32`

### D359 tests/test_audit_fixes.py

Disposition: `integrated-current`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:aeb73441fe3e308d319b47a19cd2234909c39da7`; original `100644:b5579acbbbf2016a76762ea90f64ab64ce17646f`; pinned-current `100644:b5579acbbbf2016a76762ea90f64ab64ce17646f`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_daemon_pruning_on_capacity: `-117,0+117,1`, `-125,0+126,2`, `-134,1+137,1`

### D360 tests/test_audit_round2_enhancements.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:eac894a7510f3b027b99140dffddaf08fa293200`; original `100644:14201007ba23d8eb6dbc7648500538021bdda371`; pinned-current `100644:892b50a6423637015494566277624efdd2856512`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_swarm_pubsub_publish_appends_to_state_store: `-65,1+65,1`

### D361 tests/test_audit_round2_enhancements.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:eac894a7510f3b027b99140dffddaf08fa293200`; original `100644:6f8782b64da33b43414894cafd1206205727868b`; pinned-current `100644:892b50a6423637015494566277624efdd2856512`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_memory_cascade_delete_and_compact_linking: `-98,2+98,14`, `-107,1+119,5`

### D362 tests/test_auto_fix_repair_loop.py

Disposition: `integrated-current`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:affa5acfb53d5127ec7e051895b32f471ec59ada`; original `100644:8ce2fb0ad730c4e97700026dd3739ee827ef5caf`; pinned-current `100644:8ce2fb0ad730c4e97700026dd3739ee827ef5caf`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-5,0+5,1`, `-8,0+9,1`, `-15,0+17,1`, `-53,0+58,48`, `-164,0+273,112`
- B | make_broker: `-47,0+50,2`
- B | test_repair_loop_already_passing: `-55,1+108,9`
- B | test_repair_loop_successful_fix: `-63,4+124,4`, `-68,0+129,1`, `-76,1+138,4`
- B | test_repair_loop_rollback_on_failure: `-99,1+164,0`, `-103,1+167,5`, `-116,1+184,5`
- B | test_repair_loop_does_not_dispatch_local_diagnosis_for_arbitrary_interpreter: `-126,2+198,9`, `-134,1+213,1`, `-137,0+216,1`, `-138,0+218,1`, `-141,1+222,3`
- B | test_command_run_auto_fix_flag: `-145,1+228,1`, `-147,1+230,6`, `-153,0+241,2`, `-160,1+250,20`

### D363 tests/test_auto_negative_knowledge.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:970ab53e8728547864488074c36cb4ec84ef5938`; original `100644:62c30081a84b693eac0bd2e2874bce084762595f`; pinned-current `100644:62c30081a84b693eac0bd2e2874bce084762595f`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_find_negative_knowledge_by_query: `-48,1+48,3`, `-55,0+57,2`, `-56,1+60,1`
- B | test_command_broker_skips_unscoped_known_pitfalls: `-61,1+65,1`, `-81,2+85,1`

### D364 tests/test_auto_negative_knowledge.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:970ab53e8728547864488074c36cb4ec84ef5938`; original `100644:8488f0b2eede6cabf90be6ee152bf8deb8d5ed66`; pinned-current `100644:62c30081a84b693eac0bd2e2874bce084762595f`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_find_negative_knowledge_by_query: `-48,1+48,3`, `-55,0+57,2`, `-56,1+60,1`
- A | test_command_broker_skips_unscoped_known_pitfalls: `-61,1+65,1`, `-81,2+85,1`

### D365 tests/test_auxiliary_action_policy.py

Disposition: `integrated-current`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9d6b2c92d81db0072a49ed45e8c72e6f2922295f`; original `100644:f2577ff0f92403113419842d6ac9a120a1d5b7ee`; pinned-current `100644:f2577ff0f92403113419842d6ac9a120a1d5b7ee`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-11,0+11,1`, `-14,0+15,1`, `-29,0+31,1`, `-121,0+131,126`
- B | test_command_spawn_daemon_forwards_task_id_separately_from_name.Broker: `-91,0+94,7`

### D366 tests/test_browser_bridge.py

Disposition: `preserved-only-needs-integration`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e39aaa23eefe43cf3480dae49fcd20fe32e9210c`; original `100644:97061b8fcd9de1255bb81a012db1164009216fb5`; pinned-current `100644:6bae8c96969fb3d3d8cc30dc67dc3d2bdd6adb2c`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-333,0+333,50`
- U | <module/text>: `-426,0+476,43`

### D367 tests/test_browser_bridge.py

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e39aaa23eefe43cf3480dae49fcd20fe32e9210c`; original `100644:de6167a8c50c952a547acfac0629a50af6dab506`; pinned-current `100644:6bae8c96969fb3d3d8cc30dc67dc3d2bdd6adb2c`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-333,0+333,50`
- U | <module/text>: `-426,0+476,43`

### D368 tests/test_browser_bridge_background.js

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ecaf0bc65186f1f626e1fd9c01de54eeaeb20756`; original `100644:68f485fb727c08c74d47cb8132307bd63aabe0ea`; pinned-current `100644:671efd5480e4ea6863abcf3e5a631b2de7e691bd`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-32,0+32,2`, `-52,1+73,1`
- U | <module/text>: `-46,0+48,1`, `-48,1+51,19`, `-85,0+106,38`

### D369 tests/test_browser_bridge_background.js

Disposition: `preserved-only-needs-integration`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ecaf0bc65186f1f626e1fd9c01de54eeaeb20756`; original `100644:b27aac96d4e4598ac43b449eac63b354ba9f587b`; pinned-current `100644:671efd5480e4ea6863abcf3e5a631b2de7e691bd`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-32,0+32,2`, `-52,1+79,1`
- U | <module/text>: `-46,0+48,1`, `-48,1+51,25`, `-85,0+112,44`

### D370 tests/test_browser_bridge_runtime.py

Disposition: `integrated-current`. Occurrences: 0:T/M, 7:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ab057f17a547307acf5f05f070a85606cd1efaf8`; original `100644:d830c82ef99cc30b72bf5ae4950d8e7fb9cbe9ad`; pinned-current `100644:d830c82ef99cc30b72bf5ae4950d8e7fb9cbe9ad`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_actual_current_tab_fixture_preserves_login_and_never_falls_back: `-26,1+26,1`

### D371 tests/test_bundle_import_recovery.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e231d1bc0bd64196ba76c56e64d23aa9ca602653`; original `100644:f46cc25175e72212ac8eec7b7bf9a840cbd54203`; pinned-current `100644:f46cc25175e72212ac8eec7b7bf9a840cbd54203`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | _source_bundle: `-72,4+72,16`, `-77,2+89,0`, `-81,0+91,1`, `-82,0+93,10`
- B | <module/text>: `-85,0+106,10`
- B | test_agent_state_bundle_recovers_after_partial_memory_commit: `-300,0+331,3`, `-301,4+335,13`, `-306,3+349,6`
- B | test_agent_state_initial_journal_failure_reports_no_pending_recovery: `-466,0+512,3`, `-467,0+516,2`, `-468,1+519,4`, `-471,1+525,6`

### D372 tests/test_client_startup_resilience.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c5fe2e0e9e15e3cc7e16fff8aad9ac6fd40d711d`; original `100644:6c3ff59e78e6d95f281cc3cc2e0a4d55993c0952`; pinned-current `100644:6c3ff59e78e6d95f281cc3cc2e0a4d55993c0952`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-171,0+171,20`

### D373 tests/test_client_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:30cb3b0ecee9e4236bc69871055795e8572bb543`; original `100644:0bbf33f6a7d3b6596d83fa16c7c6ed1e206c7120`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-252,0+254,43`
- A | test_client_replays_explicitly_safe_post_with_stable_request_id: `-200,0+201,1`

### D374 tests/test_client_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:30cb3b0ecee9e4236bc69871055795e8572bb543`; original `100644:21349ffe7c560c6a37431d44be67ebbf95d123ef`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`

### D375 tests/test_client_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:30cb3b0ecee9e4236bc69871055795e8572bb543`; original `100644:c3c9e9b9dffe97070e0f3a408ed96eafa5c9db36`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-8,0+8,1`
- U | <module/text>: `-21,0+22,101`

### D376 tests/test_client_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:30cb3b0ecee9e4236bc69871055795e8572bb543`; original `100644:cb40e60f6daba5949484cdcea89cda47f9aa3958`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`
- L | <module/text>: `-639,0+640,104`

### D377 tests/test_client_transport.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:67c4b50af2ff8a82e3f9e2d1ac81d09f01d235ee`; original `100644:fa13ced10577100512fea23abf6ce43d9c9ae418`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-95,0+95,123`

### D378 tests/test_client_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:87d78946c7dec5c7a262ffea1a7f0b73bd03aac8`; original `100644:35963d258a7e6534d1d4e230f7273958a2009f9b`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,4`, `-5,0+9,1`, `-163,0+274,17`
- U | <module/text>: `-106,0+111,106`, `-277,0+406,191`
- A | test_client_replays_duplicate_request_until_owner_finishes: `-157,1+268,1`
- A | test_client_replays_explicitly_safe_post_with_stable_request_id: `-225,0+353,1`
- A | test_stream_events_cancel_event_closes_blocked_response: `-445,0+765,1`

### D379 tests/test_client_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 31:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:87d78946c7dec5c7a262ffea1a7f0b73bd03aac8`; original `100644:60be62ccef19a25dd8e9a752a33e8e090f950c22`; pinned-current `100644:1c1bc0bf50e9d06854fbeb443db647c992c291fc`.

Exact checkpoint/owner witnesses: `S047 / b81b75a784f7bed45745bb709ba15d4bc018911b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`

### D380 tests/test_cloud_model_accelerators.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7925eeb63da92f233a4c3bbb5fd560023bf44e68`; original `100644:32c48e36d41f95dd27616815b04191aa5f18cc41`; pinned-current `100644:7cf3c46987c81143471a51d15925646b56c775cf`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,0+7,1`, `-13,0+14,1`, `-17,0+19,46`
- A | test_patch_and_verify_clean_success: `-150,1+198,1`, `-174,0+222,1`, `-180,1+229,1`
- A | test_patch_and_verify_syntax_error_rollback: `-190,1+239,1`, `-211,0+260,1`, `-216,0+266,1`
- A | test_patch_and_verify_test_failure_rollback: `-227,1+278,1`, `-252,0+303,1`, `-257,0+309,1`
- A | test_patch_and_verify_auto_affected_tests: `-428,1+481,1`, `-444,0+497,1`, `-459,0+513,1`

### D381 tests/test_cloud_model_accelerators.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7925eeb63da92f233a4c3bbb5fd560023bf44e68`; original `100644:b427a2a67df0ecd19b5cea202e0db26015c448d6`; pinned-current `100644:7cf3c46987c81143471a51d15925646b56c775cf`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_task_scaffold: `-287,0+287,1`

### D382 tests/test_codegraph_package_policy.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3ca5f9e552b0397f6c6fac2c59a5cc6f69a09a3b`; original `100644:cd62a94a45810909341b638619d71a2a231f0f8d`; pinned-current `100644:b41b6dedac5b0ff66284c4a2484fba1533e7dcb3`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_runtime_has_no_managed_codegraph_or_kuzu_references: `-60,1+60,4`
- L | <module/text>: `-71,0+74,36`

### D383 tests/test_codegraph_package_policy.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c89bf4c6de3425e7b46707de03a3543c6bc9c411`; original `100644:7da187c62a1579bdee631ce1322a1afabf409d29`; pinned-current `100644:b41b6dedac5b0ff66284c4a2484fba1533e7dcb3`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_codegraph_removed_from_configs_and_features: `-30,1+30,1`
- U | test_codegraph_removed_from_configs_and_features: `-41,4+41,4`

### D384 tests/test_command_rollback.py

Disposition: `preserved-only-needs-integration`. Occurrences: 28:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff369852e95ca752d30905f5e31e8c0e9f1d33ea`; original `100644:3b554fad3a8f023762df27c9dd12f957b13fb5c2`; pinned-current `100644:dea3d43189081f9bf23b6acba40bde387db1f192`.

Exact checkpoint/owner witnesses: `S060 / f8deb79389c263ccff9d0b961bf0017791fd9570 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-27,0+27,55`

### D385 tests/test_command_rollback.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff369852e95ca752d30905f5e31e8c0e9f1d33ea`; original `100644:72bc86e0ea4bca93b41d7fff7396c6efc1ec8d83`; pinned-current `100644:dea3d43189081f9bf23b6acba40bde387db1f192`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`, `-12,0+13,1`, `-28,0+62,8`
- A | _FakeTaskStore.__init__: `-15,1+17,7`, `-17,0+25,23`
- A | _FakeTaskStore.get: `-23,1+54,4`
- A | test_command_rollback_on_failure_preserves_unowned_changes: `-29,1+71,0`, `-38,1+79,0`, `-50,1+90,5`, `-52,1+96,0`, `-62,5+110,2`, `-68,1+113,1`, `-78,2+123,6`
- A | test_command_rollback_on_failure_preserves_unowned_changes.execute_in_private_tree: `-54,3+97,8`, `-60,1+108,1`
- L | <module/text>: `-85,0+134,522`, `-102,0+674,200`, `-146,0+919,319`, `-207,0+1300,69`, `-248,8+1414,0`, `-257,2+1415,263`, `-288,1+1708,147`, `-301,0+1869,116`, `-404,0+2099,187`, `-514,0+2396,335`
- A | test_command_rollback_requires_explicit_scope: `-95,0+666,1`, `-99,1+671,1`
- A | test_patch_and_verify_rollback_preserves_concurrent_foreign_changes: `-126,0+898,1`
- A | test_patch_and_verify_rejects_symlink_write_path: `-163,0+1255,1`
- A | test_rollback_snapshot_does_not_change_file_access_time: `-245,2+1407,6`
- A | test_command_rollback_rejects_path_escape: `-272,0+1691,1`
- A | test_command_rollback_rejects_nested_path_traversal: `-291,0+1857,1`, `-296,0+1863,1`, `-297,1+1865,1`
- A | test_command_rollback_rejects_hardlinks: `-311,0+1995,2`, `-316,0+2002,1`
- A | test_command_rollback_preserves_filesystem_security_metadata: `-358,10+2045,6`, `-369,10+2052,11`
- A | test_command_rollback_runs_when_execution_raises_timeout: `-384,1+2068,5`, `-386,0+2074,2`, `-393,1+2083,1`, `-397,0+2087,1`, `-401,2+2092,6`
- A | test_command_rollback_runs_when_execution_raises_timeout.timeout_after_write: `-387,2+2077,2`

### D386 tests/test_command_rollback.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff369852e95ca752d30905f5e31e8c0e9f1d33ea`; original `100644:8227cadf8de3bc667beaea48e99274cd1271580d`; pinned-current `100644:dea3d43189081f9bf23b6acba40bde387db1f192`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-5,0+6,1`, `-28,0+80,13`, `-102,0+743,200`, `-207,0+1373,69`, `-248,8+1487,0`, `-257,2+1488,263`, `-288,1+1781,147`, `-301,0+1942,116`
- U | <module/text>: `-11,0+13,1`, `-14,0+17,17`, `-85,0+158,567`, `-144,0+987,323`, `-404,0+2172,189`, `-514,0+2471,217`
- A | _FakeTaskStore.__init__: `-15,1+35,7`, `-17,0+43,23`
- A | _FakeTaskStore.get: `-23,1+72,4`
- L | test_command_rollback_on_failure_preserves_unowned_changes: `-29,1+94,0`, `-38,1+102,0`, `-50,1+113,5`, `-52,1+119,0`, `-68,1+137,1`, `-78,2+147,6`
- A | test_command_rollback_on_failure_preserves_unowned_changes.execute_in_private_tree: `-54,3+120,8`, `-60,1+131,1`
- U | test_command_rollback_on_failure_preserves_unowned_changes: `-62,5+133,3`
- A | test_command_rollback_requires_explicit_scope: `-95,0+735,1`, `-99,1+740,1`
- U | test_patch_and_verify_rollback_preserves_concurrent_foreign_changes: `-126,0+967,2`
- A | test_rollback_snapshot_does_not_change_file_access_time: `-245,2+1480,6`
- A | test_command_rollback_rejects_path_escape: `-272,0+1764,1`
- A | test_command_rollback_rejects_nested_path_traversal: `-291,0+1930,1`, `-296,0+1936,1`, `-297,1+1938,1`
- U | test_command_rollback_rejects_hardlinks: `-311,0+2068,1`
- L | test_command_rollback_rejects_hardlinks: `-316,0+2074,1`
- A | test_command_rollback_preserves_filesystem_security_metadata: `-358,10+2117,6`, `-369,10+2124,11`
- U | test_command_rollback_runs_when_execution_raises_timeout: `-384,1+2140,5`, `-386,0+2146,3`
- A | test_command_rollback_runs_when_execution_raises_timeout.timeout_after_write: `-387,2+2150,2`
- L | test_command_rollback_runs_when_execution_raises_timeout: `-393,1+2156,1`, `-397,0+2160,1`, `-401,2+2165,6`

### D387 tests/test_command_timeout_cache_contract.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b979a6347741c60f1e4b93efa1d6dfa053732a89`; original `100644:6d290456c49baf04a79dcab21fc274c101c0ae89`; pinned-current `100644:7f53fc784fe430c38a983cb641992e07c977fa99`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-2,0+2,3`, `-8,1+11,1`, `-48,0+52,70`
- A | test_timeout_and_cancelled_repeatable_commands_are_not_cached.execute: `-27,1+30,1`, `-34,0+37,1`

### D388 tests/test_command_timeout_cache_contract.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b979a6347741c60f1e4b93efa1d6dfa053732a89`; original `100644:a4fde267edfcd58f4652ee1d193779ba20e9cb7c`; pinned-current `100644:7f53fc784fe430c38a983cb641992e07c977fa99`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-2,0+2,3`, `-8,1+11,1`, `-48,0+52,70`
- L | test_timeout_and_cancelled_repeatable_commands_are_not_cached.execute: `-34,0+37,1`

### D389 tests/test_command_unblocked.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9f9ec861d15c6b4d67fa63a619ee7b1314df990c`; original `100644:172f02cb68f6aa021673994ab9de5cb2dce8779b`; pinned-current `100644:b9029f0f804315fb80ac9d06454a5e468f81a8e5`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-6,0+7,2`, `-7,0+10,1`
- L | <module/text>: `-17,0+21,39`
- A | test_mutating_command_bypasses_existing_singleflight: `-48,0+91,1`, `-62,1+106,1`
- A | test_concurrent_mutating_commands_keep_separate_active_entries: `-80,0+124,1`, `-96,1+141,8`
- A | test_concurrent_mutating_commands_require_exact_execution_id_for_cancel: `-124,0+176,1`, `-141,1+194,8`
- A | test_execution_id_cannot_cross_cancel_same_prefix_tenant: `-176,0+236,1`, `-188,1+249,5`
- A | test_mutating_policy_block_is_not_suppressed: `-241,0+306,1`, `-242,2+308,2`
- A | test_docker_sandbox_mutation_is_not_suppressed: `-260,0+326,1`, `-262,2+329,2`

### D390 tests/test_command_unblocked.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9f9ec861d15c6b4d67fa63a619ee7b1314df990c`; original `100644:5ff93db61cfc64ed6a69a5ed1b50b8375e6a6705`; pinned-current `100644:b9029f0f804315fb80ac9d06454a5e468f81a8e5`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-6,0+7,2`, `-7,0+10,1`, `-17,0+21,39`
- L | test_mutating_command_bypasses_existing_singleflight: `-48,0+91,1`
- U | test_mutating_command_bypasses_existing_singleflight: `-62,1+106,1`
- L | test_concurrent_mutating_commands_keep_separate_active_entries: `-80,0+124,1`
- U | test_concurrent_mutating_commands_keep_separate_active_entries: `-96,1+141,8`
- L | test_concurrent_mutating_commands_require_exact_execution_id_for_cancel: `-124,0+176,1`
- U | test_concurrent_mutating_commands_require_exact_execution_id_for_cancel: `-141,1+194,8`
- L | test_execution_id_cannot_cross_cancel_same_prefix_tenant: `-176,0+236,1`
- U | test_execution_id_cannot_cross_cancel_same_prefix_tenant: `-188,1+249,5`
- A | test_mutating_policy_block_is_not_suppressed: `-241,0+306,1`, `-242,2+308,2`
- A | test_docker_sandbox_mutation_is_not_suppressed: `-260,0+326,1`, `-262,2+329,2`

### D391 tests/test_completion_model_routing.py

Disposition: `integrated-current`. Occurrences: 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:315dfe7aa447e14b2f8928ea7a32d905f805cddc`; original `100644:5ff6420d50943047ae5cdd31e14f086c9f458edf`; pinned-current `100644:5ff6420d50943047ae5cdd31e14f086c9f458edf`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | CaptureRuntime: `-20,0+20,3`
- B | CaptureRuntime.request: `-22,1+25,1`
- B | <module/text>: `-52,0+55,48`

### D392 tests/test_config_hardware.py

Disposition: `integrated-current`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c5d79072fab6320540227b91369927b5c31f2f5c`; original `100644:f23c4a95a9296e0e534087b7569afef2796b7b3d`; pinned-current `100644:f23c4a95a9296e0e534087b7569afef2796b7b3d`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_security_validation_refuses_unconfigured_remote_bind: `-50,1+50,1`
- B | <module/text>: `-54,0+54,5`, `-59,8+64,12`
- B | test_security_validation_requires_token_for_remote: `-55,1+60,1`

### D393 tests/test_context_delivery.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:51619a837b109caa18ad246a860297f748ece181`; original `100644:5699ac11f3c37e4405b4487301379824d55c9114`; pinned-current `100644:622750ee9d32a3f235c1d0370c578a6def5a8c1b`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_taskless_context_pack_cache_identity_includes_tenant: `-422,1+422,1`
- L | <module/text>: `-425,0+425,47`, `-717,0+891,56`
- U | test_context_http_rejects_malformed_max_tokens_and_guard_fields: `-428,1+475,1`, `-463,0+520,29`
- L | test_context_http_rejects_malformed_max_tokens_and_guard_fields: `-438,0+485,10`, `-480,0+566,2`, `-482,0+570,1`, `-484,0+573,1`, `-491,0+581,79`
- A | test_realtime_status_includes_preprocessor_projects_on_light: `-576,1+745,1`, `-581,0+750,4`, `-616,0+789,1`
- A | test_context_http_preserves_terminal_pack_failure_with_and_without_task_context: `-861,2+1091,5`

### D394 tests/test_context_delivery.py

Disposition: `preserved-only-needs-integration`. Occurrences: 15:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:51619a837b109caa18ad246a860297f748ece181`; original `100644:b8ff32323abcbf1faa35f96160ac8d1ceb9170fb`; pinned-current `100644:622750ee9d32a3f235c1d0370c578a6def5a8c1b`.

Exact checkpoint/owner witnesses: `S025 / 3b35d5d46e53b8b23a84a27c4e0aaa779290ec1d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_taskless_context_pack_cache_identity_includes_tenant: `-422,1+422,1`
- L | <module/text>: `-425,0+425,47`, `-717,0+1134,56`
- U | test_context_http_rejects_malformed_max_tokens_and_guard_fields: `-428,1+475,1`, `-463,0+520,29`
- L | test_context_http_rejects_malformed_max_tokens_and_guard_fields: `-438,0+485,10`, `-480,0+566,2`, `-482,0+570,1`, `-484,0+573,1`, `-491,0+581,79`
- U | <module/text>: `-574,0+743,243`
- A | test_realtime_status_includes_preprocessor_projects_on_light: `-576,1+988,1`, `-581,0+993,4`, `-616,0+1032,1`
- A | test_context_http_preserves_terminal_pack_failure_with_and_without_task_context: `-861,2+1334,5`

### D395 tests/test_context_delivery.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6fae656ceba9edca5b14f8917c24980445843bcd`; original `100644:a4849a76096397bbfabad5e69fa7f415d085ea83`; pinned-current `100644:622750ee9d32a3f235c1d0370c578a6def5a8c1b`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_context_http_rejects_malformed_max_tokens_and_guard_fields: `-423,0+423,13`
- U | <module/text>: `-650,0+663,106`

### D396 tests/test_context_ledger.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:48d24cef4f87daba0dc6a6f01d705eb1596bc995`; original `100644:f2379aca43899aaf5cc6ac01b199e34792aad505`; pinned-current `100644:f2379aca43899aaf5cc6ac01b199e34792aad505`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,6`, `-4,0+10,2`, `-61,0+69,228`

### D397 tests/test_conversation_continue_route_contract.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24ed89bd6b07f7affdcae56b5dd778233e47add6`; original `100644:3bfbb15c74e1caf332c51c7688f16d5ec17ad27a`; pinned-current `100644:94d65f53e7b516dcebbd0f467b40cda57854ee50`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | production_hub: `-16,0+16,2`, `-21,1+23,2`
- L | <module/text>: `-195,0+198,97`

### D398 tests/test_conversation_continue_route_contract.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:24ed89bd6b07f7affdcae56b5dd778233e47add6`; original `100644:5dbf489a9bdc72cd83a462ac0b3d6d871a9da58d`; pinned-current `100644:94d65f53e7b516dcebbd0f467b40cda57854ee50`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_hub_client_async_job_methods_share_production_route: `-61,1+61,1`, `-91,9+91,5`

### D399 tests/test_conversation_continue_route_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:51da720cb27a204cbfb2e4566700136fef1ee43e`; original `100644:24ed89bd6b07f7affdcae56b5dd778233e47add6`; pinned-current `100644:94d65f53e7b516dcebbd0f467b40cda57854ee50`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-49,0+49,79`

### D400 tests/test_conversations.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3d44d79386f3c8115961e1f386e2a92b0735c39e`; original `100644:e7bd256fd0df111fcb0b54fe5487bac34c3480fe`; pinned-current `100644:f2bf8d788288676d62eaaea0d424079b90d5ad9b`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-52,0+52,59`

### D401 tests/test_conversations.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 20:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b6cd2a95eba000721a57d23c73d6d899012123a`; original `100644:217f3f184207448869b907e054eeb421dadeae94`; pinned-current `100644:f2bf8d788288676d62eaaea0d424079b90d5ad9b`.

Exact checkpoint/owner witnesses: `S071 / 9b1b40906612634df8a0a3bedbb217a337c67cb4 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-275,0+275,14`, `-307,0+321,33`

### D402 tests/test_conversations.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b6cd2a95eba000721a57d23c73d6d899012123a`; original `100644:72127cc4da8e6001e5f9d0cc969b5e0038330500`; pinned-current `100644:f2bf8d788288676d62eaaea0d424079b90d5ad9b`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_service_continues_with_pinned_route_without_persistent_cache: `-114,0+114,2`
- U | <module/text>: `-122,0+124,19`
- L | <module/text>: `-275,0+296,14`, `-307,0+342,33`

### D403 tests/test_daemon_lifecycle_hardening.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5749cf8062c4e4d681b7de8258eed40c3f326fbc`; original `100644:43319982bece7bb5d8532f7e29a047f2052c2085`; pinned-current `100644:7a58dc0707f59ae2ac5659c61ddcbd1ce443ac5f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-78,0+274,26`, `-116,0+479,68`, `-318,2+797,0`
- U | <module/text>: `-45,0+46,195`, `-100,0+322,141`, `-259,1+692,47`, `-388,0+865,32`, `-428,1+947,126`
- A | test_daemon_log_retains_bounded_recent_output: `-142,1+573,1`
- A | test_stop_daemon_does_not_report_success_while_process_is_alive: `-182,0+613,2`, `-191,1+624,1`
- A | test_daemon_accepts_structured_argv_without_shell: `-222,1+655,1`, `-232,1+665,1`
- A | test_stop_daemon_does_not_claim_tree_stopped_when_cleanup_is_unconfirmed: `-239,1+672,1`, `-251,1+684,1`
- A | test_daemon_job_stops_descendants_after_leader_exits: `-277,1+756,1`, `-308,1+787,1`
- A | test_daemon_ttl_retries_unconfirmed_tree_cleanup: `-341,1+818,1`
- A | test_daemon_rejects_implicit_shell_operators: `-358,1+835,1`
- A | test_daemon_ttl_stops_process_and_records_owner: `-362,1+839,1`, `-385,1+862,1`
- A | test_live_daemon_is_reconciled_after_broker_restart: `-389,1+898,1`, `-391,1+900,1`, `-404,2+913,13`, `-407,4+927,3`
- A | test_restart_reconciliation_rejects_pid_reuse: `-412,1+931,1`

### D404 tests/test_daemon_lifecycle_hardening.py

Disposition: `preserved-only-needs-integration`. Occurrences: 28:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5749cf8062c4e4d681b7de8258eed40c3f326fbc`; original `100644:c2fd6e988db3cc3660c445ab4d563df0a775d48f`; pinned-current `100644:7a58dc0707f59ae2ac5659c61ddcbd1ce443ac5f`.

Exact checkpoint/owner witnesses: `S060 / f8deb79389c263ccff9d0b961bf0017791fd9570 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-77,0+77,23`
- L | test_daemon_job_stops_descendants_after_leader_exits: `-277,1+300,1`

### D405 tests/test_daemon_lifecycle_hardening.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5749cf8062c4e4d681b7de8258eed40c3f326fbc`; original `100644:fccdd787f567a6107ce1990abe144cfac0f1b726`; pinned-current `100644:7a58dc0707f59ae2ac5659c61ddcbd1ce443ac5f`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-16,0+17,2`, `-200,0+842,135`
- A | _FakeTaskStore.__init__: `-20,1+23,23`
- A | _FakeTaskStore.get: `-26,0+51,1`, `-27,1+53,1`
- U | <module/text>: `-43,0+69,202`, `-100,0+328,344`, `-116,0+688,68`, `-259,1+1041,153`, `-385,1+1319,196`
- U | test_spawn_daemon_applies_command_policy_before_process_launch: `-110,1+682,1`
- U | test_spawn_daemon_rejects_git_shared_worktree_override_before_launch: `-130,1+770,1`
- L | test_daemon_log_retains_bounded_recent_output: `-151,1+791,0`
- U | test_stop_daemon_does_not_report_success_while_process_is_alive: `-182,0+821,1`
- L | test_stop_daemon_does_not_report_success_while_process_is_alive: `-191,1+831,1`
- A | test_stop_daemon_requires_policy_before_tree_cleanup: `-198,1+838,3`
- A | test_daemon_status_is_observational_and_redacts_sensitive_command_arguments: `-219,0+996,2`
- U | test_daemon_accepts_structured_argv_without_shell: `-232,1+1011,4`
- L | test_stop_daemon_does_not_claim_tree_stopped_when_cleanup_is_unconfirmed: `-251,1+1033,1`
- L | test_daemon_job_stops_descendants_after_leader_exits: `-308,1+1242,1`
- A | test_daemon_ttl_retries_unconfirmed_tree_cleanup: `-341,1+1275,1`
- A | test_daemon_rejects_implicit_shell_operators: `-358,1+1292,1`
- U | test_live_daemon_is_reconciled_after_broker_restart: `-391,1+1520,1`, `-407,2+1547,3`
- L | test_live_daemon_is_reconciled_after_broker_restart: `-404,2+1533,13`
- L | test_restart_reconciliation_rejects_pid_reuse: `-428,1+1569,1`

### D406 tests/test_dashboard_custom_modals.py

Disposition: `integrated-current`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0e96f10a5e94c446c604cc950a377b52f86ed6c1`; original `100644:505dbde1a8bce482582fd9e51f8005d3543ab18e`; pinned-current `100644:505dbde1a8bce482582fd9e51f8005d3543ab18e`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_trace_inspector_polling_guards_stale_responses_and_bounds_client_buffer: `-1001,1+1001,0`, `-1003,2+1002,4`, `-1006,2+1007,2`

### D407 tests/test_dashboard_operational_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0dd501bc020b06c7d6014f8cabc7ef72736712d5`; original `100644:fa40dbb737f81a7dafc5f2a04b6b31283e002fad`; pinned-current `100644:91e6c6a7967861dbee462259899ae21fc13619b7`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_live_events_with_trace_id_link_to_trace_inspector: `-38,1+38,1`
- U | test_live_pollers_skip_overlapping_requests: `-48,2+48,2`, `-51,4+51,4`

### D408 tests/test_dashboard_operational_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7335d73825868691a3a1995403beb981c65f92ec`; original `100644:49883b2abe80c7330622f20adc35e97ac77fe3e1`; pinned-current `100644:91e6c6a7967861dbee462259899ae21fc13619b7`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-1,0+1,1`, `-2,0+3,15`, `-10,0+26,238`, `-55,0+313,74`, `-115,0+447,27`
- U | test_live_pollers_skip_overlapping_requests: `-48,1+302,5`

### D409 tests/test_dashboard_operational_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7335d73825868691a3a1995403beb981c65f92ec`; original `100644:71d98f54fc956840268a91cc219670554a9a24ca`; pinned-current `100644:91e6c6a7967861dbee462259899ae21fc13619b7`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-10,0+10,188`, `-115,0+307,27`
- U | test_live_pollers_skip_overlapping_requests: `-48,1+236,5`

### D410 tests/test_dashboard_polling_quality.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3140bdb1fb4fab067dd160444d964391233689c9`; original `100644:1f6d834539f05fd5158849a30503af93242a0747`; pinned-current `100644:cd531fa744c9f28403bc5ea0bbd12be0ed1ee801`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-11,1+12,3`, `-57,0+60,167`, `-62,0+232,14`
- U | <module/text>: `-269,0+453,32`

### D411 tests/test_dashboard_polling_quality.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5334afa6a54d55e5a9b2c47eaa627c8033b30926`; original `100644:a2c715591c3260d06049b45b0b1d8b6436b1f40d`; pinned-current `100644:cd531fa744c9f28403bc5ea0bbd12be0ed1ee801`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_repeated_status_payload_does_not_trigger_redundant_render_work: `-160,1+160,1`
- A | test_hidden_status_response_cannot_commit_after_visibility_changes: `-178,1+178,1`
- A | test_failed_hardware_poll_retries_for_unchanged_status_until_success: `-199,1+199,1`

### D412 tests/test_dashboard_polling_quality.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a262fb840850825cab23f2f8d2836f2c78272182`; original `100644:27ed2ce4fd561fec4946ecd41d765a534229362a`; pinned-current `100644:cd531fa744c9f28403bc5ea0bbd12be0ed1ee801`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,29`, `-55,0+84,26`
- A | test_repeated_status_payload_does_not_trigger_redundant_render_work: `-109,1+164,1`
- A | test_hidden_status_response_cannot_commit_after_visibility_changes: `-127,1+182,1`
- A | test_failed_hardware_poll_retries_for_unchanged_status_until_success: `-148,1+203,1`

### D413 tests/test_debug_trace_request_summary.py

Disposition: `integrated-current`. Occurrences: 30:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0f6fef509999047168c246146fe5d52fa2d0d247`; original `100644:ebf4085d60acb3824cae3bdc892ab4bb73446653`; pinned-current `100644:ebf4085d60acb3824cae3bdc892ab4bb73446653`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | DebugTraceRequestSummaryTests.test_http_trace_capture_redacts_nested_sensitive_values_and_omits_large_or_binary_data: `-59,1+59,10`, `-64,0+73,3`, `-65,0+77,3`, `-67,0+82,6`

### D414 tests/test_debug_traces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1fb9f509035afb37e2b7b5ece718716b7d9f3e8d`; original `100644:f1e49df3e84b49f79ec4cd8ff19e416ec8fd7f9a`; pinned-current `100644:fba675e1817e2a2f7f4bd8bce1e0a7a3ee1bc2ab`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-5,0+6,3`, `-43,0+47,14`
- A | test_missing_debug_trace_detail_returns_not_found: `-194,0+212,1`
- U | <module/text>: `-198,0+217,12`

### D415 tests/test_debug_traces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1fb9f509035afb37e2b7b5ece718716b7d9f3e8d`; original `100644:fb9e87b438cdc54dc80738135685c196d09d0d77`; pinned-current `100644:fba675e1817e2a2f7f4bd8bce1e0a7a3ee1bc2ab`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-5,0+6,1`, `-44,0+46,14`, `-72,0+88,102`, `-198,0+323,114`
- U | test_missing_debug_trace_detail_returns_not_found: `-178,0+296,2`, `-194,0+314,5`
- U | test_missing_debug_trace_detail_returns_not_found.DebugTraces.detail: `-181,1+301,1`

### D416 tests/test_debug_traces.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:53370aa9873626fcd574c8a528d51f926f9ee2f7`; original `100644:5e02daf93eb7274415ff3caaa9df23bc2ba0aec6`; pinned-current `100644:fba675e1817e2a2f7f4bd8bce1e0a7a3ee1bc2ab`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-220,0+220,39`

### D417 tests/test_delivery_policy.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c46a83c117b466674b92d275438556bc65d3d3a9`; original `100644:67d0837f82093a18723c378f9b4d2954555d89b0`; pinned-current `100644:e61111fa3ba28b3aad893b8125f1ba85527f84c9`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-24,0+24,18`

### D418 tests/test_delivery_policy.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c46a83c117b466674b92d275438556bc65d3d3a9`; original `100644:a0379e1c62a7472466d8ba26dd6dcbb6336fecb2`; pinned-current `100644:e61111fa3ba28b3aad893b8125f1ba85527f84c9`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_install_and_update_prompts_cover_async_and_conversation_contracts: `-55,1+55,1`
- A | test_mcp_task_description_exposes_async_and_conversation_contracts: `-90,1+90,1`

### D419 tests/test_doctor_support.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4442b7003a70413124a926775d7f1fd2623bc7c1`; original `100644:a0b2090fff2db9bdf0f8872706f020fddf8d09dd`; pinned-current `100644:4e3d5918d12a4a2ba530fed1ac37b08ca461128f`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,3`, `-4,0+7,3`
- L | <module/text>: `-36,0+42,21`

### D420 tests/test_evidence_contract.py

Disposition: `integrated-current`. Occurrences: 30:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3f1626b9cbc8a0df3112656d664734388a97b6ad`; original `100644:0d71dc9b28e020cc22cf9949acab720cdcc18cb2`; pinned-current `100644:0d71dc9b28e020cc22cf9949acab720cdcc18cb2`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-1,0+1,6`, `-19,0+25,46`

### D421 tests/test_external_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e0ae070facf277bed401fbf317abf8e9663cd80a`; original `100644:26f5323cd460b8b2f95f4c203be623dde36b1515`; pinned-current `100644:280b3ceb49401145bf8eae292f1f7f901549ee96`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-13,0+13,15`, `-144,11+121,0`, `-157,35+123,0`, `-194,21+125,0`, `-217,20+127,0`, `-239,31+129,0`, `-272,24+131,0`, `-350,30+185,0`, `-413,20+218,0`, `-435,30+220,0`, `-467,16+222,0`, `-559,0+298,14`, `-637,27+360,0`, `-666,43+362,0`
- L | test_serena_index_uses_upstream_per_file_timeout: `-18,1+33,1`
- U | <module/text>: `-36,38+51,0`, `-594,28+347,0`, `-809,2+462,0`
- U | test_serena_tool_error_is_counted_as_backend_failure: `-301,1+136,1`
- U | test_serena_structured_tool_error_is_counted_as_backend_failure: `-327,1+162,1`
- A | test_serena_index_supplies_noninteractive_dominant_language: `-393,1+198,1`
- A | test_transient_circuit_is_isolated_to_failed_root: `-488,1+227,1`
- A | test_index_timeout_is_counted_as_retryable_failure: `-515,1+254,1`
- A | test_root_session_reset_clears_that_roots_circuit: `-547,1+286,1`
- A | test_serena_search_uses_available_symbol_tool_when_pattern_tool_missing: `-583,1+336,1`
- U | test_managed_context_intelligence_defaults_expose_needed_tools: `-630,2+355,0`
- A | test_serena_session_retained_for_one_hour: `-797,1+450,1`

### D422 tests/test_external_tools.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e0ae070facf277bed401fbf317abf8e9663cd80a`; original `100644:8e50c3ac1c388bbc8be10f60b53ccd2442bf65a8`; pinned-current `100644:280b3ceb49401145bf8eae292f1f7f901549ee96`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-13,0+13,15`, `-144,11+121,0`, `-157,35+123,0`, `-194,21+125,0`, `-217,20+127,0`, `-239,31+129,0`, `-272,24+131,0`, `-350,30+185,0`, `-413,20+218,0`, `-435,30+220,0`, `-467,16+222,0`, `-637,27+346,0`, `-666,43+348,0`
- L | test_serena_index_uses_upstream_per_file_timeout: `-18,1+33,1`
- U | <module/text>: `-36,38+51,0`, `-594,28+333,0`, `-809,2+448,0`
- U | test_serena_tool_error_is_counted_as_backend_failure: `-301,1+136,1`
- U | test_serena_structured_tool_error_is_counted_as_backend_failure: `-327,1+162,1`
- A | test_serena_index_supplies_noninteractive_dominant_language: `-393,1+198,1`
- A | test_transient_circuit_is_isolated_to_failed_root: `-488,1+227,1`
- A | test_index_timeout_is_counted_as_retryable_failure: `-515,1+254,1`
- A | test_root_session_reset_clears_that_roots_circuit: `-547,1+286,1`
- A | test_serena_search_uses_available_symbol_tool_when_pattern_tool_missing: `-583,1+322,1`
- U | test_managed_context_intelligence_defaults_expose_needed_tools: `-630,2+341,0`

### D423 tests/test_feature_suite.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:af4d2f044cca00eaba229963f767bb5e0790a0b7`; original `100644:2c69760d702c724992ee331e8959242514e807af`; pinned-current `100644:ad35a84d1635644c12e18d61ca334c0203aabd32`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-6,0+6,1`, `-8,0+9,1`, `-17,0+19,1`
- U | test_command_streaming_and_sse_events: `-157,0+160,22`
- L | test_command_streaming_and_sse_events: `-160,0+185,1`

### D424 tests/test_feature_suite.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:af4d2f044cca00eaba229963f767bb5e0790a0b7`; original `100644:4b4538a76298ec49d0e99025b83e09b6fd14e78d`; pinned-current `100644:ad35a84d1635644c12e18d61ca334c0203aabd32`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-8,0+8,1`
- A | test_command_streaming_and_sse_events: `-157,0+158,13`, `-160,0+174,1`, `-169,1+184,0`, `-171,2+185,3`

### D425 tests/test_feature_surface_parity.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7263f58fe871f4f5a919f6c772e6c5bbe4a9903b`; original `100644:9d30e4421a64a5046fa2269f0b9b24e81603dd4f`; pinned-current `100644:a5bc7134eda2b20b8b73934804037dfc7e47cb43`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_enabled_agent_os_and_tool_actions_are_discoverable: `-87,2+87,8`

### D426 tests/test_features.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:895c55cb4c69d09962f29a50c9660227445894ff`; original `100644:533483eabaf83712e27b03d3e681621d7c6aef3f`; pinned-current `100644:2eb0092f23d535066e5bec69ec002a6f7e21ea65`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | TestFeatureSetDefaults.test_all_on_by_default: `-24,1+24,0`
- L | TestFeatureSetDefaults: `-33,1+32,6`
- L | TestSerenaDisabled: `-40,1+44,1`
- U | <module/text>: `-45,6+49,0`, `-58,1+56,0`
- U | TestSerenaDisabled.test_semantic_hint_when_serena_enabled: `-60,12+57,2`
- A | TestBuildGlobalPolicy.test_semantic_route_absent_without_serena: `-163,3+150,3`
- A | TestRoutingEngineConfigModel.test_config_update_allows_feature_toggles: `-226,0+213,1`, `-229,0+217,1`, `-242,1+232,2`, `-245,1+236,8`
- A | TestRoutingEngineConfigModel.test_config_update_allows_feature_toggles.DummyApp: `-233,0+222,1`

### D427 tests/test_features.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M, 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:895c55cb4c69d09962f29a50c9660227445894ff`; original `100644:d7cebe7aa62ab59c24db7186b2dbae24b905ed57`; pinned-current `100644:2eb0092f23d535066e5bec69ec002a6f7e21ea65`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | TestFeatureSetDefaults.test_all_on_by_default: `-24,1+24,0`
- L | TestFeatureSetDefaults: `-33,1+32,6`
- L | TestSerenaDisabled: `-40,1+44,1`
- U | <module/text>: `-45,6+49,0`, `-58,1+56,0`
- U | TestSerenaDisabled.test_semantic_hint_when_serena_enabled: `-60,12+57,2`
- A | TestBuildGlobalPolicy.test_semantic_route_absent_without_serena: `-163,3+150,3`

### D428 tests/test_frontend_coder_context.py

Disposition: `integrated-current`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:d074368ac46ab94b158c75df59a02a062841933e`; original `100644:e780980c548f798aae2c1c05d4a09234240e205a`; pinned-current `100644:e780980c548f798aae2c1c05d4a09234240e205a`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-4,0+4,18`

### D429 tests/test_frontend_review.py

Disposition: `integrated-current`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7ef5afec760bde8faabb8f2fd27aabb7bfdc70f7`; original `100644:0a819493895fe8b1f29f86a949fdb29fe2d5a5be`; pinned-current `100644:0a819493895fe8b1f29f86a949fdb29fe2d5a5be`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_build_model_context_includes_screenshot_dom_and_prompt: `-34,0+34,6`
- B | <module/text>: `-188,0+194,14`
- B | test_service_passes_screenshot_and_dom_bundle_to_vision_model: `-230,0+250,8`

### D430 tests/test_frontend_review.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7ef5afec760bde8faabb8f2fd27aabb7bfdc70f7`; original `100644:50cb6a00302de1840a7af0e04f7b8d59f177a2f4`; pinned-current `100644:0a819493895fe8b1f29f86a949fdb29fe2d5a5be`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_service_passes_screenshot_and_dom_bundle_to_vision_model: `-230,1+230,9`

### D431 tests/test_http_tool_accounting_rejections.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:25f07284d8d23560ac799976bf1e19bd442d83b4`; original `100644:216bc8f1d5f8696e58e890a718bab93f7c7c2816`; pinned-current `100644:d5e4cfd66c7df548cb022e9cf0ac9972e78fb832`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_tool_accounting_reports_aggregate_rejections_without_exception_details.App: `-13,0+13,1`, `-14,0+15,15`

### D432 tests/test_http_tool_accounting_rejections.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:25f07284d8d23560ac799976bf1e19bd442d83b4`; original `100644:27c604efc349ba406ff1352bac89b858f8cef0dc`; pinned-current `100644:d5e4cfd66c7df548cb022e9cf0ac9972e78fb832`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-2,0+2,1`, `-43,0+51,84`
- A | test_tool_accounting_reports_aggregate_rejections_without_exception_details.Telemetry.record_tool_accounting: `-11,0+12,2`
- L | test_tool_accounting_reports_aggregate_rejections_without_exception_details: `-21,1+24,6`, `-36,2+44,2`

### D433 tests/test_http_tool_accounting_rejections.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:25f07284d8d23560ac799976bf1e19bd442d83b4`; original `100644:45a2bff02b0656f69c4a989033bbf5ffe4be2515`; pinned-current `100644:d5e4cfd66c7df548cb022e9cf0ac9972e78fb832`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_tool_accounting_reports_aggregate_rejections_without_exception_details: `-27,0+27,1`

### D434 tests/test_http_tool_accounting_rejections.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:25f07284d8d23560ac799976bf1e19bd442d83b4`; original `100644:5f66a2ad30fab8e3684c70d146cfb496f11b27f5`; pinned-current `100644:d5e4cfd66c7df548cb022e9cf0ac9972e78fb832`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_tool_accounting_reports_aggregate_rejections_without_exception_details: `-17,0+17,1`, `-43,0+45,1`
- L | test_tool_accounting_reports_aggregate_rejections_without_exception_details: `-27,0+28,1`

### D435 tests/test_http_vision_routes.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7da5340c045abc647b5207a41ddb2a2ef0c58a42`; original `100644:5e5d1ee80dd1d5143cd38fa8b9255b1e037ec61b`; pinned-current `100644:712bee8faecbae63c47e6a247184af770f8250d1`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`
- L | test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped: `-141,0+142,38`
- U | test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped: `-154,0+193,1`
- U | <module/text>: `-159,0+199,114`
- U | test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin: `-221,0+375,1`

### D436 tests/test_http_vision_routes.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7da5340c045abc647b5207a41ddb2a2ef0c58a42`; original `100644:95964fa4662f7f74f6dc9030c39fcce613ea46ee`; pinned-current `100644:712bee8faecbae63c47e6a247184af770f8250d1`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-159,0+202,114`
- U | _post: `-14,1+15,1`
- L | _post: `-22,0+23,2`
- L | test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped: `-141,0+144,38`, `-151,0+192,1`, `-158,0+200,1`
- L | test_token_auth_supports_bridge_and_review_preflight_without_wildcard_origin: `-218,0+375,1`, `-221,1+379,5`

### D437 tests/test_http_vision_routes.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7da5340c045abc647b5207a41ddb2a2ef0c58a42`; original `100644:f88c2626dde59d4123d35f3db4e990df3d3c0a9f`; pinned-current `100644:712bee8faecbae63c47e6a247184af770f8250d1`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | _post: `-14,1+14,1`
- L | test_browser_capability_capture_and_review_routes_are_explicit_and_tenant_scoped: `-45,0+45,2`, `-47,0+49,1`, `-95,1+98,5`

### D438 tests/test_identity_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:27d8228b72294da8a062614354eb2046245984cc`; original `100644:987a9e8fea14cd0c758d4124155e99cfb11d6262`; pinned-current `100644:09da0581096196f78bd48448e147f53d3312b484`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-254,0+254,137`

### D439 tests/test_inprocess_transport.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:93102d27c4a6362815def561e11cdbc8f50ded4c`; original `100644:53692f5f4dc4ea3e5a5594d103943d05b15bd97a`; pinned-current `100644:3279cb6f0854da04aee3e79f37dc1c496c9597c1`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-337,0+337,41`

### D440 tests/test_llama_cpp_routing.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:eb07721f9f796488428a065a45acecf84ae83a3c`; original `100644:e765a0e1d07c79d0d82f222e3f99ec7ab1a2875d`; pinned-current `100644:e765a0e1d07c79d0d82f222e3f99ec7ab1a2875d`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | LlamaCppRoutingTests: `-109,0+109,61`
- B | LlamaCppRoutingTests.test_router_mode_stream_translates_generate_and_chat: `-184,0+245,20`, `-207,1+291,7`
- B | LlamaCppRoutingTests.test_router_mode_stream_translates_generate_and_chat.fake_urlopen: `-200,0+281,3`

### D441 tests/test_logging_setup.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fa56fe222460c5cd62d5d031d7c2fe79ac5f639d`; original `100644:605c2486bf0fa195c4864b406e4bf06ab24252b6`; pinned-current `100644:605c2486bf0fa195c4864b406e4bf06ab24252b6`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-50,0+50,16`

### D442 tests/test_mcp_agent_routing.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:19668fe96367cdbf66ab7efd5816b873a8c615b9`; original `100644:0faef63ef106b3c861462257c31afd07a2f62a79`; pinned-current `100644:068c8b56a17464b84cfdc832b187b1c80a5f1df9`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-13,0+13,1`, `-472,0+473,56`, `-687,0+744,42`, `-754,0+853,86`

### D443 tests/test_mcp_agent_routing.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 20:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:19668fe96367cdbf66ab7efd5816b873a8c615b9`; original `100644:4747acab4419da7a7903df5f7fb9ed51d97b280b`; pinned-current `100644:068c8b56a17464b84cfdc832b187b1c80a5f1df9`.

Exact checkpoint/owner witnesses: `S071 / 9b1b40906612634df8a0a3bedbb217a337c67cb4 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_async_job_controls_bypass_model_execution_gate: `-676,1+676,1`
- L | <module/text>: `-685,0+685,32`
- A | test_async_job_wait_transport_deadline_covers_capped_wait: `-700,1+732,1`

### D444 tests/test_mcp_agent_routing.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce041ee2b6edab32671c877de97490499bf2b007`; original `100644:9f4289addb3f29212b6168687ee8a86cec3f32bc`; pinned-current `100644:068c8b56a17464b84cfdc832b187b1c80a5f1df9`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-264,0+264,27`, `-465,0+492,22`

### D445 tests/test_mcp_agent_routing.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce041ee2b6edab32671c877de97490499bf2b007`; original `100644:c5c0b23fbaaf5dc718bf777a8df2e795c54787ad`; pinned-current `100644:068c8b56a17464b84cfdc832b187b1c80a5f1df9`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-189,0+189,5`

### D446 tests/test_mcp_agent_routing.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce041ee2b6edab32671c877de97490499bf2b007`; original `100644:c620a5c82e99a0a30a7c82856c64439467661eb3`; pinned-current `100644:068c8b56a17464b84cfdc832b187b1c80a5f1df9`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | isolated_profile_catalog: `-24,0+24,2`
- L | <module/text>: `-189,0+191,7`, `-465,0+474,22`
- U | <module/text>: `-660,0+691,32`

### D447 tests/test_mcp_agent_routing.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce041ee2b6edab32671c877de97490499bf2b007`; original `100644:efef9fde235b04f92040b73311e4031721cac816`; pinned-current `100644:068c8b56a17464b84cfdc832b187b1c80a5f1df9`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-537,0+537,33`

### D448 tests/test_mcp_autostart_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2a7145cccaf24603290cd841505f0b5751acd3d4`; original `100644:c44a26f78a02b905091311be5eda2d0d4752dfc5`; pinned-current `100644:6f9bbc21575018954fad5259bd0aa5675fecdb6c`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,16`, `-39,0+56,148`
- U | test_mcp_client_bounds_auto_start_after_daemon_connection_refusal: `-15,1+31,2`, `-32,1+49,1`

### D449 tests/test_mcp_compact_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:25a8306a77f8af0e2b332f77c5c1731b6ea186c5`; original `100644:0339f8ae76c51dddd1c68025bed1a90484ccee02`; pinned-current `100644:310de25593aef9439a2a25e2a681971eebf672da`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-11,0+11,4`
- U | test_local_ai_repo_context_forwards_guarded_pack_fields: `-104,2+108,3`
- U | test_local_ai_repo_non_context_actions_ignore_guard_fields: `-149,0+154,1`, `-159,1+165,4`

### D450 tests/test_mcp_compact_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:53758b4d44581a0db65366e379f5be115f40e1f1`; original `100644:47c6e99d5427891858e1b8031a422dce5693526e`; pinned-current `100644:310de25593aef9439a2a25e2a681971eebf672da`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,1`, `-9,0+10,1`
- L | <module/text>: `-43,0+45,179`

### D451 tests/test_mcp_compact_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:53758b4d44581a0db65366e379f5be115f40e1f1`; original `100644:6053e199dcba7e6c890107d8fc187f792ae2c941`; pinned-current `100644:310de25593aef9439a2a25e2a681971eebf672da`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`, `-9,0+10,1`
- A | _capture_client: `-67,1+69,1`
- A | _capture_client.post: `-71,2+73,3`
- A | test_local_ai_repo_context_forwards_guarded_pack_fields: `-101,0+104,6`, `-104,1+113,1`, `-125,0+134,6`, `-126,2+141,5`
- A | test_local_ai_repo_non_context_actions_ignore_guard_fields: `-143,1+161,1`, `-155,0+173,1`, `-160,1+179,2`
- L | <module/text>: `-342,0+362,28`, `-363,0+411,183`

### D452 tests/test_mcp_compact_transport.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:53758b4d44581a0db65366e379f5be115f40e1f1`; original `100644:afa62228b73335ba1078e4399cace9b2fda6de09`; pinned-current `100644:310de25593aef9439a2a25e2a681971eebf672da`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,2`, `-11,0+13,299`

### D453 tests/test_mcp_contract_dispatch.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6367c3d59f95f5f846a893dd86d816b216f530b1`; original `100644:5e4dd18c615203d7dbd63f5f6e6f6f977d9f9926`; pinned-current `100644:06662c9340d7d1c19582369b37b1bf27b328401d`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,2`, `-50,0+52,30`
- U | <module/text>: `-110,0+142,699`

### D454 tests/test_mcp_response_budget.py

Disposition: `preserved-only-needs-integration`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1e5902baa5e680da9b1acf2bd5ef80324052f9b3`; original `100644:5618a4596fc322541f11cc8a330265065df2da7c`; pinned-current `100644:c4f899b63095490f0b8953eacd12ee4538ffb661`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-79,0+79,51`

### D455 tests/test_mcp_response_budget.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2fb7888012b4902de2c4c42cbe3e5f54b6f104c8`; original `100644:f93a929b5cfc926a0e946fc9dfb117ab769c80de`; pinned-current `100644:c4f899b63095490f0b8953eacd12ee4538ffb661`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_command_rollback_scope_reaches_api_payload: `-34,1+34,1`, `-55,2+55,3`
- A | test_command_rollback_scope_reaches_api_payload.fake_post: `-37,1+37,1`
- U | <module/text>: `-118,0+119,38`
- L | <module/text>: `-135,0+174,26`

### D456 tests/test_missing_and_high_value_features.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce30263c7a7a0d7fb97e4030832da1cf539728a7`; original `100644:ac24ad08684d202de1daa3e8754f5dc31004fa31`; pinned-current `100644:e9d63b6871a0e0c51de655d0566782fa953f20af`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-15,0+15,1`, `-22,0+23,1`
- A | test_command_broker_lint_fix_and_daemon_lifecycle: `-28,2+30,66`, `-32,3+98,4`, `-42,0+109,1`, `-43,1+111,1`, `-50,1+118,1`
- A | test_command_broker_http_probe: `-98,1+166,5`, `-105,1+177,0`
- A | test_process_utils_git_worktree_lifecycle: `-129,1+200,7`

### D457 tests/test_missing_and_high_value_features.py

Disposition: `preserved-only-needs-integration`. Occurrences: 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce30263c7a7a0d7fb97e4030832da1cf539728a7`; original `100644:b0629976bb8de0717c019920e18aabebd1f47144`; pinned-current `100644:e9d63b6871a0e0c51de655d0566782fa953f20af`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_audio_transcription_service_without_whisper_is_not_false_success: `-281,1+281,1`, `-285,0+285,1`, `-300,2+301,4`

### D458 tests/test_missing_and_high_value_features.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce30263c7a7a0d7fb97e4030832da1cf539728a7`; original `100644:f6262a84b8cbae9c2f5fba006d8de2ab7790deb4`; pinned-current `100644:e9d63b6871a0e0c51de655d0566782fa953f20af`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_process_utils_git_worktree_lifecycle: `-129,1+129,7`
- U | test_audio_transcription_service: `-281,1+287,1`, `-283,0+289,2`, `-285,0+293,8`
- L | test_audio_transcription_service: `-302,0+318,1`

### D459 tests/test_model_routing.py

Disposition: `integrated-current`. Occurrences: 42:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:679e53bc806d94a1da3cfa9cebbcec0461984339`; original `100644:103ed7eb23a9ff8702558d908f01e3c286cec89e`; pinned-current `100644:103ed7eb23a9ff8702558d908f01e3c286cec89e`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | ReviewDiffRoutingTests.test_model_override_requires_a_configured_tier: `-44,1+44,1`

### D460 tests/test_mutation_replay.py

Disposition: `preserved-only-needs-integration`. Occurrences: 27:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5aa37cc358125b5ac4c3c3888c517eb2e83c425f`; original `100644:11aa4d77e2869a4b5cc331c2cc747c52a13ac56e`; pinned-current `100644:bf4b98fb8cf230ef5731ab69d0d21bee5e9ef0ce`.

Exact checkpoint/owner witnesses: `S061 / c041d450a685c0c2f225270c7113c075aec585ae / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-31,0+31,69`

### D461 tests/test_mutation_replay.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5aa37cc358125b5ac4c3c3888c517eb2e83c425f`; original `100644:4974464447e407f2b6d11349bc8ac254e5259628`; pinned-current `100644:bf4b98fb8cf230ef5731ab69d0d21bee5e9ef0ce`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-13,0+13,1`
- A | test_post_journal_failure_prevents_mutation_dispatch: `-565,0+566,1`
- A | test_http_retry_replays_outcome_and_rejects_changed_payload: `-598,0+600,1`
- L | test_post_rejects_malformed_request_id_before_mutation_dispatch: `-727,0+730,1`
- U | test_http_partial_publish_failure_replays_without_dispatching_twice: `-819,0+823,1`

### D462 tests/test_mutation_replay.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5aa37cc358125b5ac4c3c3888c517eb2e83c425f`; original `100644:688bdaecad6ca89a39cde5e198eb199678804a12`; pinned-current `100644:bf4b98fb8cf230ef5731ab69d0d21bee5e9ef0ce`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-652,0+652,124`

### D463 tests/test_mutation_replay.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5aa37cc358125b5ac4c3c3888c517eb2e83c425f`; original `100644:9aca89e69e3a3cd5955cc9356e480f254a1b6105`; pinned-current `100644:bf4b98fb8cf230ef5731ab69d0d21bee5e9ef0ce`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-219,0+219,106`, `-590,0+696,40`
- U | <module/text>: `-650,0+796,45`

### D464 tests/test_mutation_replay.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5aa37cc358125b5ac4c3c3888c517eb2e83c425f`; original `100644:e96173de9b9f76b89bd7af4a3bd976ca46105cb1`; pinned-current `100644:bf4b98fb8cf230ef5731ab69d0d21bee5e9ef0ce`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-9,0+9,1`, `-97,0+167,19`, `-281,0+370,29`, `-428,0+547,26`, `-796,0+1076,1`, `-797,0+1078,1`, `-895,0+1179,79`, `-986,0+1349,365`
- U | <module/text>: `-31,0+32,69`, `-652,0+800,126`
- A | test_response_is_journaled_before_a_client_disconnect: `-319,1+437,2`
- A | test_maintenance_get_routes_are_read_only: `-528,1+673,3`, `-545,0+692,1`
- L | test_post_rejects_malformed_request_id_before_mutation_dispatch: `-752,0+1026,3`
- A | test_send_normalizes_http_error_before_journaling_and_serializing: `-785,0+1062,1`, `-789,0+1067,1`, `-790,0+1069,1`
- U | test_http_partial_publish_failure_replays_without_dispatching_twice: `-821,0+1103,1`
- L | test_http_partial_publish_failure_replays_without_dispatching_twice: `-822,0+1105,1`

### D465 tests/test_new_capabilities_and_hardening.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b79663b016262d626323ca7ad98d24b45b9405e2`; original `100644:11662e62db717b21aa194e6830b83aea6b7b8485`; pinned-current `100644:1176d8587270da4a9eee5ca2095f2859dfbda4bc`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,0+12,1`, `-18,0+19,1`
- A | test_13_mock_recorder_and_replayer: `-417,7+419,14`, `-425,1+434,25`, `-428,1+461,4`

### D466 tests/test_new_capabilities_and_hardening.py

Disposition: `preserved-only-needs-integration`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b79663b016262d626323ca7ad98d24b45b9405e2`; original `100644:54604e6978cc555bc4579ff843ea6b22279c07fb`; pinned-current `100644:1176d8587270da4a9eee5ca2095f2859dfbda4bc`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,0+12,1`, `-18,0+19,1`, `-21,1+23,1`
- A | test_8_stash_save_and_restore_requires_task_worktree: `-340,1+342,1`, `-343,1+345,2`, `-346,1+349,2`
- U | test_13_mock_recorder_and_replayer: `-417,7+421,23`
- L | test_13_mock_recorder_and_replayer: `-425,1+445,25`, `-428,1+472,4`

### D467 tests/test_new_capabilities_and_hardening.py

Disposition: `preserved-only-needs-integration`. Occurrences: 12:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b79663b016262d626323ca7ad98d24b45b9405e2`; original `100644:fbd4b59ab1d7102255e74afe9677596d2bc4960b`; pinned-current `100644:1176d8587270da4a9eee5ca2095f2859dfbda4bc`.

Exact checkpoint/owner witnesses: `S081 / 388086357ab954fbf208def00ba1ce5a60170598 / true / fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_13_mock_recorder_and_replayer: `-418,6+418,4`, `-427,0+425,1`

### D468 tests/test_ollama_ownership.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c55ec4cf81e764eb00dde251ed12d4d981ab2ef5`; original `100644:68750d79851e000cc3633fe976ec7509cfc1f9f4`; pinned-current `100644:68750d79851e000cc3633fe976ec7509cfc1f9f4`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_gaming_unload_covers_every_loaded_ollama_model: `-147,0+147,23`

### D469 tests/test_ollama_ownership.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c55ec4cf81e764eb00dde251ed12d4d981ab2ef5`; original `100644:9f6346c82abb001b4e24499aeac4c7ca95cfdb7a`; pinned-current `100644:68750d79851e000cc3633fe976ec7509cfc1f9f4`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-147,0+147,63`

### D470 tests/test_ollama_tracing.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9cf78c3f902b203b6c74073ba0478434b8f5f806`; original `100644:62c5a715309ae5afd99c1c8b5a993a90eca85164`; pinned-current `100644:62c5a715309ae5afd99c1c8b5a993a90eca85164`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_request_stream_aggregates_generate_chunks_and_notifies_callback: `-31,1+31,1`
- B | test_request_stream_separates_thinking_and_ignores_empty_output_chunks: `-47,1+47,1`
- B | test_request_stream_aggregates_chat_content_and_ignores_bad_lines: `-85,1+85,1`

### D471 tests/test_ollama_transport.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:0b8f1518c02086e047851aa38146678a68f88915`; original `100644:76b993b69f25bd84620e6256814f76ef896820be`; pinned-current `100644:76b993b69f25bd84620e6256814f76ef896820be`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-30,1+30,75`, `-38,0+112,7`
- B | _RecordingBody.__init__: `-32,1+106,1`

### D472 tests/test_operation_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ace40835d33cb3c556633817b6c7a490fc9945f4`; original `100644:03706d3bd2c0cd4fe8ace59b80eabc9bb13046fc`; pinned-current `100644:c66764502b4730937c85291b0a180646f560b609`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-6,0+6,2`, `-20,0+22,2`, `-611,0+621,322`, `-810,1+1169,51`
- U | test_repo_search_timeout_respects_120_second_protocol_limit: `-399,1+403,4`, `-403,1+410,4`
- U | test_runtime_validation_enforces_registered_schema_constraints: `-513,2+523,2`
- U | test_action_metadata_exposes_consistent_input_and_output_schemas: `-608,1+618,1`
- L | <module/text>: `-620,0+952,23`
- U | test_mcp_tools_list_publishes_artifact_output_shape_union: `-656,1+1011,1`
- U | test_output_validation_checks_shared_envelope_and_keeps_nested_payloads: `-715,1+1070,1`, `-721,1+1076,1`, `-725,2+1080,6`
- U | test_status_output_contracts_match_brief_and_cache_projections: `-778,1+1137,1`, `-781,1+1140,1`

### D473 tests/test_operational_api_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bb18a3f1a53e9ad544b66cdd105decb7d976458f`; original `100644:2139d7bd5d7c69865714a8a43edb1011c52be2be`; pinned-current `000000:0000000000000000000000000000000000000000`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`, `-43,0+44,761`, `-61,0+823,51`, `-76,0+889,34`, `-110,0+957,37`, `-168,0+1052,126`, `-280,0+1295,30`, `-372,1+1417,37`, `-386,0+1471,5`
- U | test_incident_resolution_rolls_back_when_audit_event_cannot_append: `-187,1+1197,1`, `-189,0+1199,1`
- U | test_admin_action_policy_rejects_wrong_method_and_audits_metadata_only: `-270,1+1281,5`, `-274,1+1289,1`
- U | test_status_action_aliases_match_live_and_generated_schemas: `-375,0+1456,1`, `-379,1+1461,4`, `-383,2+1468,2`

### D474 tests/test_performance.py

Disposition: `integrated-current`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ff7d97b8536ffb6dfc20b32d45a906d5121ab856`; original `100644:34f115254b83dd971a0e6a3f9f24a468c544eaac`; pinned-current `100644:34f115254b83dd971a0e6a3f9f24a468c544eaac`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-6,0+6,1`, `-15,0+16,1`, `-62,0+64,119`, `-180,0+301,16`

### D475 tests/test_preprocessing_overhaul.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:021ebf63c155e064380c802a57a1f205a8f19326`; original `100644:9fe51666ede7b0e8808280ae96cb96cc90cd7566`; pinned-current `100644:73eeeabe26c3233d1cb0c1770f53918836dbcdf9`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_preprocessing_has_no_codegraph_phase: `-128,1+128,1`
- U | <module/text>: `-134,2+134,0`
- L | test_preprocessing_has_no_codegraph_phase: `-174,1+172,1`
- L | <module/text>: `-178,0+176,56`
- A | test_worktree_cache_inheritance: `-257,0+311,2`, `-262,1+318,1`, `-266,1+322,1`, `-289,1+345,1`

### D476 tests/test_preprocessing_overhaul.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:021ebf63c155e064380c802a57a1f205a8f19326`; original `100644:f7c1c77f5d95adaccfb174b549627158021723ed`; pinned-current `100644:73eeeabe26c3233d1cb0c1770f53918836dbcdf9`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_preprocessing_has_no_codegraph_phase: `-128,1+128,1`
- U | <module/text>: `-134,2+134,0`
- L | test_preprocessing_has_no_codegraph_phase: `-174,1+172,1`

### D477 tests/test_preprocessor_and_deterministic.py

Disposition: `integrated-current`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8fd4e9336d5bfa413d800e43aaf961b175659855`; original `100644:3ffc5d03d5a0c2a8014c3bed3e76c77b5325153d`; pinned-current `100644:3ffc5d03d5a0c2a8014c3bed3e76c77b5325153d`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_cached_external_unavailability_is_retried_when_backend_is_available: `-159,1+159,1`, `-164,1+164,1`, `-169,1+169,1`
- B | test_startup_requeues_complete_project_with_available_external_backend: `-193,1+193,1`, `-203,1+203,1`
- B | test_external_index_failure_degrades_and_advances_preprocessing: `-430,1+430,1`
- B | test_external_index_timeout_is_retryable_for_unchanged_revision: `-449,1+449,1`
- B | test_malformed_external_index_response_degrades_and_advances_preprocessing: `-472,1+472,1`, `-476,1+476,1`, `-479,1+479,1`
- B | test_stale_external_project_configuration_is_skipped_once_per_revision: `-501,2+501,2`
- B | test_time_bounded_external_index_retries_after_backoff: `-532,2+532,2`, `-538,1+538,1`, `-541,1+541,1`, `-546,1+546,1`, `-549,1+549,1`
- B | test_available_backend_timeout_is_not_retried_forever: `-571,2+571,2`
- B | test_external_index_publishes_running_state_before_invocation: `-596,1+596,1`
- B | test_force_refresh_retries_cached_external_index: `-622,1+622,1`, `-626,1+626,1`, `-630,1+630,1`
- B | test_force_refresh_requeues_complete_project_from_inventory: `-656,1+656,1`
- B | test_existing_timed_out_external_index_is_retried_after_restart: `-699,1+699,1`
- B | test_external_state_is_preserved_across_restart: `-722,1+722,1`, `-733,1+733,1`

### D478 tests/test_process_utils.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1ae6fc582fe20bc53ade908e901c73caaee423eb`; original `100644:06754b5af467aa685a2a093a84810aa05ae243e5`; pinned-current `100644:afd19d1d84778b451faf774a82ec6d4ef98b31b0`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-299,0+300,43`

### D479 tests/test_process_utils.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1ae6fc582fe20bc53ade908e901c73caaee423eb`; original `100644:37e82fcbccdab533ee8ca28aad95cbe72022c7ca`; pinned-current `100644:afd19d1d84778b451faf774a82ec6d4ef98b31b0`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-266,0+266,94`

### D480 tests/test_process_utils.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 6:T/M, 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1ae6fc582fe20bc53ade908e901c73caaee423eb`; original `100644:6c7fcb28c7f137b0c0658eb87104ec7178fb2213`; pinned-current `100644:afd19d1d84778b451faf774a82ec6d4ef98b31b0`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-195,0+196,43`

### D481 tests/test_production_readiness_repairs.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:5d29bf1f30df44ad90ea18f0b1ff6d6ee0b659c8`; original `100644:36ad15c31182c6e6f58f0d99dc22a83ef1d9be19`; pinned-current `100644:36ad15c31182c6e6f58f0d99dc22a83ef1d9be19`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_memory_record_find_delete_and_restart_round_trip: `-37,0+37,1`, `-39,1+40,1`, `-41,1+42,7`, `-44,1+51,7`, `-46,1+59,7`

### D482 tests/test_project_config.py

Disposition: `preserved-only-needs-integration`. Occurrences: 12:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e56bf7fec7704132c919c79e114fd05dd54dda23`; original `100644:35a00f56c367d82aa17bb5ba65f9d393f2bb8308`; pinned-current `100644:9d4d317ae0dbd397c63f91fb85fe5328e12424ba`.

Exact checkpoint/owner witnesses: `S081 / 388086357ab954fbf208def00ba1ce5a60170598 / true / fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-17,0+18,1`, `-33,0+35,23`, `-77,0+102,55`, `-490,0+637,31`, `-602,0+780,12`, `-971,0+1161,17`
- U | <module/text>: `-124,0+204,67`

### D483 tests/test_project_config.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e56bf7fec7704132c919c79e114fd05dd54dda23`; original `100644:4780404cfaa89333a6e7fdd7082d51868ad210f9`; pinned-current `100644:9d4d317ae0dbd397c63f91fb85fe5328e12424ba`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-17,0+18,1`, `-33,0+35,23`, `-77,0+102,55`, `-490,0+570,31`, `-602,0+713,12`, `-971,0+1094,17`

### D484 tests/test_project_config.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e56bf7fec7704132c919c79e114fd05dd54dda23`; original `100644:a758d95b69f99f5e9d59bd3882c5b5735b630a28`; pinned-current `100644:9d4d317ae0dbd397c63f91fb85fe5328e12424ba`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-126,0+126,24`, `-138,0+162,203`, `-1214,0+1475,153`
- L | <module/text>: `-869,0+1096,34`

### D485 tests/test_project_config.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e56bf7fec7704132c919c79e114fd05dd54dda23`; original `100644:bd116fd8a9379990147defdffca41ba7cd6f0d1c`; pinned-current `100644:9d4d317ae0dbd397c63f91fb85fe5328e12424ba`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-4,0+4,1`, `-17,0+18,1`, `-33,0+35,23`, `-77,0+102,55`, `-138,0+218,187`, `-490,0+757,31`, `-602,0+900,12`, `-971,0+1281,17`, `-1214,0+1541,113`

### D486 tests/test_project_config_service_integration.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:97584879439321953ffa8e7a03bd722cfada8863`; original `100644:bee5bc76f244d8fce8687903bb1f2ce62554d1a5`; pinned-current `100644:5ed4c2c987a9e224d661a878a26da2a57fbd8eb6`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,1`, `-10,0+11,1`
- U | <module/text>: `-170,0+172,600`

### D487 tests/test_project_config_service_integration.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:97584879439321953ffa8e7a03bd722cfada8863`; original `100644:cffb7d8840700ca485c20a0d99ac1a5d29e0cf85`; pinned-current `100644:5ed4c2c987a9e224d661a878a26da2a57fbd8eb6`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-10,0+10,1`, `-170,0+171,198`

### D488 tests/test_project_config_service_integration.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 12:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:97584879439321953ffa8e7a03bd722cfada8863`; original `100644:f9b8126e0aaf128fcfffaff8528c0420bb3ec84d`; pinned-current `100644:5ed4c2c987a9e224d661a878a26da2a57fbd8eb6`.

Exact checkpoint/owner witnesses: `S081 / 388086357ab954fbf208def00ba1ce5a60170598 / true / fcbb1d6fa7347e9b918d030f4f99d058d9846a6c`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-170,0+170,143`

### D489 tests/test_project_path_hints.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 12:T/M, 22:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1bf3047fb59780c75b3ff1cf8c899d27ed034548`; original `100644:3e71071342da4c327b0220cdda00c6d08f797e4f`; pinned-current `100644:cbe8f974d2e5b8f65aa2f64b90285695f6c4b782`.

Exact checkpoint/owner witnesses: `S019 / 19a97f4cfa2e8a666d929a51fff7fc2a6d77fc98 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_project_context_reuses_only_current_evidence_bound_hints: `-311,3+311,5`, `-324,0+326,3`
- L | <module/text>: `-331,0+336,61`

### D490 tests/test_project_path_hints.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1bf3047fb59780c75b3ff1cf8c899d27ed034548`; original `100644:dc1b00f47cbb84f7caca9f621905e25dca0c2520`; pinned-current `100644:cbe8f974d2e5b8f65aa2f64b90285695f6c4b782`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-131,0+131,17`, `-331,0+353,61`, `-595,0+678,176`
- A | test_project_context_reuses_only_current_evidence_bound_hints: `-311,3+328,5`, `-324,0+343,3`

### D491 tests/test_project_path_hints.py

Disposition: `preserved-only-needs-integration`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1bf3047fb59780c75b3ff1cf8c899d27ed034548`; original `100644:dc601de3a4332bbf76c6c37cdf1009e0dd70e732`; pinned-current `100644:cbe8f974d2e5b8f65aa2f64b90285695f6c4b782`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-131,0+131,148`, `-595,0+775,70`
- L | <module/text>: `-470,0+618,32`

### D492 tests/test_projection_extra_fields.py

Disposition: `integrated-current`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e00106d01b6b38b9e90d2c7588a2f1c48302ef1f`; original `100644:e9f3b7dc70ccdff1b35a50a9c5dda56af7d542a9`; pinned-current `100644:e9f3b7dc70ccdff1b35a50a9c5dda56af7d542a9`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_clean_repo_search_and_profile: `-551,1+551,1`

### D493 tests/test_rag_fragment_cache.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a04b1ac72567442c9ea56b08b1e7ee91a4128138`; original `100644:ae398787d0d3b6b2bac10f5bfa7fd622ae4aeae8`; pinned-current `100644:ae398787d0d3b6b2bac10f5bfa7fd622ae4aeae8`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,2`, `-5,0+7,2`, `-6,0+10,1`, `-203,0+212,42`, `-241,3+307,426`, `-330,0+819,191`
- B | _Services.__init__: `-11,1+16,1`, `-16,0+21,1`
- B | _Services.embed: `-23,1+29,4`
- B | test_reused_chunks_keep_original_space_when_embedder_falls_back._FallbackServices.embed: `-212,0+263,4`
- B | test_reused_chunks_keep_original_space_when_embedder_falls_back: `-222,0+277,5`, `-223,1+283,1`, `-232,1+292,1`, `-236,0+296,4`, `-238,2+302,4`

### D494 tests/test_rag_hybrid.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fbd2c15f144c54239495894c47b4a304daa95dbd`; original `100644:47e1608e26a7936f173fcf3e1ddeb1ff09212400`; pinned-current `100644:47e1608e26a7936f173fcf3e1ddeb1ff09212400`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-4,0+4,2`, `-5,0+7,8`, `-60,0+70,39`, `-100,0+149,708`, `-134,0+895,261`
- B | test_rag_index_retries_transient_publish_lock: `-105,0+862,4`, `-129,1+890,1`

### D495 tests/test_rag_quality_contract.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c2b80b1b1042c9b914a4500759c86588b4a9e418`; original `100644:3b7dade12ca726644ea1534d6fd5fa929a98f6a3`; pinned-current `100644:3b7dade12ca726644ea1534d6fd5fa929a98f6a3`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,1`, `-4,0+5,1`, `-6,0+8,1`, `-9,0+12,1`, `-11,0+15,1`, `-99,0+107,159`, `-213,0+397,36`, `-246,0+466,28`, `-260,1+508,56`, `-345,1+722,0`
- B | _QueryServices.embed: `-23,1+28,1`
- B | _insert_vectors: `-48,2+53,2`, `-53,1+58,1`
- B | test_vector_search_streams_rows_and_keeps_golden_relevance: `-93,0+98,3`
- B | test_fallback_embedding_reports_identity_of_backend_that_produced_vectors: `-153,1+320,5`, `-165,0+336,6`, `-172,0+349,1`, `-184,1+362,7`
- B | test_numpy_vector_parse_skips_integer_overflow: `-219,2+439,2`
- B | test_equal_scores_use_semantic_path_order_not_row_order: `-236,1+456,1`, `-238,1+458,1`
- B | test_vector_cursor_closes_before_scoring_and_after_search: `-265,1+568,1`, `-297,0+601,3`, `-307,1+614,3`
- B | test_vector_cursor_closes_before_scoring_and_after_search._Cursor.fetchmany: `-275,0+578,1`
- B | test_vector_cursor_closes_before_scoring_and_after_search.checked_dot: `-301,1+608,1`
- B | test_retrieval_latency_and_peak_memory_baseline: `-310,1+619,1`, `-313,1+622,1`, `-318,1+627,2`, `-324,0+634,1`, `-326,3+637,15`, `-330,4+653,2`, `-338,0+659,22`, `-340,0+683,1`, `-342,0+686,5`, `-344,0+693,28`

### D496 tests/test_release_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3adab2ed7cbe850d58e50792f82f68fd348ce709`; original `100644:48b87668da6a00ec5d0043f1e1b00526997fc252`; pinned-current `100644:5f453645a7f861237a64e1d98016a8080dd6c997`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-10,0+10,1`
- L | test_release_uses_only_current_local_ai_hub_contracts: `-53,1+54,1`
- L | test_release_has_compact_mcp_surface_and_tool_first_policy: `-62,1+63,1`
- U | <module/text>: `-66,1+67,68`
- U | test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources: `-147,1+215,1`
- L | test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources: `-154,0+222,3`

### D497 tests/test_release_contract.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7474cb6c6dc3887d420c1f897b609f8b89e28ef6`; original `100644:7a2883524ca1aae1874b17cfb0cec9fefe2d8040`; pinned-current `100644:5f453645a7f861237a64e1d98016a8080dd6c997`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_release_uses_only_current_local_ai_hub_contracts: `-33,1+33,5`
- A | test_release_has_compact_mcp_surface_and_tool_first_policy: `-62,1+66,1`, `-66,1+70,6`
- A | test_no_personal_paths_or_runtime_payloads_in_tracked_release_sources: `-147,1+156,1`

### D498 tests/test_release_hardening.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8d7339d7d3b9bea92bcc5888528eceda9f485c09`; original `100644:1c780f45968d65581b13a0ae8d3fbbdf0ce8745a`; pinned-current `100644:0e59a96f663efa59726a19a6aa1453770dc02457`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_external_close_is_best_effort_across_all_sessions: `-78,1+78,1`
- L | <module/text>: `-244,0+244,19`

### D499 tests/test_release_hardening.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8d7339d7d3b9bea92bcc5888528eceda9f485c09`; original `100644:ac85763ef483aae4ef1e577d7d80aff1ddcb74f1`; pinned-current `100644:0e59a96f663efa59726a19a6aa1453770dc02457`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | _LiveProc: `-36,0+36,5`, `-38,0+43,3`
- A | test_mcp_explicit_short_deadline_is_honored: `-56,0+64,1`
- A | test_external_close_is_best_effort_across_all_sessions: `-78,1+87,1`
- L | <module/text>: `-229,3+238,17`

### D500 tests/test_reliability_core.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:69dc9ba89322e746c435386d418ea2740f84b7a7`; original `100644:53e28158ef852e74f9cd671b6294ade8fc5e82f0`; pinned-current `100644:53e28158ef852e74f9cd671b6294ade8fc5e82f0`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_external_sessions_are_bounded_lru: `-153,2+153,2`, `-158,0+158,1`, `-160,1+161,1`, `-162,2+163,2`, `-167,1+168,1`
- B | test_bundle_roundtrip_current_schema_and_binary_embedding: `-244,0+245,1`
- B | test_http_auth_json_limits_security_headers_and_binary_bundle: `-451,1+453,1`

### D501 tests/test_reliability_core.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:69dc9ba89322e746c435386d418ea2740f84b7a7`; original `100644:dbb9d670ae876deace06067632a7badeaec6cbd1`; pinned-current `100644:53e28158ef852e74f9cd671b6294ade8fc5e82f0`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_external_sessions_are_bounded_lru: `-153,2+153,2`, `-158,0+158,1`, `-160,1+161,1`, `-162,2+163,2`, `-167,1+168,1`
- A | test_http_auth_json_limits_security_headers_and_binary_bundle: `-451,1+452,1`

### D502 tests/test_reliability_integration.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:56435e884425e30f04cf69b4a3cbf37aba9b7cf3`; original `100644:e1ea5502bc3f0a405df43f247265fc8a5606c7aa`; pinned-current `100644:994d7be7b5f58210d3f310c729b2428a0ba20021`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_setup_supports_explicit_generic_mcp_config_paths: `-223,1+223,1`, `-227,0+227,1`

### D503 tests/test_reliability_integration.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:896e73d0fc50ecd1b95769d3d7f4a5e49ae02a38`; original `100644:31460cdd7f0e88280a1eaa224bcf074310682c4b`; pinned-current `100644:994d7be7b5f58210d3f310c729b2428a0ba20021`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_setup_supports_explicit_generic_mcp_config_paths: `-223,1+223,1`
- A | test_recovery_journal_waiter_replays_completed_owner_response: `-384,1+384,3`, `-392,1+394,8`

### D504 tests/test_reliability_integration.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:896e73d0fc50ecd1b95769d3d7f4a5e49ae02a38`; original `100644:378d2aeeca82b89054d7efbcc41f4110f1516e32`; pinned-current `100644:994d7be7b5f58210d3f310c729b2428a0ba20021`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_recovery_journal_waiter_replays_completed_owner_response: `-384,1+384,8`, `-392,1+399,8`

### D505 tests/test_reliability_runtime.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:061f56a17022ecbcf5b170b55539ae1ece87ad7b`; original `100644:143d7791ce74ca7d2f760963d6b84d4e52f33ca7`; pinned-current `100644:143d7791ce74ca7d2f760963d6b84d4e52f33ca7`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_generated_manifests_cover_generic_and_vscode: `-134,1+134,1`

### D506 tests/test_reranker_cache_identity.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:63cac813af4f567cbeb1a28cb8ef85a3cb138dab`; original `100644:cd88331cf719cc4bf0db45a0ebdbf76dcb9e07de`; pinned-current `100644:cd88331cf719cc4bf0db45a0ebdbf76dcb9e07de`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,3`, `-60,0+63,57`

### D507 tests/test_response_budget.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 16:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8fdc43c90f7b599d914b3c663dd8f2f81315f275`; original `100644:6be9625595fa3740588563b14d9769a5cf6a5fbf`; pinned-current `100644:f9a628c76e9a8a6439287a5a6ffce24775741f6f`.

Exact checkpoint/owner witnesses: `S076 / dd07cfe0ecc2fd926115635aff51069c037b7dcf / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-110,0+110,182`

### D508 tests/test_response_budget.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8fdc43c90f7b599d914b3c663dd8f2f81315f275`; original `100644:7142de2fd045b5cb37850730a9347162a6c6da97`; pinned-current `100644:f9a628c76e9a8a6439287a5a6ffce24775741f6f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-2,0+2,2`, `-21,0+23,50`, `-37,0+91,20`, `-54,0+128,19`
- A | test_budget_response_applies_aggregate_limit_and_preserves_decision_fields: `-24,1+76,1`, `-31,0+83,2`
- A | test_budget_response_can_return_reuse_envelope: `-48,1+122,1`
- U | <module/text>: `-110,0+203,23`

### D509 tests/test_router.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:8ecf4b4a014f8fc3f7dd52e4645089802bf8cb03`; original `100644:c9c9ce6e69efc6e9ffcb56cbf956bbbc9ef6dd9c`; pinned-current `100644:c9c9ce6e69efc6e9ffcb56cbf956bbbc9ef6dd9c`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-193,0+193,14`

### D510 tests/test_runtime_hardening.py

Disposition: `integrated-current`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6d5114f02bf00e0f808b57ec61241a0351aeb82f`; original `100644:043fe56c881fdaa774eaac5e92d90de570ec3dea`; pinned-current `100644:043fe56c881fdaa774eaac5e92d90de570ec3dea`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_client_does_not_spawn_when_hub_port_is_already_owned: `-107,1+107,1`
- B | test_client_cleans_failed_start_lock_write: `-122,1+122,1`
- B | test_client_does_not_bypass_live_managed_supervisor: `-141,1+141,1`
- B | test_client_does_not_direct_spawn_during_managed_restart: `-157,1+157,1`
- B | test_registry_repair_reactivates_the_selected_project: `-238,2+238,8`

### D511 tests/test_runtime_hardening.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6d5114f02bf00e0f808b57ec61241a0351aeb82f`; original `100644:0c209261eef05aa20729c32afc7cd399d92a34f1`; pinned-current `100644:043fe56c881fdaa774eaac5e92d90de570ec3dea`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_client_does_not_spawn_when_hub_port_is_already_owned: `-107,1+107,1`
- A | test_client_cleans_failed_start_lock_write: `-122,1+122,1`
- A | test_client_does_not_bypass_live_managed_supervisor: `-141,1+141,1`
- A | test_client_does_not_direct_spawn_during_managed_restart: `-157,1+157,1`
- A | test_registry_repair_reactivates_the_selected_project: `-238,2+238,6`

### D512 tests/test_runtime_hardening.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6d5114f02bf00e0f808b57ec61241a0351aeb82f`; original `100644:2d81cf957a559f82910d7df7defb1291f6bd945d`; pinned-current `100644:043fe56c881fdaa774eaac5e92d90de570ec3dea`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_registry_repair_reactivates_the_selected_project: `-238,2+238,8`

### D513 tests/test_setup.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e7cea0b9a1e5c0f6576569d64cba50f7f1589646`; original `100644:15cf04048b79885c6e4dcd4dd24420ef450ca2fd`; pinned-current `100644:498c39bca0e03f797f4f9db75f9d6c519e61a85d`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_compact_agent_config_is_default: `-84,1+84,1`
- A | test_direct_serena_is_explicit_opt_in: `-110,1+110,1`

### D514 tests/test_setup.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e7cea0b9a1e5c0f6576569d64cba50f7f1589646`; original `100644:48d93df7619a580916ec5092238cba07ca1eeec1`; pinned-current `100644:498c39bca0e03f797f4f9db75f9d6c519e61a85d`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-107,0+107,18`

### D515 tests/test_setup.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e7cea0b9a1e5c0f6576569d64cba50f7f1589646`; original `100644:f3b8c99af4fd547299141f2014b1ce4f47f5da0a`; pinned-current `100644:498c39bca0e03f797f4f9db75f9d6c519e61a85d`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_compact_agent_config_is_default: `-84,1+84,1`
- A | test_direct_serena_is_explicit_opt_in: `-110,1+110,1`
- L | <module/text>: `-320,0+320,46`

### D516 tests/test_speculative_draft_and_split.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:412ced79e954104651a58512caa0460bdfb1a0f6`; original `100644:3734b4a5665885c6aff71f6e5f74197e2656fedb`; pinned-current `100644:f4f98518e13536deddcbbfa1594382a2a89f3ac0`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-8,0+8,1`, `-151,0+153,85`
- L | test_speculative_draft_service: `-130,0+131,1`

### D517 tests/test_speculative_draft_and_split.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:412ced79e954104651a58512caa0460bdfb1a0f6`; original `100644:a3d39b3d8efff248a89b063f2102355344ed2050`; pinned-current `100644:f4f98518e13536deddcbbfa1594382a2a89f3ac0`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_speculative_draft_service: `-137,1+137,2`

### D518 tests/test_sse_events_stream.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e964d158f5075495bd0121a2e4de31890557f4f4`; original `100644:337583741b94525bb6dc8e7d1d3bd68a14d9f99f`; pinned-current `100644:273d62086b352d423d30696521b25fd794c398d6`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`, `-106,0+127,18`
- L | <module/text>: `-31,0+32,17`, `-145,0+185,157`, `-177,0+377,46`
- U | DummyHandler.__init__: `-43,0+61,1`
- U | DummyHandler._finish_stream_request: `-64,1+83,1`
- U | test_sse_stream_replays_and_receives_live_events: `-104,0+123,2`
- U | test_sse_stream_does_not_lose_event_between_replay_and_subscribe: `-111,1+150,1`, `-118,1+157,1`, `-130,0+169,1`
- U | test_sse_stream_does_not_lose_event_between_replay_and_subscribe.page_then_publish: `-113,2+152,2`
- U | test_client_stream_events_parsing: `-154,0+351,3`

### D519 tests/test_sse_events_stream.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e964d158f5075495bd0121a2e4de31890557f4f4`; original `100644:35e6746a2e2b49cacfa0a44ec11c8112b0f1aaf8`; pinned-current `100644:273d62086b352d423d30696521b25fd794c398d6`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-70,0+70,56`

### D520 tests/test_sse_events_stream.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e964d158f5075495bd0121a2e4de31890557f4f4`; original `100644:3c94c46bf022606f16b5d6762c74b54b481dc350`; pinned-current `100644:273d62086b352d423d30696521b25fd794c398d6`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-131,0+133,28`, `-177,0+209,87`
- U | DummyHandler.__init__: `-43,0+44,1`
- U | DummyHandler._finish_stream_request: `-64,1+66,1`
- A | test_sse_stream_replays_and_receives_live_events: `-104,0+106,1`
- L | test_sse_stream_does_not_lose_event_between_replay_and_subscribe: `-111,1+114,1`, `-118,1+120,1`
- A | test_sse_stream_does_not_lose_event_between_replay_and_subscribe.event_page_after_subscribe: `-113,2+116,1`, `-116,1+118,1`
- A | test_client_stream_events_parsing: `-154,0+184,2`

### D521 tests/test_sse_events_stream.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e964d158f5075495bd0121a2e4de31890557f4f4`; original `100644:5fb3b9c52b101a5bdb762991cd6de2de21e01783`; pinned-current `100644:273d62086b352d423d30696521b25fd794c398d6`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-5,0+5,1`, `-130,0+152,29`
- U | test_sse_stream_replays_and_receives_live_events: `-96,1+97,1`, `-104,0+105,21`
- U | test_sse_stream_does_not_lose_event_between_replay_and_subscribe: `-111,1+133,1`, `-118,1+140,1`
- U | test_sse_stream_does_not_lose_event_between_replay_and_subscribe.event_page_then_publish: `-113,2+135,2`
- U | test_sse_stream_timeout_bounds_queue_wait: `-144,1+195,3`
- U | test_client_stream_events_parsing: `-154,0+207,3`, `-158,0+214,3`, `-159,1+218,1`, `-162,1+221,1`, `-172,5+231,9`

### D522 tests/test_sse_events_stream.py

Disposition: `preserved-only-needs-integration`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e964d158f5075495bd0121a2e4de31890557f4f4`; original `100644:7f0805cd7884b237218bc38960af5a8ff421d185`; pinned-current `100644:273d62086b352d423d30696521b25fd794c398d6`.

Exact checkpoint/owner witnesses: `S044 / 398beaa7a4ccfd310677891125fa29f73198858d / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | DummyHandler.__init__: `-43,0+43,1`
- U | DummyHandler._finish_stream_request: `-64,1+65,1`
- A | test_sse_stream_replays_and_receives_live_events: `-104,0+105,1`
- A | test_client_stream_events_parsing: `-154,0+156,2`

### D523 tests/test_sse_events_stream.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 1:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e964d158f5075495bd0121a2e4de31890557f4f4`; original `100644:8b8c4d4daac8089b8fd9de669ad75a52ce9ab119`; pinned-current `100644:273d62086b352d423d30696521b25fd794c398d6`.

Exact checkpoint/owner witnesses: `S097 / 7e578713b556e8af72894c27ed43c57e678dc29b / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_client_stream_events_parsing: `-154,0+154,2`

### D524 tests/test_status_snapshot_quality.py

Disposition: `preserved-only-needs-integration`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:497e77c1436106bb00739b9f58ecf0c4df0b6670`; original `100644:719e9ffb04bcff535f37eff33055bcdfc3a18517`; pinned-current `100644:f57662dbc21b82b6500705438a59862cbf3882ee`.

Exact checkpoint/owner witnesses: `S092 / fcb49e482c3c5135f9426122b0be6fee1628a805 / true / 5538bd11a83d50392b10dc67ae6ba18ea8b967e4`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | make_app: `-88,0+88,2`
- U | <module/text>: `-92,0+94,27`, `-105,1+134,16`, `-118,1+162,0`, `-124,1+169,0`, `-129,1+173,0`
- A | test_cold_concurrent_status_request_returns_warming_without_waiting: `-122,1+165,3`, `-131,1+174,6`
- L | <module/text>: `-133,0+181,48`, `-243,0+339,32`

### D525 tests/test_status_snapshot_quality.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:89571aaa518607a2113f114eb65232cb5b7d978b`; original `100644:564d2916f5668e39174e8ed84843116875c2c9e1`; pinned-current `100644:f57662dbc21b82b6500705438a59862cbf3882ee`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_slow_status_dependency_degrades_within_deadline_and_keeps_shape: `-198,0+198,1`
- L | <module/text>: `-200,0+201,16`

### D526 tests/test_status_snapshot_quality.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:9f542a7b58be78761a2df27779ae85683853faf4`; original `100644:8c0031cd8e433709ffbdd8b7c38796d874362ab8`; pinned-current `100644:f57662dbc21b82b6500705438a59862cbf3882ee`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-1,0+1,1`, `-7,0+8,1`, `-9,0+11,1`, `-196,1+200,125`
- U | test_slow_status_dependency_degrades_within_deadline_and_keeps_shape: `-195,0+198,1`
- U | test_realtime_status_bounds_runtime_health_probes: `-261,2+389,4`, `-265,0+395,1`, `-266,0+397,1`
- U | test_timed_out_agent_state_is_reused_across_status_cache_hits: `-307,0+439,9`, `-310,1+451,2`

### D527 tests/test_storage_service_reliability.py

Disposition: `preserved-only-needs-integration`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1cb376a6bea96c622c6784041c21ddde0bff6774`; original `100644:2afe3aa865d348b0fdc573be48380187c466d7ee`; pinned-current `100644:dcee7b1f77c92039ccbcf923c4a980e4f3f48c2f`.

Exact checkpoint/owner witnesses: `S063 / 7153deb5fe0b5548b8992e3210ffe2cea72d4552 / true / b7b1b0c0fe0b786afea26ecb8d375e59d64c6655`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,0+12,1`
- L | test_verification_store_indexes_and_retry: `-129,0+130,1`
- U | test_task_store_lock_and_retry: `-207,0+209,1`, `-210,0+213,1`, `-211,0+215,1`, `-228,1+233,3`

### D528 tests/test_storage_service_reliability.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1cb376a6bea96c622c6784041c21ddde0bff6774`; original `100644:4752bd584cee47e3753367c8034f08c927f9599a`; pinned-current `100644:dcee7b1f77c92039ccbcf923c4a980e4f3f48c2f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-40,0+40,2`
- A | test_verification_store_indexes_and_retry: `-129,0+131,1`, `-134,2+137,5`
- A | test_task_store_lock_and_retry: `-207,4+213,9`, `-228,1+239,1`

### D529 tests/test_storage_service_reliability.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 29:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1cb376a6bea96c622c6784041c21ddde0bff6774`; original `100644:5a5d63d4608e3eaeeccdafb142b95557eef11f1f`; pinned-current `100644:dcee7b1f77c92039ccbcf923c4a980e4f3f48c2f`.

Exact checkpoint/owner witnesses: `S057 / 4e1ee2ac1297c9fe84370e80c93370327de2b33e / true / ec607367e99cba6f1c98410dbc81e9d216685a62`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_repair_loop_drive_letter_casing: `-278,1+278,1`, `-281,0+281,1`, `-300,0+301,2`

### D530 tests/test_stuck_preprocessing_and_dashboard_fixes.py

Disposition: `integrated-current`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:1a3f1ccbac39d687d4b50273f59b50dd8c96a04d`; original `100644:598821fae5932a3a8d841b814225698eb3db3b51`; pinned-current `100644:598821fae5932a3a8d841b814225698eb3db3b51`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_revision_scoped_error_markers: `-19,2+19,2`, `-27,2+27,2`
- B | test_preprocessor_external_index_degrades_and_skips_on_revision_error: `-78,1+78,0`, `-89,1+88,1`, `-104,1+103,1`, `-107,1+106,1`, `-112,1+111,1`, `-118,1+117,1`

### D531 tests/test_surface_and_packaging.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:48984d6c70ee5e63c0d8383dad7aec9168fbff20`; original `100644:f3056eb74a4e02adf03293d6e966e3f8a2665893`; pinned-current `100644:c017c48573ff7a9c55007c0846a4ab28ced25eb5`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_remote_bind_fails_closed_without_token: `-73,5+73,9`

### D532 tests/test_surface_benchmarks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:58f103dc660a6b1e912a474a2c93180386b0f5c5`; original `100644:0dca736592aa5e76ebb77f4584edbe4206b467c6`; pinned-current `100644:89abb059a7180c2def85999dc94c213e5235d53c`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,2`, `-8,0+10,2`, `-11,1+15,13`, `-13,0+29,1`, `-26,0+45,5`, `-28,2+52,91`, `-129,0+335,72`, `-141,0+419,244`, `-520,0+2644,68`
- L | <module/text>: `-21,1+38,3`, `-168,0+690,91`, `-193,0+806,374`, `-346,0+1496,248`, `-360,0+1758,19`, `-374,1+1791,310`, `-388,0+2141,91`, `-389,3+2233,0`, `-393,1+2234,16`, `-395,0+2251,58`, `-396,1+2310,189`
- L | _async_jobs_lifecycle_snapshot: `-47,1+160,1`
- A | _plan_grade_metadata: `-111,0+224,2`, `-114,1+229,1`
- A | _comparison_stages: `-121,3+236,21`, `-125,1+258,14`, `-127,1+273,61`
- A | test_plan_grade_gate_rejects_malformed_metadata_without_crashing: `-143,1+665,1`, `-151,1+673,1`
- L | test_run_benchmark_is_isolated_and_preserves_existing_scratch_data: `-235,1+1222,1`, `-256,1+1243,1`, `-260,1+1247,1`, `-262,0+1249,16`, `-272,1+1275,101`, `-280,0+1383,2`, `-283,1+1388,8`, `-286,0+1398,1`, `-303,0+1416,23`, `-306,1+1442,1`, `-311,1+1447,1`, `-330,1+1466,1`, `-335,1+1471,13`, `-343,1+1491,3`
- A | test_run_benchmark_is_isolated_and_preserves_existing_scratch_data.emit_diagnostic: `-238,1+1225,1`
- A | test_benchmark_rejects_duplicate_concurrency_and_unbounded_samples: `-369,1+1786,1`
- A | test_compare_records_pairs_shuffled_observations_by_explicit_id: `-376,4+2102,6`, `-381,0+2109,27`, `-382,3+2137,1`
- A | test_compare_records_requires_plan_grade_light_sample_total: `-415,1+2517,1`, `-424,4+2526,5`, `-432,1+2535,2`
- A | test_smoke_comparison_is_inconclusive_and_retains_provisional_metrics: `-436,3+2540,10`, `-446,1+2557,0`
- A | test_compare_records_marks_different_hardware_or_configuration_inconclusive: `-451,3+2561,3`, `-455,1+2565,3`
- A | test_compare_records_refuses_inference_without_model_digest: `-461,1+2573,8`
- A | test_cli_persists_and_reports_baseline_comparison: `-475,1+2594,1`, `-480,1+2599,1`, `-487,1+2606,1`
- A | test_optional_inference_uses_runtime_load_metric_without_real_model: `-491,1+2610,3`, `-503,0+2624,2`, `-505,1+2628,2`

### D533 tests/test_surface_benchmarks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 38:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:58f103dc660a6b1e912a474a2c93180386b0f5c5`; original `100644:264bf805b7738df5af8c533150c377d25bbe595b`; pinned-current `100644:89abb059a7180c2def85999dc94c213e5235d53c`.

Exact checkpoint/owner witnesses: `S002 / 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-7,0+7,3`, `-11,1+16,13`, `-13,0+30,1`, `-26,0+46,5`, `-28,2+53,91`, `-129,0+387,72`, `-141,0+471,244`, `-520,0+2696,89`
- L | <module/text>: `-8,0+11,2`, `-21,1+39,3`, `-75,0+212,28`, `-168,0+742,91`, `-193,0+858,374`, `-346,0+1548,248`, `-360,0+1810,19`, `-374,1+1843,310`, `-388,0+2193,91`, `-389,3+2285,0`, `-393,1+2286,16`, `-395,0+2303,58`, `-396,1+2362,189`
- A | _async_jobs_lifecycle_snapshot: `-47,1+161,1`, `-52,1+166,1`, `-56,1+170,24`
- A | _plan_grade_metadata: `-111,0+276,2`, `-114,1+281,1`
- A | _comparison_stages: `-121,3+288,21`, `-125,1+310,14`, `-127,1+325,61`
- A | test_plan_grade_gate_rejects_malformed_metadata_without_crashing: `-143,1+717,1`, `-151,1+725,1`
- L | test_run_benchmark_is_isolated_and_preserves_existing_scratch_data: `-235,1+1274,1`, `-256,1+1295,1`, `-260,1+1299,1`, `-262,0+1301,16`, `-272,1+1327,101`, `-280,0+1435,2`, `-283,1+1440,8`, `-286,0+1450,1`, `-303,0+1468,23`, `-306,1+1494,1`, `-311,1+1499,1`, `-330,1+1518,1`, `-335,1+1523,13`, `-343,1+1543,3`
- A | test_run_benchmark_is_isolated_and_preserves_existing_scratch_data.emit_diagnostic: `-238,1+1277,1`
- A | test_benchmark_rejects_duplicate_concurrency_and_unbounded_samples: `-369,1+1838,1`
- A | test_compare_records_pairs_shuffled_observations_by_explicit_id: `-376,4+2154,6`, `-381,0+2161,27`, `-382,3+2189,1`
- A | test_compare_records_requires_plan_grade_light_sample_total: `-415,1+2569,1`, `-424,4+2578,5`, `-432,1+2587,2`
- A | test_smoke_comparison_is_inconclusive_and_retains_provisional_metrics: `-436,3+2592,10`, `-446,1+2609,0`
- A | test_compare_records_marks_different_hardware_or_configuration_inconclusive: `-451,3+2613,3`, `-455,1+2617,3`
- A | test_compare_records_refuses_inference_without_model_digest: `-461,1+2625,8`
- A | test_cli_persists_and_reports_baseline_comparison: `-475,1+2646,1`, `-480,1+2651,1`, `-487,1+2658,1`
- A | test_optional_inference_uses_runtime_load_metric_without_real_model: `-491,1+2662,3`, `-503,0+2676,2`, `-505,1+2680,2`

### D534 tests/test_surface_benchmarks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:58f103dc660a6b1e912a474a2c93180386b0f5c5`; original `100644:e57b7469f3af0c9f876740114da1b2e60f690159`; pinned-current `100644:89abb059a7180c2def85999dc94c213e5235d53c`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-129,0+129,85`
- L | test_run_benchmark_is_isolated_and_preserves_existing_scratch_data: `-265,0+350,1`

### D535 tests/test_surface_benchmarks.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ba3d01fb82d971542925929ce299fe417fe61b4e`; original `100644:66f21e9c4d696c27b975983d38ab59464f6cd3ec`; pinned-current `100644:89abb059a7180c2def85999dc94c213e5235d53c`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-12,0+12,1`, `-13,0+14,1`, `-15,0+17,1`, `-163,0+166,14`, `-215,0+232,44`
- A | test_t12_matrix_reports_profile_corpus_metrics_and_scenario_receipts.FakeRunner.run: `-571,0+632,1`, `-592,0+654,3`, `-594,0+659,7`
- A | test_t12_matrix_reports_profile_corpus_metrics_and_scenario_receipts.FakeRunner.run_benchmark_scenario: `-597,1+669,1`, `-614,0+686,1`, `-619,0+692,1`, `-622,0+696,1`, `-629,1+704,4`, `-631,0+709,3`, `-633,1+714,17`
- A | test_t12_matrix_reports_profile_corpus_metrics_and_scenario_receipts: `-639,1+736,12`, `-656,1+764,2`, `-658,1+767,2`, `-661,0+771,8`
- L | <module/text>: `-678,0+796,68`

### D536 tests/test_surface_inventory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:376d3206a7851c38ab36f74188f86ba28af327f4`; original `100644:ab172634e7fcf6a2bc371caf208b0504d38a9514`; pinned-current `100644:f70410c53c22adbf9de527de3b547ded91124abe`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-3,0+3,1`, `-328,0+361,76`, `-865,0+990,417`
- A | make_repo: `-112,0+113,10`, `-118,1+129,4`
- U | test_operation_contract_metadata: `-185,1+199,13`, `-187,3+213,0`
- A | test_inventory_extracts_surfaces_and_resolves_dynamic_route_registry: `-288,1+311,1`, `-291,0+314,3`, `-293,1+319,5`, `-303,0+333,3`, `-306,2+339,2`
- U | test_prompt_docs_are_not_generated_manifests: `-815,1+924,1`
- L | <module/text>: `-821,1+930,17`

### D537 tests/test_surface_inventory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:376d3206a7851c38ab36f74188f86ba28af327f4`; original `100644:b4122c864f11090a3d57a5fca42f77a8408edf88`; pinned-current `100644:f70410c53c22adbf9de527de3b547ded91124abe`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-4,0+4,1`, `-330,0+342,35`, `-645,1+729,28`, `-865,0+981,626`
- U | test_operation_contract_metadata: `-181,1+182,6`
- L | test_operation_contract_metadata: `-185,1+191,10`, `-187,3+202,0`
- L | <module/text>: `-430,0+477,32`
- U | test_check_mode_reports_stale_coverage_without_repairing: `-463,1+542,1`, `-468,9+547,1`, `-479,1+550,1`, `-481,2+552,3`
- U | test_check_mode_does_not_create_missing_coverage_doc: `-485,1+557,1`, `-489,7+561,0`, `-501,1+566,1`
- U | test_check_mode_infers_task_id_without_writing_coverage: `-505,1+570,1`, `-510,1+575,8`, `-515,1+587,2`, `-519,0+592,1`
- U | test_check_mode_with_real_schema_generator_is_read_only: `-521,1+595,1`, `-523,0+597,1`, `-611,0+692,1`
- L | test_check_mode_with_real_schema_generator_is_read_only.snapshot_tree: `-541,9+616,7`
- L | test_check_mode_with_real_schema_generator_is_read_only.reject_write: `-554,1+627,1`
- L | test_check_mode_with_real_schema_generator_is_read_only: `-560,0+633,7`, `-574,2+654,2`, `-599,0+679,1`, `-613,0+695,1`
- U | test_check_cli_accepts_coverage_without_mutating_it: `-629,1+712,1`
- L | test_check_cli_accepts_coverage_without_mutating_it: `-643,0+726,1`
- U | test_inventory_contract_rows_include_required_machine_readable_fields: `-860,1+971,6`

### D538 tests/test_swarm_orchestrator.py

Disposition: `integrated-current`. Occurrences: 26:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2fa3b7aa4b3a0870f0a1413c5f3f374d60e0fa05`; original `100644:1eb35080c380c568eb59c9c0b212999395ad0b2e`; pinned-current `100644:1eb35080c380c568eb59c9c0b212999395ad0b2e`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,1`, `-4,0+5,2`, `-121,0+124,195`
- B | test_swarm_lifecycle_success: `-17,1+20,1`
- B | test_swarm_lifecycle_test_failure_triggers_rejection: `-87,1+90,1`

### D539 tests/test_swarm_orchestrator.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2fa3b7aa4b3a0870f0a1413c5f3f374d60e0fa05`; original `100644:e6db35bc03b35f1e7b148210a4f682aa2b01dba1`; pinned-current `100644:1eb35080c380c568eb59c9c0b212999395ad0b2e`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_swarm_lifecycle_success: `-17,1+17,1`
- A | test_swarm_lifecycle_test_failure_triggers_rejection: `-87,1+87,1`

### D540 tests/test_t04_public_api_contracts.py

Disposition: `integrated-current`. Occurrences: 32:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6f69d9e613deb9e618a54c693ff82e292d787f3b`; original `100644:9b6ffd6e93c5ae31cc72afea566d3e3e17a78e13`; pinned-current `100644:9b6ffd6e93c5ae31cc72afea566d3e3e17a78e13`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | live_api: `-19,1+19,5`
- B | test_task_list_query_filters_contract_and_checkpoint_before_limit: `-93,4+97,1`, `-98,0+99,1`, `-103,0+105,1`, `-108,0+111,1`, `-116,1+120,1`, `-119,6+123,7`, `-138,1+143,1`, `-141,1+146,1`, `-144,1+149,3`, `-147,1+154,1`
- B | test_task_list_surfaces_query_scan_truncation: `-178,1+185,1`, `-188,1+195,1`
- B | test_task_list_post_rejects_non_string_query: `-195,1+202,1`, `-197,0+204,1`, `-198,1+206,1`
- B | test_artifact_list_is_bounded_metadata_and_needs_no_id: `-293,1+301,1`

### D541 tests/test_t05_cache_state_isolation.py

Disposition: `integrated-current`. Occurrences: 30:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:2ad8e7a89af372f1eeb1209340a8398553e8b21c`; original `100644:c40976b26e57498c45c43caa67636ffa7b87ca8f`; pinned-current `100644:c40976b26e57498c45c43caa67636ffa7b87ca8f`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-4,0+4,2`, `-5,0+7,3`, `-16,0+21,18`, `-135,0+184,254`
- B | test_derived_sqlite_recovery_preserves_agent_state_and_leases: `-43,0+66,1`, `-44,1+68,1`, `-62,0+86,1`, `-73,9+98,18`
- B | test_scoped_memory_delete_preserves_all_relations_until_authorized: `-94,0+128,1`, `-95,11+130,9`, `-107,0+140,1`, `-116,0+150,7`, `-121,0+162,6`, `-128,0+175,1`, `-133,0+181,1`

### D542 tests/test_t10_acceptance.py

Disposition: `integrated-current`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:fcbe2e46978210e70afd2f3a66b04cb41e5320e6`; original `100644:8572f9ac127b35fc76b3add16df123d76115e560`; pinned-current `100644:8572f9ac127b35fc76b3add16df123d76115e560`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-7,0+7,1`, `-14,0+15,3`, `-16,0+20,1`, `-36,0+41,33`, `-76,0+115,104`, `-138,0+281,6`, `-142,0+291,7`, `-249,0+405,42`, `-362,0+560,30`, `-453,0+681,41`, `-489,0+758,51`, `-533,0+853,221`, `-704,0+1255,634`
- B | test_code_index_query_reports_candidate_freshness_coverage_and_truncation: `-54,0+92,1`
- B | test_adaptive_retrieval_passes_remaining_deadline_to_serena: `-656,1+1197,3`, `-698,0+1240,9`
- B | test_adaptive_retrieval_passes_remaining_deadline_to_serena.SlowDeterministic.related_paths: `-673,1+1216,0`

### D543 tests/test_t10_retrieval_edges.py

Disposition: `integrated-current`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:344e15f46544505de61c4f97f00f644cf3838717`; original `100644:1b6793d3b2e6435836804310264eb5b5d41a870e`; pinned-current `100644:1b6793d3b2e6435836804310264eb5b5d41a870e`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-4,0+4,3`, `-9,0+12,3`, `-10,0+16,122`, `-17,0+145,3`, `-19,0+150,2`, `-42,0+175,43`, `-68,0+244,411`
- B | test_call_edge_analyzer_version_rejects_stale_parse_blobs: `-139,1+726,1`

### D544 tests/test_t12_benchmark_contract.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:23cb0f5fd2222dc200a2b402b4b83345b6d3c9bc`; original `100644:cd4e4b137803eab622680704b0ce4a4647c20603`; pinned-current `100644:cd4e4b137803eab622680704b0ce4a4647c20603`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,1`, `-7,1+8,14`, `-79,0+127,103`, `-149,0+300,41`, `-395,0+596,94`, `-541,0+845,124`
- B | test_t12_case_reports_backend_throughput_and_end_to_end_latency.Runtime: `-12,0+26,2`
- B | test_t12_case_reports_backend_throughput_and_end_to_end_latency.Runtime.generate_stream: `-17,1+33,1`, `-19,0+35,1`
- B | test_t12_case_reports_backend_throughput_and_end_to_end_latency.Scheduler: `-31,0+48,3`
- B | test_t12_case_reports_backend_throughput_and_end_to_end_latency.Scheduler.submit: `-34,0+54,14`
- B | test_t12_case_reports_backend_throughput_and_end_to_end_latency: `-65,0+99,5`, `-66,0+105,9`
- B | test_t12_scenario_hook_forwards_contract_metrics_for_all_scenarios: `-186,1+378,1`, `-199,0+391,6`, `-201,0+399,3`
- B | test_t12_overload_accepts_observed_queueing_without_requiring_rejection.Runner.run_benchmark_scenario: `-437,0+732,1`
- B | test_t12_profile_matrix_uses_runner_timing_and_flat_deadline_metrics.Runner.run_t12_case: `-506,0+802,4`
- B | test_t12_profile_matrix_uses_runner_timing_and_flat_deadline_metrics: `-539,0+839,4`

### D545 tests/test_t12_runtime_scenarios.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:647524c353c5a88d6cad8276ab5c45b0e7388437`; original `100644:e98ff1ac2434f2b08ce6f7d22db1f05b366dfefc`; pinned-current `100644:10ce4dd7795e17210cf7f17b1be85f3072d01856`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-7,1+7,4`, `-59,0+62,107`, `-150,0+262,34`, `-392,0+542,65`, `-507,0+877,51`, `-546,0+981,42`
- A | test_t12_json_format_and_think_are_promoted_to_ollama_request_fields: `-61,0+171,1`
- A | test_t12_ollama_runtime_measures_deadline_stages_through_scheduler: `-82,1+193,1`, `-149,0+260,1`
- A | test_t12_runtime_overload_reports_observed_queueing: `-166,1+312,4`, `-186,0+335,1`
- U | <module/text>: `-468,0+683,155`
- A | test_t12_runtime_overload_reports_observed_admission_rejection: `-488,1+858,1`
- A | test_t12_runtime_fallback_scores_observed_response_and_labels_backends: `-512,0+933,3`, `-523,1+950,3`, `-531,0+960,2`, `-543,0+974,4`
- A | test_t12_runtime_fallback_scores_observed_response_and_labels_backends.request_interruptible: `-514,0+938,3`

### D546 tests/test_t12_scheduler_scenarios.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:6b7bd141387f7773a2b5170023676e9bd207b2d0`; original `100644:3793cacf34cb0ff0874165e746f0e050331b8522`; pinned-current `100644:6b2a52a96a48ef5e6f34e07ca5ffb2e4777a2656`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,2`, `-15,0+17,211`, `-82,0+295,32`, `-120,0+365,34`, `-161,0+440,12`, `-309,0+600,228`

### D547 tests/test_t17_auxiliary_formats.py

Disposition: `integrated-current`. Occurrences: 8:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c0b6f3fc21f4eeea80b3b965705e011f0dad91f8`; original `100644:e2e72443b38ca776a53bc6175af68a4b36993014`; pinned-current `100644:e2e72443b38ca776a53bc6175af68a4b36993014`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-137,0+137,41`

### D548 tests/test_telemetry_error_metadata_privacy_t18.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:bf8571bc98ca6e63c0f9abb6085dd39b26cb2aa0`; original `100644:76e3d92781f21bfd0c9190e831521c9bb8b832cb`; pinned-current `100644:943955181b3e608f14b9c5f16045474f866784f2`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_error_metadata_is_redacted_in_both_persisted_tables: `-16,0+16,2`, `-18,0+20,2`, `-27,2+31,4`, `-35,2+41,4`, `-51,1+59,2`, `-81,1+90,1`
- U | <module/text>: `-92,0+101,64`

### D549 tests/test_telemetry_privacy.py

Disposition: `integrated-current`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c197639d4cd1e903d1109f1b70e41e4f2686c9f2`; original `100644:b77d4b497f81d051ed829b01db8aa1ef836b4c8a`; pinned-current `100644:b77d4b497f81d051ed829b01db8aa1ef836b4c8a`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | test_error_telemetry_persists_classification_without_exception_text: `-37,1+37,1`

### D550 tests/test_telemetry_self_accounting.py

Disposition: `integrated-current`. Occurrences: 5:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:71cd7c01d35666f8cc9137c96be2463df7a7f1de`; original `100644:10ac71113cb4d8895a031502fd697e084552a797`; pinned-current `100644:10ac71113cb4d8895a031502fd697e084552a797`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-1,0+1,3`, `-2,0+5,12`, `-28,0+43,61`
- B | test_telemetry_instrumentation_is_not_recorded_as_user_tool_workload: `-7,1+22,1`, `-9,1+24,1`, `-16,2+31,2`, `-23,1+38,1`

### D551 tests/test_telemetry_tail_latency.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:f2e7262981714d32b7024940cc3977767878e94d`; original `100644:53f3b77e4804bcbaa33d3ebba1943c8a937abf86`; pinned-current `100644:53f3b77e4804bcbaa33d3ebba1943c8a937abf86`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-25,0+25,14`

### D552 tests/test_tiered_ollama_runtime.py

Disposition: `preserved-only-needs-integration`. Occurrences: 18:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:03c3029b682736a3b83554d17c7c221c30d28c27`; original `100644:aa4974d8ce5f33c7b87a191c93349feeac564855`; pinned-current `100644:98dc89774d58c4a5b54c93fcf8b603bcf3f123fd`.

Exact checkpoint/owner witnesses: `S023 / b0ade36afca1bceeb6756fe76eeb0ca90758e64a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | FakeRuntime.__init__: `-10,0+10,1`
- A | FakeRuntime.is_online: `-12,1+13,1`
- A | FakeRuntime.request: `-19,0+20,4`
- U | <module/text>: `-117,0+122,71`

### D553 tests/test_tiered_ollama_runtime.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:03c3029b682736a3b83554d17c7c221c30d28c27`; original `100644:dd539512a22ec11b45ab9452f210642d8932e41f`; pinned-current `100644:98dc89774d58c4a5b54c93fcf8b603bcf3f123fd`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | FakeRuntime.__init__: `-7,1+7,6`, `-9,0+14,1`, `-10,0+16,2`
- A | FakeRuntime.request_interruptible: `-22,1+30,2`
- A | FakeRuntime.prepare_model: `-25,1+34,9`, `-27,0+44,1`
- L | FakeRuntime: `-28,0+46,4`
- U | <module/text>: `-93,0+115,48`

### D554 tests/test_tiered_ollama_runtime.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3e6cc8ef16e115c28a5a2495e145953dd98bbff2`; original `100644:1141a483a2699a80937c4d238d8e2ee9ce817410`; pinned-current `100644:98dc89774d58c4a5b54c93fcf8b603bcf3f123fd`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | FakeRuntime.__init__: `-7,1+7,7`
- U | FakeRuntime.__init__: `-9,0+15,2`
- A | FakeRuntime.prepare_model: `-33,0+41,1`, `-37,1+46,1`
- L | FakeRuntime: `-39,0+48,4`, `-53,0+66,34`
- L | <module/text>: `-104,0+151,108`
- A | test_model_prepare_forwards_cancellation_controls_to_selected_runtime: `-111,0+266,1`, `-112,1+268,4`, `-114,1+273,1`
- A | test_smart_request_does_not_unload_unknown_external_model: `-159,1+318,1`

### D555 tests/test_token_economy_tools.py

Disposition: `integrated-current`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:587e9e0cf7059aa45012945622e8d581f9971e13`; original `100644:30941085bd6bf0b3b316b19a8f5fa9219f71d9e9`; pinned-current `100644:30941085bd6bf0b3b316b19a8f5fa9219f71d9e9`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-23,0+23,1`, `-128,0+129,26`

### D556 tests/test_transcription_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3dc82ea9c03ad0c1996ff2ecf7457c170cdd6bab`; original `100644:31941a7b6b65729765ae10b31021125df69e575d`; pinned-current `100644:442ee032ee64d8f1911a6dde0ae119c5ce3ab06b`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,1`, `-4,0+5,1`, `-8,1+10,1`, `-14,0+16,10`, `-44,0+59,97`
- A | test_transcribe_honors_requested_model_and_cleans_task_owned_output.fake_run: `-29,1+41,4`
- A | test_transcribe_honors_requested_model_and_cleans_task_owned_output: `-32,2+47,2`, `-40,1+55,1`
- L | test_missing_whisper_cli_does_not_report_metadata_as_transcription: `-51,1+163,1`
- U | <module/text>: `-60,0+172,153`, `-104,1+374,26`, `-122,0+417,53`, `-144,0+492,59`
- A | test_whisper_binary_removed_after_lookup_reports_cli_missing: `-65,1+330,1`, `-70,1+335,1`
- L | test_whisper_process_failure_never_returns_successful_transcript: `-91,0+356,2`, `-97,2+366,2`
- A | test_whisper_process_failure_never_returns_successful_transcript.fake_run: `-92,1+359,3`
- U | test_whisper_process_failure_never_returns_successful_transcript: `-103,0+372,1`
- L | test_empty_whisper_output_is_not_a_successful_transcription: `-112,1+407,1`, `-114,2+409,2`
- A | test_cancellation_cleans_task_owned_whisper_output: `-136,2+484,2`

### D557 tests/test_transcription_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3dc82ea9c03ad0c1996ff2ecf7457c170cdd6bab`; original `100644:c6b970ab36cdd820a540e996f7990aa9a6c72303`; pinned-current `100644:442ee032ee64d8f1911a6dde0ae119c5ce3ab06b`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,1`, `-4,0+5,1`, `-8,1+10,1`, `-144,0+455,88`
- U | <module/text>: `-15,0+17,9`, `-45,0+59,96`, `-60,0+170,125`, `-104,1+344,26`, `-122,0+387,46`
- A | test_transcribe_honors_requested_model_and_cleans_task_owned_output.fake_run: `-29,1+40,4`
- A | test_transcribe_honors_requested_model_and_cleans_task_owned_output: `-32,2+46,2`, `-40,1+54,1`
- L | test_missing_whisper_cli_does_not_report_metadata_as_transcription: `-51,1+161,1`
- A | test_whisper_binary_removed_after_lookup_reports_cli_missing: `-65,1+300,1`, `-70,1+305,1`
- L | test_whisper_process_failure_never_returns_successful_transcript: `-91,0+326,2`, `-97,2+336,2`
- A | test_whisper_process_failure_never_returns_successful_transcript.fake_run: `-92,1+329,3`
- U | test_whisper_process_failure_never_returns_successful_transcript: `-103,0+342,1`
- L | test_empty_whisper_output_is_not_a_successful_transcription: `-112,1+377,1`, `-114,2+379,2`
- A | test_cancellation_cleans_task_owned_whisper_output: `-136,2+447,2`

### D558 tests/test_transcription_contract.py

Disposition: `preserved-only-needs-integration`. Occurrences: 8:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:79ac464da0cd4c456d51e7632341aaace04eb957`; original `100644:eec09f86a14c8b7db907c675c4c772d5e9978598`; pinned-current `100644:442ee032ee64d8f1911a6dde0ae119c5ce3ab06b`.

Exact checkpoint/owner witnesses: `S037 / 5b16828e44f5ca0b09c265b2a5a034fe94bbddea / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | test_missing_whisper_cli_does_not_report_metadata_as_transcription: `-56,0+56,3`
- U | <module/text>: `-57,1+60,0`
- U | test_whisper_process_failure_never_returns_successful_transcript.fake_run: `-93,0+95,1`
- U | test_whisper_process_failure_never_returns_successful_transcript: `-97,0+100,1`, `-104,1+109,8`
- L | test_whisper_process_failure_never_returns_successful_transcript: `-103,0+107,1`
- U | test_empty_whisper_output_is_not_a_successful_transcription: `-122,0+134,3`

### D559 tests/test_vision_artifacts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4a116a185fa183f62a18a1069ffe613c09c5b200`; original `100644:92ae545a7adaac84e0a8dd73cfc9e1cfa32f5f7b`; pinned-current `100644:0011965a9e4f075a0377ea3518bd1fabf8f5dabb`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | test_http_binary_artifact_get_returns_complete_payload: `-416,0+416,1`
- A | test_mcp_binary_artifact_response_is_metadata_only: `-439,1+440,1`

### D560 tests/test_vision_artifacts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:4a116a185fa183f62a18a1069ffe613c09c5b200`; original `100644:c6f8e8ea0ce8511e776acd1c3ff7452bb9320013`; pinned-current `100644:0011965a9e4f075a0377ea3518bd1fabf8f5dabb`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- A | test_http_binary_artifact_get_returns_complete_payload: `-411,1+411,5`, `-416,1+420,5`
- U | test_mcp_binary_artifact_response_is_metadata_only: `-439,1+447,1`

### D561 tests/test_vision_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 8:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7065c569629d974445bb6b13e55402c8f06acb93`; original `100644:50fa4fc73b0e114dfd1e5e324c0665ac9efd0d6b`; pinned-current `100644:71b34ccffade20927c754959108d8ced424523b8`.

Exact checkpoint/owner witnesses: `S037 / 5b16828e44f5ca0b09c265b2a5a034fe94bbddea / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-2,0+2,1`
- U | <module/text>: `-437,0+438,28`

### D562 tests/test_vision_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7065c569629d974445bb6b13e55402c8f06acb93`; original `100644:965aa9e0b07bfef2c0252b5a026c16aecf484940`; pinned-current `100644:71b34ccffade20927c754959108d8ced424523b8`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-8,0+8,1`
- A | test_vision_result_rejects_confidence_outside_contract: `-81,1+82,1`, `-90,2+91,2`
- U | test_vision_result_rejects_confidence_below_contract: `-189,1+190,1`
- L | test_vision_result_rejects_confidence_below_contract: `-196,1+197,2`
- U | <module/text>: `-265,0+267,104`, `-450,0+556,89`

### D563 tests/test_vision_contracts.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M, 7:T/M, 7:I/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:7065c569629d974445bb6b13e55402c8f06acb93`; original `100644:e89d56046da54946e78d2c2548d007817c8bbbc1`; pinned-current `100644:71b34ccffade20927c754959108d8ced424523b8`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-8,0+8,1`, `-33,0+34,14`, `-90,2+105,178`, `-96,0+287,12`, `-171,0+374,17`
- A | test_vision_result_rejects_confidence_outside_contract: `-81,1+96,1`
- A | test_dom_vision_result_preserves_observation_hypothesis_uncertainty: `-116,1+319,1`
- A | test_vision_result_rejects_confidence_below_zero: `-189,1+409,1`, `-196,1+416,2`
- U | <module/text>: `-450,0+671,35`

### D564 tests/test_vision_service.py

Disposition: `preserved-only-needs-integration`. Occurrences: 0:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ea57e0d42acf0e9af31f0f17f0cd1fc96bcee802`; original `100644:01742a0a8ae2df23ef829d79c5818d74b1554124`; pinned-current `100644:b08c766396dbb038dfa3fc4973e5c991b1060a50`.

Exact checkpoint/owner witnesses: `S001 / 0e4c62c296d59bdd318342a094ebf0d64f2efe76 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-15,0+15,1`, `-16,0+17,14`, `-286,0+304,79`
- U | test_vision_defaults_to_qwen_model_and_requests_json: `-56,0+71,3`

### D565 tests/test_vision_service.py

Disposition: `preserved-only-needs-integration`. Occurrences: 7:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ea57e0d42acf0e9af31f0f17f0cd1fc96bcee802`; original `100644:5fdba830a0a642969370fc3e9ae927f138b1222f`; pinned-current `100644:b08c766396dbb038dfa3fc4973e5c991b1060a50`.

Exact checkpoint/owner witnesses: `S039 / a9d9afe89c017cd47c06c424be7d18ee97ecb192 / true / 556a5ae74cdff82e0fe1baef605fcf54efcaa2c8`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,2`, `-6,0+8,1`, `-46,1+236,16`, `-48,0+253,62`, `-54,2+321,119`, `-286,0+673,248`
- U | <module/text>: `-15,1+18,179`
- A | _services: `-20,1+201,1`, `-22,1+203,10`
- A | test_vision_resolves_network_artifact_with_console_ref_for_tenant: `-179,0+563,1`
- A | test_vision_returns_structured_findings_and_raw_artifact: `-273,0+658,1`, `-284,0+670,1`
- A | test_vision_bounds_runtime_and_parsed_text: `-620,0+1255,1`

### D566 tests/test_vision_service.py

Disposition: `preserved-only-needs-integration`. Occurrences: 6:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ea57e0d42acf0e9af31f0f17f0cd1fc96bcee802`; original `100644:dae34884f09480d4b2b36d5add1cdf555cd9ce1c`; pinned-current `100644:b08c766396dbb038dfa3fc4973e5c991b1060a50`.

Exact checkpoint/owner witnesses: `S088 / 7951ebff15e335ac4a0f9634dd6596152cb10704 / true / 0aebfbd954c8ebdd11a25860053db4f8a5778d59`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,2`, `-6,0+8,1`, `-46,1+69,16`, `-48,0+86,62`, `-54,2+154,119`, `-286,0+572,248`
- U | <module/text>: `-18,0+21,11`, `-260,0+478,66`
- A | _services: `-20,1+34,1`, `-22,1+36,10`
- A | test_vision_resolves_network_artifact_with_console_ref_for_tenant: `-179,0+396,1`
- A | test_vision_returns_structured_findings_and_raw_artifact: `-273,0+557,1`, `-284,0+569,1`
- A | test_vision_bounds_runtime_and_parsed_text: `-620,0+1154,1`

### D567 tests/test_vram_balancer.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:744345d2318ef86275dcc363bf90716bf0e4a9d2`; original `100644:d9e2832899ec776cccb48deb0ac0323f46fae0e8`; pinned-current `100644:175fc42c6ac028d29e5cf93107d75e5ecb350359`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-3,0+3,1`, `-26,0+27,174`
- U | <module/text>: `-64,0+239,82`

### D568 tests/test_vram_balancer.py

Disposition: `integrated-current`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:acb7cd75628b93fd6374633490e3f956fb4a6be0`; original `100644:175fc42c6ac028d29e5cf93107d75e5ecb350359`; pinned-current `100644:175fc42c6ac028d29e5cf93107d75e5ecb350359`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-3,0+3,1`, `-37,0+38,163`, `-75,0+239,106`

### D569 tests/test_work_handoff_acceptance.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e442ac03dfb8e46977a0c0cdc9f9274f918636c1`; original `100644:bfff04640815b31efeeac712b49eb2b4116e277a`; pinned-current `100644:5ba2fdd7716a0ad8ee8e26e790b4ff1e10d4534f`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-5,0+5,4`, `-11,0+15,8`, `-13,0+25,4`, `-14,0+30,2`, `-625,0+761,410`
- A | _Leases.claim_batch: `-19,1+37,1`
- A | test_recovery_requeues_after_crash_between_journal_clear_and_state_update: `-233,1+251,1`, `-235,0+253,1`, `-236,0+255,2`, `-242,0+263,6`, `-248,0+275,2`, `-251,0+280,7`, `-267,0+303,2`, `-274,0+312,1`
- A | test_restart_rolls_back_patch_using_postimage_journaled_before_mutation: `-286,1+325,1`, `-303,0+342,1`
- A | test_process_crash_after_patch_write_recovers_from_persisted_journal: `-319,0+359,100`
- A | test_recovery_rollback_failure_fails_closed_and_preserves_journal: `-327,1+467,1`
- A | test_rollback_accepts_chained_same_path_postimages: `-402,7+542,5`
- A | test_crash_recovery_conflict_fails_closed_without_partial_restore: `-432,3+570,2`, `-436,3+573,2`

### D570 tests/test_work_orchestrator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 11:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e1c8dcb13bb646c7a7daca081cfd91bcfd691188`; original `100644:7d40ccd89fb241bc6ca1b0beb6a2158d8b935328`; pinned-current `100644:9ea7f9f9e5d1acde52070abc3acb16959bbc1374`.

Exact checkpoint/owner witnesses: `S001 / 0e4c62c296d59bdd318342a094ebf0d64f2efe76 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-15,0+15,1`, `-298,0+311,71`, `-518,0+602,132`
- A | FakeArtifacts.get: `-24,0+25,11`
- U | FakeLeases.claim_batch: `-27,1+39,1`
- A | test_work_order_rolls_back_when_validation_fails: `-289,0+301,1`, `-290,1+303,1`

### D571 tests/test_work_orchestrator.py

Disposition: `preserved-only-needs-integration`. Occurrences: 10:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e1c8dcb13bb646c7a7daca081cfd91bcfd691188`; original `100644:ee5d3be188656cbf015f6f3ff9db2afb52fb996a`; pinned-current `100644:9ea7f9f9e5d1acde52070abc3acb16959bbc1374`.

Exact checkpoint/owner witnesses: `S031 / c6c38c5efe69a1f79cad9ddfbdb86d091f275ae3 / true / f99619a4658692b2d15d40a07f2176891c72cffa`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-15,0+15,1`, `-298,0+447,71`
- A | FakeArtifacts.get: `-24,0+25,11`
- A | FakeLeases.claim_batch: `-27,1+39,2`
- U | <module/text>: `-73,0+86,11`, `-286,0+310,124`
- A | test_work_order_rolls_back_when_validation_fails: `-289,0+437,1`, `-290,1+439,1`

### D572 tools/benchmark_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 42:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:3df95f5ef82eb33c935ebcfc30ab7ae6b1c58c69`; original `100644:4f1408641ee8174c5a3800f98c561e5512bfaa27`; pinned-current `100644:9346e0f6ad9440b157b6d7dfd1ca72625d970310`.

Exact checkpoint/owner witnesses: `S050 / 72ddb03218ccdb6c9bfcc03d5452cb17ffe8dca1 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-21,0+21,1`, `-71,0+72,43`, `-729,0+773,6`, `-754,1+807,3`, `-763,0+818,37`
- L | <module/text>: `-678,1+722,1`, `-689,1+733,1`, `-700,1+744,1`, `-711,1+755,1`, `-718,1+762,1`, `-750,1+800,4`
- A | _t12_scenario_report: `-833,0+925,4`, `-835,1+931,6`, `-845,4+946,0`, `-871,0+968,2`, `-875,0+974,3`, `-975,0+1077,1`, `-980,0+1083,1`, `-992,0+1096,1`, `-993,0+1098,6`, `-998,0+1109,9`, `-999,0+1119,6`
- A | _run_t12_matrix: `-1060,1+1186,1`, `-1077,0+1203,1`, `-1078,0+1205,1`, `-1083,0+1211,7`, `-1105,1+1240,1`, `-1108,1+1243,39`, `-1124,0+1297,8`, `-1138,0+1319,2`, `-1142,0+1325,1`, `-1215,0+1399,59`, `-1227,0+1470,2`, `-1238,0+1483,4`, `-1275,1+1524,1`, `-1281,0+1530,11`
- U | run_benchmark: `-1366,1+1626,1`, `-1370,2+1630,2`, `-1380,0+1640,3`, `-1815,11+2078,0`, `-1827,0+2079,1`, `-1832,0+2085,2`, `-1833,1+2088,4`, `-1839,1+2097,4`, `-1845,1+2106,37`

### D573 tools/benchmark_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 21:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:773392339f1d4e874ff0c6ce39209c96e3f38e0a`; original `100644:71487200bf84af3199c04ce4b5f57c5a6f9b3222`; pinned-current `100644:9346e0f6ad9440b157b6d7dfd1ca72625d970310`.

Exact checkpoint/owner witnesses: `S067 / 6c343bf186c2d6bcad5ad9c9f02341fe1b7841fb / true / 80a9cbb6765ed1f2d129bf16a0e7bc6651f8b406`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-37,0+37,2`, `-57,0+59,14`
- L | run_benchmark: `-744,0+760,5`
- U | run_benchmark: `-925,1+946,1`, `-928,0+949,2`, `-935,0+958,11`, `-936,0+970,1`, `-938,0+973,11`, `-940,2+986,6`, `-947,0+997,1`, `-963,1+1014,1`, `-971,0+1022,2`, `-991,0+1044,1`, `-1085,0+1139,1`

### D574 tools/benchmark_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:773392339f1d4e874ff0c6ce39209c96e3f38e0a`; original `100644:8a47c60b21771d38610729154c0b1169b2586671`; pinned-current `100644:9346e0f6ad9440b157b6d7dfd1ca72625d970310`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,1+12,1`, `-14,0+14,1`, `-15,1+16,1`, `-28,0+31,1`, `-41,0+45,5`, `-42,0+51,8`, `-52,0+69,2`, `-71,0+96,208`, `-99,1+332,546`, `-195,0+982,533`, `-354,0+1810,147`, `-446,0+2183,209`, `-466,0+2412,4`, `-519,8+2478,0`, `-675,0+2626,168`, `-1233,0+4963,861`
- U | <module/text>: `-21,1+22,3`, `-55,1+74,3`, `-57,0+78,4`, `-1175,1+4664,202`
- A | _plan_grade_reasons: `-103,1+881,1`, `-106,2+884,2`, `-146,0+924,9`
- A | _comparison_repetition_count: `-158,1+945,1`, `-160,2+947,2`
- A | compare_records: `-198,1+1518,1`, `-209,3+1529,23`, `-213,1+1553,5`, `-253,0+1597,2`, `-256,0+1602,9`, `-267,1+1622,1`, `-280,0+1635,10`, `-283,5+1648,3`, `-290,1+1653,0`, `-298,9+1660,49`, `-308,1+1710,10`, `-310,0+1721,1`, `-311,4+1723,3`, `-318,0+1729,14`, `-319,1+1744,13`, `-321,1+1758,1`, `-327,0+1764,1`, `-329,1+1767,7`, `-334,2+1778,3`, `-337,1+1782,1`, `-339,6+1784,14`, `-346,1+1799,1`, `-353,0+1806,3`
- A | _measure_stage: `-368,0+1971,2`, `-373,0+1978,1`, `-376,0+1982,1`, `-380,0+1987,1`, `-393,0+2001,1`, `-394,0+2003,9`, `-403,0+2021,1`, `-407,0+2026,6`
- A | _measure_stage_regimes: `-416,0+2041,1`, `-417,0+2043,2`, `-418,0+2046,3`, `-419,2+2050,87`, `-427,1+2143,5`, `-436,0+2156,17`
- A | _synthetic_source: `-467,1+2417,10`
- U | run_benchmark: `-683,1+2802,1`, `-688,0+2807,3`, `-711,0+2833,8`, `-751,5+2886,8`, `-919,5+4257,31`, `-925,1+4289,1`, `-928,0+4292,3`, `-934,5+4301,11`, `-941,1+4314,34`, `-946,0+4352,7`, `-947,0+4360,1`, `-954,0+4370,1`, `-963,1+4384,2`, `-967,0+4389,1`, `-975,0+4403,1`, `-991,0+4426,4`, `-1055,1+4502,1`, `-1067,1+4514,1`, `-1074,0+4521,10`, `-1085,1+4542,13`, `-1089,2+4558,2`, `-1092,1+4561,1`, `-1107,0+4576,2`, `-1157,0+4644,2`
- L | run_benchmark: `-694,3+2816,3`, `-703,1+2825,1`, `-747,0+2877,5`, `-797,1+2935,1`, `-809,0+2947,1`, `-812,3+2951,116`, `-817,1+3069,2`, `-820,1+3073,3`, `-823,1+3078,12`, `-826,3+3092,10`, `-838,0+3111,85`, `-846,7+3204,728`, `-873,7+3952,141`, `-882,2+4095,29`, `-892,0+4132,43`, `-894,2+4177,2`, `-897,3+4180,13`, `-906,3+4199,27`, `-913,0+4230,12`, `-914,1+4243,9`, `-916,2+4253,3`, `-949,0+4363,2`, `-957,0+4374,4`, `-958,1+4379,1`, `-971,0+4394,5`, `-983,0+4412,6`, `-1011,3+4450,11`, `-1034,1+4481,1`, `-1041,1+4488,1`, `-1108,1+4579,11`, `-1116,2+4597,2`, `-1130,0+4611,4`, `-1139,0+4624,2`
- U | main: `-1182,2+4872,2`, `-1186,2+4876,2`, `-1189,1+4879,2`, `-1191,0+4882,2`, `-1213,8+4919,30`
- L | main: `-1192,1+4885,12`, `-1198,2+4902,4`, `-1230,0+4958,2`

### D575 tools/benchmark_surfaces.py

Disposition: `preserved-only-needs-integration`. Occurrences: 38:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:773392339f1d4e874ff0c6ce39209c96e3f38e0a`; original `100644:e0c64170d2ca4704db3da7b96a7e8a49f37c54db`; pinned-current `100644:9346e0f6ad9440b157b6d7dfd1ca72625d970310`.

Exact checkpoint/owner witnesses: `S002 / 91b73fc9bd20ae0f6bcf81fff20157cf62d2ce06 / true / 5283a418ba0e3b14a81e46a2219818ebf9f123cf`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-12,1+12,1`, `-21,0+22,3`, `-28,0+32,1`, `-41,0+46,5`, `-42,0+52,8`, `-52,0+70,2`, `-71,0+97,208`, `-99,1+333,546`, `-195,0+983,533`, `-354,0+1811,147`, `-446,0+2184,209`, `-466,0+2413,4`, `-473,1+2433,24`, `-519,8+2514,0`, `-675,0+2662,168`
- U | <module/text>: `-14,0+14,1`, `-55,1+75,3`, `-57,0+79,4`, `-1175,1+4714,340`, `-1233,0+5154,826`
- A | _plan_grade_reasons: `-103,1+882,1`, `-106,2+885,2`, `-146,0+925,9`
- A | _comparison_repetition_count: `-158,1+946,1`, `-160,2+948,2`
- A | compare_records: `-198,1+1519,1`, `-209,3+1530,23`, `-213,1+1554,5`, `-253,0+1598,2`, `-256,0+1603,9`, `-267,1+1623,1`, `-280,0+1636,10`, `-283,5+1649,3`, `-290,1+1654,0`, `-298,9+1661,49`, `-308,1+1711,10`, `-310,0+1722,1`, `-311,4+1724,3`, `-318,0+1730,14`, `-319,1+1745,13`, `-321,1+1759,1`, `-327,0+1765,1`, `-329,1+1768,7`, `-334,2+1779,3`, `-337,1+1783,1`, `-339,6+1785,14`, `-346,1+1800,1`, `-353,0+1807,3`
- A | _measure_stage: `-368,0+1972,2`, `-373,0+1979,1`, `-376,0+1983,1`, `-380,0+1988,1`, `-393,0+2002,1`, `-394,0+2004,9`, `-403,0+2022,1`, `-407,0+2027,6`
- A | _measure_stage_regimes: `-416,0+2042,1`, `-417,0+2044,2`, `-418,0+2047,3`, `-419,2+2051,87`, `-427,1+2144,5`, `-436,0+2157,17`
- A | _synthetic_source: `-467,1+2418,10`
- A | _build_synthetic_repo: `-479,0+2462,1`, `-481,1+2465,8`, `-484,4+2475,6`, `-497,2+2490,4`
- L | run_benchmark: `-681,0+2836,1`, `-683,1+2839,1`, `-691,0+2850,2`, `-694,3+2855,3`, `-703,1+2864,1`, `-733,2+2902,7`, `-747,0+2921,5`, `-797,1+2979,1`, `-809,0+2991,1`, `-812,3+2995,116`, `-817,1+3113,2`, `-820,1+3117,3`, `-823,1+3122,12`, `-826,3+3136,10`, `-838,0+3155,85`, `-846,7+3248,728`, `-873,7+3996,141`, `-882,2+4139,29`, `-892,0+4176,43`, `-894,2+4221,2`, `-897,3+4224,13`, `-906,3+4243,27`, `-913,0+4274,12`, `-914,1+4287,9`, `-916,2+4297,3`, `-949,0+4407,2`, `-957,0+4418,4`, `-958,1+4423,1`, `-971,0+4438,5`, `-983,0+4456,6`, `-1011,3+4494,11`, `-1034,1+4525,1`, `-1041,1+4532,1`, `-1074,0+4565,14`, `-1089,2+4607,3`, `-1092,1+4611,1`, `-1108,1+4629,11`, `-1116,2+4647,2`, `-1130,0+4661,4`, `-1139,0+4674,2`
- U | run_benchmark: `-688,0+2844,3`, `-711,0+2872,8`, `-751,5+2930,8`, `-919,5+4301,31`, `-925,1+4333,1`, `-928,0+4336,3`, `-934,5+4345,11`, `-941,1+4358,34`, `-946,0+4396,7`, `-947,0+4404,1`, `-954,0+4414,1`, `-963,1+4428,2`, `-967,0+4433,1`, `-975,0+4447,1`, `-991,0+4470,4`, `-1055,1+4546,1`, `-1067,1+4558,1`, `-1085,1+4590,14`, `-1107,0+4626,2`, `-1157,0+4694,2`
- L | main: `-1179,1+5057,1`, `-1182,2+5060,3`, `-1186,2+5065,2`, `-1192,1+5074,12`, `-1198,2+5091,4`, `-1230,0+5149,2`
- U | main: `-1189,1+5068,2`, `-1191,0+5071,2`, `-1213,8+5108,32`

### D576 tools/doctor.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:00f759b58bab05e40927700849a175e6df8c8dec`; original `100644:094a7235c0271de538ce807d5aa0ef49da2179cc`; pinned-current `100644:197adeaea31e0de26dd0332ce973fa58753cd46c`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-112,7+112,0`, `-277,1+270,0`
- U | format_doctor_report: `-373,1+365,1`

### D577 tools/doctor.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:00f759b58bab05e40927700849a175e6df8c8dec`; original `100644:c12f6fd7a55dc82d0a7c20528c96cd91831f4fb7`; pinned-current `100644:197adeaea31e0de26dd0332ce973fa58753cd46c`.

Exact checkpoint/owner witnesses: `S005 / 2458f72c2ae6c7a964d4ff5b4d664b65ea98be9f / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-111,7+111,140`, `-275,1+433,1`, `-277,1+435,6`
- L | <module/text>: `-120,1+253,8`, `-122,0+262,10`, `-123,1+273,5`, `-131,2+285,6`, `-279,1+442,1`
- L | format_doctor_report: `-363,3+526,0`
- U | format_doctor_report: `-370,21+530,2`

### D578 tools/hubctl.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce936538b88167a688de0f21d4101af4ba883e81`; original `100644:67b263f536f57af909d26710a49ed237b395c99b`; pinned-current `100644:b1f0d690df8dd6ee446c02e463268e68aa6187b7`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | main: `-158,1+158,1`

### D579 tools/hubctl.py

Disposition: `preserved-only-needs-integration`. Occurrences: 17:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce936538b88167a688de0f21d4101af4ba883e81`; original `100644:8453125ee8ec79ddf3a83bfec1a9ce6019c5db96`; pinned-current `100644:b1f0d690df8dd6ee446c02e463268e68aa6187b7`.

Exact checkpoint/owner witnesses: `S072 / 4aa2edef7f788602da59ab7cfdf5015cd1b304cb / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | main: `-120,1+120,2`, `-138,0+139,40`

### D580 tools/hubctl.py

Disposition: `merged-reconciled-with-concretehunkproof`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce936538b88167a688de0f21d4101af4ba883e81`; original `100644:e13948871c51fbecac7a336370f5ab1cb36b4b85`; pinned-current `100644:b1f0d690df8dd6ee446c02e463268e68aa6187b7`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-22,0+22,1`, `-46,0+47,77`
- A | status: `-34,2+35,2`
- L | main: `-120,1+198,2`, `-138,0+217,20`, `-338,1+437,1`, `-340,0+439,7`, `-345,0+451,4`, `-371,0+481,4`

### D581 tools/hubctl.py

Disposition: `preserved-only-needs-integration`. Occurrences: 4:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:ce936538b88167a688de0f21d4101af4ba883e81`; original `100644:e4792cf6f1cc1244fb5030e2d9276b5e28e7dbbc`; pinned-current `100644:b1f0d690df8dd6ee446c02e463268e68aa6187b7`.

Exact checkpoint/owner witnesses: `S015 / 938a96ae7c4db791be3f3e266f64f6d468f07f9a / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-8,0+8,1`, `-9,0+10,1`, `-46,0+49,124`
- L | <module/text>: `-22,0+24,1`
- A | status: `-34,2+37,2`
- L | main: `-120,1+247,2`, `-371,0+539,4`
- U | main: `-138,0+266,27`, `-338,1+493,1`, `-340,0+495,9`, `-342,1+506,1`, `-345,1+509,5`, `-392,1+564,1`

### D582 tools/selftest.py

Disposition: `integrated-current`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:b98ea7e2d5fd44ed51650f7669ecd9547696b6b2`; original `100644:76b1b04740496342afc845816b5bb1a0440c5f01`; pinned-current `100644:76b1b04740496342afc845816b5bb1a0440c5f01`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | main: `-90,1+90,1`

### D583 tools/service.py

Disposition: `integrated-current`. Occurrences: 19:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:c6db73793140190d8e49fc08ea18f7a6d2deab6c`; original `100644:ce0eeb7de343a4ee196834743eb4abfd65d66648`; pinned-current `100644:ce0eeb7de343a4ee196834743eb4abfd65d66648`.

Exact checkpoint/owner witnesses: `S022 / 708282ff64bb345a794e364b1c765521ee7bc876 / true / 2d2d04b38846e48e7cbe7faf152f970bd043c4c5`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-17,1+17,1`, `-21,1+21,1`, `-88,1+93,29`, `-192,2+228,20`
- B | run: `-42,0+42,2`
- B | spawn_detached: `-55,1+57,1`
- B | supervisor_pid: `-86,1+88,4`
- B | kill_supervisor: `-120,14+153,6`
- B | hub_pid: `-140,1+165,4`, `-142,1+170,2`
- B | request_graceful_hub_stop: `-147,1+176,3`
- B | managed_service_running: `-170,1+201,1`, `-173,1+204,8`
- B | kill_hub: `-175,10+213,6`
- B | stop_managed_ollama: `-186,1+220,1`, `-188,3+222,5`
- B | native_stop: `-196,1+250,2`, `-199,1+254,5`, `-203,7+262,35`
- B | native_start: `-215,1+302,1`, `-225,1+312,1`
- B | main: `-378,1+465,7`, `-380,1+473,9`

### D584 tools/setup.py

Disposition: `integrated-current`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:596b334da024e8cc41c47c3a22cb30a4109596e2`; original `100644:3414a79cd1984cde7427d01d02b19907be19b56a`; pinned-current `100644:3414a79cd1984cde7427d01d02b19907be19b56a`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-61,0+61,50`
- B | main: `-707,0+757,1`, `-708,0+759,7`, `-843,5+901,4`, `-859,0+916,4`

### D585 tools/surface_inventory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e5cd5bbe2983cdfb16d80b47f4c2a23f1d749517`; original `100644:d4c3e353d774ac844a2b325fa785d13d3fd6e5cf`; pinned-current `100644:ea1698073c7f76ff8d3289647d1a9663aa8517b2`.

Exact checkpoint/owner witnesses: `S007 / 57ee7a4928ed4c1467bed7663cea62e54b6e515b / true / 9ea85e2cf3d6476fea2f8d0e57e77f1a45b7e88a`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | <module/text>: `-9,0+9,1`, `-539,0+605,80`
- U | <module/text>: `-33,0+34,1`, `-874,0+1021,979`
- L | _mcp_action_handlers: `-172,1+174,1`, `-209,2+211,38`, `-228,0+266,2`, `-239,0+279,1`
- L | _extract_mcp: `-292,0+333,2`, `-295,0+338,1`
- U | _generated_mcp_schemas: `-365,0+409,22`
- U | _merge_dynamic_routes: `-573,0+719,1`
- L | collect_inventory: `-916,0+2042,3`, `-950,0+2080,3`, `-959,1+2092,4`, `-980,0+2116,6`
- U | collect_inventory: `-932,0+2061,1`, `-1012,0+2154,11`
- L | coverage_rows: `-1234,2+2387,3`, `-1260,0+2418,2`, `-1261,0+2421,7`
- U | coverage_rows: `-1249,1+2403,1`, `-1251,1+2405,5`
- U | _findings: `-1301,0+2468,1`, `-1324,1+2500,4`
- L | _findings: `-1309,0+2477,5`, `-1311,0+2484,3`, `-1334,0+2513,5`, `-1337,1+2521,4`, `-1365,0+2552,57`, `-1528,0+2772,8`
- A | render_coverage: `-1539,1+2791,2`, `-1546,1+2799,1`, `-1563,1+2816,1`, `-1574,0+2827,1`
- L | main: `-1634,3+2888,2`, `-1638,2+2891,2`, `-1643,1+2896,1`

### D586 tools/surface_inventory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 33:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e5cd5bbe2983cdfb16d80b47f4c2a23f1d749517`; original `100644:efe3cc29ac9d17f2a7c40e4b94554cdbfc027877`; pinned-current `100644:ea1698073c7f76ff8d3289647d1a9663aa8517b2`.

Exact checkpoint/owner witnesses: `S053 / 3dc82bba6dcfb7653bb61fa1086af8194ead2aaa / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- L | collect_inventory: `-912,0+912,3`, `-922,1+925,1`, `-927,2+930,2`
- U | collect_inventory: `-934,1+937,2`
- U | _findings: `-1309,0+1313,3`, `-1310,1+1317,15`, `-1321,1+1342,1`, `-1323,2+1344,7`, `-1331,3+1357,3`, `-1337,1+1363,1`

### D587 tools/surface_inventory.py

Disposition: `preserved-only-needs-integration`. Occurrences: 3:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e5cd5bbe2983cdfb16d80b47f4c2a23f1d749517`; original `100644:fa5614e27a9a23519c585237e0593a397b18fcd5`; pinned-current `100644:ea1698073c7f76ff8d3289647d1a9663aa8517b2`.

Exact checkpoint/owner witnesses: `S042 / 974fed0d66f19421b3ceec100565316f97213d79 / true / f57947215fd48c37f14a7325b4651be836de553f`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- U | <module/text>: `-33,1+33,30`, `-344,0+369,46`, `-874,0+1103,784`
- L | <module/text>: `-46,4+75,0`, `-615,0+690,67`, `-835,1+1043,14`
- A | _dynamic_route_registry_drift: `-542,1+613,1`
- L | _merge_dynamic_routes: `-567,0+638,8`
- U | _merge_dynamic_routes: `-573,1+652,2`, `-575,7+655,2`
- A | _extract_client: `-626,0+768,5`, `-627,0+774,47`, `-628,1+822,1`, `-630,5+824,0`, `-636,0+825,15`, `-658,1+862,1`, `-667,1+871,5`
- A | _extract_manifests: `-841,1+1062,7`, `-845,1+1072,1`, `-850,1+1077,3`
- U | collect_inventory: `-880,0+1893,7`, `-1012,0+2030,8`
- L | collect_inventory: `-983,1+2003,1`, `-985,3+2005,1`
- L | coverage_rows: `-1234,2+2260,3`
- U | coverage_rows: `-1249,1+2276,1`, `-1251,1+2278,5`, `-1257,4+2288,15`
- U | _findings: `-1295,0+2337,4`, `-1299,1+2345,10`, `-1301,0+2356,1`, `-1303,1+2359,5`, `-1528,0+2588,6`
- U | render_coverage: `-1539,1+2605,1`, `-1546,1+2612,1`
- L | render_coverage: `-1574,0+2640,1`

### D588 tools/telemetry_report.py

Disposition: `integrated-current`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:a503aad18950019d168147981fdd66dbc6aa5818`; original `100644:0706eb0a11009cf592868118125718e6d62f810f`; pinned-current `100644:0706eb0a11009cf592868118125718e6d62f810f`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | main: `-115,1+115,1`

### D589 tools/uninstall.py

Disposition: `integrated-current`. Occurrences: 3:T/M, 43:T/M. Commits: immutable stash provenance row for EVERY label above; T uses stash SHA, I index SHA.

Base `100644:e7ce761cd9f5d682fb07e84902b16379033e134b`; original `100644:a670eca7647b58288173ea2d8b1ad27880dfefe6`; pinned-current `100644:a670eca7647b58288173ea2d8b1ad27880dfefe6`.

Exact checkpoint/owner witnesses: `S000 / 4891878b7cd887132cfaa8fc3d26f0bca3840702 / true / none`. Root merged snapshot `7c932b6f31d81a5c6e331e7537d687fb0c8d9c12`.

- B | <module/text>: `-22,1+22,1`

## Committed unfinished handoff

Source adoption remains unfinished: preserved-only deltas and disjoint owner queues need separately authorized implementation/behavioral disposition. This commits unfinished evidence, NOT source fixes. No full suite/runtime receipt. Final document commit SHA, exact staged path and clean/unmerged Git checks reported in chat; a document cannot embed its own containing commit SHA.
