# T21 root-current core project config packet

Status: immutable handoff patch; generated in the managed T21 worktree; not applied to root.

## Bases

- T21 worktree: `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub`
- T21 HEAD: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`
- Root checkout: `C:\Users\Adam\.local-ai-hub`
- Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`
- Patch: `T21-root-current-core-project-config-20261005.patch`
- Patch SHA-256: `9307CB6025A881DC860A45C8560E9C7A1CF29FE89B98B483ACE936A4F08EDD33`
- Patch scope: 3 T21-owned files; 157 insertions, 8 deletions.

## Root-current preimage -> patch postimage SHA-256

| Path | Preimage | Postimage |
|---|---|---|
| `src/local_ai_hub/project_config.py` | `00E80B1342E5E70A66FA8955D95553127E913F56EC693CF527B6AC96053BDBDE` | `1C004FA51B9D18737EFAF2EB63F3648814DB68B7FBF7FE348012917EDC07B641` |
| `tests/test_project_config.py` | `90A66B610B84FADDF178147321362DB91139FFCE0FDC680E01AAD9FBD1866270` | `07E063C2EC00A94BE82A6D7F2C4ADAAD39BB117BAFB5873DEC904347F8AABDC9` |
| `tests/test_project_path_hints.py` | `92EC33C9BB69D75F50ACB9EFBC501C541574D877128112444458CD11576AA5C7` | `237E00CF3E723A5EC010458277DF7810205196CD21DA0C448F5E59D915AC31C0` |

## Missing T21 behavior

- Preserve hint origin: saved hints validated as learned; request/config hints validated as unlearned. Prevents request hint with partial optional provenance from being rejected as a stored learned hint.
- Directory traversal now resolves path override specificity across lexical alias and resolved target together. Root already has `_path_override_for_candidates`; patch reuses it.
- Adds four core regression/schema tests: 256 KiB overlay boundary, alias/target directory override specificity, project config precedence, and partial request-hint metadata.

## Already present in root; deliberately not duplicated

Root and T21 AST SHA-256 match for `ProjectSettings` (`B21C34F68BFB0D9D2363AA5216BF9AD09B4B3E0738EB5933AC1BBA764E6B61ED`), `PathHint` (`CFA7717E3431F89CFE32C1C2D78763A0A1CE0CBFAAACC57C6B3084D714895032`), `PathHintUsage` (`B318709B7D5A1BDB7CB2BE5A59D6AEB9D7AFBED47849533EDB4A80C46F10206E`), `resolve_project_config` (`D6C1E6FA2C8F9B968FCF6FB90645F3E0798ABD6D04444D8BCF6AFB23AD119049`), `_resolve_project_config` (`42358BE2B92763CF3252D81D6282504114418BBDE9707C52BC626344F5B63A4D`), and `resolve_project_context` (`876D750A9D2C0C89B36B113F0A3D1410F0A868183DC044FEF0ABBF2E98F36B83`). The `PathHintUsage` telemetry projection also has identical source SHA-256 `24EF71D150A5BE3C98C4568B203560EA14C213C45893F5E876C3FA0213A20AD3`; fields remain `hint_used`, `fallback_used`, `hint_helped` only, with no path/query data.

`ProjectPathHintStore` differs: root-current retains `ensure_schema` and read-only `existing_only` connection behavior. Packet preserves root version; candidate store implementation is not transplanted.

## Adapter handoff

- T09 contract confirmed: `resolve_project_context(root, state_dir)` exposes `root`, `settings`, `config_digest`, `resolution.error_codes`.
- T21 owns resolver/schema and the two test modules in this packet.
- T03/T06/T09/T16/T19 consumer adapters remain with their owners; no adapter paths changed. Exact owner-to-file mappings stay unassigned until owners release them.
- T14 `/api/context/pack` untouched.
- Single-developer durable local project config remains allowed. Telemetry restrictions unchanged.

## Validation receipts

- Candidate command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_project_config.py tests/test_project_path_hints.py`
- Candidate result: **100 passed in 2.19s**; T21 worktree only.
- Root command: `git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error -- C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub\handoff\T21-root-current-core-project-config-20261005.patch`
- Root result: **passed**. `git apply --stat`: 3 files, 157 insertions, 8 deletions.
- Root tests: not run. Root remains unmodified; current SHA-256 values still match each listed preimage.
- No adapter, `/api/context/pack`, root, install, build, or full-suite changes/checks.
