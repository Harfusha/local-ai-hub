# Local model capability matrix

Unknown tool capability uses an advisory response without tools; the tool-aware agent checks backend capability metadata before advertising local tool schemas. A configured tag does not itself prove support. The selected execution profile is not proof of the context actually used by the backend.

The tool-aware loop caps each run at three model steps and six tool calls, even
when a configured subagent profile requests higher limits. Lower configured
limits still apply.

Semantic model responses remain advisory. Explicitly requested, quality-evaluated bounded
implementation can use the existing work executor with caller-owned file and
command scopes; the primary agent must review its diff, validation and
integration. Select suitable work by task risk and measured quality, not model
size alone. The matrix controls prompt scope and expected work; it does not
discard a model response. Weak semantic responses remain visible with
`semantic_quality` and `quality_warning` metadata.

Bounded work accepts at most eight exact file paths, eight approved commands,
eight plan steps and 1,800 seconds. Each patch rejects rename, copy, binary and
file-mode changes. The deadline requests cooperative model cancellation; late
results are rejected before mutation. It is not a guarantee that an
uncooperative backend stops immediately.

Hugging Face embedding and reranker weights use existing local caches by default.
Missing cache files do not authorize downloads. `models.allow_hf_downloads=true`
explicitly enables network loading; both shipped defaults set it to `false`.
Cached fallback models remain eligible while downloads are disabled.

| Model | Good for | Must not be used as |
| --- | --- | --- |
| `qwen2.5-coder:0.5b` | preprocessing, extraction, classification, compression | root-cause analysis, cross-file reasoning, architecture, security decisions, edits |
| `qwen2.5-coder:1.5b` | preprocessing only | inference, code generation, reviews, reasoning, or edits |
| `qwen2.5-coder:3b` | bounded review, test plans, simple patch plans, comparisons | architecture decisions, high-risk migrations, security decisions, edits |
| `qwen2.5-coder:7b` | root-cause analysis, cross-file reasoning, diff review, patch/test plans | security decisions, final verification, edits |
| `qwen3-vl:4b` | visual review, UI observations, accessibility observations | source-only reasoning, security decisions, edits, final verification |
| `qwen3.5:9b` | heavy reasoning, cross-file review, patch plans, visual review; quality-evaluated bounded implementation through `local_ai_work` | unscoped or unreviewed edits, security decisions, final verification |

Whisper CLI has a separate `transcription` policy: verified official cache weights
are required by default; downloads require `allow_model_downloads=true`. The
cache honors `XDG_CACHE_HOME` or the configured `cache_dir`. Transcription uses
explicit CPU selection; GPU CLI admission is not implemented and non-CPU
requests are rejected. Hash checks are bounded and cancellable. Configured model
names do not establish cached-weight availability, transcription quality or WER.

## Profile routing

| Profile | `background_code` | `fast_code` | `heavy_code` | `reasoning` | `general` | `vision` |
| --- | --- | --- | --- | --- | --- | --- |
| `cpu` | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen2.5-coder:7b` | `qwen3-vl:4b` |
| `integrated` | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen2.5-coder:7b` | `qwen3-vl:4b` |
| `low` | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen2.5-coder:7b` | `qwen3-vl:4b` |
| `balanced` | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen2.5-coder:7b` | `qwen3.5:9b` |
| `high` | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `qwen2.5-coder:7b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` |
| `max` | `qwen2.5-coder:3b` | `qwen2.5-coder:3b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` | `qwen3.5:9b` |

These are profile routing targets from `hardware.py`. They do not prove a model
is installed on a host, and profile selection does not pull models. Runtime
availability must be checked separately.

## Static operation contracts

`local_ai_task`, named subagent profiles, `review`, `review_diff`,
`second_opinion`, `compress` and speculative drafting use the shared prompt
builder in `src/local_ai_hub/prompt_contracts.py`. The builder supplies:

- the operation-specific goal;
- task, acceptance criteria, evidence IDs, changed paths and revision;
- static facts before free-form context;
- required `SUMMARY`, `EVIDENCE`, `ANALYSIS`, `LIMITATIONS` and `NEXT` sections except for `review`, which defaults to a JSON `verdict` and cited `findings` matching the consistency validator; explicit task response formats take precedence;
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
