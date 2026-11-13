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

function timed(promise, timeoutMs, onTimeout = undefined) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_, reject) => { timer = setTimeout(() => {
      if (onTimeout) onTimeout();
      const error = new Error("timeout");
      error.code = "timeout";
      reject(error);
    }, timeoutMs); }),
  ]).finally(() => clearTimeout(timer));
}

function isTimeout(error) {
  return Boolean(error && (error.code === "timeout" || error.message === "timeout"));
}

function isAmbiguousCommitResult(result) {
  return Boolean(
    result && ["capture_in_progress", "commit_outcome_unknown", "timeout"].includes(result.error_code),
  );
}

function isValidCommitResponse(result, expectedRequestId) {
  if (!result || typeof result !== "object" || Array.isArray(result) || typeof result.success !== "boolean") {
    return false;
  }
  if (result.request_id !== undefined && result.request_id !== expectedRequestId) return false;
  if (result.success) {
    return result.request_id === expectedRequestId
      && typeof result.bundle_artifact_id === "string"
      && Boolean(result.bundle_artifact_id.trim());
  }
  return typeof result.error_code === "string" && Boolean(result.error_code.trim());
}

function isValidCaptureBundleId(value) {
  return typeof value === "string" && /^art_[0-9a-f]{24}$/.test(value);
}

async function post(path, payload, {retryServerErrors = false} = {}) {
  if (typeof globalThis.AbortController !== "function") {
    const error = new Error("AbortController unavailable");
    error.code = "unsupported";
    throw error;
  }
  const controller = new globalThis.AbortController();
  const headers = {"Content-Type": "application/json"};
  let response;
  try {
    response = await timed(fetch(`${HUB_URL}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      credentials: "omit",
      signal: controller.signal,
    }), HUB_REQUEST_TIMEOUT_MS, () => controller.abort());
    const value = await timed(response.json(), HUB_REQUEST_TIMEOUT_MS, () => controller.abort());
    if (!response.ok && retryServerErrors && response.status >= 500) {
      const error = new Error("server_error");
      error.code = "server_error";
      throw error;
    }
    if (!response.ok && !value.error_code) {
      value.error_code = response.status === 403 ? "permission_denied" : "unsupported";
    }
    return value;
  } catch (error) {
    if (isTimeout(error) || error && error.name === "AbortError") {
      const timeout = new Error("timeout");
      timeout.code = "timeout";
      throw timeout;
    }
    throw error;
  }
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

function captureRequestId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") return globalThis.crypto.randomUUID().slice(0, 128);
  return `capture-${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;
}

async function abandonCapture(capability, tab, origin, requestId) {
  try {
    return await post("/api/browser/capture/abandon", {
      capability,
      origin,
      tab_id: tab.id,
      window_id: tab.windowId,
      request_id: requestId,
    });
  } catch (_) {
    return {success: false, error_code: "unsupported", fallback: false};
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
      if (!current || typeof current.url !== "string" || !current.url) return {status: "permission_denied"};
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

function supportsCaptureUrl(value) {
  try {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch (_) {
    return false;
  }
}

function isSensitiveOrigin(value) {
  try {
    const labels = new URL(value).hostname.toLowerCase().split(".");
    return labels.some((label) => /^(auth|login|signin|bank|banking|payment|wallet|identity|idp)$/.test(label));
  } catch (_) {
    return false;
  }
}

async function maskSensitiveScreenshot(dataUrl, page) {
  if (!page || page.redaction_complete !== true || !Array.isArray(page.redaction_regions)
    || !page.viewport || page.redaction_regions.length > 512) {
    return {success: false, error_code: "redaction_failed"};
  }
  try {
    if (!chrome.offscreen || typeof chrome.offscreen.hasDocument !== "function") {
      return {success: false, error_code: "redaction_failed"};
    }
    if (!await chrome.offscreen.hasDocument()) {
      await chrome.offscreen.createDocument({
        url: "offscreen.html",
        reasons: ["BLOBS"],
        justification: "Mask sensitive page regions in the locally captured screenshot before staging it to the loopback Hub.",
      });
    }
    const result = await timed(chrome.runtime.sendMessage({
      type: "LOCAL_AI_MASK_SCREENSHOT",
      dataUrl,
      regions: page.redaction_regions,
      viewport: page.viewport,
    }), CAPTURE_TIMEOUT_MS);
    if (!result || result.success !== true || typeof result.dataUrl !== "string"
      || !result.dataUrl.startsWith("data:image/png;base64,")
      || result.maskedRegions !== page.redaction_regions.length) {
      return {success: false, error_code: "redaction_failed"};
    }
    return {success: true, screenshot: result.dataUrl, maskedRegions: result.maskedRegions};
  } catch (_) {
    return {success: false, error_code: "redaction_failed"};
  }
}

function boundedIdentity(value) {
  if (!value || typeof value !== "object") return null;
  const url = String(value.url || "");
  const targetOrigin = String(value.target_origin || "");
  const documentToken = String(value.document_token || "");
  const documentStateToken = String(value.document_state_token || "");
  if (!url || url.length > 4096 || !targetOrigin || targetOrigin.length > 256 || !documentToken || documentToken.length > 256 || !documentStateToken || documentStateToken.length > 256) return null;
  return {
    url,
    target_origin: targetOrigin,
    document_id: String(value.document_id || documentToken).slice(0, 256),
    document_token: documentToken,
    content_revision: String(value.content_revision || "").slice(0, 128),
    interaction_revision: String(value.interaction_revision || "").slice(0, 128),
    document_state_token: documentStateToken,
    relevant_state_token: String(value.relevant_state_token || "").slice(0, 128),
    relevant_state_complete: value.relevant_state_complete === true,
    history_state_token: String(value.history_state_token || "").slice(0, 128),
    viewport_token: String(value.viewport_token || "").slice(0, 128),
    interaction_observed: value.interaction_observed === true,
  };
}

function compareIdentity(left, right) {
  if (!left || !right) return "unverifiable";
  if (left.url !== right.url || left.target_origin !== right.target_origin
    || left.document_id !== right.document_id || left.document_token !== right.document_token) return "target_changed";
  if (!left.relevant_state_complete || !right.relevant_state_complete
    || !left.relevant_state_token || !right.relevant_state_token
    || !left.interaction_observed || !right.interaction_observed) return "unverifiable";
  if (left.interaction_revision !== right.interaction_revision
    || left.history_state_token !== right.history_state_token || left.viewport_token !== right.viewport_token) return "target_changed";
  if (left.relevant_state_token !== right.relevant_state_token) return "target_changed";
  if (left.content_revision !== right.content_revision || left.document_state_token !== right.document_state_token) return "changed_but_safe";
  return "unchanged";
}

function tabUrlMatches(tab, identity) {
  const tabUrl = String(tab && tab.url || "");
  return Boolean(tabUrl && identity && tabUrl === identity.url);
}

async function captureCurrentTab(tab, options = {}) {
  if (!tab || typeof tab.id !== "number" || typeof tab.windowId !== "number") {
    return {success: false, error_code: "closed_tab", fallback: false};
  }
  const privacyMode = options && options.privacyMode;
  if (!["full_local_capture", "privacy_redacted", "screenshot_only"].includes(privacyMode)) {
    return {success: false, error_code: "unsupported_privacy_mode", fallback: false};
  }
  if (options.consentAcknowledged !== true) {
    return {success: false, error_code: "capture_consent_required", fallback: false};
  }
  if (privacyMode === "full_local_capture" && options.fullCaptureAcknowledged !== true) {
    return {success: false, error_code: "full_capture_confirmation_required", fallback: false};
  }
  const initialState = await currentTabState(tab);
  if (initialState.status !== "ok") return {success: false, error_code: initialState.status, fallback: false};
  if (!supportsCaptureUrl(initialState.tab.url)) return {success: false, error_code: "unsupported", fallback: false};
  if (options.blockSensitiveOrigins === true && isSensitiveOrigin(initialState.tab.url)) {
    return {success: false, error_code: "sensitive_origin_blocked", fallback: false};
  }
  const origin = extensionOrigin();
  let capability;
  try {
    const issued = await post("/api/browser/capability", {origin, tab_id: tab.id, window_id: tab.windowId});
    if (!issued.success) return issued;
    capability = issued.capability;
  } catch (error) {
    return {success: false, error_code: isTimeout(error) ? "timeout" : "unsupported", fallback: false};
  }

  try {
    await timed(chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["capture.js"]}), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (isTimeout(error)) return sendFailure(capability, tab, "timeout");
    return sendFailure(capability, tab, "permission_denied");
  }

  let page;
  try {
    page = await timed(chrome.tabs.sendMessage(tab.id, {type: "LOCAL_AI_CAPTURE_CURRENT_TAB", privacyMode}), CAPTURE_TIMEOUT_MS);
  } catch (error) {
    if (isTimeout(error)) return sendFailure(capability, tab, "timeout");
    const status = await activeTabStatus(tab);
    return sendFailure(capability, tab, status === "ok" ? "permission_denied" : status);
  }
  if (!page || page.success !== true) {
    return sendFailure(capability, tab, page && page.error_code ? page.error_code : "unsupported");
  }
  if (page.privacy_mode !== privacyMode) return sendFailure(capability, tab, "privacy_mode_mismatch");
  if (privacyMode === "privacy_redacted" && page.redaction_complete !== true) {
    return sendFailure(capability, tab, "redaction_failed");
  }
  const initialIdentity = boundedIdentity(page.capture_identity && page.capture_identity.initial);
  if (!initialIdentity || !initialIdentity.relevant_state_complete || !initialIdentity.interaction_observed) return sendFailure(capability, tab, "unverifiable");
  if (!tabUrlMatches(initialState.tab, initialIdentity)) return sendFailure(capability, tab, "target_changed");

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
  let maskedRegions = 0;
  if (privacyMode === "privacy_redacted") {
    const masked = await maskSensitiveScreenshot(screenshot, page);
    if (!masked.success) return sendFailure(capability, tab, "redaction_failed");
    screenshot = masked.screenshot;
    maskedRegions = masked.maskedRegions;
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
  const initialConsistency = compareIdentity(initialIdentity, finalIdentity);
  if (["target_changed", "unverifiable"].includes(initialConsistency) || !tabUrlMatches(afterScreenshot.tab, finalIdentity)) {
    return sendFailure(capability, tab, initialConsistency === "unverifiable" ? "unverifiable" : "target_changed");
  }
  const requestId = captureRequestId();
  const stagedPayload = {
      capability,
      origin,
      tab_id: tab.id,
      window_id: tab.windowId,
      request_id: requestId,
      screenshot,
      privacy_mode: privacyMode,
      privacy_notice_acknowledged: true,
      full_capture_acknowledged: privacyMode !== "full_local_capture" || options.fullCaptureAcknowledged === true,
      screenshot_redaction: privacyMode === "privacy_redacted" ? "opaque_region_mask" : "none",
      screenshot_redaction_regions: maskedRegions,
      redaction_manifest: page.redaction_manifest || {},
      ...page,
      capture_identity: {initial: initialIdentity, final: finalIdentity, consistency: initialConsistency},
  };
  delete stagedPayload.redaction_regions;
  delete stagedPayload.redaction_complete;
  try {
    const staged = await post("/api/browser/capture/stage", stagedPayload);
    if (!staged.success) return staged;
    const beforeCommit = await currentTabState(tab);
    if (beforeCommit.status !== "ok" || !tabUrlMatches(beforeCommit.tab, finalIdentity)) {
      await abandonCapture(capability, tab, origin, requestId);
      return {success: false, error_code: beforeCommit.status === "ok" ? "target_changed" : beforeCommit.status, fallback: false};
    }
    let commitIdentity;
    try {
      commitIdentity = await timed(
        chrome.tabs.sendMessage(tab.id, {type: "LOCAL_AI_VERIFY_CURRENT_TAB"}),
        CAPTURE_TIMEOUT_MS,
      );
    } catch (error) {
      await abandonCapture(capability, tab, origin, requestId);
      return {success: false, error_code: isTimeout(error) ? "timeout" : "target_changed", fallback: false};
    }
    const currentIdentity = boundedIdentity(commitIdentity);
    const commitConsistency = compareIdentity(finalIdentity, currentIdentity);
    if (!commitIdentity || commitIdentity.success !== true || ["target_changed", "unverifiable"].includes(commitConsistency)) {
      await abandonCapture(capability, tab, origin, requestId);
      return {success: false, error_code: commitIdentity && commitIdentity.error_code || commitConsistency, fallback: false};
    }
    const commitPayload = {
      capability,
      origin,
      tab_id: tab.id,
      window_id: tab.windowId,
      request_id: requestId,
      capture_consistency: initialConsistency === "changed_but_safe" || commitConsistency === "changed_but_safe"
        ? "changed_but_safe" : "unchanged",
    };
    let committed;
    try {
      committed = await post("/api/browser/capture/commit", commitPayload, {retryServerErrors: true});
    } catch (_) {
      // Commit is idempotent by request_id. Replay once to recover a terminal
      // result when the server committed but the response was lost.
      try {
        committed = await post("/api/browser/capture/commit", commitPayload, {retryServerErrors: true});
      } catch (_) {
        return {success: false, error_code: "commit_outcome_unknown", request_id: requestId, fallback: false};
      }
      if (!isValidCommitResponse(committed, requestId) || isAmbiguousCommitResult(committed)) {
        return {success: false, error_code: "commit_outcome_unknown", request_id: requestId, fallback: false};
      }
    }
    if (!isValidCommitResponse(committed, requestId)) {
      // A malformed 2xx response cannot prove whether the server committed.
      // Replay once with the same idempotency key, then preserve ambiguity.
      try {
        committed = await post("/api/browser/capture/commit", commitPayload, {retryServerErrors: true});
      } catch (_) {
        return {success: false, error_code: "commit_outcome_unknown", request_id: requestId, fallback: false};
      }
      if (!isValidCommitResponse(committed, requestId) || isAmbiguousCommitResult(committed)) {
        return {success: false, error_code: "commit_outcome_unknown", request_id: requestId, fallback: false};
      }
    }
    if (!committed.success) {
      if (isAmbiguousCommitResult(committed)) {
        return {success: false, error_code: "commit_outcome_unknown", request_id: requestId, fallback: false};
      }
      await abandonCapture(capability, tab, origin, requestId);
    }
    return committed;
  } catch (error) {
    await abandonCapture(capability, tab, origin, requestId);
    return {success: false, error_code: isTimeout(error) ? "timeout" : "unsupported", fallback: false};
  }
}

async function purgeCurrentCapture(tab, bundleArtifactId) {
  if (!tab || !Number.isInteger(tab.id) || !Number.isInteger(tab.windowId) || !isValidCaptureBundleId(bundleArtifactId)) {
    return {success: false, error_code: "invalid_request", fallback: false};
  }
  const origin = extensionOrigin();
  try {
    const permission = await post("/api/browser/capability", {
      origin, tab_id: tab.id, window_id: tab.windowId,
    });
    if (!permission || permission.success !== true || typeof permission.capability !== "string" || !permission.capability) {
      return {success: false, error_code: permission && permission.error_code || "permission_denied", fallback: false};
    }
    const result = await post("/api/browser/capture/purge", {
      capability: permission.capability,
      origin,
      tab_id: tab.id,
      window_id: tab.windowId,
      bundle_artifact_id: bundleArtifactId,
    });
    return result && typeof result.success === "boolean"
      ? result
      : {success: false, error_code: "unsupported", fallback: false};
  } catch (error) {
    return {success: false, error_code: isTimeout(error) ? "timeout" : "unsupported", fallback: false};
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !["LOCAL_AI_START_CAPTURE", "LOCAL_AI_PURGE_CAPTURE"].includes(message.type)) return undefined;
  const ownOrigin = extensionOrigin();
  if (!sender || sender.id !== chrome.runtime.id || typeof sender.url !== "string" || !sender.url.startsWith(`${ownOrigin}/`)) {
    sendResponse({success: false, error_code: "unsupported"});
    return false;
  }
  if (message.type === "LOCAL_AI_PURGE_CAPTURE") {
    if (!isValidCaptureBundleId(message.bundle_artifact_id)) {
      sendResponse({success: false, error_code: "invalid_request"});
      return false;
    }
    chrome.tabs.query({active: true, currentWindow: true}).then((tabs) => {
      const tab = Array.isArray(tabs) && tabs[0];
      return purgeCurrentCapture(tab, message.bundle_artifact_id);
    }).then(sendResponse).catch(() => sendResponse({success: false, error_code: "unsupported"}));
    return true;
  }
  if (message.consent_acknowledged !== true) {
    sendResponse({success: false, error_code: "capture_consent_required"});
    return false;
  }
  if (message.privacy_mode === "full_local_capture" && message.full_capture_acknowledged !== true) {
    sendResponse({success: false, error_code: "full_capture_confirmation_required"});
    return false;
  }
  chrome.tabs.query({active: true, currentWindow: true}).then((tabs) => {
    const tab = Array.isArray(tabs) && tabs[0];
    return captureCurrentTab(tab, {
      privacyMode: message.privacy_mode,
      consentAcknowledged: message.consent_acknowledged,
      fullCaptureAcknowledged: message.full_capture_acknowledged,
      blockSensitiveOrigins: message.block_sensitive_origins === true,
    });
  }).then(sendResponse).catch(() => sendResponse({success: false, error_code: "unsupported"}));
  return true;
});
