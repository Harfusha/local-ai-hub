# Local Model Fine-Tuning

Opt-in training tools live in `tools/model_training/`. They do not alter Hub routing or start training by themselves. Current configured preprocessing model depends on hardware profile: this PC's `high` profile selects `qwen2.5-coder:3b`; the matrix example covers the 0.5B, 1.5B, and 3B variants. The same runner accepts a separate decision-model dataset and base model.

## Pipeline

1. `list-existing-card-candidates` returns IDs and metadata only. `export-existing-cards` reads selected eligible cards and source text already stored in the Hub index, limited to authorized registered roots. It skips deterministic-generated cards when provenance identifies them. It makes no model calls and generates no new cards.
2. `split` creates deterministic group-held-out data. Projects stay intact; exact duplicate source rows stay on one side, and the embedding corpus removes duplicate card text before splitting. `validate` rejects group, ID, and source-hash leakage before loading model weights.
3. `run-matrix` evaluates each untrained base model first, trains with the selected backend, then runs a paired before/after benchmark on the exact same held-out rows. Preprocessing and generic decision-model manifests use Transformers LoRA; Laya uses its native typed-decision trainer and checkpoint format.
4. Review `benchmark-before.json`, `training_run.json`, `benchmark-after.json`, and every output row before considering a candidate. The report marks manual source review as required.

## Dataset provenance

Existing-card candidates are listed without returning card or source text. Card-training export selects only current eligible row IDs, checks already-indexed source hashes, skips deterministic card generators, and confines output to `state_dir`. It performs no card generation, preprocessing, or model call.

Laya training candidates come only from actual scoped runtime outcomes and export as `provenance.data_class=local_scoped`, with candidate identity/hash, repository/task/session and evidence scope, and verified label provenance. Per-example consent receipts are not required or persisted. Synthetic non-private fixtures instead require a fixture ID. Candidate rows need `label_provenance.status=verified` and `target_sha256`, the SHA-256 of canonical target JSON. Blind double annotation needs two distinct annotators, an independent adjudicator, and an independent verifier. Deterministic labels need evidence IDs. Fixture-oracle labels are accepted only for synthetic non-private rows. The validator checks structure and target binding; it does not authenticate reviewer identities. The scoped `curate_dataset` Laya operation `delete` invalidates affected snapshots and removes associated local train JSONL exports and candidate/runtime event payloads. It cannot recall copies already exported outside `server.state_dir`.

The generic decision-model manifest uses the same Transformers LoRA pipeline. Supply its real base model, task-specific JSONL, output schema, LoRA target modules, and task-specific scoring facts. No decision-model behavior or routing is inferred by this scaffold. For Laya, use the dedicated Laya backend below.

Training rows use one system/user/assistant conversation and provenance. Evaluation rows omit the assistant answer and provide `expected`, `required_facts`, or `forbidden_claims` for scoring. `group_id` must identify the project, repository, conversation, or other leakage boundary:

```json
{"id":"train-1","group_id":"project-a","messages":[{"role":"system","content":"Return JSON."},{"role":"user","content":"Input..."},{"role":"assistant","content":"{\"label\":\"yes\"}"}],"provenance":{"dataset":"decision-v1","source_sha256":"<64 hex characters>"}}
{"id":"eval-1","group_id":"project-b","messages":[{"role":"system","content":"Return JSON."},{"role":"user","content":"Held-out input..."}],"provenance":{"dataset":"decision-v1","source_sha256":"<64 hex characters>"},"expected":{"label":"yes"},"required_facts":[{"field":"label","value":"yes"}],"forbidden_claims":["unsupported claim"]}
```

## Isolated Environment

Create a separate Python environment. Install a CUDA-enabled PyTorch wheel for the host, then the training dependencies:

```powershell
python -m venv .venv-model-training
& .\.venv-model-training\Scripts\python.exe -m pip install --upgrade pip
# Install the CUDA-enabled PyTorch wheel selected for this host.
& .\.venv-model-training\Scripts\python.exe -m pip install -r tools/model_training/requirements.txt
```

For 4-bit QLoRA, install `tools/model_training/requirements-qlora.txt` in the same environment. QLoRA requires CUDA and fails explicitly if its backend is missing. The current [bitsandbytes installation guide](https://huggingface.co/docs/bitsandbytes/installation) lists Windows x86-64 CUDA builds including CUDA 12.8 and SM120. Full-precision LoRA remains the default for the preprocessing matrix.

## Existing Preprocessing Cards

Export existing cards and their already-indexed source text for preprocessing-model fine-tuning. This does not call a teacher model or start preprocessing. Choose the configured Hub `state_dir` explicitly. To use all projects currently registered in the index:

```powershell
$stateDir = "$env:USERPROFILE\.local-ai-hub\state" # Replace with configured server.state_dir if customized.
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli list-existing-card-candidates `
  --state-dir $stateDir --all-indexed --format card-training
# This lists metadata only. Export reads cards and source text already stored in the Hub index.
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli export-existing-cards `
  --state-dir $stateDir `
  --all-indexed `
  --output experiments/model-training/data/preprocess-existing-cards.jsonl `
  --format card-training
```

The exporter skips known deterministic cards, uses only existing indexed cards, and does not regenerate cards. Resume rebuilds from rows still indexed. To restrict it to specific projects, copy `tools/model_training/examples/roots.example.json`, use absolute paths and stable IDs, and pass `--roots <file>` instead of `--all-indexed`. Missing or stale indexed source/card pairs are skipped and counted.

Create train and held-out files by project group:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli split `
  --input "$stateDir\experiments\model-training\data\preprocess-existing-cards.jsonl" `
  --train "$stateDir\experiments\model-training\data\preprocess-card-train.jsonl" `
  --evaluation "$stateDir\experiments\model-training\data\preprocess-card-eval.jsonl" `
  --evaluation-fraction 0.2 --seed 20261110
```

Write a local manifest after export and split. It records file hashes, counts, opaque group counts, split leakage checks, and rows removed by embedding deduplication. Paths must stay inside `server.state_dir`; project root paths are not copied into the manifest.

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.data_manifest `
  --state-dir $stateDir --format card-training `
  --source "$stateDir\experiments\model-training\data\preprocess-existing-cards.jsonl" `
  --train "$stateDir\experiments\model-training\data\preprocess-card-train.jsonl" `
  --evaluation "$stateDir\experiments\model-training\data\preprocess-card-eval.jsonl" `
  --output "$stateDir\experiments\model-training\data\preprocess-card.dataset-manifest.json"
```

Review and edit `tools/model_training/examples/preprocess-card-matrix.example.json` paths and settings. Validate without loading models:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli validate `
  --manifest tools/model_training/examples/preprocess-card-matrix.json --matrix
```

Running the three models is a separate, explicit step. `--allow-model-download` permits missing Hugging Face base checkpoints to download. Without it, cached/local weights only are used. Do not run this while preparing data.

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli run-matrix `
  --manifest tools/model_training/examples/preprocess-card-matrix.json `
  --allow-model-download
```

Each model gets its own run folder. The command benchmarks base first, trains the adapter, then stores a paired after-training report. Existing successful phases are reused; partial adapter output fails closed. No adapters are promoted or uploaded.

## Existing Cards for Embeddings

Export the Hub's existing file, module, and project cards as a card-text corpus:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli export-existing-cards `
  --state-dir $stateDir `
  --all-indexed `
  --output experiments/model-training/data/preprocess-existing-embedding-corpus.jsonl `
  --format embedding-corpus `
  --benchmark-cases tests/fixtures/search_benchmark_cases.json `
  --benchmark-root .

& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli split `
  --format embedding-corpus `
  --input "$stateDir\experiments\model-training\data\preprocess-existing-embedding-corpus.jsonl" `
  --train "$stateDir\experiments\model-training\data\preprocess-embedding-train.jsonl" `
  --evaluation "$stateDir\experiments\model-training\data\preprocess-embedding-eval.jsonl"
```

The exporter reads only cards already present in the preprocessing index. It does
not generate cards, run a model, or mutate the index. It writes a sibling
`.manifest.json` with the corpus hash and counts. To bind existing manually judged
retrieval cases to the exported cards, pass `--benchmark-cases` and
`--benchmark-root`; this records source hash and path coverage and writes a
filtered case file beside the corpus. `tools/benchmark_rag_reranker.py --cases`
can consume that file later. Excluded cases and absent targets stay listed in the
manifest. It does not create embedding fine-tuning labels or run a benchmark.

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.data_manifest `
  --state-dir $stateDir --format embedding-corpus `
  --source "$stateDir\experiments\model-training\data\preprocess-existing-embedding-corpus.jsonl" `
  --train "$stateDir\experiments\model-training\data\preprocess-embedding-train.jsonl" `
  --evaluation "$stateDir\experiments\model-training\data\preprocess-embedding-eval.jsonl" `
  --output "$stateDir\experiments\model-training\data\preprocess-embedding.dataset-manifest.json"
```

The corpus contains existing card text and provenance only. The embedding split removes exact duplicate card text first, then holds out whole projects. It does not invent query/relevance labels, so it is not a supervised retrieval benchmark or a complete contrastive fine-tuning set by itself.

### Local export snapshot (2026-11-10)

The current preprocessing index contains 19 registered projects. Exporting only already-indexed, non-deterministic file cards with matching stored source produced 742 rows; 19,863 deterministic placeholder cards were skipped and no source pairs were missing. Dataset SHA-256: `2d1f5c959f80fa126f546ae084376f33f6d553f94e006a1e3fb72bb32bc4d447`. The project-held-out split has 334 train rows across 10 groups and 408 evaluation rows across 5 groups, with zero ID, group, or source-hash overlap. The requested 20% evaluation fraction became 54.99% because project groups are uneven. The split manifest reports `evaluation_status="dataset_only"`; the existing cards are teacher outputs, not independent quality labels.

The runnable, not-yet-executed three-model matrix is `server.state_dir/experiments/model-training/preprocess-card-matrix.json`; its data manifest is `server.state_dir/experiments/model-training/data/preprocess-existing-cards.dataset-manifest.json`. It targets Qwen2.5-Coder 0.5B, 1.5B, and 3B with the prepared group-safe files. Validation checked manifest shape and split leakage only. No model was loaded, trained, or benchmarked.

The latest existing-card embedding export contains 20,774 rows from the same 19 projects: 20,602 file cards, 153 module cards, and 19 project cards. Dataset SHA-256: `39a98be3380d7af856fb307abc32b39f647f23790cd460d3c3b0668676f6c104`. Existing fixture `agent-search-manual-2026-11-05-v2` has 22 positive manually judged retrieval cases; 18 fully resolve to cards from this repository and are written to `preprocess-existing-embedding-corpus-retrieval-cases.json`. The benchmark tool accepts the prepared subset with `--cases`; source anchors validate before any run. Two expected paths have no card: `docs/INSTALL_PROMPT.md` is absent from the index; `src/local_ai_hub/preprocess.py` is indexed as source but has no card for this repository root (same-path cards belong to other roots). The manifest records fixture hash, subset hash, and excluded cases. These are retrieval evaluation inputs only; the corpus still has no supervised embedding fine-tuning labels. Both exports and manifests stay under `server.state_dir/experiments/model-training/data/`; export makes no model calls and starts no preprocessing.

Eligible successful ordinary context requests now queue `LayaRuntimeAdapter` through the existing bounded executor when the pinned runtime is enabled, an evidence gap remains, and two authorized sources have verified evidence IDs. The callback stores only actual scoped runtime outcomes; no consent or receipt is required. The last verified candidate count was zero, so no reviewed labels are available to export yet. Do not fabricate examples or use model predictions as labels.

## Laya Decision Model Run

Laya is a typed-decision classifier, not a causal language model. Its backend calls the pinned `laya==0.4.30` training API, including Laya's calibration, and writes a native checkpoint that `laya.load()` can open. It does not use the generic LoRA trainer. The example pins `convaiinnovations/laya-multilingual` to revision `1720e3e3357cfe1e281542e223f8273b0890ca34`.

Laya capture requires authorized task/session and verified evidence provenance; candidate state remains minimal. Rows stay pending until two independent labels, adjudication, and separate verification are recorded. Train export writes only verified rows into configured `state_dir` and includes stable `id`, opaque `group_id`, `source_sha256`, and local scope provenance. The Laya splitter keeps groups, shared hashes, and exact state/question duplicates on one side. It refuses overlap before loading a checkpoint.

Create a manifest for a verified Laya train export using the same snapshot ID. The manifest labels the dataset train-only and evaluation status unassessed; it does not replace the source database's label verification.

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.data_manifest `
  --state-dir $stateDir --format laya --snapshot-id $snapshotId `
  --train "$stateDir\experiments\model-training\data\laya-$snapshotId.train.jsonl" `
  --output "$stateDir\experiments\model-training\data\laya-$snapshotId.dataset-manifest.json"
```

```powershell
& .\.venv-model-training\Scripts\python.exe -m pip install -r tools/model_training/requirements-laya.txt

& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli split `
  --format laya `
  --input state/experiments/model-training/data/laya-reviewed.jsonl `
  --train state/experiments/model-training/data/laya-train.jsonl `
  --evaluation state/experiments/model-training/data/laya-eval.jsonl `
  --evaluation-fraction 0.2 --seed 20261110

& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli run-matrix `
  --manifest tools/model_training/examples/laya-decision-matrix.example.json
```

Edit the example paths first. The run evaluates the pinned base on the held-out split, fine-tunes Laya on CUDA, then evaluates the saved checkpoint on that same split and records per-metric deltas. CUDA is the default and no CPU fallback is accepted. A missing base checkpoint stays local-cache-only unless `--allow-model-download` is explicitly supplied. The run does not publish, promote, or alter Hub routing.

The saved `checkpoint/` is Laya's native full fine-tuned checkpoint and loads with `laya.load(path)`. The scaffold does not convert it to ONNX or install runtime providers. Any ONNX/device export is a separate derived artifact that needs output-parity and quality checks before use.

## GPU Behavior

- CUDA is required by default. A CUDA request never falls back silently to CPU; set `training.device` to `cpu` only when CPU training is intentional.
- CUDA precision selects BF16 when supported, otherwise FP16. Built-in SDPA and fused AdamW are used when available and recorded in the run receipt.
- Gradient checkpointing and configurable micro-batches/accumulation limit VRAM use. Set `training.quantization` to `4bit` for QLoRA on generic causal decision models; it requires the optional bitsandbytes environment. Laya uses its own full-fine-tuning recipe and AMP settings.
- Models run sequentially to avoid competing for the same GPU. The scaffold does not manage or terminate other GPU processes.

## Hugging Face Distribution

Keep first candidates private under the user's account. Generic models publish an adapter; Laya publishes its native checkpoint plus model card and safe provenance. Never upload source repositories, generated project cards, or private datasets. Before public release, check the base model's license, rights to the fine-tuning data, and evaluation results. The Hugging Face Hub supports private model repositories, and model cards carry base-model, task, license, and training details. [Repository visibility](https://huggingface.co/docs/hub/repositories-settings), [model cards](https://huggingface.co/docs/hub/model-cards).

This scaffold intentionally has no Hugging Face upload command. Publishing is a separate deliberate release step after review.
