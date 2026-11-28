use super::super::*;

impl Desktop {
    pub(super) fn activity(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.current() == "Agent event stream" {
            ui.label("Scoped agent event stream ID (repository root required)");
            if ui.text_edit_singleline(&mut self.stream_id).changed() {
                self.event_cursor = 0;
                self.clear_response();
            }
            ui.horizontal_wrapped(|ui| {
                ui.label("Resume after sequence");
                if ui.add(egui::DragValue::new(&mut self.event_cursor).range(0..=i64::MAX)).changed() { self.auto_live = false; self.live_events.clear(); }
                if ui.button("Read history page").clicked() { self.auto_live = false; self.live_events.clear(); self.refresh(ctx); }
                if ui.button("Collect live SSE (5 seconds)").clicked() {
                    self.submit(ctx, "Agent event stream".into(), request("event_stream",
                        json!({"root": self.repo, "stream": self.stream_id, "after": self.event_cursor})));
                }
            });
            ui.small("Retention gaps and cursor resets are reported in Raw fields. Live follow is opt-in, pauses when hidden or unfocused, and retains at most 500 records.");
        }
    }
}
