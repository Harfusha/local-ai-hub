use super::super::*;

impl Desktop {
    pub(super) fn projects(&mut self, ui: &mut egui::Ui, _ctx: &egui::Context) {
        ui.horizontal_wrapped(|ui| {
            for (title, action) in [
                ("Register", "register"),
                ("Reindex", "refresh"),
                ("Pause", "pause"),
                ("Resume", "resume"),
                ("Unregister (keep data)", "unregister"),
            ] {
                if ui.button(title).clicked() {
                    self.confirm(
                        title,
                        request(
                            "project",
                            json!({"root": self.repo,
                        "action": action, "confirmed": true}),
                        ),
                    );
                }
            }
        });
        if ui.button("Unregister and purge project data").clicked() {
            self.confirm("Unregister and permanently purge selected project data", request("project", json!({"root": self.repo, "action": "unregister", "purge_data": true, "confirmed": true})));
        }
        ui.horizontal_wrapped(|ui| {
            for (title, action) in [
                ("Pause all", "pause"),
                ("Resume all", "resume"),
                ("Cleanup missing", "cleanup_deleted"),
            ] {
                if ui.button(title).clicked() {
                    self.confirm(
                        title,
                        request(
                            "global_preprocess",
                            json!({"action": action, "confirmed": true}),
                        ),
                    );
                }
            }
        });
    }
}
