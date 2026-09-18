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

const html = new FakeElement("html", {lang: "en"});
const body = html.append(new FakeElement("body"));
const main = body.append(new FakeElement("main", {"data-authenticated": "true"}, "Signed-in checkout"));
main.append(new FakeElement("button", {id: "pay", type: "button"}, "Pay"));
body.append(new FakeElement("input", {type: "password", value: "do-not-export"}));

const captureContext = {
  document: {
    documentElement: html,
    title: "Signed-in checkout",
    querySelectorAll: (selector) => html.querySelectorAll(selector),
  },
  location: {href: "https://fixture.test/checkout?session=preserved", origin: "https://fixture.test"},
  history: {state: {step: 1}, replaceState(value) { this.state = value; }},
  performance: {timeOrigin: 1000, getEntriesByType: (type) => type === "navigation" ? [{startTime: 0, type: "navigate"}] : [{name: "https://fixture.test/app.js?token=hidden", initiatorType: "script", duration: 2, transferSize: 10}]},
  getComputedStyle: () => ({display: "block", visibility: "visible", position: "static", color: "black", backgroundColor: "white", fontSize: "16px", lineHeight: "20px", width: "100px", height: "20px"}),
  innerWidth: 1280,
  innerHeight: 720,
  devicePixelRatio: 1,
  chrome: {runtime: {onMessage: {addListener: () => {}}}},
  URL,
};
vm.runInNewContext(captureSource, captureContext);
async function runFixture() {
assert.equal(captureContext.sha256Fallback("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
const page = await captureContext.captureCurrentTab();
assert.equal(page.success, true);
assert.equal(page.dom.redaction, "none");
assert.equal(page.dom.password_values_sanitized, true);
assert.match(page.dom.html, /data-authenticated="true"/);
assert.doesNotMatch(page.dom.html, /do-not-export/);
assert.equal(html.querySelectorAll('input[type="password"]')[0].value, "do-not-export");
assert.match(page.target_origin, /^https:\/\/fixture\.test$/);
assert.match(page.captured_at, /T/);
assert.match(page.document_state_token, /^state:sha256:[0-9a-f]{64}$/);

const webCryptoContext = {...captureContext, crypto: webcrypto};
vm.runInNewContext(captureSource, webCryptoContext);
const webCryptoPage = await webCryptoContext.captureCurrentTab();
assert.equal(webCryptoPage.document_state_token, page.document_state_token);

async function runBackground({timeout = null, hubTimeout = null, finalPostTimeout = null, queryTimeout = false, getTimeout = false, switchTab = false, switchAfterScreenshot = false, screenshotTimeout = false, closed = false, permission = false, navigateAfterScreenshot = false, mutateDocumentAfterScreenshot = false, missingUrl = false, emptyUrl = false, token = ""} = {}) {
  let activeId = closed ? null : 7;
  const posts = [];
  const committedPosts = [];
  let aborted = false;
  const currentTab = {id: 7, windowId: 3};
  if (!missingUrl) currentTab.url = emptyUrl ? "" : page.url;
  const bgContext = {
    __LOCAL_AI_CAPTURE_TIMEOUT_MS__: timeout || 8000,
    __LOCAL_AI_HUB_REQUEST_TIMEOUT_MS__: hubTimeout || 5000,
    __LOCAL_AI_HUB_API_TOKEN__: token,
    AbortController: FakeAbortController,
    chrome: {
      runtime: {getURL: () => "chrome-extension://fixture/"},
      action: {onClicked: {addListener: () => {}}},
      tabs: {
        get: async () => { if (getTimeout) return new Promise(() => {}); return {...currentTab}; },
        query: async () => { if (queryTimeout) return new Promise(() => {}); if (permission) throw new Error("permission denied"); return activeId === null ? [] : [{id: activeId, windowId: 3}]; },
        sendMessage: async (tabId, message) => {
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && navigateAfterScreenshot) {
            return {...page, url: "https://fixture.test/other", target_origin: "https://fixture.test", document_token: "document:new", document_state_token: "state:new"};
          }
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && mutateDocumentAfterScreenshot) {
            captureContext.history.replaceState({step: 2}, "", captureContext.location.href);
            main.append(new FakeElement("p", {}, "DOM changed after screenshot"));
            return {...page, ...(await captureContext.verifyCurrentTab())};
          }
          if (switchTab) activeId = 8;
          return page;
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
      if (hubTimeout || (finalPostTimeout && body.screenshot)) {
        return new Promise((_, reject) => {
          options.signal.addEventListener("abort", () => {
            aborted = true;
            reject(Object.assign(new Error("aborted"), {name: "AbortError"}));
          });
        });
      }
      if (token) assert.equal(options.headers["X-LocalAI-Token"], token);
      posts.push(body);
      const value = body.capture_error ? {success: false, error_code: body.capture_error} : body.capability ? {success: true, bundle_artifact_id: "bundle"} : {success: true, capability: "cap"};
      committedPosts.push(body);
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
  const result = await bgContext.captureCurrentTab(tab);
  return {result, posts, committedPosts, aborted};
}

  const success = await runBackground();
  assert.equal(success.result.success, true);
  assert.equal(success.posts.at(-1).tab_id, 7);
  assert.equal(success.posts.at(-1).window_id, 3);
  assert.match(success.posts.at(-1).dom.html, /data-authenticated="true"/);
  assert.equal(success.posts.at(-1).capture_identity.initial.document_token, "document:1000:0:navigate");

  const timeout = await runBackground({timeout: 5});
  assert.equal(timeout.result.error_code, "timeout");
  assert.equal(timeout.posts.at(-1).capture_error, "timeout");

  const screenshotTimeout = await runBackground({timeout: 5, screenshotTimeout: true});
  assert.equal(screenshotTimeout.result.error_code, "timeout");
  assert.equal(screenshotTimeout.posts.at(-1).capture_error, "timeout");
  const hubTimeoutResult = await runBackground({hubTimeout: 5});
  assert.equal(hubTimeoutResult.result.error_code, "timeout");
  assert.equal(hubTimeoutResult.posts.length, 0);
  assert.equal(hubTimeoutResult.aborted, true);
  const finalPostTimeoutResult = await runBackground({finalPostTimeout: 5});
  assert.equal(finalPostTimeoutResult.result.error_code, "timeout");
  assert.equal(finalPostTimeoutResult.aborted, true);
  assert.equal(finalPostTimeoutResult.committedPosts.some((post) => post.screenshot), false);
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
  const mutated = await runBackground({mutateDocumentAfterScreenshot: true});
  assert.equal(captureContext.history.state.step, 2);
  assert.match(captureContext.document.documentElement.outerHTML, /DOM changed after screenshot/);
  assert.equal(mutated.result.error_code, "target_changed");
  assert.equal(mutated.posts.at(-1).capture_error, "target_changed");
  assert.equal(mutated.posts.some((post) => post.screenshot), false);
  for (const options of [{missingUrl: true}, {emptyUrl: true}]) {
    const missingOrEmpty = await runBackground(options);
    assert.equal(missingOrEmpty.result.error_code, "target_changed");
    assert.equal(missingOrEmpty.posts.at(-1).capture_error, "target_changed");
    assert.equal(missingOrEmpty.posts.some((post) => post.screenshot), false);
  }
  assert.equal((await runBackground({closed: true})).result.error_code, "closed_tab");
  assert.equal((await runBackground({permission: true})).result.error_code, "permission_denied");
  const tokenRun = await runBackground({token: "0123456789abcdef"});
  assert.equal(tokenRun.result.success, true);
  process.stdout.write(JSON.stringify({success: true, fixture: "login-preserving", cases: ["success", "timeout", "screenshot-timeout", "hub-timeout", "final-post-timeout", "query-timeout", "get-timeout", "tab-switch", "same-tab-navigation", "same-url-state-race", "missing-tab-url", "empty-tab-url", "password", "timestamp", "origin", "token"]}));
}

runFixture().catch((error) => { console.error(error); process.exitCode = 1; });
