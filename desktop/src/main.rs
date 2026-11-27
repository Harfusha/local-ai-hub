#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod records;
mod trace;
mod summary;

use eframe::egui;
use serde_json::{json, Value};
use std::{
    io::Write,
    path::PathBuf,
    process::{Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

const PAGES: &[(&str, &[&str])] = &[
    ("Overview", &["Overview", "Hardware", "GPU"]),
    ("Requests", &["Requests", "Active requests", "Async jobs", "Work orders", "Trace index", "Endpoint analytics"]),
    ("Tasks", &["Tasks", "Memory", "Incidents", "Vision review"]),
    ("Coordination", &["Plans", "Plan board", "Semaphores", "File leases", "Worktrees"]),
    ("Projects", &["Projects", "Project config"]),
    ("Commands", &["Commands", "Worktrees"]),
    ("Models & search", &["Models & search", "Search workspaces", "Model inventory", "Resident inventory", "Benchmark", "Telemetry report", "Laya"]),
    ("Service health", &["Runtime health", "Service health", "Diagnostics", "Audit"]),
    ("Settings", &["Settings", "Settings — activity mode", "Updates"]),
    ("Activity", &["Activity", "Agent event stream"]),
    ("Transfers", &["Search workspaces"]),
    ("Changes & commits", &["Changes & commits"]),
];
const MAINTENANCE: &[&str] = &[
    "Optimize databases", "Purge expired cache (7 days)", "Cleanup stale agent state",
    "Purge detailed traces", "Reset all statistics",
];
const MAX_ROWS: usize = 12_000;

#[derive(Clone)]
struct Install {
    root: PathBuf,
    python: PathBuf,
    config: Option<PathBuf>,
}
impl Install {
    fn from_env() -> Self {
        let root = std::env::var_os("LOCAL_AI_HUB_ROOT").map(PathBuf::from)
            .or_else(|| std::env::current_dir().ok()).unwrap_or_default();
        let venv = root.join(if cfg!(windows) { ".venv/Scripts/python.exe" } else { ".venv/bin/python" });
        let python = std::env::var_os("LOCAL_AI_DESKTOP_PYTHON").map(PathBuf::from)
            .unwrap_or_else(|| if venv.is_file() { venv } else { PathBuf::from(if cfg!(windows) { "python.exe" } else { "python3" }) });
        Self { root, python, config: std::env::var_os("LOCAL_AI_CONFIG").map(PathBuf::from) }
    }

    fn call(&self, request: &Value) -> Result<Value, String> {
        let root = self.root.canonicalize().map_err(|e| format!("Hub installation: {e}"))?;
        let adapter = root.join("tools/desktop.py");
        if !adapter.is_file() || !root.join("tools/hubctl.py").is_file() {
            return Err("Select a trusted Local AI Hub source checkout containing tools/desktop.py and tools/hubctl.py.".into());
        }
        let mut command = Command::new(&self.python);
        command.arg(&adapter).arg("--bridge").current_dir(root)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
        if let Some(config) = &self.config {
            command.arg("--config").arg(config);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let bytes = serde_json::to_vec(request).map_err(|e| e.to_string())?;
        if bytes.len() > 65_536 { return Err("Request too large".into()); }
        let mut child = command.spawn().map_err(|e| format!("Cannot launch Hub adapter: {e}"))?;
        let written = child.stdin.take().ok_or_else(|| "Missing adapter stdin".to_string())
            .and_then(|mut pipe| pipe.write_all(&bytes).map_err(|e| e.to_string()));
        if let Err(error) = written {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        let output = child.wait_with_output().map_err(|e| e.to_string())?;
        if !output.status.success() { return Err(format!("Adapter exited: {}", output.status)); }
        if output.stdout.len() > 8_100_000 { return Err("Adapter response exceeds limit".into()); }
        let envelope: Value = serde_json::from_slice(&output.stdout)
            .map_err(|_| "Invalid adapter response; check Python installation and Hub dependencies.".to_string())?;
        if envelope["ok"].as_bool() != Some(true) {
            return Err(envelope["error"].as_str().unwrap_or("Unknown adapter failure").to_owned());
        }
        Ok(envelope["result"].clone())
    }
}

#[derive(Clone)]
struct Row { path: String, value: String }
fn flatten(value: &Value, path: &str, depth: usize, rows: &mut Vec<Row>) {
    if rows.len() >= MAX_ROWS { return; }
    if depth >= 16 {
        rows.push(Row { path: path.into(), value: "[Nested data omitted]".into() });
        return;
    }
    match value {
        Value::Object(items) if !items.is_empty() => {
            for (key, item) in items {
                let next = if path.is_empty() { key.clone() } else { format!("{path}.{key}") };
                flatten(item, &next, depth + 1, rows);
                if rows.len() >= MAX_ROWS { break; }
            }
        }
        Value::Array(items) if !items.is_empty() => {
            for (index, item) in items.iter().enumerate() {
                flatten(item, &format!("{path}[{index}]"), depth + 1, rows);
                if rows.len() >= MAX_ROWS { break; }
            }
        }
        _ => {
            let value = value.as_str().map(str::to_owned).unwrap_or_else(|| value.to_string());
            rows.push(Row { path: path.into(), value });
        }
    }
}
fn request(op: &str, args: Value) -> Value { json!({"op": op, "args": args}) }
fn view_request(view: &str, root: &str, id: &str) -> Value {
    let op = match view {
        "Plans" => "plans", "Plan board" => "plan_board", "Semaphores" => "semaphores",
        "Worktrees" => "worktrees", "Project config" => "project_config", _ => "read",
    };
    request(op, json!({"view": view, "root": root, "id": id}))
}
struct Pending { label: String, payload: Value }
struct Completed { label: String, result: Result<Value, String>, probe: bool, live: bool }
struct Desktop {
    install: Install,
    page: usize,
    view: usize,
    repo: String,
    entity: String,
    reason: String,
    prompt: String,
    mode: String,
    feature: String,
    goal: String,
    criteria: String,
    memory_key: String,
    memory_value: String,
    memory_scope: String,
    memory_kind: String,
    memory_scope_id: String,
    task_scope: String,
    task_risk: String,
    incident_kind: String,
    incident_message: String,
    plan_title: String,
    revision: String,
    plan_task: String,
    description: String,
    archive_path: String,
    semaphore: String,
    capacity: i64,
    trace_cursor: i64,
    task_offset: i64,
    change_offset: i64,
    change_mode: String,
    change_base: String,
    change_head: String,
    change_expected: String,
    change_paths: String,
    change_hunks: String,
    change_revision: String,
    change_tree: String,
    change_message: String,
    change_mixed: bool,
    change_operation: String,
    change_annotation: String,
    change_sequence: String,
    change_verification: String,
    change_preview_digest: String,
    task_query: String,
    stream_id: String,
    event_cursor: i64,
    live_events: Vec<Value>,
    auto_live: bool,
    last_live: Instant,
    update_version: String,
    update_revision: String,
    hardware_profile: String,
    plan_status: String,
    vision_path: String,
    filter: String,
    rows: Vec<Row>,
    snapshot: Option<Value>,
    snapshot_view: String,
    raw_view: bool,
    reveal_trace: bool,
    record_detail: Option<Value>,
    visible: Vec<usize>,
    detail: Option<usize>,
    pending: Option<Pending>,
    busy: Option<String>,
    receiver: Option<mpsc::Receiver<Completed>>,
    status: String,
    service: Option<bool>,
    last_probe: Instant,
    auto_probe: bool,
    installation_open: bool,
    root_input: String,
    python_input: String,
    config_input: String,
}
impl Desktop {
    fn new() -> Self {
        let install = Install::from_env();
        Self {
            root_input: install.root.to_string_lossy().into_owned(),
            python_input: install.python.to_string_lossy().into_owned(),
            config_input: install.config.as_ref().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default(),
            install, page: 0, view: 0, repo: String::new(), entity: String::new(),
            reason: String::new(), prompt: String::new(), mode: "active".into(), feature: "status".into(), goal: String::new(), criteria: String::new(), memory_key: String::new(), memory_value: String::new(), memory_scope: "repository".into(), memory_kind: "fact".into(), memory_scope_id: String::new(), task_scope: "task".into(), task_risk: "normal".into(), incident_kind: String::new(), incident_message: String::new(), plan_title: String::new(), revision: String::new(), plan_task: String::new(), description: String::new(), archive_path: String::new(), semaphore: String::new(), capacity: 1, trace_cursor: 0, task_offset: 0, change_offset: 0, change_mode: "summary".into(), change_base: String::new(), change_head: "HEAD".into(), change_expected: String::new(), change_paths: String::new(), change_hunks: String::new(), change_revision: String::new(), change_tree: String::new(), change_message: String::new(), change_mixed: false, change_operation: String::new(), change_annotation: String::new(), change_sequence: String::new(), change_verification: String::new(), change_preview_digest: String::new(), task_query: String::new(), stream_id: String::new(), event_cursor: 0, live_events: Vec::new(), auto_live: false, last_live: Instant::now(), update_version: String::new(), update_revision: String::new(), hardware_profile: "auto".into(), plan_status: "planned".into(), vision_path: String::new(), filter: String::new(),
            rows: Vec::new(), snapshot: None, snapshot_view: String::new(), raw_view: false, reveal_trace: false, record_detail: None, visible: Vec::new(), detail: None, pending: None, busy: None,
            receiver: None, status: "Desktop ready. Check the Hub installation and service.".into(),
            service: None, last_probe: Instant::now() - Duration::from_secs(30),
            auto_probe: true, installation_open: false,
        }
    }
    fn current(&self) -> &'static str { PAGES[self.page].1[self.view] }
    fn submit(&mut self, ctx: &egui::Context, label: String, payload: Value) {
        if self.busy.is_some() { return; }
        let probe = payload["op"] == "probe";
        let live = payload["op"] == "event_stream";
        self.busy = Some(label.clone());
        let install = self.install.clone();
        let (tx, rx) = mpsc::channel();
        self.receiver = Some(rx);
        let ctx = ctx.clone();
        thread::spawn(move || {
            let result = install.call(&payload);
            let _ = tx.send(Completed { label, result, probe, live });
            ctx.request_repaint();
        });
    }
    fn confirm(&mut self, label: &str, payload: Value) {
        self.pending = Some(Pending { label: label.to_owned(), payload });
    }
    fn refilter(&mut self) {
        let needle = self.filter.to_lowercase();
        self.visible = self.rows.iter().enumerate().filter_map(|(i, row)| {
            (needle.is_empty() || row.path.to_lowercase().contains(&needle) ||
             row.value.to_lowercase().contains(&needle)).then_some(i)
        }).collect();
    }
    fn receive(&mut self) {
        let result = self.receiver.as_ref().map(|rx| rx.try_recv());
        match result {
            Some(Ok(done)) => {
                self.receiver = None;
                self.busy = None;
                match done.result {
                    Ok(value) if done.probe => {
                        self.service = value["online"].as_bool();
                        self.last_probe = Instant::now();
                    }
                    Err(error) if done.probe => {
                        self.service = None;
                        self.status = format!("Status check: {error}");
                        self.last_probe = Instant::now();
                    }
                    Ok(mut value) => {
                        if done.live {
                            self.last_live = Instant::now();
                            if value["controls"].as_array().is_some_and(|controls| controls.iter().any(|c|
                                matches!(c["kind"].as_str(), Some("cursor_reset" | "replay_cursor_reset")))) {
                                self.live_events.clear();
                            }
                            if let Some(events) = value["events"].as_array() {
                                records::merge_events(&mut self.live_events, events, 500);
                            }
                            value["events"] = Value::Array(self.live_events.clone());
                            value["desktop_event_buffer_limit"] = json!(500);
                        }
                        self.rows.clear();
                        self.reveal_trace = false;
                        self.detail = None;
                        self.record_detail = None;
                        if done.label == "Trace detail" || done.label == "Trace index" {
                            flatten(&trace::sanitize(&value), "", 0, &mut self.rows);
                        } else {
                            flatten(&value, "", 0, &mut self.rows);
                        }
                        if done.label == "Updates" {
                            self.update_version = value.pointer("/check/target_version").and_then(Value::as_str).unwrap_or("").into();
                            self.update_revision = value.pointer("/check/revision").and_then(Value::as_str).unwrap_or("").into();
                        }
                        if done.label == "Agent event stream" {
                            if let Some(cursor) = value["next_seq"].as_i64() { self.event_cursor = cursor; }
                        }
                        self.snapshot = Some(value);
                        self.snapshot_view = done.label.clone();
                        self.refilter();
                        self.status = format!("{}: response received{}", done.label,
                            if self.rows.len() >= MAX_ROWS { " (display capped)" } else { "" });
                        self.last_probe = Instant::now() - Duration::from_secs(30);
                    }
                    Err(error) => { if done.live { self.auto_live = false; self.last_live = Instant::now(); }
                        self.status = format!("{}: {error} (previous response, if any, is not fresh)", done.label); }
                }
            }
            Some(Err(mpsc::TryRecvError::Disconnected)) => {
                self.busy = None; self.receiver = None;
                self.status = "Operation worker disconnected; outcome unknown.".into();
            }
            _ => {}
        }
    }
    fn lifecycle(&mut self, ctx: &egui::Context, action: &str) {
        let data = request("lifecycle", json!({"action": action}));
        if action == "start" { self.submit(ctx, "Start Hub".into(), data); }
        else { self.confirm(&format!("{action} Hub (may interrupt active work)"), data); }
    }
    fn clear_response(&mut self) {
        self.rows.clear(); self.visible.clear(); self.detail = None; self.record_detail = None;
        self.snapshot = None; self.snapshot_view.clear(); self.reveal_trace = false;
        self.live_events.clear(); self.auto_live = false;
    }
    fn refresh(&mut self, ctx: &egui::Context) {
        let view = self.current();
        let data = match view {
            "Updates" => request("update_status", json!({})),
            "Tasks" => request("task_page", json!({"root": self.repo, "offset": self.task_offset, "query": self.task_query})),
            "Agent event stream" => request("event_page", json!({"root": self.repo, "stream": self.stream_id, "after": self.event_cursor})),
            "Changes & commits" => request("change_plan", json!({
                "root": self.repo, "mode": self.change_mode, "base": self.change_base,
                "head": self.change_head, "path": self.entity, "offset": self.change_offset,
                "expected_revision": self.change_expected
            })),
            "Vision review" => { self.status = "Choose an image and enter a prompt first.".into(); return; }
            _ => view_request(view, &self.repo, &self.entity),
        };
        self.submit(ctx, view.into(), data);
    }
    fn operations(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        match self.page {
            1 => {
                if matches!(self.current(), "Async jobs" | "Work orders") {
                    let async_job = self.current() == "Async jobs";
                    let op = if async_job { "async_job" } else { "work_order" };
                    ui.label(if async_job { "Async job ID" } else { "Work order ID" });
                    ui.text_edit_singleline(&mut self.entity);
                    if !async_job { ui.label("Answer for continuation"); ui.text_edit_multiline(&mut self.reason); }
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
                if self.current() == "Trace index" {
                    ui.small("Full inputs and outputs are captured only when detailed telemetry is enabled. Stored details appear as recorded; local access only; separate local retention policy.");
                    ui.horizontal_wrapped(|ui| {
                        ui.label("Trace ID");
                        ui.text_edit_singleline(&mut self.entity);
                        ui.label("After sequence");
                        ui.add(egui::DragValue::new(&mut self.trace_cursor).range(0..=i64::MAX));
                        if ui.button("Load trace events").clicked() {
                            self.submit(ctx, "Trace detail".into(), request("trace_detail",
                                json!({"id": self.entity, "after": self.trace_cursor})));
                        }
                    });
                }
            }
            2 => {
                if self.current() == "Vision review" {
                    ui.small("Raster images are not semantically indexed. Review is opt-in and sends the selected PNG/JPEG to the configured vision route.");
                    ui.label("Image file (PNG or JPEG, maximum 8 MiB)");
                    ui.text_edit_singleline(&mut self.vision_path);
                    ui.label("Review prompt");
                    ui.text_edit_multiline(&mut self.prompt);
                    if ui.button("Run vision review").clicked() {
                        self.confirm("Run vision review", request("vision_review",
                            json!({"file": self.vision_path, "prompt": self.prompt, "confirmed": true})));
                    }
                    return;
                }
                if self.view == 1 {
                    ui.horizontal_wrapped(|ui| {
                        egui::ComboBox::from_id_salt("memory_scope").selected_text(&self.memory_scope).show_ui(ui, |ui| {
                            for scope in ["global", "repository", "clone", "worktree", "branch", "task", "session"] {
                                ui.selectable_value(&mut self.memory_scope, scope.into(), scope);
                            }
                        });
                        egui::ComboBox::from_id_salt("memory_kind").selected_text(&self.memory_kind).show_ui(ui, |ui| {
                            for kind in ["fact", "decision", "convention", "gotcha", "hypothesis", "assumption", "playbook",
                                "capability_observation", "environment_capsule", "finding", "reusable_candidate", "contract_mapping",
                                "rejected_approach", "unknown", "validation"] {
                                ui.selectable_value(&mut self.memory_kind, kind.into(), kind);
                            }
                        });
                    });
                    if matches!(self.memory_scope.as_str(), "task" | "session") {
                        ui.label("Task or session identity");
                        ui.text_edit_singleline(&mut self.memory_scope_id);
                    }
                    ui.label("Memory key and value (text or JSON)");
                    ui.text_edit_singleline(&mut self.memory_key);
                    ui.text_edit_multiline(&mut self.memory_value);
                    ui.horizontal(|ui| {
                        for (title, op) in [("Record fact", "memory_record"), ("Delete fact", "memory_delete")] {
                            if ui.button(title).clicked() {
                                self.confirm(title, request(op, json!({"root": self.repo, "key": self.memory_key,
                                    "value": self.memory_value, "scope": self.memory_scope, "kind": self.memory_kind,
                                    "task_id": self.memory_scope_id, "session_id": self.memory_scope_id, "confirmed": true})));
                            }
                        }
                    });
                    return;
                }
                if self.view == 2 {
                    ui.label("Incident operation class and message");
                    ui.text_edit_singleline(&mut self.incident_kind);
                    ui.text_edit_multiline(&mut self.incident_message);
                    if ui.button("Record incident").clicked() {
                        self.confirm("Record incident", request("incident", json!({"root": self.repo,
                            "kind": self.incident_kind, "message": self.incident_message, "confirmed": true})));
                    }
                    return;
                }
                ui.horizontal_wrapped(|ui| {
                    ui.label("Server-side task search");
                    if ui.text_edit_singleline(&mut self.task_query).changed() { self.task_offset = 0; }
                    if ui.button("Search tasks").clicked() { self.task_offset = 0; self.refresh(ctx); }
                    if ui.add_enabled(self.task_offset >= 100, egui::Button::new("Previous 100")).clicked() {
                        self.task_offset = self.task_offset.saturating_sub(100); self.refresh(ctx);
                    }
                    let more = self.snapshot_view == "Tasks" && self.snapshot.as_ref()
                        .is_some_and(|v| v["has_more"].as_bool().unwrap_or_else(|| v["tasks"].as_array().is_some_and(|a| a.len() == 100)));
                    if ui.add_enabled(more, egui::Button::new("Next 100")).clicked() {
                        self.task_offset = (self.task_offset + 100).min(i32::MAX as i64); self.refresh(ctx);
                    }
                    ui.label(format!("Offset {}", self.task_offset));
                });
                ui.collapsing("Create task contract", |ui| {
                    ui.horizontal_wrapped(|ui| {
                        egui::ComboBox::from_id_salt("task_scope").selected_text(&self.task_scope).show_ui(ui, |ui| {
                            for scope in ["task", "session", "repository", "system"] { ui.selectable_value(&mut self.task_scope, scope.into(), scope); }
                        });
                        egui::ComboBox::from_id_salt("task_risk").selected_text(&self.task_risk).show_ui(ui, |ui| {
                            for risk in ["low", "normal", "high"] { ui.selectable_value(&mut self.task_risk, risk.into(), risk); }
                        });
                    });
                    ui.label("Goal");
                    ui.text_edit_multiline(&mut self.goal);
                    ui.label("Acceptance criteria (one per line)");
                    ui.text_edit_multiline(&mut self.criteria);
                    if ui.button("Create task").clicked() {
                        self.confirm("Create task", request("task_create", json!({"root": self.repo,
                            "goal": self.goal, "criteria": self.criteria, "scope": self.task_scope, "risk": self.task_risk, "confirmed": true})));
                    }
                });
                ui.label("Task ID and reason (repository required)");
                ui.text_edit_singleline(&mut self.entity);
                ui.text_edit_singleline(&mut self.reason);
                ui.horizontal_wrapped(|ui| {
                    for (title, action) in [("Inspect", "get"), ("Complete", "complete"), ("Fail", "fail")] {
                        if ui.button(title).clicked() {
                            let data = request("task", json!({"root": self.repo, "id": self.entity,
                                "reason": self.reason, "action": action, "confirmed": true}));
                            if action == "get" { self.submit(ctx, title.into(), data); }
                            else { self.confirm(title, data); }
                        }
                    }
                });
            }
            3 => {
                if self.current() == "Semaphores" {
                    ui.label("Semaphore name; owner ID (acquire) or lease ID (release)");
                    ui.text_edit_singleline(&mut self.semaphore);
                    ui.text_edit_singleline(&mut self.entity);
                    ui.add(egui::DragValue::new(&mut self.capacity).range(1..=100));
                    ui.horizontal(|ui| {
                        for (title, op) in [("Acquire", "semaphore_acquire"), ("Release", "semaphore_release")] {
                            if ui.button(title).clicked() {
                                self.confirm(title, request(op, json!({"name": self.semaphore,
                                    "id": self.entity, "capacity": self.capacity, "confirmed": true})));
                            }
                        }
                    });
                    return;
                }
                if self.current() == "File leases" {
                    ui.label("Lease ID");
                    ui.text_edit_singleline(&mut self.entity);
                    if ui.button("Release lease").clicked() {
                        self.confirm("Release file lease", request("lease_release", json!({"id": self.entity, "confirmed": true})));
                    }
                    return;
                }
                if self.current() == "Worktrees" {
                    self.worktrees(ui);
                    return;
                }
                ui.label("Plan ID, current file revision (required for edits)");
                ui.text_edit_singleline(&mut self.entity);
                ui.text_edit_singleline(&mut self.revision);
                ui.label("Plan/task title and description");
                ui.text_edit_singleline(&mut self.plan_title);
                ui.text_edit_multiline(&mut self.description);
                ui.label("Plan task ID (for task edit/delete)");
                ui.text_edit_singleline(&mut self.plan_task);
                ui.horizontal_wrapped(|ui| {
                    for (title, op) in [("Create plan", "plan_create"), ("Update plan", "plan_update"),
                        ("Add plan task", "plan_task_create"), ("Edit plan task", "plan_task_edit"), ("Delete plan task", "plan_task_delete")] {
                        if ui.button(title).clicked() {
                            self.confirm(title, request(op, json!({"root": self.repo, "id": self.entity,
                                "title": self.plan_title, "description": self.description, "revision": self.revision,
                                "task_id": self.plan_task, "confirmed": true})));
                        }
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    egui::ComboBox::from_id_salt("plan_move").selected_text(&self.plan_status).show_ui(ui, |ui| {
                        for status in ["planned", "ready", "in_progress", "blocked"] {
                            ui.selectable_value(&mut self.plan_status, status.into(), status);
                        }
                    });
                    if ui.button("Move task").clicked() {
                        self.confirm("Move plan task", request("plan_task_move", json!({
                            "root": self.repo, "id": self.entity, "task_id": self.plan_task,
                            "revision": self.revision, "status": self.plan_status, "confirmed": true})));
                    }
                });
                ui.collapsing("Session briefing", |ui| {
                    ui.label("Agent ID");
                    ui.text_edit_singleline(&mut self.reason);
                    if ui.button("Load briefing").clicked() {
                        self.submit(ctx, "Session briefing".into(), request("session_briefing",
                            json!({"id": self.reason, "confirmed": true})));
                    }
                });
            }
            4 => {
                ui.horizontal_wrapped(|ui| {
                    for (title, action) in [("Register", "register"), ("Reindex", "refresh"),
                        ("Pause", "pause"), ("Resume", "resume"), ("Unregister (keep data)", "unregister")] {
                        if ui.button(title).clicked() {
                            self.confirm(title, request("project", json!({"root": self.repo,
                                "action": action, "confirmed": true})));
                        }
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    for (title, action) in [("Pause all", "pause"), ("Resume all", "resume"), ("Cleanup missing", "cleanup_deleted")] {
                        if ui.button(title).clicked() {
                            self.confirm(title, request("global_preprocess", json!({"action": action, "confirmed": true})));
                        }
                    }
                });
            }
            5 => { if self.current() == "Worktrees" { self.worktrees(ui); } }
            6 => {
                ui.label("Compare automatic and high-complexity model routes (runs inference twice)");
                ui.text_edit_multiline(&mut self.prompt);
                if ui.button("Compare models").clicked() {
                    self.confirm("Run two model requests", request("compare", json!({"prompt": self.prompt})));
                }
            }
            7 => {
                ui.horizontal_wrapped(|ui| {
                    for action in MAINTENANCE {
                        if ui.button(*action).clicked() {
                            self.confirm(action, request("maintenance", json!({"action": action, "confirmed": true})));
                        }
                    }
                });
            }
            8 => {
                if self.current() == "Updates" {
                    ui.small("Managed installations only. The Hub checks the exact release candidate again before scheduling the update and restart.");
                    if ui.button("Check for updates").clicked() {
                        self.confirm("Updates", request("update_check", json!({"confirmed": true})));
                    }
                    ui.label(format!("Candidate: {} / {}", self.update_version, self.update_revision));
                    if ui.add_enabled(!self.update_version.is_empty() && self.update_revision.len() == 40,
                        egui::Button::new("Install reviewed candidate")).clicked() {
                        self.confirm("Install reviewed release and restart Hub", request("update_install", json!({
                            "version": self.update_version, "revision": self.update_revision, "confirmed": true})));
                    }
                    return;
                }
                ui.horizontal_wrapped(|ui| {
                    egui::ComboBox::from_id_salt("hardware_profile").selected_text(&self.hardware_profile).show_ui(ui, |ui| {
                        for profile in ["auto", "cpu", "integrated", "low", "balanced", "medium", "high", "max"] {
                            ui.selectable_value(&mut self.hardware_profile, profile.into(), profile);
                        }
                    });
                    if ui.button("Apply hardware profile").clicked() {
                        self.confirm("Apply hardware profile", request("setting", json!({
                            "key": "hardware.profile", "value": self.hardware_profile, "confirmed": true})));
                    }
                    for (title, key) in [("Preprocessing", "preprocessing.enabled"), ("Code intelligence", "code_intelligence.enabled"),
                        ("Serena", "code_intelligence.serena_enabled"), ("Work orchestrator", "features.work_orchestrator")] {
                        ui.menu_button(title, |ui| {
                            for (label, enabled) in [("Enable", true), ("Disable", false)] {
                                if ui.button(label).clicked() {
                                    self.confirm(&format!("{label} {title}"), request("setting",
                                        json!({"key": key, "value": enabled, "confirmed": true})));
                                    ui.close_menu();
                                }
                            }
                        });
                    }
                });
                ui.horizontal_wrapped(|ui| {
                    for (title, mode) in [("Telemetry off", "off"), ("Minimal telemetry", "minimal"), ("Detailed telemetry", "full")] {
                        if ui.button(title).clicked() {
                            self.confirm(&format!("{title} (may retain sensitive request content)"),
                                request("telemetry", json!({"mode": mode, "confirmed": true})));
                        }
                    }
                    egui::ComboBox::from_id_salt("feature").selected_text(&self.feature).show_ui(ui, |ui| {
                        for feature in ["status", "repo", "tasks", "rag", "commands", "coord", "artifacts", "subagents", "agent_os"] {
                            ui.selectable_value(&mut self.feature, feature.to_owned(), feature);
                        }
                    });
                    for (title, enabled) in [("Enable feature", true), ("Disable feature", false)] {
                        if ui.button(title).clicked() {
                            self.confirm(&format!("{title}: {}", self.feature), request("feature",
                                json!({"feature": self.feature, "enabled": enabled, "confirmed": true})));
                        }
                    }
                    if ui.button("Reset configuration overrides").clicked() {
                        self.confirm("Reset configuration overrides", request("config_reset", json!({"confirmed": true})));
                    }
                });
            }
            9 => {
                if self.current() == "Agent event stream" {
                    ui.label("Scoped agent event stream ID (repository root required)");
                    if ui.text_edit_singleline(&mut self.stream_id).changed() { self.event_cursor = 0; self.clear_response(); }
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
            10 => {
                ui.label("ZIP file path (export requires a new file; import requires repository root)");
                ui.text_edit_singleline(&mut self.archive_path);
                ui.horizontal_wrapped(|ui| {
                    for (title, op) in [("Export project", "bundle_export"), ("Import project", "bundle_import"),
                        ("Export encrypted diagnostics", "diagnostics_export")] {
                        if ui.button(title).clicked() {
                            self.confirm(title, request(op, json!({"file": self.archive_path,
                                "root": self.repo, "confirmed": true})));
                        }
                    }
                });
            }
            11 => {
                ui.label("Commit planning and explicitly approved local Git transactions.");
                ui.horizontal_wrapped(|ui| {
                    ui.label("View");
                    if egui::ComboBox::from_id_salt("change_mode").selected_text(&self.change_mode).show_ui(ui, |ui| {
                        let mut changed = false;
                        for mode in ["summary", "details", "semantic", "pr", "release"] {
                            changed |= ui.selectable_value(&mut self.change_mode, mode.into(), mode).changed();
                        }
                        changed
                    }).inner.unwrap_or(false) {
                        self.change_offset = 0; self.change_expected.clear(); self.clear_response();
                    }
                    ui.label("Base (optional)");
                    if ui.text_edit_singleline(&mut self.change_base).changed() {
                        self.change_offset = 0; self.change_expected.clear(); self.clear_response();
                    }
                    ui.label("Head");
                    if ui.text_edit_singleline(&mut self.change_head).changed() {
                        self.change_offset = 0; self.change_expected.clear(); self.clear_response();
                    }
                });
                ui.label("Optional repository-relative file (details)");
                if ui.text_edit_singleline(&mut self.entity).changed() {
                    self.change_offset = 0; self.change_expected.clear(); self.clear_response();
                }
                ui.horizontal_wrapped(|ui| {
                    if ui.button("Refresh plan").clicked() {
                        self.change_offset = 0; self.change_expected.clear(); self.refresh(ctx);
                    }
                    let revision = self.snapshot.as_ref().and_then(|v| v["observed_change_set_id"].as_str()).unwrap_or("").to_owned();
                    let next = self.snapshot.as_ref().and_then(|v| v["next_offset"].as_i64());
                    if ui.add_enabled(next.is_some() && !revision.is_empty(), egui::Button::new("Next groups")).clicked() {
                        if let Some(offset) = next {
                            self.change_offset = offset; self.change_expected = revision; self.refresh(ctx);
                        }
                    }
                });
                ui.small("For PR/release choose the explicit base. Semantic mode uses local advisory messages only. Refresh after any repository edit.");
                ui.separator();
                ui.collapsing("Stage and commit reviewed changes", |ui| {
                    ui.small("Local only. No push. Confirm the exact paths, revision and tree; a successful transaction is not proof of verification.");
                    if ui.button("Use observation identities from displayed result").clicked() {
                        if let Some(value) = &self.snapshot {
                            if let Some(revision) = value["observed_change_set_id"].as_str() { self.change_revision = revision.into(); }
                            self.change_tree = value["prospective_tree_oid"].as_str()
                                .or_else(|| value["prospective_index_tree_oid"].as_str())
                                .or_else(|| value.pointer("/git_snapshot_metadata/index_tree_oid").and_then(Value::as_str))
                                .unwrap_or("").into();
                        }
                    }
                    ui.label("Exact selected repository-relative paths (one per line)");
                    ui.text_edit_multiline(&mut self.change_paths);
                    ui.label("Optional exact unstaged hunk IDs (one per line)");
                    ui.text_edit_multiline(&mut self.change_hunks);
                    ui.label("Observed change-set ID");
                    ui.text_edit_singleline(&mut self.change_revision);
                    ui.label("Approved tree ID");
                    ui.text_edit_singleline(&mut self.change_tree);
                    ui.label("Commit message");
                    ui.text_edit_multiline(&mut self.change_message);
                    ui.checkbox(&mut self.change_mixed, "Explicitly leave remaining hunks unstaged");
                    let paths: Vec<&str> = self.change_paths.lines().filter(|p| !p.is_empty()).collect();
                    let hunks: Vec<&str> = self.change_hunks.lines().filter(|p| !p.is_empty()).collect();
                    let ready = !paths.is_empty() && self.change_revision.len() == 64;
                    let tree_ready = self.change_tree.len() == 40 || self.change_tree.len() == 64;
                    let payload = |action: &str, confirmed: bool| request("change_transaction", json!({
                        "action": action, "root": self.repo, "paths": paths, "hunk_ids": hunks,
                        "expected_revision": self.change_revision, "expected_tree": self.change_tree,
                        "message": self.change_message, "allow_mixed_staged": self.change_mixed, "confirmed": confirmed
                    }));
                    let preview = payload("stage-preview", false);
                    let stage = payload("stage-apply", true);
                    let commit = payload("commit-staged", true);
                    ui.horizontal_wrapped(|ui| {
                        if ui.add_enabled(ready, egui::Button::new("Preview staging")).clicked() {
                            self.submit(ctx, "Stage preview".into(), preview);
                        }
                        if ui.add_enabled(ready && tree_ready, egui::Button::new("Apply reviewed staging")).clicked() {
                            self.confirm("Apply reviewed staging", stage);
                        }
                        if ui.add_enabled(ready && tree_ready && !self.change_message.trim().is_empty(), egui::Button::new("Commit staged tree")).clicked() {
                            self.confirm("Commit staged tree (no push)", commit);
                        }
                    });
                    ui.small("After staging, refresh the plan and use the new observed revision and staged tree ID before committing. For multiple staged commits, use the sequence panel below.");
                });
                ui.collapsing("Review and assign observed atoms", |ui| {
                    ui.small("Local declarations only; not authenticated ownership or verification. Use the observed revision above.");
                    ui.label("Annotation JSON: atom_ids, actor, task_id, status");
                    ui.text_edit_multiline(&mut self.change_annotation);
                    let record = serde_json::from_str::<Value>(&self.change_annotation).ok().filter(Value::is_object);
                    if ui.add_enabled(record.is_some() && self.change_revision.len() == 64, egui::Button::new("Record declaration")).clicked() {
                        if let Some(record) = record {
                            self.confirm("Record local review declaration", request("change_transaction", json!({
                                "action": "annotate", "root": self.repo, "expected_revision": self.change_revision,
                                "record": record, "confirmed": true
                            })));
                        }
                    }
                });
                ui.collapsing("Ordered staged commit sequence", |ui| {
                    ui.small("Use the exact staged paths, revision and tree above. Preview first. Inspect receipt status or explicitly run configured git_commit policy checks. For other local checks use hubctl sequence-verify. Checks run as your OS user, not in a security sandbox.");
                    if ui.button("Suggest sequence from staged changes").clicked() {
                        self.submit(ctx, "Sequence suggestion".into(), request("change_transaction", json!({
                            "action": "sequence-suggest", "root": self.repo
                        })));
                    }
                    if ui.button("Load displayed suggestion into editor").clicked() {
                        if let Some(value) = self.snapshot.as_ref() {
                            if let (Some(sequence), Some(paths), Some(revision), Some(tree)) = (
                                value["sequence"].as_array(), value["selected_paths"].as_array(),
                                value["observed_change_set_id"].as_str(), value["tree_oid"].as_str()
                            ) {
                                if let Ok(record) = serde_json::to_string_pretty(sequence) {
                                    self.change_sequence = record;
                                    self.change_paths = paths.iter().filter_map(Value::as_str).collect::<Vec<_>>().join("\n");
                                    self.change_revision = revision.into();
                                    self.change_tree = tree.into();
                                    self.change_preview_digest.clear();
                                }
                            }
                        }
                    }
                    ui.label("Ordered sequence JSON (array of paths and message objects)");
                    if ui.text_edit_multiline(&mut self.change_sequence).changed() {
                        self.change_preview_digest.clear();
                    }
                    ui.label("Reviewed preview digest");
                    ui.text_edit_singleline(&mut self.change_preview_digest);
                    if ui.button("Use digest from displayed sequence result").clicked() {
                        if let Some(digest) = self.snapshot.as_ref().and_then(|v| v["preview_digest"].as_str()) {
                            self.change_preview_digest = digest.into();
                        }
                    }
                    if ui.button("Resolve configured verification policy").clicked() {
                        self.submit(ctx, "Project verification policy".into(), request("change_transaction", json!({
                            "action": "verification-policy", "root": self.repo
                        })));
                    }
                    if ui.button("Load displayed policy manifest template").clicked() {
                        if let Some(value) = self.snapshot.as_ref().and_then(|v| v.get("verification_manifest")) {
                            if let Ok(record) = serde_json::to_string_pretty(value) {
                                self.change_verification = record;
                            }
                        }
                    }
                    ui.small("Supply the actual environment capsule SHA-256; the template never generates or certifies it.");
                    ui.label("Verification manifest JSON (exact executable argv and environment digest)");
                    ui.text_edit_multiline(&mut self.change_verification);
                    let sequence = serde_json::from_str::<Value>(&self.change_sequence).ok().filter(Value::is_array);
                    let manifest = serde_json::from_str::<Value>(&self.change_verification).ok().filter(|value| {
                        value.is_object() && value["environment_id"].as_str().is_some_and(|id| id.len() == 64 && id.bytes().all(|b| b.is_ascii_digit() || (b\x27a\x27..=b\x27f\x27).contains(&b)))
                            && value["commands"].is_array()
                    });
                    let paths: Vec<&str> = self.change_paths.lines().filter(|p| !p.is_empty()).collect();
                    let ready = !paths.is_empty() && self.change_revision.len() == 64
                        && (self.change_tree.len() == 40 || self.change_tree.len() == 64) && sequence.is_some();
                    let common = json!({
                        "root": self.repo, "paths": paths, "expected_revision": self.change_revision,
                        "expected_tree": self.change_tree, "sequence": sequence,
                        "allow_mixed_staged": self.change_mixed
                    });
                    if ui.add_enabled(ready, egui::Button::new("Preview ordered commits")).clicked() {
                        let mut args = common.clone();
                        args["action"] = json!("sequence-preview");
                        self.submit(ctx, "Sequence preview".into(), request("change_transaction", args));
                    }
                    let verified_input = ready && manifest.is_some() && self.change_preview_digest.len() == 64;
                    if ui.add_enabled(verified_input, egui::Button::new("Inspect exact-tree receipt status")).clicked() {
                        let mut args = common.clone();
                        args["action"] = json!("sequence-status");
                        args["verification_manifest"] = json!(manifest.clone());
                        args["preview_digest"] = json!(self.change_preview_digest);
                        self.submit(ctx, "Verification receipt status".into(), request("change_transaction", args));
                    }
                    if ui.add_enabled(verified_input, egui::Button::new("Run configured project checks")).clicked() {
                        let mut args = common.clone();
                        args["action"] = json!("sequence-verify-policy");
                        args["verification_manifest"] = json!(manifest.clone());
                        args["preview_digest"] = json!(self.change_preview_digest);
                        args["confirmed"] = json!(true);
                        self.confirm("Run reviewed project policy commands as local user (not sandboxed)", request("change_transaction", args));
                    }
                    if ui.add_enabled(verified_input,
                        egui::Button::new("Publish verified sequence (no push)")).clicked() {
                        let mut args = common;
                        args["action"] = json!("sequence-apply");
                        args["verification_manifest"] = json!(manifest);
                        args["preview_digest"] = json!(self.change_preview_digest);
                        args["confirmed"] = json!(true);
                        self.confirm("Publish exact verified commit sequence (no push)", request("change_transaction", args));
                    }
                });
                ui.collapsing("Commit recovery", |ui| {
                    if ui.button("List recent local operations").clicked() {
                        self.submit(ctx, "Commit operations".into(), request("change_transaction",
                            json!({"action":"commit-list", "root": self.repo})));
                    }
                    ui.label("Operation ID");
                    ui.text_edit_singleline(&mut self.change_operation);
                    if ui.button("Inspect operation (no retry)").clicked() {
                        self.submit(ctx, "Commit inspection".into(), request("change_transaction",
                            json!({"action":"commit-inspect", "root": self.repo, "operation_id": self.change_operation})));
                    }
                });
            }
            _ => {}
        }
    }
    fn worktrees(&mut self, ui: &mut egui::Ui) {
        ui.label("Worktree path (release); repository root above");
        ui.text_edit_singleline(&mut self.entity);
        ui.horizontal(|ui| {
            for (title, op) in [("Prune stale worktrees", "worktree_prune"), ("Release worktree", "worktree_release")] {
                if ui.button(title).clicked() {
                    self.confirm(title, request(op, json!({"root": self.repo, "id": self.entity, "confirmed": true})));
                }
            }
        });
    }
}
impl eframe::App for Desktop {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.receive();
        // Only wake for health checks while focused, never continuously repaint an idle window.
        let focused = ctx.input(|i| i.focused);
        if self.auto_live && self.current() == "Agent event stream" && focused && self.busy.is_none()
            && self.pending.is_none() && !self.installation_open {
            if self.last_live.elapsed() >= Duration::from_secs(1) {
                self.submit(ctx, "Agent event stream".into(), request("event_stream",
                    json!({"root": self.repo, "stream": self.stream_id, "after": self.event_cursor})));
            } else {
                ctx.request_repaint_after(Duration::from_secs(1).saturating_sub(self.last_live.elapsed()));
            }
        }
        if self.auto_probe && focused && self.busy.is_none() && self.pending.is_none() && !self.installation_open {
            if self.last_probe.elapsed() >= Duration::from_secs(30) {
                self.last_probe = Instant::now();
                self.submit(ctx, "Check service".into(), request("probe", json!({})));
            } else {
                ctx.request_repaint_after(Duration::from_secs(30).saturating_sub(self.last_probe.elapsed()));
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
                ui.label(match self.service { Some(true) => "Service online", Some(false) => "Service unreachable — Start Hub", None => "Service status unknown" });
                ui.add_enabled_ui(self.busy.is_none() && self.pending.is_none(), |ui| {
                    for (title, action) in [("Start Hub", "start"), ("Stop", "stop"), ("Restart", "restart")] {
                        if ui.button(title).clicked() { self.lifecycle(ctx, action); }
                    }
                    if ui.button("Check status").clicked() { self.submit(ctx, "Check service".into(), request("probe", json!({}))); }
                    egui::ComboBox::from_id_salt("mode").selected_text(&self.mode).show_ui(ui, |ui| {
                        for mode in ["active", "gaming", "maintenance", "preprocessing"] {
                            ui.selectable_value(&mut self.mode, mode.to_owned(), mode);
                        }
                    });
                    if ui.button("Apply mode").clicked() {
                        self.confirm("Change activity mode", request("mode", json!({"mode": self.mode})));
                    }
                    if ui.button("Installation").clicked() { self.installation_open = true; }
                });
            });
            ui.horizontal_wrapped(|ui| {
                ui.checkbox(&mut self.auto_probe, "Check status automatically while focused");
                if self.current() == "Agent event stream" { ui.checkbox(&mut self.auto_live, "Follow live SSE while focused"); }
                ui.label("Repository root");
                if ui.add_enabled(self.busy.is_none(), egui::TextEdit::singleline(&mut self.repo).desired_width(400.0)).changed() { self.clear_response(); self.entity.clear(); self.revision.clear(); self.task_offset = 0; self.change_offset = 0; self.change_expected.clear(); self.event_cursor = 0; self.update_version.clear(); self.update_revision.clear(); }
            });
        });
        egui::TopBottomPanel::bottom("status").show(ctx, |ui| {
            if let Some(label) = &self.busy { ui.horizontal(|ui| { ui.spinner(); ui.label(format!("{label} — running")); }); }
            else { ui.label(&self.status); }
        });
        egui::SidePanel::left("navigation").resizable(false).default_width(170.0).show(ctx, |ui| {
            ui.add_enabled_ui(self.busy.is_none() && self.pending.is_none(), |ui| {
                for (index, (name, _)) in PAGES.iter().enumerate() {
                    if ui.selectable_label(self.page == index, *name).clicked() && self.page != index {
                        self.page = index; self.view = 0; self.clear_response(); self.entity.clear(); self.revision.clear(); self.change_offset = 0; self.change_expected.clear();
                        self.filter.clear();
                    }
                }
            });
        });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading(PAGES[self.page].0);
            ui.add_enabled_ui(self.busy.is_none() && self.pending.is_none(), |ui| {
                ui.horizontal_wrapped(|ui| {
                    for (index, view) in PAGES[self.page].1.iter().enumerate() {
                        if ui.selectable_label(self.view == index, *view).clicked() && self.view != index {
                            self.view = index; self.clear_response(); self.entity.clear(); self.revision.clear();
                        }
                    }
                    if ui.button("Load / refresh").clicked() { self.refresh(ctx); }
                });
                self.operations(ui, ctx);
            });
            ui.separator();
            ui.horizontal(|ui| {
                ui.label("Search response");
                if ui.text_edit_singleline(&mut self.filter).changed() { self.refilter(); }
                ui.label(format!("{} fields", self.visible.len()));
                ui.checkbox(&mut self.raw_view, "Raw fields");
            });
            if self.rows.is_empty() { ui.label("Load this view to inspect data. No hidden screen is polled."); }
            if self.snapshot_view == "Trace detail" && !self.raw_view {
                if let Some(projection) = self.snapshot.as_ref().and_then(trace::trace) {
                    ui.heading("Retained trace");
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
                                                if ui.button(title.chars().take(80).collect::<String>()).clicked() { selected = Some(card.clone()); }
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
                                if let Some(id) = card["task_id"].as_str() { self.plan_task = id.to_owned(); }
                                if let Some(revision) = card["plan_file_revision"].as_str() { self.revision = revision.to_owned(); }
                                if let Some(id) = card["plan_id"].as_str() { self.entity = id.to_owned(); }
                                if let Some(title) = card["title"].as_str() { self.plan_title = title.to_owned(); }
                                self.record_detail = Some(card);
                            }
                            return;
                        }
                    }
                    if self.current() == "Search workspaces" { ui.label("Read-only inventory. Unknown status is not proof of a missing index. No automatic removal."); }
                    if self.current() == "Endpoint analytics" { ui.label("Endpoint and MCP calls do not prove model execution. Select an explicit repository to scope counts."); }
                    if let Some(table) = records::records(self.current(), snapshot) {
                        let needle = self.filter.to_lowercase();
                        let filtered: Vec<&Value> = table.values.into_iter().filter(|item|
                            needle.is_empty() || item.to_string().to_lowercase().contains(&needle)).collect();
                        ui.label(format!("{} matching records (bounded response)", filtered.len()));
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
                                            let value = if self.current() == "Trace index" { records::display(&trace::sanitize(&item[*field])) } else { records::display(&item[*field]) };
                                            let display: String = value.chars().take(32).collect();
                                            if col == 0 {
                                                if ui.add_sized([155.0, height], egui::Button::new(display)).clicked() { selected = Some(item.clone()); }
                                            } else {
                                                ui.add_sized([155.0, height], egui::Label::new(display));
                                            }
                                        }
                                    });
                                }
                            });
                        });
                        if let Some(item) = selected {
                            if let Some(id) = item["trace_id"].as_str().or_else(|| item["task_id"].as_str()).or_else(|| item["job_id"].as_str()).or_else(|| item["work_id"].as_str()).or_else(|| item["id"].as_str()) { self.entity = id.to_owned(); }
                            if self.current() == "Plans" {
                                if let Some(revision) = item["file_revision"].as_str() { self.revision = revision.to_owned(); }
                                if let Some(title) = item["title"].as_str() { self.plan_title = title.to_owned(); }
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
        if let Some(record) = &self.record_detail {
            let mut open = true;
            egui::Window::new("Record detail").open(&mut open).show(ctx, |ui| {
                let text = serde_json::to_string_pretty(record).unwrap_or_default();
                if ui.button("Copy record").clicked() { ui.ctx().copy_text(text.clone()); }
                egui::ScrollArea::both().max_height(500.0).show(ui, |ui| { ui.label(text); });
            });
            if !open { self.record_detail = None; }
        }
        if let Some(index) = self.detail {
            let mut open = true;
            if let Some(row) = self.rows.get(index) {
                egui::Window::new("Field detail").open(&mut open).resizable(true).show(ctx, |ui| {
                    ui.label(&row.path);
                    if ui.button("Copy value").clicked() { ui.ctx().copy_text(row.value.clone()); }
                    egui::ScrollArea::both().show(ui, |ui| { ui.label(&row.value); });
                });
            }
            if !open { self.detail = None; }
        }
        if self.pending.is_some() {
            let mut decision = None;
            egui::Window::new("Confirm operation").collapsible(false).resizable(true).default_width(560.0).show(ctx, |ui| {
                ui.label(&self.pending.as_ref().unwrap().label);
                ui.label("This operation may change Hub state. Verify the selected repository and target.");
                let args = &self.pending.as_ref().unwrap().payload["args"];
                for key in ["root", "id", "task_id", "action", "file", "revision", "version", "key", "status", "scope", "kind", "expected_revision", "expected_tree", "preview_digest"] {
                    if let Some(value) = args[key].as_str() { ui.label(format!("{key}: {value}")); }
                }
                if self.pending.as_ref().unwrap().payload["op"].as_str() == Some("change_transaction") {
                    ui.separator();
                    ui.label("Exact reviewed operation (including paths, messages and selected hunks):");
                    egui::ScrollArea::vertical().max_height(320.0).show(ui, |ui| {
                        for key in ["paths", "hunk_ids", "message", "sequence", "record", "allow_mixed_staged", "verification_manifest"] {
                            if let Some(value) = args.get(key) {
                                ui.label(key);
                                let display = serde_json::to_string_pretty(value).unwrap_or_default();
                                ui.monospace(display);
                            }
                        }
                    });
                }
                ui.horizontal(|ui| {
                    if ui.button("Cancel").clicked() { decision = Some(false); }
                    if ui.button("Confirm").clicked() { decision = Some(true); }
                });
            });
            if let Some(accepted) = decision {
                if let Some(pending) = self.pending.take() {
                    if accepted { self.submit(ctx, pending.label, pending.payload); }
                }
            }
        }
        if self.installation_open {
            let mut open = true;
            let mut apply = false;
            egui::Window::new("Hub installation").open(&mut open).show(ctx, |ui| {
                ui.label("Trusted Hub checkout (contains tools/hubctl.py)");
                ui.text_edit_singleline(&mut self.root_input);
                ui.label("Python interpreter used by that Hub installation");
                ui.text_edit_singleline(&mut self.python_input);
                ui.label("Config path (optional)");
                ui.text_edit_singleline(&mut self.config_input);
                ui.label("Only select installations and interpreters you trust. No credentials are saved by this GUI.");
                if ui.button("Apply for this session").clicked() { apply = true; }
            });
            if apply {
                self.install = Install { root: PathBuf::from(&self.root_input),
                    python: PathBuf::from(&self.python_input),
                    config: (!self.config_input.trim().is_empty()).then(|| PathBuf::from(&self.config_input)) };
                self.service = None; self.clear_response(); self.entity.clear(); self.revision.clear();
                self.last_probe = Instant::now() - Duration::from_secs(30);
                open = false;
            }
            self.installation_open = open;
        }
    }
}

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([1200.0, 760.0]).with_min_inner_size([800.0, 500.0]),
        renderer: eframe::Renderer::Glow,
        ..Default::default()
    };
    eframe::run_native("Local AI Hub", options, Box::new(|_cc| Ok(Box::new(Desktop::new()))))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scoped_views_are_named_operations() {
        assert_eq!(view_request("Plan board", "/repo", "plan_1"),
            json!({"op":"plan_board","args":{"view":"Plan board","root":"/repo","id":"plan_1"}}));
    }
    #[test]
    fn rows_are_bounded() {
        let mut rows = Vec::new();
        flatten(&json!(vec![1; MAX_ROWS + 10]), "", 0, &mut rows);
        assert_eq!(rows.len(), MAX_ROWS);
    }
    #[test]
    fn response_paths_are_stable() {
        let mut rows = Vec::new();
        flatten(&json!({"tasks":[{"id":"x"}]}), "", 0, &mut rows);
        assert_eq!(rows[0].path, "tasks[0].id");
        assert_eq!(rows[0].value, "x");
    }
}
