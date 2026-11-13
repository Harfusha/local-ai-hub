# Type safety rollout

CI runs `mypy --strict` on the five extracted boundary modules listed in
`pyproject.toml`. Add every new extracted API boundary to that list before
merging its slice. The development extra provides the checker.

The legacy backlog remains explicit: `services.py`, `deterministic.py`,
`http_server.py`, `commands.py`, and `mcp_server.py` are not yet under strict
mypy. Expand coverage by boundary as those monoliths are split; do not treat
the targeted gate as whole-repository typing acceptance.
