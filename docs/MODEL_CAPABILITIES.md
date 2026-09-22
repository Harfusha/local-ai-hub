# Local model capability matrix

The Hub keeps every local model advisory. The matrix controls prompt scope and
expected work; it does not discard a model response. A weak response remains
visible with `semantic_quality` and `quality_warning` metadata.

| Model | Good for | Must not be used as |
| --- | --- | --- |
| `qwen2.5-coder:0.5b` | preprocessing, extraction, classification, compression | root-cause analysis, cross-file reasoning, architecture, security decisions, edits |
| `qwen2.5-coder:1.5b` | bounded extraction, summaries, single-file explanations, checklists | root-cause analysis, cross-file reasoning, architecture, security decisions, edits |
| `qwen2.5-coder:3b` | bounded review, test plans, simple patch plans, comparisons | architecture decisions, high-risk migrations, security decisions, edits |
| `qwen2.5-coder:7b` | root-cause analysis, cross-file reasoning, diff review, patch/test plans | security decisions, final verification, edits |
| `qwen3-vl:4b` | visual review, UI observations, accessibility observations | source-only reasoning, security decisions, edits, final verification |
| `qwen3.5:9b` | heavy reasoning, cross-file review, patch plans, visual review | edits, security decisions, final verification |

## Profile routing

| Profile | Preprocessing | Fast/simple | Ordinary/involved | Hard reasoning | Extreme reasoning | Vision |
| --- | --- | --- | --- | --- | --- | --- |
| `integrated` | `qwen2.5-coder:0.5b` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | none | `qwen3-vl:4b` |
| `balanced` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen3.5:9b` |
| `high` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen3.5:9b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen3.5:9b` |
| `max` | `qwen2.5-coder:1.5b` | `qwen2.5-coder:3b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` |

The integrated profile never selects `qwen3.5:9b`; the 9B model is reserved for
the balanced profile's extreme reasoning and vision routes.

## Static operation contracts

`local_ai_task`, named subagent profiles, `review`, `review_diff`,
`second_opinion`, `compress` and speculative drafting use the shared prompt
builder in `src/local_ai_hub/prompt_contracts.py`. The builder supplies:

- the operation-specific goal;
- task, acceptance criteria, evidence IDs, changed paths and revision;
- static facts before free-form context;
- required `SUMMARY`, `EVIDENCE`, `ANALYSIS`, `LIMITATIONS` and `NEXT` sections;
- an explicit no-invention rule for paths, symbols, line numbers, APIs and tests.

The `integrated` hardware profile receives the same contract with a bounded
single-pass instruction. It does not trigger a slow model cascade.

## Quality behavior

Semantic quality checks are advisory. If a response mentions unrelated paths,
has an unsupported location, is empty, queued or malformed, the Hub keeps the
response and adds `semantic_quality`, `quality_warning` and `bypass_reason`.
The response is not converted into `success=false` and is never silently lost.

## Benchmark interpretation

The text evaluation suite reports bounded response evidence (`status`, elapsed
time, output size, token estimate, SHA-256 and a short preview) and preserves
runtime errors per case. `success=true` means that the benchmark runner
completed; it does not mean that every model case passed.

If a model is configured only for the `vision` role, a text suite reports
`status=role_mismatch` instead of calling that model through the wrong route.
In the balanced profile, `qwen3.5:9b` serves both vision and extreme reasoning;
ordinary reasoning remains on the 7B tier, so a text benchmark must distinguish
the requested complexity before judging model quality.

Hardware measurements with fewer than two generated tokens have no composite
score. Missing models, provider errors and empty responses are failures with
explicit diagnostics, never synthetic successful one-token measurements.
