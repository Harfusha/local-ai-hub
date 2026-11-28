use super::super::*;

impl Desktop {
    pub(super) fn requests(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        if self.current() == "Telemetry history" {
            ui.small("Installation-wide retained diagnostic events. The search applies to the loaded page only.");
            ui.horizontal_wrapped(|ui| {
                let previous = self.telemetry_limit;
                egui::ComboBox::from_id_salt("telemetry_page_size")
                    .selected_text(format!("{} rows", self.telemetry_limit))
                    .show_ui(ui, |ui| {
                        for limit in [50, 100, 250] {
                            ui.selectable_value(
                                &mut self.telemetry_limit,
                                limit,
                                format!("{limit} rows"),
                            );
                        }
                    });
                let next = self
                    .snapshot
                    .as_ref()
                    .filter(|_| self.snapshot_view == "Telemetry history")
                    .filter(|v| v["has_more"] == true)
                    .and_then(|v| v["next_cursor"].as_i64())
                    .filter(|next| {
                        *next > 0 && (self.telemetry_before == 0 || *next < self.telemetry_before)
                    });
                let newest = ui.button("Newest page").clicked();
                let older = ui
                    .add_enabled(next.is_some(), egui::Button::new("Older page"))
                    .clicked();
                if newest || previous != self.telemetry_limit {
                    self.telemetry_before = 0;
                    self.clear_response();
                    self.refresh(ctx);
                } else if older {
                    self.telemetry_before = next.expect("enabled only with cursor");
                    self.clear_response();
                    self.refresh(ctx);
                }
            });
            return;
        }
        if matches!(self.current(), "Async jobs" | "Work orders") {
            let async_job = self.current() == "Async jobs";
            let op = if async_job { "async_job" } else { "work_order" };
            ui.label(if async_job {
                "Async job ID"
            } else {
                "Work order ID"
            });
            ui.text_edit_singleline(&mut self.entity);
            if !async_job {
                ui.label("Answer for continuation");
                ui.text_edit_multiline(&mut self.reason);
            }
            ui.horizontal_wrapped(|ui| {
                let actions: &[(&str, &str)] = if async_job { &[("Status", "status"), ("Result", "result"), ("Cancel", "cancel")] }
                    else { &[("Status", "status"), ("Result", "get"), ("Cancel", "cancel"), ("Continue", "continue")] };
                for (title, action) in actions {
                    if ui.button(*title).clicked() {
                        let data = request(op, json!({"id": self.entity, "action": action, "answer": self.reason, "confirmed": true}));
                        if matches!(*action, "cancel" | "continue") { self.confirm(title, data); }
                        else { self.submit(ctx, (*title).into(), data); }
                    }
                }
            });
            return;
        }
        if self.current() == "Requests" {
            ui.horizontal_wrapped(|ui| {
                egui::ComboBox::from_id_salt("request_status")
                    .selected_text(&self.request_status)
                    .show_ui(ui, |ui| {
                        for status in ["all", "failed", "2xx", "4xx", "5xx"] {
                            ui.selectable_value(&mut self.request_status, status.into(), status);
                        }
                    });
                ui.label("Exact action");
                ui.text_edit_singleline(&mut self.request_action);
                egui::ComboBox::from_id_salt("request_sort")
                    .selected_text(&self.request_sort)
                    .show_ui(ui, |ui| {
                        for key in ["created_at", "duration_ms", "status_code", "action"] {
                            ui.selectable_value(&mut self.request_sort, key.into(), key);
                        }
                    });
                ui.checkbox(&mut self.request_desc, "Descending");
            });
        }
        if self.current() == "Endpoint analytics" {
            ui.horizontal_wrapped(|ui| {
                egui::ComboBox::from_id_salt("endpoint_scope")
                    .selected_text(&self.endpoint_scope)
                    .show_ui(ui, |ui| {
                        for scope in ["all", "active", "unused"] {
                            ui.selectable_value(&mut self.endpoint_scope, scope.into(), scope);
                        }
                    });
                egui::ComboBox::from_id_salt("endpoint_sort")
                    .selected_text(&self.endpoint_sort)
                    .show_ui(ui, |ui| {
                        for key in [
                            "name",
                            "type",
                            "calls",
                            "success_rate",
                            "p50_ms",
                            "p95_ms",
                            "p99_ms",
                        ] {
                            ui.selectable_value(&mut self.endpoint_sort, key.into(), key);
                        }
                    });
                ui.checkbox(&mut self.endpoint_desc, "Descending");
                if ui.button("Reset selected statistics").clicked() {
                    let global = self.repo.trim().is_empty();
                    let label = if global {
                        "Reset ALL project statistics and retained telemetry"
                    } else {
                        "Reset statistics for selected repository"
                    };
                    self.confirm(
                        label,
                        request(
                            "endpoint_reset",
                            json!({"root": self.repo, "global": global, "confirmed": true}),
                        ),
                    );
                }
            });
        }
        if self.current() == "Trace index" {
            ui.horizontal_wrapped(|ui| {
                ui.label("Kind");
                egui::ComboBox::from_id_salt("trace_kind")
                    .selected_text(if self.trace_kind.is_empty() {
                        "All"
                    } else {
                        &self.trace_kind
                    })
                    .show_ui(ui, |ui| {
                        for kind in ["", "api_request", "async_job"] {
                            ui.selectable_value(
                                &mut self.trace_kind,
                                kind.into(),
                                if kind.is_empty() { "All" } else { kind },
                            );
                        }
                    });
                ui.label("State");
                egui::ComboBox::from_id_salt("trace_state")
                    .selected_text(if self.trace_state.is_empty() {
                        "All"
                    } else {
                        &self.trace_state
                    })
                    .show_ui(ui, |ui| {
                        for state in [
                            "",
                            "running",
                            "queued",
                            "completed",
                            "failed",
                            "interrupted",
                        ] {
                            ui.selectable_value(
                                &mut self.trace_state,
                                state.into(),
                                if state.is_empty() { "All" } else { state },
                            );
                        }
                    });
                ui.label("Action");
                ui.text_edit_singleline(&mut self.trace_action);
                ui.label("Minimum ms");
                ui.add(egui::DragValue::new(&mut self.trace_min_ms).range(0..=86400000));
                if ui.button("Apply trace filters").clicked() {
                    self.trace_offset = 0;
                    self.refresh(ctx);
                }
            });
            ui.horizontal_wrapped(|ui| {
                let total = self
                    .snapshot
                    .as_ref()
                    .filter(|_| self.snapshot_view == "Trace index")
                    .and_then(|v| v["total"].as_i64());
                if ui
                    .add_enabled(
                        self.trace_offset > 0,
                        egui::Button::new("Previous trace page"),
                    )
                    .clicked()
                {
                    self.trace_offset = (self.trace_offset - 100).max(0);
                    self.refresh(ctx);
                }
                if ui
                    .add_enabled(
                        total.is_some_and(|n| self.trace_offset + 100 < n),
                        egui::Button::new("Next trace page"),
                    )
                    .clicked()
                {
                    self.trace_offset += 100;
                    self.refresh(ctx);
                }
                ui.label(format!(
                    "Offset {} / {}",
                    self.trace_offset,
                    total
                        .map(|n| n.to_string())
                        .unwrap_or_else(|| "unknown".into())
                ));
            });
            ui.small("Full inputs and outputs are captured only when detailed telemetry is enabled. Stored details appear as recorded; local access only; separate local retention policy.");
            ui.horizontal_wrapped(|ui| {
                ui.label("Trace ID");
                if ui.text_edit_singleline(&mut self.entity).changed() { self.trace_cursor = 0; self.trace_before = 0; self.trace_content_offset = 0; self.clear_response(); }
                ui.label("After sequence");
                ui.add(egui::DragValue::new(&mut self.trace_cursor).range(0..=i64::MAX));
                ui.label("Before sequence (0 = unset)");
                ui.add(egui::DragValue::new(&mut self.trace_before).range(0..=i64::MAX));
                if ui.button("Load trace events").clicked() {
                    self.submit(ctx, "Trace detail".into(), request("trace_detail",
                        json!({"id": self.entity, "after": self.trace_cursor, "before": self.trace_before})));
                }
            });
            ui.horizontal_wrapped(|ui| {
                if ui.button("Trace metrics").clicked() {
                    self.submit(ctx, "Trace metrics".into(), request("trace_metrics", json!({"id": self.entity})));
                }
                ui.label("Content field");
                ui.text_edit_singleline(&mut self.trace_content_field);
                ui.label("Offset");
                ui.add(egui::DragValue::new(&mut self.trace_content_offset).range(0..=i64::MAX));
                if ui.button("Read stored content page").clicked() {
                    self.confirm("Read sensitive locally retained content", request("trace_content",
                        json!({"id": self.entity, "field": self.trace_content_field, "offset": self.trace_content_offset, "confirmed": true})));
                }
            });
            ui.horizontal_wrapped(|ui| {
                ui.label("Redacted export file");
                ui.text_edit_singleline(&mut self.archive_path);
                if ui.button("Export redacted trace page").clicked() {
                    self.confirm("Export server-redacted trace page to a new file", request("trace_export",
                        json!({"id": self.entity, "after": self.trace_cursor, "file": self.archive_path, "confirmed": true})));
                }
            });
        }
    }
}
