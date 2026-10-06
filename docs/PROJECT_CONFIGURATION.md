# Project configuration

Local AI Hub reads optional project settings from four layers, low to high:

1. Built-in defaults.
2. Primary repository root `.local-ai.toml`, inherited by linked worktrees.
3. Current worktree root `.local-ai.toml`, when distinct from primary root.
4. Git common directory `info/local-ai.toml`, shared by linked worktrees.
5. Current worktree root `.local-ai.worktree.toml`.

The resolver finds the primary worktree through Git's common directory and bounded `git worktree list --porcelain` fallback. The current worktree's project file can override inherited keys; its worktree file remains the highest local layer.

Single-developer deployments may keep settings durably in local config sources. These files are never required for Hub startup. Config files must resolve within their project or Git common source root; escaping links are rejected. Invalid configuration rejects the complete overlay and returns built-in defaults with a safe error code.

## Inheritance

Maps merge by key. A higher layer replaces values for keys it names while unrelated lower-layer keys remain. Lists replace as a whole; a worktree's `exclude_paths` or `force_include_paths` therefore replaces that list from lower layers. `path_overrides` keys normalize separators before merging; Windows also folds case. Equivalent keys in higher layers replace lower values. Duplicate equivalent keys in one layer reject that overlay.

## Supported settings

- `exclude_paths`, `force_include_paths`, `path_overrides`, and `[preprocess].exclude_paths` control path policy. Explicit excludes and hard boundaries beat force includes.
- `[custom_extensions].text`, `[custom_extensions].binary`, and `[file_limits].max_file_size_bytes` configure file classification and size policy. `custom_extension_kind(path, settings, language=...)` returns `text`, `binary`, or `None`; matching is case-insensitive and supports compound extensions such as `.tar.gz`. `path_is_allowed(...)` rejects configured binary extensions. Readers and indexers must call `custom_extension_kind(...)` before interpreting content; adapter adoption remains owner-gated. A configured size cap rejects missing or malformed size evidence and files larger than the cap.
- `skip_phases` accepts `rag`, `call_graph`, and `modules`. `phase_is_allowed(settings, phase)` denies unknown phase names before an optional phase starts; `path_is_allowed(...)` and `may_descend(...)` deny unknown path phases and candidates in skipped optional phases. Known path phases include `search`, `repository_search`, `preprocess`, and `test`; optional phases use the names above. Task-facing settings also include `commands`, `affected_tests_mapping`, `env`, and additive `verification_rules`. Verification rule values accept only `true` or a non-empty array of non-blank strings; `false`, empty arrays, and malformed entries reject the overlay. Rule keys are intended to match task acceptance criteria; `true` requires configured `lint` and `test` receipts; arrays list exact command aliases. The T21 branch's `VerificationStore.completion()` lacks project-rule and mutation-generation parameters, so `verification_rules.py` remains a proposed bridge. A read-only audit of T09 candidate `968443549f2a68d17df26689cd49874d1ce400de` found a dirty, unreleased `evaluate_completion_receipts` implementation and a `completion()` wrapper forwarding owner, revision, mutation generation, project rules, configured criteria, mapped receipt IDs, and persisted receipts. This is not a release or runtime integration proof; require T09 owner release and a compatible change in the T21 base before claiming integration. Command aliases are a separate `commands` mapping from `_KEY` names to shell strings or typed `argv` definitions.
- Literal repo-relative `pinned_context` files (no glob syntax), literal `entry_points` (files or directories; no glob syntax), and `[retrieval_weights]` provide retrieval inputs. `resolve_pinned_context(...)` returns existing repo-contained pinned candidates after `path_is_allowed`; `resolve_entry_points(...)` does the same for files and directories, using `may_descend(...)` for directories. These are candidates, not read authorization: consumers must reapply policy with actual soft-ignore/hard-deny state before reading pinned files and during every directory traversal. `project_type`, `solution_path`, and `[language_overrides]` provide project and language context; `model_profile` accepts `integrated`, `balanced`, `high`, or `max`; an absent setting defaults to `balanced`. The resolver validates the name but does not check runtime model availability or apply the profile to a consumer. `system_prompt_prefix` is optional untrusted text limited to 4000 characters; an absent setting is `None`. Only an owning system-prompt builder may add it below fixed system policy. Never concatenate it into task or context text. Core stores the value but does not apply it. T21 defines no separate `task_profile` key.
- `shared_namespace` shares hints across linked worktrees under the same Git common directory and partitions them by namespace; different common directories remain isolated. Top-level `[env]` keys must use portable environment identifier syntax (`[A-Za-z_][A-Za-z0-9_]*`). It accepts literal project values such as `PYTHONPATH = "."` and `NODE_ENV = "test"`; values written as `${NAME}` remain host-environment references in `env_references`. Keep secrets in host variables, not literal config values.

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

[env]
PYTHONPATH = "."
NODE_ENV = "test"
API_TOKEN = "${HOST_API_TOKEN}"

[verification_rules]
tests = ["check"]

[retrieval_weights]
lexical = 0.6

[language_overrides.python]
text_extensions = [".py"]

```

Command values are data; resolver does not execute them. Host variable names resolve only in the owning command adapter.

The `verification_rules` table maps exact task acceptance-criterion names to receipt requirements. In the example, the task criterion must be `tests`; the array names configured command aliases. `verification_rules.py::evaluate_project_completion(...)` is a T21-owned proposed bridge contract. It forwards repository revision, mutation generation, settings rules, and command aliases to a typed store protocol; its positive test uses a stand-in. `evaluate_completion_receipts` and its `VerificationStore.completion()` wrapper exist only in the separately inspected, dirty T09 candidate, not in this T21 checkout. Require T09 owner release plus a compatible base/API before claiming live integration. The intended completion gate does not execute commands or mutate task state.

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

Hub-wide configuration is separate: `config.py::load_config` merges installation defaults, user `config.toml`, and its adjacent `config.runtime.toml`. The project resolver does not read or write those files. `state_dir` holds only derived, bounded path hints, not project configuration.

## Core API for retrieval

`resolve_project_context(root, state_dir)` returns immutable effective settings and a `config_digest`. It keeps config in the project or Git common directory; the state directory stores only bounded, evidence-bound path hints.

Call `ProjectContext.prioritize_paths(candidates, purpose, scope, repository_revision, path_hints=())` to rank the complete candidate list in this order: configured literal `entry_points`, per-call `path_hints`, then saved hints matching current scope, revision, and config digest. The optional `path_hints` argument is a tuple of `PathHint` records; it is request-scoped and is not persisted. Ranking preserves every candidate and returns `PathHintUsage`. `hint_helped` remains unknown until a consumer measures usefulness; `telemetry_metadata()` exposes only `hint_used`, `fallback_used`, and `hint_helped`, without candidate paths. Consumers use the normal broader fallback when no hint helps. Save only verified hints through `ProjectContext.save_path_hint(...)`.

Use one optional wire field, `path_hints`, for search-oriented repo, command, or MCP requests that rank repository candidates. Its JSON shape is an array of objects with required string fields `path`, `purpose`, and `scope`, plus optional string fields `evidence_id`, `provenance`, `repository_revision`, `config_digest`, and `expires_at`. Cap it at 64 records at ingress; core also caps direct calls. There is no `paths` alias. Keep this separate from command argument paths, changed paths, focus text, and durable `entry_points`. Request hints may omit evidence metadata; learned/persisted hints require evidence ID, provenance, matching repository revision and config digest.

Resolve hints beneath the trusted project root and reject absolute, drive/UNC, traversal, glob, missing, and symlink/junction escape paths. Saved hints are reused only for exact project identity, purpose, scope, repository revision, and config digest; expired rows are excluded and paths are revalidated on every read. Rows for older contexts may remain for linked worktrees and revision rollback, but never match a different current context; normal cap pruning may evict them. Storage caps retention at 256 hints per project/purpose/scope/revision/digest and 4096 per project. A hint can reorder candidates only: it cannot choose the root, authorize a path, narrow recall, bypass exclusions or trust checks, or change security scope. Consumers still apply `path_is_allowed(...)` to each file and `may_descend(...)` to each directory. Never write raw paths or hint contents to telemetry.

Retrieval adapters must call this API at their owned integration seam. The core API does not change HTTP, MCP, search, preprocessing, RAG, or command behavior by itself.

`path_matches_pattern(path, pattern)` exposes the same validated repo-relative glob matching for owned adapters. The T21 candidate wires project mapping, entry points, request hints, saved hints, and post-ranking path policy into `LocalAIServices.affected_tests` and the `run_affected` command branch. This is code presence, not release evidence: the T06 owner reports no verified release receipt for these seams. Treat them as candidate behavior until T06 supplies the exact release revision and focused passing receipt. Other adapters remain owner-gated.
