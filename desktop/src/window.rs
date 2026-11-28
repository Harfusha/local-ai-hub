use super::*;

impl Desktop {
    // Keep rendering independent of eframe::Frame so all native screens can
    // be exercised with an egui context in the cross-platform test matrix.
    pub(super) fn render(&mut self, ctx: &egui::Context) {
        self.receive();
        // Keyboard navigation never confirms a mutation implicitly.
        if ctx.input_mut(|i| i.consume_key(egui::Modifiers::NONE, egui::Key::Escape)) {
            if self.pending.take().is_some() {
                self.status = "Operation cancelled before dispatch.".into();
            } else if self.installation_open {
                self.installation_open = false;
            } else {
                self.detail = None;
                self.record_detail = None;
            }
        }
        if self.can_edit_context()
            && ctx.input_mut(|i| i.consume_key(egui::Modifiers::NONE, egui::Key::F5))
        {
            self.refresh(ctx);
        }
        // Only wake for health checks while focused, never continuously repaint an idle window.
        let focused = ctx.input(|i| i.focused);
        if self.auto_live
            && self.current() == "Agent event stream"
            && focused
            && self.busy.is_none()
            && self.pending.is_none()
            && !self.installation_open
        {
            if self.last_live.elapsed() >= Duration::from_secs(1) {
                self.submit(ctx, "Agent event stream".into(), request("event_stream",
                    json!({"root": self.repo, "stream": self.stream_id, "after": self.event_cursor})));
            } else {
                ctx.request_repaint_after(
                    Duration::from_secs(1).saturating_sub(self.last_live.elapsed()),
                );
            }
        }
        if self.auto_probe
            && focused
            && self.busy.is_none()
            && self.pending.is_none()
            && !self.installation_open
        {
            if self.last_probe.elapsed() >= Duration::from_secs(30) {
                self.last_probe = Instant::now();
                self.submit(ctx, "Check service".into(), request("probe", json!({})));
            } else {
                ctx.request_repaint_after(
                    Duration::from_secs(30).saturating_sub(self.last_probe.elapsed()),
                );
            }
        }
        if self.auto_log
            && self.current() == "Service health"
            && !self.raw_view
            && focused
            && self.can_edit_context()
        {
            let interval = Duration::from_secs(5);
            if self.last_log.elapsed() >= interval {
                self.refresh(ctx);
            } else {
                ctx.request_repaint_after(interval.saturating_sub(self.last_log.elapsed()));
            }
        }
        if self.busy.is_some() && ctx.input(|i| i.viewport().close_requested()) {
            ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
            self.status = "An operation is in progress. Finish it before closing.".into();
        }
        egui::TopBottomPanel::top("toolbar").show(ctx, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.heading("Local AI Hub");
                ui.separator();
                ui.label(match self.service {
                    Some(true) => "Service online",
                    Some(false) => "Service unreachable — Start Hub",
                    None => "Service status unknown",
                });
                ui.add_enabled_ui(self.can_edit_context(), |ui| {
                    for (title, action) in [
                        ("Start Hub", "start"),
                        ("Stop", "stop"),
                        ("Restart", "restart"),
                    ] {
                        if ui.button(title).clicked() {
                            self.lifecycle(ctx, action);
                        }
                    }
                    if ui.button("Check status").clicked() {
                        self.submit(ctx, "Check service".into(), request("probe", json!({})));
                    }
                    egui::ComboBox::from_id_salt("mode")
                        .selected_text(&self.mode)
                        .show_ui(ui, |ui| {
                            for mode in ["active", "gaming", "maintenance", "preprocessing"] {
                                ui.selectable_value(&mut self.mode, mode.to_owned(), mode);
                            }
                        });
                    if ui.button("Apply mode").clicked() {
                        self.confirm(
                            "Change activity mode",
                            request("mode", json!({"mode": self.mode, "confirmed": true})),
                        );
                    }
                    if ui.button("Installation").clicked() {
                        self.installation_open = true;
                    }
                });
            });
            ui.horizontal_wrapped(|ui| {
                ui.checkbox(
                    &mut self.auto_probe,
                    "Check status automatically while focused",
                );
                if self.current() == "Agent event stream" {
                    ui.checkbox(&mut self.auto_live, "Follow live SSE while focused");
                }
                if self.current() == "Service health"
                    && ui
                        .checkbox(&mut self.auto_log, "Follow log tail while focused")
                        .changed()
                    && self.auto_log
                {
                    self.last_log = Instant::now() - Duration::from_secs(5);
                    ctx.request_repaint();
                }
                let label = ui.label("Repository root");
                let response = ui
                    .add_enabled(
                        self.can_edit_context(),
                        egui::TextEdit::singleline(&mut self.repo).desired_width(400.0),
                    )
                    .labelled_by(label.id);
                if self.can_edit_context()
                    && ctx.input_mut(|i| i.consume_key(egui::Modifiers::COMMAND, egui::Key::L))
                {
                    response.request_focus();
                }
                if response.changed() {
                    self.reset_scope();
                }
            });
        });
        egui::TopBottomPanel::bottom("status").show(ctx, |ui| {
            if let Some(label) = &self.busy {
                ui.horizontal(|ui| {
                    // A short periodic probe must not start a continuous
                    // animation/repaint loop on otherwise idle desktops.
                    if label != "Check service" {
                        ui.spinner();
                    }
                    ui.label(format!("{label} — running"));
                });
            } else {
                ui.label(&self.status);
            }
        });
        egui::SidePanel::left("navigation")
            .resizable(false)
            .default_width(170.0)
            .show(ctx, |ui| {
                ui.add_enabled_ui(self.can_edit_context(), |ui| {
                    for (index, (name, _)) in PAGES.iter().enumerate() {
                        if ui.selectable_label(self.page == index, *name).clicked()
                            && self.page != index
                        {
                            self.navigate(index, 0);
                        }
                    }
                });
            });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading(PAGES[self.page].0);
            ui.add_enabled_ui(self.can_edit_context(), |ui| {
                ui.horizontal_wrapped(|ui| {
                    for (index, view) in PAGES[self.page].1.iter().enumerate() {
                        if ui.selectable_label(self.view == index, *view).clicked() && self.view != index {
                            self.navigate(self.page, index);
                        }
                    }
                    if matches!(self.current(), "Overview" | "Requests" | "Active requests" | "Async jobs" | "Work orders" | "Commands" | "Process sessions" | "Recent errors" | "Runtime health" | "Models & search" | "Model statistics" | "Execution profiles" | "Cache layers" | "Agent statistics" | "Execution routes" | "Laya" | "Laya capture") {
                        let previous = self.metrics_period.clone();
                        egui::ComboBox::from_id_salt("metrics_period").selected_text(if self.metrics_period == "process" { "Since restart" } else { "Last 30 days" }).show_ui(ui, |ui| {
                            ui.selectable_value(&mut self.metrics_period, "process".into(), "Since restart");
                            ui.selectable_value(&mut self.metrics_period, "window".into(), "Last 30 days");
                        });
                        if self.metrics_period != previous { self.clear_response(); self.refresh(ctx); }
                    }
                    if ui.button("Load / refresh").on_hover_text("F5 — refresh current view").clicked() { self.refresh(ctx); }
                });
                // Long forms (plans, operator catalog, traces) must not push
                // their action buttons and the response table outside the window.
                let control_height = (ui.available_height() * 0.45).max(100.0);
                egui::ScrollArea::vertical().id_salt(("view_controls", self.page, self.view))
                    .max_height(control_height).auto_shrink([false, true]).show(ui, |ui| self.operations(ui, ctx));
            });
            ui.separator();
            ui.horizontal(|ui| {
                let label = ui.label("Search response");
                let response = ui.text_edit_singleline(&mut self.filter).labelled_by(label.id);
                if self.can_edit_context() && ctx.input_mut(|i| i.consume_key(egui::Modifiers::COMMAND, egui::Key::F)) { response.request_focus(); }
                if response.changed() { self.refilter(); }
                ui.label(format!("{} fields", self.visible.len()));
                ui.checkbox(&mut self.raw_view, "Raw fields");
            });
            if self.rows.is_empty() { ui.label("Load this view to inspect data. No hidden screen is polled."); }
            if self.current() == "Service health" && !self.raw_view {
                ui.heading("Operational log tail");
                ui.horizontal_wrapped(|ui| {
                    let before = self.log_lines;
                    ui.add_enabled_ui(self.can_edit_context(), |ui| {
                        egui::ComboBox::from_id_salt("log_line_count")
                            .selected_text(format!("{} lines", self.log_lines)).show_ui(ui, |ui| {
                            for count in [100, 250, 500] {
                                ui.selectable_value(&mut self.log_lines, count, format!("{count} lines"));
                            }
                        });
                    });
                    if self.log_lines != before { self.refresh(ctx); }
                    ui.small("Search response filters the latest bounded tail. Follow refreshes every five seconds while focused; it is not a gap-free event stream. Logs may contain sensitive data.");
                });
                if let Some(snapshot) = self.snapshot.as_ref().filter(|_| self.snapshot_view == "Service health") {
                    if let Some(lines) = filtered_log_lines(snapshot, &self.filter) {
                        ui.horizontal(|ui| {
                            ui.label(format!("{} matching lines", lines.len()));
                            if ui.add_enabled(!lines.is_empty(), egui::Button::new("Copy filtered logs")).clicked() {
                                ui.ctx().copy_text(lines.join("\n"));
                            }
                        });
                        if lines.is_empty() { ui.label("No log lines match this filter."); }
                        let height = ui.text_style_height(&egui::TextStyle::Monospace) + 4.0;
                        egui::ScrollArea::both().id_salt("operational_logs").stick_to_bottom(self.auto_log)
                            .show_rows(ui, height, lines.len(), |ui, range| {
                                for index in range { ui.add(egui::Label::new(egui::RichText::new(lines[index]).monospace()).wrap_mode(egui::TextWrapMode::Extend)); }
                            });
                    } else { ui.label("Log data unavailable."); }
                }
                return;
            }
            if self.current() == "Instruction compression" && self.snapshot_view == "Instruction review" && !self.raw_view {
                if let Some(receipt) = self.snapshot.as_ref() {
                    ui.heading("Exact staged instruction review");
                    ui.label(format!("Source: {}", records::display(&receipt["source"])));
                    ui.label(format!("State: {} — {} bytes → {} bytes", records::display(&receipt["status"]),
                        records::display(&receipt["original_bytes"]), records::display(&receipt["candidate_bytes"])));
                    ui.small(format!("Manifest SHA-256: {}", records::display(&receipt["manifest_sha256"])));
                    ui.small("Local semantic review is advisory. Compare actual text before approving; no new inference occurs on apply.");
                    ui.columns(2, |columns| {
                        for (index, (key, heading)) in [("original","Original"), ("candidate","Candidate")].iter().enumerate() {
                            let ui = &mut columns[index];
                            ui.heading(*heading);
                            let text = receipt[*key].as_str().unwrap_or("");
                            if ui.button("Copy text").clicked() { ui.ctx().copy_text(text.to_owned()); }
                            let lines: Vec<&str> = text.lines().collect();
                            let row_height = ui.text_style_height(&egui::TextStyle::Monospace) + 3.0;
                            egui::ScrollArea::both().id_salt(("instruction_review", key))
                                .show_rows(ui, row_height, lines.len(), |ui, range| {
                                    for line in range {
                                        ui.add(egui::Label::new(egui::RichText::new(lines[line]).monospace())
                                            .wrap_mode(egui::TextWrapMode::Extend));
                                    }
                                });
                        }
                    });
                }
                return;
            }
            if self.snapshot_view == "Export encrypted diagnostics" {
                if let Some(receipt) = self.snapshot.as_ref() {
                    ui.heading("Encrypted support archive");
                    ui.label(format!("File: {}", records::display(&receipt["file"])));
                    ui.label(format!("Size: {} bytes", records::display(&receipt["bytes"])));
                    ui.small("Keep the password separately from the archive. It is available only until another response or navigation replaces this receipt.");
                    if let Some(password) = receipt["archive_password"].as_str() {
                        ui.checkbox(&mut self.reveal_trace, "Reveal archive password");
                        if self.reveal_trace {
                            ui.label(egui::RichText::new(password).monospace());
                            if ui.button("Copy archive password").clicked() { ui.ctx().copy_text(password.to_owned()); }
                        }
                    } else { ui.colored_label(ui.visuals().warn_fg_color, "Archive password not supplied; do not assume the archive is recoverable."); }
                    return;
                }
            }
            if self.snapshot_view == "Trace content" {
                if let Some(page) = self.snapshot.as_ref().and_then(|response| response.get("content_page")) {
                    ui.label(format!("Stored content: {} · offset {} · next {} · more {} · storage truncated {}",
                        page["field"], page["offset"], page["next_offset"], page["has_more"], page["storage_truncated"]));
                    if page["has_more"] == true && ui.button("Use next content offset").clicked() {
                        if let Some(offset) = page["next_offset"].as_i64() { self.trace_content_offset = offset; }
                    }
                    ui.checkbox(&mut self.reveal_trace, "Reveal raw stored content (sensitive)");
                    if self.reveal_trace {
                        egui::ScrollArea::vertical().show(ui, |ui| {
                            let text = page["text"].as_str().unwrap_or("Stored content unavailable");
                            if ui.button("Copy sensitive content").clicked() { ui.ctx().copy_text(text.to_owned()); }
                            ui.label(text);
                        });
                    }
                    return;
                }
            }
            if self.snapshot_view == "Trace detail" && !self.raw_view {
                if let Some(projection) = self.snapshot.as_ref().and_then(trace::trace) {
                    ui.heading("Retained trace");
                    if let Some(snapshot) = self.snapshot.as_ref() {
                        ui.label(format!("Page: next sequence {} · more {} · retained range {}–{} · truncated {}", snapshot["next_seq"], snapshot["has_more"], snapshot["first_retained_seq"], snapshot["last_seq"], snapshot["page_truncated"]));
                        if snapshot["has_more"] == true && ui.button("Use next event cursor").clicked() {
                            if let Some(next) = snapshot["next_seq"].as_i64() { self.trace_cursor = next; self.trace_before = 0; }
                        }
                    }
                    ui.label(format!("{} · {}", records::display(&projection.session["action"]),
                        records::display(&projection.session["state"])));
                    egui::ScrollArea::vertical().id_salt("trace_primary").show(ui, |ui| {
                        for (label, value) in [("Input", projection.input), ("Output", projection.output)] {
                            ui.heading(format!("{label} — {}", trace::capture_state(value, "")));
                            if let Some(value) = value {
                                let safe = trace::sanitize(value);
                                let content = if let Some(text) = safe.as_str() { text.to_owned() }
                                    else { serde_json::to_string_pretty(&safe).unwrap_or_default() };
                                ui.label(content);
                            }
                        }
                        ui.collapsing(format!("Events ({})", projection.events.len()), |ui| {
                            for event in projection.events.iter().take(100) {
                                let title = format!("{} · {}", records::display(&event["seq"]), records::display(&event["event_type"]));
                                ui.collapsing(title, |ui| { ui.label(serde_json::to_string_pretty(&trace::sanitize(event)).unwrap_or_default()); });
                            }
                        });
                        ui.collapsing("Technical session details (redacted)", |ui| {
                            ui.label(serde_json::to_string_pretty(&trace::sanitize(projection.session)).unwrap_or_default());
                        });
                        ui.checkbox(&mut self.reveal_trace, "Show complete stored response as recorded (may contain sensitive material)");
                        if self.reveal_trace {
                            let raw = serde_json::to_string_pretty(self.snapshot.as_ref().unwrap()).unwrap_or_default();
                            if ui.button("Copy complete stored response").clicked() { ui.ctx().copy_text(raw.clone()); }
                            ui.label(raw);
                        }
                    });
                    return;
                }
            }
            if self.snapshot_view == "Completion gate" && !self.raw_view {
                if let Some(snapshot) = self.snapshot.as_ref() {
                    summary::completion(ui, &snapshot["completion"]);
                    return;
                }
            }
            if matches!(self.snapshot_view.as_str(), "Save settings" | "Reset configuration overrides") {
                if let Some(snapshot) = self.snapshot.as_ref() {
                    if snapshot["restart_required"] == true { ui.colored_label(ui.visuals().warn_fg_color, "Overrides saved; restart Hub to apply."); }
                    else if snapshot["applied_live"] == true { ui.label("Server reports settings applied live."); }
                    else { ui.label("Application status not reported; reload configuration."); }
                }
            }
            if self.snapshot_view == "Run events" && !self.raw_view {
                if let Some(snapshot) = self.snapshot.as_ref() {
                    ui.heading("Task run events");
                    if snapshot["retention_gap_metadata_available"] != true {
                        ui.colored_label(ui.visuals().warn_fg_color, "History completeness is not established; inspect retention metadata.");
                    }
                    if let Some(gaps) = snapshot["gap_ranges"].as_array() {
                        if !gaps.is_empty() { ui.colored_label(ui.visuals().warn_fg_color, format!("Retention gaps: {}", snapshot["gap_ranges"])); }
                    }
                    ui.label(format!("Next sequence: {} · more: {}", snapshot["next_seq"], snapshot["has_more"]));
                    egui::ScrollArea::vertical().show(ui, |ui| {
                        if let Some(events) = snapshot["events"].as_array() {
                            for event in events.iter().take(100) {
                                ui.collapsing(format!("{} · {}", event["seq"], records::display(&event["kind"])), |ui| {
                                    ui.label(serde_json::to_string_pretty(&trace::sanitize(event)).unwrap_or_default());
                                });
                            }
                        }
                    });
                    return;
                }
            }
            if !self.raw_view && self.snapshot_view == self.current() {
                if let Some(snapshot) = &self.snapshot {
                    summary::render(ui, self.current(), snapshot);
                    if self.current() == "Plan board" {
                        if let Some(columns) = records::board_columns(snapshot) {
                            if let Some((total, declared, verified)) = records::progress(snapshot) {
                                ui.label(format!("{verified} verified complete / {total} tasks · {declared} declared done"));
                                if total > 0 { ui.add(egui::ProgressBar::new(verified as f32 / total as f32).show_percentage()); }
                            }
                            let mut selected = None;
                            let needle = self.filter.to_lowercase();
                            egui::ScrollArea::both().id_salt("kanban").show(ui, |ui| {
                                ui.horizontal_top(|ui| {
                                    for (state, cards) in columns {
                                        ui.vertical(|ui| {
                                            ui.set_min_width(175.0);
                                            ui.heading(format!("{state} ({})", cards.len()));
                                            for card in cards.iter().take(500) {
                                                if !needle.is_empty() && !card.to_string().to_lowercase().contains(&needle) { continue; }
                                                let title = records::display(&card["title"]);
                                                if ui.add_enabled(self.can_edit_context(), egui::Button::new(title.chars().take(80).collect::<String>())).clicked() { selected = Some(card.clone()); }
                                                ui.small(records::display(&card["task_id"]));
                                                if state == "done" && card["verified"].as_bool() != Some(true) {
                                                    ui.small("Declared, not verified");
                                                }
                                            }
                                            if cards.len() > 500 { ui.small("Display capped at 500 cards"); }
                                        });
                                        ui.separator();
                                    }
                                });
                            });
                            if let Some(card) = selected {
                                self.plan_task = card["task_id"].as_str().unwrap_or("").to_owned();
                                self.revision = card["plan_file_revision"].as_str().unwrap_or("").to_owned();
                                self.entity = card["plan_id"].as_str().unwrap_or("").to_owned();
                                self.plan_draft = None;
                                self.plan_title.clear(); self.description.clear();
                                self.record_detail = Some(card);
                            }
                            return;
                        }
                    }
                    if self.current() == "Search workspaces" { ui.label("Read-only inventory. Unknown status is not proof of a missing index. No automatic removal."); }
                    if self.current() == "Endpoint analytics" { ui.label("Endpoint and MCP calls do not prove model execution. Select an explicit repository to scope counts."); }
                    if let Some(table) = records::records(self.current(), snapshot) {
                        let needle = self.filter.to_lowercase();
                        let mut filtered: Vec<&Value> = table.values.into_iter().filter(|item|
                            needle.is_empty() || item.to_string().to_lowercase().contains(&needle)).collect();
                        if self.current() == "Endpoint analytics" {
                            filtered.retain(|item| records::endpoint_matches(item, &self.endpoint_scope));
                            records::sort_records(&mut filtered, &self.endpoint_sort, self.endpoint_desc);
                        }
                        if self.current() == "Requests" {
                            filtered.retain(|item| records::request_matches(item, &self.request_status, &self.request_action));
                            records::sort_records(&mut filtered, &self.request_sort, self.request_desc);
                        }
                        ui.label(format!("{} matching records (bounded response)", filtered.len()));
                        if self.current() == "Plans" && snapshot["count"].as_u64().zip(snapshot["desktop_list_limit"].as_u64())
                            .is_some_and(|(count, limit)| count >= limit) {
                            ui.colored_label(ui.visuals().warn_fg_color, "Plan list reached its bound. Narrow the server search or increase the limit.");
                        }
                        let mut selected = None;
                        egui::ScrollArea::horizontal().id_salt("records").show(ui, |ui| {
                            ui.horizontal(|ui| {
                                for column in table.columns {
                                    ui.add_sized([155.0, 24.0], egui::Label::new(*column));
                                }
                            });
                            let height = ui.text_style_height(&egui::TextStyle::Body) + 10.0;
                            egui::ScrollArea::vertical().id_salt("records_rows").show_rows(ui, height, filtered.len(), |ui, range| {
                                for index in range {
                                    let item = filtered[index];
                                    ui.horizontal(|ui| {
                                        for (col, field) in table.columns.iter().enumerate() {
                                            let value = if self.current() == "Trace index" { records::display(&trace::sanitize(records::field(item, field))) } else { records::display(records::field(item, field)) };
                                            let display: String = value.chars().take(32).collect();
                                            if col == 0 {
                                                if ui.add_enabled(self.can_edit_context(), egui::Button::new(display).min_size(egui::vec2(155.0, height))).clicked() { selected = Some(item.clone()); }
                                            } else {
                                                ui.add_sized([155.0, height], egui::Label::new(display));
                                            }
                                        }
                                    });
                                }
                            });
                        });
                        if let Some(item) = selected {
                            if let Some(id) = records::selection_id(self.current(), &item) {
                                if self.entity != id { self.history_cursor = 0; self.trace_cursor = 0; self.trace_before = 0; self.trace_content_offset = 0; }
                                self.entity = id.to_owned();
                            }
                            if self.current() == "Memory" {
                                let id = item["record_id"].as_str().filter(|_| item["scope"].as_str() == Some(self.memory_scope.as_str())).unwrap_or("");
                                if self.memory_record_id != id { self.reason.clear(); }
                                self.memory_record_id = id.to_owned();
                            }
                            if self.current() == "File leases" {
                                self.lease_owner = item["owner"].as_str().unwrap_or("").to_owned();
                            }
                            if self.current() == "Semaphores" {
                                self.semaphore = item["name"].as_str().unwrap_or("").to_owned();
                                self.lease_owner.clear();
                                self.entity.clear();
                            }
                            if self.current() == "Plans" {
                                self.revision = item["file_revision"].as_str().unwrap_or("").to_owned();
                                self.plan_task.clear(); self.plan_draft = None;
                                self.plan_title.clear(); self.description.clear();
                            }
                            self.record_detail = Some(if self.current() == "Trace index" { trace::sanitize(&item) } else { item });
                        }
                        return;
                    }
                }
            }
            let row_height = ui.text_style_height(&egui::TextStyle::Body) + 8.0;
            egui::ScrollArea::vertical().id_salt("response").show_rows(ui, row_height, self.visible.len(), |ui, range| {
                for pos in range {
                    let index = self.visible[pos];
                    let row = &self.rows[index];
                    ui.horizontal(|ui| {
                        let path: String = row.path.chars().take(100).collect();
                        let preview: String = row.value.chars().take(180).collect();
                        if ui.selectable_label(self.detail == Some(index), path).clicked() { self.detail = Some(index); }
                        ui.label(preview.replace(['\n', '\r'], " "));
                    });
                }
            });
        });
        let mut open_trace = None;
        let mut open_project = None;
        if let Some(record) = &self.record_detail {
            let mut open = true;
            let can_navigate = self.can_edit_context();
            egui::Window::new("Record detail")
                .open(&mut open)
                .show(ctx, |ui| {
                    let text = serde_json::to_string_pretty(record).unwrap_or_default();
                    if ui.button("Copy record").clicked() {
                        ui.ctx().copy_text(text.clone());
                    }
                    if self.current() == "Projects" || self.current() == "Search workspaces" {
                        if let Some(root) = record["root"].as_str().filter(|r| !r.trim().is_empty())
                        {
                            if ui
                                .add_enabled(
                                    can_navigate,
                                    egui::Button::new(
                                        "Select repository and inspect configuration",
                                    ),
                                )
                                .clicked()
                            {
                                open_project = Some(root.to_owned());
                            }
                        }
                    }
                    if let Some(id) = linked_trace(record) {
                        if ui
                            .add_enabled(can_navigate, egui::Button::new("Open linked trace"))
                            .clicked()
                        {
                            open_trace = Some(id.to_owned());
                        }
                    }
                    egui::ScrollArea::both().max_height(500.0).show(ui, |ui| {
                        ui.label(text);
                    });
                });
            if !open {
                self.record_detail = None;
            }
        }
        if let Some(root) = open_project {
            self.open_project(ctx, root);
        } else if let Some(id) = open_trace {
            self.open_linked_trace(ctx, id);
        }
        if let Some(index) = self.detail {
            let mut open = true;
            if let Some(row) = self.rows.get(index) {
                egui::Window::new("Field detail")
                    .open(&mut open)
                    .resizable(true)
                    .show(ctx, |ui| {
                        ui.label(&row.path);
                        if ui.button("Copy value").clicked() {
                            ui.ctx().copy_text(row.value.clone());
                        }
                        egui::ScrollArea::both().show(ui, |ui| {
                            ui.label(&row.value);
                        });
                    });
            }
            if !open {
                self.detail = None;
            }
        }
        if self.pending.is_some() {
            let mut decision = None;
            egui::Window::new("Confirm operation").collapsible(false).resizable(true).default_width(550.0).show(ctx, |ui| {
                ui.label(&self.pending.as_ref().unwrap().label);
                ui.label("This operation may change Hub state. Verify the selected repository and target.");
                let payload = &self.pending.as_ref().unwrap().payload;
                let args = &payload["args"];
                let max_height = (ctx.input(|i| i.screen_rect().height()) * 0.5).max(120.0);
                egui::ScrollArea::vertical().max_height(max_height).show(ui, |ui| {
                    for (key, value) in confirmation_items(payload) {
                        ui.label(format!("{key}: {value}"));
                    }
                    if let Some(changes) = args["settings"].as_object() {
                        for (key, value) in changes { ui.label(format!("{key}: {value}")); }
                    }
                    if let Some(fields) = args["fields"].as_object() {
                        ui.collapsing("Reviewed operator parameters", |ui| {
                            for (key, value) in fields { ui.label(format!("{key}: {value}")); }
                        });
                    }
                });
                ui.small("Escape cancels without applying changes.");
                ui.horizontal(|ui| {
                    if ui.button("Cancel").clicked() { decision = Some(false); }
                    if ui.button("Confirm").clicked() { decision = Some(true); }
                });
            });
            if let Some(accepted) = decision {
                if let Some(pending) = self.pending.take() {
                    if accepted {
                        self.submit(ctx, pending.label, pending.payload);
                    }
                }
            }
        }
        if self.installation_open {
            let mut open = true;
            let mut apply = false;
            egui::Window::new("Hub installation").open(&mut open).show(ctx, |ui| {
                let root_label = ui.label("Trusted Hub checkout (contains tools/hubctl.py)");
                ui.text_edit_singleline(&mut self.root_input).labelled_by(root_label.id);
                let python_label = ui.label("Python interpreter used by that Hub installation");
                ui.text_edit_singleline(&mut self.python_input).labelled_by(python_label.id);
                let config_label = ui.label("Config path (optional)");
                ui.text_edit_singleline(&mut self.config_input).labelled_by(config_label.id);
                ui.label("Only select installations and interpreters you trust. No credentials are saved by this GUI.");
                if ui.button("Apply for this session").clicked() { apply = true; }
            });
            if apply {
                self.install = Install {
                    root: PathBuf::from(&self.root_input),
                    python: PathBuf::from(&self.python_input),
                    config: (!self.config_input.trim().is_empty())
                        .then(|| PathBuf::from(&self.config_input)),
                };
                self.service = None;
                self.settings_draft = settings::Draft::default();
                self.reset_scope();
                self.operator_catalog.clear();
                self.repo.clear();
                self.last_probe = Instant::now() - Duration::from_secs(30);
                open = false;
            }
            self.installation_open = open;
        }
    }
}

impl eframe::App for Desktop {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.render(ctx);
    }
}
