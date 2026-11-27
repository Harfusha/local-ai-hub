//! Native schema-aware presentation of operational records. Missing data stays unknown.
use serde_json::Value;

pub struct Records<'a> {
    pub columns: &'static [&'static str],
    pub values: Vec<&'a Value>,
}

pub fn records<'a>(view: &str, response: &'a Value) -> Option<Records<'a>> {
    if view == "Semaphores" {
        let semaphores = response.get("semaphores")?.as_object()?;
        return Some(Records {
            columns: &["name", "capacity", "active_count", "queue_length", "updated_at"],
            values: semaphores.values().take(12_000).collect(),
        });
    }
    let (paths, columns): (&[&str], &[&str]) = match view {
        "Requests" => (&["/observability/recent_http"], &["request_id", "project", "agent", "action", "status_code", "duration_ms", "error_type"]),
        "Telemetry history" => (&["/timeline"], &["id", "timestamp", "event_type", "agent", "action", "duration_ms", "success", "route", "stage", "error_type"]),
        "Diagnostics" => (&["/checks"], &["component", "status", "detail"]),
        "Active requests" => (&["/observability/active_requests"], &["request_id", "agent", "action", "project", "duration_ms", "state"]),
        "Scheduler queue" => (&["/scheduler/pending_jobs"], &["job_id", "state", "model", "source", "agent", "wait_ms", "wait_reason"]),
        "Scheduler running" => (&["/scheduler/inflight_jobs"], &["job_id", "state", "model", "source", "agent", "wait_ms", "service_ms"]),
        "Recovery journal" => (&["/recovery/recent"], &["request_id", "action", "state", "updated_at", "detail"]),
        "Async jobs" => (&["/async_jobs/recent", "/async_jobs/jobs", "/async_jobs/items"], &["job_id", "action", "state", "created_at", "updated_at", "error"]),
        "Work orders" => (&["/work_orchestrator/recent", "/work_orchestrator/orders", "/work_orchestrator/items"], &["work_id", "goal", "state", "updated_at", "error"]),
        "Trace index" => (&["/items"], &["trace_id", "request_id", "action", "agent", "kind", "status", "duration_ms", "updated_at"]),
        "Commands" => (&["/runtime_stats/commands/active"], &["command", "cwd", "class", "age_ms", "timeout_seconds"]),
        "Process sessions" => (&["/observability/sessions"], &["session_id", "pid", "status", "started_at", "duration_seconds", "events", "cache_hit_rate", "version"]),
        "Recent errors" => (&["/observability/recent_errors"], &["component", "operation", "safe_message", "count", "recovered_count", "last_seen"]),
        "Run history" => (&["/tasks", "/items"], &["task_id", "goal", "status", "owner", "tokens_used", "updated_at"]),
        "Tasks" => (&["/tasks", "/items"], &["task_id", "goal", "status", "updated_at", "root"]),
        "Memory" => (&["/records", "/memory", "/items"], &["key", "scope", "kind", "confidence", "provenance", "created_at", "updated_at"]),
        "Search workspaces" => (&["/workspaces"], &["root", "path", "workspace", "status", "documents", "chunks"]),
        "Endpoint analytics" => (&["/items"], &["name", "type", "calls", "success_rate", "p50_ms", "p95_ms", "p99_ms", "status"]),
        "Incidents" => (&["/incidents", "/items"], &["incident_id", "operation_class", "redacted_message", "status", "created_at"]),
        "Projects" => (&["/projects", "/preprocessing/projects"], &["root", "project", "phase", "phase_progress_pct", "active_detail", "waiting_reason"]),
        "Plans" => (&["/plans", "/items"], &["id", "title", "lifecycle", "file_revision"]),
        "Worktrees" => (&["/worktrees", "/items"], &["path", "branch", "head", "status"]),
        "File leases" => (&["/leases"], &["lease_id", "owner", "paths", "purpose", "expires_at"]),
        "Session briefing" => (&["/active_tasks"], &["task_id", "goal", "status", "owner"]),
        "Model inventory" => (&["/data"], &["id", "owned_by", "object"]),
        "Activity" | "Agent event stream" => (&["/events", "/items"], &["seq", "kind", "agent", "action", "success", "duration_ms"]),
        _ => return None,
    };
    let values = paths.iter().find_map(|p| response.pointer(p).and_then(Value::as_array))?;
    Some(Records { columns, values: values.iter().take(12_000).collect() })
}

pub fn selection_id<'a>(view: &str, item: &'a Value) -> Option<&'a str> {
    let key = match view {
        "Trace index" => "trace_id",
        "Tasks" | "Run history" => "task_id",
        "Async jobs" | "Scheduler queue" | "Scheduler running" => "job_id",
        "Work orders" => "work_id",
        "Plans" => "id",
        "File leases" => "lease_id",
        "Worktrees" => "path",
        _ => return None,
    };
    item.get(key)?.as_str().filter(|id| !id.trim().is_empty())
}

pub fn field<'a>(item: &'a Value, name: &str) -> &'a Value {
    item.get(name).filter(|v| !v.is_null()).or_else(|| match name {
        "goal" => item.pointer("/contract/goal"),
        "tokens_used" => item.pointer("/checkpoint/state_data/tokens_used"),
        "status" => item.get("state"),
        _ => None,
    }).unwrap_or(&Value::Null)
}

pub fn request_matches(item: &Value, status: &str, action: &str) -> bool {
    if !action.is_empty() && item["action"].as_str() != Some(action) { return false; }
    let code = item["status_code"].as_u64();
    match status {
        "failed" => item["success"].as_bool() == Some(false) || code.is_some_and(|n| n >= 400),
        "2xx" => code.is_some_and(|n| (200..300).contains(&n)),
        "4xx" => code.is_some_and(|n| (400..500).contains(&n)),
        "5xx" => code.is_some_and(|n| (500..600).contains(&n)),
        _ => true,
    }
}

pub fn endpoint_matches(item: &Value, scope: &str) -> bool {
    match scope {
        "active" => item["calls"].as_u64().is_some_and(|n| n > 0),
        "unused" => item["calls"].as_u64() == Some(0),
        _ => true,
    }
}

pub fn sort_records(values: &mut [&Value], key: &str, descending: bool) {
    use std::cmp::Ordering;
    values.sort_by(|a, b| {
        let a = field(a, key);
        let b = field(b, key);
        match (a.is_null(), b.is_null()) {
            (true, true) => Ordering::Equal,
            (true, false) => Ordering::Greater,
            (false, true) => Ordering::Less,
            _ => {
                let order = match (a.as_f64(), b.as_f64()) {
                    (Some(a), Some(b)) => a.total_cmp(&b),
                    _ => display(a).to_lowercase().cmp(&display(b).to_lowercase()),
                };
                if descending { order.reverse() } else { order }
            }
        }
    });
}

pub fn display(value: &Value) -> String {
    match value {
        Value::Null => "Unavailable".into(),
        Value::String(s) => s.clone(),
        _ => value.to_string(),
    }
}

pub fn board_columns(response: &Value) -> Option<Vec<(&str, &[Value])>> {
    let columns = response.get("columns")?.as_object()?;
    let mut result = Vec::new();
    for state in ["planned", "ready", "in_progress", "blocked", "source_ready", "done"] {
        if let Some(items) = columns.get(state) {
            result.push((state, items.as_array()?.as_slice()));
        }
    }
    if result.len() != columns.len() {
        for (state, items) in columns {
            if !result.iter().any(|(key, _)| *key == state.as_str()) {
                result.push((state.as_str(), items.as_array()?.as_slice()));
            }
        }
    }
    Some(result)
}

pub fn progress(response: &Value) -> Option<(usize, usize, usize)> {
    let columns = board_columns(response)?;
    let total = columns.iter().map(|(_, cards)| cards.len()).sum();
    let declared = columns.iter().filter(|(state, _)| *state == "done").map(|(_, cards)| cards.len()).sum();
    let verified = columns.iter().filter(|(state, _)| *state == "done")
        .flat_map(|(_, cards)| cards.iter()).filter(|card| card["verified"].as_bool() == Some(true)).count();
    Some((total, declared, verified))
}

pub fn merge_events(buffer: &mut Vec<Value>, incoming: &[Value], limit: usize) {
    use std::collections::BTreeSet;
    let mut ids: BTreeSet<i64> = buffer.iter().filter_map(|v| v["seq"].as_i64()).collect();
    for event in incoming {
        if let Some(id) = event["seq"].as_i64() {
            if ids.insert(id) { buffer.push(event.clone()); }
        }
    }
    buffer.sort_by_key(|v| v["seq"].as_i64().unwrap_or_default());
    if buffer.len() > limit { buffer.drain(..buffer.len() - limit); }
    let mut bytes = 0usize;
    let retained = buffer.iter().rev().take_while(|event| {
        bytes = bytes.saturating_add(event.to_string().len()); bytes <= 8_000_000
    }).count();
    if retained < buffer.len() { buffer.drain(..buffer.len() - retained); }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn selection_uses_view_specific_identity_not_trace_or_request_aliases() {
        let item = json!({"trace_id":"trace_a","task_id":"task_a","job_id":"job_a","lease_id":"lease_a"});
        assert_eq!(selection_id("Tasks", &item), Some("task_a"));
        assert_eq!(selection_id("Trace index", &item), Some("trace_a"));
        assert_eq!(selection_id("Async jobs", &item), Some("job_a"));
        assert_eq!(selection_id("File leases", &item), Some("lease_a"));
        assert_eq!(selection_id("Work orders", &item), None);
        assert_eq!(selection_id("Memory", &item), None);
    }
    #[test]
    fn semaphore_and_lease_tables_use_canonical_shapes() {
        let response = json!({"semaphores":{"gpu":{"name":"gpu","capacity":1}}});
        assert_eq!(records("Semaphores", &response).unwrap().values.len(), 1);
        assert!(records("Semaphores", &json!({})).is_none());
        let leases = json!({"leases":[{"lease_id":"lease_a","owner":"writer"}]});
        assert_eq!(records("File leases", &leases).unwrap().values[0]["owner"], "writer");
    }
    #[test]
    fn missing_is_not_empty() {
        assert!(records("Requests", &json!({})).is_none());
        assert!(records("Requests", &json!({"observability":{"recent_http":[]}})).unwrap().values.is_empty());
    }
    #[test]
    fn verified_completion_is_not_declared_completion() {
        let board = json!({"columns":{"done":[{"verified":true},{"verified":false},{}],"blocked":[{}]}});
        assert_eq!(progress(&board), Some((4, 3, 1)));
    }
    #[test]
    fn live_event_buffer_deduplicates_and_caps() {
        let mut buffer = vec![json!({"seq": 1}), json!({"seq": 2})];
        merge_events(&mut buffer, &[json!({"seq": 2}), json!({"seq": 3}), json!({"seq": 4})], 3);
        assert_eq!(buffer, vec![json!({"seq": 2}), json!({"seq": 3}), json!({"seq": 4})]);
    }
    #[test]
    fn memory_provenance_is_not_discarded() {
        let response = json!({"records":[{"key":"fact","provenance":{"root":"/project","repository":"repo"},"created_at":123}]});
        let table = records("Memory", &response).unwrap();
        assert!(table.columns.contains(&"provenance"));
        assert_eq!(table.values[0]["provenance"]["root"], "/project");
    }
    #[test]
    fn workspace_inventory_is_read_only_and_missing_is_unknown() {
        assert!(records("Search workspaces", &json!({})).is_none());
        let response = json!({"workspaces":[{"root":"/project","status":"unknown"}]});
        let table = records("Search workspaces", &response).unwrap();
        assert_eq!(table.values[0]["status"], "unknown");
    }
    #[test]
    fn unavailable_fields_are_not_zero() {
        assert_eq!(display(&Value::Null), "Unavailable");
        assert_eq!(display(&json!(false)), "false");
    }
}

#[cfg(test)]
mod endpoint_filter_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn unknown_counts_are_neither_active_nor_unused() {
        assert!(!endpoint_matches(&json!({}), "active"));
        assert!(!endpoint_matches(&json!({}), "unused"));
        assert!(endpoint_matches(&json!({"calls": 0}), "unused"));
    }

    #[test]
    fn missing_metric_sorts_after_measured_zero_in_both_directions() {
        let a = json!({"calls": 0});
        let b = json!({});
        let c = json!({"calls": 2});
        let mut rows = vec![&b, &a, &c];
        sort_records(&mut rows, "calls", true);
        assert_eq!(rows, vec![&c, &a, &b]);
        sort_records(&mut rows, "calls", false);
        assert_eq!(rows, vec![&a, &c, &b]);
    }
}

#[cfg(test)]
mod request_filter_tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn request_filters_preserve_unknown_status_and_exact_action() {
        assert!(!request_matches(&json!({"action":"read"}), "2xx", ""));
        assert!(request_matches(&json!({"action":"read","status_code":503}), "failed", "read"));
        assert!(!request_matches(&json!({"action":"read","status_code":503}), "failed", "re"));
        assert!(request_matches(&json!({"success":false}), "failed", ""));
    }
}
