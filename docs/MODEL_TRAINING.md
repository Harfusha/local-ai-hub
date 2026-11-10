# Local Model Fine-Tuning

Opt-in training tools live in `tools/model_training/`. They do not alter Hub routing or start training by themselves. Current configured preprocessing model depends on hardware profile: this PC's `high` profile selects `qwen2.5-coder:3b`; the matrix example covers the 0.5B, 1.5B, and 3B variants. The same runner accepts a separate decision-model dataset and base model.

## Pipeline

1. Give `collect-cards` an explicit roots file. It reads selected text/code files and calls the local Ollama API on loopback only, defaulting to `qwen2.5-coder:3b`. It writes resumable JSONL with project group IDs, source paths, source hashes, teacher model, and token metadata. It does not discover every project on the PC automatically.
2. `split` creates a deterministic group-held-out evaluation split. Projects stay intact; content hashes shared between projects are grouped together. `validate` rejects group, ID, and source-hash leakage before loading model weights.
3. `run-matrix` evaluates each untrained base model first, trains its LoRA adapter, then runs a paired base-versus-adapter benchmark on the exact same held-out rows.
4. Review `benchmark-before.json`, `training_run.json`, `benchmark-after.json`, and every output row before considering a candidate. The report marks manual source review as required.

The decision-model manifest uses the same pipeline. Supply its real base model, task-specific JSONL, output schema, LoRA target modules, and task-specific scoring facts. No decision-model behavior or routing is inferred by this scaffold.

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

## Preprocessing Card Run

1. Copy `tools/model_training/examples/roots.example.json`, replace each path with an absolute project root, and use stable unique IDs. Keep sensitive or out-of-scope projects out of this file.
2. Generate teacher cards. `--resume` appends only missing content IDs after an interruption:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli collect-cards `
  --roots tools/model_training/examples/roots.json `
  --output state/experiments/model-training/data/preprocess-card-all.jsonl `
  --model qwen2.5-coder:3b --resume
```

3. Create train and held-out files by project group:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli split `
  --input state/experiments/model-training/data/preprocess-card-all.jsonl `
  --train state/experiments/model-training/data/preprocess-card-train.jsonl `
  --evaluation state/experiments/model-training/data/preprocess-card-eval.jsonl `
  --evaluation-fraction 0.2 --seed 20261110
```

4. Review and edit `tools/model_training/examples/preprocess-card-matrix.example.json` paths and settings. Validate without loading models:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli validate `
  --manifest tools/model_training/examples/preprocess-card-matrix.json --matrix
```

5. Run the three models sequentially. `--allow-model-download` explicitly permits missing Hugging Face base checkpoints to download. Without it, cached/local weights only are used:

```powershell
& .\.venv-model-training\Scripts\python.exe -m tools.model_training.cli run-matrix `
  --manifest tools/model_training/examples/preprocess-card-matrix.json `
  --allow-model-download
```

Each model gets its own run folder. The command benchmarks base first, trains the adapter, then stores a paired after-training report. Existing successful phases are reused; partial adapter output fails closed. No adapters are promoted or uploaded.

## GPU Behavior

- CUDA is required by default. A CUDA request never falls back silently to CPU; set `training.device` to `cpu` only when CPU training is intentional.
- CUDA precision selects BF16 when supported, otherwise FP16. Built-in SDPA and fused AdamW are used when available and recorded in the run receipt.
- Gradient checkpointing and configurable micro-batches/accumulation limit VRAM use. Set `training.quantization` to `4bit` for QLoRA on large decision models; it requires the optional bitsandbytes environment.
- Models run sequentially to avoid competing for the same GPU. The scaffold does not manage or terminate other GPU processes.

## Hugging Face Distribution

Keep first candidates private under the user's account. Publish only the adapter/model card and safe provenance; never upload source repositories, generated project cards, or private datasets. Before public release, check the base model's license, rights to the fine-tuning data, and evaluation results. The Hugging Face Hub supports private model repositories, and model cards carry base-model, task, license, and training details. [Repository visibility](https://huggingface.co/docs/hub/repositories-settings), [model cards](https://huggingface.co/docs/hub/model-cards).

This scaffold intentionally has no Hugging Face upload command. Publishing is a separate deliberate release step after review.
