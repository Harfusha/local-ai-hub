# Idle project preprocessing

Local AI Hub preprocesses only stable roots explicitly registered by an agent. Never register `System32`, temp/build/test sandboxes, the Local AI install/state directory, or incidental process working directories. Use `preprocess_unregister` to remove a stale scheduler registration without deleting reusable content-addressed caches.

Two resource lanes are intentionally separate:

- **CPU lane:** metadata/hash work, deterministic parsers/indexes, FTS, code embeddings and reranking. It does not enter the GPU scheduler and may continue while the foreground model runtime is active.
- **Idle GPU lane:** unresolved semantic file/module/project enrichment. A dedicated managed Ollama server loads the configured background model only after the configured idle interval, with capacity selected by the hardware profile.

Foreground intent has absolute priority. Submission preempts the dedicated background server synchronously before the foreground scheduler can load the interactive model. Background work is content-addressed and checkpointed, so cancellation loses at most the disposable in-flight batch. A measured CPU-offload guard rejects a poor idle-GPU profile and cools down before retrying. Live throughput speed (`files/s`, `chunks/s`, `cards/s`) and dynamic ETA are reported in real time.

Caches are keyed by repository/content/model/analyzer state so unchanged artifacts are shared across agents and survive restarts without repeating work.
