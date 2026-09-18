function stableElementId(element) {
  const parts = [];
  let cursor = element;
  while (cursor && cursor.parentElement) {
    let index = 0;
    let sibling = cursor;
    while ((sibling = sibling.previousElementSibling)) index += 1;
    parts.unshift(index);
    cursor = cursor.parentElement;
  }
  return `e-${parts.join("-")}`;
}

function visible(element) {
  const style = getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden";
}

function collectAccessibleProjection(elements) {
  return elements.filter(visible).map((element) => ({
    element_id: stableElementId(element),
    role: element.getAttribute("role") || element.tagName.toLowerCase(),
    name: element.getAttribute("aria-label") || (element.textContent || "").trim().slice(0, 256),
  }));
}

function collectVisibleComputedStyles(elements) {
  const styles = {};
  elements.filter(visible).forEach((element) => {
    const computed = getComputedStyle(element);
    styles[stableElementId(element)] = {
      display: computed.display,
      visibility: computed.visibility,
      position: computed.position,
      color: computed.color,
      background_color: computed.backgroundColor,
      font_size: computed.fontSize,
      line_height: computed.lineHeight,
      width: computed.width,
      height: computed.height,
    };
  });
  return styles;
}

function collectRuntimeRefs() {
  const console_refs = Array.isArray(globalThis.__LOCAL_AI_CONSOLE_REFS__)
    ? globalThis.__LOCAL_AI_CONSOLE_REFS__.slice(0, 128).map((item) => {
        if (typeof item === "string" && item.startsWith("console:")) return item.slice(0, 160);
        if (item && typeof item === "object" && item.ref_id) {
          return {ref_id: String(item.ref_id).slice(0, 160), level: String(item.level || "").slice(0, 32)};
        }
        return null;
      }).filter(Boolean)
    : [];
  const network_refs = performance.getEntriesByType("resource").slice(0, 128).map((entry, index) => {
    let safeUrl = "";
    try {
      const parsed = new URL(entry.name, location.href);
      safeUrl = `${parsed.origin}${parsed.pathname}`;
    } catch (_) {}
    return {
      request_id: `resource:${index}`,
      url: safeUrl,
      initiator: entry.initiatorType || "resource",
      duration_ms: Math.round(entry.duration),
      transfer_size: entry.transferSize,
    };
  });
  return {console_refs, network_refs};
}

function safeDomHtml() {
  const clone = document.documentElement.cloneNode(true);
  clone.querySelectorAll('input[type="password"]').forEach((passwordInput) => {
    passwordInput.removeAttribute("value");
    passwordInput["value"] = "";
    passwordInput["defaultValue"] = "";
  });
  return clone.outerHTML;
}

function currentDocumentIdentity() {
  const navigation = performance.getEntriesByType("navigation")[0] || {};
  const document_token = `document:${String(performance.timeOrigin || "unknown")}:${String(navigation.startTime || 0)}:${String(navigation.type || "navigate")}`.slice(0, 256);
  return {
    url: String(location.href).slice(0, 4096),
    target_origin: String(location.origin).slice(0, 256),
    document_token,
  };
}

function captureCurrentTab() {
  const initial_identity = currentDocumentIdentity();
  const allElements = Array.from(document.querySelectorAll("*"));
  const elements = allElements.slice(0, 256).map((element) => ({
    element_id: stableElementId(element),
    tag: element.tagName.toLowerCase(),
    id: element.id || undefined,
    role: element.getAttribute("role") || undefined,
  }));
  return {
    success: true,
    url: initial_identity.url,
    target_origin: initial_identity.target_origin,
    document_token: initial_identity.document_token,
    captured_at: new Date().toISOString(),
    title: document.title,
    capture_identity: {initial: initial_identity},
    dom: {redaction: "none", password_values_sanitized: true, html: safeDomHtml(), elements},
    accessibility: {snapshot: collectAccessibleProjection(allElements.slice(0, 256))},
    computed_styles: collectVisibleComputedStyles(allElements.slice(0, 256)),
    runtime: collectRuntimeRefs(),
    viewport: {width: innerWidth, height: innerHeight, device_scale_factor: devicePixelRatio},
  };
}

function verifyCurrentTab() {
  const identity = currentDocumentIdentity();
  return {success: true, ...identity};
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !["LOCAL_AI_CAPTURE_CURRENT_TAB", "LOCAL_AI_VERIFY_CURRENT_TAB"].includes(message.type)) return undefined;
  try {
    sendResponse(message.type === "LOCAL_AI_CAPTURE_CURRENT_TAB" ? captureCurrentTab() : verifyCurrentTab());
  } catch (_) {
    sendResponse({success: false, error_code: "unsupported"});
  }
  return false;
});
