import { createHash, randomUUID } from "node:crypto"
import { realpath } from "node:fs/promises"
import { createGoal, pauseGoal, resumeGoal, settleGoal } from "./core.js"
import { completeTask, createTask, getBoundTask, validateTransportOptions } from "./transport.js"

// Controllers loaded from this module share admission and state-write locks.
// Separate module instances or processes still require an external fence.
const inFlight = new Map()
const locks = new Map()

// State belongs to an OpenCode session, not to the plugin's load location.
export function makeGoalController(ctx, { resolveRoot = realpath, completeTaskImpl = completeTask, createTaskImpl = createTask, getBoundTaskImpl = getBoundTask, transport = {} } = {}) {
  const knownSessions = new Set()
  const stepSnapshots = new Map()
  const completedSequences = new Map()
  let eventStreamAvailable = true
  const key = (id) => `goal:${id}`
  const read = (id) => ctx.storage.get(key(id))
  const write = (id, state) => ctx.storage.set(key(id), state)
  function finishFlight(id, flight) {
    if (inFlight.get(id) !== flight) return
    inFlight.delete(id)
    if (flight.events?.length) {
      void (async () => { for (const item of flight.events) await settle(item.event, item.step) })().catch(() => {})
    }
  }
  async function locked(id, action) {
    const previous = locks.get(id) ?? Promise.resolve()
    let release
    const next = new Promise((resolve) => { release = resolve })
    locks.set(id, next)
    await previous
    try { return await action() } finally {
      release()
      if (locks.get(id) === next) locks.delete(id)
    }
  }
  const sessionRoot = async (id) => {
    const session = await ctx.session.get({ sessionID: id })
    if (typeof session?.location?.directory !== "string") throw new Error("session directory unavailable")
    return resolveRoot(session.location.directory)
  }
  const prompt = (id, state, delivery) => ctx.session.prompt({
    sessionID: id, delivery,
    text: `Continue the goal: ${state.goal}\nTask ID: ${state.taskId}\nAcceptance criteria:\n${state.criteria.map((c) => `- ${c}`).join("\n")}\nUse authentic Agent OS verification receipts; do not claim completion without evidence.`,
  })
  async function promptOrBlock(id, state, delivery) {
    if (!eventStreamAvailable) throw new Error("goal event stream is unavailable")
    const flight = inFlight.get(id)
    if (flight) flight.prompting = true
    try {
      await prompt(id, state, delivery)
    } catch (error) {
      await locked(id, async () => {
        const current = await read(id)
        if (current?.status === "CONTINUE" && current.epoch === state.epoch) {
          await write(id, { ...current, status: "BLOCKED", outcomeUnknown: true, reason: "prompt admission outcome is unknown; inspect the session before retrying" })
        }
      })
      throw error
    } finally {
      if (flight) flight.prompting = false
    }
  }
  async function start(id, spec, delivery) {
    if (!eventStreamAvailable) throw new Error("goal event stream is unavailable")
    knownSessions.add(id)
    if (inFlight.has(id)) throw new Error("a goal operation is already running for this session")
    stepSnapshots.delete(id)
    const flight = { controller: new AbortController(), mutating: false, events: [] }
    inFlight.set(id, flight)
    let state
    try {
      if (await read(id)) throw new Error("a goal already exists for this session")
      const root = await sessionRoot(id)
      const needsTask = spec?.taskId === undefined
      state = { ...createGoal({ ...spec, taskId: needsTask ? `goal-${randomUUID()}` : spec.taskId, root }), epoch: randomUUID() }
      if (flight.controller.signal.aborted) return await read(id)
      if (needsTask) {
        state = { ...state, status: "BLOCKED", outcomeUnknown: true, pendingOperation: "task_create", reason: "task creation pending; inspect Agent OS before retrying" }
        await locked(id, async () => write(id, state))
        if (flight.controller.signal.aborted) return await read(id)
        flight.mutating = true
        const result = await createTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
        if (result?.success !== true) throw new Error("Agent OS task creation was not confirmed")
        state = await locked(id, async () => {
          const current = await read(id)
          if (!current || current.epoch !== state.epoch || current.status !== "BLOCKED" || flight.controller.signal.aborted) return current
          const { outcomeUnknown: _outcomeUnknown, pendingOperation: _pendingOperation, ...confirmed } = current
          const next = { ...confirmed, status: "CONTINUE", reason: "task created" }
          await write(id, next)
          return next
        })
        if (state?.status !== "CONTINUE" || flight.controller.signal.aborted) return await read(id)
        flight.mutating = false
      } else {
        state = { ...state, status: "BLOCKED", bindingUnverified: true, reason: "verifying existing Agent OS task binding" }
        await locked(id, async () => write(id, state))
        if (flight.controller.signal.aborted) return await read(id)
        const result = await getBoundTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
        if (result?.success !== true) {
          return await locked(id, async () => {
            const current = await read(id)
            if (!current || current.epoch !== state.epoch || flight.controller.signal.aborted) return current
            const blocked = { ...current, reason: "existing task binding could not be verified" }
            await write(id, blocked)
            return blocked
          })
        }
        state = await locked(id, async () => {
          const current = await read(id)
          if (!current || current.epoch !== state.epoch || current.status !== "BLOCKED" || flight.controller.signal.aborted) return current
          const { bindingUnverified: _bindingUnverified, ...confirmed } = current
          const next = { ...confirmed, status: "CONTINUE", reason: "existing task binding verified" }
          await write(id, next)
          return next
        })
        if (state?.status !== "CONTINUE" || flight.controller.signal.aborted) return await read(id)
      }
      if (flight.controller.signal.aborted) return await read(id)
      await promptOrBlock(id, state, delivery)
      return await read(id)
    } finally {
      finishFlight(id, flight)
    }
  }
  async function pause(id) {
    const flight = inFlight.get(id)
    const uncertain = flight?.mutating === true || flight?.prompting === true
    flight?.controller.abort()
    return locked(id, async () => {
      const state = await read(id)
      if (!state) throw new Error("no goal for this session")
      const paused = { ...pauseGoal(state), epoch: randomUUID(), ...(uncertain ? { outcomeUnknown: true, reason: "request outcome is unknown; inspect the session and Agent OS before retrying" } : {}) }
      await write(id, paused)
      return paused
    })
  }
  async function resume(id, delivery) {
    if (!eventStreamAvailable) throw new Error("goal event stream is unavailable")
    knownSessions.add(id)
    if (inFlight.has(id)) return read(id)
    stepSnapshots.delete(id)
    const flight = { controller: new AbortController(), mutating: false, events: [] }
    inFlight.set(id, flight)
    try {
      let state = await read(id)
      if (!state) throw new Error("no goal for this session")
      if (state.status === "CONTINUE") return state
      if (await sessionRoot(id) !== state.root) throw new Error("session directory no longer matches the goal")
      if (state.pendingOperation === "task_create" && state.outcomeUnknown === true) {
        const checked = await getBoundTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
        if (checked?.success !== true || flight.controller.signal.aborted) return await read(id)
        state = await locked(id, async () => {
          const current = await read(id)
          if (!current || current.epoch !== state.epoch || current.pendingOperation !== "task_create" ||
              current.outcomeUnknown !== true || flight.controller.signal.aborted) return current
          const { outcomeUnknown: _outcomeUnknown, pendingOperation: _pendingOperation, ...confirmed } = current
          const updated = { ...confirmed, status: "PAUSED", reason: "created task binding verified" }
          await write(id, updated)
          return updated
        })
        if (!state || state.pendingOperation === "task_create" || flight.controller.signal.aborted) return await read(id)
      }
      if (state.bindingUnverified === true) {
        const checked = await getBoundTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
        if (checked?.success !== true || flight.controller.signal.aborted) return await read(id)
        state = await locked(id, async () => {
          const current = await read(id)
          if (!current || current.epoch !== state.epoch || flight.controller.signal.aborted) return current
          const { bindingUnverified: _bindingUnverified, ...confirmed } = current
          const updated = { ...confirmed, status: "PAUSED", reason: "existing task binding verified" }
          await write(id, updated)
          return updated
        })
        if (!state || state.bindingUnverified === true || flight.controller.signal.aborted) return await read(id)
      }
      const next = await locked(id, async () => {
        const current = await read(id)
        if (!current || current.epoch !== state.epoch || flight.controller.signal.aborted) return current
        const updated = { ...resumeGoal(current), epoch: randomUUID() }
        await write(id, updated)
        return updated
      })
      if (next?.status === "CONTINUE" && !flight.controller.signal.aborted) await promptOrBlock(id, next, delivery)
      return await read(id)
    } finally {
      finishFlight(id, flight)
    }
  }
  function observeStep(event) {
    const id = event?.data?.sessionID
    if (!eventStreamAvailable || event?.type !== "session.step.ended" || !knownSessions.has(id)) return
    const seq = event?.durable?.seq
    const snapshot = event?.data?.snapshot
    if (event?.durable?.aggregateID !== id || !Number.isSafeInteger(seq) || seq < 0 ||
        typeof snapshot !== "string" || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(snapshot)) {
      stepSnapshots.delete(id)
      return
    }
    const previous = stepSnapshots.get(id)
    if (seq <= (completedSequences.get(id) ?? -1)) return
    if (!previous || seq > previous.seq) stepSnapshots.set(id, { seq, snapshot })
  }
  async function settle(event, savedStep = undefined) {
    const id = event?.data?.sessionID
    if (typeof id !== "string" || typeof event?.id !== "string") return
    if (!eventStreamAvailable) return
    let step = savedStep
    if (step === undefined) {
      step = null
      const candidate = stepSnapshots.get(id)
      const seq = event?.durable?.seq
      if (event?.durable?.aggregateID === id && Number.isSafeInteger(seq)) {
        if (seq <= (completedSequences.get(id) ?? -1)) return
        completedSequences.set(id, seq)
      }
      if (event.type === "session.execution.succeeded" && candidate && event?.durable?.aggregateID === id &&
          Number.isSafeInteger(seq) && seq > candidate.seq) step = candidate
      stepSnapshots.delete(id)
    }
    if (event.type === "session.execution.interrupted" && inFlight.has(id)) {
      await pause(id)
      return
    }
    if (inFlight.has(id)) {
      const active = inFlight.get(id)
      if (active.prompting && ["session.execution.succeeded", "session.execution.failed"].includes(event.type) && !active.events.some((item) => item.event.id === event.id)) {
        if (active.events.length >= 32) { await pause(id); return }
        active.events.push({ event, step })
      }
      return
    }
    const flight = { controller: new AbortController(), mutating: false, events: [] }
    inFlight.set(id, flight)
    let state
    try {
      state = await read(id)
      if (!state || state.status !== "CONTINUE" || state.eventIds.includes(event.id)) return
      knownSessions.add(id)
      if (await sessionRoot(id) !== state.root) {
        await locked(id, async () => {
          const current = await read(id)
          if (current?.status === "CONTINUE" && current.epoch === state.epoch && !flight.controller.signal.aborted) {
            await write(id, { ...current, status: "BLOCKED", reason: "session directory changed" })
          }
        })
        return
      }
      const type = event.type === "session.execution.succeeded" ? "succeeded" : event.type === "session.execution.failed" ? "failed" : event.type === "session.execution.interrupted" ? "interrupted" : ""
      if (!type) return
      let verification
      let observation
      if (type === "succeeded") {
        const binding = await getBoundTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
        const checkpoint = binding?.task?.checkpoint
        if (step && binding?.success === true && checkpoint && typeof checkpoint === "object" && !Array.isArray(checkpoint)) {
          observation = createHash("sha256").update(JSON.stringify([step.snapshot, checkpoint])).digest("hex")
        }
        verification = binding?.success === true
          ? await completeTaskImpl(state, {
              ...transport, sessionId: id, signal: flight.controller.signal,
              canCommit: async () => { const current = await read(id); return current?.status === "CONTINUE" && current.epoch === state.epoch },
              onMutationStart: () => { flight.mutating = true },
            })
          : { success: false, verification_unavailable: true }
      }
      const next = await locked(id, async () => {
        const current = await read(id)
        if (!current || current.status !== "CONTINUE" || current.epoch !== state.epoch || flight.controller.signal.aborted) return undefined
        const updated = settleGoal(current, { id: event.id, type, verification, observation })
        await write(id, updated)
        return updated
      })
      if (!next) return
      const latest = await read(id)
      if (next.status === "CONTINUE" && latest?.status === "CONTINUE" && latest.epoch === state.epoch && !flight.controller.signal.aborted) await promptOrBlock(id, next)
    } catch (error) {
      if (!state) throw error
      await locked(id, async () => {
        const current = await read(id)
        if (current?.status === "CONTINUE" && current.epoch === state.epoch && !flight.controller.signal.aborted) {
          await write(id, { ...current, status: "BLOCKED", reason: flight.mutating ? "completion outcome is unknown; inspect Agent OS before retrying" : "goal execution or verification failed", ...(flight.mutating ? { outcomeUnknown: true } : {}) })
        }
      })
    } finally {
      finishFlight(id, flight)
    }
  }
  async function eventStreamLost() {
    eventStreamAvailable = false
    stepSnapshots.clear()
    for (const id of knownSessions) inFlight.get(id)?.controller.abort()
    await Promise.all([...knownSessions].map((id) => locked(id, async () => {
      const current = await read(id)
      if (current?.status === "CONTINUE" || current?.status === "BLOCKED") {
        await write(id, { ...current, status: "BLOCKED", epoch: randomUUID(), outcomeUnknown: true,
          reason: "goal event stream stopped; inspect the session and Agent OS before retrying" })
      }
    })))
  }
  return { start, pause, resume, settle, observeStep, eventStreamLost, status: read }
}

export default {
  id: "local-ai-hub.goal",
  async setup(ctx) {
    const tokenEnv = ctx.options?.tokenEnv
    if (tokenEnv !== undefined && (typeof tokenEnv !== "string" || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(tokenEnv))) throw new Error("invalid token environment name")
    if (tokenEnv && !process.env[tokenEnv]) throw new Error("configured Hub token environment variable is empty or missing")
    const settings = { baseURL: ctx.options?.hubURL, token: tokenEnv ? process.env[tokenEnv] : "", actor: ctx.options?.actor ?? "opencode-local" }
    validateTransportOptions(settings)
    const controller = makeGoalController(ctx, { transport: settings })
    await ctx.command.transform((editor) => editor.add({
      name: "goal",
      description: "Receipt-gated goal: /goal {\"goal\":\"...\",\"criteria\":[\"...\"],\"taskId\":\"optional\"}; status, pause, resume",
      execute: async ({ sessionID, prompt, delivery }) => {
        const text = String(prompt.text ?? "").replace(/^\s*\/goal\b/i, "").trim()
        if (text === "pause") { await controller.pause(sessionID); return }
        if (text === "resume") { await controller.resume(sessionID, delivery); return }
        if (!text || text === "status") {
          const state = await controller.status(sessionID)
          const summary = state ? { status: state.status, reason: state.reason, turns: state.turns, maxTurns: state.maxTurns } : { status: "NO_GOAL" }
          throw new Error(`Goal status: ${JSON.stringify(summary)}`)
        }
        await controller.start(sessionID, JSON.parse(text), delivery)
      },
    }))
    const abort = new AbortController()
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: abort.signal })) {
          if (event.type === "session.step.ended") controller.observeStep(event)
          if (["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"].includes(event.type)) {
            void controller.settle(event).catch(() => {})
          }
        }
      } catch { /* A failed stream is handled identically to a closed stream. */ }
      finally { await controller.eventStreamLost().catch(() => {}) }
    })()
    return () => abort.abort()
  },
}
