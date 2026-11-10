# Preprocessing Card Model Evaluation

> Superseded pilot proposal: this draft used synthetic training data and proposed downloading a base model. Current direction uses only cards already stored in the configured Hub index. Do not download, train, or benchmark under this data-preparation task. The reusable scaffold is specified separately in `2026-11-10-local-model-finetuning-scaffold.md`.

## Goal

Measure whether a fine-tuned preprocessing model produces more useful semantic file cards than the configured base model.

## Scope

- Target only the `preprocess:file-card` generation path in `ProjectPreprocessor`.
- The current prompt asks for short, factual file cards using `CARD_SCHEMA`; generation is capped at 320 output tokens by default.
- Deterministic parsing, symbol extraction, embeddings, reranking, module cards, and project cards are outside this pilot.
- Export existing indexed Hub cards and their matching source text. Never generate new cards as training data.
- Reserve evaluation rows by project group. Do not include them in fine-tuning data.
- Model download, training, and live benchmark are outside the current authorization.
- Use `Qwen/Qwen2.5-Coder-1.5B-Instruct` as the full-precision training base, aligned with the configured `qwen2.5-coder:1.5b` preprocessing role.
- Do not create synthetic training examples. Existing card/source pairs are the only preprocessing training source.
- Keep training code and dependencies isolated from production Hub dependencies. Store weights, adapter, and run outputs in a task-scoped directory under configured Hub state.
- Use LoRA with Transformers and PEFT. Do not change production provider, config, routing, or model profile.
- Do not merge, publish, or promote adapter. It remains an experimental candidate.

## Paired Evaluation

Run the same prompt, system instruction, schema, token limit, and sampling settings for base and candidate models. Use three repetitions per case if the runtime supports fixed settings; otherwise record the actual repetition count. Keep model tag, quantization, runtime build, fixture revision, and exact prompt hash with every result.

Any later, separately authorized LoRA run must use bounded sequence length, epochs, and output directory. Record seed, target modules, rank, alpha, dropout, learning rate, batch size, precision, package versions, and model revision. Acquire the Hub GPU reservation only while training and evaluation run. If another owner or foreground workload holds the GPU, defer training and report the blocker; never clear another owner's reservation.

Score each card separately for:

1. Schema validity and completion of all required fields.
2. Recall and precision of source-grounded facts in `symbols`, `dependencies`, `side_effects`, `risks`, and `tests`.
3. Unsupported claims, especially invented network, database, security, or framework behavior.
4. Usefulness and brevity of `purpose` and `keywords`, reviewed against source.
5. Prompt and output token counts, latency, and failures.

Do not treat this four-file, one-project pilot as production qualification. Continue only if the candidate improves grounded fact quality without raising hallucinations or schema failures. Any later production change needs a larger held-out set spanning multiple repositories and languages, plus separate throughput and regression evidence.

## Current Run State

No model training or benchmark has run. Current local export uses existing indexed cards from 19 projects. It contains 140 matching card/source pairs for preprocessing and 20,775 card texts for embeddings before exact duplicate removal. The embedding corpus has no query/relevance labels.

