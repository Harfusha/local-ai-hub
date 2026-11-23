import { readFile, unlink, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(root, "src/local_ai_hub/ui_static/dist");
const chunks = [
  "dashboard_overview.js",
  "dashboard_vision.js",
  "dashboard_trace_events.js",
  "dashboard_trace_timeline.js",
  "dashboard_trace_presentations.js",
  "dashboard_task_trajectory.js",
  "dashboard_tasks_memory.js",
  "dashboard_project_settings.js",
  "dashboard_tool_modals.js",
  "dashboard_models_activity.js",
  "dashboard_projects_trace.js",
  "dashboard_bundles.js",
  "dashboard_agent_os.js",
  "dashboard_rag.js",
  "dashboard_worktrees.js",
  "dashboard_benchmark.js",
  "dashboard_trajectory.js",
  "dashboard_analytics.js",
  "dashboard_coordination.js",
];
const parts = await Promise.all(chunks.map((name) => readFile(resolve(output, name), "utf8")));
await writeFile(resolve(output, "dashboard.js"), parts.join("\n"), "utf8");
await Promise.all(chunks.map((name) => unlink(resolve(output, name))));
