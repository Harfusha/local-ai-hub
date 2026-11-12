# Laya Annotation and Evaluation Protocol

**Status:** The Hub Laya service remains available for the Hub process lifetime.
Eligible ordinary context requests queue bounded shadow evaluation when a useful
unresolved gap has at least two authorized sources and verified evidence IDs,
independent of the retired `laya.runtime.enabled` gate. The pinned provider is
loaded on demand and held through work plus the 600-second idle window after the
latest completed request. Capture stores only actual runtime outcomes in the
existing local Agent State store, scoped to repository/task/session with
revalidatable evidence provenance. Useful bounded task input and retrieved
excerpts may be retained after recognized-secret redaction. Per-example consent
or receipt IDs are not required. Laya outputs, deterministic outcomes and human
labels remain separate. Training, benchmarking, card generation and rollout
remain deferred until separately requested and safely approved.

Existing-card export reads only selected eligible, non-deterministic cards and
source text already stored in the Hub index. It needs no per-example consent
manifest, makes no model calls, and generates no cards.

## Approved `context_source` pilot

- Trigger: an unresolved evidence gap with at least two authorized sources.
- Typed decision state: `gap_code=unresolved_evidence_gap`, two to four unique
  `source_codes` from `indexed`, `artifact`, `memory`, or `rag`, aligned
  `freshness_codes` (`current`, `stale`, `unknown`) and `coverage_codes`
  (`complete`, `partial`, `incomplete`, `unknown`), plus one evidence ID
  per source in the same order. For useful training examples, the ordinary
  request hook may also pass the task query and bounded retrieved excerpts when
  materially useful. These optional text fields are redacted and stored
  separately from the typed codes; see Candidate handling for limits.
- Current deterministic retrieval order is the baseline.
- The local operator may confirm one permitted target under the versioned
  rubric; this is the human label for the single-owner Hub. No second annotator,
  adjudicator, SSH reviewer key, or remote quorum is required.
- A capable local Codex/model may add a separately attributed review only when
  the Hub binds its identity from a trusted local invocation. `model_review`
  accepts only a candidate ID and invokes a server-configured local reviewer;
  callers cannot submit decisions, confidence, or model identity. Without that
  callback, the request fails closed without storing a review. The current Hub
  application has not wired the callback, so model review remains unavailable.
  Model reviews never become human labels or human-confirmed export evidence.
- Useful only when it removes one retrieval roundtrip without losing any
  required fact. Unauthorized, stale, or incomplete sources count as false
  positives. Abstain when evidence is insufficient.
- Capture resolves every evidence ID through the existing EvidenceStore
  under the authorized repository root and rejects missing, cross-root, or
  stale references. It also requires each source code to match route metadata
  recorded by trusted Hub retrieval callsites in the same EvidenceStore
  database. Current capture provenance supports `indexed` from repository and
  deterministic retrieval, `rag` from repository-search result metadata, and
  `artifact` after a successful `evidence_get`. The schema accepts `memory`
  as a code, but capture rejects it until an existing root-scoped EvidenceStore
  path can record that route. Caller-supplied codes alone cannot establish
  provenance.
- Capture is tied to actual typed runtime execution, not an automatic scrape or
  synthetic inference. It requires the strict typed-input, authorized-root,
  task/session, and evidence-provenance checks above. Training remains disabled.

The current Laya Multilingual model card reports typed-decision zero-shot
accuracy of 0.342 against a 0.461 majority baseline and warns that its
probabilities are uncalibrated and overconfident. This upstream result is not a
Hub evaluation and does not prove this pilot useful.

## Entry gate

The approved pilot scope fixes its category, minimal fields, deterministic
baseline, label rubric, and privacy scope. Do not enable other categories until
their own evidence, labels, baseline, and approval gates pass.

## Candidate handling

- Use only examples from the scoped candidate lifecycle. Keep the input to the
  minimum fields needed by the chosen decision category.
- For the current `context_source` pilot, retain the task query and relevant
  retrieved excerpts only when they materially improve the training example.
  Bound each field to 8 KiB and combined raw content to 16 KiB; redact
  recognized credential, token, and password patterns and record redacted or
  unavailable fields. Keep authorized evidence IDs and source provenance.
  Exclude full transcripts, full source files, unrelated conversations,
  credentials, and unnecessary personal data. Redact or exclude an example if
  its minimum useful input cannot be retained within this approved scope.
- Keep candidate text out of telemetry, ordinary diagnostics export, and model
  logs. Persist candidates only in the configured `server.state_dir`, using an
  existing state/artifact mechanism with explicit retention and deletion. Never
  write runtime candidate data under the repository root or commit it to Git.
- Give each example a stable opaque group key for its underlying task, source,
  or conversation. Keep related examples in the same group. Do not derive a
  group key from text, paths, or other private content.
- Preserve local operator-confirmation method, rubric version, target hash,
  and group key with each exported human label. Keep any model-review record,
  model identity, rubric, evidence, timestamp, confidence/abstention, and
  decision separate from the target; unattested model submissions are not
  review proof. Provenance fields record origin, not correctness.
- Keep repository/task/session identity, evidence IDs, model output, and human
  label provenance separate. Metadata-only diagnostics omit candidate rows.
- `laya_operation={action:"delete",candidate_id:"..."}` invalidates affected
  snapshots, removes local train JSONL exports and candidate/runtime event
  payloads, then retains only a minimal deletion audit. It cannot recall copies
  already exported outside `server.state_dir`.

### Existing-card export and dataset admission

The model-training exporter reads only cards already stored in the Hub
preprocessing index. It does not call a model or generate new cards. Candidate
listing returns metadata only; content export is local and scoped to registered
project roots. Source text is included only when its indexed hash still matches
the card's source pair. Resume drops rows no longer present in the current
index. `card-training` export uses selected, currently indexed rows with
matching source hashes. It skips deterministic-generated cards when provenance
identifies them. It needs no per-example consent manifest and generates no cards.

Laya training/evaluation rows preserve candidate, evidence, label, and group
provenance. Candidate rows use `provenance.data_class="local_scoped"` with
candidate identity/hash, repository/task/session and evidence scope. Existing
card rows remain a separate source and do not become Laya candidates. Synthetic fixtures retain an explicit
`synthetic_non_private` fixture ID. Candidate labels need a verified record
whose target hash matches exported labels. Blind double annotation requires two
distinct annotators, independent adjudicator, and independent verifier.
Deterministic labels require evidence IDs. The offline validator checks schema
and target binding; it cannot authenticate reviewer identity.

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

Use existing `local_ai_coord(action="curate_dataset")` with `laya_operation`,
or the root-authorized HTTP `POST /api/agent-state/tasks` `curate_dataset`
action. The retired `include_laya_candidates` and caller-authored JSONL import
fields are not accepted. Candidate rows and metadata events live in the existing
`server.state_dir/agent_state.sqlite` database. No separate candidate database
or telemetry payload is used. Ordinary task export omits candidate text. The
existing support ZIP strips candidate tables and linked Laya capture traces from
disposable snapshots. Candidate JSONL requires an authorized repository,
verified snapshot, and separate local export. This verifies the code path, not
data quality or label quality.

- `capture` requires a task and matching session resolved under the authorized
  repository root, authorized evidence provenance, a closed typed candidate,
  and server-derived group identity.
  The server derives the group ID. Do not supply caller-authored group IDs.
- `capture_batch` is unavailable. Only a real per-decision Laya runtime callback
  may create a candidate.
- Capture the minimum decision state, category, allowed options, language,
  preprocessing identity, and authorized evidence IDs. For context-source
  examples, the approved specification also permits the task query and relevant
  retrieved excerpts when they materially improve training value; redact
  recognized credentials, bound each raw field to 8 KiB and combined raw text
  to 16 KiB, and exclude unrelated private content. Never reconstruct a
  candidate from telemetry or unrelated conversation history.
- Preserve the caller's option order. Laya `choice.criteria` is an ordered
  mapping whose position changes the model's output classes; freeze it with
  the category and rubric before collecting or labeling examples.
- `list` returns candidate identity, task/session/group IDs, status and
  timestamps; it does not return candidate text. Candidate payloads stay out of
  telemetry and ordinary diagnostics. Explicit `delete` removes the payload
  while retaining metadata-only audit events.
- `get` reads one candidate by ID under the caller's authorized repository
  root, confirms its task still belongs to that root, and returns its bounded
  review payload. It strips workflow status, `model_output`, targets, label
  status, and label provenance so annotators do not see Laya's answer or earlier
  human labels.
- `label` requires two distinct annotators and a separate adjudicator, all with
  allowed option values. `verify` requires a reviewer distinct from all three
  and an installed server-side reviewer authenticator. Opaque reviewer IDs alone
  cannot set `verified`. The current Hub app has no authenticator configured, so
  labels remain `reviewed` and local candidate export rejects them until a real
  authenticated human-review path is integrated. Legacy caller-attested
  verification records are not accepted for export.
- Reject and delete remain explicit scoped operations. `prepare_splits` snapshots
  verified candidates into deterministic 80/10/10 train/calibration/test
  groups. It joins matching task or session groups and merges state strings
  whose normalized character-trigram Jaccard similarity is at least 0.80.
  Bounded-scan overflow fails closed. Deleting a member invalidates its
  snapshot.
- Split reports contain counts and label distributions, not candidate text or
  test labels. Fewer than two independent calibration or test groups for any
  category/language is INSUFFICIENT DATA; otherwise status remains UNASSESSED
  until case-count and quality thresholds are predeclared. `export` requires a
  snapshot ID and writes its train split under configured `server.state_dir`. Validation
  and locked-test rows cannot enter this training export. Treat explicit JSONL
  output as sensitive.
- Normal support ZIPs exclude candidate text. An explicitly requested candidate
  export contains that installation and repository's train split,
  serialized with stable `id`, opaque `group_id`, `source_sha256`, minimal
  provenance, `state`, `questions`, and `expected`; task/session identities and
  labeler references stay private. The offline
  `laya-dataset-merge <notebook.zip> <desktop.zip> --output-dir <new-directory>`
  command can pool two or more explicitly included encrypted ZIP members. It prompts for
  each password, reads only that exact member,
  validates the row shape, removes exact canonical duplicates, and aborts on
  conflicting labels for identical state/questions. It writes
  `laya.train.jsonl` plus a manifest with row counts and no archive names.
  Output preserves candidate IDs and opaque group IDs, and is marked
  `training_only=true` and `evaluation_eligible=false` because the archive
  member contains training rows only. Never use it for pooled calibration or
  evaluation; those require a separate held-out split.
- The operator approved a `context_source` pilot only for an unresolved evidence
  gap with at least two authorized sources. Inputs contain typed gap/source/
  freshness/coverage codes and verified evidence IDs; the task query and
  relevant retrieved excerpts may also be retained when materially useful,
  subject to the redaction and size limits above. Compare with deterministic
  retrieval; success requires one fewer retrieval roundtrip with no factual
  loss. Runtime outputs may be collected only from the actual runtime callback.
  Synthetic tests do not prove data quality.
- Near-duplicate grouping is deterministic heuristic protection, not semantic
  proof. Independent provenance validation, retention expiry, split
  sufficiency thresholds, paired baselines, and quality evaluation remain
  required.

## Current blocker

No Hub-specific category has independent labeled examples, a deterministic
paired baseline, or a sealed group-safe holdout. The `context_source` pilot
remains scoped to authorized roots, typed metadata, verified evidence IDs, and
minimum necessary redacted raw context when useful. The state_dir-backed
candidate lifecycle is infrastructure only: it does not prove label quality or utility.
Synthetic tests verify support-ZIP exclusion and truthful manifests, not
production-data quality. Independent labels, a deterministic baseline, and
fixed evaluation thresholds remain required. No shadow, advisory, or guarded
execution is enabled.

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
this is format compatibility only. Merged output remains training-only and
cannot support pooled calibration or evaluation. Before training, pin a
compatible Laya package/source
revision alongside the model revision and validate the dataset with
`laya-train --dry-run`; no package install, data download, inference, or training
is performed by this protocol. Local validators check dataset structure and
label provenance but do not authenticate reviewer identity.

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
