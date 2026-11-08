import { createHash, randomUUID } from "node:crypto"
import { realpath } from "node:fs/promises"
import { createGoal, pauseGoal, resumeGoal, settleGoal } from "./core.js"
import { completeTask, createTask, getBoundTask, getCompletedTask, runProjectCommand, validateTransportOptions } from "./transport.js"

// Controllers loaded from this module share admission and state-write locks.
// Separate module instances or processes still require an external fence.
const inFlight = new Map()
const locks = new Map()

// State belongs to an OpenCode session, not to the plugin's load location.
export function makeGoalController(ctx, { resolveRoot = realpath, completeTaskImpl = completeTask, createTaskImpl = createTask, getBoundTaskImpl = getBoundTask, getCompletedTaskImpl = getCompletedTask, runProjectCommandImpl = runProjectCommand, transport = {} } = {}) {
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
  const promptText = (state) => `Continue the goal: ${state.goal}\nTask ID: ${state.taskId}\nAcceptance criteria:\n${state.criteria.map((c) => `- ${c}`).join("\n")}\nUse goal_verify with a configured verification alias to obtain authentic Agent OS receipts; do not claim completion without evidence.`
  const prompt = (id, state, delivery, promptId) => ctx.session.prompt({
    sessionID: id, delivery, id: promptId,
    text: promptText(state),
  })
  async function promptOrBlock(id, state, delivery) {
    if (!eventStreamAvailable) throw new Error("goal event stream is unavailable")
    const flight = inFlight.get(id)
    if (flight) flight.prompting = true
    try {
      const promptId = `msg_${randomUUID().replaceAll("-", "")}`
      const recorded = await locked(id, async () => {
        const current = await read(id)
        if (current?.status !== "CONTINUE" || current.epoch !== state.epoch || flight?.controller.signal.aborted) return false
        await write(id, { ...current, status: "BLOCKED", outcomeUnknown: true, pendingOperation: "prompt_admission",
          pendingPromptId: promptId, pendingDelivery: delivery ?? null,
          reason: "prompt admission outcome is unknown; inspect the session before retrying" })
        return true
      })
      if (!recorded || flight?.controller.signal.aborted || !eventStreamAvailable) return
      const admission = await prompt(id, state, delivery, promptId)
      if (admission?.id !== promptId || admission?.sessionID !== id || admission?.type !== "user" ||
          admission?.payload?.text !== promptText(state)) return
      await locked(id, async () => {
        const current = await read(id)
        if (current?.status === "BLOCKED" && current.epoch === state.epoch &&
            current.pendingOperation === "prompt_admission" && !flight?.controller.signal.aborted) {
          const { outcomeUnknown: _outcomeUnknown, pendingOperation: _pendingOperation,
            pendingPromptId: _pendingPromptId, pendingDelivery: _pendingDelivery, ...confirmed } = current
          await write(id, { ...confirmed, status: "CONTINUE", reason: state.reason })
        }
      })
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
      if (state.status === "BLOCKED" && state.pendingOperation === "prompt_admission" && state.outcomeUnknown === true &&
          typeof state.pendingPromptId === "string" && /^msg_[a-f0-9]{32}$/.test(state.pendingPromptId)) {
        let binding, history, session
        try {
          binding = await getBoundTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
          if (binding?.success !== true) return await read(id)
          history = await ctx.session.context({ sessionID: id })
          session = await ctx.session.get({ sessionID: id })
        } catch { return await read(id) }
        if (flight.controller.signal.aborted || !Array.isArray(history) || session?.id !== id ||
            session.outcome !== "succeeded" || !Number.isFinite(session.time?.busy) ||
            !Number.isFinite(session.time?.idle) || session.time.idle < session.time.busy) return await read(id)
        const matches = history.filter((message) => message?.id === state.pendingPromptId)
        const promptIndex = history.findIndex((message) => message?.id === state.pendingPromptId)
        const tail = history.at(-1)
        const afterPrompt = history.slice(promptIndex + 1)
        if (matches.length !== 1 || matches[0]?.type !== "user" || matches[0]?.text !== promptText(state) ||
            promptIndex >= history.length - 1 || afterPrompt.some((message) => message?.type === "user") ||
            afterPrompt.filter((message) => message?.type === "idle").length !== 1 ||
            tail?.type !== "idle" || tail?.outcome !== "succeeded" || typeof tail.id !== "string" || !tail.id) return await read(id)
        return await locked(id, async () => {
          const current = await read(id)
          if (!current || current.status !== "BLOCKED" || current.epoch !== state.epoch ||
              current.pendingOperation !== "prompt_admission" || current.pendingPromptId !== state.pendingPromptId ||
              current.outcomeUnknown !== true || flight.controller.signal.aborted) return current
          const { outcomeUnknown: _outcomeUnknown, pendingOperation: _pendingOperation,
            pendingPromptId: _pendingPromptId, pendingDelivery: _pendingDelivery, ...confirmed } = current
          const updated = { ...confirmed, status: "PAUSED", reason: "prompt execution confirmed; resume to continue" }
          await write(id, updated)
          return updated
        })
      }
      if (state.pendingOperation === "task_complete" && state.outcomeUnknown === true &&
          typeof state.pendingEventId === "string" && state.pendingEventId) {
        let checked
        try { checked = await getCompletedTaskImpl(state, id, { ...transport, signal: flight.controller.signal }) }
        catch { return await read(id) }
        if (checked?.success !== true || flight.controller.signal.aborted) return await read(id)
        return await locked(id, async () => {
          const current = await read(id)
          if (!current || current.epoch !== state.epoch || current.pendingOperation !== "task_complete" ||
              current.pendingEventId !== state.pendingEventId || current.outcomeUnknown !== true || flight.controller.signal.aborted) return current
          const { outcomeUnknown: _outcomeUnknown, pendingOperation: _pendingOperation, pendingEventId, ...confirmed } = current
          const updated = settleGoal({ ...confirmed, status: "CONTINUE" }, { id: pendingEventId, type: "succeeded", verification: checked })
          if (updated.status !== "DONE") return current
          await write(id, updated)
          return updated
        })
      }
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
              onMutationStart: async () => {
                flight.mutating = true
                return locked(id, async () => {
                  const current = await read(id)
                  if (current?.status !== "CONTINUE" || current.epoch !== state.epoch || flight.controller.signal.aborted) return false
                  await write(id, { ...current, status: "BLOCKED", outcomeUnknown: true, pendingOperation: "task_complete", pendingEventId: event.id,
                    reason: "task completion outcome is unknown; inspect Agent OS before retrying" })
                  return true
                })
              },
            })
          : { success: false, verification_unavailable: true }
      }
      const next = await locked(id, async () => {
        const current = await read(id)
        if (!current || current.epoch !== state.epoch || flight.controller.signal.aborted) return undefined
        let base = current
        if (current.status === "BLOCKED" && current.pendingOperation === "task_complete" && current.outcomeUnknown === true) {
          const { outcomeUnknown: _outcomeUnknown, pendingOperation: _pendingOperation, pendingEventId: _pendingEventId, ...confirmed } = current
          base = { ...confirmed, status: "CONTINUE" }
          const candidate = settleGoal(base, { id: event.id, type, verification, observation })
          if (candidate.status !== "DONE") return undefined
        } else if (current.status !== "CONTINUE") return undefined
        const updated = settleGoal(base, { id: event.id, type, verification, observation })
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
  async function verifyProject(id, alias, signal) {
    if (typeof alias !== "string" || !alias || alias !== alias.trim() || alias.length > 128) throw new Error("invalid verification alias")
    if (inFlight.has(id)) throw new Error("another goal operation is in progress")
    const flight = { controller: new AbortController(), mutating: false, events: [] }
    const cancel = () => flight.controller.abort()
    if (signal?.aborted) cancel()
    else signal?.addEventListener("abort", cancel, { once: true })
    inFlight.set(id, flight)
    try {
      const state = await read(id)
      if (!state || state.status !== "CONTINUE" || state.outcomeUnknown) throw new Error("goal is not ready for verification")
      const verifyKey = `goal-verify:${id}`
      const previous = await ctx.storage.get(verifyKey)
      if (previous && previous.status !== "settled") return { success: false, outcome_unknown: true, request_id: previous.requestId, error: "previous verification outcome is unknown" }
      if (await sessionRoot(id) !== state.root) throw new Error("session directory no longer matches the goal")
      const binding = await getBoundTaskImpl(state, id, { ...transport, signal: flight.controller.signal })
      if (binding?.success !== true || flight.controller.signal.aborted) throw new Error("task binding could not be verified")
      const requestId = randomUUID().replaceAll("-", "")
      const admitted = await locked(id, async () => {
        const current = await read(id)
        if (current?.status !== "CONTINUE" || current.epoch !== state.epoch || flight.controller.signal.aborted) return false
        await ctx.storage.set(verifyKey, { status: "pending", requestId, alias, root: state.root, taskId: state.taskId, sessionId: id, epoch: state.epoch })
        flight.mutating = true
        return true
      })
      if (!admitted || flight.controller.signal.aborted) return { success: false, outcome_unknown: true, request_id: requestId }
      let result
      try { result = await runProjectCommandImpl(state, id, alias, requestId, { ...transport, signal: flight.controller.signal }) }
      catch { result = { success: false, outcome_unknown: true, error: "verification outcome is unknown" } }
      if (!result || typeof result.success !== "boolean" || result.outcome_unknown || result.in_progress || flight.controller.signal.aborted) {
        return { success: false, outcome_unknown: true, request_id: requestId, error: "verification outcome is unknown" }
      }
      await locked(id, async () => {
        const current = await read(id)
        if (current?.epoch === state.epoch && current.status === "CONTINUE" && !flight.controller.signal.aborted) {
          await ctx.storage.set(verifyKey, { status: "settled", requestId, alias, root: state.root, taskId: state.taskId, sessionId: id, epoch: state.epoch })
        }
      })
      return { ...result, request_id: requestId }
    } finally { signal?.removeEventListener("abort", cancel); finishFlight(id, flight) }
  }
  return { start, pause, resume, settle, observeStep, eventStreamLost, verifyProject, status: read }
}

export default {
  id: "local-ai-hub.goal",
  async setup(ctx) {
    if (ctx.options && Object.hasOwn(ctx.options, "tokenEnv")) throw new Error("Hub tokenEnv option was removed")
    const settings = { baseURL: ctx.options?.hubURL, actor: ctx.options?.actor ?? "opencode-local" }
    validateTransportOptions(settings)
    const controller = makeGoalController(ctx, { transport: settings })
    await ctx.tool.transform((editor) => editor.add({
      name: "goal_verify",
      description: "Run a configured project verification for the current goal and record its authentic receipt.",
      options: { codemode: false },
      input: { type: "object", properties: { alias: { type: "string", minLength: 1, maxLength: 128 } }, required: ["alias"], additionalProperties: false },
      execute: async ({ alias }, context) => {
        await ctx.permission.assert({ sessionID: context.sessionID, agent: context.agent,
          source: { type: "tool", messageID: context.messageID, id: context.id },
          action: "shell", resources: [alias], save: [alias] })
        return { content: JSON.stringify(await controller.verifyProject(context.sessionID, alias, context.signal)) }
      },
    }))
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
