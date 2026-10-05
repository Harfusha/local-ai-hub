# T03 root-current evidence receipt

Source packet: `T03-root-current-sse-source-20261005.patch`  
Patch SHA-256: `4030f95ce922bbe4cee82bd51d8ff647d3f344446b3ea70f7259d9986877bfa8`  
Manifest: `T03-root-current-source-acceptance-20261005.json`  
Manifest SHA-256: `1633c1c8f959536cddec6a6138589c78b3b544301856984aed86c5e64fba83162`

Root: `C:\Users\Adam\.local-ai-hub`  
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`  
Candidate: `C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub`  
Candidate base: `d68ee694c6d3f75db5c1ab2f63497226880e5010`

## Changed paths

The root-current source patch changes exactly:

- `src/local_ai_hub/http_server.py`
- `tests/test_sse_events_stream.py`

The separate test-only live-client packet changes exactly `tests/test_mcp_live_30_client_acceptance.py`; its patch SHA-256 is `c1ca6073878d4400d97a63ff629180883a988d259726affcd6f69ac2bbd434dc`, and its manifest SHA-256 is `0a467cd4a524bf7c07ed8fb4efa878345dc310dd8e0dfb0c584c3473626b928d`.

## Root file images

Preimage and expected patch postimage SHA-256 values come from the verified root snapshot. Root was not patched; actual postimage hashes equal the preimages.

| Path | Root preimage SHA-256 | Expected patch postimage SHA-256 | Actual root postimage SHA-256 |
|---|---|---|---|
| `src/local_ai_hub/operation_contracts.py` | `79abad111dddbca541d0e8e7a439742f54ba431fac51918a704fccb7fbe06930` | `79abad111dddbca541d0e8e7a439742f54ba431fac51918a704fccb7fbe06930` | `79abad111dddbca541d0e8e7a439742f54ba431fac51918a704fccb7fbe06930` |
| `src/local_ai_hub/mcp_server.py` | `88949aaf1660bad4ffa40a3f27614cc0014868c669d633ca1e5e346e58f29e36` | `88949aaf1660bad4ffa40a3f27614cc0014868c669d633ca1e5e346e58f29e36` | `88949aaf1660bad4ffa40a3f27614cc0014868c669d633ca1e5e346e58f29e36` |
| `src/local_ai_hub/http_server.py` | `e736143d9b2c6386a1f70549a6c990cd65f70db409410d553fc00af4aa8c19c9` | `a8949253e023e42d4db432640caf4fbfa3544e1cf1565dfbe969c401f36125ca` | `e736143d9b2c6386a1f70549a6c990cd65f70db409410d553fc00af4aa8c19c9` |
| `src/local_ai_hub/generator.py` | `5ea7feee62e07731a75d31991a3e26a0461fff6d318dea85f2995b405123d11b` | `5ea7feee62e07731a75d31991a3e26a0461fff6d318dea85f2995b405123d11b` | `5ea7feee62e07731a75d31991a3e26a0461fff6d318dea85f2995b405123d11b` |
| `src/local_ai_hub/resilience.py` | `88c16039afc2919bb5e7f8deaf2165ac09c2c064ad496ba15c1fd2ffac2ac67e` | `88c16039afc2919bb5e7f8deaf2165ac09c2c064ad496ba15c1fd2ffac2ac67e` | `88c16039afc2919bb5e7f8deaf2165ac09c2c064ad496ba15c1fd2ffac2ac67e` |
| `tests/test_operation_contracts.py` | `7a22137b1d17c52163f938ae206264d0a788f1481b460b4cab9ef073c8477c88` | `7a22137b1d17c52163f938ae206264d0a788f1481b460b4cab9ef073c8477c88` | `7a22137b1d17c52163f938ae206264d0a788f1481b460b4cab9ef073c8477c88` |
| `tests/test_features.py` | `1d3c99b341eb68c0916621f7b95a71d0c7343f971a59456ee42f702c1a4150d9` | `1d3c99b341eb68c0916621f7b95a71d0c7343f971a59456ee42f702c1a4150d9` | `1d3c99b341eb68c0916621f7b95a71d0c7343f971a59456ee42f702c1a4150d9` |
| `tests/test_sse_events_stream.py` | `b466686507ee84cc83cdb0812a19826e2eb18c033d3be599a23cc71b361801f2` | `c603e6006abdc13ad1d2636182e063caa42755900686edfd2ae70b4edc743a03` | `b466686507ee84cc83cdb0812a19826e2eb18c033d3be599a23cc71b361801f2` |
| `tests/test_mcp_contract_dispatch.py` | `ab81768f86ad19735d5e7cebfd72cc5a05e4a341d867ed6750ea7be6f272c400` | `ab81768f86ad19735d5e7cebfd72cc5a05e4a341d867ed6750ea7be6f272c400` | `ab81768f86ad19735d5e7cebfd72cc5a05e4a341d867ed6750ea7be6f272c400` |

## Commands and results

Root patch applicability check:

```text
git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\e809\.local-ai-hub\handoff\T03-root-current-sse-source-20261005.patch
```

Result: passed. Patch was not applied to root.

Candidate SSE regressions:

```text
$env:PYTHONPATH='src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py -k 'future_cursor or has_more or without_has_more'
```

Result: `5 passed, 26 deselected in 0.42s`.

Root snapshot regression in a temporary copy with the patch applied:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_sse_events_stream.py -k 'future_cursor or replay_has_more or replays_all_bounded_pages'
```

Result: `3 passed, 4 deselected in 0.74s`. The temporary copy was removed; root remained unchanged.

Final live 30-client command recorded in the separate packet:

```text
python -m pytest -q tests/test_mcp_live_30_client_acceptance.py --tb=short
```

Result: `outcome_unknown` after transport failure, request `req_b259c00611e5`. No rerun or native bypass. The harness safety selectors on its final helper revision passed: `python -m pytest -q tests/test_mcp_live_30_client_acceptance.py -k 'launcher or cleanup' --tb=short` → `3 passed, 1 deselected in 0.14s`.

## Limits

Live 30-client acceptance remains unverified (`outcome_unknown`). Earlier live attempts failed for harness defects; those exact results are preserved in the separate live-client manifest. No root tests were run; T20 owns that slot. Root stayed unmodified.
