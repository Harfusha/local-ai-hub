/**
 * Local AI Hub Dashboard Frontend (HUB-093, HUB-094, HUB-096, HUB-097, HUB-098, HUB-099).
 * CSP-strict, offline local-only, zero raw HTML injection, visibility-aware polling.
 */

let activeSection = "overview";
let timelineCursor = null;
let currentPollTimer = null;
let activeAbortController = null;
let lastSuccessAt = 0;
let consecutiveErrors = 0;
let healthRequestEpoch = 0;
const sectionRequestEpochs = { agents: 0, tasks: 0, models: 0, diagnostics: 0, settings: 0 };

function isCurrentSectionRequest(section, epoch) {
  return activeSection === section && sectionRequestEpochs[section] === epoch;
}

const SECTIONS = {
  overview: {
    kicker: "OVERVIEW",
    title: "Overview",
    description: "See whether the Hub is ready and choose the next useful action.",
  },
  projects: {
    kicker: "SCOPED REPOSITORY OPERATIONS",
    title: "Projects and indexing",
    description: "Inspect indexing freshness, reindex a repository, or safely remove cached state.",
  },
  agents: {
    kicker: "AGENT HOST INSPECTION",
    title: "Agents & Hosts",
    description: "Truthful verification of Codex, Antigravity, and MCP capabilities.",
  },
  tasks: {
    kicker: "AGENT OS COORDINATION",
    title: "Tasks & Coordination",
    description: "Inspect Agent OS task contracts, stored receipts, and worktree leases.",
  },
  models: {
    kicker: "LOCAL MODEL INVENTORY",
    title: "Models & Inference",
    description: "Installed models, VRAM residency, and inference readiness.",
  },
  diagnostics: {
    kicker: "SYSTEM OBSERVABILITY",
    title: "Diagnostics & Telemetry",
    description: "Subsystem health, endpoint response times, and historical event timeline.",
  },
  settings: {
    kicker: "REDACTED CONFIGURATION SNAPSHOT",
    title: "Settings",
    description: "Read-only configuration snapshot. Secrets remain redacted.",
  },
};

/**
 * Shared fetch helper with AbortController, timeout, and monotonic revision tracking (HUB-099).
 */
async function request(url, options = {}) {
  const { timeout: timeoutMs = 8000, signal: externalSignal, headers: extraHeaders, ...fetchOptions } = options;
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", onAbort, { once: true });
  }
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: { Accept: "application/json", ...(extraHeaders || {}) },
    });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await response.json() : await response.text();
    const rejected = data !== null && typeof data === "object" && data.success === false;
    return { ok: response.ok && !rejected, status: response.status, data };
  } catch (err) {
    return {
      ok: false,
      status: err?.name === "AbortError" ? 408 : 0,
      data: { error: err?.message || "Network request failed" },
    };
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", onAbort);
  }
}

function updateStatusDot(elementId, state) {
  const dot = document.getElementById(elementId);
  if (!dot) return;
  dot.classList.remove("is-good", "is-danger");
  if (state === "ready" || state === "good") {
    dot.classList.add("is-good");
  } else if (state === "error" || state === "danger" || state === "offline") {
    dot.classList.add("is-danger");
  }
}

function updatePill(elementId, state, text) {
  const pill = document.getElementById(elementId);
  if (!pill) return;
  pill.classList.remove("pill-good", "pill-warn", "pill-danger", "pill-neutral");
  pill.textContent = text;
  if (state === "good") {
    pill.classList.add("pill-good");
  } else if (state === "warn") {
    pill.classList.add("pill-warn");
  } else if (state === "danger") {
    pill.classList.add("pill-danger");
  } else {
    pill.classList.add("pill-neutral");
  }
}

/**
 * Visibility-aware live health checking with adaptive backoff (HUB-094).
 */
async function checkHub() {
  if (activeAbortController) activeAbortController.abort();
  const controller = new AbortController();
  activeAbortController = controller;
  const epoch = ++healthRequestEpoch;
  const statusLabel = document.getElementById("api-status");
  const heartbeatValue = document.getElementById("heartbeat-value");
  const heartbeatDetail = document.getElementById("heartbeat-detail");
  const checkedAt = document.getElementById("checked-at");

  try {
    const res = await request("/ready", { timeout: 4000, signal: controller.signal });
    // Ignore old responses arriving after focus/visibility refreshes.
    if (epoch !== healthRequestEpoch) return;
    const now = Date.now();
    if (res.ok && res.data && res.data.ready === true) {
      lastSuccessAt = now;
      consecutiveErrors = 0;
      updateStatusDot("api-dot", "good");
      updatePill("api-pill", "good", "READY");
      if (statusLabel) statusLabel.textContent = "Hub online";
      if (heartbeatValue) heartbeatValue.textContent = "Hub is ready";
      if (heartbeatDetail) heartbeatDetail.textContent = "Local AI Hub service is responding to local loopback queries.";
      if (checkedAt) checkedAt.textContent = "Observed " + new Date().toLocaleTimeString();
    } else {
      consecutiveErrors++;
      const isDegraded = res.status === 200 || res.status === 503;
      updateStatusDot("api-dot", isDegraded ? "warning" : "danger");
      updatePill("api-pill", isDegraded ? "warn" : "danger", isDegraded ? "DEGRADED" : "OFFLINE");
      if (statusLabel) statusLabel.textContent = isDegraded ? "Hub degraded" : "Hub offline";
      if (heartbeatValue) heartbeatValue.textContent = isDegraded ? "Hub is degraded" : "Hub is unreachable";
      if (heartbeatDetail) heartbeatDetail.textContent =
        (res.data && typeof res.data.reason === "string") ? res.data.reason : "Could not reach local service.";
      if (checkedAt) checkedAt.textContent = "Attempted " + new Date().toLocaleTimeString();
    }
  } finally {
    if (epoch === healthRequestEpoch) {
      activeAbortController = null;
      scheduleNextPoll();
    }
  }
}

function scheduleNextPoll() {
  if (currentPollTimer) {
    clearTimeout(currentPollTimer);
  }
  let delay = 5000;
  if (document.hidden) {
    delay = 30000;
  } else if (consecutiveErrors > 0) {
    delay = Math.min(30000, 2000 * Math.pow(2, consecutiveErrors - 1));
  }
  currentPollTimer = setTimeout(checkHub, delay);
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    checkHub();
  } else {
    scheduleNextPoll();
  }
});

window.addEventListener("focus", () => {
  checkHub();
});

/**
 * Section navigation & tab display.
 */
function setSection(name) {
  if (!SECTIONS[name]) return;
  if (activeSection !== name) {
    for (const section of Object.keys(sectionRequestEpochs)) sectionRequestEpochs[section]++;
  }
  activeSection = name;

  document.querySelectorAll(".nav-item").forEach((btn) => {
    const isCurrent = btn.getAttribute("data-section") === name;
    btn.classList.toggle("is-active", isCurrent);
    if (isCurrent) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
  });

  const sec = SECTIONS[name];
  const kicker = document.getElementById("section-kicker");
  const title = document.getElementById("section-title");
  const desc = document.getElementById("section-description");
  if (kicker) kicker.textContent = sec.kicker;
  if (title) title.textContent = sec.title;
  if (desc) desc.textContent = sec.description;

  const views = {
    overview: "overview-cards",
    projects: "projects-view",
    agents: "agents-view",
    tasks: "tasks-view",
    models: "models-view",
    diagnostics: "diagnostics-view",
    settings: "settings-view",
  };

  for (const [key, id] of Object.entries(views)) {
    const el = document.getElementById(id);
    if (el) {
      if (key === name) {
        el.removeAttribute("hidden");
      } else {
        el.setAttribute("hidden", "");
      }
    }
  }

  // Auto-load on section switch if unpopulated
  if (name === "agents") {
    loadAgentHosts();
  } else if (name === "tasks") {
    loadTasks();
  } else if (name === "models") {
    loadModels();
  } else if (name === "settings") {
    loadSettings();
  }
}

/**
 * Agent Host Inspection (HUB-093).
 */
async function loadAgentHosts() {
  const statusEl = document.getElementById("hosts-status");
  const listEl = document.getElementById("hosts-list");
  if (!listEl) return;

  const epoch = ++sectionRequestEpochs.agents;
  if (statusEl) statusEl.textContent = "Checking agent host CLIs and MCP configuration…";
  listEl.replaceChildren();

  const res = await request("/api/agent/hosts");
  if (!isCurrentSectionRequest("agents", epoch)) return;
  if (!res.ok || !res.data || !Array.isArray(res.data.hosts)) {
    if (statusEl) statusEl.textContent = "Could not query agent hosts: " + (res.data?.error || "service unavailable");
    return;
  }

  if (statusEl) statusEl.textContent = "Found " + res.data.hosts.length + " inspected agent hosts.";

  for (const host of res.data.hosts) {
    const card = document.createElement("article");
    card.className = "host-card";

    const header = document.createElement("div");
    header.className = "host-header";

    const title = document.createElement("h3");
    title.textContent = host.display_name || host.host_id;

    const pill = document.createElement("span");
    pill.className = "pill";
    if (host.status === "ready") {
      pill.classList.add("pill-good");
      pill.textContent = "READY";
    } else if (host.status === "degraded") {
      pill.classList.add("pill-warn");
      pill.textContent = "DEGRADED";
    } else if (host.status === "stale") {
      pill.classList.add("pill-warn");
      pill.textContent = "STALE";
    } else {
      pill.classList.add("pill-danger");
      pill.textContent = "NOT INSTALLED";
    }

    header.append(title, pill);

    const details = document.createElement("dl");
    details.className = "project-details";

    const dtCli = document.createElement("dt");
    dtCli.textContent = "Detected CLI";
    const ddCli = document.createElement("dd");
    ddCli.textContent = host.detected_cli || "None (binary not found in PATH)";

    const dtMcp = document.createElement("dt");
    dtMcp.textContent = "MCP config";
    const ddMcp = document.createElement("dd");
    ddMcp.textContent = host.mcp_config_path || "None configured";

    const dtSkills = document.createElement("dt");
    dtSkills.textContent = "Skills & hooks";
    const ddSkills = document.createElement("dd");
    ddSkills.textContent = host.skills_state || "missing";

    const dtRem = document.createElement("dt");
    dtRem.textContent = "Status detail";
    const ddRem = document.createElement("dd");
    ddRem.textContent = host.remediation || "-";

    details.append(dtCli, ddCli, dtMcp, ddMcp, dtSkills, ddSkills, dtRem, ddRem);
    card.append(header, details);
    listEl.append(card);
  }
}

/**
 * Task Board & Coordination (HUB-096).
 */
async function loadTasks() {
  const statusEl = document.getElementById("tasks-status");
  const listEl = document.getElementById("task-list");
  const rootInput = document.getElementById("tasks-root");
  const root = rootInput ? rootInput.value.trim() : "";

  if (!listEl) return;
  const epoch = ++sectionRequestEpochs.tasks;
  if (root && !/^(?:[a-zA-Z]:[\\\\/]|\\\\\\\\|\\/)/.test(root)) {
    if (statusEl) statusEl.textContent = "Repository root must be absolute.";
    return;
  }
  if (statusEl) statusEl.textContent = "Loading tasks…";
  listEl.replaceChildren();

  const url = root ? `/api/agent-state/tasks?root=${encodeURIComponent(root)}` : "/api/agent-state/tasks";
  const res = await request(url);
  if (!isCurrentSectionRequest("tasks", epoch) || rootInput?.value.trim() !== root) return;

  if (!res.ok || !res.data) {
    if (statusEl) statusEl.textContent = "Failed to load tasks: " + (res.data?.error || "service unavailable");
    return;
  }

  const items = Array.isArray(res.data.tasks) ? res.data.tasks : [];
  if (statusEl) {
    statusEl.textContent = items.length === 0 ? "No active tasks recorded." : `Showing ${items.length} tasks. Expand a task to inspect every field returned by the stored record.`;
  }

  for (const record of items) {
    const card = document.createElement("article");
    card.className = "task-card";

    const title = document.createElement("h3");
    title.textContent = (record.task_id || "Task") + " · " + (record.status || "unknown");

    const desc = document.createElement("p");
    desc.textContent = record.title || record.acceptance_criteria || "No description";

    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Show stored task details";

    const payload = document.createElement("pre");
    payload.textContent = JSON.stringify(record, null, 2);

    details.append(summary, payload);
    card.append(title, desc, details);
    listEl.append(card);
  }

  // Also query worktrees if root provided
  const wtResponse = document.getElementById("worktree-response");
  if (wtResponse && root) {
    const wtRes = await request(`/api/coord/worktrees?root=${encodeURIComponent(root)}`);
    if (!isCurrentSectionRequest("tasks", epoch) || rootInput?.value.trim() !== root) return;
    if (wtRes.ok && wtRes.data) {
      wtResponse.textContent = JSON.stringify(wtRes.data, null, 2);
    } else {
      wtResponse.textContent = "Worktrees unavailable: " + (wtRes.data?.error || "error");
    }
  }
}

/**
 * Local Model Inventory (HUB-097).
 */
async function loadModels() {
  const statusEl = document.getElementById("models-status");
  const listEl = document.getElementById("model-list");
  if (!listEl) return;
  const epoch = ++sectionRequestEpochs.models;
  if (statusEl) statusEl.textContent = "Loading installed models…";
  listEl.replaceChildren();

  const res = await request("/api/models");
  if (!isCurrentSectionRequest("models", epoch)) return;
  if (!res.ok || !res.data || res.data.object !== "list" || !Array.isArray(res.data.data)) {
    if (statusEl) statusEl.textContent = "Model inventory unavailable or response contract changed.";
    return;
  }
  // The server currently lists installed Ollama IDs, not VRAM residency or digest.
  const models = res.data.data;
  if (models.length === 0) {
    if (statusEl) statusEl.textContent = "No Ollama models reported as installed; other providers were not queried.";
    return;
  }
  if (statusEl) statusEl.textContent = `Found ${models.length} installed Ollama model IDs (loaded/routable state unknown).`;
  for (const model of models) {
    const card = document.createElement("article");
    card.className = "task-card";
    const title = document.createElement("h3");
    title.textContent = model.id || "Unknown model ID";
    const meta = document.createElement("p");
    meta.textContent = `Source: ${model.owned_by || "unknown"} · GPU residency: unverified · Digest: unavailable`;
    card.append(title, meta);
    listEl.append(card);
  }
}

/**
 * Historical Telemetry Timeline (HUB-099).
 */
async function loadTelemetryTimeline(loadMore = false) {
  const statusEl = document.getElementById("diagnostics-status");
  const listEl = document.getElementById("telemetry-timeline");
  const loadMoreBtn = document.getElementById("load-older-telemetry");
  if (!listEl) return;
  const epoch = ++sectionRequestEpochs.diagnostics;
  if (!loadMore) {
    timelineCursor = null;
    listEl.replaceChildren();
  }
  if (statusEl) statusEl.textContent = "Loading telemetry events…";
  const params = new URLSearchParams({ limit: "50" });
  if (timelineCursor !== null) params.set("before_id", String(timelineCursor));

  const res = await request(`/api/telemetry/timeline?${params.toString()}`);
  if (!isCurrentSectionRequest("diagnostics", epoch)) return;
  if (!res.ok || !res.data || !Array.isArray(res.data.timeline) || typeof res.data.has_more !== "boolean") {
    if (statusEl) statusEl.textContent = "Telemetry unavailable or response contract changed.";
    return;
  }

  const events = res.data.timeline;
  if (statusEl) {
    statusEl.textContent = events.length
      ? `Loaded ${events.length} historical telemetry events; this is not live health.`
      : (loadMore ? "No older events found." : "No telemetry events recorded yet.");
  }
  const cursor = res.data.next_cursor;
  timelineCursor = Number.isSafeInteger(cursor) && cursor >= 0 ? cursor : null;
  if (loadMoreBtn) {
    loadMoreBtn.disabled = !res.data.has_more;
    if (res.data.has_more) loadMoreBtn.removeAttribute("hidden");
    else loadMoreBtn.setAttribute("hidden", "");
  }

  const fragment = document.createDocumentFragment();
  for (const event of events) {
    const article = document.createElement("article");
    article.className = "task-card";
    const title = document.createElement("h3");
    const time = typeof event.timestamp === "number"
      ? new Date(event.timestamp * 1000).toLocaleTimeString() : "Unknown time";
    title.textContent = `${event.event_type || "Event"} · ${event.action || "unknown"} · ${time}`;
    const metadata = document.createElement("p");
    const duration = Number.isFinite(event.duration_ms) ? event.duration_ms.toFixed(1) + "ms" : "-";
    metadata.textContent = `Duration: ${duration} · Net tokens saved: ${event.net_tokens_saved ?? "unknown"}`;
    const outcome = document.createElement("p");
    outcome.textContent = event.success ? "Success" : (event.error_type || "Failed");
    article.append(title, metadata, outcome);
    fragment.append(article);
  }
  // API pages are oldest-to-newest; older pages precede already displayed events.
  if (loadMore) listEl.prepend(fragment);
  else listEl.append(fragment);
}

/**
 * Settings Snapshot (HUB-098).
 */
async function loadSettings() {
  const statusEl = document.getElementById("settings-status");
  const recordsEl = document.getElementById("settings-records");
  if (!recordsEl) return;

  const epoch = ++sectionRequestEpochs.settings;
  if (statusEl) statusEl.textContent = "Loading configuration snapshot…";

  const res = await request("/api/config");
  if (!isCurrentSectionRequest("settings", epoch)) return;
  if (!res.ok || !res.data) {
    if (statusEl) statusEl.textContent = "Could not load settings: " + (res.data?.error || "service unavailable");
    return;
  }

  if (statusEl) statusEl.textContent = "Redacted configuration snapshot loaded. Secret values are redacted by the server.";
  recordsEl.removeAttribute("hidden");
  recordsEl.textContent = JSON.stringify(res.data, null, 2);
}

/**
 * Project Scoped Preprocessing Actions.
 */
async function handleProjectAction(action) {
  const rootInput = document.getElementById("project-root");
  const statusEl = document.getElementById("project-status");
  const detailsEl = document.getElementById("project-details");

  const root = rootInput ? rootInput.value.trim() : "";
  if (!root) {
    if (statusEl) statusEl.textContent = "Please provide an absolute repository root path.";
    return;
  }

  if (statusEl) statusEl.textContent = `Executing ${action} for ${root}…`;

  let url = "/api/preprocess/status";
  let body = { root };
  if (action === "reindex") {
    url = "/api/preprocess";
  } else if (action === "unregister") {
    url = "/api/preprocess/unregister";
    body = { root, purge_data: false };
  }

  const res = await request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok || !res.data) {
    if (statusEl) statusEl.textContent = `Action ${action} failed: ` + (res.data?.error || "unknown error");
    return;
  }

  if (statusEl) statusEl.textContent = `Action ${action} completed successfully.`;

  if (res.data && typeof res.data === "object") {
    if (detailsEl) detailsEl.removeAttribute("hidden");
    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val != null ? String(val) : "-";
    };
    setText("project-root-value", res.data.root || root);
    setText("project-phase-value", res.data.phase);
    setText("project-status-value", res.data.status);
    setText("project-fts-value", res.data.fts_indexed_rows);
    setText("project-ast-value", res.data.ast_indexed_rows);
    setText("project-error-value", res.data.last_error);
  }
}

/**
 * DOM Initialization.
 */
document.addEventListener("DOMContentLoaded", () => {
  // Navigation buttons
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const section = btn.getAttribute("data-section");
      if (section) setSection(section);
    });
  });

  // Mobile menu toggle
  const menuToggle = document.querySelector(".menu-toggle");
  const sidebar = document.querySelector(".sidebar");
  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", () => {
      const isOpen = sidebar.classList.toggle("is-open");
      menuToggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  // Project form buttons
  const form = document.getElementById("project-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      handleProjectAction("check");
    });
  }
  const reindexBtn = document.getElementById("project-reindex");
  if (reindexBtn) {
    reindexBtn.addEventListener("click", () => handleProjectAction("reindex"));
  }
  const unregisterBtn = document.getElementById("project-unregister");
  if (unregisterBtn) {
    unregisterBtn.addEventListener("click", () => {
      if (window.confirm("Safely unregister this project? (Cached files will not be purged)")) {
        handleProjectAction("unregister");
      }
    });
  }

  // Load buttons
  const loadHostsBtn = document.getElementById("load-hosts");
  if (loadHostsBtn) loadHostsBtn.addEventListener("click", loadAgentHosts);

  const loadTasksBtn = document.getElementById("load-tasks");
  if (loadTasksBtn) loadTasksBtn.addEventListener("click", loadTasks);

  const loadModelsBtn = document.getElementById("load-models");
  if (loadModelsBtn) loadModelsBtn.addEventListener("click", loadModels);

  const loadTimelineBtn = document.getElementById("load-telemetry-timeline");
  if (loadTimelineBtn) loadTimelineBtn.addEventListener("click", () => loadTelemetryTimeline(false));

  const loadOlderBtn = document.getElementById("load-older-telemetry");
  if (loadOlderBtn) loadOlderBtn.addEventListener("click", () => loadTelemetryTimeline(true));

  const loadSettingsBtn = document.getElementById("load-settings");
  if (loadSettingsBtn) loadSettingsBtn.addEventListener("click", loadSettings);

  // Initial check
  checkHub();
});
