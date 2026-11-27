//! Native, read-only view of the canonical Hub verification projection.
use eframe::egui;
use serde_json::Value;

fn count(value: &Value, key: &str) -> Option<u64> {
    value.get(key)?.as_u64()
}

fn progress(value: &Value) -> Option<(u64, u64)> {
    let total = count(value, "total")?;
    let verified = count(value, "verified")?;
    if total == 0 || verified > total { return None; }
    Some((verified, total))
}

fn label(value: &Value, key: &str) -> String {
    value.get(key).and_then(Value::as_str).unwrap_or("unknown").to_owned()
}

pub fn render(ui: &mut egui::Ui, snapshot: &Value) {
    let completion = &snapshot["completion"];
    let execution = &completion["execution"];
    if snapshot["success"].as_bool() != Some(true) || !execution.is_object() {
        ui.label("Verification status unavailable.");
        return;
    }
    ui.heading("Verified execution");
    ui.label(format!("Profile: {}", label(execution, "profile")));
    let ready = completion["complete"].as_bool() == Some(true)
        && execution["ready_for_completion_attempt"].as_bool() == Some(true);
    ui.label(if ready { "Ready for completion attempt — not a completed task." }
        else { "Incomplete or blocked." });
    let coverage = &execution["coverage"];
    if let Some((verified, total)) = progress(coverage) {
        ui.label(format!("{verified}/{total} verified obligations"));
        ui.add(egui::ProgressBar::new(verified as f32 / total as f32).show_percentage());
    } else { ui.label("Coverage unavailable."); }
    for key in ["unverified", "stale", "dependency_blocked"] {
        if let Some(n) = count(coverage, key) { ui.label(format!("{key}: {n}")); }
    }
    ui.label(format!("Checkpoint blockers: {}", count(execution, "checkpoint_blocker_count")
        .map(|n| n.to_string()).unwrap_or_else(|| "unknown".into())));
    if let Some(scope) = execution.get("scope_check") {
        ui.label(format!("Scope: {}", label(scope, "status")));
    }
    if let Some(dimensions) = execution["dimensions"].as_object() {
        ui.heading("Coverage by dimension");
        for (name, counts) in dimensions.iter().take(512) {
            if let Some((verified, total)) = progress(counts) {
                ui.label(format!("{name}: {verified}/{total}"));
            } else { ui.label(format!("{name}: unavailable")); }
        }
    }
    if execution["next_obligation"].is_object() {
        ui.heading("Next obligation");
        ui.label(label(&execution["next_obligation"], "criterion"));
    }
    if let Some(remaining) = execution["remaining_preview"].as_array() {
        ui.heading("Remaining obligations (bounded preview)");
        for row in remaining.iter().take(12) {
            ui.label(format!("{} — {}", label(row, "status"), label(row, "criterion")));
            if let Some(waiting) = row["waiting_on"].as_array() {
                for dependency in waiting.iter().filter_map(Value::as_str).take(12) {
                    ui.small(format!("Depends on: {dependency}"));
                }
            }
        }
        if execution["preview_truncated"].as_bool() == Some(true) {
            ui.label("Additional obligations exist. Inspect the full task contract.");
        }
    }
    let problems = &execution["problems"];
    ui.heading("Problem reports");
    ui.label(format!("Open: {} · blocking: {} · resolved: {}",
        count(problems, "open").map_or("unknown".into(), |n| n.to_string()),
        count(problems, "blocking_open").map_or("unknown".into(), |n| n.to_string()),
        count(problems, "resolved").map_or("unknown".into(), |n| n.to_string())));
    if let Some(reports) = problems["open_preview"].as_array() {
        for report in reports.iter().take(12) {
            ui.label(format!("{}: {}", label(report, "id"), label(report, "title")));
            if report["blocking"].as_bool() == Some(true) { ui.small("Blocking"); }
        }
    }
    if problems["preview_truncated"].as_bool() == Some(true) { ui.label("Additional reports exist."); }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn coverage_requires_valid_denominator() {
        assert_eq!(progress(&json!({"total": 4, "verified": 3})), Some((3,4)));
        for value in [json!({}), json!({"total": 0, "verified": 0}), json!({"total": 2, "verified": 3})] {
            assert_eq!(progress(&value), None);
        }
    }
}
