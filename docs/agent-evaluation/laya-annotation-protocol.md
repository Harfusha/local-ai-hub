# Laya Annotation and Evaluation Protocol (Draft)

**Status:** Proposed protocol. No candidate data has been collected or approved.

## Entry gate

Do not collect or evaluate examples until an operator approves the category, its
minimal input fields, the deterministic Hub baseline, the label rubric, and the
privacy scope. The current Laya Multilingual model card reports typed-decision
zero-shot accuracy of 0.342 against a 0.461 majority baseline and warns that
its probabilities are uncalibrated and overconfident. This upstream result is
not a Hub evaluation and does not select a category.

## Candidate handling

- Use only examples explicitly opted in for this evaluation. Keep the input to
  the minimum fields needed by the chosen decision category.
- Exclude full transcripts, prompts, source files, private conversations,
  credentials, and unnecessary personal data. Redact or exclude an example if
  its minimum useful input cannot be shared within the approved scope.
- Keep candidate text out of telemetry, ordinary diagnostics export, and model
  logs. Persist candidates only in the configured `server.state_dir`, using an
  existing state/artifact mechanism with explicit retention and deletion. Never
  write runtime candidate data under the repository root or commit it to Git.
- Give each example a stable opaque group key for its underlying task, source,
  or conversation. Keep related examples in the same group. Do not derive a
  group key from text, paths, or other private content.
- Preserve label source, rubric version, annotator pseudonym, adjudication
  reference, consent scope, and group key with each exported example. These
  fields record provenance; they do not prove that a label is independent.

## Labeling

1. Freeze the category, allowed options, rubric, and deterministic baseline
   before labeling.
2. Have two qualified annotators label each example independently. Hide model
   outputs and baseline answers from annotators.
3. Send disagreements to a separate adjudicator. Retain both original labels,
   the adjudicated label, and a reference to the adjudication record.
4. Report agreement before adjudication. Do not call caller-supplied
   provenance verified without checking its referenced source.

## Paired evaluation

- Run the deterministic baseline and Laya on the same held-out examples,
  category options, and approved inputs.
- Split by group, never by row. A group must appear in only one of train,
  validation, or test. Keep a final holdout sealed until thresholds and
  decision rules are fixed.
- Record category, language, group counts, label source, exclusions,
  adjudication, and split rule. Exclude examples whose group or provenance is
  unknown.
- Report per-category and per-language accuracy, confusion counts, abstention,
  and errors against both independent labels and the deterministic baseline.
  Report calibration only when the held-out sample supports it.
- Measure latency, protocol/schema tokens, model tokens or compute, cache state,
  and actual runtime/provider/device separately. Mark unobserved values
  `NOT_VERIFIED`; provider selection alone does not prove device execution.
- Set sample size and pass thresholds before scoring. Do not claim quality or
  utility from synthetic fixtures, training examples, or an underpowered holdout.

## Candidate lifecycle and export

Use existing `local_ai_coord(action="curate_dataset")` with `laya_operation`.
The retired `include_laya_candidates` and caller-authored JSONL import fields are
not accepted. Candidate rows and metadata events live in the existing
`server.state_dir/agent_state.sqlite` database; no separate candidate database,
public endpoint, telemetry field, or exporter is used. Ordinary task export
omits candidate text. The existing support ZIP strips candidate tables and
linked Laya capture traces from disposable snapshots. Synthetic archive tests
verify the exclusion, metadata-only report, and manifest counts; candidate
JSONL still requires explicit consent and an authorized repository/snapshot.
This verifies the code path, not consent or readiness for production data.

- `capture` requires per-example `consent=true`, a task and matching session
  resolved under the authorized repository root, and a closed typed candidate.
  The server derives the group ID. Do not supply caller-authored group IDs.
- `capture_batch` accepts 1–100 examples for the same scoped task/session. Each
  item needs its own `consent=true`; the batch validates fully before one
  transaction, deduplicates exact inputs, and returns IDs/status only.
- Capture only the minimal state, category, allowed options, language,
  preprocessing identity, and authorized evidence IDs required by the approved
  decision. Never include transcripts, prompts, source files, or evidence
  contents. The candidate is not reconstructed from telemetry or task text.
- Preserve the caller's option order. Laya `choice.criteria` is an ordered
  mapping whose position changes the model's output classes; freeze it with
  the category and rubric before collecting or labeling examples.
- `list` returns candidate identity, task/session/group IDs, status and
  timestamps; it does not return candidate text. Candidate payloads stay out of
  telemetry and ordinary diagnostics. Explicit `delete` removes the payload
  while retaining metadata-only audit events.
- `label` requires two distinct annotators and a separate adjudicator, all with
  allowed option values. `verify` requires explicit consent and a reviewer
  distinct from all three. Capture, labeling, and verification do not prove that
  references are real people or that review was blind; provenance is
  caller-attested until independently checked.
- reject and delete require explicit consent. prepare_splits snapshots
  verified candidates into deterministic 80/10/10 train/calibration/test
  groups. It joins matching task or session groups and merges state strings
  whose normalized character-trigram Jaccard similarity is at least 0.80.
  Bounded-scan overflow fails closed. Deleting a member invalidates its
  snapshot.
- Split reports contain counts and label distributions, not candidate text or
  test labels. Fewer than two independent calibration or test groups for any
  category/language is INSUFFICIENT DATA; otherwise status remains UNASSESSED
  until case-count and quality thresholds are predeclared. export requires
  consent=true plus a snapshot ID and exports its train split only. Validation
  and locked-test rows cannot enter this training export. Treat explicit JSONL
  output as sensitive.
- The ZIP includes `laya/candidates.train.jsonl` only after explicit opt-in
  during export. It contains that installation and repository's train split,
  serialized only as `state`, `questions`, and `expected`; it omits candidate,
  task, session, group, label-provenance, and split identities. The offline
  `laya-dataset-merge <notebook.zip> <desktop.zip> --output-dir <new-directory>`
  command can pool two or more opted-in encrypted ZIP members. It prompts for
  each password, reads only that exact member,
  validates the row shape, removes exact canonical duplicates, and aborts on
  conflicting labels for identical state/questions. It writes
  `laya.train.jsonl` plus a manifest with row counts and no archive names.
  Output is marked `training_only=true` and `evaluation_eligible=false`.
  Because source rows omit global groups and provenance, this merge cannot
  reconstruct a valid pooled split or prove holdout isolation. Never use it
  for pooled calibration or evaluation; those require authorized source
  records and a separately defined global group/near-duplicate split.
- Do not capture any examples until the operator approves one category,
  minimal input/privacy scope, deterministic baseline, and label rubric.
  Synthetic archive tests verify candidate-text exclusion and
  manifest reporting in the existing ZIP; they do not authorize production
  capture. No production examples, inference, or training have been performed
  in this task. No automatic collection is enabled.
- Near-duplicate grouping is deterministic heuristic protection, not semantic
  proof. Independent provenance validation, retention expiry, split
  sufficiency thresholds, paired baselines, and quality evaluation remain
  required.

## Current blocker

No Hub-specific category has an approved minimal input, independent labeled
examples, deterministic paired baseline, or sealed group-safe holdout. The
state_dir-backed candidate lifecycle is infrastructure only: it does not prove
category suitability, consent for any example, independent labels, quality, or
utility. Synthetic tests verify the support-ZIP candidate exclusion and truthful
manifest, but do not authorize collecting production examples. Collection
remains stopped pending category/input/privacy approval, a deterministic
baseline, independent labels, and fixed evaluation thresholds. This draft
grants no collection consent and enables no shadow, advisory, or guarded
execution.

## Fine-tuning format evidence

The pinned multilingual checkpoint is 322M parameters, uses the mmBERT-base
encoder, and accepts `state` plus typed `choice`, `score`, or `noul` questions.
Its [pinned model card](https://huggingface.co/convaiinnovations/laya-multilingual/tree/1720e3e3357cfe1e281542e223f8273b0890ca34)
reports that typed-decision zero-shot accuracy is near the majority
baseline and that shipped probabilities are uncalibrated/overconfident. It
recommends specializing a checkpoint for a specific workflow and calibrating
on held-out data. Those are upstream results, not Local AI Hub measurements.

The [official Laya fine-tuning docs](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune.md)
(upstream `main`, checked 2026-11-10) describe `laya-train` and
`laya.train.finetune` for a local checkpoint directory, on CUDA, MPS, or CPU.
JSONL accepts `{state, questions, expected}` hard labels or `{state, questions,
gold}` teacher distributions. The existing candidate train export's
`state`/`questions`/`expected` shape matches the documented hard-label input;
this is format compatibility only. The exporter omits global group and label
provenance, so merged output remains training-only and cannot support pooled
calibration or evaluation. Before training, pin a compatible Laya package/source
revision alongside the model revision and validate the dataset with
`laya-train --dry-run`; no package install, data download, inference, or training
is performed by this protocol.

The upstream [Python `ONNXAgent` reference](https://github.com/NandhaKishorM/laya/blob/main/docs/reference/agent.md)
(checked 2026-11-10) documents CPU execution. [ONNX Runtime's provider list](https://onnxruntime.ai/docs/execution-providers/)
includes separate providers for NVIDIA CUDA, Intel OpenVINO, DirectML, AMD
MIGraphX, and AMD Ryzen AI/Vitis AI. For Windows, Microsoft's [Windows ML provider
catalog](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers)
on Windows 11 24H2+ lists Intel OpenVINO for CPU/GPU/NPU, AMD MIGraphX for GPU,
AMD VitisAI for NPU, and NVIDIA TensorRT RTX for GPU; CPU and DirectML are
included providers. Its [silicon mapping](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/accelerate-ai-models)
states that Windows ML distributes providers but does not optimize a model.
This is a promising single-runtime route across the requested device classes,
not proof that Laya's graph is supported or executes fully on an accelerator.
The [Windows ML Runtime API](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/runtime/overview)
is currently marked experimental, including its Python API; production adapter
selection therefore still needs a supported Hub integration path. Keep the
single multilingual checkpoint as the source of truth. Treat ONNX or
quantized artifacts as derived caches, and require numerical parity plus
device-specific runtime/resource tests before enabling them. The upstream INT8
export is described as CPU-only with an accuracy trade-off; do not select it as
a universal GPU/NPU variant.
