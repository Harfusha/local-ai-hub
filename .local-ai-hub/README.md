# Local AI Hub Project Workspace

This directory contains repository-owned project plans, adopted specifications, and decisions.

## Governance Rules
- `plans/`: Authoritative, versioned `.plan.json` files for durable project goals, releases, and milestones.
- Ephemeral / smoke / local plans: Test, smoke (`*smoke*.plan.json`), and temporary scratch plans are ignored by Git.
- `local/`: Machine-local cache, durable intents, and runtime session bindings (ignored by Git).
