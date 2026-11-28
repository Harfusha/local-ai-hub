use super::*;
mod activity;
mod commands;
mod coordination;
mod models;
mod projects;
mod requests;
mod service_health;
mod settings;
mod tasks;
mod transfers;

impl Desktop {
    pub(super) fn operations(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.current() == "Overview" {
            ui.heading("Workload drilldown");
            ui.horizontal_wrapped(|ui| {
                for &(label, target) in OVERVIEW_DRILLDOWNS {
                    if ui.button(label).clicked() {
                        let (page, view) =
                            view_destination(target).expect("native drilldown target exists");
                        self.navigate(page, view);
                        self.refresh(ctx);
                    }
                }
            });
        }
        match self.page {
            1 => self.requests(ui, ctx),
            2 => self.tasks(ui, ctx),
            3 => self.coordination(ui, ctx),
            4 => self.projects(ui, ctx),
            5 => self.commands(ui, ctx),
            6 => self.models(ui, ctx),
            7 => self.service_health(ui, ctx),
            8 => self.settings(ui, ctx),
            9 => self.activity(ui, ctx),
            10 => self.transfers(ui, ctx),
            _ => {}
        }
    }
    fn operator_tools(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        ui.small("Local CLI operations with fixed argument schemas. Offline reads do not start the Hub. Mutations require confirmation.");
        if self.operator_catalog.is_empty() {
            if ui.button("Load operator catalog").clicked() {
                self.refresh(ctx);
            }
            return;
        }
        let previous = self.operator_name.clone();
        egui::ComboBox::from_id_salt("operator_name")
            .selected_text(if self.operator_name.is_empty() {
                "Choose operation"
            } else {
                &self.operator_name
            })
            .show_ui(ui, |ui| {
                for operation in &self.operator_catalog {
                    if let Some(name) = operation["name"].as_str() {
                        ui.selectable_value(&mut self.operator_name, name.to_owned(), name);
                    }
                }
            });
        if previous != self.operator_name {
            self.operator_fields.clear();
        }
        let Some(operation) = self
            .operator_catalog
            .iter()
            .find(|v| v["name"].as_str() == Some(&self.operator_name))
            .cloned()
        else {
            return;
        };
        if operation["requires_root"] == true {
            ui.label(format!(
                "Repository: {}",
                if self.repo.is_empty() {
                    "(select root above)"
                } else {
                    &self.repo
                }
            ));
        }
        if let Some(fields) = operation["fields"].as_array() {
            for field in fields {
                let Some(name) = field["name"].as_str() else {
                    continue;
                };
                let label = field["label"].as_str().unwrap_or(name);
                let value = self
                    .operator_fields
                    .entry(name.to_owned())
                    .or_insert(Value::Null);
                match field["kind"].as_str() {
                    Some("bool") => {
                        let mut checked = value.as_bool().unwrap_or(false);
                        ui.checkbox(&mut checked, label);
                        *value = json!(checked);
                    }
                    Some("choice") => {
                        let mut selected = value.as_str().unwrap_or("").to_owned();
                        ui.label(label);
                        egui::ComboBox::from_id_salt(("operator_field", name))
                            .selected_text(&selected)
                            .show_ui(ui, |ui| {
                                if field["required"] != true {
                                    ui.selectable_value(&mut selected, String::new(), "(default)");
                                }
                                if let Some(choices) = field["choices"].as_array() {
                                    for choice in choices.iter().filter_map(Value::as_str) {
                                        ui.selectable_value(
                                            &mut selected,
                                            choice.to_owned(),
                                            choice,
                                        );
                                    }
                                }
                            });
                        *value = json!(selected);
                    }
                    Some("file") => {
                        let mut input = value.as_str().unwrap_or("").to_owned();
                        ui.horizontal(|ui| {
                            ui.label(label);
                            ui.text_edit_singleline(&mut input);
                            if ui.button("Browse…").clicked() {
                                if let Some(path) = rfd::FileDialog::new()
                                    .add_filter("JSON files", &["json"])
                                    .pick_file()
                                {
                                    input = path.to_string_lossy().into_owned();
                                }
                            }
                        });
                        *value = json!(input);
                    }
                    _ => {
                        let mut input = value.as_str().unwrap_or("").to_owned();
                        ui.label(label);
                        if field["kind"] == "lines" {
                            ui.text_edit_multiline(&mut input);
                        } else {
                            ui.text_edit_singleline(&mut input);
                        }
                        *value = json!(input);
                    }
                }
            }
        }
        if ui.button("Run selected operation").clicked() {
            let payload = request(
                "operator_run",
                json!({"name": self.operator_name,
                "root": self.repo, "fields": self.operator_fields, "confirmed": true}),
            );
            let name = self.operator_name.clone();
            if operation["requires_confirmation"] == true {
                self.confirm(&name, payload);
            } else {
                self.submit(ctx, name, payload);
            }
        }
    }
    pub(super) fn worktrees(&mut self, ui: &mut egui::Ui) {
        ui.label("Worktree path (release); repository root above");
        ui.text_edit_singleline(&mut self.entity);
        ui.horizontal(|ui| {
            for (title, op) in [
                ("Prune stale worktrees", "worktree_prune"),
                ("Release worktree", "worktree_release"),
            ] {
                if ui.button(title).clicked() {
                    self.confirm(
                        title,
                        request(
                            op,
                            json!({"root": self.repo, "id": self.entity, "confirmed": true}),
                        ),
                    );
                }
            }
        });
    }
}
