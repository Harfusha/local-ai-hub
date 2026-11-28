#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod records;
mod settings;
mod summary;
mod trace;
mod views;
mod window;

use eframe::egui;
use serde_json::{json, Value};
use std::{
    io::{self, Read, Write},
    path::PathBuf,
    process::{Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

const PAGES: &[(&str, &[&str])] = &[
    ("Overview", &["Overview", "Hardware", "GPU"]),
    (
        "Requests",
        &[
            "Requests",
            "Active requests",
            "Scheduler queue",
            "Scheduler running",
            "Async jobs",
            "Work orders",
            "Trace index",
            "Endpoint analytics",
            "Telemetry history",
        ],
    ),
    (
        "Tasks",
        &[
            "Tasks",
            "Memory",
            "Incidents",
            "Vision review",
            "Run history",
        ],
    ),
    (
        "Coordination",
        &[
            "Plans",
            "Plan board",
            "Semaphores",
            "File leases",
            "Worktrees",
            "Session briefing",
        ],
    ),
    ("Projects", &["Projects", "Project config"]),
    ("Commands", &["Commands", "Worktrees"]),
    (
        "Models & search",
        &[
            "Models & search",
            "Search workspaces",
            "Model inventory",
            "Resident inventory",
            "Ollama management",
            "Benchmark",
            "Telemetry report",
            "Model statistics",
            "Execution profiles",
            "Cache layers",
            "Agent statistics",
            "Execution routes",
            "Laya",
            "Laya capture",
        ],
    ),
    (
        "Service health",
        &[
            "Runtime health",
            "Service health",
            "Process sessions",
            "Recent errors",
            "Recovery journal",
            "Diagnostics",
            "Audit",
        ],
    ),
    (
        "Settings",
        &[
            "Settings",
            "Settings — activity mode",
            "Updates",
            "Operator tools",
            "Instruction compression",
        ],
    ),
    ("Activity", &["Activity", "Agent event stream"]),
    ("Transfers", &["Project and diagnostics archives"]),
];
const OVERVIEW_DRILLDOWNS: &[(&str, &str)] = &[
    ("Active API requests", "Active requests"),
    ("Queued work", "Scheduler queue"),
    ("Running work", "Scheduler running"),
    ("Async jobs", "Async jobs"),
    ("Work orders", "Work orders"),
    ("Health and dependencies", "Runtime health"),
];

fn view_destination(target: &str) -> Option<(usize, usize)> {
    PAGES.iter().enumerate().find_map(|(page, (_, views))| {
        views
            .iter()
            .position(|candidate| *candidate == target)
            .map(|view| (page, view))
    })
}

const MAINTENANCE: &[&str] = &[
    "Optimize databases",
    "Purge expired cache (7 days)",
    "Cleanup stale agent state",
    "Purge detailed traces",
    "Reset all statistics",
];
const MAX_ROWS: usize = 12_000;
const MAX_ADAPTER_RESPONSE: usize = 8_100_000;

// Absolute IPC deadline, separate from individual HTTP/CLI timeouts. A
// timed-out mutation is NOT replayed, and the Hub/supervisor is not killed.
fn adapter_timeout(request: &Value) -> Duration {
    let seconds = match request["op"].as_str().unwrap_or("") {
        "probe" => 15,
        "read" | "log_tail" | "timeline_page" | "trace_page" | "task_page" | "event_page"
        | "event_stream" | "operator_catalog" | "vision_inspect" => 60,
        "vision_review" => 450,
        "lifecycle" | "operator_run" | "compare" | "bundle_import" | "bundle_export"
        | "diagnostics_export" | "model_manage" => 900,
        // Some scoped mutations perform two sequential 120-second requests.
        _ => 300,
    };
    Duration::from_secs(seconds)
}

// Drain all output so an oversized response cannot deadlock the child on
// a full pipe. Retain only a bounded prefix and never parse partial JSON.
fn read_bounded(mut reader: impl Read, limit: usize) -> io::Result<(Vec<u8>, bool)> {
    let mut data = Vec::new();
    let mut overflow = false;
    let mut chunk = [0_u8; 16_384];
    loop {
        let size = match reader.read(&mut chunk) {
            Ok(0) => break,
            Ok(size) => size,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        };
        let retained = size.min(limit.saturating_sub(data.len()));
        data.extend_from_slice(&chunk[..retained]);
        overflow |= retained < size;
    }
    Ok((data, overflow))
}

fn adapter_exchange(
    command: &mut Command,
    bytes: Vec<u8>,
    timeout: Duration,
) -> Result<(std::process::ExitStatus, Vec<u8>, bool), String> {
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = command
        .spawn()
        .map_err(|e| format!("Cannot launch Hub adapter: {e}"))?;
    let Some(stdout) = child.stdout.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err("Missing adapter stdout".into());
    };
    let Some(mut stdin) = child.stdin.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err("Missing adapter stdin".into());
    };
    let deadline = Instant::now() + timeout;
    let (read_tx, read_rx) = mpsc::channel();
    thread::spawn(move || {
        let _ = read_tx.send(read_bounded(stdout, MAX_ADAPTER_RESPONSE));
    });
    let (write_tx, write_rx) = mpsc::channel();
    thread::spawn(move || {
        let result = stdin.write_all(&bytes);
        drop(stdin); // EOF is the JSON bridge request boundary.
        let _ = write_tx.send(result);
    });
    let mut write_complete = false;
    let status = loop {
        if !write_complete {
            match write_rx.try_recv() {
                Ok(Ok(())) => write_complete = true,
                Ok(Err(error)) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!("Adapter input failed: {error}; outcome unknown"));
                }
                Err(mpsc::TryRecvError::Disconnected) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err("Adapter input worker disconnected; outcome unknown".into());
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {}
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Adapter wait failed: {error}; outcome unknown"));
            }
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            // Terminate only the short-lived bridge, never the service or
            // its detached supervisor. An already sent operation may finish.
            let _ = child.kill();
            let _ = child.wait();
            return Err(
                "Adapter deadline exceeded; operation outcome unknown. Reload before retrying."
                    .into(),
            );
        }
        thread::sleep(remaining.min(Duration::from_millis(50)));
    };
    if !write_complete {
        write_rx
            .recv_timeout(
                deadline
                    .saturating_duration_since(Instant::now())
                    .min(Duration::from_secs(5)),
            )
            .map_err(|_| "Adapter input receipt unavailable; outcome unknown".to_string())?
            .map_err(|e| format!("Adapter input failed: {e}; outcome unknown"))?;
    }
    // A descendant can inherit a pipe handle. Do not wait indefinitely
    // for EOF after the actual adapter process has already exited.
    let (stdout, overflow) = read_rx
        .recv_timeout(
            deadline
                .saturating_duration_since(Instant::now())
                .min(Duration::from_secs(5)),
        )
        .map_err(|_| "Adapter output did not close; outcome unknown".to_string())?
        .map_err(|e| format!("Cannot read adapter response: {e}"))?;
    Ok((status, stdout, overflow))
}

#[derive(Clone)]
struct Install {
    root: PathBuf,
    python: PathBuf,
    config: Option<PathBuf>,
}
impl Install {
    fn from_env() -> Self {
        let root = std::env::var_os("LOCAL_AI_HUB_ROOT")
            .map(PathBuf::from)
            .or_else(|| std::env::current_dir().ok())
            .unwrap_or_default();
        let venv = root.join(if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python"
        });
        let python = std::env::var_os("LOCAL_AI_DESKTOP_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                if venv.is_file() {
                    venv
                } else {
                    PathBuf::from(if cfg!(windows) {
                        "python.exe"
                    } else {
                        "python3"
                    })
                }
            });
        Self {
            root,
            python,
            config: std::env::var_os("LOCAL_AI_CONFIG").map(PathBuf::from),
        }
    }

    fn call(&self, request: &Value) -> Result<Value, String> {
        let root = self
            .root
            .canonicalize()
            .map_err(|e| format!("Hub installation: {e}"))?;
        let adapter = root.join("tools/desktop.py");
        if !adapter.is_file() || !root.join("tools/hubctl.py").is_file() {
            return Err("Select a trusted Local AI Hub source checkout containing tools/desktop.py and tools/hubctl.py.".into());
        }
        let mut command = Command::new(&self.python);
        command
            .arg(&adapter)
            .arg("--bridge")
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(config) = &self.config {
            command.arg("--config").arg(config);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let bytes = serde_json::to_vec(request).map_err(|e| e.to_string())?;
        if bytes.len() > 65_536 {
            return Err("Request too large".into());
        }
        let (status, stdout, overflow) =
            adapter_exchange(&mut command, bytes, adapter_timeout(request))?;
        if !status.success() {
            return Err(format!("Adapter exited: {status}"));
        }
        if overflow {
            return Err("Adapter response exceeds limit".into());
        }
        let envelope: Value = serde_json::from_slice(&stdout).map_err(|_| {
            "Invalid adapter response; check Python installation and Hub dependencies.".to_string()
        })?;
        if envelope["ok"].as_bool() != Some(true) {
            return Err(envelope["error"]
                .as_str()
                .unwrap_or("Unknown adapter failure")
                .to_owned());
        }
        Ok(envelope["result"].clone())
    }
}

#[derive(Clone)]
struct Row {
    path: String,
    value: String,
}
fn flatten(value: &Value, path: &str, depth: usize, rows: &mut Vec<Row>) {
    if rows.len() >= MAX_ROWS {
        return;
    }
    if depth >= 16 {
        rows.push(Row {
            path: path.into(),
            value: "[Nested data omitted]".into(),
        });
        return;
    }
    match value {
        Value::Object(items) if !items.is_empty() => {
            for (key, item) in items {
                let next = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                flatten(item, &next, depth + 1, rows);
                if rows.len() >= MAX_ROWS {
                    break;
                }
            }
        }
        Value::Array(items) if !items.is_empty() => {
            for (index, item) in items.iter().enumerate() {
                flatten(item, &format!("{path}[{index}]"), depth + 1, rows);
                if rows.len() >= MAX_ROWS {
                    break;
                }
            }
        }
        _ => {
            let value = value
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| value.to_string());
            rows.push(Row {
                path: path.into(),
                value,
            });
        }
    }
}
fn request(op: &str, args: Value) -> Value {
    json!({"op": op, "args": args})
}

struct TaskCreateInput<'a> {
    root: &'a str,
    goal: &'a str,
    criteria: &'a str,
    scope: &'a str,
    risk_profile: &'a str,
    description: &'a str,
    non_goals: &'a str,
    constraints: &'a str,
    session_id: &'a str,
    slo_json: &'a str,
}

fn task_create_payload(input: TaskCreateInput<'_>) -> Result<Value, String> {
    let slo_profile = if input.slo_json.trim().is_empty() {
        json!({})
    } else {
        let value: Value = serde_json::from_str(input.slo_json)
            .map_err(|error| format!("SLO profile must be a JSON object: {error}"))?;
        if !value.is_object() {
            return Err("SLO profile must be a JSON object".into());
        }
        value
    };
    let lines = |value: &str| {
        value
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>()
    };
    let mut context = serde_json::Map::new();
    if !input.session_id.trim().is_empty() {
        context.insert("session_id".into(), json!(input.session_id.trim()));
    }

    Ok(request(
        "task_create",
        json!({
            "root": input.root,
            "contract": {
                "goal": input.goal,
                "acceptance_criteria": lines(input.criteria),
                "scope": input.scope,
                "risk_profile": input.risk_profile,
                "description": input.description,
                "non_goals": lines(input.non_goals),
                "constraints": lines(input.constraints),
                "slo_profile": slo_profile
            },
            "context": context,
            "confirmed": true
        }),
    ))
}

// The confirmation shows the exact target and reviewed mutation fields.
// Never dump an arbitrary request (e.g. image bytes, archive passwords).
fn confirmation_items(payload: &Value) -> Vec<(String, String)> {
    let args = &payload["args"];
    if payload["op"] == "task_create" {
        let mut items = Vec::new();
        if let Some(root) = args["root"].as_str() {
            items.push(("root".into(), root.into()));
        }
        for key in [
            "goal",
            "acceptance_criteria",
            "scope",
            "risk_profile",
            "description",
            "non_goals",
            "constraints",
            "slo_profile",
        ] {
            if let Some(value) = args["contract"].get(key) {
                let text = value
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| value.to_string());
                items.push((format!("contract.{key}"), text));
            }
        }
        if let Some(session_id) = args["context"]["session_id"].as_str() {
            items.push(("session_id".into(), session_id.into()));
        }
        return items;
    }
    [
        "root",
        "id",
        "task_id",
        "execution_id",
        "action",
        "file",
        "revision",
        "version",
        "manifest",
        "manifest_sha256",
        "image_sha256",
        "key",
        "status",
        "scope",
        "kind",
        "name",
        "model",
        "mode",
        "stream",
        "session_id",
        "record_id",
        "owner",
        "clone_id",
        "worktree_id",
        "branch",
        "global",
        "purge",
        "capacity",
        "title",
        "description",
        "criteria",
        "next_action",
        "accountable_role",
        "blocker",
        "lifecycle",
        "default_target_ref",
        "work_phase",
        "order",
        "depends_on_json",
        "goal",
        "risk",
        "reason",
        "non_goals",
        "constraints",
        "slo",
        "resolution",
        "message",
        "root_cause",
        "fix",
        "feature",
        "enabled",
    ]
    .iter()
    .filter_map(|key| {
        let value = args.get(*key)?;
        if value.is_null() {
            return None;
        }
        let text = value
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| value.to_string());
        Some(((*key).to_owned(), text))
    })
    .collect()
}
fn view_request(view: &str, root: &str, id: &str) -> Value {
    let op = match view {
        "Plans" => "plans",
        "Plan board" => "plan_board",
        "Semaphores" => "semaphores",
        "Worktrees" => "worktrees",
        "Project config" => "project_config",
        _ => "read",
    };
    request(op, json!({"view": view, "root": root, "id": id}))
}
// Only follow an explicit trace identifier returned by the server. A request
// ID, task ID or job ID is not a trace ID and must never be guessed.
fn filtered_log_lines<'a>(response: &'a Value, filter: &str) -> Option<Vec<&'a str>> {
    let lines = response.get("lines")?.as_array()?;
    let needle = filter.trim().to_lowercase();
    Some(
        lines
            .iter()
            .filter_map(Value::as_str)
            .filter(|line| needle.is_empty() || line.to_lowercase().contains(&needle))
            .collect(),
    )
}
fn linked_trace(record: &Value) -> Option<&str> {
    record.get("trace_id").and_then(Value::as_str).filter(|id| {
        !id.is_empty()
            && id.len() <= 200
            && id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    })
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
        if revision.is_empty() {
            return None;
        }
        let plan = &response["plan"];
        let source = if task_id.is_empty() {
            plan
        } else {
            plan.get("tasks")?.get(task_id)?
        };
        let mut original = serde_json::Map::new();
        for key in ["title", "description"] {
            original.insert(key.into(), json!(source.get(key)?.as_str()?));
        }
        // Role is optional at both levels. Blank is a placeholder for an
        // omitted role, not a request to delete an existing role.
        if let Some(value) = source.get("accountable_role").and_then(Value::as_str) {
            original.insert("accountable_role".into(), json!(value));
        } else if source.get("accountable_role").is_none() {
            original.insert("accountable_role".into(), json!(""));
        }
        if task_id.is_empty() {
            if let Some(value) = source.get("lifecycle").and_then(Value::as_str) {
                original.insert("lifecycle".into(), json!(value));
            }
            if let Some(value) = source.get("default_target_ref").and_then(Value::as_str) {
                original.insert("default_target_ref".into(), json!(value));
            } else if source.get("default_target_ref").is_some_and(Value::is_null) {
                original.insert("default_target_ref".into(), json!(""));
            }
        } else {
            for key in ["kind", "work_phase"] {
                if let Some(value) = source.get(key).and_then(Value::as_str) {
                    original.insert(key.into(), json!(value));
                } else if key == "work_phase" && source.get(key).is_none() {
                    original.insert(key.into(), json!(""));
                }
            }
            if let Some(order) = source.get("order").and_then(Value::as_u64) {
                original.insert("order".into(), json!(order.to_string()));
            } else if source.get("order").is_none() {
                original.insert("order".into(), json!(""));
            }
            if let Some(deps) = source.get("depends_on").filter(|v| v.is_array()) {
                if let Ok(serialized) = serde_json::to_string_pretty(deps) {
                    original.insert("depends_on_json".into(), json!(serialized));
                }
            }
            for key in ["next_action", "blocker"] {
                if let Some(value) = source.get(key).and_then(Value::as_str) {
                    original.insert(key.into(), json!(value));
                } else if source.get(key).is_none_or(Value::is_null) {
                    original.insert(key.into(), json!(""));
                }
            }
            // Multiline criteria cannot round-trip through the one-per-line editor.
            // Keep such criteria untouched instead of flattening them.
            if let Some(items) = source.get("acceptance_criteria").and_then(Value::as_array) {
                let lines: Option<Vec<&str>> = items
                    .iter()
                    .map(|item| {
                        item.as_str().filter(|line| {
                            !line.contains(['\n', '\r']) && line.trim() == *line && !line.is_empty()
                        })
                    })
                    .collect();
                if let Some(lines) = lines {
                    original.insert("criteria".into(), json!(lines.join("\n")));
                }
            }
        }
        Some(Self {
            plan_id: plan_id.into(),
            task_id: task_id.into(),
            revision,
            edited: original.clone(),
            original,
        })
    }
    fn matches(&self, plan_id: &str, task_id: &str, revision: &str) -> bool {
        self.plan_id == plan_id && self.task_id == task_id && self.revision == revision
    }
    fn patch(&self) -> serde_json::Map<String, Value> {
        self.edited
            .iter()
            .filter(|(key, value)| self.original.get(*key) != Some(*value))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect()
    }
    fn render(&mut self, ui: &mut egui::Ui) {
        for (key, label, multiline) in [
            ("title", "Title", false),
            ("description", "Description", true),
            ("criteria", "Acceptance criteria (one per line)", true),
            ("next_action", "Next action", true),
            ("accountable_role", "Accountable role", false),
            ("blocker", "Blocker", true),
            (
                "default_target_ref",
                "Default target ref (refs/heads/…; blank = none)",
                false,
            ),
            ("order", "Task order (0–1000000000)", false),
            (
                "depends_on_json",
                "Dependencies (JSON array of plan_id / task_id objects)",
                true,
            ),
        ] {
            if let Some(Value::String(text)) = self.edited.get_mut(key) {
                ui.label(label);
                if multiline {
                    ui.text_edit_multiline(text);
                } else {
                    ui.text_edit_singleline(text);
                }
            } else if !self.task_id.is_empty() && key == "criteria" {
                ui.small("Criteria unavailable for lossless line editing; preserved unchanged.");
            }
        }
        for (key, label, choices) in [
            (
                "lifecycle",
                "Plan lifecycle",
                &["draft", "active", "paused", "cancelled"][..],
            ),
            (
                "kind",
                "Task kind",
                &["code", "documentation", "analysis", "operation"][..],
            ),
            (
                "work_phase",
                "Work phase",
                &["discovery", "implementation", "verification", "integration"][..],
            ),
        ] {
            if let Some(Value::String(value)) = self.edited.get_mut(key) {
                ui.horizontal_wrapped(|ui| {
                    ui.label(label);
                    egui::ComboBox::from_id_salt(("draft_choice", key))
                        .selected_text(if value.is_empty() {
                            "Not specified"
                        } else {
                            value.as_str()
                        })
                        .show_ui(ui, |ui| {
                            for choice in choices {
                                ui.selectable_value(value, (*choice).to_owned(), *choice);
                            }
                        });
                });
            }
        }
        ui.small("Only changed fields are sent. Completion and source delivery still require the canonical verification workflow.");
    }
}
struct Pending {
    label: String,
    payload: Value,
}
struct Completed {
    label: String,
    result: Result<Value, String>,
    probe: bool,
    live: bool,
}
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
    auto_log: bool,
    last_log: Instant,
    goal: String,
    criteria: String,
    task_form_error: Option<String>,
    memory_key: String,
    memory_value: String,
    memory_scope: String,
    memory_kind: String,
    memory_scope_id: String,
    memory_record_id: String,
    memory_query: String,
    memory_search_key: String,
    memory_status: String,
    memory_limit: i64,
    lease_owner: String,
    task_scope: String,
    task_non_goals: String,
    task_constraints: String,
    task_slo: String,
    task_session: String,
    task_risk: String,
    incident_kind: String,
    incident_message: String,
    incident_cause: String,
    incident_fix: String,
    incident_status: String,
    incident_query: String,
    incident_limit: i64,
    plan_title: String,
    revision: String,
    plan_task: String,
    plan_execution_id: String,
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
    task_back: Vec<i64>,
    task_limit: i64,
    task_status: String,
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
    plan_query: String,
    plan_lifecycle: String,
    plan_limit: i64,
    board_plan_filter: String,
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
            config_input: install
                .config
                .as_ref()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default(),
            install,
            page: 0,
            view: 0,
            repo: String::new(),
            entity: String::new(),
            reason: String::new(),
            prompt: String::new(),
            mode: "active".into(),
            settings_draft: settings::Draft::default(),
            metrics_period: "process".into(),
            log_lines: 250,
            auto_log: false,
            last_log: Instant::now(),
            goal: String::new(),
            criteria: String::new(),
            task_form_error: None,
            memory_key: String::new(),
            memory_value: String::new(),
            memory_scope: "repository".into(),
            memory_kind: "fact".into(),
            memory_scope_id: String::new(),
            memory_record_id: String::new(),
            memory_query: String::new(),
            memory_search_key: String::new(),
            memory_status: String::new(),
            memory_limit: 100,
            lease_owner: String::new(),
            task_scope: "task".into(),
            task_non_goals: String::new(),
            task_constraints: String::new(),
            task_slo: String::new(),
            task_session: String::new(),
            task_risk: "normal".into(),
            incident_kind: String::new(),
            incident_message: String::new(),
            incident_cause: String::new(),
            incident_fix: String::new(),
            incident_status: String::new(),
            incident_query: String::new(),
            incident_limit: 100,
            plan_title: String::new(),
            revision: String::new(),
            plan_task: String::new(),
            plan_execution_id: String::new(),
            plan_draft: None,
            description: String::new(),
            archive_path: String::new(),
            semaphore: String::new(),
            capacity: 1,
            trace_cursor: 0,
            trace_offset: 0,
            trace_kind: String::new(),
            trace_state: String::new(),
            trace_action: String::new(),
            trace_min_ms: 0,
            request_status: "all".into(),
            request_action: String::new(),
            request_sort: "created_at".into(),
            request_desc: true,
            trace_before: 0,
            trace_content_field: "request".into(),
            trace_content_offset: 0,
            task_offset: 0,
            task_back: Vec::new(),
            task_limit: 100,
            task_status: String::new(),
            task_query: String::new(),
            task_target: "active".into(),
            history_cursor: 0,
            telemetry_before: 0,
            telemetry_limit: 100,
            endpoint_scope: "all".into(),
            endpoint_sort: "calls".into(),
            endpoint_desc: true,
            stream_id: String::new(),
            event_cursor: 0,
            live_events: Vec::new(),
            auto_live: false,
            last_live: Instant::now(),
            update_version: String::new(),
            update_revision: String::new(),
            plan_status: "planned".into(),
            plan_query: String::new(),
            plan_lifecycle: String::new(),
            plan_limit: 100,
            board_plan_filter: String::new(),
            vision_path: String::new(),
            filter: String::new(),
            operator_catalog: Vec::new(),
            operator_name: String::new(),
            operator_fields: serde_json::Map::new(),
            rows: Vec::new(),
            snapshot: None,
            snapshot_view: String::new(),
            raw_view: false,
            reveal_trace: false,
            record_detail: None,
            visible: Vec::new(),
            detail: None,
            pending: None,
            busy: None,
            receiver: None,
            status: "Desktop ready. Check the Hub installation and service.".into(),
            service: None,
            last_probe: Instant::now() - Duration::from_secs(30),
            auto_probe: true,
            installation_open: false,
        }
    }
    fn current(&self) -> &'static str {
        PAGES[self.page].1[self.view]
    }
    fn submit(&mut self, ctx: &egui::Context, label: String, payload: Value) {
        if !self.can_edit_context() {
            return;
        }
        let probe = payload["op"] == "probe";
        let live = payload["op"] == "event_stream";
        if payload["op"] == "lifecycle" {
            self.last_probe = Instant::now() - Duration::from_secs(30);
        }
        self.busy = Some(label.clone());
        let install = self.install.clone();
        let (tx, rx) = mpsc::channel();
        self.receiver = Some(rx);
        let ctx = ctx.clone();
        thread::spawn(move || {
            let result = install.call(&payload);
            let _ = tx.send(Completed {
                label,
                result,
                probe,
                live,
            });
            ctx.request_repaint();
        });
    }
    fn confirm(&mut self, label: &str, payload: Value) {
        if !self.can_edit_context() {
            return;
        }
        self.pending = Some(Pending {
            label: label.to_owned(),
            payload,
        });
    }
    fn refilter(&mut self) {
        let needle = self.filter.to_lowercase();
        self.visible = self
            .rows
            .iter()
            .enumerate()
            .filter_map(|(i, row)| {
                (needle.is_empty()
                    || row.path.to_lowercase().contains(&needle)
                    || row.value.to_lowercase().contains(&needle))
                .then_some(i)
            })
            .collect();
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
                        if done.label == "Service health" {
                            self.last_log = Instant::now();
                        }
                        if done.live {
                            self.last_live = Instant::now();
                            if value["controls"].as_array().is_some_and(|controls| {
                                controls.iter().any(|c| {
                                    matches!(
                                        c["kind"].as_str(),
                                        Some("cursor_reset" | "replay_cursor_reset")
                                    )
                                })
                            }) {
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
                        if done.label == "Instruction review" {
                            let valid = value["success"] == true
                                && value["action"] == "inspect"
                                && value["manifest_sha256"].as_str().is_some_and(|d| {
                                    d.len() == 64 && d.bytes().all(|b| b.is_ascii_hexdigit())
                                })
                                && value["manifest"].as_str().is_some_and(|p| !p.is_empty());
                            if valid {
                                self.entity = value["manifest"].as_str().unwrap().to_owned();
                                self.revision =
                                    value["manifest_sha256"].as_str().unwrap().to_owned();
                            } else {
                                self.revision.clear();
                            }
                        }
                        if matches!(
                            done.label.as_str(),
                            "Apply reviewed instructions" | "Restore original instructions"
                        ) {
                            self.revision.clear();
                        }
                        if done.label == "Plan detail" {
                            self.plan_draft =
                                PlanDraft::from_response(&value, &self.entity, &self.plan_task);
                            self.revision = if value["plan"]["id"].as_str()
                                == Some(self.entity.as_str())
                                && value["success"] == true
                            {
                                value["file_revision"].as_str().unwrap_or("").to_owned()
                            } else {
                                String::new()
                            };
                        }
                        if matches!(
                            done.label.as_str(),
                            "Update plan"
                                | "Edit plan task"
                                | "Add plan task"
                                | "Delete plan task"
                                | "Move plan task"
                                | "Archive plan"
                                | "Bind execution task"
                        ) {
                            self.plan_draft = None;
                            self.revision.clear();
                        }
                        if done.label == "Settings" {
                            self.settings_draft = settings::Draft::from_response(&value);
                        }
                        if done.label == "Save settings"
                            || done.label == "Reset configuration overrides"
                        {
                            self.settings_draft = settings::Draft::default();
                        }
                        if matches!(done.label.as_str(), "Run events" | "Trace index") {
                            value = trace::sanitize(&value);
                        }
                        if done.label == "Trace content" {
                            // Do not flatten arbitrary stored text into searchable or copyable rows.
                            self.rows.clear();
                        } else if done.label == "Export encrypted diagnostics" {
                            // Keep the password only in the explicit receipt, never
                            // in the generic search/filter/copy field projection.
                            let mut receipt = value.clone();
                            if let Some(fields) = receipt.as_object_mut() {
                                fields.remove("archive_password");
                            }
                            flatten(&receipt, "", 0, &mut self.rows);
                        } else if done.label == "Trace detail"
                            || done.label == "Trace index"
                            || done.label == "Trace metrics"
                        {
                            flatten(&trace::sanitize(&value), "", 0, &mut self.rows);
                        } else {
                            flatten(&value, "", 0, &mut self.rows);
                        }
                        if done.label == "Operator catalog" {
                            self.operator_catalog =
                                value["operations"].as_array().cloned().unwrap_or_default();
                            self.operator_name.clear();
                            self.operator_fields.clear();
                        }
                        if done.label == "Updates" {
                            self.update_version = value
                                .pointer("/check/target_version")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .into();
                            self.update_revision = value
                                .pointer("/check/revision")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .into();
                        }
                        if done.label == "Agent event stream" {
                            if let Some(cursor) = value["next_seq"].as_i64() {
                                self.event_cursor = cursor;
                            }
                        }
                        self.snapshot = Some(value);
                        self.snapshot_view = done.label.clone();
                        self.refilter();
                        self.status = format!(
                            "{}: {}{}",
                            done.label,
                            if self
                                .snapshot
                                .as_ref()
                                .is_some_and(|v| v["success"] == false)
                            {
                                "operation failed — inspect details"
                            } else {
                                "response received"
                            },
                            if self.rows.len() >= MAX_ROWS {
                                " (display capped)"
                            } else {
                                ""
                            }
                        );
                    }
                    Err(error) => {
                        // A failed load/mutation must not leave a previously
                        // successful snapshot looking current or enable another
                        // write against its stale plan revision.
                        self.clear_response();
                        self.plan_draft = None;
                        self.revision.clear();
                        self.settings_draft = settings::Draft::default();
                        self.update_version.clear();
                        self.update_revision.clear();
                        if done.live {
                            self.last_live = Instant::now();
                        }
                        self.status =
                            format!("{}: {error} — reload to obtain fresh state", done.label);
                    }
                }
            }
            Some(Err(mpsc::TryRecvError::Disconnected)) => {
                self.busy = None;
                self.receiver = None;
                self.clear_response();
                self.plan_draft = None;
                self.revision.clear();
                self.settings_draft = settings::Draft::default();
                self.update_version.clear();
                self.update_revision.clear();
                self.status =
                    "Operation worker disconnected; outcome unknown. Reload before retrying."
                        .into();
            }
            _ => {}
        }
    }
    fn lifecycle(&mut self, ctx: &egui::Context, action: &str) {
        let data = request("lifecycle", json!({"action": action, "confirmed": true}));
        if action == "start" {
            self.submit(ctx, "Start Hub".into(), data);
        } else {
            self.confirm(&format!("{action} Hub (may interrupt active work)"), data);
        }
    }
    fn clear_response(&mut self) {
        self.rows.clear();
        self.visible.clear();
        self.detail = None;
        self.record_detail = None;
        self.snapshot = None;
        self.snapshot_view.clear();
        self.reveal_trace = false;
        self.live_events.clear();
        self.auto_live = false;
        self.auto_log = false;
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
        self.plan_query.clear();
        self.plan_lifecycle.clear();
        self.board_plan_filter.clear();
        self.description.clear();
        self.memory_scope_id.clear();
        self.memory_record_id.clear();
        self.memory_key.clear();
        self.memory_value.clear();
        self.memory_query.clear();
        self.memory_search_key.clear();
        self.memory_status.clear();
        self.goal.clear();
        self.criteria.clear();
        self.task_non_goals.clear();
        self.task_constraints.clear();
        self.task_slo.clear();
        self.task_session.clear();
        self.plan_execution_id.clear();
        self.reason.clear();
        self.prompt.clear();
        self.incident_kind.clear();
        self.incident_message.clear();
        self.incident_cause.clear();
        self.incident_fix.clear();
        self.incident_status.clear();
        self.incident_query.clear();
        self.vision_path.clear();
        self.archive_path.clear();
        self.semaphore.clear();
        self.lease_owner.clear();
        self.stream_id.clear();
        self.task_offset = 0;
        self.task_back.clear();
        self.task_status.clear();
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
    // A view change must not reuse a different view's selection, edit draft,
    // history cursor, or mutation fields. Keep only installation-wide preferences.
    fn navigate(&mut self, page: usize, view: usize) {
        if !self.can_edit_context() || (self.page == page && self.view == view) {
            return;
        }
        self.reset_scope();
        self.settings_draft = settings::Draft::default();
        self.page = page;
        self.view = view;
    }
    fn open_project(&mut self, ctx: &egui::Context, root: String) {
        if !self.can_edit_context() {
            return;
        }
        self.reset_scope();
        self.repo = root;
        self.page = 4;
        self.view = PAGES[4]
            .1
            .iter()
            .position(|view| *view == "Project config")
            .expect("Project config view");
        self.refresh(ctx);
    }
    fn open_linked_trace(&mut self, ctx: &egui::Context, id: String) {
        if !self.can_edit_context() {
            return;
        }
        self.reset_scope();
        self.page = 1;
        self.view = PAGES[1]
            .1
            .iter()
            .position(|view| *view == "Trace index")
            .expect("Trace index view");
        self.entity = id;
        self.trace_cursor = 0;
        self.trace_before = 0;
        self.trace_content_offset = 0;
        self.trace_offset = 0;
        self.filter.clear();
        self.submit(
            ctx,
            "Trace detail".into(),
            request(
                "trace_detail",
                json!({"id": self.entity, "after": 0, "before": 0}),
            ),
        );
    }
    fn can_edit_context(&self) -> bool {
        self.busy.is_none() && self.pending.is_none() && !self.installation_open
    }
    fn memory_args(&self, op: &str) -> Value {
        let mut args = json!({"root": self.repo, "scope": self.memory_scope});
        let field = match self.memory_scope.as_str() {
            "task" => Some("task_id"),
            "session" => Some("session_id"),
            "clone" => Some("clone_id"),
            "worktree" => Some("worktree_id"),
            "branch" => Some("branch"),
            _ => None,
        };
        if let Some(field) = field {
            args[field] = json!(self.memory_scope_id);
        }
        match op {
            "memory_find" => {
                args["query"] = json!(self.memory_query);
                args["key"] = json!(self.memory_search_key);
                args["status"] = json!(self.memory_status);
                args["limit"] = json!(self.memory_limit);
            }
            "memory_get" | "memory_quarantine" => {
                args["record_id"] = json!(self.memory_record_id);
                if op == "memory_quarantine" {
                    args["reason"] = json!(self.reason);
                    args["confirmed"] = json!(true);
                }
            }
            "memory_record" => {
                args["key"] = json!(self.memory_key);
                args["value"] = json!(self.memory_value);
                args["kind"] = json!(self.memory_kind);
                args["confirmed"] = json!(true);
            }
            "memory_delete" => {
                args["record_id"] = json!(self.memory_record_id);
                args["confirmed"] = json!(true);
            }
            _ => {}
        }
        args
    }
    fn refresh(&mut self, ctx: &egui::Context) {
        let view = self.current();
        let data = match view {
            "Updates" => request("update_status", json!({})),
            "Service health" => request("log_tail", json!({"lines": self.log_lines})),
            "Diagnostics" => request("doctor", json!({})),
            "Memory" => request("memory_find", self.memory_args("memory_find")),
            "Incidents" => request(
                "incident_list",
                json!({"root": self.repo, "status": self.incident_status, "limit": self.incident_limit}),
            ),
            "Plans" => request(
                "plans",
                json!({"root": self.repo, "query": self.plan_query, "lifecycle": self.plan_lifecycle, "limit": self.plan_limit}),
            ),
            "Plan board" => request(
                "plan_board",
                json!({"root": self.repo, "id": self.board_plan_filter, "query": self.plan_query}),
            ),
            "Session briefing" => request("session_briefing", json!({"root": self.repo})),
            "Project and diagnostics archives" => {
                self.status = "Select an archive operation below.".into();
                return;
            }
            "Telemetry history" => request(
                "timeline_page",
                json!({"before": self.telemetry_before, "limit": self.telemetry_limit}),
            ),
            "Operator tools" => {
                self.submit(
                    ctx,
                    "Operator catalog".into(),
                    request("operator_catalog", json!({})),
                );
                return;
            }
            "Instruction compression" => {
                if self.entity.trim().is_empty() {
                    self.status = "Select a staged manifest first.".into();
                    return;
                }
                self.revision.clear();
                self.submit(
                    ctx,
                    "Instruction review".into(),
                    request(
                        "instruction_manifest",
                        json!({"root":self.repo, "manifest":self.entity, "action":"inspect"}),
                    ),
                );
                return;
            }
            "Trace index" => request(
                "trace_page",
                json!({"offset": self.trace_offset, "kind": self.trace_kind, "state": self.trace_state, "action": self.trace_action, "min_duration_ms": self.trace_min_ms}),
            ),
            "Tasks" | "Run history" => request(
                "task_page",
                json!({"root": self.repo, "offset": self.task_offset, "limit": self.task_limit, "status": self.task_status, "query": self.task_query}),
            ),
            "Agent event stream" => request(
                "event_page",
                json!({"root": self.repo, "stream": self.stream_id, "after": self.event_cursor}),
            ),
            "Vision review" => {
                self.status = "Choose an image and enter a prompt first.".into();
                return;
            }
            _ => {
                let mut payload = view_request(view, &self.repo, &self.entity);
                payload["args"]["period"] = json!(self.metrics_period);
                payload
            }
        };
        self.submit(ctx, view.into(), data);
    }
}
fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1200.0, 760.0])
            .with_min_inner_size([800.0, 500.0]),
        renderer: eframe::Renderer::Wgpu,
        ..Default::default()
    };
    eframe::run_native(
        "Local AI Hub",
        options,
        Box::new(|_cc| Ok(Box::new(Desktop::new()))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn task_creation_sends_canonical_nested_contract() {
        let payload = task_create_payload(TaskCreateInput {
            root: "/repo",
            goal: "  Build a native app  ",
            criteria: "first criterion\n\n second criterion  \n",
            scope: "repository",
            risk_profile: "high",
            description: "  Scoped description  ",
            non_goals: "one\ntwo",
            constraints: "constraint",
            session_id: "session-1",
            slo_json: "{\"max_runtime_seconds\":30}",
        })
        .unwrap();

        assert_eq!(payload["op"], "task_create");
        assert_eq!(payload["args"]["root"], "/repo");
        assert_eq!(
            payload["args"]["contract"],
            json!({
                "goal":"  Build a native app  ",
                "acceptance_criteria":["first criterion", "second criterion"],
                "scope":"repository",
                "risk_profile":"high",
                "description":"  Scoped description  ",
                "non_goals":["one", "two"],
                "constraints":["constraint"],
                "slo_profile":{"max_runtime_seconds":30}
            })
        );
        assert_eq!(
            payload["args"]["context"],
            json!({"session_id":"session-1"})
        );
        assert_eq!(payload["args"]["confirmed"], true);
        assert!(payload["args"].get("criteria").is_none());
    }

    #[test]
    fn task_creation_rejects_non_object_slo_json() {
        for invalid in ["not json", "[]", "42", "null"] {
            assert!(task_create_payload(TaskCreateInput {
                root: "/repo",
                goal: "goal",
                criteria: "criterion",
                scope: "task",
                risk_profile: "normal",
                description: "",
                non_goals: "",
                constraints: "",
                session_id: "",
                slo_json: invalid,
            })
            .is_err());
        }
    }

    #[test]
    fn task_creation_confirmation_shows_nested_contract_fields() {
        let payload = task_create_payload(TaskCreateInput {
            root: "/repo",
            goal: "Build a native app",
            criteria: "Tests pass",
            scope: "repository",
            risk_profile: "high",
            description: "Replace dashboard",
            non_goals: "No web UI",
            constraints: "No legacy behavior",
            session_id: "session-2",
            slo_json: "{\"max_runtime_seconds\":30}",
        })
        .unwrap();
        let items: std::collections::BTreeMap<_, _> =
            confirmation_items(&payload).into_iter().collect();

        assert_eq!(items.get("root").map(String::as_str), Some("/repo"));
        assert_eq!(
            items.get("contract.goal").map(String::as_str),
            Some("Build a native app")
        );
        assert_eq!(
            items
                .get("contract.acceptance_criteria")
                .map(String::as_str),
            Some("[\"Tests pass\"]")
        );
        assert_eq!(
            items.get("contract.scope").map(String::as_str),
            Some("repository")
        );
        assert_eq!(
            items.get("contract.risk_profile").map(String::as_str),
            Some("high")
        );
        assert_eq!(
            items.get("contract.description").map(String::as_str),
            Some("Replace dashboard")
        );
        assert_eq!(
            items.get("contract.non_goals").map(String::as_str),
            Some("[\"No web UI\"]")
        );
        assert_eq!(
            items.get("contract.constraints").map(String::as_str),
            Some("[\"No legacy behavior\"]")
        );
        assert_eq!(
            items.get("contract.slo_profile").map(String::as_str),
            Some("{\"max_runtime_seconds\":30}")
        );
        assert_eq!(
            items.get("session_id").map(String::as_str),
            Some("session-2")
        );
    }

    #[test]
    fn scoped_views_are_named_operations() {
        assert_eq!(
            view_request("Plan board", "/repo", "plan_1"),
            json!({"op":"plan_board","args":{"view":"Plan board","root":"/repo","id":"plan_1"}})
        );
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
        app.goal = "old repository goal".into();
        app.prompt = "old prompt".into();
        app.incident_message = "old incident".into();
        app.archive_path = "old export path".into();
        app.stream_id = "old-stream".into();
        app.history_cursor = 42;
        app.event_cursor = 42;
        app.trace_offset = 100;
        app.trace_content_offset = 200;
        app.task_offset = 100;
        app.operator_fields
            .insert("task-id".into(), json!("old-task"));
        app.snapshot = Some(json!({"old": true}));
        app.pending = Some(Pending {
            label: "old operation".into(),
            payload: json!({}),
        });
        assert!(!app.can_edit_context());
        app.reset_scope();
        assert!(app.can_edit_context());
        assert!(app.pending.is_none() && app.snapshot.is_none());
        assert!(app.entity.is_empty() && app.plan_task.is_empty() && app.revision.is_empty());
        assert!(app.memory_scope_id.is_empty() && app.stream_id.is_empty());
        assert!(
            app.goal.is_empty()
                && app.prompt.is_empty()
                && app.incident_message.is_empty()
                && app.archive_path.is_empty()
        );
        assert_eq!(
            (
                app.history_cursor,
                app.event_cursor,
                app.trace_offset,
                app.trace_content_offset,
                app.task_offset
            ),
            (0, 0, 0, 0, 0)
        );
        assert!(app.operator_fields.is_empty());
        app.installation_open = true;
        assert!(!app.can_edit_context());
    }
    #[test]
    fn confirmation_includes_exact_mutation_identity_and_excludes_binary_or_secrets() {
        let payload = request(
            "model_manage",
            json!({"model":"fixture:7b", "action":"delete",
            "execution_id":"task_a","revision":"rev_1","depends_on_json":"[]",
            "archive_password":"secret","image":"large-bytes"}),
        );
        let items: std::collections::BTreeMap<_, _> =
            confirmation_items(&payload).into_iter().collect();
        assert_eq!(items.get("model").map(String::as_str), Some("fixture:7b"));
        assert_eq!(
            items.get("execution_id").map(String::as_str),
            Some("task_a")
        );
        assert_eq!(items.get("revision").map(String::as_str), Some("rev_1"));
        assert_eq!(items.get("depends_on_json").map(String::as_str), Some("[]"));
        assert!(!items.contains_key("archive_password") && !items.contains_key("image"));
    }

    #[test]
    fn all_native_views_render_offline_without_spawning_adapter() {
        let mut app = Desktop::new();
        app.auto_probe = false;
        app.repo = "/repo".into();
        let ctx = egui::Context::default();
        for (page, (_, views)) in PAGES.iter().enumerate() {
            for (view, name) in views.iter().enumerate() {
                app.navigate(page, view);
                let input = egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        egui::Pos2::ZERO,
                        egui::vec2(800.0, 500.0),
                    )),
                    ..Default::default()
                };
                let output = ctx.run(input, |ctx| app.render(ctx));
                assert!(!output.shapes.is_empty(), "No shapes rendered for {name}");
                assert!(
                    app.busy.is_none() && app.receiver.is_none(),
                    "Unexpected adapter for {name}"
                );
                assert!(app.pending.is_none(), "Unexpected confirmation for {name}");
            }
        }
    }
    #[test]
    fn log_follow_is_opt_in_and_stops_on_navigation_or_failed_read() {
        let mut app = Desktop::new();
        assert!(!app.auto_log);
        app.navigate(7, 1);
        assert_eq!(app.current(), "Service health");
        app.auto_log = true;
        app.navigate(7, 0);
        assert!(!app.auto_log);
        app.navigate(7, 1);
        app.auto_log = true;
        app.busy = Some("Service health".into());
        let (tx, rx) = mpsc::channel();
        app.receiver = Some(rx);
        tx.send(Completed {
            label: "Service health".into(),
            result: Err("offline".into()),
            probe: false,
            live: false,
        })
        .unwrap();
        app.receive();
        assert!(!app.auto_log);
        assert!(app.status.contains("offline"));
    }
    #[test]
    fn support_archive_password_is_not_indexed_by_generic_search() {
        let mut app = Desktop::new();
        app.busy = Some("Export encrypted diagnostics".into());
        let (tx, rx) = mpsc::channel();
        app.receiver = Some(rx);
        tx.send(Completed {
            label: "Export encrypted diagnostics".into(),
            result: Ok(json!({"success":true,"file":"support.zip","bytes":100,"archive_password":"fixture-secret"})),
            probe: false, live: false,
        }).unwrap();
        app.receive();
        assert!(app
            .rows
            .iter()
            .all(|row| !row.path.contains("password") && !row.value.contains("fixture-secret")));
        assert_eq!(
            app.snapshot.as_ref().unwrap()["archive_password"],
            "fixture-secret"
        );
        assert!(!app.reveal_trace);
        app.navigate(10, 0);
        assert!(app.snapshot.is_none());
    }
    #[test]
    fn failed_worker_invalidates_previous_snapshot_and_mutation_revision() {
        let mut app = Desktop::new();
        app.snapshot = Some(json!({"success":true}));
        app.revision = "stale".into();
        app.busy = Some("Edit plan task".into());
        let (tx, rx) = mpsc::channel();
        app.receiver = Some(rx);
        tx.send(Completed {
            label: "Edit plan task".into(),
            result: Err("conflict".into()),
            probe: false,
            live: false,
        })
        .unwrap();
        app.receive();
        assert!(app.snapshot.is_none() && app.revision.is_empty());
        assert!(app.busy.is_none() && app.receiver.is_none());
        assert!(app.status.contains("conflict"));
    }
    #[test]
    fn overview_workload_drilldowns_resolve_to_existing_native_views() {
        let expected = [
            ("Active API requests", "Active requests"),
            ("Queued work", "Scheduler queue"),
            ("Running work", "Scheduler running"),
            ("Async jobs", "Async jobs"),
            ("Work orders", "Work orders"),
            ("Health and dependencies", "Runtime health"),
        ];
        assert_eq!(OVERVIEW_DRILLDOWNS, expected.as_slice());
        let mut app = Desktop::new();
        for (_, target) in OVERVIEW_DRILLDOWNS {
            let (page, view) = view_destination(target).expect("drilldown target exists");
            assert_eq!(PAGES[page].1[view], *target);
            app.navigate(page, view);
            assert_eq!(app.current(), *target);
        }
    }

    #[test]
    fn navigation_drops_cross_view_mutation_targets_and_preserves_root() {
        let mut app = Desktop::new();
        app.repo = "/repo".into();
        app.entity = "old".into();
        app.memory_record_id = "old-record".into();
        app.lease_owner = "old-owner".into();
        app.reason = "old continuation".into();
        app.event_cursor = 123;
        app.task_offset = 100;
        app.navigate(2, 1);
        assert_eq!(app.current(), "Memory");
        assert_eq!(app.repo, "/repo");
        assert!(app.entity.is_empty() && app.memory_record_id.is_empty());
        assert!(app.lease_owner.is_empty() && app.reason.is_empty());
        assert_eq!((app.event_cursor, app.task_offset), (0, 0));
        app.pending = Some(Pending {
            label: "pending".into(),
            payload: json!({}),
        });
        app.navigate(3, 0);
        assert_eq!(app.current(), "Memory");
        assert!(app.pending.is_some());
    }
    #[test]
    fn trace_links_use_only_explicit_valid_trace_ids() {
        assert_eq!(
            linked_trace(&json!({"trace_id":"trace_1-2","request_id":"different"})),
            Some("trace_1-2")
        );
        assert_eq!(linked_trace(&json!({"request_id":"req_1"})), None);
        for id in ["", "../config", "a/b", "a?b", "a b", "č"] {
            assert_eq!(linked_trace(&json!({"trace_id":id})), None);
        }
        assert_eq!(linked_trace(&json!({"trace_id":123})), None);
    }
    #[test]
    fn operational_log_filter_is_case_insensitive_and_missing_is_unknown() {
        let response = json!({"lines": ["INFO ready", "ERROR timeout", "error retry"]});
        assert_eq!(
            filtered_log_lines(&response, " ERROR ").unwrap(),
            vec!["ERROR timeout", "error retry"]
        );
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
        assert_eq!(
            Value::Object(draft.patch()),
            json!({"next_action":"review"})
        );
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

#[cfg(test)]
mod bounded_adapter_tests {
    use super::*;

    #[test]
    fn adapter_deadlines_cover_longest_allowed_operations_without_unbounded_probes() {
        assert_eq!(
            adapter_timeout(&request("probe", json!({}))),
            Duration::from_secs(15)
        );
        for op in ["lifecycle", "operator_run", "compare", "bundle_export"] {
            assert_eq!(
                adapter_timeout(&request(op, json!({}))),
                Duration::from_secs(900)
            );
        }
        assert!(adapter_timeout(&request("plan_bind_task", json!({}))) > Duration::from_secs(240));
    }

    // The test executable acts as a deliberately nonresponsive child; no
    // shell, Python dependency, or platform-specific sleep executable.
    #[test]
    fn adapter_fixture_child() {
        if std::env::var_os("LAH_TEST_HUNG_ADAPTER").is_some() {
            thread::sleep(Duration::from_secs(10));
        }
    }

    #[test]
    fn adapter_deadline_reaps_unresponsive_child_even_if_stdin_is_blocked() {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "bounded_adapter_tests::adapter_fixture_child",
                "--nocapture",
            ])
            .env("LAH_TEST_HUNG_ADAPTER", "1");
        let started = Instant::now();
        let error = adapter_exchange(&mut command, vec![b'x'; 65_536], Duration::from_millis(250))
            .expect_err("unresponsive child must not succeed");
        assert!(error.contains("deadline exceeded"), "{error}");
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "watchdog did not return promptly"
        );
    }

    #[test]
    fn oversized_output_is_drained_with_bounded_retention() {
        let bytes = vec![b'x'; 100_000];
        let mut cursor = io::Cursor::new(&bytes);
        let (retained, overflow) = read_bounded(&mut cursor, 1024).unwrap();
        assert_eq!(retained.len(), 1024);
        assert!(overflow);
        assert_eq!(cursor.position(), bytes.len() as u64);
    }

    #[test]
    fn exact_limit_and_empty_response_are_not_overflow() {
        assert_eq!(
            read_bounded(&b"abc"[..], 3).unwrap(),
            (b"abc".to_vec(), false)
        );
        assert_eq!(read_bounded(&b""[..], 0).unwrap(), (Vec::new(), false));
        assert_eq!(read_bounded(&b"x"[..], 0).unwrap(), (Vec::new(), true));
    }
}
