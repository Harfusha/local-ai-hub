import { spawn } from "node:child_process"
import { StringDecoder } from "node:string_decoder"
import path from "node:path"

const MAX_LINE = 4 * 1024 * 1024
const MAX_PENDING = 16
const REQUEST_TIMEOUT_MS = 60000

// This adapter remains experimental until the host launcher provides the
// complete filesystem and process isolation required by the integration.
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
    const mcp = openMcp(ctx.options?.server)
    try {
      await mcp.request("initialize", { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "local-ai-hub-opencode", version: "1" } })
      mcp.notify("notifications/initialized")
      const catalog = await mcp.request("tools/list", {})
      if (!catalog || !Array.isArray(catalog.tools) || catalog.tools.length > 32) throw new Error("invalid MCP tool catalog")
      const names = new Set()
      for (const tool of catalog.tools) {
        if (!tool || typeof tool.name !== "string" || !/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(tool.name) || names.has(tool.name) ||
            typeof tool.description !== "string" || !tool.inputSchema || typeof tool.inputSchema !== "object" || Array.isArray(tool.inputSchema)) {
          throw new Error("invalid MCP tool definition")
        }
        names.add(tool.name)
      }
      await ctx.tool.transform(editor => {
        for (const tool of catalog.tools) editor.add({
          name: tool.name, description: tool.description, input: tool.inputSchema, options: { codemode: false },
          execute: async (args, context) => ({ content: JSON.stringify(await mcp.request("tools/call", { name: tool.name, arguments: args }, context.signal)) }),
        })
      })
      return () => mcp.stop()
    } catch (error) {
      mcp.stop()
      throw error
    }
  },
}
