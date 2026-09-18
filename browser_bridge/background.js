const HUB_URL = "http://127.0.0.1:11435";
const DEFAULT_CAPTURE_TIMEOUT_MS = 8000;
const DEFAULT_HUB_TIMEOUT_MS = 5000;

function boundedTimeout(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 1 && parsed <= 30000 ? Math.floor(parsed) : fallback;
}

const CAPTURE_TIMEOUT_MS = boundedTimeout(globalThis.__LOCAL_AI_CAPTURE_TIMEOUT_MS__, DEFAULT_CAPTURE_TIMEOUT_MS);
const HUB_REQUEST_TIMEOUT_MS = boundedTimeout(globalThis.__LOCAL_AI_HUB_REQUEST_TIMEOUT_MS__, DEFAULT_HUB_TIMEOUT_MS);

function extensionOrigin() {
  return new URL(chrome.runtime.getURL("/")).origin;
}

function timed(promise, timeoutMs) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => {
      const error = new Error("timeout");
      error.code = "timeout";
      reject(error);
    }, timeoutMs); }),
  ]).finally(() => clearTimeout(timer));
}

function isTimeout(error) {
  return Boolean(error && (error.code === "timeout" || error.message === "timeout"));
}

async function post(path, payload) {
  const apiToken = String(globalThis.__LOCAL_AI_HUB_API_TOKEN__ || "").trim();
  const headers = {"Content-Type": "application/json"};
  if (apiToken) headers["X-LocalAI-Token"] = apiToken;
  const response = await timed(fetch(`${HUB_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    credentials: "omit",
  }), HUB_REQUEST_TIMEOUT_MS);
  const value = await timed(response.json(), HUB_REQUEST_TIMEOUT_MS);
  if (!response.ok && !value.error_code) {
    value.error_code = response.status === 403 ? "permission_denied" : "unsupported";
  }
  return value;
}

async function sendFailure(capability, tab, errorCode) {
  try {
    return await post("/api/browser/capture", {
    capability,
    origin: extensionOrigin(),
    tab_id: tab.id,
    window_id: tab.windowId,
    capture_error: errorCode,
    });
  } catch (error) {
    return {success: false, error_code: isTimeout(error) ? "timeout" : "unsupported", fallback: false};
  }
}

async function currentTabState(tab) {
  try {
    const activeTabs = await timed(Promise.resolve().then(() => chrome.tabs.query({active: true, windowId: tab.windowId})), CAPTURE_TIMEOUT_MS);
    if (!activeTabs || activeTabs.length === 0) return {status: "closed_tab"};
    const active = activeTabs[0];
    if (active.id !== tab.id || active.windowId !== tab.windowId) return {status: "tab_mismatch"};
    try {
      const current = await timed(Promise.resolve().then(() => chrome.tabs.get(tab.id)), CAPTURE_TIMEOUT_MS);
      return {status: "ok", tab: current};
    } catch (error) {
      if (isTimeout(error)) return {status: "timeout"};
      const message = String(error && error.message || "").toLowerCase();
      return {status: /closed|no tab|not found|invalid/.test(message) ? "closed_tab" : "permission_denied"};
    }
  } catch (error) {
    if (isTimeout(error)) return {status: "timeout"};
    return {status: "permission_denied"};
  }
}

async function activeTabStatus(tab) {
  return (await currentTabState(tab)).status;
}

function boundedIdentity(value) {
  if (!value || typeof value !== "object") return null;
  const url = String(value.url || "");
  const targetOrigin = String(value.target_origin || "");
  const documentToken = String(value.document_token || "");
  const documentStateToken = String(value.document_state_token || "");
  if (!url || url.length > 4096 || !targetOrigin || targetOrigin.length > 256 || !documentToken || documentToken.length > 256 || !documentStateToken || documentStateToken.length > 256) return null;
  return {url, target_origin: targetOrigin, document_token: documentToken, document_state_token: documentStateToken};
}

function sameIdentity(left, right) {
  return Boolean(left && right && left.url === right.url && left.target_origin === right.target_origin && left.document_token === right.document_token && left.document_state_token === right.document_state_token);
}

function tabUrlMatches(tab, identity) {
  const tabUrl = String(tab && tab.url || "");
  return Boolean(tabUrl && identity && tabUrl === identity.url);
}

async function captureCurrentTab(tab) {
  if (!tab || typeof tab.id !== "number" || typeof tab.windowId !== "number") {
    return {success: false, error_code: "closed_tab", fallback: false};
  }
  const initialState = await currentTabState(tab);
  if (initialState.status !== "ok") return {success: false, error_code: initialState.status, fallback: false};
  const origin = extensionOrigin();
  let capability;
  try {
    const issued = await post("/api/browser/capability", {origin, tab_id: tab.id, window_id: tab.windowId});
    if (!issued.success) return issued;
    capability = issued.capability;
  } catch (error) {
    return {success: false, error_code: isTimeout(error) ? "timeout" : "unsupported", fallback: false};
  }

  let page;
  try {
    page = await timed(chrome.tabs.sendMessage(tab.id, {type: "LOCAL_AI_CAPTURE_CURRENT_TAB"}), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (isTimeout(error)) return sendFailure(capability, tab, "timeout");
    const status = await activeTabStatus(tab);
    return sendFailure(capability, tab, status === "ok" ? "permission_denied" : status);
  }
  if (!page || page.success !== true) {
    return sendFailure(capability, tab, page && page.error_code ? page.error_code : "unsupported");
  }
  const initialIdentity = boundedIdentity(page.capture_identity && page.capture_identity.initial);
  if (!initialIdentity || !tabUrlMatches(initialState.tab, initialIdentity)) return sendFailure(capability, tab, "target_changed");

  const beforeScreenshot = await currentTabState(tab);
  if (beforeScreenshot.status !== "ok") return sendFailure(capability, tab, beforeScreenshot.status);
  if (!tabUrlMatches(beforeScreenshot.tab, initialIdentity)) return sendFailure(capability, tab, "target_changed");

  let screenshot;
  try {
    screenshot = await timed(Promise.resolve().then(() => chrome.tabs.captureVisibleTab(tab.windowId, {format: "png"})), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (isTimeout(error)) return sendFailure(capability, tab, "timeout");
    const status = await activeTabStatus(tab);
    return sendFailure(capability, tab, status === "ok" ? "permission_denied" : status);
  }
  const afterScreenshot = await currentTabState(tab);
  if (afterScreenshot.status !== "ok") return sendFailure(capability, tab, afterScreenshot.status);
  if (!tabUrlMatches(afterScreenshot.tab, initialIdentity)) return sendFailure(capability, tab, "target_changed");

  let finalPage;
  try {
    finalPage = await timed(chrome.tabs.sendMessage(tab.id, {type: "LOCAL_AI_VERIFY_CURRENT_TAB"}), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (isTimeout(error)) return sendFailure(capability, tab, "timeout");
    const status = await activeTabStatus(tab);
    return sendFailure(capability, tab, status === "ok" ? "permission_denied" : status);
  }
  if (!finalPage || finalPage.success !== true) return sendFailure(capability, tab, finalPage && finalPage.error_code ? finalPage.error_code : "unsupported");
  const finalIdentity = boundedIdentity(finalPage);
  if (!sameIdentity(initialIdentity, finalIdentity) || !tabUrlMatches(afterScreenshot.tab, finalIdentity)) {
    return sendFailure(capability, tab, "target_changed");
  }
  try {
    return await post("/api/browser/capture", {
      capability,
      origin,
      tab_id: tab.id,
      window_id: tab.windowId,
      screenshot,
      ...page,
      capture_identity: {initial: initialIdentity, final: finalIdentity},
    });
  } catch (error) {
    return {success: false, error_code: isTimeout(error) ? "timeout" : "unsupported", fallback: false};
  }
}

// The browser action is the only capture trigger. It receives the tab Chrome
// passed for that click; it never queries, activates, updates, or navigates tabs.
chrome.action.onClicked.addListener((tab) => {
  captureCurrentTab(tab).catch(() => undefined);
});
