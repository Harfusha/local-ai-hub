---
name: token-economizer
description: Use when starting any coding or repository task involving source discovery, file reading, tests, command output, or code review.
---

# Token Economizer

Load and follow this skill before any coding or repository task. Apply its discovery, reading, and output limits even when a task is urgent; use the token-economy tools whenever they are available.

## Available Token-Saving Tooling

1. **`tokcount <path|stdin>`**:
   - Computes exact token count (o200k/Astra, cl100k/Codex) for any file, folder, or pipe.
   - Example: `tokcount src/` or `git diff | tokcount`

2. **`trim-run [-n 40] <command>` / `cmd | trim-run`**:
   - Universal terminal wrapper: runs commands, strips ANSI codes, truncates large output dumps to first/last N lines.
   - Example: `trim-run pytest -q` or `git log | trim-run`

3. **`repo-map [dir] [-n 200]`**:
   - Generates high-density AST skeleton (classes, methods, signatures) of the whole repo using Tree-sitter / grep-ast without reading file bodies.

4. **`grep-ast <pattern> <file>`**:
   - AST-aware search: returns matching lines with parent class/function scope instead of dumping the file.

5. **`ast-grep scan --pattern '<pattern>'` (or `sg`)**:
   - Fast structural AST search across codebase without loading files into context.

6. **`repomix --compress --output <file>`**:
   - Packs repo with comment stripping, blank line removal, Tree-sitter compression, and token counts.

7. **`files-to-prompt -c <paths...>`**:
   - Formats selected files into structured LLM XML without shell overhead.

8. **`local_ai_artifact(action="slice")`**:
   - Fetches exact slice of a file (e.g. lines 120-160) without reading entire file.

9. **`local_ai_command`**:
   - Bounded command runner with automatic ANSI stripping and failure compression.

10. **`rg` (`ripgrep`)**:
    - Fast regex code search: always bound matches with `-m <N>` or `--max-columns <N>` to avoid context floods.

11. **`fd` (`fd-find`)**:
    - Fast file/dir discovery: use `fd <pattern> -d <depth>` instead of wide recursive trees.

12. **`jq <filter>`**:
    - Stream JSON filter: slice and project only necessary fields from API responses or command outputs (`cmd | jq '...'`).

## Rules of Engagement

### 1. Zero Full-File Dumping
- **NEVER** use `cat`, `type`, `Get-Content` or unconstrained reads on files larger than 80 lines.
- Use `repo-map` or `grep-ast` for orientation.
- Use `rg -m 5` or `fd` for bounded targeted search instead of unconstrained directory scans.
- Use targeted line ranges (`view_file` with `StartLine`/`EndLine`) or `local_ai_artifact(action="slice")`.
- Use **Serena** (`find_symbol`, `find_referencing_symbols`) or `ast-grep` before opening files.

### 2. Bounded Command & Test Outputs
- **NEVER** run verbose build/test commands raw into context.
- Always wrap terminal commands with `trim-run` or route through `local_ai_command`.
- Filter large JSON outputs with `jq` to extract only relevant fields before returning to LLM.
- Use minimal test flags: `pytest -q --tb=short`, `dotnet test --verbosity quiet`.
- Use compact git commands: `git status -s`, `git diff --stat`, `git log -n 5 --oneline`.

### 3. Surgical Edits (Diffs Over Rewrites)
- Prefer single-block replacements (`replace_file_content` / targeted patches) over rewriting entire files.
- Do not recite or parrot existing file contents before or after changes.

### 4. Offload to Local Model (Ollama / Local AI Hub)
- For microtasks (summarization, lint fixing, boilerplate, second opinion), delegate to local inference:
  - `local_ai_task(model="qwen2.5-coder:7b", ...)`
  - Zero cloud tokens consumed.

### 5. Concise Output (Caveman Protocol)
- Omit conversational filler, decorative preambles, and post-execution summaries of obvious changes.
- Focus strictly on file links, diff summaries, and failure diagnostics.
