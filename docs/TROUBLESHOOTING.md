# Troubleshooting

## Hub will not start
Run `local-ai-hub --version`, then `python tools/doctor.py`. Invalid TOML now fails fast; fix the reported file/key instead of deleting state blindly. Check that the configured port is free.

## Serena/CodeGraph unavailable
Check the code-intelligence status in the dashboard, rediscover executables, then reset sessions. Setup can reinstall isolated tool environments. Deterministic/code-index/search operations should continue while these backends are degraded.

## Context references a deleted temp repository
Use a stable project root. The API returns a structured stale/degraded result rather than crashing; callers should discard the obsolete root.

## Commands are blocked
Use `local_ai_command(action="classify")`. Unknown, mutating, install/deploy/publish/clean and unsafe formatter commands are denied by default. Run intentional mutation directly under user control rather than weakening the hub policy.

## Dashboard authentication
Set the API token in the dashboard toolbar for the current browser session. The token is not placed in the URL.
