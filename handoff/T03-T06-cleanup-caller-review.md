# T03 → T06 cleanup caller review

Root snapshot reviewed read-only: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

## Finding

T06 `TaskStore.cleanup_worktree(task_id, delete_branch=True, *, actor="http-default")` rejects the default/reserved actor and requires a non-reserved actor matching task owner. The HTTP caller still calls `cleanup_worktree(t_id, delete_branch=del_br)` without actor, so both HTTP and MCP cleanup requests fail closed. MCP sends only the action/task id, while `HubClient` already forwards `X-LocalAI-Agent`; the HTTP handler's `_agent()` reads that identity. T06 task creation uses the same handler identity for ownership.

## Root-current caller patch

`T03-T06-cleanup-actor-caller.patch` adds `actor=self._agent()` at the HTTP cleanup call. `git apply --check` passes against the reviewed root snapshot; no root edit was made. Patch SHA-256: `326A2ACEA9029EE244C0B68352D897C4F688134C626020B099D6FC2ED54AE647`.

The patch only touches the task-cleanup dispatch lines in `http_server.py`; it does not touch T21 `project_config.py`, `/api/search`, or the T13 gaming-mode handler.

## Acceptance needed at integration

The T06 cleanup contract tests exercise the store directly (owner match, dirty-worktree preservation, clean removal, tampered metadata); they do not cover HTTP/MCP actor propagation. Add/run a focused HTTP acceptance using `X-LocalAI-Agent` equal to task owner and assert successful cleanup, plus a foreign-agent denial. MCP transport should retain its header-derived agent identity. Tests were not run by T03 in this review.

## Path-hints service boundary

T03 owns the bounded search-only public schema and MCP forwarding. Candidate T03's `Services.repo_search` does not accept `path_hints`; HTTP correctly gates forwarding on the service signature. Current root/T21 `repo_search` supports `path_hints`, so no T03 change to T21-owned service or project configuration is needed. Root path-hints acceptance was previously reported by T20; this review did not rerun it.
