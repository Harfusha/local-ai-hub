use super::super::*;

impl Desktop {
    pub(super) fn coordination(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.current() == "Semaphores" {
            ui.label("Semaphore name");
            ui.text_edit_singleline(&mut self.semaphore);
            ui.label("Exact owner ID");
            ui.text_edit_singleline(&mut self.lease_owner);
            ui.label("Lease ID (release only)");
            ui.text_edit_singleline(&mut self.entity);
            ui.add(egui::DragValue::new(&mut self.capacity).range(1..=100));
            ui.horizontal(|ui| {
                for (title, op) in [("Acquire", "semaphore_acquire"), ("Release", "semaphore_release")] {
                    if ui.button(title).clicked() {
                        self.confirm(title, request(op, json!({"name": self.semaphore,
                            "id": if op == "semaphore_acquire" { &self.lease_owner } else { &self.entity },
                            "owner": self.lease_owner, "capacity": self.capacity, "confirmed": true})));
                    }
                }
            });
            return;
        }
        if self.current() == "File leases" {
            ui.label("Lease ID and exact writer owner");
            ui.text_edit_singleline(&mut self.entity);
            ui.text_edit_singleline(&mut self.lease_owner);
            if ui
                .add_enabled(
                    !self.repo.is_empty()
                        && !self.entity.is_empty()
                        && !self.lease_owner.is_empty(),
                    egui::Button::new("Release lease"),
                )
                .clicked()
            {
                self.confirm(
                    "Release observed file lease",
                    request(
                        "lease_release",
                        json!({"root": self.repo,
                    "id": self.entity, "owner": self.lease_owner, "confirmed": true}),
                    ),
                );
            }
            return;
        }
        if self.current() == "Worktrees" {
            self.worktrees(ui);
            return;
        }
        if self.current() == "Session briefing" {
            ui.small(
                "Repository-scoped summary of plans, board and active tasks. Use Load / refresh.",
            );
            return;
        }
        ui.horizontal_wrapped(|ui| {
            ui.label("Server-side search");
            ui.text_edit_singleline(&mut self.plan_query);
            if self.current() == "Plans" {
                egui::ComboBox::from_id_salt("plan_lifecycle")
                    .selected_text(if self.plan_lifecycle.is_empty() {
                        "All lifecycles"
                    } else {
                        &self.plan_lifecycle
                    })
                    .show_ui(ui, |ui| {
                        for lifecycle in [
                            "",
                            "draft",
                            "active",
                            "paused",
                            "completed",
                            "archived",
                            "cancelled",
                        ] {
                            ui.selectable_value(
                                &mut self.plan_lifecycle,
                                lifecycle.into(),
                                if lifecycle.is_empty() {
                                    "All lifecycles"
                                } else {
                                    lifecycle
                                },
                            );
                        }
                    });
                egui::ComboBox::from_id_salt("plan_limit")
                    .selected_text(format!("{} plans", self.plan_limit))
                    .show_ui(ui, |ui| {
                        for limit in [25, 100, 250] {
                            ui.selectable_value(
                                &mut self.plan_limit,
                                limit,
                                format!("{limit} plans"),
                            );
                        }
                    });
            } else {
                ui.label("Board plan filter (blank = all non-archived, non-cancelled plans)");
                ui.text_edit_singleline(&mut self.board_plan_filter);
            }
            if ui.button("Apply plan filters").clicked() {
                self.clear_response();
                self.refresh(ctx);
            }
        });
        ui.label("Selected plan ID (independent of board filter)");
        if ui.text_edit_singleline(&mut self.entity).changed() {
            self.revision.clear();
            self.plan_draft = None;
            self.plan_task.clear();
            self.plan_execution_id.clear();
            self.plan_title.clear();
            self.description.clear();
        }
        ui.label("Task ID (empty for plan-level edit)");
        if ui.text_edit_singleline(&mut self.plan_task).changed() {
            self.plan_draft = None;
            self.plan_title.clear();
            self.description.clear();
            self.plan_execution_id.clear();
        }
        ui.label(format!(
            "Observed revision: {}",
            if self.revision.is_empty() {
                "not loaded"
            } else {
                &self.revision
            }
        ));
        if ui.button("Load exact plan / task for editing").clicked() {
            self.plan_draft = None;
            self.revision.clear();
            self.submit(
                ctx,
                "Plan detail".into(),
                request("plan_detail", json!({"root": self.repo, "id": self.entity})),
            );
        }
        ui.horizontal_wrapped(|ui| {
            if ui
                .add_enabled(
                    !self.entity.trim().is_empty(),
                    egui::Button::new("Validate plan"),
                )
                .clicked()
            {
                self.submit(
                    ctx,
                    "Plan validation".into(),
                    request(
                        "plan_validate",
                        json!({"root": self.repo, "id": self.entity}),
                    ),
                );
            }
            if ui
                .add_enabled(
                    !self.entity.trim().is_empty() && !self.revision.is_empty(),
                    egui::Button::new("Archive plan"),
                )
                .clicked()
            {
                self.confirm(
                    "Archive plan",
                    request(
                        "plan_archive",
                        json!({"root": self.repo,
                    "id": self.entity, "revision": self.revision, "confirmed": true}),
                    ),
                );
            }
        });
        ui.collapsing("Bind existing execution task", |ui| {
            ui.small("The task must belong to this repository, have a persisted session and matching acceptance criteria. Binding synchronizes its checkpoint into the plan.");
            ui.label("Exact Agent OS execution task ID");
            ui.text_edit_singleline(&mut self.plan_execution_id);
            let ready = self.plan_draft.as_ref().is_some_and(|draft|
                !draft.task_id.is_empty() && draft.matches(&self.entity, &self.plan_task, &self.revision));
            if ui.add_enabled(ready && !self.plan_execution_id.trim().is_empty(), egui::Button::new("Bind execution task")).clicked() {
                self.confirm("Bind execution task", request("plan_bind_task", json!({
                    "root": self.repo, "id": self.entity, "task_id": self.plan_task,
                    "execution_id": self.plan_execution_id, "revision": self.revision, "confirmed": true})));
            }
        });
        let mut edit_request = None;
        if let Some(draft) = self
            .plan_draft
            .as_mut()
            .filter(|d| d.matches(&self.entity, &self.plan_task, &self.revision))
        {
            ui.collapsing("Edit observed plan fields", |ui| {
                draft.render(ui);
                let changes = draft.patch();
                let title = if draft.task_id.is_empty() {
                    "Update plan"
                } else {
                    "Edit plan task"
                };
                if ui
                    .add_enabled(!changes.is_empty(), egui::Button::new(title))
                    .clicked()
                {
                    let op = if draft.task_id.is_empty() {
                        "plan_update"
                    } else {
                        "plan_task_edit"
                    };
                    let mut args = changes;
                    args.insert("root".into(), json!(self.repo));
                    args.insert("id".into(), json!(draft.plan_id));
                    args.insert("task_id".into(), json!(draft.task_id));
                    args.insert("revision".into(), json!(draft.revision));
                    args.insert("confirmed".into(), json!(true));
                    edit_request = Some((title, request(op, Value::Object(args))));
                }
            });
        }
        if let Some((title, payload)) = edit_request {
            self.confirm(title, payload);
        }
        ui.collapsing("Create new plan or task", |ui| {
            ui.label("New title and description");
            ui.text_edit_singleline(&mut self.plan_title);
            ui.text_edit_multiline(&mut self.description);
            ui.horizontal_wrapped(|ui| {
                if ui.button("Create plan").clicked() {
                    self.confirm("Create plan", request("plan_create", json!({"root": self.repo,
                        "id": self.entity, "title": self.plan_title, "description": self.description, "confirmed": true})));
                }
                if ui.add_enabled(!self.plan_task.is_empty() && !self.revision.is_empty(), egui::Button::new("Add plan task")).clicked() {
                    self.confirm("Add plan task", request("plan_task_create", json!({"root": self.repo,
                        "id": self.entity, "title": self.plan_title, "description": self.description,
                        "revision": self.revision, "task_id": self.plan_task, "confirmed": true})));
                }
            });
        });
        if ui
            .add_enabled(
                !self.plan_task.is_empty() && !self.revision.is_empty(),
                egui::Button::new("Delete plan task"),
            )
            .clicked()
        {
            self.confirm("Delete plan task", request("plan_task_delete", json!({"root": self.repo,
                "id": self.entity, "revision": self.revision, "task_id": self.plan_task, "confirmed": true})));
        }
        ui.horizontal_wrapped(|ui| {
            egui::ComboBox::from_id_salt("plan_move")
                .selected_text(&self.plan_status)
                .show_ui(ui, |ui| {
                    for status in ["planned", "ready", "in_progress", "blocked"] {
                        ui.selectable_value(&mut self.plan_status, status.into(), status);
                    }
                });
            if ui
                .add_enabled(
                    !self.plan_task.is_empty() && !self.revision.is_empty(),
                    egui::Button::new("Move task"),
                )
                .clicked()
            {
                self.confirm(
                    "Move plan task",
                    request(
                        "plan_task_move",
                        json!({
                    "root": self.repo, "id": self.entity, "task_id": self.plan_task,
                    "revision": self.revision, "status": self.plan_status, "confirmed": true}),
                    ),
                );
            }
        });
    }
}
