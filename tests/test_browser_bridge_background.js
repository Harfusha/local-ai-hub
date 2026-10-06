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
    let responseStatus = 200;
    let responseOk = true;
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
      const commitCount = posts.filter((post) => post.path.endsWith("/commit")).length;
      value = changeKind === "artifact-failure"
        ? {success: false, retryable: false, error_code: "artifact_store_error"}
        : changeKind === "commit-request-id-mismatch"
          ? {success: true, request_id: `${body.request_id}-other`, bundle_artifact_id: "bundle-1"}
        : changeKind === "commit-invalid-shape"
          ? "not-an-object"
          : changeKind === "commit-missing-artifact-id"
            ? {success: true, request_id: body.request_id, bundle_artifact_id: ""}
        : changeKind === "commit-missing-request-id"
          ? {success: true, bundle_artifact_id: "bundle-1"}
        : changeKind === "commit-mismatched-request-id"
          ? {success: true, request_id: "wrong-request-id", bundle_artifact_id: "bundle-1"}
        : changeKind === "commit-mismatched-error-request-id"
          ? {success: false, error_code: "capture_expired", request_id: "wrong-request-id"}
        : changeKind === "commit-in-progress"
          ? {success: false, error_code: "capture_in_progress"}
          : changeKind === "commit-timeout-response"
            ? {success: false, error_code: "timeout"}
            : {success: true, request_id: body.request_id, bundle_artifact_id: "bundle-1"};
      if (["lost-commit-response", "commit-in-progress", "commit-timeout-response"].includes(changeKind) && commitCount === 1) {
        throw new Error("commit response lost after server commit");
      }
      if (changeKind === "commit-response-lost-twice") {
        throw new Error("commit response unavailable");
      }
      if (changeKind === "commit-5xx-response" && commitCount === 1) {
        responseStatus = 503;
        responseOk = false;
      }
    } else {
      throw new Error(`unexpected endpoint ${path}`);
    }
    return {ok: responseOk, status: responseStatus, json: async () => value};
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
  } else if (changeKind === "lost-commit-response") {
    assert.equal(result.success, true);
    assert.equal(result.bundle_artifact_id, "bundle-1");
    const commits = posts.filter((post) => post.path.endsWith("/commit"));
    assert.equal(commits.length, 2);
    assert.deepEqual(commits[1].body, commits[0].body);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 0);
    process.stdout.write(JSON.stringify({success: true, case: "lost-commit-response-reconciled"}));
  } else if (changeKind === "commit-5xx-response") {
    assert.equal(result.success, true);
    assert.equal(result.bundle_artifact_id, "bundle-1");
    const commits = posts.filter((post) => post.path.endsWith("/commit"));
    assert.equal(commits.length, 2);
    assert.deepEqual(commits[1].body, commits[0].body);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 0);
    process.stdout.write(JSON.stringify({success: true, case: "commit-5xx-reconciled"}));
  } else if (changeKind === "commit-in-progress") {
    assert.equal(result.success, false);
    assert.equal(result.error_code, "commit_outcome_unknown");
    assert.equal(posts.filter((post) => post.path.endsWith("/commit")).length, 2);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 0);
    process.stdout.write(JSON.stringify({success: true, case: "in-progress-commit-not-cancelled"}));
  } else if (changeKind === "commit-timeout-response") {
    assert.equal(result.success, false);
    assert.equal(result.error_code, "commit_outcome_unknown");
    assert.equal(posts.filter((post) => post.path.endsWith("/commit")).length, 2);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 0);
    process.stdout.write(JSON.stringify({success: true, case: "timed-out-commit-not-cancelled"}));
  } else if (changeKind === "commit-response-lost-twice") {
    assert.equal(result.success, false);
    assert.equal(result.error_code, "commit_outcome_unknown");
    assert.equal(result.request_id, posts.find((post) => post.path.endsWith("/commit")).body.request_id);
    assert.equal(posts.filter((post) => post.path.endsWith("/commit")).length, 2);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 0);
    process.stdout.write(JSON.stringify({success: true, case: "ambiguous-commit-left-uncancelled"}));
  } else if (["commit-request-id-mismatch", "commit-invalid-shape", "commit-missing-artifact-id", "commit-missing-request-id", "commit-mismatched-request-id", "commit-mismatched-error-request-id"].includes(changeKind)) {
    assert.equal(result.success, false);
    assert.equal(result.error_code, "commit_outcome_unknown");
    assert.equal(result.request_id, posts.find((post) => post.path.endsWith("/commit")).body.request_id);
    assert.equal(posts.filter((post) => post.path.endsWith("/commit")).length, 2);
    assert.equal(posts.filter((post) => post.path.endsWith("/abandon")).length, 0);
    const commits = posts.filter((post) => post.path.endsWith("/commit"));
    assert.deepEqual(commits[1].body, commits[0].body);
    process.stdout.write(JSON.stringify({success: true, case: "malformed-commit-remains-unknown"}));
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
