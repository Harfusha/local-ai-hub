import assert from "node:assert/strict"
import test from "node:test"
import { appendHubContextGuidance, appendPostEditContext, opencodeEditedPath, opencodePermissionCommand, selectHubTools } from "./index.js"

const coreTools = ["local_ai_status", "local_ai_repo", "local_ai_task", "local_ai_coord", "local_ai_artifact", "local_ai_rag"]
const tool = name => ({ name, description: name, inputSchema: { type: "object" } })

test("OpenCode exposes local work only when the live Hub schema advertises it", () => {
  const coreCatalog = coreTools.map(tool)
  const fullCatalog = [...coreCatalog, tool("local_ai_work")]
  assert.deepEqual(selectHubTools(coreCatalog).map(item => item.name), coreTools)
  assert.deepEqual(selectHubTools(fullCatalog).map(item => item.name), [...coreTools, "local_ai_work"])
  assert.throws(() => selectHubTools(coreCatalog.slice(1)), /missing a core tool/)
})

test("OpenCode static hook accepts only bounded absolute edit paths", () => {
  assert.equal(opencodeEditedPath("edit", { filePath: "C:\\repo\\file.py", newString: "secret" }), "C:\\repo\\file.py")
  assert.equal(opencodeEditedPath("read", { filePath: "C:\\repo\\file.py" }), null)
  assert.equal(opencodeEditedPath("edit", { filePath: "relative.py" }), null)
  assert.equal(opencodeEditedPath("edit", { filePath: `C:\\repo\\${"a".repeat(4100)}` }), null)
})

test("OpenCode static findings append as tool context only", () => {
  const event = { result: { content: [{ type: "text", text: "updated" }], metadata: { preserved: true } } }
  assert.equal(appendPostEditContext(event, "syntax error"), true)
  assert.equal(event.result.content.at(-1).text, "Local AI Hub static check: syntax error")
  assert.deepEqual(event.result.metadata, { preserved: true })
  assert.equal(appendPostEditContext({ result: { output: "updated" } }, "warning"), false)
})

test("OpenCode permission command checks every bounded shell resource", () => {
  assert.equal(opencodePermissionCommand({ action: "shell", resources: ["git status", "python -m pytest -q"] }), "git status\npython -m pytest -q")
  assert.equal(opencodePermissionCommand({ action: "shell", resources: ["git status", "x".repeat(4100)] }), null)
  assert.equal(opencodePermissionCommand({ action: "edit", resources: ["file.py"] }), null)
})

test("OpenCode adds Laya guidance only when Hub tools are available", () => {
  const event = { system: [{ type: "text", text: "existing system" }], tools: { local_ai_repo: {} } }
  assert.equal(appendHubContextGuidance(event), true)
  assert.match(event.system.at(-1).text, /Laya output as advisory/)
  assert.match(event.system.at(-1).text, /host permissions/)
  assert.equal(appendHubContextGuidance(event), false)
  assert.equal(appendHubContextGuidance({ system: [], tools: { read: {} } }), false)
})
