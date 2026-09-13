# Preprocessed Resource Metrics and 30-Day Restart History

## Goal

Provide operator visibility into two distinct performance dimensions:
1. **Preprocessed Resource Utilization**: Measure how effectively background indexing serves agent repository queries (Query Index Hit Rate) and how effectively incremental scans reuse existing content-addressed cards (Ingestion Reuse Rate), without polluting or conflating LLM generation cache metrics.
2. **30-Day Restart & Session History**: Track process session lifecycles (start, heartbeat, clean stop, or crash/abnormal termination) over the last 30 days in persistent telemetry and display a structured restart history table on the Dashboard.

## Architecture and Components

### 1. Preprocessed Resource Metrics

#### 1.1 Ingestion Card Reuse Rate
* **Source**: Background preprocessor stats in `src/local_ai_hub/preprocess.py`.
* **Definition**: Ratio of files processed that reused an existing content card (via content-addressable hash match across worktrees or deterministic AST) versus files requiring full card generation:
  $$\text{ingestion\_reuse\_rate} = \frac{\text{file\_card\_hits} + \text{deterministic\_card\_hits}}{\max(1, \text{file\_card\_hits} + \text{deterministic\_card\_hits} + \text{file\_card\_generations})}$$
* **Exposition**: Included in `preprocessor.status()` and surfaced via `/api/status` under `preprocessing.ingestion_reuse_rate` along with raw hit and generation counts.

#### 1.2 Query Index Hit Rate
* **Source**: Repository queries in `src/local_ai_hub/services.py` (`repo_search`, `repo_code_index`, `repo_deterministic`, `repo_context`).
* **Definition**: Ratio of repository requests that were resolved or narrowed using warm preprocessed data (FTS tables, AST indexes, candidate paths) versus cold fallback operations (full filesystem walks, raw regex/grep scans):
  $$\text{query\_index\_hit\_rate} = \frac{\text{preprocessed\_query\_hits}}{\max(1, \text{preprocessed\_query\_hits} + \text{preprocessed\_query\_misses})}$$
* **Telemetry**: Recorded as `preprocessed_hit: bool` in HTTP telemetry events and tracked in `telemetry.py` aggregate summaries.

### 2. Persistent Process Sessions (Restart History)

#### 2.1 Database Schema
In `src/local_ai_hub/telemetry.py`, maintain a persistent table in `state/telemetry.sqlite3`:
```sql
CREATE TABLE IF NOT EXISTS process_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL,
    stopped_at REAL,
    last_heartbeat REAL NOT NULL,
    exit_clean INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_process_sessions_started ON process_sessions(started_at);
```

#### 2.2 Lifecycle Management
* **Start**: On hub startup in `http_server.py`, invoke `telemetry.session_start(pid, version)` to insert a session row with `started_at = time.time()`, `last_heartbeat = time.time()`.
* **Heartbeat**: During periodic telemetry flushes (`_writer_loop`), update `last_heartbeat = time.time()` for the active session.
* **Clean Stop**: On graceful shutdown in `http_server.py`, invoke `telemetry.session_stop()` to set `stopped_at = time.time()` and `exit_clean = 1`.
* **Crash / Unclean Exit Detection**: If a session row has `exit_clean = 0` and `stopped_at IS NULL`, and either a newer session started or the current process ID does not match, the session is classified as `crashed` / `unclean_exit` with effective duration calculated up to `last_heartbeat`.

#### 2.3 Session Aggregation (30-Day Window)
A method `telemetry.sessions(days=30)` queries `process_sessions` where `started_at >= cutoff`. For each session interval `[started_at, COALESCE(stopped_at, last_heartbeat)]`, compute aggregated metrics from the `events` table:
* `events`: total HTTP/inference events processed
* `generation_cache_hit_rate`: cache hit rate during that session
* `net_cloud_token_delta`: estimated tokens saved during that session
* `status`: `active` (current running session), `clean_stop` (`exit_clean == 1`), or `crashed` (`exit_clean == 0` and not running)
* `uptime_seconds`: `stopped_at - started_at` (or `last_heartbeat - started_at` if crashed, `time.time() - started_at` if active)

### 3. Dashboard and API Surface

#### 3.1 Status & Report API
* `/api/status` exposes:
  * `preprocessing.query_hit_rate`
  * `preprocessing.ingestion_reuse_rate`
* `telemetry.realtime_summary()` and `telemetry.dashboard_report()` include:
  * `sessions`: list of session dictionaries for the last 30 days.

#### 3.2 Dashboard UI (`src/local_ai_hub/dashboard.py`)
* **Top Metric / Subtext**:
  * In the Cache / Preprocessing card, present:
    `Query Hit: X% · Ingestion Reuse: Y%`
* **Restart History Table**:
  * A dedicated table rendered in the dashboard (under Runtime / Supervisor section):
    * **Started**: Formatted local datetime (e.g., `2026-09-12 14:30`)
    * **Uptime / Duration**: Human-readable duration (`2d 4h`, `45m`, etc.)
    * **Status**: Badge (`Active` [green], `Clean stop` [neutral], `Crashed / Killed` [warning])
    * **Events**: Total requests handled
    * **Cache Hit Rate**: Generation cache hit % for that session
    * **Net Tokens Saved**: Estimated cloud tokens avoided

## Acceptance Criteria

1. Preprocessing stats expose mathematically accurate `ingestion_reuse_rate` without division-by-zero errors.
2. Repo queries accurately identify preprocessed vs fallback execution and compute `query_index_hit_rate`.
3. Process startup and graceful shutdown record sessions in `process_sessions`.
4. Crashes/unclean restarts are detected and reported with uptime bounded by `last_heartbeat`.
5. Dashboard renders the 30-day restart history table with accurate session metrics.
6. All existing telemetry and regression suites pass without regressions.
