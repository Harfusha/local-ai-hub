const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = {globalThis: null};
context.globalThis = context;
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);
assert.equal(context.buildCaptureRequest("privacy_redacted", true, false), "privacy_redacted");
assert.equal(context.buildCaptureRequest("screenshot_only", true, false), "screenshot_only");
assert.equal(context.buildCaptureRequest("full_local_capture", true, false), null);
assert.equal(context.buildCaptureRequest("full_local_capture", true, true), "full_local_capture");
assert.equal(context.buildCaptureRequest("privacy_redacted", false, false), null);
assert.equal(context.buildCaptureRequest("unknown", true, true), null);
process.stdout.write(JSON.stringify({success: true, cases: ["redacted-consent", "screenshot-consent", "full-mode-extra-ack", "first-notice-required", "reject-unknown-mode"]}));
