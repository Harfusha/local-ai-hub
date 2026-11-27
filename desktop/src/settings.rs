//! Typed operator settings draft. Only observed server fields are editable;
//! missing values never silently acquire defaults or overwrite configuration.
use eframe::egui;
use serde_json::{Map, Value};

const PROFILES: &[&str] = &["auto", "cpu", "integrated", "low", "balanced", "medium", "high", "max"];
const FLAGS: &[(&str, &str)] = &[
    ("preprocessing.enabled", "Preprocessing enabled"),
    ("code_intelligence.enabled", "Code intelligence enabled"),
    ("code_intelligence.serena_enabled", "Serena integration"),
    ("features.status", "Status tools"),
    ("features.repo", "Repository tools"),
    ("features.tasks", "Task tools"),
    ("features.rag", "RAG"),
    ("features.commands", "Command broker"),
    ("features.coord", "Coordination"),
    ("features.artifacts", "Artifacts"),
    ("features.code_intelligence", "Code intelligence feature"),
    ("features.preprocessing", "Preprocessing feature"),
    ("features.subagents", "Subagents"),
    ("features.agent_os", "Agent OS"),
    ("features.work_orchestrator", "Work orchestrator"),
];

#[derive(Default)]
pub struct Draft {
    original: Map<String, Value>,
    edited: Map<String, Value>,
}

impl Draft {
    pub fn from_response(response: &Value) -> Self {
        let mut original = Map::new();
        if response["success"] != true { return Self::default(); }
        let config = &response["config"];
        if let Some(profile) = config.pointer("/hardware/profile").and_then(Value::as_str).filter(|p| PROFILES.contains(p)) {
            original.insert("hardware.profile".into(), Value::String(profile.into()));
        }
        for (key, _) in FLAGS {
            let pointer = format!("/{}", key.replace('.', "/"));
            if let Some(value) = config.pointer(&pointer).and_then(Value::as_bool) {
                original.insert((*key).into(), Value::Bool(value));
            }
        }
        Self { edited: original.clone(), original }
    }

    pub fn patch(&self) -> Map<String, Value> {
        self.edited.iter().filter(|(key, value)| self.original.get(*key) != Some(*value))
            .map(|(key, value)| (key.clone(), value.clone())).collect()
    }

    pub fn render(&mut self, ui: &mut egui::Ui) -> bool {
        if self.original.is_empty() {
            ui.label("Load configuration first. Unknown values cannot be edited.");
            return false;
        }
        ui.small("Edit loaded settings. Saving writes only changed overrides; server validates the batch. Telemetry changes use separate live controls.");
        if let Some(Value::String(profile)) = self.edited.get_mut("hardware.profile") {
            ui.horizontal(|ui| {
                ui.label("Hardware profile");
                egui::ComboBox::from_id_salt("draft_profile").selected_text(profile.as_str()).show_ui(ui, |ui| {
                    for candidate in PROFILES { ui.selectable_value(profile, (*candidate).into(), *candidate); }
                });
            });
        } else { ui.label("Hardware profile: unavailable"); }
        egui::CollapsingHeader::new("Feature switches").default_open(true).show(ui, |ui| {
            egui::Grid::new("draft_flags").num_columns(2).show(ui, |ui| {
                for (index, (key, label)) in FLAGS.iter().enumerate() {
                    if let Some(Value::Bool(value)) = self.edited.get_mut(*key) { ui.checkbox(value, *label); }
                    else { ui.label(format!("{label}: unavailable")); }
                    if index % 2 == 1 { ui.end_row(); }
                }
            });
        });
        let count = self.patch().len();
        let mut save = false;
        ui.horizontal(|ui| {
            ui.label(format!("{count} changed fields"));
            if ui.add_enabled(count > 0, egui::Button::new("Discard edits")).clicked() { self.edited = self.original.clone(); }
            save = ui.add_enabled(count > 0, egui::Button::new("Review and save overrides")).clicked();
        });
        save
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn only_changed_observed_fields_are_written() {
        let mut draft = Draft::from_response(&json!({"success":true,"config":{"features":{"tasks":true,"dashboard":true},"hardware":{"profile":"cpu"}}}));
        assert!(draft.patch().is_empty());
        assert!(!draft.edited.contains_key("features.rag"));
        assert!(!draft.edited.contains_key("features.dashboard"));
        draft.edited.insert("features.tasks".into(), json!(false));
        assert_eq!(draft.patch(), json!({"features.tasks":false}).as_object().unwrap().clone());
    }
}
