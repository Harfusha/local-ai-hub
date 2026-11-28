use super::super::*;

impl Desktop {
    pub(super) fn transfers(&mut self, ui: &mut egui::Ui, _ctx: &egui::Context) {
        ui.label("ZIP file path (export requires a new file; import requires repository root)");
        ui.text_edit_singleline(&mut self.archive_path);
        ui.horizontal_wrapped(|ui| {
            for (title, op) in [
                ("Export project", "bundle_export"),
                ("Import project", "bundle_import"),
                ("Export encrypted diagnostics", "diagnostics_export"),
            ] {
                if ui.button(title).clicked() {
                    self.confirm(
                        title,
                        request(
                            op,
                            json!({"file": self.archive_path,
                        "root": self.repo, "confirmed": true}),
                        ),
                    );
                }
            }
        });
    }
}
