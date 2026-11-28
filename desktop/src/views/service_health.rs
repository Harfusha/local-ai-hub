use super::super::*;

impl Desktop {
    pub(super) fn service_health(&mut self, ui: &mut egui::Ui, _ctx: &egui::Context) {
        ui.horizontal_wrapped(|ui| {
            for action in MAINTENANCE {
                if ui.button(*action).clicked() {
                    self.confirm(
                        action,
                        request("maintenance", json!({"action": action, "confirmed": true})),
                    );
                }
            }
        });
    }
}
