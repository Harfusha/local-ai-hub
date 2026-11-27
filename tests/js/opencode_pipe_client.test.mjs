import assert from "node:assert/strict"
import { createRequire } from "node:module"
import test from "node:test"

const require = createRequire(import.meta.url)
const { validatePipeName } = require("../../tools/opencode_pipe_client.cjs")

test("validates AppContainer LOCAL named-pipe namespace", () => {
  const session = "0123456789abcdef0123456789abcdef"

  assert.equal(validatePipeName(`\\\\.\\pipe\\LOCAL\\lah-opencode-${session}`), `\\\\.\\pipe\\LOCAL\\lah-opencode-${session}`)
  assert.equal(validatePipeName(`\\\\.\\pipe\\lah-opencode-${session}`), `\\\\.\\pipe\\lah-opencode-${session}`)
  assert.throws(() => validatePipeName(`\\\\.\\pipe\\other\\lah-opencode-${session}`), /invalid local pipe name/)
  assert.throws(() => validatePipeName(`\\\\.\\pipe\\LOCAL\\lah-opencode-${session.toUpperCase()}`), /invalid local pipe name/)
})
