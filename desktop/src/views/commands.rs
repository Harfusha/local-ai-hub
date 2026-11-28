use super::super::*;

impl Desktop {
    pub(super) fn commands(&mut self, ui: &mut egui::Ui, _ctx: &egui::Context) {
        if self.current() == "Worktrees" {
            self.worktrees(ui);
        }
    }
}
