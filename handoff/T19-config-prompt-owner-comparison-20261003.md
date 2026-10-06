# T19 config/prompt owner comparison — 2026-10-03

## T19 result

Smallest T19 config/prompt delta: **none**. T19's existing portable-config contract and prompts already describe their current candidate boundary. No runtime adapter or root file changed.

## Owner candidates inspected

| Owner | Candidate | Current contract relevant to T19 |
|---|---|---|
| T03 | `t03-contracts-resume/.local-ai-hub`, HEAD `ad622f8a90a81e349e94d3402f297f2995e733b2` | `client.py` candidate exposes `outcome_unknown`; config still comments CodeGraphContext as a code-intelligence backend. |
| T04 | `t04-integration/.local-ai-hub`, HEAD `3658d5056354849ddf17883ed04f807f16cc44c1` | `client.py` candidate classifies `request_not_sent` when request delivery has not started. T19 client does not implement this full contract. |
| T13 | `t13-operational-mode/.local-ai-hub`, HEAD `6050c41ce5510a6de3eaeb674a180560ea404f24` | Operational-mode module exists in owner candidate; it is absent from T19 runtime. T19 install/update prompts identify the target contract as unintegrated. |

T03's CodeGraph config comment conflicts with T19's standalone-only policy. T19 config/docs remain internally consistent; resolve this owner overlap before root integration. T19 prompts also keep T04 and T13 acceptance explicitly pending.

## Evidence

- Portable install simulation and wrapper gates: **4 passed in 0.45s**. Covered dry install copy/defaults, supported host config merge, revision pin guard, and install/update prompt revision requirement.
- The broader T19 independent config/docs/install selector passed **48 tests** in 2.21s.
- T19 CodeGraph tests cover absence from Hub runtime/config/telemetry, standalone `codegraphcontext[gcf]==0.6.13` docs, uninstall preservation, and no Ollama prompt claim.
- No install, service start, network, root write, or runtime-adapter edit was performed. Simulation only.

## Acceptance boundary

T03/T04/T13 parity remains candidate integration work. Clean-host install/update/restart remains unverified. This receipt is not release PASS.
