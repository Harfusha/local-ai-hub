# T01 root-current owner coverage delta v3

Candidate snapshot for T03, T08 Agent OS, T13 mode, and T14 surfaces. This is a T20 handoff, not a root write or final acceptance.

- Candidate HEAD `689165fbe18101feacf5f489847a4890fc27ed1f`; root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root source input SHA pins are listed below. Existing generated MCP schema manifest SHA-256: `AF189139D32645E708586FD78EF9445800561FA4DFA57C8D58E6EAFFD8DE6B10`.
- Candidate inventory module SHA-256: `6513D91FAB541B3B32FC10845F007FF495BD8177D56E34371AA029A19A11A1E2`. Candidate rendering task ID: `01a0d30b-fffc-7810-a1ca-9cdde7be9264`.
- Current root source inventory rows: 685; selected owner rows: 151.
- Row counts and linked selectors are inventory evidence, not pass receipts. Root tests were not run. Candidate-only pytest tests import the candidate and are deliberately not credited to root rows.
- Owner dispositions (behavior-linked selector / metadata only):

| Owner | Rows | Linked selectors | Metadata only |
|---|---:|---:|---:|
| T03 | 25 | 11 | 14 |
| T08 | 105 | 35 | 70 |
| T13 | 14 | 2 | 12 |
| T14 | 7 | 3 | 4 |

- Current root inventory drift: `["missing MCP action handler local_ai_status:brief"]`. Preserve for T03: generated schema advertises `local_ai_status.action=brief`, while static source action literals omit it.
- Candidate full render/patch snapshot is pinned separately in `T01-root-current-surface-delta-20261001-v2.md`; T20 should regenerate from the final integrated root snapshot.
- No root API document write or root `--check` was performed. Prior candidate-only hash and mtime non-write selectors passed 2/2 within the 5-selector receipt; current candidate docs hash remained `4B83315C990B6FC74F3BF89CBB49337CFF9AA085266FE3DA4004EEA72AC80C72` at the start of this continuation.
- No root operation receipt is inferred from candidate-only tests. T20 owns root test serialization, final document generation, and same-environment `--check`.

## Root input SHA-256

- `tools/surface_inventory.py`: `862731FDB1312D2B6A604A1EB7F2559C196EAC11985C032C091633DEA960A85C`
- `src/local_ai_hub/mcp_server.py`: `8EC5C493964419233A349A78ECCA6487A78078B6125A7A328980877B3AA132FB`
- `src/local_ai_hub/operation_contracts.py`: `28DD0FF31AE5F4163BC439768F2C76B513ED3D2A1CF41AF432520D54A9AF7C83`
- `src/local_ai_hub/agent_verification.py`: `06D0D49E77BF54A0B3C6B5470894F53459E7167A6AF5C39EF685732224C2675F`
- `src/local_ai_hub/features.py`: `877EF243D109A62699D7D54CE14097EF9B6859FEC1DA50D7678B69C80FE44C43`
- `src/local_ai_hub/generator.py`: `2147622D0713579F7BE9EEE9890C646D50F932F26687D26BB951A51E560CDFCB`
- `docs/API_COVERAGE.md`: `E3B5A6559C5F0E6ADEC165B6A416E6DE600C7F00B121DA4615B176ABDA397A49`

## Candidate artifacts

- CSV `T01-root-current-owner-coverage-delta-20261001-v3.csv`: SHA-256 `5207D7612DCCCF62DBB242B38468BCD3DBEE827B06DEB6C90443B38B8F33E42B`; 151 rows.
