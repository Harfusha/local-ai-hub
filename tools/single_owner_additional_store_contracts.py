"""Static supplemental SQLite contracts for the explicit offline converter.

This module is intentionally data-only: it does not open stores, execute SQL,
or transform persisted values. Captured trace payloads remain opaque text.
"""

ADDITIONAL_STORE_DDL = {
    "async_jobs": (
        {
            "async_jobs": """CREATE TABLE IF NOT EXISTS async_jobs (
job_id TEXT PRIMARY KEY, action TEXT NOT NULL, request_hash TEXT NOT NULL,
payload_json TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '',
artifact_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
attempts INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL,
trace_id TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT '',
dispatch_not_before REAL NOT NULL DEFAULT 0
)""",
            "async_job_progress": """CREATE TABLE IF NOT EXISTS async_job_progress (
job_id TEXT PRIMARY KEY, attempt INTEGER NOT NULL,
progress_percent REAL NOT NULL DEFAULT 0, current_stage TEXT NOT NULL DEFAULT '',
updated_at REAL NOT NULL
)""",
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_async_jobs_state ON async_jobs(state, lease_until, expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_async_jobs_dispatch ON async_jobs(state, dispatch_not_before, expires_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_async_jobs_active_dedupe ON async_jobs(request_hash) WHERE state IN ('queued','running')",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_async_jobs_request_id ON async_jobs(json_extract(payload_json, '$.request_id')) WHERE json_valid(payload_json) AND json_type(payload_json, '$.request_id')='text' AND json_extract(payload_json, '$.request_id')<>''",
        ),
    ),
    "work_orchestrator": (
        {
            "work_orders": """CREATE TABLE IF NOT EXISTS work_orders(
work_id TEXT PRIMARY KEY, root TEXT NOT NULL, task TEXT NOT NULL,
state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
cancel_requested INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
)""",
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_work_orders_state_created ON work_orders(state, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_work_orders_updated ON work_orders(updated_at DESC)",
        ),
    ),
    "debug_traces": (
        {
            "traces": """CREATE TABLE IF NOT EXISTS traces (
trace_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
agent TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '',
source TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
request_id TEXT NOT NULL DEFAULT '', async_job_id TEXT NOT NULL DEFAULT '',
scheduler_job_id TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
request_json TEXT NOT NULL DEFAULT '', effective_payload_json TEXT NOT NULL DEFAULT '',
output_text TEXT NOT NULL DEFAULT '', response_json TEXT NOT NULL DEFAULT '',
error TEXT NOT NULL DEFAULT '', text_bytes INTEGER NOT NULL DEFAULT 0,
created_at REAL NOT NULL, updated_at REAL NOT NULL, finished_at REAL NOT NULL DEFAULT 0,
expires_at REAL NOT NULL
)""",
            "trace_events": """CREATE TABLE IF NOT EXISTS trace_events (
trace_id TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
seq INTEGER NOT NULL, created_at REAL NOT NULL, event_type TEXT NOT NULL,
payload_json TEXT NOT NULL DEFAULT '',
PRIMARY KEY(trace_id, seq)
)""",
            "trace_content_meta": """CREATE TABLE IF NOT EXISTS trace_content_meta (
trace_id TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
content_field TEXT NOT NULL, event_seq INTEGER NOT NULL DEFAULT 0,
encoding TEXT NOT NULL, total_chars INTEGER NOT NULL DEFAULT 0,
total_bytes INTEGER NOT NULL DEFAULT 0,
storage_truncated INTEGER NOT NULL DEFAULT 0,
PRIMARY KEY(trace_id, content_field, event_seq)
)""",
            "trace_content_chunks": """CREATE TABLE IF NOT EXISTS trace_content_chunks (
trace_id TEXT NOT NULL, content_field TEXT NOT NULL,
event_seq INTEGER NOT NULL DEFAULT 0, chunk_index INTEGER NOT NULL,
chunk_text TEXT NOT NULL,
PRIMARY KEY(trace_id, content_field, event_seq, chunk_index),
FOREIGN KEY(trace_id, content_field, event_seq)
    REFERENCES trace_content_meta(trace_id, content_field, event_seq)
    ON DELETE CASCADE
)""",
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_traces_state_updated ON traces(state, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_traces_kind_created ON traces(kind, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_trace_events_created ON trace_events(created_at)",
        ),
    ),
    "telemetry": (
        {
            "events": """CREATE TABLE IF NOT EXISTS events (
id INTEGER PRIMARY KEY AUTOINCREMENT,
created_at REAL NOT NULL,
action TEXT NOT NULL DEFAULT 'unknown', model TEXT,
cache_hit INTEGER NOT NULL DEFAULT 0, coalesced INTEGER NOT NULL DEFAULT 0,
input_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
output_tokens INTEGER NOT NULL DEFAULT 0, avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
duration_ms REAL NOT NULL DEFAULT 0, success INTEGER NOT NULL DEFAULT 1,
cache_layer TEXT NOT NULL DEFAULT '', load_duration_ms REAL NOT NULL DEFAULT 0,
event_type TEXT NOT NULL DEFAULT 'inference', agent TEXT NOT NULL DEFAULT '',
request_id TEXT NOT NULL DEFAULT '', trace_id TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT '',
task_type TEXT NOT NULL DEFAULT '', complexity TEXT NOT NULL DEFAULT '', route TEXT NOT NULL DEFAULT '',
queue_wait_ms REAL NOT NULL DEFAULT 0, queue_age_ms REAL NOT NULL DEFAULT 0,
wait_count INTEGER NOT NULL DEFAULT 0, wait_duration_ms REAL NOT NULL DEFAULT 0,
service_ms REAL NOT NULL DEFAULT 0, status_code INTEGER NOT NULL DEFAULT 0,
degraded INTEGER NOT NULL DEFAULT 0, retry_count INTEGER NOT NULL DEFAULT 0,
fallback_used INTEGER NOT NULL DEFAULT 0, bypass_reason TEXT NOT NULL DEFAULT '',
terminal INTEGER NOT NULL DEFAULT -1, retryable INTEGER NOT NULL DEFAULT -1,
receipt_count INTEGER NOT NULL DEFAULT 0, error_type TEXT NOT NULL DEFAULT '',
error_fingerprint TEXT NOT NULL DEFAULT '', tool_calls INTEGER NOT NULL DEFAULT 0,
evidence_count INTEGER NOT NULL DEFAULT 0, response_bytes INTEGER NOT NULL DEFAULT 0,
gross_avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
gross_input_tokens_avoided INTEGER NOT NULL DEFAULT 0,
gross_output_tokens_avoided INTEGER NOT NULL DEFAULT 0,
agent_protocol_tokens INTEGER NOT NULL DEFAULT 0, tool_request_tokens INTEGER NOT NULL DEFAULT 0,
tool_response_tokens INTEGER NOT NULL DEFAULT 0, tool_schema_tokens INTEGER NOT NULL DEFAULT 0,
local_compute_tokens_avoided INTEGER NOT NULL DEFAULT 0, net_cloud_token_delta INTEGER NOT NULL DEFAULT 0,
cloud_token_overhead INTEGER NOT NULL DEFAULT 0, net_after_schema_token_delta INTEGER NOT NULL DEFAULT 0,
schema_adjusted_overhead INTEGER NOT NULL DEFAULT 0, savings_source TEXT NOT NULL DEFAULT '',
input_savings_source TEXT NOT NULL DEFAULT '', output_savings_source TEXT NOT NULL DEFAULT '',
savings_breakdown_json TEXT NOT NULL DEFAULT '', preprocessed_hit INTEGER NOT NULL DEFAULT 0,
root TEXT NOT NULL DEFAULT '', db_wait_ms REAL NOT NULL DEFAULT 0, exec_ms REAL NOT NULL DEFAULT 0,
serialization_ms REAL NOT NULL DEFAULT 0, db_wait_measured INTEGER NOT NULL DEFAULT 0,
exec_measured INTEGER NOT NULL DEFAULT 0, serialization_measured INTEGER NOT NULL DEFAULT 0
)""",
            "process_sessions": """CREATE TABLE IF NOT EXISTS process_sessions (
id INTEGER PRIMARY KEY AUTOINCREMENT, pid INTEGER NOT NULL, version TEXT NOT NULL DEFAULT '',
started_at REAL NOT NULL, stopped_at REAL, last_heartbeat REAL NOT NULL,
exit_clean INTEGER NOT NULL DEFAULT 0
)""",
            "errors": """CREATE TABLE IF NOT EXISTS errors (
id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
request_id TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT '',
component TEXT NOT NULL, operation TEXT NOT NULL, error_type TEXT NOT NULL,
fingerprint TEXT NOT NULL, safe_message TEXT NOT NULL,
retryable INTEGER NOT NULL DEFAULT 0, recovered INTEGER NOT NULL DEFAULT 0
)""",
            "snapshots": """CREATE TABLE IF NOT EXISTS snapshots (
id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
name TEXT NOT NULL, metrics_json TEXT NOT NULL
)""",
            "daily_rollups": """CREATE TABLE IF NOT EXISTS daily_rollups (
day TEXT NOT NULL, event_type TEXT NOT NULL, action TEXT NOT NULL,
agent TEXT NOT NULL, model TEXT NOT NULL, cache_layer TEXT NOT NULL,
success INTEGER NOT NULL, events INTEGER NOT NULL DEFAULT 0,
duration_ms REAL NOT NULL DEFAULT 0, queue_wait_ms REAL NOT NULL DEFAULT 0,
input_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
output_tokens INTEGER NOT NULL DEFAULT 0, avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
cache_hits INTEGER NOT NULL DEFAULT 0, fallback_count INTEGER NOT NULL DEFAULT 0,
degraded_count INTEGER NOT NULL DEFAULT 0, gross_avoided_cloud_tokens INTEGER NOT NULL DEFAULT 0,
gross_input_tokens_avoided INTEGER NOT NULL DEFAULT 0,
gross_output_tokens_avoided INTEGER NOT NULL DEFAULT 0,
agent_protocol_tokens INTEGER NOT NULL DEFAULT 0, tool_schema_tokens INTEGER NOT NULL DEFAULT 0,
local_compute_tokens_avoided INTEGER NOT NULL DEFAULT 0,
tool_request_tokens INTEGER NOT NULL DEFAULT 0, tool_response_tokens INTEGER NOT NULL DEFAULT 0,
net_cloud_token_delta INTEGER NOT NULL DEFAULT 0, cloud_token_overhead INTEGER NOT NULL DEFAULT 0,
net_after_schema_token_delta INTEGER NOT NULL DEFAULT 0,
schema_adjusted_overhead INTEGER NOT NULL DEFAULT 0,
PRIMARY KEY(day,event_type,action,agent,model,cache_layer,success)
)""",
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_action_created ON events(action, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_error ON events(error_fingerprint, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_model ON events(model, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_process_sessions_started ON process_sessions(started_at)",
            "CREATE INDEX IF NOT EXISTS idx_errors_fp_created ON errors(fingerprint, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_snapshots_name_created ON snapshots(name, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_savings_created ON events(event_type, savings_source, created_at)",
        ),
    ),
}

# These stores removed only the retired tenancy columns; no additional
# credential/principal columns were removed from their current schemas.
ADDITIONAL_RETIRED_COLUMNS = {}

# Only these JSON containers receive semantic preflight. Trace request,
# response, event, and captured payload columns are deliberately opaque.
ADDITIONAL_JSON_CONTAINERS = {
    "async_jobs": {
        ("async_jobs", "payload_json"): "runtime recursively rejects exact retired tenancy keys in JSON object keys; nested unknown contracts require manual review",
        ("async_jobs", "result_json"): "runtime recursively rejects exact retired tenancy keys in JSON object keys; preserve opaque string values; nested unknown contracts require manual review",
    },
    "telemetry": {
        ("snapshots", "metrics_json"): "runtime checks structured snapshot metadata only; bounded parse up to 250000 records, 1048576 chars each, depth 16, 4096 inspected dict keys; nested or conflicting semantics require manual review",
    },
}
