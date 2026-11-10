# Export Existing Hub Cards for Training Data

**Decision:** Training data must come from semantic cards already persisted by Local AI Hub. Do not generate replacement or new cards through a teacher model as part of collection.

**Current operator steering:** Per-example consent manifests and receipt IDs are not required. Existing-card listing stays metadata-only; export uses only existing indexed cards and matching source rows from registered roots, skips known deterministic card models, and confines generated datasets to `state_dir`. Resume keeps only rows that still match current index identity and hashes. This spec does not authorize card generation, inference, or training.

**Scope:** Use a bounded collector over the configured preprocessing SQLite index. Require an explicit roots manifest or an explicit `--all-indexed` choice. First list eligible row IDs and metadata without returning card or source text. Export locally from registered roots, using only already-stored eligible cards and source rows. Query source text only after root authorization, then confirm its indexed hash still matches the card. Preserve opaque project grouping, content hashes, card model/version, group-held-out splits, and runtime-state output paths. Never create cards, invoke a model, or start preprocessing during collection.

**Constraints:** Collection must not start preprocessing, invoke an LLM, download a model, or change routing. Missing or stale indexes/cards are reported and never synthesized. This change prepares data only and does not train or live-benchmark any model.
