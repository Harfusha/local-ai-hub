# T10 source acceptance diff + impact — 2026-10-02

## Candidate result

Candidate six-module T10 selector previously passed **30 in 4.81s**. Current source/test SHA-256 values exactly match that receipt. This is candidate evidence; root has not run this selector. No test or benchmark ran in this continuation.

## Concrete diff

[Candidate-only unified diff](t10-source-acceptance-diff-20261002.patch), SHA-256 `61BF1FEF1B820B0296638F3B65A48890661348B7A39CA06C330E4C6FC6874922`. Base is candidate HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`. Included paths: `code_index.py`, `preprocess.py`, `repo_tools.py`, and both defaults files. It is **not root-applicable**: root contains other owner changes and distinct hashes. Do not apply wholesale.

T10 source delta: derived-schema guard; function-owned fallback call edges and declaration filtering; fresh snapshot reads and cache invalidation; deleted-path edge cleanup; callers/callees call-edge filtering; independent bounded Python fallback count plus metrics; two preprocess invalidate-before-hash sites; matching default in both TOML files.

Static impact: indexing/freshness paths may reread changed files rather than reuse stale snapshot; stale derived rows are removed; query caches clear on index mutation; fallback search is bounded and exposes scan-limit metadata. No public service signature change identified in these candidate hunks.

## Static verification

Python AST parse passed for 9 T10 files. Both TOML files parsed and are byte-equal (SHA-256 `418B62992343D074C33BB6DF7D2E8139F2B0DDCD6B47CDB1A4E94971A502D57B`). Candidate source/test hashes match prior 30-pass receipt. `git diff --check` exited 0 (Git printed line-ending normalization warnings only).

T21 files kept outside diff: `project_config.py`, `services.py`, `tool_agent.py`, project configuration docs/tests. Mixed/shared ownership stays excluded.

## Remaining gates

Root hash snapshot still has 0 drift across 16 pinned paths; T10 made no root writes or root test runs. Root selector command remains in the [root acceptance handoff](t10-root-acceptance-handoff-20261002.md). T20 has only tentatively queued T10 for slot 18 after T11/11, T05/12, T03/13, T21/14, T01/15, T08/16, T17/17. No explicit grant yet. T02 owns `hub_impact_latency` and paired 100k measurement; no valid performance receipt. T19/T20 release gates remain open.


## Patch integrity recheck

Regenerated `git diff --binary` for the five listed paths byte-matches the saved patch (SHA-256 `61BF1FEF1B820B0296638F3B65A48890661348B7A39CA06C330E4C6FC6874922`). Current candidate source hashes match manifest. Patch has no `/api/context/pack` or `context_pack_paths` references and omits HTTP/MCP/services/T21 path-hint consumers. Root untouched; no test/benchmark.
