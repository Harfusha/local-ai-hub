# Trained model distribution

Selected inference artifacts are hosted in public Hugging Face model repositories under `Harfusha`. Public visibility lets a clean install download the selected model without a Hugging Face token. Training data, source files, raw benchmark cases, and training checkpoints are not published.

## Selected models

| Hub role | Public repository | Artifact | Provisioning |
|---|---|---|---|
| Laya decision model | `Harfusha/local-ai-hub-laya-run-expanded` | SafeTensors checkpoint | Downloaded lazily at the first Laya decision; pinned commit and file SHA-256 checks |
| Embedding | `Harfusha/local-ai-hub-bge-small-en-v1-5-code` | Merged SentenceTransformers model | Downloaded lazily when the embedding model loads |
| Reranker | `Harfusha/local-ai-hub-bge-reranker-v2-m3-code` | Merged CrossEncoder model | Downloaded lazily when reranking loads |
| Preprocessing default (`qwen2.5-coder-prep-v4:3b`) | `Harfusha/local-ai-hub-preprocess-qwen25-coder-3b` | Qwen2.5-Coder 3B QLoRA merge, GGUF Q4_K_M | Downloaded on the first Ollama generate/chat using the selected trained tag |
| Smaller preprocessing option (`qwen2.5-coder-prep-v3:0.5b`) | `Harfusha/local-ai-hub-preprocess-qwen25-coder-0-5b` | Qwen2.5-Coder 0.5B QLoRA merge, GGUF Q4_K_M | Same on-demand Ollama provisioning |

Model commits and artifact digests are pinned in package defaults and `src/local_ai_hub/model_distribution.py`. Hugging Face downloads are enabled by default for configured embedding and reranker models. Trained checkpoint downloads remain restricted to exact allowlisted repositories, pinned revisions, and verified SHA-256 digests. Set `models.allow_hf_downloads=false` to require local cache files for Hugging Face models.

| Model | Immutable repository commit | Weight SHA-256 |
|---|---|---|
| Laya | `e39264852ac9ba7c243ce33a0faa08eb647e54d4` | `3f503b3c02b1a60f4d52d732ce191f0d9d0cd8e466095e8cad11c9b510f4a8a7` |
| Embedding | `7bdcdf89c776fadc557b189c42b754d89d7832d1` | `1498c33b81574971cbbd14fb29a6a4936db2a87729fb417744055ea33ea79851` |
| Reranker | `a1596861f10fcc4efb8a5fa9df687d37860ba1a6` | `653ad0545ec469ea813453838c5b43befc52a7c63e8e85888ac190da3f76702b` |
| Preprocessing 0.5B | `00205f82897f6a18a6df8b12f27f33dfad82b1f5` | `1b4a1adc42693edd4c414cbee638706ab0768f5526ba7e37f694337f088d9b54` |
| Preprocessing 1.5B | `402474e54b881e2ade306a09afc81a29910e26ca` | `23c2a208cdd8fa33cc0d959f076f8b54d7021f0ce896e5323ce4df715bb2c96b` |
| Preprocessing 3B | `3e8c25fc7b6fd839701dad01dfe13a1ef4898543` | `f8f815fc8d8992063c294c11a906c38899d2cd8150b5ccf2a1aeefab95983113` |

## Cache and integrity

Hugging Face models use the standard Hugging Face cache. A model is fetched at its pinned immutable commit and its selected weight file(s) are checked against SHA-256 before loading. Preprocessing GGUFs are stored under the configured Hub state directory at `models/`, verified before Ollama registration, and then reused by Ollama. A checksum mismatch fails closed.

The first use needs an internet connection. Later uses reuse the local cache. On a new PC, installation of the relevant optional runtime remains necessary: `local-nlp` for embedding/reranking and `laya-runtime` for Laya. Preprocessing uses the configured Ollama provider.

## Training and evaluation

- Embeddings: selected merged LoRA. Aggregate held-out hit@1 improved from 0.650 to 0.825; MRR from 0.7493 to 0.8703.
- Reranker: selected merged LoRA. Aggregate margin accuracy improved from 0.889 to 0.975; loss from 0.2119 to 0.0511.
- Laya: selected full `run_expanded` checkpoint. Aggregate choice accuracy on 388 held-out decisions improved from 0.4278 to 0.9768. It is active typed advisory for eligible low-risk model routing, context-budget, retrieval, and task-guidance decisions. The Hub applies valid suggestions with deterministic fallback; Laya cannot grant host permissions or bypass high-impact gates.
- Preprocessing: both selected v3 QLoRA adapters are published. The 1.5B model is the default because its aggregate held-out exact match was 0.20 versus 0.08 for 0.5B, with mean latency 9.66 s versus 8.45 s. Raw evaluation rows remain local.

Upstream licenses are retained or identified in each model card. The fine-tuned BGE-small card links to the upstream MIT license because that upstream repository does not include a license text file; the other staged artifacts include their upstream license text.
