import { spawn } from "node:child_process"
import { StringDecoder } from "node:string_decoder"
import path from "node:path"

const MAX_LINE = 4 * 1024 * 1024
const MAX_PENDING = 16
const MAX_TOOLS = 256
const REQUEST_TIMEOUT_MS = 60000
const HOOK_TIMEOUT_MS = 4000
const MAX_HOOK_OUTPUT = 65536
const MAX_STATIC_HOOKS = 4
const OPENCODE_EDIT_TOOLS = new Set(["edit", "write", "apply_patch", "edit_file", "write_file", "replace"])
const CORE_HUB_TOOLS = new Set([
  "local_ai_status",
  "local_ai_repo",
  "local_ai_task",
  "local_ai_coord",
  "local_ai_artifact",
  "local_ai_rag",
])
const OPTIONAL_HUB_TOOLS = new Set(["local_ai_work"])

export function selectHubTools(catalogTools) {
  if (!Array.isArray(catalogTools)) throw new Error("invalid Local AI Hub MCP catalog")
  const names = new Set(catalogTools.map(tool => tool?.name))
  if ([...CORE_HUB_TOOLS].some(name => !names.has(name))) {
    throw new Error("Local AI Hub MCP catalog is missing a core tool")
  }
  return catalogTools.filter(tool => CORE_HUB_TOOLS.has(tool?.name) || OPTIONAL_HUB_TOOLS.has(tool?.name))
}

export function usesNativeMcp(server) {
  return server?.nativeMcp === true
}

export function opencodeEditedPath(tool, input) {
  if (typeof tool !== "string" || !OPENCODE_EDIT_TOOLS.has(tool.toLowerCase()) || !input || typeof input !== "object") return null
  const file = input.file_path ?? input.filePath ?? input.path ?? input.target
  return typeof file === "string" && path.isAbsolute(file) && Buffer.byteLength(file, "utf8") <= 4096 ? file : null
}

export function opencodePermissionCommand(event) {
  if (event?.action !== "shell" || !Array.isArray(event.resources) || event.resources.length < 1 || event.resources.length > 16) return null
  if (event.resources.some(value => typeof value !== "string" || !value.trim() || Buffer.byteLength(value, "utf8") > 4096)) return null
  const command = event.resources.join("\n")
  return Buffer.byteLength(command, "utf8") <= 4096 ? command : null
}

export function opencodePreToolTarget(tool, input) {
  if (typeof tool !== "string" || !input || typeof input !== "object") return null
  const toolLower = tool.toLowerCase()
  if (toolLower === "bash" || toolLower === "shell") {
    const cmd = input.command ?? input.cmd ?? input.CommandLine
    return typeof cmd === "string" && cmd.trim() && Buffer.byteLength(cmd, "utf8") <= 4096 ? { type: "command", target: cmd } : null
  }
  if (OPENCODE_EDIT_TOOLS.has(toolLower)) {
    const file = input.file_path ?? input.filePath ?? input.path ?? input.target
    return typeof file === "string" && path.isAbsolute(file) && Buffer.byteLength(file, "utf8") <= 4096 ? { type: "file", target: file } : null
  }
  return null
}

function runOpenCodePostEditCheck(server, root, event, active) {
  const file = opencodeEditedPath(event?.tool, event?.input)
  if (!file || typeof root !== "string" || !path.isAbsolute(root) || active.count >= MAX_STATIC_HOOKS) return Promise.resolve(null)
  active.count += 1
  return new Promise(resolve => {
    let settled = false
    let output = ""
    let timer = null
    const finish = value => {
      if (settled) return
      settled = true
      if (timer !== null) clearTimeout(timer)
      active.count = Math.max(0, active.count - 1)
      resolve(value)
    }
    let child
    try {
      child = spawn(server.command[0], ["-m", "local_ai_hub.repo_plan.host_hooks", "--root", root,
        "--host", "opencode", "--event", "PostToolUse"], {
        cwd: server.cwd,
        env: { ...process.env, ...server.environment, LOCAL_AI_AGENT: "opencode", LOCAL_AI_AGENT_PROFILE: "opencode" },
        stdio: ["pipe", "pipe", "ignore"],
        windowsHide: true,
      })
    } catch { finish(null); return }
    timer = setTimeout(() => {
      child.kill()
      finish(null)
    }, HOOK_TIMEOUT_MS)
    child.stdout.on("data", chunk => {
      output += chunk.toString("utf8")
      if (Buffer.byteLength(output, "utf8") > MAX_HOOK_OUTPUT) {
        child.kill()
        finish(null)
      }
    })
    child.stdout.on("error", () => finish(null))
    child.on("error", () => finish(null))
    child.on("close", code => {
      if (code !== 0) return finish(null)
      try {
        const result = JSON.parse(output)
        finish(typeof result?.additionalContext === "string" ? result.additionalContext.slice(0, 1600) : null)
      } catch { finish(null) }
    })
    child.stdin.on("error", () => finish(null))
    try {
      child.stdin.end(JSON.stringify({
        hook_event_name: "PostToolUse",
        session_id: typeof event.sessionID === "string" ? event.sessionID.slice(0, 200) : "",
        cwd: root,
        tool_name: event.tool,
        tool_input: { file_path: file },
      }))
    } catch {
      child.kill()
      finish(null)
    }
  })
}

function runOpenCodePermissionCheck(server, root, event, active) {
  if (typeof root !== "string" || !path.isAbsolute(root) || active.count >= MAX_STATIC_HOOKS) return Promise.resolve(null)
  const command = opencodePermissionCommand(event)
  if (!command) return Promise.resolve(null)
  active.count += 1
  return new Promise(resolve => {
    let settled = false
    let output = ""
    let timer = null
    const finish = value => {
      if (settled) return
      settled = true
      if (timer !== null) clearTimeout(timer)
      active.count = Math.max(0, active.count - 1)
      resolve(value)
    }
    let child
    try {
      child = spawn(server.command[0], ["-m", "local_ai_hub.repo_plan.host_hooks", "--root", root,
        "--host", "opencode", "--event", "PermissionRequest"], {
        cwd: server.cwd,
        env: { ...process.env, ...server.environment, LOCAL_AI_AGENT: "opencode", LOCAL_AI_AGENT_PROFILE: "opencode" },
        stdio: ["pipe", "pipe", "ignore"],
        windowsHide: true,
      })
    } catch { finish(null); return }
    timer = setTimeout(() => { child.kill(); finish(null) }, HOOK_TIMEOUT_MS)
    child.stdout.on("data", chunk => {
      output += chunk.toString("utf8")
      if (Buffer.byteLength(output, "utf8") > MAX_HOOK_OUTPUT) { child.kill(); finish(null) }
    })
    child.stdout.on("error", () => finish(null))
    child.on("error", () => finish(null))
    child.on("close", code => {
      if (code !== 0) return finish(null)
      try {
        const result = JSON.parse(output)
        finish(result?.decision === "deny" && typeof result.reason === "string" ? result.reason.slice(0, 1600) : null)
      } catch { finish(null) }
    })
    child.stdin.on("error", () => finish(null))
    try {
      child.stdin.end(JSON.stringify({
        hook_event_name: "PermissionRequest",
        session_id: typeof event.sessionID === "string" ? event.sessionID.slice(0, 200) : "",
        cwd: root,
        tool_name: "Bash",
        tool_input: { command },
      }))
    } catch { child.kill(); finish(null) }
  })
}

function runOpenCodeProactiveContext(server, root, sessionID, active) {
  if (typeof root !== "string" || !path.isAbsolute(root) || active.count >= MAX_STATIC_HOOKS) return Promise.resolve(null)
  active.count += 1
  return new Promise(resolve => {
    let settled = false
    let output = ""
    let timer = null
    const finish = value => {
      if (settled) return
      settled = true
      if (timer !== null) clearTimeout(timer)
      active.count = Math.max(0, active.count - 1)
      resolve(value)
    }
    let child
    try {
      child = spawn(server.command[0], ["-m", "local_ai_hub.repo_plan.host_hooks", "--root", root,
        "--host", "opencode", "--event", "UserPromptSubmit"], {
        cwd: server.cwd,
        env: { ...process.env, ...server.environment, LOCAL_AI_AGENT: "opencode", LOCAL_AI_AGENT_PROFILE: "opencode" },
        stdio: ["pipe", "pipe", "ignore"],
        windowsHide: true,
      })
    } catch { finish(null); return }
    timer = setTimeout(() => { child.kill(); finish(null) }, HOOK_TIMEOUT_MS)
    child.stdout.on("data", chunk => {
      output += chunk.toString("utf8")
      if (Buffer.byteLength(output, "utf8") > MAX_HOOK_OUTPUT) { child.kill(); finish(null) }
    })
    child.stdout.on("error", () => finish(null))
    child.on("error", () => finish(null))
    child.on("close", code => {
      if (code !== 0) return finish(null)
      try {
        const result = JSON.parse(output)
        finish(typeof result?.additionalContext === "string" ? result.additionalContext.slice(0, 3200) : null)
      } catch { finish(null) }
    })
    child.stdin.on("error", () => finish(null))
    try {
      child.stdin.end(JSON.stringify({
        hook_event_name: "UserPromptSubmit",
        session_id: typeof sessionID === "string" ? sessionID.slice(0, 200) : "",
        cwd: root,
      }))
    } catch { child.kill(); finish(null) }
  })
}

function runOpenCodePreToolCheck(server, root, event, active) {
  if (typeof root !== "string" || !path.isAbsolute(root) || active.count >= MAX_STATIC_HOOKS) return Promise.resolve(null)
  const target = opencodePreToolTarget(event?.tool, event?.input)
  if (!target) return Promise.resolve(null)
  active.count += 1
  return new Promise(resolve => {
    let settled = false
    let output = ""
    let timer = null
    const finish = value => {
      if (settled) return
      settled = true
      if (timer !== null) clearTimeout(timer)
      active.count = Math.max(0, active.count - 1)
      resolve(value)
    }
    let child
    try {
      child = spawn(server.command[0], ["-m", "local_ai_hub.repo_plan.host_hooks", "--root", root,
        "--host", "opencode", "--event", "PreToolUse"], {
        cwd: server.cwd,
        env: { ...process.env, ...server.environment, LOCAL_AI_AGENT: "opencode", LOCAL_AI_AGENT_PROFILE: "opencode" },
        stdio: ["pipe", "pipe", "ignore"],
        windowsHide: true,
      })
    } catch { finish(null); return }
    timer = setTimeout(() => { child.kill(); finish(null) }, HOOK_TIMEOUT_MS)
    child.stdout.on("data", chunk => {
      output += chunk.toString("utf8")
      if (Buffer.byteLength(output, "utf8") > MAX_HOOK_OUTPUT) { child.kill(); finish(null) }
    })
    child.stdout.on("error", () => finish(null))
    child.on("error", () => finish(null))
    child.on("close", code => {
      if (code !== 0) return finish(null)
      try {
        const result = JSON.parse(output)
        finish(result?.decision === "deny" && typeof result.reason === "string" ? result.reason.slice(0, 1600) : null)
      } catch { finish(null) }
    })
    child.stdin.on("error", () => finish(null))
    try {
      child.stdin.end(JSON.stringify({
        hook_event_name: "PreToolUse",
        session_id: typeof event.sessionID === "string" ? event.sessionID.slice(0, 200) : "",
        cwd: root,
        tool_name: event.tool,
        tool_input: event.input,
      }))
    } catch { child.kill(); finish(null) }
  })
}

export function appendPostEditContext(event, context) {
  if (!context || !event?.result || !Array.isArray(event.result.content)) return false
  event.result = {
    ...event.result,
    content: [...event.result.content, { type: "text", text: `Local AI Hub static check: ${context}` }],
  }
  return true
}

export function appendHubContextGuidance(event) {
  if (!Array.isArray(event?.system) || !event.tools || typeof event.tools !== "object") return false
  const names = Object.keys(event.tools)
  const hasHubTool = names.some(name => name.toLowerCase().includes("local_ai_"))
  const hasCodeMode = names.some(name => name.toLowerCase() === "execute")
  if (!hasHubTool && !hasCodeMode) return false
  if (event.system.some(part => typeof part?.text === "string" && part.text.includes("Local AI Hub guidance:"))) return false
  event.system.push({
    type: "text",
export function appendProactivePlanContext(event, planContext) {
  if (!planContext || !Array.isArray(event?.system)) return false
  if (event.system.some(part => typeof part?.text === "string" && part.text.includes("Local AI Hub Proactive Context:"))) return false
  event.system.push({
    type: "text",
    text: planContext,
  })
  return true
}

export function appendHubContextGuidance(event) {
  if (!Array.isArray(event?.system) || !event.tools || typeof event.tools !== "object") return false
  const names = Object.keys(event.tools)
  const hasHubTool = names.some(name => name.toLowerCase().includes("local_ai_"))
  const hasCodeMode = names.some(name => name.toLowerCase() === "execute")
  if (!hasHubTool && !hasCodeMode) return false
  if (event.system.some(part => typeof part?.text === "string" && part.text.includes("Local AI Hub guidance:"))) return false
  event.system.push({
    type: "text",
    text: hasCodeMode
      ? "Local AI Hub guidance: use Code Mode for Hub actions. Discover the tool catalog with top-level `await search({query: \"local_ai_repo\"})`; this helper is not under `tools`, so never call `tools.search`. Then call the Hub tool directly, for example `const result = await tools[\"local-ai-hub\"].local_ai_repo({action: \"search\", root: \"<absolute repository root>\", query: \"<specific question>\"}); const payload = result.structuredContent ?? result; return {request_id: payload.request_id, first_result_path: payload.results?.[0]?.path}`. Do not treat catalog discovery as repository search or depend on a guessed discovery-result shape. Do not stringify full Hub tool results. Use the exact `tools[\"local-ai-hub\"]` namespace; do not guess underscore namespaces or use `list_mcp_resources` to find tools. Use eligible Hub tools for typed Laya advice on bounded routing, context, or retrieval. Treat Laya output as advisory; it never grants access or overrides host permissions and deterministic validation."
      : "Local AI Hub guidance: use available Hub tools for indexed repository evidence and eligible typed Laya advice on bounded routing, context, or retrieval. Prioritize local-ai MCP tools (local_ai_repo) over broad shell execution for repository discovery. For code inspection, use local_ai_artifact bounded slices. Mint authentic receipts with local_ai_coord before claiming completion. Treat Laya output as advisory; it never grants access or overrides host permissions and deterministic validation.",
  })
  return true
}

export function openMcp(server) {
  if (!server || !Array.isArray(server.command) || server.command.length !== 3 ||
      typeof server.command[0] !== "string" || !path.isAbsolute(server.command[0]) ||
      server.command[1] !== "-m" || server.command[2] !== "local_ai_hub.mcp_server" ||
      typeof server.cwd !== "string" || !path.isAbsolute(server.cwd) ||
      !server.environment || typeof server.environment !== "object" || Array.isArray(server.environment) ||
      Object.entries(server.environment).some(([k, v]) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(k) || typeof v !== "string" || v.includes("\0"))) {
    throw new Error("invalid local MCP adapter configuration")
  }
  const child = spawn(server.command[0], server.command.slice(1), {
    cwd: server.cwd, env: { ...process.env, ...server.environment }, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
  })
  child.stderr.resume()
  const decoder = new StringDecoder("utf8")
  const pending = new Map()
  let buffer = ""
  let nextId = 0
  let closed = false
  function stop(reason = "MCP adapter stopped") {
    if (closed) return
    closed = true
    for (const item of pending.values()) item.reject(new Error(reason))
    pending.clear()
    child.stdin.destroy()
    child.stdout.destroy()
    child.stderr.destroy()
    child.kill()
  }
  function consume(chunk) {
    buffer += decoder.write(chunk)
    if (Buffer.byteLength(buffer, "utf8") > MAX_LINE) return stop("MCP response exceeds limit")
    for (;;) {
      const end = buffer.indexOf("\n")
      if (end < 0) break
      const line = buffer.slice(0, end)
      buffer = buffer.slice(end + 1)
      if (!line.trim()) continue
      let message
      try { message = JSON.parse(line) } catch { return stop("invalid MCP response") }
      if (!message || typeof message !== "object" || Array.isArray(message) || message.jsonrpc !== "2.0") return stop("invalid MCP response")
      const item = pending.get(message.id)
      if (!item) continue
      pending.delete(message.id)
      if (message.error !== undefined) item.reject(new Error("MCP request failed"))
      else if (!("result" in message)) item.reject(new Error("invalid MCP response"))
      else item.resolve(message.result)
    }
  }
  child.stdout.on("data", consume)
  child.stdout.on("error", () => stop("MCP output failed"))
  child.stdin.on("error", () => stop("MCP input failed"))
  child.on("error", () => stop("MCP process failed"))
  child.on("exit", () => stop("MCP process exited"))
  function notify(method, params) {
    if (closed) throw new Error("MCP adapter is unavailable")
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, ...(params === undefined ? {} : { params }) }) + "\n")
  }
  function request(method, params, signal) {
    if (closed || pending.size >= MAX_PENDING) return Promise.reject(new Error("MCP adapter is unavailable or busy"))
    if (signal?.aborted) return Promise.reject(new Error("MCP request cancelled"))
    return new Promise((resolve, reject) => {
      const id = ++nextId
      const finish = callback => value => {
        clearTimeout(timer)
        signal?.removeEventListener("abort", cancel)
        callback(value)
      }
      const cancel = () => { pending.delete(id); finish(reject)(new Error("MCP request cancelled; outcome may be unknown")); stop("MCP request outcome unknown") }
      const timer = setTimeout(() => { pending.delete(id); finish(reject)(new Error("MCP request timed out; outcome may be unknown")); stop("MCP request outcome unknown") }, REQUEST_TIMEOUT_MS)
      pending.set(id, { resolve: finish(resolve), reject: finish(reject) })
      signal?.addEventListener("abort", cancel, { once: true })
      try {
        const wire = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n"
        if (Buffer.byteLength(wire, "utf8") > MAX_LINE) throw new Error("request too large")
        child.stdin.write(wire)
      }
      catch { pending.delete(id); finish(reject)(new Error("MCP request could not be sent")) }
    })
  }
  return { request, notify, stop }
}

export default {
  id: "local-ai-hub.mcp",
  async setup(ctx) {
    const storedConfig = await ctx.storage?.get?.("local-ai-hub:server-config")
    const serverConfig = storedConfig ?? ctx.options?.server
    if (!serverConfig) {
      throw new Error("local-ai-hub: server config missing; please configure the local-ai-hub server in OpenCode")
    }

    let mcp = null
    let tools = []
    try {
      if (!usesNativeMcp(serverConfig)) {
        mcp = openMcp(serverConfig)
        let initialized = false
        let lastErr = null
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            await mcp.request("initialize", {
              protocolVersion: "2025-03-26",
              capabilities: {},
              clientInfo: { name: "local-ai-hub-opencode", version: "5.0" },
            })
            mcp.notify("notifications/initialized")
            initialized = true
            break
          } catch (err) {
            lastErr = err
            if (attempt < 2) await new Promise(r => setTimeout(r, 1000 * (attempt + 1)))
          }
        }
        if (!initialized) throw lastErr ?? new Error("MCP initialization timed out")

        const catalog = await mcp.request("tools/list", {})
        if (!catalog || !Array.isArray(catalog.tools) || catalog.tools.length > MAX_TOOLS) throw new Error("invalid MCP tool catalog")
        const names = new Set()
        for (const tool of catalog.tools) {
          if (!tool || typeof tool.name !== "string" || !/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(tool.name) || names.has(tool.name) ||
              typeof tool.description !== "string" || !tool.inputSchema || typeof tool.inputSchema !== "object" || Array.isArray(tool.inputSchema)) {
            throw new Error("invalid MCP tool definition")
          }
          names.add(tool.name)
        }
        tools = selectHubTools(catalog.tools)
      }

      let postEditRegistration = null
      let preToolRegistration = null
      let permissionRegistration = null
      let contextRegistration = null
      if (typeof ctx.session?.hook === "function") {
        const activeContextHooks = { count: 0 }
        try {
          contextRegistration = await ctx.session.hook("context", async event => {
            appendHubContextGuidance(event)
            const root = ctx.location?.project?.canonical
            if (typeof root === "string") {
              const proactive = await runOpenCodeProactiveContext(serverConfig, root, event?.sessionID, activeContextHooks)
              if (proactive) {
                appendProactivePlanContext(event, proactive)
              }
            }
          })
        } catch (error) {
          console.error("Local AI Hub OpenCode context hook registration failed", error)
        }
      }
      if (typeof ctx.tool?.hook === "function") {
        const activeStaticHooks = { count: 0 }
        const activePreToolHooks = { count: 0 }
        try {
          preToolRegistration = await ctx.tool.hook("execute.before", async event => {
            const root = ctx.location?.project?.canonical
            if (typeof root !== "string") return
            const reason = await runOpenCodePreToolCheck(serverConfig, root, event, activePreToolHooks)
            if (reason) {
              throw new Error(`[Local AI Hub Policy] ${reason}`)
            }
          })
        } catch (error) {
          console.error("Local AI Hub OpenCode pre-tool hook registration failed", error)
        }
        try {
          postEditRegistration = await ctx.tool.hook("execute.after", async event => {
            if (event?.status !== "completed") return
            const root = ctx.location?.project?.canonical
            if (typeof root !== "string") return
            const context = await runOpenCodePostEditCheck(serverConfig, root, event, activeStaticHooks)
            appendPostEditContext(event, context)
          })
        } catch (error) {
          console.error("Local AI Hub OpenCode post-edit hook registration failed", error)
        }
      }
      if (typeof ctx.permission?.hook === "function") {
        const activePermissionHooks = { count: 0 }
        try {
          permissionRegistration = await ctx.permission.hook("evaluate", async event => {
            const root = ctx.location?.project?.canonical
            if (typeof root !== "string") return
            const reason = await runOpenCodePermissionCheck(serverConfig, root, event, activePermissionHooks)
            if (reason) {
              event.effect = "deny"
              event.message = reason
            }
          })
        } catch (error) {
          console.error("Local AI Hub OpenCode permission hook registration failed", error)
        }
      }

      if (typeof ctx.tool?.transform === "function") {
        await ctx.tool.transform(editor => {
          for (const tool of tools) {
            editor.add({
              name: tool.name,
              description: tool.description,
              input: tool.inputSchema,
              options: { codemode: false },
              execute: async (args, context) => ({
                content: JSON.stringify(await mcp.request("tools/call", { name: tool.name, arguments: args }, context?.signal))
              }),
            })
          }
        })
      } else if (typeof ctx.tool?.register === "function") {
        for (const tool of tools) {
          ctx.tool.register({
            name: tool.name,
            description: tool.description,
            parameters: tool.inputSchema,
            execute: async (args, context) => ({
              content: JSON.stringify(await mcp.request("tools/call", { name: tool.name, arguments: args }, context?.signal))
            }),
          })
        }
      }
      return async () => {
        try { await postEditRegistration?.dispose?.() } catch {}
        try { await preToolRegistration?.dispose?.() } catch {}
        try { await permissionRegistration?.dispose?.() } catch {}
        try { await contextRegistration?.dispose?.() } catch {}
        mcp?.stop()
      }
    } catch (error) {
      mcp?.stop()
      throw error
    }
  },
}
