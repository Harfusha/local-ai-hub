import test from "node:test"
import assert from "node:assert/strict"
import { makeGoalController } from "../../tools/opencode_goal/index.js"

function fixture(interruptSession, controllerOptions = {}) {
  const state = {
    goal: "check cancellation",
    taskId: "task-1",
    root: "C:\\repo",
    criteria: ["task remains receipt gated"],
    maxTurns: 4,
    turns: 0,
    status: "CONTINUE",
    reason: "goal created",
    observations: [],
    eventIds: [],
    epoch: "epoch-1",
  }
  const values = new Map([["goal:session-1", state]])
  const ctx = {
    storage: {
      get: async (key) => values.get(key),
      set: async (key, value) => values.set(key, value),
    },
    session: { get: async () => ({ location: { directory: state.root } }) },
  }
  return { state, values, controller: makeGoalController(ctx, { resolveRoot: async (root) => root, interruptSession, ...controllerOptions }) }
}

test("goal cancel interrupts the OpenCode session before pausing", async () => {
  const calls = []
  const { controller } = fixture(async (sessionID) => {
    calls.push(sessionID)
    return { data: { interrupted: true } }
  })

  const result = await controller.cancel("session-1")

  assert.deepEqual(calls, ["session-1"])
  assert.equal(result.status, "PAUSED")
  assert.match(result.reason, /interrupted|paused/i)
})

test("goal cancel blocks when OpenCode cannot confirm interruption", async () => {
  const { controller } = fixture(async () => ({ data: { interrupted: false } }))

  const result = await controller.cancel("session-1")

  assert.equal(result.status, "BLOCKED")
  assert.equal(result.outcomeUnknown, true)
})

test("goal pause interrupts an active OpenCode session before pausing", async () => {
  const calls = []
  const { controller } = fixture(async (sessionID) => {
    calls.push(sessionID)
    return { data: { interrupted: true } }
  })

  const result = await controller.pause("session-1")

  assert.deepEqual(calls, ["session-1"])
  assert.equal(result.status, "PAUSED")
})

test("goal pause blocks when OpenCode cannot confirm interruption", async () => {
  const { controller } = fixture(async () => ({ data: { interrupted: false } }))

  const result = await controller.pause("session-1")

  assert.equal(result.status, "BLOCKED")
  assert.equal(result.outcomeUnknown, true)
})

test("goal pause does not interrupt a terminal session", async () => {
  const calls = []
  const { state, controller } = fixture(async (sessionID) => {
    calls.push(sessionID)
    return { data: { interrupted: true } }
  })
  state.status = "DONE"

  const result = await controller.pause("session-1")

  assert.deepEqual(calls, [])
  assert.equal(result.status, "DONE")
})

test("goal verification retries an unknown request with the same idempotency key", async () => {
  const calls = []
  const { controller, values } = fixture(undefined, {
    getBoundTaskImpl: async () => ({ success: true }),
    runProjectCommandImpl: async (_state, sessionID, alias, requestId) => {
      calls.push({ sessionID, alias, requestId })
      return calls.length === 1
        ? { success: false, outcome_unknown: true }
        : { success: true, receipt: { passed: true } }
    },
  })

  const first = await controller.verifyProject("session-1", "pytest")
  const second = await controller.verifyProject("session-1", "pytest")

  assert.equal(first.outcome_unknown, true)
  assert.equal(second.success, true)
  assert.equal(calls.length, 2)
  assert.equal(calls[0].requestId, calls[1].requestId)
  assert.deepEqual(calls[1], { ...calls[0], alias: "pytest" })
  assert.equal(values.get("goal-verify:session-1").status, "settled")
})

test("goal resume reconciles a pending verification without repeating its command", async () => {
  const calls = []
  const { state, values, controller } = fixture(undefined, {
    getBoundTaskImpl: async () => ({ success: true }),
    runProjectCommandImpl: async (_state, sessionID, alias, requestId) => {
      calls.push({ sessionID, alias, requestId })
      return { success: true, receipt: { passed: true } }
    },
  })
  state.status = "BLOCKED"
  state.outcomeUnknown = true
  state.reason = "verification outcome is unknown"
  state.epoch = "epoch-after-interruption"
  values.set("goal-verify:session-1", {
    status: "pending", requestId: "a".repeat(32), alias: "pytest", root: state.root,
    taskId: state.taskId, sessionId: "session-1", epoch: "epoch-before-interruption",
  })

  const result = await controller.resume("session-1")

  assert.equal(calls.length, 1)
  assert.equal(calls[0].requestId, "a".repeat(32))
  assert.equal(result.status, "PAUSED")
  assert.equal(result.outcomeUnknown, undefined)
  assert.equal(values.get("goal-verify:session-1").status, "settled")
})
