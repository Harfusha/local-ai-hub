# Token Economy & Optimization Guide

Local AI Hub is engineered around **token-first economy**: maximizing the signal-to-noise ratio in model context windows, eliminating redundant file dumps, preventing terminal pollution, and offloading microtasks to free, local Ollama models.

---

## 1. Why Token Economics Matters

Every token sent to a cloud frontier model (GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro) carries three distinct costs:
1. **Financial Cost**: API pricing scales linearly with prompt input tokens and output tokens.
2. **Latency**: Time-to-first-token (TTFT) and throughput degrade as context grows into tens of thousands of tokens.
3. **Attention Degradation (Lost in the Middle)**: LLMs degrade in reasoning accuracy, instruction adherence, and hallucination rate when overloaded with full-file dumps and verbose compiler output.

By combining Local AI Hub's deterministic index with the **Token Economy Suite**, agents typically achieve an **80–95% reduction in cloud token consumption** and dramatic speedups.

---

## 2. The One-Command Experience: "Install Local AI Hub"

Any user can clone or download Local AI Hub and either run a single command in terminal or simply tell their AI coding assistant:

> **"Install Local AI Hub"** *(or "Nainstaluj local ai hub")*

The automated setup runner (`install.ps1` / `install.sh` / `python tools/setup.py`):
1. **Bootstraps Python 3.11+ & Virtual Environment** (`.venv`).
2. **Installs Core & Token Economy Dependencies**:
   - `mcp`, `watchdog`
   - `tiktoken` (exact o200k/cl100k token computation)
   - `files-to-prompt` (structured XML file packing)
   - `grep-ast` (syntax-aware AST search)
3. **Deploys CLI Executables & Wrappers**:
   - `tokcount` (exact token counter)
   - `trim-run` (ANSI stripper & head/tail output truncator)
   - `repo-map` (multi-language AST codebase mapper)
4. **Probes & Auto-Installs External CLI Tools**:
   - `ripgrep` (`rg`): Fast regex search via `winget` / `brew` / `apt`.
   - `fd` / `fd-find`: Lightning-fast file indexing via `winget` / `brew` / `apt`.
   - `ast-grep` (`sg`): Structural AST pattern matcher via `npm`.
   - `repomix`: Repository context compactor via `npm`.
   - `jq`: High-speed JSON stream processor and projection filter via `winget` / `brew` / `apt`.
5. **Configures Local Ollama Runtime & Models**:
   - Auto-starts Ollama daemon.
   - Pulls default fast tier (`qwen2.5-coder:7b`) and embedding models (`bge-m3` or `nomic-embed-text`).
6. **Auto-Wires MCP Hosts & Skills**:
   - Configures MCP endpoints into **Codex**, **Claude Desktop**, **Gemini**, **Cursor**, **Windsurf**, and **VS Code / GitHub Copilot**.
   - Installs companion skills: `token-economizer`, `caveman`, `tool-orchestration`, `ollama-quality-routing`.
   - Injects the `LOCAL AI HUB TOOL POLICY` and `TOKEN ECONOMY POLICY` into `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`.
7. **Starts Local AI Hub Daemon** & executes self-testing diagnostics.

---

## 3. Tool Inventory

| Tool | Source / Install | Purpose | Typical Token Savings |
| :--- | :--- | :--- | :--- |
| **`tokcount`** | Built-in CLI | Exact token measurement for files, dirs, or stdin (`o200k_base`, `cl100k_base`) | Context budgeting |
| **`trim-run`** | Built-in CLI | Strips ANSI escapes; truncates massive test/build logs to first/last $N$ lines | 70–95% output reduction |
| **`repo-map`** | Built-in CLI | AST structural outline of classes, methods, and functions across 12 languages | 80–90% vs full files |
| **`rg`** (`ripgrep`) | `winget` / `brew` / `apt` | Fast bounded regex search (`-m <N>`, `--max-columns <N>`) | 80–95% vs unconstrained grep |
| **`fd`** (`fd-find`) | `winget` / `brew` / `apt` | Lightning-fast file/directory discovery (`-d <depth>`) | 85–95% vs recursive directory trees |
| **`jq`** | `winget` / `brew` / `apt` | JSON projection: extract only relevant keys from API and CLI outputs | 70–98% vs raw JSON dumps |
| **`grep-ast`** | PyPI (`grep-ast`) | Syntax-aware search: returns matching lines with enclosing function/class definitions | 60–85% vs dumping files |
| **`ast-grep` (`sg`)** | npm (`@ast-grep/cli`) | Fast structural AST pattern searching and linting across codebases | 90% vs raw grep dumps |
| **`repomix`** | npm (`repomix`) | Packs repos with comment stripping, empty line removal, and token counts | 40–60% vs raw directory |
| **`files-to-prompt`** | PyPI (`files-to-prompt`) | Formats files into clean XML prompt structures without shell overhead | Clean prompt format |
| **`local_ai_artifact`** | Local AI Hub MCP | Fetches exact line slices (`slice`) or evidence fragments | Zero whole-file reads |
| **`local_ai_task`** | Local AI Hub MCP | Local model inference (`qwen2.5-coder:7b`) for summarization, lint fixing, second opinions | 100% free (0 cloud tokens) |
| **`local_ai_command`** | Local AI Hub MCP | Single-flight cached command broker with automated ANSI stripping | Prevents rerun token waste |

---

## 4. Usage Examples & Recipes

### A. Measuring Token Impact Before Loading Context
```bash
# Count tokens in a file
tokcount src/main.py

# Measure git diff size before review
git diff | tokcount

# Check entire directory with quiet token count
tokcount src/ -q
```

### B. Bounded Command & Test Execution
```bash
# Run pytest with automatic truncation to 40 lines
trim-run -n 40 pytest -q

# Truncate verbose git log or build output via pipe
git log --oneline -n 100 | trim-run -n 30
```

### C. High-Density Codebase Mapping
```bash
# Map entire codebase (default 250 lines)
repo-map .

# Map specific subdirectory with higher line limit
repo-map src/local_ai_hub --max-lines 500
```

### D. Structural AST Code Search
```bash
# Search for all async function definitions
sg scan --pattern 'async function $NAME($$$) { $$$ }'

# Search for React hooks
sg scan --pattern 'useEffect($$$)'
```

### E. Bounded Text & File Search (`rg` & `fd`)
```bash
# Search for patterns with bounded matches (avoid massive output)
rg -n -m 5 "def load_config" src/

# Find files matching pattern within 3 directory levels
fd -e py -d 3 config
```

### F. JSON Filtering with `jq`
```bash
# Extract only relevant fields from API or CLI responses
curl -s http://127.0.0.1:11435/api/live/status | jq '{version, hub_online, active_model}'

# Filter complex JSON arrays to minimal identifier tuples
cat data.json | jq '[.items[] | {id: .id, name: .name}]'
```

### G. Compact Git Hygiene
```bash
# Compact git inspection
git status -s
git diff --stat
git log -n 5 --oneline
```

---

## 5. Agent Rules of Engagement (Token Economy Policy)

When paired with an AI coding agent, the following rules are permanently active in `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`:

```markdown
<!-- BEGIN TOKEN ECONOMY POLICY -->
- Zero full-file dumping: Never read files >80 lines in their entirety. Use `repo-map` for high-level structure, `grep-ast <pattern> <file>`, targeted line slices, or `local_ai_artifact(action="slice")`.
- Fast code search: Use `rg` (`ripgrep`) with `-m 5` / bounded matches and `fd` for file finding before opening files.
- AST & structural code search: Use `ast-grep` (`sg`), Serena LSP (`find_symbol`, `find_referencing_symbols`), or `local_ai_repo(action="code_index")` before opening files.
- Context compression & token measurement: Use `repomix --compress` or `files-to-prompt -c` for repo snapshots. Use `tokcount` to measure exact tokens.
- Bounded command outputs: Filter test and build output (`trim-run <cmd>`, `pytest -q --tb=short`, `dotnet test --verbosity quiet`, `git log | trim-run`, `jq` for JSON) or route through `local_ai_command`.
- Surgical edits: Prefer targeted block replacements over rewriting entire files.
- Local model delegation: Route routine microtasks, reviews, and second opinions to local models via `local_ai_task(model="qwen2.5-coder:7b")`.
<!-- END TOKEN ECONOMY POLICY -->
```
