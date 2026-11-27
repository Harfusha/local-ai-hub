#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod records;
mod trace;
mod summary;
mod settings;

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
    ("Requests", &["Requests", "Active requests", "Scheduler queue", "Scheduler running", "Async jobs", "Work orders", "Trace index", "Endpoint analytics", "Telemetry history"]),
    ("Tasks", &["Tasks", "Memory", "Incidents", "Vision review", "Run history"]),
    ("Coordination", &["Plans", "Plan board", "Semaphores", "File leases", "Worktrees", "Session briefing"]),
    ("Projects", &["Projects", "Project config"]),
    ("Commands", &["Commands", "Worktrees"]),
    ("Models & search", &["Models & search", "Search workspaces", "Model inventory", "Resident inventory", "Benchmark", "Telemetry report", "Laya"]),
    ("Service health", &["Runtime health", "Service health", "Process sessions", "Recent errors", "Recovery journal", "Diagnostics", "Audit"]),
    ("Settings", &["Settings", "Settings — activity mode", "Updates", "Operator tools"]),
    ("Activity", &["Activity", "Agent event stream"]),
    ("Transfers", &["Project and diagnostics archives"]),
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
// Only follow an explicit trace identifier returned by the server. A request
// ID, task ID or job ID is not a trace ID and must never be guessed.
fn filtered_log_lines<'a>(response: &'a Value, filter: &str) -> Option<Vec<&'a str>> {
    let lines = response.get("lines")?.as_array()?;
    let needle = filter.trim().to_lowercase();
    Some(lines.iter().filter_map(Value::as_str)
        .filter(|line| needle.is_empty() || line.to_lowercase().contains(&needle)).collect())
}
fn linked_trace(record: &Value) -> Option<&str> {
    record.get("trace_id").and_then(Value::as_str).filter(|id|
        !id.is_empty() && id.len() <= 200 &&
        id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-'))
}
// Plan edits are based on the complete server document, not the potentially
// truncated Kanban projection. An omitted field is never silently overwritten.
struct PlanDraft {
    plan_id: String,
    task_id: String,
    revision: String,
    original: serde_json::Map<String, Value>,
    edited: serde_json::Map<String, Value>,
}
impl PlanDraft {
    fn from_response(response: &Value, plan_id: &str, task_id: &str) -> Option<Self> {
        if response["success"] != true || response["plan"]["id"].as_str()? != plan_id {
            return None;
        }
        let revision = response["file_revision"].as_str()?.to_owned();
        if revision.is_empty() { return None; }
        let plan = &response["plan"];
        let source = if task_id.is_empty() { plan } else { plan.get("tasks")?.get(task_id)? };
        let mut original = serde_json::Map::new();
        for key in ["title", "description"] {
            original.insert(key.into(), json!(source.get(key)?.as_str()?));
        }
        if !task_id.is_empty() {
            for key in ["next_action", "accountable_role", "blocker"] {
                if let Some(value) = source.get(key).and_then(Value::as_str) {
                    original.insert(key.into(), json!(value));
                } else if source.get(key).is_none_or(Value::is_null) {
                    original.insert(key.into(), json!(""));
                }
            }
            // Multiline criteria cannot round-trip through the one-per-line editor.
            // Keep such criteria untouched instead of flattening them.
            if let Some(items) = source.get("acceptance_criteria").and_then(Value::as_array) {
                let lines: Option<Vec<&str>> = items.iter().map(|item| {
                    item.as_str().filter(|line| !line.contains(['\n', '\r']) && line.trim() == *line && !line.is_empty())
                }).collect();
                if let Some(lines) = lines { original.insert("criteria".into(), json!(lines.join("\n"))); }
            }
        }
        Some(Self { plan_id: plan_id.into(), task_id: task_id.into(), revision,
                    edited: original.clone(), original })
    }
    fn matches(&self, plan_id: &str, task_id: &str, revision: &str) -> bool {
        self.plan_id == plan_id && self.task_id == task_id && self.revision == revision
    }
    fn patch(&self) -> serde_json::Map<String, Value> {
        self.edited.iter().filter(|(key, value)| self.original.get(*key) != Some(*value))
            .map(|(key, value)| (key.clone(), value.clone())).collect()
    }
    fn render(&mut self, ui: &mut egui::Ui) {
        for (key, label, multiline) in [
            ("title", "Title", false), ("description", "Description", true),
            ("criteria", "Acceptance criteria (one per line)", true),
            ("next_action", "Next action", true), ("accountable_role", "Accountable role", false),
            ("blocker", "Blocker", true),
        ] {
            if let Some(Value::String(text)) = self.edited.get_mut(key) {
                ui.label(label);
                if multiline { ui.text_edit_multiline(text); }
                else { ui.text_edit_singleline(text); }
            } else if !self.task_id.is_empty() && key == "criteria" {
                ui.small("Criteria unavailable for lossless line editing; preserved unchanged.");
            }
        }
    }
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
    settings_draft: settings::Draft,
    metrics_period: String,
    log_lines: i64,
    goal: String,
    criteria: String,
    memory_key: String,
    memory_value: String,
    memory_scope: String,
    memory_kind: String,
    memory_scope_id: String,
    memory_record_id: String,
    memory_query: String,
    lease_owner: String,
    task_scope: String,
    task_risk: String,
    incident_kind: String,
    incident_message: String,
    plan_title: String,
    revision: String,
    plan_task: String,
    plan_draft: Option<PlanDraft>,
    description: String,
    archive_path: String,
    semaphore: String,
    capacity: i64,
    trace_cursor: i64,
    trace_offset: i64,
    trace_kind: String,
    trace_state: String,
    trace_action: String,
    trace_min_ms: i64,
    request_status: String,
    request_action: String,
    request_sort: String,
    request_desc: bool,
    trace_before: i64,
    trace_content_field: String,
    trace_content_offset: i64,
    task_offset: i64,
    task_query: String,
    task_target: String,
    history_cursor: i64,
    telemetry_before: i64,
    telemetry_limit: i64,
    endpoint_scope: String,
    endpoint_sort: String,
    endpoint_desc: bool,
    stream_id: String,
    event_cursor: i64,
    live_events: Vec<Value>,
    auto_live: bool,
    last_live: Instant,
    update_version: String,
    update_revision: String,
    plan_status: String,
    vision_path: String,
    filter: String,
    operator_catalog: Vec<Value>,
    operator_name: String,
    operator_fields: serde_json::Map<String, Value>,
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
            reason: String::new(), prompt: String::new(), mode: "active".into(), settings_draft: settings::Draft::default(), metrics_period: "process".into(), log_lines: 250, goal: String::new(), criteria: String::new(), memory_key: String::new(), memory_value: String::new(), memory_scope: "repository".into(), memory_kind: "fact".into(), memory_scope_id: String::new(), memory_record_id: String::new(), memory_query: String::new(), lease_owner: String::new(), task_scope: "task".into(), task_risk: "normal".into(), incident_kind: String::new(), incident_message: String::new(), plan_title: String::new(), revision: String::new(), plan_task: String::new(), plan_draft: None, description: String::new(), archive_path: String::new(), semaphore: String::new(), capacity: 1, trace_cursor: 0, trace_offset: 0, trace_kind: String::new(), trace_state: String::new(), trace_action: String::new(), trace_min_ms: 0, request_status: "all".into(), request_action: String::new(), request_sort: "created_at".into(), request_desc: true, trace_before: 0, trace_content_field: "request".into(), trace_content_offset: 0, task_offset: 0, task_query: String::new(), task_target: "active".into(), history_cursor: 0, telemetry_before: 0, telemetry_limit: 100, endpoint_scope: "all".into(), endpoint_sort: "calls".into(), endpoint_desc: true, stream_id: String::new(), event_cursor: 0, live_events: Vec::new(), auto_live: false, last_live: Instant::now(), update_version: String::new(), update_revision: String::new(), plan_status: "planned".into(), vision_path: String::new(), filter: String::new(), operator_catalog: Vec::new(), operator_name: String::new(), operator_fields: serde_json::Map::new(),
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
                        if done.label == "Plan detail" {
                            self.plan_draft = PlanDraft::from_response(&value, &self.entity, &self.plan_task);
                            self.revision = if value["plan"]["id"].as_str() == Some(self.entity.as_str()) && value["success"] == true {
                                value["file_revision"].as_str().unwrap_or("").to_owned()
                            } else { String::new() };
                        }
                        if matches!(done.label.as_str(), "Update plan" | "Edit plan task" | "Add plan task" | "Delete plan task" | "Move plan task") {
                            self.plan_draft = None;
                            self.revision.clear();
                        }
                        if done.label == "Settings" { self.settings_draft = settings::Draft::from_response(&value); }
                        if done.label == "Save settings" || done.label == "Reset configuration overrides" { self.settings_draft = settings::Draft::default(); }
                        if matches!(done.label.as_str(), "Run events" | "Trace index") { value = trace::sanitize(&value); }
                        if done.label == "Trace content" {
                            // Do not flatten arbitrary stored text into searchable or copyable rows.
                            self.rows.clear();
                        } else if done.label == "Trace detail" || done.label == "Trace index" || done.label == "Trace metrics" {
                            flatten(&trace::sanitize(&value), "", 0, &mut self.rows);
                        } else {
                            flatten(&value, "", 0, &mut self.rows);
                        }
                        if done.label == "Operator catalog" {
                            self.operator_catalog = value["operations"].as_array().cloned().unwrap_or_default();
                            self.operator_name.clear();
                            self.operator_fields.clear();
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
                        self.status = format!("{}: {}{}", done.label, if self.snapshot.as_ref().is_some_and(|v| v["success"] == false) { "operation failed — inspect details" } else { "response received" },
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
        let data = request("lifecycle", json!({"action": action, "confirmed": true}));
        if action == "start" { self.submit(ctx, "Start Hub".into(), data); }
        else { self.confirm(&format!("{action} Hub (may interrupt active work)"), data); }
    }
    fn clear_response(&mut self) {
        self.rows.clear(); self.visible.clear(); self.detail = None; self.record_detail = None;
        self.snapshot = None; self.snapshot_view.clear(); self.reveal_trace = false;
        self.live_events.clear(); self.auto_live = false;
    }
    // A root or installation switch invalidates all scope-bound selection and
    // continuation state, not just the visible rows.
    fn reset_scope(&mut self) {
        self.clear_response();
        self.pending = None;
        self.entity.clear();
        self.revision.clear();
        self.plan_task.clear();
        self.plan_draft = None;
        self.plan_title.clear();
        self.description.clear();
        self.memory_scope_id.clear();
        self.memory_record_id.clear();
        self.memory_key.clear();
        self.memory_value.clear();
        self.memory_query.clear();
        self.lease_owner.clear();
        self.stream_id.clear();
        self.task_offset = 0;
        self.task_query.clear();
        self.history_cursor = 0;
        self.telemetry_before = 0;
        self.event_cursor = 0;
        self.trace_cursor = 0;
        self.trace_before = 0;
        self.trace_offset = 0;
        self.trace_content_offset = 0;
        self.update_version.clear();
        self.update_revision.clear();
        self.operator_name.clear();
        self.operator_fields.clear();
        self.filter.clear();
    }
    fn open_project(&mut self, ctx: &egui::Context, root: String) {
        if !self.can_edit_context() { return; }
        self.reset_scope();
        self.repo = root;
        self.page = 4;
        self.view = PAGES[4].1.iter().position(|view| *view == "Project config").expect("Project config view");
        self.refresh(ctx);
    }
    fn open_linked_trace(&mut self, ctx: &egui::Context, id: String) {
        if !self.can_edit_context() { return; }
        self.clear_response();
        self.page = 1;
        self.view = PAGES[1].1.iter().position(|view| *view == "Trace index").expect("Trace index view");
        self.entity = id;
        self.trace_cursor = 0;
        self.trace_before = 0;
        self.trace_content_offset = 0;
        self.trace_offset = 0;
        self.filter.clear();
        self.submit(ctx, "Trace detail".into(), request("trace_detail",
            json!({"id": self.entity, "after": 0, "before": 0})));
    }
    fn can_edit_context(&self) -> bool {
        self.busy.is_none() && self.pending.is_none() && !self.installation_open
    }
    fn memory_args(&self) -> Value {
        json!({"root": self.repo, "scope": self.memory_scope, "query": self.memory_query,
            "record_id": self.memory_record_id, "key": self.memory_key,
            "value": self.memory_value, "kind": self.memory_kind,
            "task_id": self.memory_scope_id, "session_id": self.memory_scope_id,
            "clone_id": self.memory_scope_id, "worktree_id": self.memory_scope_id,
            "branch": self.memory_scope_id, "confirmed": true})
    }
    fn refresh(&mut self, ctx: &egui::Context) {
        let view = self.current();
        let data = match view {
            "Updates" => request("update_status", json!({})),
            "Service health" => request("log_tail", json!({"lines": self.log_lines})),
            "Diagnostics" => request("doctor", json!({})),
            "Memory" => request("memory_find", self.memory_args()),
            "Session briefing" => request("session_briefing", json!({"root": self.repo})),
            "Project and diagnostics archives" => { self.status = "Select an archive operation below.".into(); return; }
            "Telemetry history" => request("timeline_page", json!({"before": self.telemetry_before, "limit": self.telemetry_limit})),
            "Operator tools" => { self.submit(ctx, "Operator catalog".into(), request("operator_catalog", json!({}))); return; }
            "Trace index" => request("trace_page", json!({"offset": self.trace_offset, "kind": self.trace_kind, "state": self.trace_state, "action": self.trace_action, "min_duration_ms": self.trace_min_ms})),
            "Tasks" | "Run history" => request("task_page", json!({"root": self.repo, "offset": self.task_offset, "query": self.task_query})),
            "Agent event stream" => request("event_page", json!({"root": self.repo, "stream": self.stream_id, "after": self.event_cursor})),
            "Vision review" => { self.status = "Choose an image and enter a prompt first.".into(); return; }
            _ => { let mut payload = view_request(view, &self.repo, &self.entity); payload["args"]["period"] = json!(self.metrics_period); payload },
        };
        self.submit(ctx, view.into(), data);
    }
    fn operations(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        match self.page {
            1 => {
                if self.current() == "Telemetry history" {
                    ui.small("Installation-wide retained diagnostic events. The search applies to the loaded page only.");
                    ui.horizontal_wrapped(|ui| {
                        let previous = self.telemetry_limit;
                        egui::ComboBox::from_id_salt("telemetry_page_size")
                            .selected_text(format!("{} rows", self.telemetry_limit)).show_ui(ui, |ui| {
                                for limit in [50, 100, 250] {
                                    ui.selectable_value(&mut self.telemetry_limit, limit, format!("{limit} rows"));
                                }
                            });
                        let next = self.snapshot.as_ref().filter(|_| self.snapshot_view == "Telemetry history")
                            .filter(|v| v["has_more"] == true)
                            .and_then(|v| v["next_cursor"].as_i64())
                            .filter(|next| *next > 0 && (self.telemetry_before == 0 || *next < self.telemetry_before));
                        let newest = ui.button("Newest page").clicked();
                        let older = ui.add_enabled(next.is_some(), egui::Button::new("Older page")).clicked();
                        if newest || previous != self.telemetry_limit {
                            self.telemetry_before = 0; self.clear_response(); self.refresh(ctx);
                        } else if older {
                            self.telemetry_before = next.expect("enabled only with cursor");
                            self.clear_response(); self.refresh(ctx);
                        }
                    });
                    return;
                }
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
                if self.current() == "Requests" {
                    ui.horizontal_wrapped(|ui| {
                        egui::ComboBox::from_id_salt("request_status").selected_text(&self.request_status).show_ui(ui, |ui| {
                            for status in ["all", "failed", "2xx", "4xx", "5xx"] { ui.selectable_value(&mut self.request_status, status.into(), status); }
                        });
                        ui.label("Exact action");
                        ui.text_edit_singleline(&mut self.request_action);
                        egui::ComboBox::from_id_salt("request_sort").selected_text(&self.request_sort).show_ui(ui, |ui| {
                            for key in ["created_at", "duration_ms", "status_code", "action"] { ui.selectable_value(&mut self.request_sort, key.into(), key); }
                        });
                        ui.checkbox(&mut self.request_desc, "Descending");
                    });
                }
                if self.current() == "Endpoint analytics" {
                    ui.horizontal_wrapped(|ui| {
                        egui::ComboBox::from_id_salt("endpoint_scope").selected_text(&self.endpoint_scope).show_ui(ui, |ui| {
                            for scope in ["all", "active", "unused"] { ui.selectable_value(&mut self.endpoint_scope, scope.into(), scope); }
                        });
                        egui::ComboBox::from_id_salt("endpoint_sort").selected_text(&self.endpoint_sort).show_ui(ui, |ui| {
                            for key in ["name", "type", "calls", "success_rate", "p50_ms", "p95_ms", "p99_ms"] {
                                ui.selectable_value(&mut self.endpoint_sort, key.into(), key);
                            }
                        });
                        ui.checkbox(&mut self.endpoint_desc, "Descending");
                        if ui.button("Reset selected statistics").clicked() {
                            let global = self.repo.trim().is_empty();
                            let label = if global { "Reset ALL project statistics and retained telemetry" } else { "Reset statistics for selected repository" };
                            self.confirm(label, request("endpoint_reset", json!({"root": self.repo, "global": global, "confirmed": true})));
                        }
                    });
                }
                if self.current() == "Trace index" {
                    ui.horizontal_wrapped(|ui| {
                        ui.label("Kind");
                        egui::ComboBox::from_id_salt("trace_kind").selected_text(if self.trace_kind.is_empty() { "All" } else { &self.trace_kind }).show_ui(ui, |ui| {
                            for kind in ["", "api_request", "async_job"] { ui.selectable_value(&mut self.trace_kind, kind.into(), if kind.is_empty() { "All" } else { kind }); }
                        });
                        ui.label("State");
                        egui::ComboBox::from_id_salt("trace_state").selected_text(if self.trace_state.is_empty() { "All" } else { &self.trace_state }).show_ui(ui, |ui| {
                            for state in ["", "running", "queued", "completed", "failed", "interrupted"] { ui.selectable_value(&mut self.trace_state, state.into(), if state.is_empty() { "All" } else { state }); }
                        });
                        ui.label("Action");
                        ui.text_edit_singleline(&mut self.trace_action);
                        ui.label("Minimum ms");
                        ui.add(egui::DragValue::new(&mut self.trace_min_ms).range(0..=86400000));
                        if ui.button("Apply trace filters").clicked() { self.trace_offset = 0; self.refresh(ctx); }
                    });
                    ui.horizontal_wrapped(|ui| {
                        let total = self.snapshot.as_ref().filter(|_| self.snapshot_view == "Trace index").and_then(|v| v["total"].as_i64());
                        if ui.add_enabled(self.trace_offset > 0, egui::Button::new("Previous trace page")).clicked() { self.trace_offset = (self.trace_offset - 100).max(0); self.refresh(ctx); }
                        if ui.add_enabled(total.is_some_and(|n| self.trace_offset + 100 < n), egui::Button::new("Next trace page")).clicked() { self.trace_offset += 100; self.refresh(ctx); }
                        ui.label(format!("Offset {} / {}", self.trace_offset, total.map(|n| n.to_string()).unwrap_or_else(|| "unknown".into())));
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
                    let previous_scope = self.memory_scope.clone();
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
                    if previous_scope != self.memory_scope {
                        self.memory_scope_id.clear(); self.memory_record_id.clear(); self.memory_key.clear();
                        self.memory_value.clear(); self.clear_response();
                    }
                    if matches!(self.memory_scope.as_str(), "task" | "session" | "clone" | "worktree" | "branch") {
                        ui.label(format!("Exact {} identity", self.memory_scope));
                        if ui.text_edit_singleline(&mut self.memory_scope_id).changed() {
                            self.memory_record_id.clear(); self.clear_response();
                        }
                    }
                    ui.horizontal_wrapped(|ui| {
                        ui.label("Server search");
                        ui.text_edit_singleline(&mut self.memory_query);
                        if ui.button("Search memory").clicked() {
                            self.memory_record_id.clear(); self.clear_response(); self.refresh(ctx);
                        }
                    });
                    ui.label("New memory key and value (text or JSON)");
                    ui.text_edit_singleline(&mut self.memory_key);
                    ui.text_edit_multiline(&mut self.memory_value);
                    if ui.button("Record memory").clicked() {
                        self.confirm("Record memory", request("memory_record", self.memory_args()));
                    }
                    ui.label("Delete exact record ID (select a row or enter the ID)");
                    ui.text_edit_singleline(&mut self.memory_record_id);
                    if ui.add_enabled(!self.memory_record_id.trim().is_empty() && self.memory_scope != "worktree",
                        egui::Button::new("Delete memory record")).clicked() {
                        self.confirm("Delete exact scoped memory record", request("memory_delete", self.memory_args()));
                    }
                    if self.memory_scope == "worktree" { ui.small("Worktree deletion requires an independently verified scope and is not supported here."); }
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
                    let more = self.snapshot_view == self.current() && self.snapshot.as_ref()
                        .is_some_and(|v| v["has_more"].as_bool().unwrap_or_else(|| v["tasks"].as_array().is_some_and(|a| a.len() == 100)));
                    if ui.add_enabled(more, egui::Button::new("Next 100")).clicked() {
                        self.task_offset = (self.task_offset + 100).min(i32::MAX as i64); self.refresh(ctx);
                    }
                    ui.label(format!("Offset {}", self.task_offset));
                });
                if self.current() == "Run history" {
                    ui.label("Select a task from the table or enter its ID. History stays repository-scoped.");
                    if ui.text_edit_singleline(&mut self.entity).changed() { self.history_cursor = 0; self.clear_response(); }
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
                    if ui.button("Check completion receipts").clicked() {
                        self.submit(ctx, "Completion gate".into(), request("task_gate",
                            json!({"root": self.repo, "id": self.entity})));
                    }
                    egui::ComboBox::from_id_salt("task_target").selected_text(&self.task_target).show_ui(ui, |ui| {
                        for state in ["active", "verifying", "blocked", "planned"] {
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
            3 => {
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
                    if ui.add_enabled(!self.repo.is_empty() && !self.entity.is_empty() && !self.lease_owner.is_empty(),
                        egui::Button::new("Release lease")).clicked() {
                        self.confirm("Release observed file lease", request("lease_release", json!({"root": self.repo,
                            "id": self.entity, "owner": self.lease_owner, "confirmed": true})));
                    }
                    return;
                }
                if self.current() == "Worktrees" {
                    self.worktrees(ui);
                    return;
                }
                if self.current() == "Session briefing" {
                    ui.small("Repository-scoped summary of plans, board and active tasks. Use Load / refresh.");
                    return;
                }
                ui.label("Plan ID");
                if ui.text_edit_singleline(&mut self.entity).changed() {
                    self.revision.clear(); self.plan_draft = None; self.plan_task.clear();
                    self.plan_title.clear(); self.description.clear();
                }
                ui.label("Task ID (empty for plan-level edit)");
                if ui.text_edit_singleline(&mut self.plan_task).changed() {
                    self.plan_draft = None; self.plan_title.clear(); self.description.clear();
                }
                ui.label(format!("Observed revision: {}", if self.revision.is_empty() { "not loaded" } else { &self.revision }));
                if ui.button("Load exact plan / task for editing").clicked() {
                    self.plan_draft = None; self.revision.clear();
                    self.submit(ctx, "Plan detail".into(), request("plan_detail",
                        json!({"root": self.repo, "id": self.entity})));
                }
                let mut edit_request = None;
                if let Some(draft) = self.plan_draft.as_mut().filter(|d|
                    d.matches(&self.entity, &self.plan_task, &self.revision)) {
                    ui.collapsing("Edit observed plan fields", |ui| {
                        draft.render(ui);
                        let changes = draft.patch();
                        let title = if draft.task_id.is_empty() { "Update plan" } else { "Edit plan task" };
                        if ui.add_enabled(!changes.is_empty(), egui::Button::new(title)).clicked() {
                            let op = if draft.task_id.is_empty() { "plan_update" } else { "plan_task_edit" };
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
                if let Some((title, payload)) = edit_request { self.confirm(title, payload); }
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
                if ui.add_enabled(!self.plan_task.is_empty() && !self.revision.is_empty(), egui::Button::new("Delete plan task")).clicked() {
                    self.confirm("Delete plan task", request("plan_task_delete", json!({"root": self.repo,
                        "id": self.entity, "revision": self.revision, "task_id": self.plan_task, "confirmed": true})));
                }
                ui.horizontal_wrapped(|ui| {
                    egui::ComboBox::from_id_salt("plan_move").selected_text(&self.plan_status).show_ui(ui, |ui| {
                        for status in ["planned", "ready", "in_progress", "blocked"] {
                            ui.selectable_value(&mut self.plan_status, status.into(), status);
                        }
                    });
                    if ui.add_enabled(!self.plan_task.is_empty() && !self.revision.is_empty(), egui::Button::new("Move task")).clicked() {
                        self.confirm("Move plan task", request("plan_task_move", json!({
                            "root": self.repo, "id": self.entity, "task_id": self.plan_task,
                            "revision": self.revision, "status": self.plan_status, "confirmed": true})));
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
                if ui.button("Unregister and purge project data").clicked() {
                    self.confirm("Unregister and permanently purge selected project data", request("project", json!({"root": self.repo, "action": "unregister", "purge_data": true, "confirmed": true})));
                }
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
                if self.current() == "Operator tools" { self.operator_tools(ui, ctx); return; }
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
                if self.current() == "Settings" {
                    if self.settings_draft.render(ui) {
                        let patch = self.settings_draft.patch();
                        if !patch.is_empty() {
                            self.confirm("Save settings", request("settings_batch", json!({"settings": patch, "confirmed": true})));
                        }
                    }
                    ui.horizontal_wrapped(|ui| {
                        for (title, mode) in [("Telemetry off", "off"), ("Minimal telemetry", "minimal"), ("Detailed telemetry", "full")] {
                            if ui.button(title).clicked() {
                                self.confirm(&format!("{title} (may retain sensitive request content)"),
                                    request("telemetry", json!({"mode": mode, "confirmed": true})));
                            }
                        }
                        if ui.button("Reset configuration overrides").clicked() {
                            self.confirm("Reset configuration overrides", request("config_reset", json!({"confirmed": true})));
                        }
                    });
                } else {
                    ui.small("Change activity mode from the top toolbar.");
                }
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
            _ => {}
        }
    }
    fn operator_tools(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        ui.small("Local CLI operations with fixed argument schemas. Offline reads do not start the Hub. Mutations require confirmation.");
        if self.operator_catalog.is_empty() {
            if ui.button("Load operator catalog").clicked() { self.refresh(ctx); }
            return;
        }
        let previous = self.operator_name.clone();
        egui::ComboBox::from_id_salt("operator_name").selected_text(
            if self.operator_name.is_empty() { "Choose operation" } else { &self.operator_name }
        ).show_ui(ui, |ui| {
            for operation in &self.operator_catalog {
                if let Some(name) = operation["name"].as_str() {
                    ui.selectable_value(&mut self.operator_name, name.to_owned(), name);
                }
            }
        });
        if previous != self.operator_name { self.operator_fields.clear(); }
        let Some(operation) = self.operator_catalog.iter().find(|v| v["name"].as_str() == Some(&self.operator_name)).cloned() else { return; };
        if operation["requires_root"] == true { ui.label(format!("Repository: {}", if self.repo.is_empty() { "(select root above)" } else { &self.repo })); }
        if let Some(fields) = operation["fields"].as_array() {
            for field in fields {
                let Some(name) = field["name"].as_str() else { continue; };
                let label = field["label"].as_str().unwrap_or(name);
                let value = self.operator_fields.entry(name.to_owned()).or_insert(Value::Null);
                match field["kind"].as_str() {
                    Some("bool") => {
                        let mut checked = value.as_bool().unwrap_or(false);
                        ui.checkbox(&mut checked, label);
                        *value = json!(checked);
                    }
                    Some("choice") => {
                        let mut selected = value.as_str().unwrap_or("").to_owned();
                        ui.label(label);
                        egui::ComboBox::from_id_salt(("operator_field", name)).selected_text(&selected).show_ui(ui, |ui| {
                            if field["required"] != true { ui.selectable_value(&mut selected, String::new(), "(default)"); }
                            if let Some(choices) = field["choices"].as_array() {
                                for choice in choices.iter().filter_map(Value::as_str) {
                                    ui.selectable_value(&mut selected, choice.to_owned(), choice);
                                }
                            }
                        });
                        *value = json!(selected);
                    }
                    _ => {
                        let mut input = value.as_str().unwrap_or("").to_owned();
                        ui.label(label);
                        if field["kind"] == "lines" { ui.text_edit_multiline(&mut input); }
                        else { ui.text_edit_singleline(&mut input); }
                        *value = json!(input);
                    }
                }
            }
        }
        if ui.button("Run selected operation").clicked() {
            let payload = request("operator_run", json!({"name": self.operator_name,
                "root": self.repo, "fields": self.operator_fields, "confirmed": true}));
            let name = self.operator_name.clone();
            if operation["requires_confirmation"] == true { self.confirm(&name, payload); }
            else { self.submit(ctx, name, payload); }
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
                ui.add_enabled_ui(self.can_edit_context(), |ui| {
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
                        self.confirm("Change activity mode", request("mode", json!({"mode": self.mode, "confirmed": true})));
                    }
                    if ui.button("Installation").clicked() { self.installation_open = true; }
                });
            });
            ui.horizontal_wrapped(|ui| {
                ui.checkbox(&mut self.auto_probe, "Check status automatically while focused");
                if self.current() == "Agent event stream" { ui.checkbox(&mut self.auto_live, "Follow live SSE while focused"); }
                ui.label("Repository root");
                if ui.add_enabled(self.can_edit_context(), egui::TextEdit::singleline(&mut self.repo).desired_width(400.0)).changed() { self.reset_scope(); }
            });
        });
        egui::TopBottomPanel::bottom("status").show(ctx, |ui| {
            if let Some(label) = &self.busy { ui.horizontal(|ui| { ui.spinner(); ui.label(format!("{label} — running")); }); }
            else { ui.label(&self.status); }
        });
        egui::SidePanel::left("navigation").resizable(false).default_width(170.0).show(ctx, |ui| {
            ui.add_enabled_ui(self.can_edit_context(), |ui| {
                for (index, (name, _)) in PAGES.iter().enumerate() {
                    if ui.selectable_label(self.page == index, *name).clicked() && self.page != index {
                        self.page = index; self.view = 0; self.clear_response(); self.entity.clear(); self.revision.clear();
                        self.filter.clear();
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
                            self.view = index; self.clear_response(); self.entity.clear(); self.revision.clear();
                        }
                    }
                    if matches!(self.current(), "Overview" | "Requests" | "Active requests" | "Async jobs" | "Work orders" | "Commands" | "Process sessions" | "Recent errors" | "Runtime health" | "Models & search" | "Laya") {
                        let previous = self.metrics_period.clone();
                        egui::ComboBox::from_id_salt("metrics_period").selected_text(if self.metrics_period == "process" { "Since restart" } else { "Last 30 days" }).show_ui(ui, |ui| {
                            ui.selectable_value(&mut self.metrics_period, "process".into(), "Since restart");
                            ui.selectable_value(&mut self.metrics_period, "window".into(), "Last 30 days");
                        });
                        if self.metrics_period != previous { self.clear_response(); self.refresh(ctx); }
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
                    ui.small("Search response filters log lines. Logs may contain sensitive data.");
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
                        egui::ScrollArea::both().id_salt("operational_logs")
                            .show_rows(ui, height, lines.len(), |ui, range| {
                                for index in range { ui.add(egui::Label::new(egui::RichText::new(lines[index]).monospace()).wrap_mode(egui::TextWrapMode::Extend)); }
                            });
                    } else { ui.label("Log data unavailable."); }
                }
                return;
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
                                self.memory_record_id = item["record_id"].as_str().filter(|_| item["scope"].as_str() == Some(self.memory_scope.as_str())).unwrap_or("").to_owned();
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
            egui::Window::new("Record detail").open(&mut open).show(ctx, |ui| {
                let text = serde_json::to_string_pretty(record).unwrap_or_default();
                if ui.button("Copy record").clicked() { ui.ctx().copy_text(text.clone()); }
                if self.current() == "Projects" || self.current() == "Search workspaces" {
                    if let Some(root) = record["root"].as_str().filter(|r| !r.trim().is_empty()) {
                        if ui.add_enabled(can_navigate, egui::Button::new("Select repository and inspect configuration")).clicked() {
                            open_project = Some(root.to_owned());
                        }
                    }
                }
                if let Some(id) = linked_trace(record) {
                    if ui.add_enabled(can_navigate, egui::Button::new("Open linked trace")).clicked() {
                        open_trace = Some(id.to_owned());
                    }
                }
                egui::ScrollArea::both().max_height(500.0).show(ui, |ui| { ui.label(text); });
            });
            if !open { self.record_detail = None; }
        }
        if let Some(root) = open_project { self.open_project(ctx, root); }
        else if let Some(id) = open_trace { self.open_linked_trace(ctx, id); }
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
            egui::Window::new("Confirm operation").collapsible(false).resizable(false).show(ctx, |ui| {
                ui.label(&self.pending.as_ref().unwrap().label);
                ui.label("This operation may change Hub state. Verify the selected repository and target.");
                let args = &self.pending.as_ref().unwrap().payload["args"];
                for key in ["root", "id", "task_id", "action", "file", "revision", "version", "key", "status", "scope", "kind", "name", "mode", "stream", "session_id", "record_id", "owner", "clone_id", "worktree_id", "branch"] {
                    if let Some(value) = args[key].as_str() { ui.label(format!("{key}: {value}")); }
                }
                for key in ["global", "purge", "confirmed", "capacity"] {
                    if args[key].is_boolean() || args[key].is_number() {
                        ui.label(format!("{key}: {}", args[key]));
                    }
                }
                for key in ["title", "description", "criteria", "next_action", "accountable_role", "blocker"] {
                    if let Some(value) = args[key].as_str() { ui.label(format!("{key}: {value}")); }
                }
                if let Some(changes) = args["settings"].as_object() {
                    for (key, value) in changes { ui.label(format!("{key}: {value}")); }
                }
                if let Some(fields) = args["fields"].as_object() {
                    ui.collapsing("Reviewed operator parameters", |ui| {
                        for (key, value) in fields { ui.label(format!("{key}: {value}")); }
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
                self.service = None; self.settings_draft = settings::Draft::default(); self.reset_scope(); self.operator_catalog.clear(); self.repo.clear();
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
    fn context_switch_discards_scope_bound_targets_and_cursors() {
        let mut app = Desktop::new();
        app.entity = "old-task".into();
        app.plan_task = "old-plan-card".into();
        app.revision = "old-revision".into();
        app.memory_scope_id = "old-session".into();
        app.stream_id = "old-stream".into();
        app.history_cursor = 42;
        app.event_cursor = 42;
        app.trace_offset = 100;
        app.trace_content_offset = 200;
        app.task_offset = 100;
        app.operator_fields.insert("task-id".into(), json!("old-task"));
        app.snapshot = Some(json!({"old": true}));
        app.pending = Some(Pending { label: "old operation".into(), payload: json!({}) });
        assert!(!app.can_edit_context());
        app.reset_scope();
        assert!(app.can_edit_context());
        assert!(app.pending.is_none() && app.snapshot.is_none());
        assert!(app.entity.is_empty() && app.plan_task.is_empty() && app.revision.is_empty());
        assert!(app.memory_scope_id.is_empty() && app.stream_id.is_empty());
        assert_eq!((app.history_cursor, app.event_cursor, app.trace_offset, app.trace_content_offset, app.task_offset), (0, 0, 0, 0, 0));
        assert!(app.operator_fields.is_empty());
        app.installation_open = true;
        assert!(!app.can_edit_context());
    }
    #[test]
    fn trace_links_use_only_explicit_valid_trace_ids() {
        assert_eq!(linked_trace(&json!({"trace_id":"trace_1-2","request_id":"different"})), Some("trace_1-2"));
        assert_eq!(linked_trace(&json!({"request_id":"req_1"})), None);
        for id in ["", "../config", "a/b", "a?b", "a b", "č"] {
            assert_eq!(linked_trace(&json!({"trace_id":id})), None);
        }
        assert_eq!(linked_trace(&json!({"trace_id":123})), None);
    }
    #[test]
    fn operational_log_filter_is_case_insensitive_and_missing_is_unknown() {
        let response = json!({"lines": ["INFO ready", "ERROR timeout", "error retry"]});
        assert_eq!(filtered_log_lines(&response, " ERROR ").unwrap(), vec!["ERROR timeout", "error retry"]);
        assert_eq!(filtered_log_lines(&response, "").unwrap().len(), 3);
        assert!(filtered_log_lines(&json!({}), "").is_none());
        assert!(filtered_log_lines(&response, "absent").unwrap().is_empty());
    }
    #[test]
    fn plan_draft_preserves_unedited_fields_and_binds_target_revision() {
        let response = json!({"success":true,"file_revision":"rev1","plan":{"id":"plan_a",
            "title":"Plan","description":"Plan description","tasks":{"task_a":{"title":"Task",
            "description":"Complete task description","acceptance_criteria":["first","second"],
            "next_action":"test","blocker":null,"accountable_role":"developer"}}}});
        let mut draft = PlanDraft::from_response(&response, "plan_a", "task_a").unwrap();
        assert!(draft.matches("plan_a", "task_a", "rev1"));
        assert!(!draft.matches("plan_a", "task_b", "rev1"));
        assert!(!draft.matches("plan_a", "task_a", "rev2"));
        assert!(draft.patch().is_empty());
        draft.edited.insert("next_action".into(), json!("review"));
        assert_eq!(Value::Object(draft.patch()), json!({"next_action":"review"}));
        assert!(PlanDraft::from_response(&response, "other", "task_a").is_none());
        assert!(PlanDraft::from_response(&response, "plan_a", "missing").is_none());
    }
    #[test]
    fn plan_draft_preserves_multiline_criteria_without_lossy_editing() {
        let response = json!({"success":true,"file_revision":"rev1","plan":{"id":"plan_a",
            "tasks":{"task_a":{"title":"Task","description":"Text","acceptance_criteria":["one\ntwo"]}}}});
        let draft = PlanDraft::from_response(&response, "plan_a", "task_a").unwrap();
        assert!(!draft.edited.contains_key("criteria"));
        assert!(draft.patch().is_empty());
    }
    #[test]
    fn response_paths_are_stable() {
        let mut rows = Vec::new();
        flatten(&json!({"tasks":[{"id":"x"}]}), "", 0, &mut rows);
        assert_eq!(rows[0].path, "tasks[0].id");
        assert_eq!(rows[0].value, "x");
    }
}
