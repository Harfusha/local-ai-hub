use super::super::*;

impl Desktop {
    pub(super) fn tasks(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.current() == "Vision review" {
            ui.small("Raster images are not semantically indexed. Review is opt-in and sends the selected PNG/JPEG to the configured vision route.");
            ui.label("Image file (PNG or JPEG, maximum 8 MiB)");
            ui.text_edit_singleline(&mut self.vision_path);
            ui.label("Review prompt");
            ui.text_edit_multiline(&mut self.prompt);
            if ui
                .add_enabled(
                    !self.vision_path.trim().is_empty(),
                    egui::Button::new("Inspect image locally"),
                )
                .clicked()
            {
                self.clear_response();
                self.submit(
                    ctx,
                    "Image inspection".into(),
                    request("vision_inspect", json!({"file": self.vision_path})),
                );
            }
            let digest = self
                .snapshot
                .as_ref()
                .filter(|v| {
                    self.snapshot_view == "Image inspection"
                        && v["success"] == true
                        && v["file"].as_str() == Some(self.vision_path.trim())
                })
                .and_then(|v| v["image_sha256"].as_str())
                .filter(|d| d.len() == 64 && d.bytes().all(|b| b.is_ascii_hexdigit()))
                .map(str::to_owned);
            if let Some(ref value) = digest {
                ui.small(format!("Reviewed SHA-256: {value}"));
            } else {
                ui.small("Inspect the selected file before authorizing transmission.");
            }
            if ui
                .add_enabled(
                    digest.is_some() && !self.prompt.trim().is_empty(),
                    egui::Button::new("Run vision review"),
                )
                .clicked()
            {
                if let Some(digest) = digest {
                    self.confirm(
                        "Send inspected image to configured vision route",
                        request(
                            "vision_review",
                            json!({"file": self.vision_path, "image_sha256": digest,
                            "prompt": self.prompt, "confirmed": true}),
                        ),
                    );
                }
            }
            return;
        }
        if self.view == 1 {
            let previous_scope = self.memory_scope.clone();
            ui.horizontal_wrapped(|ui| {
                egui::ComboBox::from_id_salt("memory_scope")
                    .selected_text(&self.memory_scope)
                    .show_ui(ui, |ui| {
                        for scope in [
                            "global",
                            "repository",
                            "clone",
                            "worktree",
                            "branch",
                            "task",
                            "session",
                        ] {
                            ui.selectable_value(&mut self.memory_scope, scope.into(), scope);
                        }
                    });
                egui::ComboBox::from_id_salt("memory_kind")
                    .selected_text(&self.memory_kind)
                    .show_ui(ui, |ui| {
                        for kind in [
                            "fact",
                            "decision",
                            "convention",
                            "gotcha",
                            "hypothesis",
                            "assumption",
                            "playbook",
                            "capability_observation",
                            "environment_capsule",
                            "finding",
                            "reusable_candidate",
                            "contract_mapping",
                            "rejected_approach",
                            "unknown",
                            "validation",
                        ] {
                            ui.selectable_value(&mut self.memory_kind, kind.into(), kind);
                        }
                    });
            });
            if previous_scope != self.memory_scope {
                self.memory_scope_id.clear();
                self.memory_record_id.clear();
                self.memory_key.clear();
                self.memory_value.clear();
                self.reason.clear();
                self.clear_response();
            }
            if matches!(
                self.memory_scope.as_str(),
                "task" | "session" | "clone" | "worktree" | "branch"
            ) {
                ui.label(format!("Exact {} identity", self.memory_scope));
                if ui.text_edit_singleline(&mut self.memory_scope_id).changed() {
                    self.memory_record_id.clear();
                    self.memory_key.clear();
                    self.memory_value.clear();
                    self.reason.clear();
                    self.clear_response();
                }
            }
            ui.horizontal_wrapped(|ui| {
                ui.label("Server search");
                let query_changed = ui.text_edit_singleline(&mut self.memory_query).changed();
                ui.label("Exact key");
                let key_changed = ui
                    .text_edit_singleline(&mut self.memory_search_key)
                    .changed();
                let previous_status = self.memory_status.clone();
                let previous_limit = self.memory_limit;
                egui::ComboBox::from_id_salt("memory_status")
                    .selected_text(if self.memory_status.is_empty() {
                        "Any status"
                    } else {
                        &self.memory_status
                    })
                    .show_ui(ui, |ui| {
                        for status in [
                            "",
                            "candidate",
                            "active",
                            "confirmed",
                            "quarantined",
                            "superseded",
                            "rejected",
                            "stale",
                        ] {
                            ui.selectable_value(
                                &mut self.memory_status,
                                status.into(),
                                if status.is_empty() {
                                    "Any status"
                                } else {
                                    status
                                },
                            );
                        }
                    });
                egui::ComboBox::from_id_salt("memory_limit")
                    .selected_text(format!("Up to {}", self.memory_limit))
                    .show_ui(ui, |ui| {
                        for limit in [25, 50, 100] {
                            ui.selectable_value(
                                &mut self.memory_limit,
                                limit,
                                format!("Up to {limit}"),
                            );
                        }
                    });
                if query_changed
                    || key_changed
                    || previous_status != self.memory_status
                    || previous_limit != self.memory_limit
                {
                    self.memory_record_id.clear();
                    self.reason.clear();
                    self.clear_response();
                }
                if ui.button("Search memory").clicked() {
                    self.memory_record_id.clear();
                    self.clear_response();
                    self.refresh(ctx);
                }
            });
            ui.label("New memory key and value (text or JSON)");
            ui.text_edit_singleline(&mut self.memory_key);
            ui.text_edit_multiline(&mut self.memory_value);
            if ui.button("Record memory").clicked() {
                self.confirm(
                    "Record memory",
                    request("memory_record", self.memory_args("memory_record")),
                );
            }
            ui.label("Exact record ID (select a row or enter the ID)");
            if ui
                .text_edit_singleline(&mut self.memory_record_id)
                .changed()
            {
                self.reason.clear();
                self.clear_response();
            }
            let selected = !self.memory_record_id.trim().is_empty();
            if ui
                .add_enabled(selected, egui::Button::new("Load exact memory record"))
                .clicked()
            {
                self.submit(
                    ctx,
                    "Memory detail".into(),
                    request("memory_get", self.memory_args("memory_get")),
                );
            }
            ui.label("Quarantine reason");
            ui.text_edit_multiline(&mut self.reason);
            ui.horizontal_wrapped(|ui| {
                let mutable = selected && self.memory_scope != "worktree";
                if ui
                    .add_enabled(
                        mutable && !self.reason.trim().is_empty(),
                        egui::Button::new("Quarantine record"),
                    )
                    .clicked()
                {
                    self.confirm(
                        "Quarantine exact scoped memory record",
                        request("memory_quarantine", self.memory_args("memory_quarantine")),
                    );
                }
                if ui
                    .add_enabled(mutable, egui::Button::new("Delete memory record"))
                    .clicked()
                {
                    self.confirm(
                        "Delete exact scoped memory record",
                        request("memory_delete", self.memory_args("memory_delete")),
                    );
                }
            });
            ui.small("Results are bounded, not an exhaustive inventory. Global scope is shared; select it explicitly. Compaction and global promotion are not authorized by this HTTP endpoint.");
            if self.memory_scope == "worktree" {
                ui.small("Worktree mutations require an independently verified scope and are not supported here.");
            }
            return;
        }
        if self.view == 2 {
            ui.horizontal_wrapped(|ui| {
                let previous = self.incident_status.clone();
                let previous_limit = self.incident_limit;
                egui::ComboBox::from_id_salt("incident_status")
                    .selected_text(if self.incident_status.is_empty() {
                        "All states"
                    } else {
                        &self.incident_status
                    })
                    .show_ui(ui, |ui| {
                        for status in ["", "unresolved", "resolved", "ignored"] {
                            ui.selectable_value(
                                &mut self.incident_status,
                                status.into(),
                                if status.is_empty() {
                                    "All states"
                                } else {
                                    status
                                },
                            );
                        }
                    });
                egui::ComboBox::from_id_salt("incident_limit")
                    .selected_text(format!("Up to {}", self.incident_limit))
                    .show_ui(ui, |ui| {
                        for limit in [25, 50, 100] {
                            ui.selectable_value(
                                &mut self.incident_limit,
                                limit,
                                format!("Up to {limit}"),
                            );
                        }
                    });
                if previous != self.incident_status || previous_limit != self.incident_limit {
                    self.clear_response();
                }
                if ui.button("List incidents").clicked() {
                    self.refresh(ctx);
                }
            });
            ui.horizontal_wrapped(|ui| {
                ui.label("Search prior failures and lessons");
                ui.text_edit_singleline(&mut self.incident_query);
                if ui
                    .add_enabled(
                        !self.incident_query.trim().is_empty(),
                        egui::Button::new("Search negative knowledge"),
                    )
                    .clicked()
                {
                    self.submit(
                        ctx,
                        "Incidents".into(),
                        request(
                            "incident_find",
                            json!({"root": self.repo,
                        "query": self.incident_query, "limit": self.incident_limit}),
                        ),
                    );
                }
            });
            ui.small("Search uses a separate server operation and is not constrained by the list status filter. Both results are bounded.");
            ui.collapsing("Record incident or verified lesson", |ui| {
                ui.label("Incident operation class and message");
                ui.text_edit_singleline(&mut self.incident_kind);
                ui.text_edit_multiline(&mut self.incident_message);
                ui.label("Root cause (optional)");
                ui.text_edit_multiline(&mut self.incident_cause);
                ui.label("Verified fix (optional; leave empty if unverified)");
                ui.text_edit_multiline(&mut self.incident_fix);
                if ui
                    .add_enabled(
                        !self.incident_kind.trim().is_empty()
                            && !self.incident_message.trim().is_empty(),
                        egui::Button::new("Record incident"),
                    )
                    .clicked()
                {
                    self.confirm(
                        "Record incident",
                        request(
                            "incident",
                            json!({"root": self.repo,
                        "kind": self.incident_kind, "message": self.incident_message,
                        "cause": self.incident_cause, "fix": self.incident_fix, "confirmed": true}),
                        ),
                    );
                }
            });
            return;
        }
        ui.horizontal_wrapped(|ui| {
            ui.label("Server-side task search");
            let query_changed = ui.text_edit_singleline(&mut self.task_query).changed();
            let previous_status = self.task_status.clone();
            let previous_limit = self.task_limit;
            egui::ComboBox::from_id_salt("task_status_filter")
                .selected_text(if self.task_status.is_empty() {
                    "All states"
                } else {
                    &self.task_status
                })
                .show_ui(ui, |ui| {
                    for state in [
                        "",
                        "draft",
                        "planned",
                        "active",
                        "verifying",
                        "completed",
                        "waiting",
                        "blocked",
                        "failed",
                        "cancelled",
                        "abandoned",
                    ] {
                        ui.selectable_value(
                            &mut self.task_status,
                            state.into(),
                            if state.is_empty() {
                                "All states"
                            } else {
                                state
                            },
                        );
                    }
                });
            egui::ComboBox::from_id_salt("task_page_size")
                .selected_text(format!("{} rows", self.task_limit))
                .show_ui(ui, |ui| {
                    for size in [25, 50, 100, 250] {
                        ui.selectable_value(&mut self.task_limit, size, format!("{size} rows"));
                    }
                });
            if query_changed
                || previous_status != self.task_status
                || previous_limit != self.task_limit
            {
                self.task_offset = 0;
                self.task_back.clear();
                self.clear_response();
            }
            if ui.button("Search tasks").clicked() {
                self.task_offset = 0;
                self.task_back.clear();
                self.refresh(ctx);
            }
            let next = self
                .snapshot
                .as_ref()
                .filter(|_| self.snapshot_view == self.current())
                .filter(|v| v["has_more"] == true)
                .and_then(|v| v["next_offset"].as_i64())
                .filter(|next| *next > self.task_offset);
            if ui
                .add_enabled(
                    !self.task_back.is_empty(),
                    egui::Button::new("Previous page"),
                )
                .clicked()
            {
                self.task_offset = self.task_back.pop().expect("enabled only with history");
                self.clear_response();
                self.refresh(ctx);
            }
            if ui
                .add_enabled(
                    next.is_some() && self.task_back.len() < 500,
                    egui::Button::new("Next page"),
                )
                .clicked()
            {
                self.task_back.push(self.task_offset);
                self.task_offset = next.expect("enabled only with advancing server cursor");
                self.clear_response();
                self.refresh(ctx);
            }
            if self.snapshot_view == self.current()
                && self
                    .snapshot
                    .as_ref()
                    .is_some_and(|v| v["query_truncated"] == true)
            {
                ui.colored_label(
                    ui.visuals().warn_fg_color,
                    "Incomplete bounded search; refine filters.",
                );
            }
            ui.label(format!("Offset {}", self.task_offset));
        });
        if self.current() == "Run history" {
            ui.label(
                "Select a task from the table or enter its ID. History stays repository-scoped.",
            );
            if ui.text_edit_singleline(&mut self.entity).changed() {
                self.history_cursor = 0;
                self.clear_response();
            }
            ui.horizontal_wrapped(|ui| {
                ui.label("After sequence");
                ui.add(egui::DragValue::new(&mut self.history_cursor).range(0..=i64::MAX));
                if ui.button("Inspect run events").clicked() {
                    self.submit(ctx, "Run events".into(), request("event_page",
                        json!({"root": self.repo, "stream": self.entity, "after": self.history_cursor})));
                }
                let next = self.snapshot.as_ref().filter(|_| self.snapshot_view == "Run events")
                    .and_then(|v| v["next_seq"].as_i64());
                if let Some(next) = next {
                    if ui.add_enabled(next > self.history_cursor, egui::Button::new("Next event page")).clicked() {
                        self.history_cursor = next;
                        self.submit(ctx, "Run events".into(), request("event_page",
                            json!({"root": self.repo, "stream": self.entity, "after": self.history_cursor})));
                    }
                }
            });
            return;
        }
        ui.collapsing("Create task contract", |ui| {
            ui.horizontal_wrapped(|ui| {
                egui::ComboBox::from_id_salt("task_scope").selected_text(&self.task_scope).show_ui(ui, |ui| {
                    for scope in ["task", "session", "repository", "branch", "worktree", "clone", "global"] { ui.selectable_value(&mut self.task_scope, scope.into(), scope); }
                });
                egui::ComboBox::from_id_salt("task_risk").selected_text(&self.task_risk).show_ui(ui, |ui| {
                    for risk in ["low", "normal", "high", "critical"] { ui.selectable_value(&mut self.task_risk, risk.into(), risk); }
                });
            });
            ui.label("Goal");
            ui.text_edit_multiline(&mut self.goal);
            ui.label("Acceptance criteria (one per line)");
            ui.text_edit_multiline(&mut self.criteria);
            ui.collapsing("Additional contract fields", |ui| {
                ui.label("Description");
                ui.text_edit_multiline(&mut self.description);
                ui.label("Non-goals (one per line)");
                ui.text_edit_multiline(&mut self.task_non_goals);
                ui.label("Constraints (one per line)");
                ui.text_edit_multiline(&mut self.task_constraints);
                ui.label("Session ID (optional; required for plan binding)");
                ui.text_edit_singleline(&mut self.task_session);
                ui.label("SLO profile (optional JSON object)");
                ui.text_edit_multiline(&mut self.task_slo);
            });
            ui.small("Goal scope describes the contract; repository authorization still uses the explicit selected root.");
            if let Some(error) = &self.task_form_error {
                ui.colored_label(egui::Color32::RED, error);
            }
            if ui.add_enabled(!self.goal.trim().is_empty(), egui::Button::new("Create task")).clicked() {
                match task_create_payload(TaskCreateInput {
                    root: &self.repo,
                    goal: &self.goal,
                    criteria: &self.criteria,
                    scope: &self.task_scope,
                    risk_profile: &self.task_risk,
                    description: &self.description,
                    non_goals: &self.task_non_goals,
                    constraints: &self.task_constraints,
                    session_id: &self.task_session,
                    slo_json: &self.task_slo,
                }) {
                    Ok(payload) => {
                        self.task_form_error = None;
                        self.confirm("Create task", payload);
                    }
                    Err(error) => self.task_form_error = Some(error),
                }
            }
        });
        ui.label("Task ID and reason (repository required)");
        ui.text_edit_singleline(&mut self.entity);
        ui.text_edit_singleline(&mut self.reason);
        ui.horizontal_wrapped(|ui| {
            if ui.button("Check completion receipts").clicked() {
                self.submit(ctx, "Completion gate".into(), request("task_gate",
                    json!({"root": self.repo, "id": self.entity})));
            }
            egui::ComboBox::from_id_salt("task_target").selected_text(&self.task_target).show_ui(ui, |ui| {
                for state in ["active", "verifying", "blocked", "planned", "waiting", "cancelled", "abandoned"] {
                    ui.selectable_value(&mut self.task_target, state.into(), state);
                }
            });
            for (title, action) in [("Inspect", "get"), ("Complete", "complete"), ("Fail", "fail"), ("Transition", "transition")] {
                if ui.button(title).clicked() {
                    let data = request("task", json!({"root": self.repo, "id": self.entity,
                        "reason": self.reason, "status": self.task_target, "action": action, "confirmed": true}));
                    if action == "get" { self.submit(ctx, title.into(), data); }
                    else { self.confirm(title, data); }
                }
            }
        });
    }
}
