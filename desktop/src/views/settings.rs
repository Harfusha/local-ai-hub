use super::super::*;

impl Desktop {
    pub(super) fn settings(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.current() == "Operator tools" {
            self.operator_tools(ui, ctx);
            return;
        }
        if self.current() == "Instruction compression" {
            ui.small("Stage generates a local candidate and semantic review without replacing source files. Inspect the exact manifest before apply or restore; the reviewed digest must match.");
            if ui
                .add_enabled(
                    !self.repo.trim().is_empty(),
                    egui::Button::new("Stage compressed instructions"),
                )
                .clicked()
            {
                self.confirm("Stage compressed instructions", request("operator_run",
                    json!({"name":"Stage compressed instructions","root":self.repo,"fields":{},"confirmed":true})));
            }
            if ui.button("Choose staged manifest…").clicked() {
                if let Some(path) = rfd::FileDialog::new()
                    .add_filter("Instruction manifest", &["json"])
                    .set_file_name("manifest.json")
                    .pick_file()
                {
                    if path.file_name().and_then(|name| name.to_str()) == Some("manifest.json") {
                        self.entity = path.to_string_lossy().into_owned();
                        self.revision.clear();
                        self.clear_response();
                    } else {
                        self.status =
                            "Select manifest.json from an instruction staging folder.".into();
                    }
                }
            }
            ui.label(if self.entity.is_empty() {
                "No staged manifest selected."
            } else {
                &self.entity
            });
            if ui
                .add_enabled(
                    !self.repo.trim().is_empty() && !self.entity.trim().is_empty(),
                    egui::Button::new("Review staged bytes"),
                )
                .clicked()
            {
                self.refresh(ctx);
            }
            let status = self
                .snapshot
                .as_ref()
                .filter(|_| self.snapshot_view == "Instruction review")
                .filter(|data| {
                    data["manifest_sha256"].as_str() == Some(self.revision.as_str())
                        && data["manifest"].as_str() == Some(self.entity.as_str())
                })
                .and_then(|data| data["status"].as_str())
                .unwrap_or("");
            let staged = status == "staged";
            let applied = status == "applied";
            ui.horizontal_wrapped(|ui| {
                for (title, action, allowed) in [
                    ("Apply reviewed instructions", "apply", staged),
                    ("Restore original instructions", "restore", applied),
                ] {
                    if ui.add_enabled(allowed && !self.revision.is_empty(), egui::Button::new(title)).clicked() {
                        self.confirm(title, request("instruction_manifest", json!({
                            "root":self.repo, "manifest":self.entity, "manifest_sha256":self.revision,
                            "action":action,"confirmed":true})));
                    }
                }
            });
            return;
        }
        if self.current() == "Updates" {
            ui.small("Managed installations only. The Hub checks the exact release candidate again before scheduling the update and restart.");
            if ui.button("Check for updates").clicked() {
                self.confirm(
                    "Updates",
                    request("update_check", json!({"confirmed": true})),
                );
            }
            ui.label(format!(
                "Candidate: {} / {}",
                self.update_version, self.update_revision
            ));
            if ui
                .add_enabled(
                    !self.update_version.is_empty() && self.update_revision.len() == 40,
                    egui::Button::new("Install reviewed candidate"),
                )
                .clicked()
            {
                self.confirm("Install reviewed release and restart Hub", request("update_install", json!({
                    "version": self.update_version, "revision": self.update_revision, "confirmed": true})));
            }
            return;
        }
        if self.current() == "Settings" {
            if self.settings_draft.render(ui) {
                let patch = self.settings_draft.patch();
                if !patch.is_empty() {
                    self.confirm(
                        "Save settings",
                        request(
                            "settings_batch",
                            json!({"settings": patch, "confirmed": true}),
                        ),
                    );
                }
            }
            ui.horizontal_wrapped(|ui| {
                for (title, mode) in [
                    ("Telemetry off", "off"),
                    ("Minimal telemetry", "minimal"),
                    ("Detailed telemetry", "full"),
                ] {
                    if ui.button(title).clicked() {
                        self.confirm(
                            &format!("{title} (may retain sensitive request content)"),
                            request("telemetry", json!({"mode": mode, "confirmed": true})),
                        );
                    }
                }
                if ui.button("Reset configuration overrides").clicked() {
                    self.confirm(
                        "Reset configuration overrides",
                        request("config_reset", json!({"confirmed": true})),
                    );
                }
            });
        } else {
            ui.small("Change activity mode from the top toolbar.");
        }
    }
}
