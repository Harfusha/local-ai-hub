"use strict"

// Experimental local bridge bootstrap. Filesystem access, process-tree cleanup
// and complete sandbox acceptance must be established by the host launcher.
const fs = require("node:fs")
const net = require("node:net")
const path = require("node:path")
const Module = require("node:module")
const { spawn } = require("node:child_process")

function localAbsolutePath(value) {
  return typeof value === "string" && !value.includes("\0") && path.isAbsolute(value) &&
    (process.platform !== "win32" || /^[A-Za-z]:[\\/]/.test(value))
}

function readClientSource(clientPath) {
  const limit = 262144
  const fd = fs.openSync(clientPath, "r")
  try {
    const info = fs.fstatSync(fd)
    if (!info.isFile()) throw new Error("sandbox bridge client is not a regular file")
    if (info.size > limit) throw new Error("sandbox bridge client is too large")
    const buffer = Buffer.alloc(limit + 1)
    let length = 0
    while (length < buffer.length) {
      const count = fs.readSync(fd, buffer, length, buffer.length - length, null)
      if (!count) break
      length += count
    }
    if (length > limit) throw new Error("sandbox bridge client is too large")
    return buffer.subarray(0, length).toString("utf8")
  } finally { fs.closeSync(fd) }
}

function main() {
  const env = process.env
  const encoded = env.LOCAL_AI_PIPE_SECRET
  const pipeName = env.LOCAL_AI_PIPE_NAME
  const portText = env.LOCAL_AI_CLIENT_PORT
  const clientPath = env.LOCAL_AI_BOOTSTRAP_CLIENT
  const executable = env.LOCAL_AI_BOOTSTRAP_EXECUTABLE
  const project = env.LOCAL_AI_BOOTSTRAP_PROJECT
  const encodedArgs = env.LOCAL_AI_BOOTSTRAP_ARGS
  delete env.LOCAL_AI_PIPE_SECRET
  delete env.LOCAL_AI_PIPE_NAME
  delete env.LOCAL_AI_CLIENT_PORT
  delete env.LOCAL_AI_BOOTSTRAP_CLIENT
  delete env.LOCAL_AI_BOOTSTRAP_EXECUTABLE
  delete env.LOCAL_AI_BOOTSTRAP_PROJECT
  delete env.LOCAL_AI_BOOTSTRAP_ARGS
  if (typeof encoded !== "string" || !/^[a-f0-9]{64}$/.test(encoded) ||
      typeof portText !== "string" || !/^[1-9][0-9]{3,4}$/.test(portText) ||
      Number(portText) < 1024 || Number(portText) > 65535 ||
      !localAbsolutePath(clientPath) || !localAbsolutePath(executable) || !localAbsolutePath(project) ||
      typeof encodedArgs !== "string" || encodedArgs.length > 8192) throw new Error("invalid sandbox bootstrap configuration")
  let args
  try { args = JSON.parse(encodedArgs) } catch { throw new Error("invalid sandbox bootstrap arguments") }
  if (!Array.isArray(args) || args.length > 128 || args.some(value => typeof value !== "string" || value.includes("\0"))) {
    throw new Error("invalid sandbox bootstrap arguments")
  }
  const source = readClientSource(clientPath)
  const client = new Module("sandbox-bridge-client")
  client._compile(source, "sandbox-bridge-client.cjs")
  client.exports.validatePipeName(pipeName)
  const bridge = client.exports.createBridge({ secret: Buffer.from(encoded, "hex"), connectPipe: () => net.connect(pipeName) })
  const sockets = new Set()
  bridge.on("connection", socket => { sockets.add(socket); socket.once("close", () => sockets.delete(socket)) })
  let finished = false
  let child = null
  function report(message) { process.stderr.write(`sandbox bootstrap: ${message}\n`) }
  function finish(code) {
    if (finished) return
    finished = true
    if (sockets.size) { report("transport still active at child exit"); code = 1 } // Outcome is not confirmed.
    for (const socket of sockets) socket.destroy()
    bridge.close(() => { process.exitCode = code })
  }
  bridge.on("error", error => {
    const code = typeof error?.code === "string" && /^[A-Z0-9_]{1,32}$/.test(error.code) ? error.code : "UNKNOWN"
    report(`local transport failed (${code})`)
    if (child) { child.kill(); finish(1) } else process.exitCode = 1
  })
  bridge.listen(Number(portText), "127.0.0.1", () => {
    try {
      child = spawn(executable, args, { cwd: project, env: { ...env, OPENCODE_DISABLE_PROJECT_CONFIG: "1",
        OPENCODE_DISABLE_MODELS_FETCH: "1", OPENCODE_DISABLE_AUTOUPDATE: "1" }, stdio: "inherit" })
    } catch { report("child creation failed"); finish(1); return }
    child.once("error", () => { report("child process failed"); finish(1) })
    child.once("exit", code => finish(Number.isInteger(code) ? code : 1))
  })
}

module.exports = { main }
if (require.main === module) main()
