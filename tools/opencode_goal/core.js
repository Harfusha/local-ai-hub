/** Receipt-gated goal transitions. The caller owns persistence and transport. */
import path from "node:path"

function canonical(value) {
  return typeof value === "string" && value.length > 0 && value.trim() === value && !value.includes("\0")
}

export function validateBinding({ taskId, root, criteria }) {
  if (!canonical(taskId) || !canonical(root)) throw new Error("taskId and root are required")
  if (!path.posix.isAbsolute(root) && !path.win32.isAbsolute(root)) throw new Error("root must be absolute")
  if (!Array.isArray(criteria) || !criteria.length || criteria.some((item) => !canonical(item)) || new Set(criteria).size !== criteria.length) {
    throw new Error("criteria must be distinct nonempty strings")
  }
}

export function createGoal({ goal, taskId, root, criteria, maxTurns = 20 }) {
  if (!canonical(goal)) throw new Error("goal is required")
  validateBinding({ taskId, root, criteria })
  if (!Number.isInteger(maxTurns) || maxTurns < 1 || maxTurns > 100) throw new Error("maxTurns must be 1-100")
  return { goal, taskId, root, criteria: [...criteria], maxTurns, turns: 0, status: "CONTINUE", reason: "goal created", observations: [], eventIds: [] }
}

export function pauseGoal(state, reason = "paused by user") {
  if (state.status === "DONE" || state.status === "FAILED") return state
  return { ...state, status: "PAUSED", reason }
}

export function resumeGoal(state) {
  if (state.status !== "PAUSED" && state.status !== "BLOCKED") return state
  if (state.outcomeUnknown === true || state.bindingUnverified === true) return state
  if (state.turns >= state.maxTurns) return { ...state, status: "FAILED", reason: "continuation limit reached" }
  return { ...state, status: "CONTINUE", reason: "resumed", observations: [] }
}

function verifiedCompletion(state, response) {
  const task = response?.task
  const actual = task?.contract?.acceptance_criteria
  return response?.success === true && task?.task_id === state.taskId && task?.status === "completed" &&
    Array.isArray(actual) && actual.length === state.criteria.length && actual.every((item, i) => item === state.criteria[i])
}

export function settleGoal(state, event) {
  if (state.status !== "CONTINUE" || !canonical(event?.id) || state.eventIds.includes(event.id)) return state
  const eventIds = [...state.eventIds, event.id].slice(-128)
  if (event.type === "interrupted") return { ...state, eventIds, status: "PAUSED", reason: "user interrupted" }
  if (event.type === "failed") return { ...state, eventIds, status: "FAILED", reason: "agent turn failed" }
  if (event.type !== "succeeded") return state
  const turns = state.turns + 1
  if (event.verification?.outcome_unknown === true) {
    return { ...state, eventIds, turns, outcomeUnknown: true, status: "BLOCKED", reason: "Agent OS completion outcome is unknown; inspect task state before retrying" }
  }
  if (event.verification?.verification_unavailable === true) {
    return { ...state, eventIds, turns, status: "BLOCKED", reason: "Agent OS verification unavailable" }
  }
  if (verifiedCompletion(state, event.verification)) {
    return { ...state, eventIds, turns, status: "DONE", reason: "Agent OS confirmed completion" }
  }
  // Missing observation is not evidence of unchanged work. Break the streak.
  const observation = typeof event.observation === "string" && event.observation ? event.observation : null
  const observations = observation === null ? [] : [...state.observations, observation].slice(-3)
  if (turns >= state.maxTurns) return { ...state, eventIds, turns, observations, status: "FAILED", reason: "continuation limit reached" }
  if (observations.length === 3 && observations.every((item) => item === observations[0])) {
    return { ...state, eventIds, turns, observations, status: "BLOCKED", reason: "stagnation: three unchanged observations" }
  }
  return { ...state, eventIds, turns, observations, status: "CONTINUE", reason: "Agent OS has not verified completion" }
}
