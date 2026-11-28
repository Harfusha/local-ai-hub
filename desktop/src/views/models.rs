use super::super::*;

impl Desktop {
    pub(super) fn models(&mut self, ui: &mut egui::Ui, _ctx: &egui::Context) {
        if self.current() == "Ollama management" {
            ui.small("Ollama only. Pull downloads a model through the configured backend; it can take several minutes. Delete is restricted to a confirmed non-resident installed model.");
            let label = ui.label("Exact model name (including tag)");
            ui.text_edit_singleline(&mut self.entity)
                .labelled_by(label.id);
            let ready = !self.entity.trim().is_empty();
            let deletable = self
                .snapshot
                .as_ref()
                .filter(|_| self.snapshot_view == "Ollama management")
                .is_some_and(|data| {
                    data["running_status_available"] == true
                        && data["models"].as_array().is_some_and(|rows| {
                            rows.iter()
                                .filter(|row| row["name"].as_str() == Some(self.entity.as_str()))
                                .count()
                                == 1
                                && rows.iter().any(|row| {
                                    row["name"].as_str() == Some(self.entity.as_str())
                                        && row["running"] == false
                                })
                        })
                });
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(ready, egui::Button::new("Pull model"))
                    .clicked()
                {
                    self.confirm(
                        "Download Ollama model",
                        request(
                            "model_manage",
                            json!({"action":"pull", "model":self.entity, "confirmed":true}),
                        ),
                    );
                }
                if ui
                    .add_enabled(deletable, egui::Button::new("Delete installed model"))
                    .clicked()
                {
                    self.confirm(
                        "Delete Ollama model",
                        request(
                            "model_manage",
                            json!({"action":"delete", "model":self.entity, "confirmed":true}),
                        ),
                    );
                }
            });
            if self.snapshot.as_ref().is_some_and(|data| {
                self.snapshot_view == "Ollama management"
                    && data["running_status_available"] != true
            }) {
                ui.small("Resident status unavailable; deletion disabled.");
            }
            return;
        }
        if self.current() != "Benchmark" {
            return;
        }
        ui.label("Compare automatic and high-complexity model routes (runs inference twice)");
        ui.text_edit_multiline(&mut self.prompt);
        if ui.button("Compare models").clicked() {
            self.confirm(
                "Run two model requests",
                request("compare", json!({"prompt": self.prompt, "confirmed": true})),
            );
        }
    }
}
