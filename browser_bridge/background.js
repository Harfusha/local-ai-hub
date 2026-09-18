const HUB_URL = "http://127.0.0.1:11435";
const CAPTURE_TIMEOUT_MS = 8000;

function extensionOrigin() {
  return new URL(chrome.runtime.getURL("/")).origin;
}

function timed(promise, timeoutMs) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), timeoutMs)),
  ]);
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

async function sendFailure(capability, tabId, errorCode) {
  return post("/api/browser/capture", {
    capability,
    origin: extensionOrigin(),
    tab_id: tabId,
    capture_error: errorCode,
  });
}

async function tabStillOpen(tabId) {
  try {
    await chrome.tabs.get(tabId);
    return true;
  } catch (_) {
    return false;
  }
}

async function captureCurrentTab(tab) {
  if (!tab || typeof tab.id !== "number") {
    return {success: false, error_code: "closed_tab", fallback: false};
  }
  const origin = extensionOrigin();
  let capability;
  try {
    const issued = await post("/api/browser/capability", {origin, tab_id: tab.id});
    if (!issued.success) return issued;
    capability = issued.capability;
  } catch (_) {
    return {success: false, error_code: "unsupported", fallback: false};
  }

  let page;
  try {
    page = await timed(chrome.tabs.sendMessage(tab.id, {type: "LOCAL_AI_CAPTURE_CURRENT_TAB"}), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (String(error && error.message) === "timeout") return sendFailure(capability, tab.id, "timeout");
    return sendFailure(capability, tab.id, await tabStillOpen(tab.id) ? "permission_denied" : "closed_tab");
  }
  if (!page || page.success !== true) {
    return sendFailure(capability, tab.id, page && page.error_code ? page.error_code : "unsupported");
  }

  let screenshot;
  try {
    screenshot = await timed(chrome.tabs.captureVisibleTab(tab.windowId, {format: "png"}), CAPTURE_TIMEOUT_MS);
  } catch (_) {
    return sendFailure(capability, tab.id, await tabStillOpen(tab.id) ? "permission_denied" : "closed_tab");
  }
  return post("/api/browser/capture", {
    capability,
    origin,
    tab_id: tab.id,
    screenshot,
    ...page,
  });
}

// The browser action is the only capture trigger. It receives the tab Chrome
// passed for that click; it never queries, activates, updates, or navigates tabs.
chrome.action.onClicked.addListener((tab) => {
  captureCurrentTab(tab).catch(() => undefined);
});
