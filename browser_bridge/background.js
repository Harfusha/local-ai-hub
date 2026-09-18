const HUB_URL = "http://127.0.0.1:11435";
const CAPTURE_TIMEOUT_MS = globalThis.__LOCAL_AI_CAPTURE_TIMEOUT_MS__ || 8000;

function extensionOrigin() {
  return new URL(chrome.runtime.getURL("/")).origin;
}

function timed(promise, timeoutMs) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => {
      const error = new Error("timeout");
      error.code = "timeout";
      reject(error);
    }, timeoutMs)),
  ]);
}

function isTimeout(error) {
  return Boolean(error && (error.code === "timeout" || error.message === "timeout"));
}

async function post(path, payload) {
  const response = await fetch(`${HUB_URL}${path}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const value = await response.json();
  if (!response.ok && !value.error_code) {
    value.error_code = response.status === 403 ? "permission_denied" : "unsupported";
  }
  return value;
}

async function sendFailure(capability, tab, errorCode) {
  return post("/api/browser/capture", {
    capability,
    origin: extensionOrigin(),
    tab_id: tab.id,
    window_id: tab.windowId,
    capture_error: errorCode,
  });
}

async function activeTabStatus(tab) {
  try {
    const activeTabs = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (!activeTabs || activeTabs.length === 0) return "closed_tab";
    const active = activeTabs[0];
    if (active.id !== tab.id || active.windowId !== tab.windowId) return "tab_mismatch";
    try {
      await chrome.tabs.get(tab.id);
    } catch (error) {
      const message = String(error && error.message || "").toLowerCase();
      return /closed|no tab|not found|invalid/.test(message) ? "closed_tab" : "permission_denied";
    }
    return "ok";
  } catch (_) {
    return "permission_denied";
  }
}

async function captureCurrentTab(tab) {
  if (!tab || typeof tab.id !== "number" || typeof tab.windowId !== "number") {
    return {success: false, error_code: "closed_tab", fallback: false};
  }
  const initialStatus = await activeTabStatus(tab);
  if (initialStatus !== "ok") return {success: false, error_code: initialStatus, fallback: false};
  const origin = extensionOrigin();
  let capability;
  try {
    const issued = await post("/api/browser/capability", {origin, tab_id: tab.id, window_id: tab.windowId});
    if (!issued.success) return issued;
    capability = issued.capability;
  } catch (_) {
    return {success: false, error_code: "unsupported", fallback: false};
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

  const beforeScreenshot = await activeTabStatus(tab);
  if (beforeScreenshot !== "ok") return sendFailure(capability, tab, beforeScreenshot);

  let screenshot;
  try {
    screenshot = await timed(chrome.tabs.captureVisibleTab(tab.windowId, {format: "png"}), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (isTimeout(error)) return sendFailure(capability, tab, "timeout");
    const status = await activeTabStatus(tab);
    return sendFailure(capability, tab, status === "ok" ? "permission_denied" : status);
  }
  const afterScreenshot = await activeTabStatus(tab);
  if (afterScreenshot !== "ok") return sendFailure(capability, tab, afterScreenshot);
  return post("/api/browser/capture", {
    capability,
    origin,
    tab_id: tab.id,
    window_id: tab.windowId,
    screenshot,
    ...page,
  });
}

// The browser action is the only capture trigger. It receives the tab Chrome
// passed for that click; it never queries, activates, updates, or navigates tabs.
chrome.action.onClicked.addListener((tab) => {
  captureCurrentTab(tab).catch(() => undefined);
});
