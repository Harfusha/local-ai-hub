//! Native schema-aware presentation of operational records. Missing data stays unknown.
use serde_json::Value;

pub struct Records<'a> {
    pub columns: &'static [&'static str],
    pub values: Vec<&'a Value>,
}

pub fn records<'a>(view: &str, response: &'a Value) -> Option<Records<'a>> {
    let (paths, columns): (&[&str], &[&str]) = match view {
        "Requests" => (&["/observability/recent_http"], &["request_id", "project", "agent", "action", "status_code", "duration_ms", "error_type"]),
        "Trace index" => (&["/items"], &["trace_id", "request_id", "action", "agent", "kind", "status", "updated_at"]),
        "Tasks" => (&["/tasks", "/items"], &["task_id", "goal", "status", "updated_at", "root"]),
        "Memory" => (&["/records", "/memory", "/items"], &["key", "scope", "kind", "confidence", "updated_at"]),
        "Incidents" => (&["/incidents", "/items"], &["incident_id", "operation_class", "redacted_message", "status", "created_at"]),
        "Projects" => (&["/projects", "/preprocessing/projects"], &["root", "project", "phase", "phase_progress_pct", "active_detail", "waiting_reason"]),
        "Plans" => (&["/plans", "/items"], &["id", "title", "lifecycle", "file_revision"]),
        "Worktrees" => (&["/worktrees", "/items"], &["path", "branch", "head", "status"]),
        "Model inventory" => (&["/data"], &["id", "owned_by", "object"]),
        "Activity" => (&["/events", "/items"], &["seq", "kind", "agent", "action", "success", "duration_ms"]),
        _ => return None,
    };
    let values = paths.iter().find_map(|p| response.pointer(p).and_then(Value::as_array))?;
    Some(Records { columns, values: values.iter().take(12_000).collect() })
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
            if !result.iter().any(|(key, _)| key == state) {
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
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
    fn unavailable_fields_are_not_zero() {
        assert_eq!(display(&Value::Null), "Unavailable");
        assert_eq!(display(&json!(false)), "false");
    }
}
