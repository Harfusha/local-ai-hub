# Type safety rollout

CI runs `python -m mypy` with `strict = true` on 14 extracted boundary modules
listed in `pyproject.toml` across supported Python versions (3.11 and 3.13).
Add every new extracted API boundary to that list before merging its slice.
The development extra provides the checker.

The strict set includes:
1. `source_outline.py`
2. `mcp_lifecycle_contracts.py`
3. `command_redaction.py`
4. `evidence_merge.py`
5. `http_event_cursor.py`
6. `external_candidate_paths.py`
7. `agent_event_pages.py`
8. `command_patch_paths.py`
9. `mcp_normalization.py`
10. `python_shell_injection.py`
11. `search_fusion.py`
12. `repository_scope.py`
13. `dashboard_contracts.py`
14. `operation_contracts.py`

Import boundaries: Boundary modules must not import heavy runtime-only
dependencies (such as NumPy) directly or transitively. Shared enums (e.g.
`MemoryKind` in `agent_identity.py`) are kept isolated from heavy engine
modules (`agent_memory.py`) so boundary type-checking remains pure, fast,
and strictly compatible with Python 3.11 syntax without requiring external
stub packages.

The legacy backlog remains explicit: `services.py`, `deterministic.py`,
`http_server.py`, `commands.py`, and `mcp_server.py` are not yet under strict
mypy. Expand coverage by boundary as those monoliths are split; do not treat
the targeted gate as whole-repository typing acceptance.
