#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

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
    ("Overview", &["Overview", "Hardware"]),
    ("Requests", &["Requests", "Trace index"]),
    ("Tasks", &["Tasks", "Memory", "Incidents"]),
    ("Coordination", &["Plans", "Plan board", "Semaphores", "File leases", "Worktrees"]),
    ("Projects", &["Projects", "Project config"]),
    ("Commands", &["Commands", "Worktrees"]),
    ("Models & search", &["Models & search", "Search workspaces"]),
    ("Service health", &["Runtime health", "Service health", "Diagnostics"]),
    ("Settings", &["Settings", "Settings — activity mode"]),
    ("Activity", &["Activity"]),
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
struct Completed { label: String, result: Result<Value, String>, probe: bool }
struct Desktop {
    install: Install,
    page: usize,
    view: usize,
    repo: String,
    entity: String,
    reason: String,
    prompt: String,
    mode: String,
    filter: String,
    rows: Vec<Row>,
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
            reason: String::new(), prompt: String::new(), mode: "active".into(), filter: String::new(),
            rows: Vec::new(), visible: Vec::new(), detail: None, pending: None, busy: None,
            receiver: None, status: "Desktop ready. Check the Hub installation and service.".into(),
            service: None, last_probe: Instant::now() - Duration::from_secs(30),
            auto_probe: true, installation_open: false,
        }
    }
    fn current(&self) -> &'static str { PAGES[self.page].1[self.view] }
    fn submit(&mut self, ctx: &egui::Context, label: String, payload: Value) {
        if self.busy.is_some() { return; }
        let probe = payload["op"] == "probe";
        self.busy = Some(label.clone());
        let install = self.install.clone();
        let (tx, rx) = mpsc::channel();
        self.receiver = Some(rx);
        let ctx = ctx.clone();
        thread::spawn(move || {
            let result = install.call(&payload);
            let _ = tx.send(Completed { label, result, probe });
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
                    Ok(value) => {
                        self.rows.clear();
                        self.detail = None;
                        flatten(&value, "", 0, &mut self.rows);
                        self.refilter();
                        self.status = format!("{}: response received{}", done.label,
                            if self.rows.len() >= MAX_ROWS { " (display capped)" } else { "" });
                        self.last_probe = Instant::now() - Duration::from_secs(30);
                    }
                    Err(error) => { self.status = format!("{}: {error}", done.label); }
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
    fn refresh(&mut self, ctx: &egui::Context) {
        let view = self.current();
        let data = view_request(view, &self.repo, &self.entity);
        self.submit(ctx, view.into(), data);
    }
    fn operations(&mut self, ui: &mut egui::Ui, ctx: &egui::Context) {
        match self.page {
            2 => {
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
                ui.horizontal(|ui| {
                    ui.label("Plan ID");
                    ui.text_edit_singleline(&mut self.entity);
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
            }
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
                ui.horizontal_wrapped(|ui| {
                    for (title, mode) in [("Minimal telemetry", "minimal"), ("Detailed telemetry", "full")] {
                        if ui.button(title).clicked() {
                            self.confirm(&format!("{title} (may retain sensitive request content)"),
                                request("telemetry", json!({"mode": mode, "confirmed": true})));
                        }
                    }
                    if ui.button("Reset configuration overrides").clicked() {
                        self.confirm("Reset configuration overrides", request("config_reset", json!({"confirmed": true})));
                    }
                });
            }
            _ => {}
        }
    }
}
impl eframe::App for Desktop {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.receive();
        // Only wake for health checks while focused, never continuously repaint an idle window.
        let focused = ctx.input(|i| i.focused);
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
                ui.label("Repository root");
                ui.add_enabled(self.busy.is_none(), egui::TextEdit::singleline(&mut self.repo).desired_width(400.0));
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
                        self.page = index; self.view = 0; self.rows.clear(); self.visible.clear(); self.detail = None;
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
                            self.view = index; self.rows.clear(); self.visible.clear(); self.detail = None;
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
            });
            if self.rows.is_empty() { ui.label("Load this view to inspect data. No hidden screen is polled."); }
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
                self.service = None; self.rows.clear(); self.visible.clear(); self.detail = None;
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
