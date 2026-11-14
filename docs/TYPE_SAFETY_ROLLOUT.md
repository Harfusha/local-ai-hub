# Type safety rollout

CI runs `python -m mypy` with `strict = true` on ten extracted boundary modules
listed in `pyproject.toml`. Add every new extracted API boundary to that list
before merging its slice. The development extra provides the checker.

The strict set includes `source_outline.py`, `mcp_lifecycle_contracts.py`,
`command_redaction.py`, `evidence_merge.py`, `http_event_cursor.py`,
`external_candidate_paths.py`, `agent_event_pages.py`,
`command_patch_paths.py`, `mcp_normalization.py`, and
`python_shell_injection.py`.

The legacy backlog remains explicit: `services.py`, `deterministic.py`,
`http_server.py`, `commands.py`, and `mcp_server.py` are not yet under strict
mypy. Expand coverage by boundary as those monoliths are split; do not treat
the targeted gate as whole-repository typing acceptance.
