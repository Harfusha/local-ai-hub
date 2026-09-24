const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const sourcePath = process.argv[2];
const changeKind = process.argv[3] || "navigation";
const backgroundSource = fs.readFileSync(sourcePath, "utf8");
const tab = {id: 7, windowId: 3, url: "https://fixture.test/checkout"};
let documentToken = "document:fixture:1";
let stateToken = "state:fixture:1";
let changedAfterStage = false;
const posts = [];

function identity() {
  return {
    url: tab.url,
    target_origin: new URL(tab.url).origin,
    document_token: documentToken,
    document_state_token: stateToken,
  };
}

const context = {
  AbortController,
  URL,
  console,
  fetch: async (url, options) => {
    const path = new URL(url).pathname;
    const body = JSON.parse(options.body);
    posts.push({path, body});
    let value;
    if (path.endsWith("/capability")) {
      value = {success: true, capability: "capability-1"};
    } else if (path.endsWith("/stage")) {
      value = {success: true, staged: true, request_id: body.request_id};
      changedAfterStage = true;
      if (changeKind === "same-url-state") {
        stateToken = "state:fixture:2";
      } else if (changeKind === "navigation") {
        tab.url = "https://fixture.test/next";
        documentToken = "document:fixture:2";
      }
    } else if (path.endsWith("/abandon")) {
      value = {success: true, abandoned: true, request_id: body.request_id};
    } else if (path.endsWith("/commit")) {
      value = changeKind === "artifact-failure"
        ? {success: false, retryable: false, error_code: "artifact_store_error"}
        : {success: true, bundle_artifact_id: "bundle-1"};
    } else {
      throw new Error(`unexpected endpoint ${path}`);
    }
    return {ok: true, status: 200, json: async () => value};
  },
  chrome: {
    runtime: {getURL: () => "chrome-extension://fixture/"},
    action: {onClicked: {addListener: () => undefined}},
    tabs: {
      query: async () => [{...tab}],
      get: async () => ({...tab}),
      sendMessage: async (_tabId, message) => {
        const value = identity();
        if (message.type === "LOCAL_AI_CAPTURE_CURRENT_TAB") {
          return {success: true, ...value, capture_identity: {initial: value}, dom: {html: "<main />"}};
        }
        return {success: true, ...value};
      },
      captureVisibleTab: async () => "data:image/png;base64,c2NyZWVuc2hvdA==",
    },
  },
  setTimeout,
  clearTimeout,
};
context.globalThis = context;
vm.runInNewContext(backgroundSource, context, {filename: sourcePath});

(async () => {
  const result = await context.captureCurrentTab({id: 7, windowId: 3});
  assert.equal(changedAfterStage, true);
  if (changeKind === "artifact-failure") {
    assert.equal(result.success, false);
    assert.equal(result.error_code, "artifact_store_error");
    assert.equal(posts.filter((post) => post.path.endsWith("/commit")).length, 1);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 1);
    process.stdout.write(JSON.stringify({success: true, case: "artifact-failure-reported-and-abandoned"}));
  } else {
    assert.equal(result.success, false, "page change after staging must prevent commit");
    assert.equal(result.error_code, "target_changed");
    assert.equal(posts.some((post) => post.path.endsWith("/commit")), false);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 1);
    process.stdout.write(JSON.stringify({success: true, case: `${changeKind}-after-stage-abandons`}));
  }
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
