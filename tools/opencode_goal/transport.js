import { validateBinding } from "./core.js"

function transport({ baseURL, token = "", actor = "opencode-local", fetchImpl = fetch, timeoutMs = 15000, signal }) {
  let endpoint
  try { endpoint = new URL(baseURL) } catch { throw new Error("Agent OS URL must be a loopback HTTP origin with an explicit port") }
  if (endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1" || !endpoint.port ||
      endpoint.username || endpoint.password || endpoint.pathname !== "/" || endpoint.search || endpoint.hash) {
    throw new Error("Agent OS URL must be a loopback HTTP origin with an explicit port")
  }
  if (typeof token !== "string" || /[\r\n]/.test(token)) throw new Error("invalid Hub token")
  if (typeof actor !== "string" || !/^[A-Za-z0-9_.-]{1,128}$/.test(actor)) throw new Error("invalid Hub agent identity")
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) throw new Error("invalid timeout")
  const headers = { "Content-Type": "application/json", "X-LocalAI-Agent": actor }
  if (token) headers["X-LocalAI-Token"] = token
  async function request(path, payload, mutating, requestId) {
    let reader
    try {
      const response = await fetchImpl(`${endpoint.origin}${path}`, {
        method: "POST", headers: requestId ? { ...headers, "X-LocalAI-Request-ID": requestId } : headers, redirect: "error",
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs),
        body: JSON.stringify(payload),
      })
      if (!response.ok) throw new Error("HTTP error")
      reader = response.body?.getReader()
      if (!reader) throw new Error("missing body")
      const chunks = []
      let size = 0
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > 65536) { await reader.cancel(); throw new Error("body too large") }
        chunks.push(value)
      }
      const bytes = new Uint8Array(size)
      let offset = 0
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
      const result = JSON.parse(new TextDecoder().decode(bytes))
      if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("invalid result")
      return result
    } catch {
      return { success: false, outcome_unknown: mutating, error: "Agent OS request was not confirmed" }
    } finally {
      reader?.releaseLock()
    }
  }
  return { request, actor }
}

export async function runProjectCommand(state, sessionId, alias, requestId, options) {
  validateBinding(state)
  if (!/^[a-f0-9]{32}$/.test(requestId)) throw new Error("invalid request ID")
  const client = transport({ ...options, timeoutMs: 60000 })
  return client.request("/api/agent-state/verification", {
    action: "project_command", root: state.root, task_id: state.taskId, session_id: sessionId, alias,
  }, true, requestId)
}

export function validateTransportOptions(options) {
  transport(options)
}

async function readBoundTask(state, sessionId, options, statuses) {
  validateBinding(state)
  if (typeof sessionId !== "string" || !sessionId || sessionId !== sessionId.trim() || sessionId.includes("\0")) throw new Error("session ID is required")
  const { request, actor } = transport(options)
  const result = await request("/api/agent-state/tasks", {action: "get", root: state.root, task_id: state.taskId}, false)
  const task = result?.task
  const actual = task?.contract?.acceptance_criteria
  if (result?.success !== true || task?.task_id !== state.taskId || !statuses.includes(task?.status) ||
      task?.owner !== actor || task?.context?.session_id !== sessionId || task?.contract?.goal !== state.goal ||
      task?.checkpoint?.state_data?._agent_task_scope?.version !== 2 ||
      task?.checkpoint?.state_data?._agent_task_scope?.repo_root !== state.root ||
      !Array.isArray(actual) || actual.length !== state.criteria.length || !actual.every((item, i) => item === state.criteria[i])) {
    return {success: false, error: "existing task binding could not be verified"}
  }
  return result
}

/** Verify an existing task before it can be attached to a session. */
export async function getBoundTask(state, sessionId, options) {
  return readBoundTask(state, sessionId, options, ["planned", "active", "verifying"])
}

/** Reconcile a completed task only with its exact binding and fresh receipts. */
export async function getCompletedTask(state, sessionId, options) {
  const result = await readBoundTask(state, sessionId, options, ["completed"])
  if (result?.success !== true) return result
  const { request } = transport(options)
  const check = await request("/api/agent-state/verification", {action: "completion", root: state.root, task_id: state.taskId}, false)
  const verification = check?.completion
  if (check?.success !== true || verification?.task_id !== state.taskId || verification.complete !== true ||
      !Array.isArray(verification.satisfied_criteria) || !Array.isArray(verification.unsatisfied_criteria) ||
      !Array.isArray(verification.stale_criteria) || verification.unsatisfied_criteria.length || verification.stale_criteria.length ||
      !state.criteria.every(item => verification.satisfied_criteria.includes(item))) {
    return {success: false, error: "completed task verification unavailable or stale"}
  }
  return result
}

/** Create a task only after the caller has durably recorded its intent. */
export async function createTask(state, sessionId, options) {
  validateBinding(state)
  if (typeof sessionId !== "string" || !sessionId || sessionId !== sessionId.trim() || sessionId.includes("\0")) throw new Error("session ID is required")
  const { request, actor } = transport(options)
  const result = await request("/api/agent-state/tasks", {
    action: "create", root: state.root, task_id: state.taskId,
    idempotency_key: `create-${state.taskId}`, context: { session_id: sessionId },
    contract: { goal: state.goal, acceptance_criteria: state.criteria },
  }, true)
  const task = result?.task
  const actual = task?.contract?.acceptance_criteria
  if (result?.success !== true || task?.task_id !== state.taskId || task?.status !== "planned" || task?.owner !== actor ||
      task?.context?.session_id !== sessionId || task?.contract?.goal !== state.goal ||
      task?.checkpoint?.state_data?._agent_task_scope?.repo_root !== state.root ||
      !Array.isArray(actual) || actual.length !== state.criteria.length || !actual.every((item, i) => item === state.criteria[i])) {
    return { success: false, outcome_unknown: true, error: "Agent OS creation outcome is not confirmed" }
  }
  return result
}

/** Send a completion request only to the explicitly configured loopback Hub. */
export async function completeTask(state, options) {
  validateBinding(state)
  const { signal, sessionId, canCommit = async () => true, onMutationStart = async () => true } = options
  if (typeof sessionId !== "string" || !sessionId || sessionId !== sessionId.trim() || sessionId.includes("\0")) throw new Error("session ID is required")
  const { request, actor } = transport(options)
  const check = await request("/api/agent-state/verification", { action: "completion", root: state.root, task_id: state.taskId }, false)
  const verification = check?.completion
  if (check?.success !== true || verification?.task_id !== state.taskId || typeof verification.complete !== "boolean" ||
      !Array.isArray(verification.satisfied_criteria) || !Array.isArray(verification.unsatisfied_criteria) || !Array.isArray(verification.stale_criteria)) {
    return { success: false, outcome_unknown: false, verification_unavailable: true, error: "Agent OS verification unavailable or invalid" }
  }
  if (verification.complete !== true || verification.unsatisfied_criteria.length || verification.stale_criteria.length ||
      !state.criteria.every((item) => verification.satisfied_criteria.includes(item))) {
    return { success: false, outcome_unknown: false, error: "Agent OS verification incomplete" }
  }
  if (signal?.aborted || await canCommit() !== true || signal?.aborted) {
    return { success: false, outcome_unknown: false, verification_unavailable: true, error: "Goal was interrupted before completion" }
  }
  if (await onMutationStart() !== true || signal?.aborted) {
    return { success: false, outcome_unknown: false, verification_unavailable: true, error: "Goal completion intent was not recorded" }
  }
  const completed = await request("/api/agent-state/tasks", { action: "complete", root: state.root, task_id: state.taskId, expected_criteria: state.criteria, expected_binding: {goal: state.goal, session_id: sessionId} }, true)
  const task = completed?.task
  const actual = task?.contract?.acceptance_criteria
  if (completed?.success !== true || task?.task_id !== state.taskId || task?.status !== "completed" || task?.owner !== actor ||
      task?.contract?.goal !== state.goal || task?.context?.session_id !== sessionId ||
      task?.checkpoint?.state_data?._agent_task_scope?.version !== 2 || task?.checkpoint?.state_data?._agent_task_scope?.repo_root !== state.root ||
      !Array.isArray(actual) || actual.length !== state.criteria.length || !actual.every((item, i) => item === state.criteria[i])) {
    return { success: false, outcome_unknown: true, error: "Agent OS completion outcome is not confirmed" }
  }
  return completed
}
