# Cloud-agent reliability, cache and transport design

## Evidence

Diagnostics show queue wait and low generation-cache reuse as hotspots. The largest avoidable HTTP failures are protocol outcomes (`request with this id is already running`) and Git-only actions used on non-Git roots. Hot-query preprocessing already warms deterministic/RAG capsules; prompts are intentionally not persisted, so historical generation-cache warming is unsafe. CodeGraph has a broken local executable (`ModuleNotFoundError`) and must degrade permanently rather than re-fail after cooldown.

## Design

1. The built-in client gets per-thread HTTP/1.1 connection reuse and request singleflight keyed by canonical method/path/body. It retains bounded replay behavior; a failed socket is discarded before the one permitted replay.
2. Recovery-journal duplicates return `in_progress:true` with a retry hint and become a successful protocol outcome in telemetry. Git diff/impact detect a non-Git root early and return a terminal client result, rather than a raw Git usage error.
3. An optional code-intelligence backend that proves its installation is irreparably broken is disabled for the process and reported as unavailable. Built-in indexes remain available; no retry loop is created.
4. Evaluation reports add an evidence-only promotion gate. It requires ten matched `hub_on`/`hub_off` tasks and rejects any quality/test regression or missing quality evidence; it never changes routing automatically.

## Constraints

- Keep public MCP surface at seven tools. Do not persist prompts/source/model output, add polling, or alter Qwen 9B.
- Existing hot-query preprocessing and `batch_delegate` remain canonical warming/batching paths; docs direct agents to use them.
- Do not reduce Qwen 7B context/concurrency merely to address external Ollama CPU offload.
