"use strict"

// Experimental AppContainer-local relay. The host pipe listener and the Hub
// router remain authoritative; this module does not provide isolation alone.
const net = require("node:net")

const MAX_REQUEST = 4 * 1024 * 1024 + 65536
const MAX_RESPONSE = 64 * 1024 * 1024
const MAX_FRAME = 65536

function validatePipeName(name) {
  if (typeof name !== "string" || !/^\\\\\.\\pipe\\lah-opencode-[a-f0-9]{32}$/.test(name)) throw new Error("invalid local pipe name")
  return name
}

function createBridge({ secret, connectPipe, timeoutMs = 120000 }) {
  if (!Buffer.isBuffer(secret) || secret.length !== 32 || typeof connectPipe !== "function") throw new Error("invalid bridge configuration")
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 300000) throw new Error("invalid bridge timeout")
  const key = Buffer.from(secret)
  const queue = []
  let active = false
  function next() {
    if (active) return
    while (queue.length) {
      const item = queue.shift()
      clearTimeout(item.timer)
      item.client.removeListener("close", item.closed)
      item.client.pause()
      item.client.removeListener("data", item.data)
      item.client.removeListener("end", item.ended)
      if (item.client.destroyed) continue
      if (item.bytes) item.client.unshift(Buffer.concat(item.chunks, item.bytes))
      active = true
      start(item.client, () => { active = false; next() })
      return
    }
  }
  const server = net.createServer({ allowHalfOpen: true }, (client) => {
    client.pause()
    const item = { client, chunks: [], bytes: 0 }
    item.closed = () => { const i = queue.indexOf(item); if (i !== -1) queue.splice(i, 1); clearTimeout(item.timer) }
    item.data = (data) => {
      item.bytes += data.length
      if (item.bytes > MAX_REQUEST) return client.destroy()
      item.chunks.push(data)
    }
    item.ended = () => client.destroy()
    item.timer = setTimeout(() => client.destroy(), timeoutMs)
    item.timer.unref()
    client.on("error", () => {})
    client.once("close", item.closed)
    client.on("data", item.data)
    client.once("end", item.ended)
    queue.push(item)
    next()
    if (queue.includes(item)) client.resume()
  })
  function start(client, release) {
    let pipe
    let terminal = false
    let acknowledged = false
    let pending = Buffer.alloc(0)
    let requestBytes = 0
    let responseBytes = 0
    let paused = false
    const timer = setTimeout(() => fail(), timeoutMs)
    timer.unref()
    function fail() {
      clearTimeout(timer)
      client.destroy()
      if (pipe) pipe.destroy()
      else release()
    }
    function parse() {
      while (!terminal && !paused && pending.length >= 4) {
        const length = pending.readUInt32BE(0)
        if (length > MAX_FRAME || responseBytes + length > MAX_RESPONSE) return fail()
        if (pending.length < 4 + length) return
        const data = pending.subarray(4, 4 + length)
        pending = pending.subarray(4 + length)
        if (length === 0) {
          if (pending.length !== 0) return fail()
          terminal = true
          pipe.write(Buffer.from([6]), (error) => { if (error) return fail(); acknowledged = true; clearTimeout(timer); pipe.end() })
          client.end()
          return
        }
        responseBytes += length
        if (!client.write(data)) {
          paused = true
          pipe.pause()
        }
      }
    }
    try { pipe = connectPipe() } catch { fail(); return }
    if (!pipe || typeof pipe.on !== "function" || typeof pipe.write !== "function" || typeof pipe.destroy !== "function") {
      pipe = null
      fail()
      return
    }
    client.on("error", fail)
    client.on("close", () => { if (!terminal) fail() })
    client.on("end", () => { if (!terminal) fail() })
    client.on("drain", () => { paused = false; parse(); if (!terminal && !paused) pipe.resume() })
    client.on("data", (data) => {
      requestBytes += data.length
      if (requestBytes > MAX_REQUEST) return fail()
      if (!pipe.write(data)) client.pause()
    })
    pipe.on("connect", () => { if (!pipe.write(key)) pipe.once("drain", () => client.resume()); else client.resume() })
    pipe.on("drain", () => client.resume())
    pipe.on("data", (data) => {
      if (terminal || pending.length + data.length > 262144) return fail()
      pending = Buffer.concat([pending, data])
      parse()
    })
    pipe.on("error", () => { if (!terminal || !acknowledged) fail() })
    pipe.on("end", () => { if (!terminal || !acknowledged) fail() })
    pipe.on("close", () => { if (!terminal || !acknowledged) fail(); release() })
  }
  server.maxConnections = 16
  return server
}

if (require.main === module) {
  const name = validatePipeName(process.env.LOCAL_AI_PIPE_NAME)
  const encoded = process.env.LOCAL_AI_PIPE_SECRET
  if (typeof encoded !== "string" || !/^[a-f0-9]{64}$/.test(encoded)) throw new Error("invalid bridge secret")
  delete process.env.LOCAL_AI_PIPE_SECRET
  const server = createBridge({ secret: Buffer.from(encoded, "hex"), connectPipe: () => net.connect(name) })
  server.listen(0, "127.0.0.1", () => process.stdout.write(JSON.stringify({ port: server.address().port }) + "\n"))
}

module.exports = { createBridge, validatePipeName }
