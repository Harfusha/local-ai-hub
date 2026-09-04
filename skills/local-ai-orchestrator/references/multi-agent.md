# Multi-agent coordination

All clients share canonical cache, RAG, code index, evidence store, command broker and scheduler. Agent-specific projection happens after expensive work, so Codex, Claude, Antigravity, and Gemini can reuse one local result without receiving the same payload shape.

Use a write lease only when edits may overlap. Claim the smallest path scope and release promptly. Before repeating investigation, check a compact workspace memo when a previous agent is likely to have produced a durable conclusion. Store only short verified handoffs, not conversation transcripts.

Evidence IDs include source fingerprints. Verify them before applying an older finding when another agent may have changed the same file. Cache hits never replace this stale-context check for edits.
