const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const captureSource = fs.readFileSync(process.argv[2], "utf8");
const backgroundSource = fs.readFileSync(process.argv[3], "utf8");
const fixture = fs.readFileSync(process.argv[4], "utf8");
const {webcrypto} = require("node:crypto");

class FakeAbortController {
  constructor() {
    this.signal = {aborted: false, listeners: []};
    this.signal.addEventListener = (_name, listener) => this.signal.listeners.push(listener);
  }

  abort() {
    if (this.signal.aborted) return;
    this.signal.aborted = true;
    this.signal.listeners.forEach((listener) => listener());
  }
}

class FakeElement {
  constructor(tagName, attributes = {}, textContent = "") {
    this.rectIndex = FakeElement.rectIndex++;
    this.tagName = tagName.toUpperCase();
    this.attributes = {...attributes};
    this.textContent = textContent;
    this.children = [];
    this.parentElement = null;
    this.value = attributes.value || "";
    this.defaultValue = this.value;
  }

  append(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  get id() { return this.attributes.id || ""; }
  getAttribute(name) { return this.attributes[name] || null; }
  getBoundingClientRect() { const top = 10 + (this.rectIndex % 20) * 25; return {left: 10, top, right: 210, bottom: top + 20, width: 200, height: 20}; }
  removeAttribute(name) { delete this.attributes[name]; }
  get previousElementSibling() {
    if (!this.parentElement) return null;
    const index = this.parentElement.children.indexOf(this);
    return index > 0 ? this.parentElement.children[index - 1] : null;
  }

  cloneNode(deep) {
    const copy = new FakeElement(this.tagName, this.attributes, this.textContent);
    copy.value = this.value;
    copy.defaultValue = this.defaultValue;
    if (deep) this.children.forEach((child) => copy.append(child.cloneNode(true)));
    return copy;
  }

  querySelectorAll(selector) {
    const all = [];
    const visit = (node) => {
      node.children.forEach((child) => { all.push(child); visit(child); });
    };
    visit(this);
    if (selector === "*") return all;
    if (selector === 'input[type="password"]') {
      return all.filter((node) => node.tagName === "INPUT" && node.getAttribute("type") === "password");
    }
    return [];
  }

  get outerHTML() {
    const attrs = Object.entries(this.attributes).map(([key, value]) => ` ${key}="${value}"`).join("");
    if (this.tagName === "INPUT") return `<input${attrs}>`;
    return `<${this.tagName.toLowerCase()}${attrs}>${this.textContent}${this.children.map((child) => child.outerHTML).join("")}</${this.tagName.toLowerCase()}>`;
  }
}
FakeElement.rectIndex = 0;

const html = new FakeElement("html", {lang: "en"});
const body = html.append(new FakeElement("body"));
const main = body.append(new FakeElement("main", {"data-authenticated": "true"}, "Signed-in checkout"));
main.append(new FakeElement("button", {id: "pay", type: "button"}, "Pay"));
body.append(new FakeElement("input", {type: "password", value: "do-not-export"}));
body.append(new FakeElement("input", {type: "hidden", name: "csrf-token", value: "hidden-token"}));
body.append(new FakeElement("textarea", {}, "textarea-secret"));
body.append(new FakeElement("div", {"data-state": "inline-secret"}, "api_key=secret-visible-token-123 and alice@example.test"));
body.append(new FakeElement("script", {}, "window.__INITIAL_STATE__={token:'script-secret'}"));

const captureContext = {
  messageListeners: [],
  documentEventListeners: {},
  document: {
    documentElement: html,
    title: "Signed-in checkout",
    querySelectorAll: (selector) => html.querySelectorAll(selector),
    addEventListener: (name, listener) => (captureContext.documentEventListeners[name] ||= []).push(listener),
  },
  location: {href: "https://fixture.test/checkout?session=preserved", origin: "https://fixture.test"},
  history: {state: {step: 1}, replaceState(value) { this.state = value; }},
  performance: {timeOrigin: 1000, getEntriesByType: (type) => type === "navigation" ? [{startTime: 0, type: "navigate"}] : [{name: "https://fixture.test/app.js?token=hidden", initiatorType: "script", duration: 2, transferSize: 10}]},
  getComputedStyle: () => ({display: "block", visibility: "visible", position: "static", color: "black", backgroundColor: "white", fontSize: "16px", lineHeight: "20px", width: "100px", height: "20px"}),
  innerWidth: 1280,
  innerHeight: 720,
  devicePixelRatio: 1,
  chrome: {runtime: {onMessage: {addListener: (listener) => captureContext.messageListeners.push(listener)}}},
  URL,
};
vm.runInNewContext(captureSource, captureContext);
assert.equal(captureContext.messageListeners.length, 1);
vm.runInNewContext(captureSource, captureContext);
assert.equal(captureContext.messageListeners.length, 1);
class FixtureMutationObserver {
  constructor(callback) { this.callback = callback; }
  observe() {}
  trigger() { this.callback(); }
}
const revisionContext = {...captureContext, MutationObserver: FixtureMutationObserver};
vm.runInNewContext(captureSource, revisionContext);
async function runFixture() {
const identityBeforeMutation = await revisionContext.currentDocumentIdentity();
revisionContext.__LOCAL_AI_DOCUMENT_REVISION__.observer.trigger();
const identityAfterMutation = await revisionContext.currentDocumentIdentity();
assert.equal(identityAfterMutation.document_id, identityBeforeMutation.document_id);
assert.notEqual(identityAfterMutation.document_state_token, identityBeforeMutation.document_state_token);
assert.equal(identityAfterMutation.content_revision, "1");
assert.equal(captureContext.sha256Fallback("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
assert.equal(captureContext.sha256Fallback("\ud800"), "83d544ccc223c057d2bf80d3f2a32982c32c3c0db8e2674820da5064783fb097");
const redactedText = captureContext.redactSensitiveText("api_key=sk-12345678901234567890 and Bearer abcdefghijklmnop");
assert.equal(redactedText.text, "api_key=[REDACTED] and Bearer [REDACTED]");
assert.deepEqual(JSON.parse(JSON.stringify(redactedText.manifest)), {credential: 2});
const redactedUrl = captureContext.sanitizePrivacyUrl("https://fixture.test/reset/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturetoken?access_token=secret");
assert.equal(redactedUrl.url, "https://fixture.test/reset/~redacted~");
assert.deepEqual(JSON.parse(JSON.stringify(redactedUrl.manifest)), {path_segments: 1, query: true, fragment: false});
const page = await captureContext.captureCurrentTab();
assert.equal(page.success, true);
assert.match(page.dom.snapshot_digest, /^sha256:[0-9a-f]{64}$/);
assert.equal(page.dom.redaction, "none");
assert.equal(page.dom.password_values_sanitized, true);
assert.match(page.dom.html, /data-authenticated="true"/);
assert.doesNotMatch(page.dom.html, /do-not-export/);
assert.doesNotMatch(page.dom.html, /hidden-token|textarea-secret|inline-secret|script-secret|INITIAL_STATE/);
assert.equal(html.querySelectorAll('input[type="password"]')[0].value, "do-not-export");
assert.match(page.target_origin, /^https:\/\/fixture\.test$/);
assert.match(page.captured_at, /T/);
assert.equal(page.document_state_token, "state:content-unobserved");
const originalHistoryState = captureContext.history.state;
const cyclicHistoryState = {};
cyclicHistoryState.self = cyclicHistoryState;
captureContext.history.state = cyclicHistoryState;
assert.equal((await captureContext.currentDocumentIdentity()).relevant_state_complete, false);
captureContext.history.state = originalHistoryState;
const redactedPage = await captureContext.captureCurrentTab({privacyMode: "privacy_redacted"});
assert.equal(redactedPage.privacy_mode, "privacy_redacted");
assert.equal(redactedPage.dom.redaction, "deterministic");
assert.doesNotMatch(redactedPage.dom.html, /secret-visible-token-123|alice@example\.test|textarea-secret/);
assert.match(redactedPage.dom.html, /\[REDACTED\]/);
assert.ok(redactedPage.redaction_manifest.credential >= 1);
assert.ok(redactedPage.redaction_manifest.form_field >= 1);
assert.equal(redactedPage.redaction_complete, true);
assert.ok(redactedPage.redaction_regions.length >= 2, JSON.stringify({count: redactedPage.redaction_regions.length, manifest: redactedPage.redaction_manifest}));
const screenshotOnlyPage = await captureContext.captureCurrentTab({privacyMode: "screenshot_only"});
assert.equal(screenshotOnlyPage.privacy_mode, "screenshot_only");
assert.equal(screenshotOnlyPage.dom.html, "");
assert.deepEqual(JSON.parse(JSON.stringify(screenshotOnlyPage.dom.elements)), []);
assert.deepEqual(JSON.parse(JSON.stringify(screenshotOnlyPage.accessibility.snapshot)), []);

  const webCryptoContext = {...captureContext, crypto: webcrypto};
  webCryptoContext.TextEncoder = TextEncoder;
  vm.runInNewContext(captureSource, webCryptoContext);
  assert.equal(await webCryptoContext.digestState("\ud800"), "83d544ccc223c057d2bf80d3f2a32982c32c3c0db8e2674820da5064783fb097");
  const webCryptoPage = await webCryptoContext.captureCurrentTab();
assert.equal(webCryptoPage.document_state_token, page.document_state_token);
const largeDom = new FakeElement("html");
const largeBody = largeDom.append(new FakeElement("body"));
for (let index = 0; index < 1700; index += 1) largeBody.append(new FakeElement("div", {id: `filler-${index}`}));
const lateTarget = largeBody.append(new FakeElement("button", {id: "late-target", "aria-label": "Submit"}, "Submit"));
const largeDomContext = {
  ...captureContext,
  document: {...captureContext.document, documentElement: largeDom, title: "Large page", querySelectorAll: (selector) => largeDom.querySelectorAll(selector)},
};
vm.runInNewContext(captureSource, largeDomContext);
const largePage = await largeDomContext.captureCurrentTab();
assert.equal(largePage.dom.coverage_incomplete, true);
assert.equal(largePage.dom.element_count_total, 1702);
assert.ok(largePage.dom.elements.some((element) => element.id === "late-target"));

async function runBackground({timeout = null, hubTimeout = null, stageTimeout = false, finalPostTimeout = null, dropFirstCommitResponse = false, disconnectAfterStage = false, queryTimeout = false, getTimeout = false, switchTab = false, switchAfterScreenshot = false, screenshotTimeout = false, closed = false, permission = false, injectionError = false, unsupportedPage = false, navigateAfterScreenshot = false, mutateDocumentAfterScreenshot = false, mutateBenignDocumentAfterScreenshot = false, mutateTargetAfterScreenshot = false, mutateViewportAfterScreenshot = false, interactionAfterScreenshot = false, incompleteFingerprint = false, missingUrl = false, emptyUrl = false, token = "", privacyMode = "full_local_capture", redactionFailure = false, blockSensitiveOrigins = false, currentUrl = null} = {}) {
  const revisionState = captureContext.__LOCAL_AI_DOCUMENT_REVISION__;
  if (revisionState && !revisionState.observer) revisionState.observer = {observe: () => {}};
  let activeId = closed ? null : 7;
  const posts = [];
  const committedPosts = [];
  const serverStaged = new Set();
  const committedResults = new Map();
  let delayedStageResponses = 0;
  let artifactCommits = 0;
  let injections = 0;
  const maskRequests = [];
  let offscreenReady = false;
  let commitAttempts = 0;
  let aborted = false;
  const currentTab = {id: 7, windowId: 3};
  if (!missingUrl) currentTab.url = unsupportedPage ? "chrome://settings" : emptyUrl ? "" : currentUrl || page.url;
  const bgContext = {
    __LOCAL_AI_CAPTURE_TIMEOUT_MS__: timeout || 8000,
    __LOCAL_AI_HUB_REQUEST_TIMEOUT_MS__: hubTimeout || 5000,
    __LOCAL_AI_HUB_API_TOKEN__: token,
    AbortController: FakeAbortController,
    chrome: {
      runtime: {
        id: "fixture",
        getURL: () => "chrome-extension://fixture/",
        onMessage: {addListener: () => {}},
        sendMessage: async (message) => {
          if (message.type !== "LOCAL_AI_MASK_SCREENSHOT") return undefined;
          maskRequests.push(message);
          return redactionFailure ? {success: false, error_code: "screenshot_redaction_failed"}
            : {success: true, dataUrl: "data:image/png;base64,bWFza2Vk", maskedRegions: message.regions.length};
        },
      },
      offscreen: {
        hasDocument: async () => offscreenReady,
        createDocument: async () => { offscreenReady = true; },
      },
      action: {onClicked: {addListener: () => {}}},
      scripting: {
        executeScript: async () => {
          injections += 1;
          if (injectionError) throw new Error("Cannot access contents of the page");
          return [];
        },
      },
      tabs: {
        get: async () => { if (getTimeout) return new Promise(() => {}); return {...currentTab}; },
        query: async () => { if (queryTimeout) return new Promise(() => {}); if (permission) throw new Error("permission denied"); return activeId === null ? [] : [{id: activeId, windowId: 3}]; },
        sendMessage: async (tabId, message) => {
          if (message.type === "LOCAL_AI_CAPTURE_CURRENT_TAB") {
            const captured = await captureContext.captureCurrentTab({privacyMode: message.privacyMode});
            if (switchTab) activeId = 8;
            return captured;
          }
          if (disconnectAfterStage && message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && serverStaged.size > 0) {
            throw new Error("The message port closed before a response was received.");
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && navigateAfterScreenshot) {
            return {...page, url: "https://fixture.test/other", target_origin: "https://fixture.test", document_token: "document:new", document_state_token: "state:new"};
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && mutateDocumentAfterScreenshot) {
            captureContext.history.replaceState({step: 2}, "", captureContext.location.href);
            main.append(new FakeElement("p", {}, "DOM changed after screenshot"));
            return {...page, ...(await captureContext.verifyCurrentTab())};
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && mutateTargetAfterScreenshot) {
            main.children[0].textContent = "Different payment target";
            return await captureContext.verifyCurrentTab();
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && mutateBenignDocumentAfterScreenshot) {
            main.append(new FakeElement("p", {}, "Clock refreshed"));
            captureContext.__LOCAL_AI_DOCUMENT_REVISION__.content += 1;
            return await captureContext.verifyCurrentTab();
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && interactionAfterScreenshot) {
            captureContext.documentEventListeners.click.forEach((listener) => listener());
            return await captureContext.verifyCurrentTab();
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && mutateViewportAfterScreenshot) {
            captureContext.innerWidth += 1;
            return await captureContext.verifyCurrentTab();
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && incompleteFingerprint) {
            return {...await captureContext.verifyCurrentTab(), relevant_state_complete: false};
          }
          if (switchTab) activeId = 8;
          return message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" ? await captureContext.verifyCurrentTab() : page;
        },
        captureVisibleTab: async () => {
          if (screenshotTimeout) return new Promise(() => {});
          if (switchAfterScreenshot) activeId = 8;
          return "data:image/png;base64,cG5n";
        },
      },
    },
    fetch: async (_url, options) => {
      const body = JSON.parse(options.body);
      const path = new URL(_url).pathname;
      if (finalPostTimeout && path.endsWith("/commit")) {
        commitAttempts += 1;
        if (commitAttempts > 1) {
          return {ok: true, status: 200, json: async () => ({success: false, error_code: "timeout"})};
        }
      }
      if (hubTimeout || (finalPostTimeout && path.endsWith("/commit") && commitAttempts === 1) || (stageTimeout && path.endsWith("/stage"))) {
        if (path.endsWith("/stage")) serverStaged.add(body.request_id);
        return new Promise((_, reject) => {
          if (stageTimeout && path.endsWith("/stage")) {
            setTimeout(() => {
              delayedStageResponses += 1;
              if (options.signal.aborted) serverStaged.delete(body.request_id);
            }, 15);
          }
          options.signal.addEventListener("abort", () => {
            aborted = true;
            if (path.endsWith("/stage")) serverStaged.delete(body.request_id);
            reject(Object.assign(new Error("aborted"), {name: "AbortError"}));
          });
        });
      }
      if (token) {
        assert.equal(options.headers["X-LocalAI-Token"], undefined);
        assert.equal(options.headers.Authorization, undefined);
        assert.equal(options.headers["X-LocalAI-Tenant"], undefined);
      }
      posts.push(body);
      let value;
      if (path.endsWith("/stage")) {
        serverStaged.add(body.request_id);
        value = {success: true, staged: true, request_id: body.request_id};
      } else if (path.endsWith("/commit")) {
        committedPosts.push(body);
        value = committedResults.get(body.request_id);
        if (!value) {
          artifactCommits += 1;
          serverStaged.delete(body.request_id);
          value = {success: true, bundle_artifact_id: "bundle", request_id: body.request_id};
          committedResults.set(body.request_id, value);
        }
        if (dropFirstCommitResponse && committedPosts.length === 1) {
          throw new TypeError("Failed to fetch");
        }
      } else if (path.endsWith("/abandon")) {
        serverStaged.delete(body.request_id);
        value = {success: true, abandoned: true, request_id: body.request_id};
      } else {
        value = body.capture_error ? {success: false, error_code: body.capture_error} : {success: true, capability: "cap"};
      }
      return {ok: true, status: 200, json: async () => value};
    },
    URL,
    Promise,
    Error,
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(backgroundSource, bgContext);
  const tab = {id: 7, windowId: 3};
  if (timeout && !screenshotTimeout) {
    bgContext.chrome.tabs.sendMessage = () => new Promise(() => {});
  }
  const result = await bgContext.captureCurrentTab(tab, {
    privacyMode,
    consentAcknowledged: true,
    fullCaptureAcknowledged: privacyMode === "full_local_capture",
    blockSensitiveOrigins,
  });
  if (stageTimeout) await new Promise((resolve) => setTimeout(resolve, 25));
  return {result, posts, committedPosts, serverStaged, delayedStageResponses, artifactCommits, aborted, injections, maskRequests};
}

  const success = await runBackground();
  assert.equal(success.result.success, true);
  assert.equal(success.injections, 1);
  assert.equal(success.posts.at(-1).tab_id, 7);
  assert.equal(success.posts.at(-1).window_id, 3);
  const stagedSuccess = success.posts.find((post) => post.screenshot);
  assert.match(stagedSuccess.dom.html, /data-authenticated="true"/);
  assert.equal(stagedSuccess.capture_identity.initial.document_token, "document:1000:0:navigate");

  const redactedCapture = await runBackground({privacyMode: "privacy_redacted"});
  assert.equal(redactedCapture.result.success, true);
  const stagedRedacted = redactedCapture.posts.find((post) => post.screenshot);
  assert.equal(stagedRedacted.privacy_mode, "privacy_redacted");
  assert.equal(stagedRedacted.screenshot, "data:image/png;base64,bWFza2Vk");
  assert.doesNotMatch(stagedRedacted.dom.html, /secret-visible-token-123|alice@example\.test/);
  assert.equal(redactedCapture.maskRequests.length, 1);
  assert.equal(redactedCapture.maskRequests[0].regions.length, 3);

  const screenshotOnlyCapture = await runBackground({privacyMode: "screenshot_only"});
  assert.equal(screenshotOnlyCapture.result.success, true);
  const stagedScreenshotOnly = screenshotOnlyCapture.posts.find((post) => post.screenshot);
  assert.equal(stagedScreenshotOnly.privacy_mode, "screenshot_only");
  assert.equal(stagedScreenshotOnly.dom.html, "");
  assert.deepEqual(JSON.parse(JSON.stringify(stagedScreenshotOnly.dom.elements)), []);
  assert.equal(screenshotOnlyCapture.maskRequests.length, 0);

  const failedScreenshotMask = await runBackground({privacyMode: "privacy_redacted", redactionFailure: true});
  assert.equal(failedScreenshotMask.result.error_code, "redaction_failed");
  assert.equal(failedScreenshotMask.posts.some((post) => post.screenshot), false);
  const blockedSensitiveOrigin = await runBackground({
    privacyMode: "privacy_redacted",
    blockSensitiveOrigins: true,
    currentUrl: "https://login.fixture.test/authorize",
  });
  assert.equal(blockedSensitiveOrigin.result.error_code, "sensitive_origin_blocked");
  assert.equal(blockedSensitiveOrigin.posts.length, 0);
  assert.equal(blockedSensitiveOrigin.injections, 0);

  const timeout = await runBackground({timeout: 5});
  assert.equal(timeout.result.error_code, "timeout");
  assert.equal(timeout.posts.at(-1).capture_error, "timeout");

  const unsupportedPage = await runBackground({unsupportedPage: true});
  assert.equal(unsupportedPage.result.error_code, "unsupported");
  assert.equal(unsupportedPage.injections, 0);
  assert.equal(unsupportedPage.posts.length, 0);

  const injectionDenied = await runBackground({injectionError: true});
  assert.equal(injectionDenied.result.error_code, "permission_denied");
  assert.equal(injectionDenied.injections, 1);

  const screenshotTimeout = await runBackground({timeout: 5, screenshotTimeout: true});
  assert.equal(screenshotTimeout.result.error_code, "timeout");
  assert.equal(screenshotTimeout.posts.at(-1).capture_error, "timeout");
  const hubTimeoutResult = await runBackground({hubTimeout: 5});
  assert.equal(hubTimeoutResult.result.error_code, "timeout");
  assert.equal(hubTimeoutResult.posts.length, 0);
  assert.equal(hubTimeoutResult.aborted, true);
  const finalPostTimeoutResult = await runBackground({finalPostTimeout: 5});
  assert.equal(finalPostTimeoutResult.result.error_code, "commit_outcome_unknown");
  assert.equal(finalPostTimeoutResult.aborted, true);
  assert.equal(finalPostTimeoutResult.committedPosts.some((post) => post.screenshot), false);
  assert.equal(finalPostTimeoutResult.serverStaged.size, 1);
  const droppedCommitResponse = await runBackground({dropFirstCommitResponse: true});
  assert.equal(droppedCommitResponse.result.success, true);
  assert.equal(droppedCommitResponse.committedPosts.length, 2);
  assert.equal(droppedCommitResponse.artifactCommits, 1);
  assert.equal(droppedCommitResponse.serverStaged.size, 0);
  const delayedStage = await runBackground({stageTimeout: true});
  assert.equal(delayedStage.result.error_code, "timeout");
  assert.equal(delayedStage.aborted, true);
  assert.equal(delayedStage.delayedStageResponses, 1);
  assert.equal(delayedStage.serverStaged.size, 0);
  assert.equal(delayedStage.artifactCommits, 0);
  const queryTimeoutResult = await runBackground({timeout: 5, queryTimeout: true});
  assert.equal(queryTimeoutResult.result.error_code, "timeout");
  assert.equal(queryTimeoutResult.posts.length, 0);
  const getTimeoutResult = await runBackground({timeout: 5, getTimeout: true});
  assert.equal(getTimeoutResult.result.error_code, "timeout");
  assert.equal(getTimeoutResult.posts.length, 0);

  const switched = await runBackground({switchTab: true});
  assert.equal(switched.result.error_code, "tab_mismatch");
  assert.equal(switched.posts.at(-1).capture_error, "tab_mismatch");
  assert.equal(switched.posts.some((post) => post.screenshot), false);
  const switchedAfter = await runBackground({switchAfterScreenshot: true});
  assert.equal(switchedAfter.result.error_code, "tab_mismatch");
  assert.equal(switchedAfter.posts.at(-1).capture_error, "tab_mismatch");
  assert.equal(switchedAfter.posts.some((post) => post.screenshot), false);
  const navigated = await runBackground({navigateAfterScreenshot: true});
  assert.equal(navigated.result.error_code, "target_changed");
  assert.equal(navigated.posts.at(-1).capture_error, "target_changed");
  assert.equal(navigated.posts.some((post) => post.screenshot), false);
  const disconnected = await runBackground({disconnectAfterStage: true});
  assert.equal(disconnected.result.error_code, "target_changed");
  assert.equal(disconnected.serverStaged.size, 0);
  assert.equal(disconnected.committedPosts.length, 0);
  assert.equal(disconnected.artifactCommits, 0);
  const mutated = await runBackground({mutateDocumentAfterScreenshot: true});
  assert.equal(captureContext.history.state.step, 2);
  assert.match(captureContext.document.documentElement.outerHTML, /DOM changed after screenshot/);
  assert.equal(mutated.result.error_code, "target_changed");
  assert.equal(mutated.posts.some((post) => post.screenshot), false);
  const benignMutation = await runBackground({mutateBenignDocumentAfterScreenshot: true});
  assert.equal(benignMutation.result.success, true);
  assert.equal(benignMutation.posts.find((post) => post.screenshot).capture_identity.consistency, "changed_but_safe");
  const changedTarget = await runBackground({mutateTargetAfterScreenshot: true});
  assert.equal(changedTarget.result.error_code, "target_changed");
  assert.equal(changedTarget.posts.at(-1).capture_error, "target_changed");
  assert.equal(changedTarget.posts.some((post) => post.screenshot), false);
  const interacted = await runBackground({interactionAfterScreenshot: true});
  assert.equal(interacted.result.error_code, "target_changed");
  assert.equal(interacted.posts.some((post) => post.screenshot), false);
  const viewportChanged = await runBackground({mutateViewportAfterScreenshot: true});
  assert.equal(viewportChanged.result.error_code, "target_changed");
  assert.equal(viewportChanged.posts.some((post) => post.screenshot), false);
  captureContext.innerWidth = 1280;
  const incompleteFingerprintResult = await runBackground({incompleteFingerprint: true});
  assert.equal(incompleteFingerprintResult.result.error_code, "unverifiable");
  assert.equal(incompleteFingerprintResult.posts.some((post) => post.screenshot), false);
  for (const options of [{missingUrl: true}, {emptyUrl: true}]) {
    const missingOrEmpty = await runBackground(options);
    assert.equal(missingOrEmpty.result.error_code, "permission_denied");
    assert.equal(missingOrEmpty.posts.length, 0);
    assert.equal(missingOrEmpty.serverStaged.size, 0);
    assert.equal(missingOrEmpty.artifactCommits, 0);
    assert.equal(missingOrEmpty.posts.some((post) => post.screenshot), false);
  }
  assert.equal((await runBackground({closed: true})).result.error_code, "closed_tab");
  const permissionDenied = await runBackground({permission: true});
  assert.equal(permissionDenied.result.error_code, "permission_denied");
  assert.equal(permissionDenied.posts.length, 0);
  assert.equal(permissionDenied.serverStaged.size, 0);
  assert.equal(permissionDenied.committedPosts.length, 0);
  assert.equal(permissionDenied.artifactCommits, 0);
  const tokenRun = await runBackground({token: "0123456789abcdef"});
  assert.equal(tokenRun.result.success, true);
  process.stdout.write(JSON.stringify({success: true, fixture: "login-preserving", cases: ["success", "permission-denied-no-capture", "unsupported-page-no-injection", "injection-denied", "timeout", "screenshot-timeout", "hub-timeout", "final-post-timeout", "query-timeout", "get-timeout", "tab-switch", "same-tab-navigation", "same-url-state-race", "benign-visual-mutation-safe", "target-mutation-rejected", "interaction-race-rejected", "viewport-race-rejected", "incomplete-fingerprint-unverifiable", "disconnect-after-stage", "missing-tab-url", "empty-tab-url", "password", "timestamp", "origin", "token", "privacy-redacted", "screenshot-only", "mask-failure-no-stage", "sensitive-origin-blocked"]}));
}

runFixture().catch((error) => { console.error(error); process.exitCode = 1; });
