const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const captureSource = fs.readFileSync(process.argv[2], "utf8");
const backgroundSource = fs.readFileSync(process.argv[3], "utf8");
const fixture = fs.readFileSync(process.argv[4], "utf8");

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
    if (this.tagName === "HTML") {
      const password = this.querySelectorAll('input[type="password"]')[0];
      return fixture.replace("</body>", `${password ? password.outerHTML : ""}</body>`);
    }
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
  performance: {timeOrigin: 1000, getEntriesByType: (type) => type === "navigation" ? [{startTime: 0, type: "navigate"}] : [{name: "https://fixture.test/app.js?token=hidden", initiatorType: "script", duration: 2, transferSize: 10}]},
  getComputedStyle: () => ({display: "block", visibility: "visible", position: "static", color: "black", backgroundColor: "white", fontSize: "16px", lineHeight: "20px", width: "100px", height: "20px"}),
  innerWidth: 1280,
  innerHeight: 720,
  devicePixelRatio: 1,
  chrome: {runtime: {onMessage: {addListener: () => {}}}},
  URL,
};
vm.runInNewContext(captureSource, captureContext);
const page = captureContext.captureCurrentTab();
assert.equal(page.success, true);
assert.equal(page.dom.redaction, "none");
assert.equal(page.dom.password_values_sanitized, true);
assert.match(page.dom.html, /data-authenticated="true"/);
assert.doesNotMatch(page.dom.html, /do-not-export/);
assert.equal(html.querySelectorAll('input[type="password"]')[0].value, "do-not-export");
assert.match(page.target_origin, /^https:\/\/fixture\.test$/);
assert.match(page.captured_at, /T/);

async function runBackground({timeout = null, switchTab = false, switchAfterScreenshot = false, screenshotTimeout = false, closed = false, permission = false, navigateAfterScreenshot = false} = {}) {
  let activeId = closed ? null : 7;
  const posts = [];
  const bgContext = {
    __LOCAL_AI_CAPTURE_TIMEOUT_MS__: timeout || 8000,
    chrome: {
      runtime: {getURL: () => "chrome-extension://fixture/"},
      action: {onClicked: {addListener: () => {}}},
      tabs: {
        get: async () => ({id: 7, windowId: 3, url: page.url}),
        query: async () => { if (permission) throw new Error("permission denied"); return activeId === null ? [] : [{id: activeId, windowId: 3}]; },
        sendMessage: async (tabId, message) => {
          if (message.type === "LOCAL_AI_VERIFY_CURRENT_TAB" && navigateAfterScreenshot) {
            return {...page, url: "https://fixture.test/other", target_origin: "https://fixture.test", document_token: "document:new"};
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
      posts.push(body);
      const value = body.capture_error ? {success: false, error_code: body.capture_error} : body.capability ? {success: true, bundle_artifact_id: "bundle"} : {success: true, capability: "cap"};
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
  return {result, posts};
}

(async () => {
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
  assert.equal((await runBackground({closed: true})).result.error_code, "closed_tab");
  assert.equal((await runBackground({permission: true})).result.error_code, "permission_denied");
  process.stdout.write(JSON.stringify({success: true, fixture: "login-preserving", cases: ["success", "timeout", "tab-switch", "same-tab-navigation", "password", "timestamp", "origin"]}));
})().catch((error) => { console.error(error); process.exitCode = 1; });
