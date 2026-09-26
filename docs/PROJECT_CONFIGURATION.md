# Project configuration

Local AI Hub reads optional project settings from four layers, low to high:

1. Built-in defaults.
2. Repository root `.local-ai.toml`.
3. Git common directory `info/local-ai.toml`, shared by linked worktrees.
4. Repository root `.local-ai.worktree.toml`, local to that worktree.

Single-developer deployments may keep settings durably in local config sources. These files are never required for Hub startup. Config files must resolve within their project or Git common source root; escaping links are rejected. Invalid configuration rejects the complete overlay and returns built-in defaults with a safe error code.

## Inheritance

Maps merge by key. A higher layer replaces values for keys it names while unrelated lower-layer keys remain. Lists replace as a whole; a worktree's `exclude_paths` or `force_include_paths` therefore replaces that list from lower layers. `path_overrides` keys normalize separators before merging; Windows also folds case. Equivalent keys in higher layers replace lower values. Duplicate equivalent keys in one layer reject that overlay.

## Supported settings

- `exclude_paths`, `force_include_paths`, `path_overrides`, and `[preprocess].exclude_paths` control path policy. Explicit excludes and hard boundaries beat force includes.
- `[custom_extensions].text`, `[custom_extensions].binary`, and `[file_limits].max_file_size_bytes` set file handling limits. A configured size cap rejects missing or malformed size evidence and files larger than the cap.
- `skip_phases` accepts `rag`, `call_graph`, and `modules`. `phase_is_allowed(settings, phase)` denies unknown phase names before an optional phase starts; `path_is_allowed(...)` and `may_descend(...)` deny unknown path phases and candidates in skipped optional phases. Known path phases include `search`, `repository_search`, `preprocess`, and `test`; optional phases use the names above. Task-facing settings also include `commands`, `affected_tests_mapping`, `env`, and additive `verification_rules`.
- Literal repo-relative `pinned_context` files (no glob syntax), literal `entry_points` (files or directories; no glob syntax), and `[retrieval_weights]` provide retrieval inputs. `resolve_pinned_context(...)` returns existing repo-contained pinned candidates after `path_is_allowed`; `resolve_entry_points(...)` does the same for files and directories, using `may_descend(...)` for directories. These are candidates, not read authorization: consumers must reapply policy with actual soft-ignore/hard-deny state before reading pinned files and during every directory traversal. `project_type`, `solution_path`, and `[language_overrides]` provide project and language context; `model_profile` selects the project model context. `system_prompt_prefix` supplies task-prompt context; T21 does not define a separate `task_profile` key.
- `shared_namespace` shares hints across linked worktrees under the same Git common directory and partitions them by namespace; different common directories remain isolated. Environment values must reference host variables as `${NAME}`; config never stores secret values.

Example project or worktree file:

```toml
project_type = "python"
model_profile = "balanced"
shared_namespace = "widget"
exclude_paths = ["vendor/**"]
force_include_paths = ["build/generated/keep.py"]
skip_phases = ["call_graph"]
pinned_context = ["README.md"]
entry_points = ["src/main.py"]

[preprocess]
exclude_paths = ["generated/**"]

[file_limits]
max_file_size_bytes = 1048576

[commands.check]
argv = ["python", "-m", "pytest", "-q"]

[commands.check.env]
CI_TOKEN = "${HOST_CI_TOKEN}"

[verification_rules]
require_receipt = true

[retrieval_weights]
lexical = 0.6

[language_overrides.python]
text_extensions = [".py"]
```

Command values are data; resolver does not execute them. Host variable names resolve only in the owning command adapter.

## Path patterns and overrides

Path patterns are repository-relative, use `/`, reject control characters, and cannot contain `.` or `..` path segments. `*`, `?`, and character classes match within one path segment. A segment exactly equal to `**` matches zero or more segments.

`exclude_paths` marks project exclusions. Each exclude glob is checked against both the normalized repository-relative lexical path (before following symlinks) and the resolved target path. A match on either path excludes the candidate, even when reached through a symlink alias. Exclusions win over both `path_overrides` and `force_include_paths`. Force includes can override inherited standard ignore state only. `path_overrides` provides per-pattern decisions for paths not covered by `exclude_paths`:

```toml
exclude_paths = ["vendor/**"]
force_include_paths = ["build/generated/keep.py"]

[path_overrides]
"build/**" = "exclude"
"build/generated/keep.py" = "include"
"build/local/**" = "default"
```

Allowed actions are `include`, `exclude`, and `default`; schema accepts at most 512 override patterns per merged configuration. Same-pattern values from higher layers replace lower-layer values; unrelated patterns remain inherited. At runtime, the most-specific matching pattern wins across lexical alias and resolved target. More literal segments and characters increase specificity; fewer `**` segments and fewer wildcards break remaining ties. Equal-specificity conflict resolves to `exclude`. A winning `default` falls through to `force_include_paths` and inherited ignore state; explicit `exclude_paths` still denies it.

Project path decisions remain bounded by root containment, hard denial, binary policy, configured maximum file size, and preprocessing-only exclusions. Symlinks resolving outside the project root are hard denied. `force_include_paths` and `path_overrides` cannot bypass containment or hard denial. A missing size measurement denies a file when a maximum size is configured. No override can bypass those boundaries.

Directory walkers must call `may_descend(...)` before pruning a directory. A soft-ignored parent remains traversable if a `force_include_paths` pattern or `path_overrides` `include`/`default` may match the directory or a descendant. Each file must still pass `path_is_allowed(...)`.

## Local-only config

`.local-ai.toml` and `.local-ai.worktree.toml` are resolver inputs and are excluded from normal project scans, pinned context, and entry-point candidates. The worktree override should remain untracked. The Git common-directory file is outside the worktree and is not committed with the repository.

Hub-wide configuration is separate: `config.py::load_config` merges installation defaults, user `config.toml`, and its adjacent `config.runtime.toml`. The project resolver does not read or write those files. `state_dir` holds only the bounded path-hint database, not project configuration.

## Core API for retrieval

`resolve_project_context(root, state_dir)` returns immutable effective settings and a `config_digest`. It keeps config in the project or Git common directory; the state directory stores only bounded, evidence-bound path hints.

Call `ProjectContext.prioritize_paths(candidates, purpose, scope, repository_revision, path_hints=())` to rank the complete candidate list in this order: configured literal `entry_points`, per-call `path_hints`, then saved hints matching current scope, revision, and config digest. The optional `path_hints` argument is a tuple of `PathHint` records; it is request-scoped and is not persisted. Ranking preserves every candidate and returns `PathHintUsage`. Consumers measure usefulness, report it with `report_path_hint_outcome(...)`, and use the normal broader fallback when no hint helps. Save only verified hints through `ProjectContext.save_path_hint(...)`.

Use one optional wire field, `path_hints`, for search-oriented repo, command, or MCP requests that rank repository candidates. Its JSON shape is an array of objects with required string fields `path`, `purpose`, and `scope`, plus optional string fields `evidence_id`, `provenance`, `repository_revision`, `config_digest`, and `expires_at`. Cap it at 64 records at ingress; core also caps direct calls. There is no `paths` alias. Keep this separate from command argument paths, changed paths, focus text, and durable `entry_points`. Request hints may omit evidence metadata; learned/persisted hints require evidence ID, provenance, matching repository revision and config digest.

Resolve hints beneath the trusted project root and reject absolute, drive/UNC, traversal, glob, missing, and symlink/junction escape paths. A hint can reorder candidates only: it cannot choose the root, authorize a path, narrow recall, bypass exclusions or trust checks, or change security scope. Consumers still apply `path_is_allowed(...)` to each file and `may_descend(...)` to each directory. Never write raw paths or hint contents to telemetry.

Retrieval adapters must call this API at their owned integration seam. The core API does not change HTTP, MCP, search, preprocessing, RAG, or command behavior by itself.

`path_matches_pattern(path, pattern)` exposes the same validated repo-relative glob matching for owned adapters. T21 currently wires project mapping, entry points, request hints, saved hints, and post-ranking path policy into T06's released `LocalAIServices.affected_tests` seam. Other adapters remain owner-gated.
