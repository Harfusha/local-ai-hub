const descriptions = {
  overview: ["Overview", "See whether the Hub is ready and choose the next useful action."],
  projects: ["Projects", "Inspect repositories, freshness, and existing project workflows."],
  agents: ["Agents", "Open the current agent and command surfaces."],
  tasks: ["Tasks", "Review requests, task ownership, coordination, and receipts."],
  models: ["Models", "Inspect installed models, search, and routing."],
  diagnostics: ["Diagnostics", "Review current service health and recent activity."],
  settings: ["Settings", "Configure the local Hub through the existing settings surface."],
};

const navItems = Array.from(document.querySelectorAll("[data-section].nav-item"));
const legacyLinks = Array.from(document.querySelectorAll(".legacy-link[data-section]"));
const title = document.getElementById("section-title");
const description = document.getElementById("section-description");
const kicker = document.getElementById("section-kicker");
const main = document.getElementById("main-content");
const menuToggle = document.querySelector(".menu-toggle");
const projectsView = document.getElementById("projects-view");
const sectionNotice = document.getElementById("section-notice");
const projectForm = document.getElementById("project-form");
const projectRootInput = document.getElementById("project-root");
const projectOperationStatus = document.getElementById("project-operation-status");
const projectDetails = document.getElementById("project-details");
const projectActionButtons = Array.from(document.querySelectorAll("#project-form button"));
const tasksView = document.getElementById("tasks-view");
const tasksForm = document.getElementById("tasks-form");
const tasksRootInput = document.getElementById("tasks-root");
const tasksStatus = document.getElementById("tasks-status");
const taskList = document.getElementById("task-list");
const worktreeResponse = document.getElementById("worktree-response");
const diagnosticsView = document.getElementById("diagnostics-view");
const diagnosticsForm = document.getElementById("diagnostics-form");
const diagnosticsRootInput = document.getElementById("diagnostics-root");
const diagnosticsStatus = document.getElementById("diagnostics-status");
const diagnosticsSummary = document.getElementById("diagnostics-summary");
const diagnosticsRecords = document.getElementById("diagnostics-records");
const timelineStatus = document.getElementById("timeline-status");
const timelineList = document.getElementById("telemetry-timeline");
const loadTimelineButton = document.getElementById("load-telemetry-timeline");
const loadOlderTimelineButton = document.getElementById("load-older-telemetry");
const modelsView = document.getElementById("models-view");
const modelsStatus = document.getElementById("models-status");
const modelList = document.getElementById("model-list");
const loadModelsButton = document.getElementById("load-models");
const settingsView = document.getElementById("settings-view");
const settingsStatus = document.getElementById("settings-status");
const settingsRecords = document.getElementById("settings-records");
const loadSettingsButton = document.getElementById("load-settings");
let projectOperationInFlight = false;

function showSection(section, moveFocus = false) {
  const copy = descriptions[section] || descriptions.overview;
  title.textContent = copy[0];
  description.textContent = copy[1];
  kicker.textContent = copy[0].toLocaleUpperCase();
  for (const item of navItems) {
    const active = item.dataset.section === section;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  for (const link of legacyLinks) {
    link.hidden = link.dataset.section !== section;
  }
  document.getElementById("overview-cards").hidden = section !== "overview";
  projectsView.hidden = section !== "projects";
  tasksView.hidden = section !== "tasks";
  diagnosticsView.hidden = section !== "diagnostics";
  modelsView.hidden = section !== "models";
  settingsView.hidden = section !== "settings";
  const migrated = section === "overview" || section === "projects" || section === "tasks" || section === "diagnostics" || section === "models" || section === "settings";
  sectionNotice.hidden = migrated;
  document.getElementById("section-notice-title").textContent = `${copy[0]} page remains in the current dashboard`;
  document.getElementById("section-notice-copy").textContent = `The ${copy[0]} view has not moved into this preview yet. Use the existing dashboard page links below; this shell has not checked or changed its configuration.`;
  document.getElementById("legacy-heading").textContent = section === "overview" ? "Existing dashboard pages" : `${copy[0]} pages`;
  if (moveFocus) main.focus();
  document.querySelector(".sidebar").classList.remove("is-open");
  menuToggle.setAttribute("aria-expanded", "false");
  menuToggle.setAttribute("aria-label", "Open navigation");
}

function absoluteRoot(value) {
  const root = value.trim();
  if (!root) throw new Error("Enter an absolute repository root first.");
  const windowsDrive = /^[A-Za-z]:[\\/]/.test(root);
  const uncPath = root.startsWith("\\\\");
  const posixPath = root.startsWith("/");
  if (!windowsDrive && !uncPath && !posixPath) throw new Error("Repository root must be an absolute path.");
  return root;
}

function projectRoot() { return absoluteRoot(projectRootInput.value); }

async function projectRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json", "X-LocalAI-Client": "dashboard", ...(options.headers || {}) },
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Hub returned an unreadable response (HTTP ${response.status}).`);
  }
  if (!payload || typeof payload !== "object") throw new Error("Hub returned an invalid project response.");
  if (!response.ok || payload.success === false) {
    if (response.status === 403) throw new Error("The Hub rejected access to this root. Check repository authorization and permissions.");
    throw new Error(payload.error || payload.message || `Hub request failed (HTTP ${response.status}).`);
  }
  return payload;
}

async function runProjectOperation(operation) {
  if (projectOperationInFlight) return;
  projectOperationInFlight = true;
  for (const button of projectActionButtons) button.disabled = true;
  try {
    await operation();
  } catch (error) {
    projectOperationStatus.textContent = error.message;
  } finally {
    projectOperationInFlight = false;
    for (const button of projectActionButtons) button.disabled = false;
  }
}

function projectDetail(label, value) {
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value === null || value === undefined || value === "" ? "Unknown" : String(value);
  projectDetails.append(term, description);
}

async function loadProjectStatus() {
  projectDetails.replaceChildren();
  projectDetails.hidden = true;
  const root = projectRoot();
  projectOperationStatus.textContent = "Loading status for the selected root…";
  const payload = await projectRequest(`/api/preprocess/status?root=${encodeURIComponent(root)}`, { cache: "no-store" });
  const project = Array.isArray(payload.projects) ? payload.projects.find((item) => item.root === root) : null;
  if (!project) {
    projectOperationStatus.textContent = payload.available === false
      ? "Project status is unavailable from this Hub instance."
      : "No preprocessing status was returned for this exact root.";
    return;
  }
  const measured = project.phase_progress_measured !== false && Number.isFinite(project.phase_progress_pct);
  projectOperationStatus.textContent = "Status loaded for the exact requested root. Freshness reflects the last preprocessing checkpoint; watcher state is not measured here.";
  projectDetails.hidden = false;
  projectDetail("Repository", project.project || root);
  projectDetail("Root", project.root);
  projectDetail("Pipeline state", project.state || project.status);
  projectDetail("Current phase", project.phase);
  projectDetail("Phase progress", measured ? `${project.phase_progress_pct}% · measured` : "Unknown · not measured");
  projectDetail("Last checkpoint age", Number.isFinite(project.progress_age_seconds) ? `${project.progress_age_seconds} seconds` : "Unknown");
  projectDetail("Activity", project.active_detail || project.waiting_reason || project.last_error_short);
  projectDetail("Indexed files", Number.isFinite(project.files) ? project.files : null);
  projectDetail("Hashed files", Number.isFinite(project.hashed_files) ? project.hashed_files : null);
  projectDetail("RAG files", Number.isFinite(project.rag_files) ? project.rag_files : null);
}

async function projectAction(action) {
  const root = projectRoot();
  const labels = { register: "Registering", refresh: "Refreshing indexes for", unregister: "Unregistering" };
  projectOperationStatus.textContent = `${labels[action]} ${root}…`;
  const payload = await projectRequest("/api/preprocess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root, action, ...(action === "unregister" ? { purge_data: false } : {}) }),
  });
  projectOperationStatus.textContent = payload.message || `${action} request accepted for the selected root.`;
  if (action !== "unregister") await loadProjectStatus();
}

projectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runProjectOperation(loadProjectStatus);
});
document.getElementById("register-project").addEventListener("click", async () => {
  await runProjectOperation(() => projectAction("register"));
});
document.getElementById("refresh-project").addEventListener("click", async () => {
  try {
    const root = projectRoot();
    if (!window.confirm(`Refresh indexes for this exact root?\n\n${root}`)) return;
  } catch (error) {
    projectOperationStatus.textContent = error.message;
    return;
  }
  await runProjectOperation(() => projectAction("refresh"));
});
document.getElementById("unregister-project").addEventListener("click", async () => {
  try {
    const root = projectRoot();
    if (!window.confirm(`Unregister this root? Source files stay untouched; cache purge is disabled.\n\n${root}`)) return;
  } catch (error) {
    projectOperationStatus.textContent = error.message;
    return;
  }
  await runProjectOperation(async () => {
    await projectAction("unregister");
    projectDetails.replaceChildren();
    projectDetails.hidden = true;
  });
});

function renderTaskRecords(records) {
  taskList.replaceChildren();
  for (const record of records) {
    const article = document.createElement("article");
    const title = document.createElement("h3");
    const status = document.createElement("p");
    const identity = document.createElement("p");
    const nextAction = document.createElement("p");
    const blockers = document.createElement("p");
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const payload = document.createElement("pre");
    article.className = "task-card";
    title.textContent = typeof record.title === "string" ? record.title : record.task_id || "Task record";
    status.textContent = `Recorded state: ${typeof record.status === "string" ? record.status : "unknown"}`;
    identity.textContent = `Task ID: ${typeof record.task_id === "string" ? record.task_id : "unknown"}`;
    nextAction.textContent = `Next action: ${typeof record.next_action === "string" ? record.next_action : "unknown"}`;
    blockers.textContent = `Recorded blockers: ${Array.isArray(record.blockers) ? record.blockers.length : "unknown"}`;
    summary.textContent = "Show stored task details";
    payload.textContent = JSON.stringify(record, null, 2);
    details.append(summary, payload);
    article.append(title, status, identity, nextAction, blockers, details);
    taskList.append(article);
  }
}

tasksForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (tasksForm.dataset.loading === "true") return;
  tasksForm.dataset.loading = "true";
  const button = tasksForm.querySelector("button[type=submit]");
  button.disabled = true;
  taskList.replaceChildren();
  try {
    const root = absoluteRoot(tasksRootInput.value);
    tasksStatus.textContent = "Loading task records for the exact repository root…";
    const query = `root=${encodeURIComponent(root)}&limit=50&include_stale=false`;
    const tasksResult = await projectRequest(`/api/agent-state/tasks?${query}`, { cache: "no-store" });
    renderTaskRecords(Array.isArray(tasksResult.tasks) ? tasksResult.tasks : []);
    tasksStatus.textContent = `Loaded ${Array.isArray(tasksResult.tasks) ? tasksResult.tasks.length : 0} stored task records. These records do not establish completion.`;
    try {
      const locks = await projectRequest(`/api/coord/worktrees?root=${encodeURIComponent(root)}`, { cache: "no-store" });
      worktreeResponse.textContent = JSON.stringify(locks, null, 2);
    } catch (error) {
      worktreeResponse.textContent = `Worktree state unavailable: ${error.message}`;
    }
  } catch (error) {
    tasksStatus.textContent = error.message;
    worktreeResponse.textContent = "Not loaded.";
  } finally {
    tasksForm.dataset.loading = "false";
    button.disabled = false;
  }
});

diagnosticsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (diagnosticsForm.dataset.loading === "true") return;
  diagnosticsForm.dataset.loading = "true";
  const button = diagnosticsForm.querySelector("button[type=submit]");
  button.disabled = true;
  diagnosticsSummary.replaceChildren();
  diagnosticsSummary.hidden = true;
  diagnosticsRecords.textContent = "";
  diagnosticsRecords.hidden = true;
  try {
    const root = diagnosticsRootInput.value.trim();
    const params = new URLSearchParams({ scope: "active", buckets: "1" });
    if (root) params.set("root", absoluteRoot(root));
    diagnosticsStatus.textContent = root
      ? "Loading aggregate statistics for the selected repository…"
      : "Loading installation-wide aggregate statistics…";
    const result = await projectRequest(`/api/telemetry/endpoint-stats?${params}`, { cache: "no-store" });
    const add = (label, value) => {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = value === null || value === undefined || value === "" ? "Unknown" : String(value);
      diagnosticsSummary.append(term, description);
    };
    add("Scope", root ? "Selected repository" : "Installation-wide · one Hub instance");
    add("Window", result.window);
    add("Latency method", result.latency_method === "fixed_histogram_bucket_estimate"
      ? "Estimated from fixed histogram buckets"
      : "Not reported by the endpoint");
    add("Open upper bucket", result.histogram_top_bucket_open_ended === true
      ? `Yes · estimated ceiling ${Number.isFinite(result.histogram_bucket_ceiling_ms) ? `${result.histogram_bucket_ceiling_ms} ms` : "unknown"}`
      : "No or unknown");
    add("Aggregate rows", Array.isArray(result.items) ? result.items.length : "Unknown");
    diagnosticsSummary.hidden = false;
    diagnosticsRecords.textContent = JSON.stringify(Array.isArray(result.items) ? result.items : [], null, 2);
    diagnosticsRecords.hidden = false;
    diagnosticsStatus.textContent = result.available === false
      ? "Endpoint statistics are unavailable in this Hub instance."
      : "Aggregate rows loaded. No request body or prompt content was requested.";
  } catch (error) {
    diagnosticsStatus.textContent = error.message;
  } finally {
    diagnosticsForm.dataset.loading = "false";
    button.disabled = false;
  }
});

let timelineCursor = null;
let timelineLoading = false;

function appendTimelineEvents(events) {
  const fragment = document.createDocumentFragment();
  for (const event of events) {
    const article = document.createElement("article");
    const title = document.createElement("h3");
    const metadata = document.createElement("p");
    const outcome = document.createElement("p");
    article.className = "task-card";
    title.textContent = typeof event.action === "string" && event.action
      ? event.action
      : typeof event.event_type === "string" ? event.event_type : "Telemetry event";
    const timestamp = typeof event.timestamp === "number" && Number.isFinite(event.timestamp)
      ? new Date(event.timestamp * 1000).toLocaleString()
      : "Unknown time";
    const agent = typeof event.agent === "string" && event.agent ? event.agent : "Unknown";
    metadata.textContent = `Recorded event: ${typeof event.event_type === "string" ? event.event_type : "unknown"} · Agent: ${agent} · ${timestamp}`;
    const duration = typeof event.duration_ms === "number" && Number.isFinite(event.duration_ms)
      ? `${event.duration_ms} ms`
      : "unknown duration";
    const saved = typeof event.net_tokens_saved === "number" && Number.isFinite(event.net_tokens_saved)
      ? String(event.net_tokens_saved)
      : "unknown";
    outcome.textContent = `Result: ${event.success === true ? "success" : event.success === false ? "failure" : "unknown"} · Duration: ${duration} · Reported net tokens saved: ${saved}`;
    article.append(title, metadata, outcome);
    if (typeof event.error_type === "string" && event.error_type) {
      const error = document.createElement("p");
      error.textContent = `Error type: ${event.error_type}`;
      article.append(error);
    }
    fragment.append(article);
  }
  timelineList.append(fragment);
}

async function loadTelemetryTimeline(older = false) {
  if (timelineLoading) return;
  timelineLoading = true;
  loadTimelineButton.disabled = true;
  loadOlderTimelineButton.disabled = true;
  if (!older) {
    timelineCursor = null;
    timelineList.replaceChildren();
  }
  timelineStatus.textContent = older ? "Loading older historical events…" : "Loading recent historical events…";
  try {
    const params = new URLSearchParams({ limit: "50" });
    if (older && timelineCursor !== null) params.set("before_id", String(timelineCursor));
    const result = await projectRequest(`/api/telemetry/timeline?${params}`, { cache: "no-store" });
    const events = Array.isArray(result.timeline) ? result.timeline : [];
    appendTimelineEvents(events);
    timelineCursor = result.has_more === true && Number.isSafeInteger(result.next_cursor)
      ? result.next_cursor
      : null;
    loadOlderTimelineButton.disabled = timelineCursor === null;
    timelineStatus.textContent = `Loaded ${events.length} historical metadata events. This timeline does not show current runtime health or request traces.`;
  } catch (error) {
    timelineStatus.textContent = error.message;
  } finally {
    timelineLoading = false;
    loadTimelineButton.disabled = false;
    if (timelineCursor !== null) loadOlderTimelineButton.disabled = false;
  }
}

loadTimelineButton.addEventListener("click", () => loadTelemetryTimeline(false));
loadOlderTimelineButton.addEventListener("click", () => loadTelemetryTimeline(true));

loadModelsButton.addEventListener("click", async () => {
  if (loadModelsButton.disabled) return;
  loadModelsButton.disabled = true;
  modelList.replaceChildren();
  modelsStatus.textContent = "Loading the installed model inventory…";
  try {
    const result = await projectRequest("/api/models", { cache: "no-store" });
    const models = Array.isArray(result.data) ? result.data : [];
    for (const model of models) {
      const card = document.createElement("article");
      const title = document.createElement("h3");
      const owner = document.createElement("p");
      card.className = "task-card";
      title.textContent = typeof model.id === "string" ? model.id : "Model ID unknown";
      owner.textContent = `Inventory owner: ${typeof model.owned_by === "string" ? model.owned_by : "unknown"}`;
      card.append(title, owner);
      modelList.append(card);
    }
    modelsStatus.textContent = `Received ${models.length} installed model inventory records. Runtime and quality state remain unknown.`;
  } catch (error) {
    modelsStatus.textContent = error.message;
  } finally {
    loadModelsButton.disabled = false;
  }
});

loadSettingsButton.addEventListener("click", async () => {
  if (loadSettingsButton.disabled) return;
  loadSettingsButton.disabled = true;
  settingsRecords.textContent = "";
  settingsRecords.hidden = true;
  settingsStatus.textContent = "Loading the redacted configuration snapshot…";
  try {
    const result = await projectRequest("/api/config", { cache: "no-store" });
    settingsRecords.textContent = JSON.stringify({
      config_path: result.config_path,
      runtime_override_path: result.runtime_override_path,
      config: result.config,
    }, null, 2);
    settingsRecords.hidden = false;
    settingsStatus.textContent = "Redacted configuration snapshot loaded. No values were changed.";
  } catch (error) {
    settingsStatus.textContent = error.message;
  } finally {
    loadSettingsButton.disabled = false;
  }
});

async function checkHub() {
  const status = document.getElementById("api-status");
  const value = document.getElementById("heartbeat-value");
  const detail = document.getElementById("heartbeat-detail");
  const checkedAt = document.getElementById("checked-at");
  const pill = document.getElementById("api-pill");
  const dot = document.getElementById("api-dot");
  const observedAt = new Date();
  checkedAt.textContent = `Requested ${new Intl.DateTimeFormat(undefined, { timeStyle: "medium" }).format(observedAt)}`;
  try {
    const response = await fetch("/api/live/status?light=1", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      status.textContent = `Hub API returned HTTP ${response.status}`;
      value.textContent = "Health unknown";
      detail.textContent = "The endpoint responded with an error. Service readiness is not established.";
      pill.textContent = "UNKNOWN";
      pill.className = "pill pill-warn";
      return;
    }
    const payload = await response.json();
    if (payload.snapshot_warming === true) {
      status.textContent = "Hub status is warming";
      value.textContent = "Unknown";
      detail.textContent = "A current status snapshot is not available yet.";
      pill.textContent = "WARMING";
      pill.className = "pill pill-warn";
      return;
    }
    if (payload.snapshot_stale === true) {
      status.textContent = "Hub returned a stale snapshot";
      value.textContent = "Stale snapshot";
      detail.textContent = "This is the last cached status snapshot, not a current health measurement.";
      pill.textContent = "STALE";
      pill.className = "pill pill-warn";
      return;
    }
    const degraded = payload.degraded === true || payload.status === "degraded";
    if (degraded) {
      status.textContent = "Hub reports degraded status";
      value.textContent = "Degraded";
      detail.textContent = "The current status response reports a degraded dependency.";
      pill.textContent = "DEGRADED";
      pill.className = "pill pill-warn";
      dot.classList.add("is-danger");
    } else {
      const reportedStatus = typeof payload.status === "string" ? payload.status : "responding";
      status.textContent = `Hub API responds · ${reportedStatus}`;
      value.textContent = "API responding";
      detail.textContent = "This current request confirms the status endpoint responds. Other resource health is unknown.";
      pill.textContent = "RESPONDING";
      pill.className = "pill pill-good";
      dot.classList.add("is-good");
    }
  } catch {
    status.textContent = "Hub status could not be read";
    value.textContent = "Unknown";
    detail.textContent = "The local status endpoint was unavailable or returned unreadable data.";
    pill.textContent = "UNKNOWN";
    pill.className = "pill pill-danger";
    dot.classList.add("is-danger");
  }
}

for (const item of navItems) {
  item.addEventListener("click", () => showSection(item.dataset.section, true));
}
menuToggle.addEventListener("click", () => {
  const open = menuToggle.getAttribute("aria-expanded") !== "true";
  menuToggle.setAttribute("aria-expanded", String(open));
  menuToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  document.querySelector(".sidebar").classList.toggle("is-open", open);
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
    document.querySelector(".sidebar").classList.remove("is-open");
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Open navigation");
    menuToggle.focus();
  }
});

showSection("overview");
void checkHub();
