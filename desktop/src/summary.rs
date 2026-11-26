//! Native operator summary. Do not convert unknown or stale observations to zero.
use eframe::egui;
use serde_json::Value;

pub fn health(snapshot: &Value) -> (&'static str, Vec<String>) {
    let current = snapshot.get("current").or_else(|| snapshot.get("headless")).unwrap_or(snapshot);
    let state = ["health", "status", "service_status", "state"].iter()
        .find_map(|key| current.get(*key).and_then(Value::as_str)).unwrap_or("").to_lowercase();
    let online = snapshot.get("hub_online").or_else(|| current.get("hub_online")).and_then(Value::as_bool);
    if online == Some(false) || matches!(state.as_str(), "down" | "offline" | "unavailable" | "crashed" | "stopped") {
        return ("Offline", vec!["Server reports unavailable".into()]);
    }
    if snapshot["snapshot_stale"].as_bool() == Some(true) || current["heartbeat_stale"].as_bool() == Some(true)
        || snapshot["snapshot_warming"].as_bool() == Some(true) {
        return ("Unverified", vec!["Status is stale or warming; current health is unknown".into()]);
    }
    let mut notes = Vec::new();
    if let Some(deps) = snapshot["dependency_status"].as_object() {
        for (name, dependency) in deps {
            if dependency["degraded"].as_bool() == Some(true) {
                notes.push(format!("{name}: {}", dependency["reason"].as_str().unwrap_or("degraded")));
            }
        }
    }
    if snapshot["ollama_online"].as_bool().or_else(|| current["ollama_online"].as_bool()) == Some(false) {
        notes.push("Model runtime offline".into());
    }
    if !notes.is_empty() || matches!(state.as_str(), "degraded" | "error" | "attention") {
        return ("Attention", notes);
    }
    if online == Some(true) || matches!(state.as_str(), "running" | "healthy" | "ok" | "online") {
        return ("Live", vec!["Process liveness reported; this does not prove all subsystems healthy".into()]);
    }
    ("Unverified", vec!["No current liveness evidence".into()])
}

pub fn count(value: Option<&Value>) -> Option<u64> {
    value.and_then(Value::as_u64)
}

pub fn project_progress(project: &Value) -> Option<f32> {
    project["overall_progress_pct"].as_f64().filter(|x| x.is_finite())
        .map(|x| x.clamp(0.0, 100.0) as f32 / 100.0)
}

pub fn resident_inventory(snapshot: &Value) -> &'static str {
    if snapshot["snapshot_stale"].as_bool() == Some(true) || snapshot["loaded_model_inventory_stale"].as_bool() == Some(true) {
        return "Stale";
    }
    if snapshot["loaded_models_available"].as_bool() == Some(false) || snapshot["model_inventory_available"].as_bool() == Some(false) {
        return "Unknown";
    }
    let details = snapshot.get("loaded_model_details");
    let names = snapshot.get("loaded_models");
    if details.is_some_and(|v| !v.is_array()) || names.is_some_and(|v| !v.is_array()) {
        return "Unknown";
    }
    let details = details.and_then(Value::as_array);
    let names = names.and_then(Value::as_array);
    if details.is_some_and(|a| a.iter().any(|x| x["name"].as_str().is_none_or(str::is_empty)))
        || names.is_some_and(|a| a.iter().any(|x| x.as_str().is_none_or(str::is_empty))) {
        return "Unknown";
    }
    if details.is_some_and(|a| !a.is_empty()) || names.is_some_and(|a| !a.is_empty()) { "Loaded" }
    else if details.is_some() || names.is_some() { "None loaded" }
    else { "Unknown" }
}

fn recent_durations(snapshot: &Value) -> Vec<f64> {
    snapshot.pointer("/observability/recent_http").and_then(Value::as_array)
        .map(|rows| rows.iter().take(200).filter_map(|row| row["duration_ms"].as_f64())
            .filter(|ms| ms.is_finite() && *ms >= 0.0).collect()).unwrap_or_default()
}

pub fn render(ui: &mut egui::Ui, view: &str, snapshot: &Value) {
    if matches!(view, "Overview" | "Runtime health") {
        let (label, notes) = health(snapshot);
        ui.group(|ui| {
            ui.heading(format!("Hub health: {label}"));
            for note in notes { ui.label(note); }
            let active = snapshot.pointer("/observability/active_requests").and_then(Value::as_array).map(Vec::len);
            ui.label(format!("Active API requests: {}", active.map(|n| n.to_string()).unwrap_or("Unavailable".into())));
        });
        ui.collapsing("Recent request durations (ms)", |ui| {
            let samples = recent_durations(snapshot);
            if samples.is_empty() { ui.label("No recorded duration samples in this response"); return; }
            let max = samples.iter().copied().fold(0.0, f64::max).max(1.0);
            ui.label(format!("{} recorded samples · max {:.2} ms · server response window", samples.len(), max));
            let (rect, _) = ui.allocate_exact_size(egui::vec2(ui.available_width().max(100.0), 85.0), egui::Sense::hover());
            let width = rect.width() / samples.len() as f32;
            let color = ui.visuals().selection.bg_fill;
            for (index, duration) in samples.iter().enumerate() {
                let height = (duration / max) as f32 * rect.height();
                let x = rect.left() + index as f32 * width;
                ui.painter().rect_filled(egui::Rect::from_min_max(
                    egui::pos2(x, rect.bottom() - height), egui::pos2(x + width * 0.8, rect.bottom())), 0.0, color);
            }
        });
    }
    if view == "Resident inventory" {
        ui.heading(format!("Resident model inventory: {}", resident_inventory(snapshot)));
    }
    if view == "Projects" {
        if let Some(projects) = snapshot.get("projects").and_then(Value::as_array) {
            ui.collapsing("Preprocessing progress (server estimate)", |ui| {
                for project in projects.iter().take(100) {
                    ui.label(project["root"].as_str().unwrap_or("Unknown project"));
                    if let Some(progress) = project_progress(project) {
                        ui.add(egui::ProgressBar::new(progress).show_percentage());
                    } else {
                        ui.label("Overall estimate unavailable");
                    }
                    let total = if project["phase"].as_str() == Some("inventory") { None } else { count(project.get("files")) };
                    for (label, key) in [("Hashed", "hashed_files"), ("Code index", "code_index_files"), ("RAG", "rag_files")] {
                        let done = count(project.get(key));
                        let text = match (done, total) {
                            (Some(done), Some(total)) => format!("{done} / {total} files"),
                            (Some(done), None) => format!("{done} files · total pending"),
                            _ => "Unavailable".into(),
                        };
                        ui.small(format!("{label}: {text}"));
                    }
                }
                if projects.len() > 100 { ui.label("Progress preview limited to 100 projects"); }
            });
        }
    }
    if view == "Agent event stream" {
        if let Some(controls) = snapshot["controls"].as_array() {
            for control in controls.iter().filter(|c| matches!(c["kind"].as_str(), Some("retention_gap" | "stream.gap" | "cursor_reset" | "replay_cursor_reset" | "replay_limit"))) {
                ui.colored_label(ui.visuals().warn_fg_color, format!("Stream continuity: {}", control));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn stale_and_missing_health_are_not_healthy() {
        assert_eq!(health(&json!({})).0, "Unverified");
        assert_eq!(health(&json!({"hub_online":true,"snapshot_stale":true})).0, "Unverified");
        assert_eq!(health(&json!({"hub_online":true,"dependency_status":{"scheduler":{"degraded":true}}})).0, "Attention");
    }
    #[test]
    fn measured_zero_is_distinct_from_missing() {
        assert_eq!(project_progress(&json!({})), None);
        assert_eq!(project_progress(&json!({"overall_progress_pct":0})), Some(0.0));
        assert_eq!(count(Some(&json!(0))), Some(0));
        assert_eq!(count(None), None);
    }
    #[test]
    fn inventory_does_not_invent_empty_or_loaded() {
        assert_eq!(resident_inventory(&json!({})), "Unknown");
        assert_eq!(resident_inventory(&json!({"loaded_models":[]})), "None loaded");
        assert_eq!(resident_inventory(&json!({"loaded_models":["model"],"snapshot_stale":true})), "Stale");
    }
    #[test]
    fn chart_excludes_missing_and_invalid_samples() {
        assert_eq!(recent_durations(&json!({"observability":{"recent_http":[{"duration_ms":0.25},{},{"duration_ms":-1},{"duration_ms":"unknown"}]}})), vec![0.25]);
    }
}
