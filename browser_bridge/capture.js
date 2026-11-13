(function installLocalAiCapture() {
const elementIdCache = new WeakMap();
const siblingIndexCache = new WeakMap();

function documentRevisionState() {
  const existing = globalThis.__LOCAL_AI_DOCUMENT_REVISION__;
  if (existing && existing.document === document) return existing;
  const state = {document, content: 0, interaction: 0, observer: null, interactionObserved: false};
  if (typeof globalThis.MutationObserver === "function") {
    state.observer = new MutationObserver(() => { state.content += 1; });
    state.observer.observe(document.documentElement || document, {subtree: true, childList: true, attributes: true, characterData: true});
  }
  if (typeof document.addEventListener === "function") {
    for (const eventName of ["input", "change", "click", "submit"]) {
      document.addEventListener(eventName, () => { state.interaction += 1; }, true);
    }
    state.interactionObserved = true;
  }
  globalThis.__LOCAL_AI_DOCUMENT_REVISION__ = state;
  return state;
}

function stableElementId(element) {
  const cached = elementIdCache.get(element);
  if (cached) return cached;
  const parts = [];
  let cursor = element;
  while (cursor && cursor.parentElement) {
    const parent = cursor.parentElement;
    let indexes = siblingIndexCache.get(parent);
    if (!indexes) {
      indexes = new Map();
      Array.from(parent.children || []).forEach((child, index) => indexes.set(child, index));
      siblingIndexCache.set(parent, indexes);
    }
    const index = indexes.get(cursor);
    if (index === undefined) break;
    parts.unshift(index);
    cursor = parent;
  }
  const identity = `e-${parts.join("-")}`;
  elementIdCache.set(element, identity);
  return identity;
}

function visible(element) {
  let cursor = element;
  while (cursor) {
    if (cursor.getAttribute && cursor.getAttribute("aria-hidden") === "true") return false;
    const style = getComputedStyle(cursor);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse" || style.opacity === "0") return false;
    if (typeof cursor.getBoundingClientRect === "function") {
      const rect = cursor.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0) return false;
      if (rect.bottom < 0 || rect.right < 0 || rect.top > innerHeight || rect.left > innerWidth) return false;
    }
    cursor = cursor.parentElement;
  }
  return true;
}

const MAX_CAPTURE_ELEMENTS = 8192;
const MAX_PROJECTED_ELEMENTS = 256;
const IMPORTANT_ELEMENT = /^(button|input|select|textarea|option|label|summary|h[1-6])$/i;

function selectRelevantElements(elements, totalElementCount = elements.length) {
  const bounded = elements;
  const labelTargets = new Set();
  const labels = document.querySelectorAll("label");
  for (let index = 0; index < Math.min(labels.length, MAX_CAPTURE_ELEMENTS); index += 1) {
    const target = labels[index].getAttribute("for");
    if (target) labelTargets.add(target);
  }
  const ranked = bounded.map((element, index) => {
    const tag = String(element.tagName || "").toLowerCase();
    const role = String(element.getAttribute && element.getAttribute("role") || "").toLowerCase();
    const invalid = element.getAttribute && element.getAttribute("aria-invalid") === "true";
    const labelFor = Boolean(element.id && labelTargets.has(element.id));
    const priority = (visible(element) ? 100 : -1000)
      + (IMPORTANT_ELEMENT.test(tag) ? 80 : 0)
      + (["alert", "status", "dialog", "textbox", "button", "combobox", "checkbox", "radio"].includes(role) ? 50 : 0)
      + (invalid || role === "alert" ? 80 : 0)
      + (labelFor ? 20 : 0)
      + (element.getAttribute && element.getAttribute("aria-label") ? 10 : 0);
    return {element, index, priority};
  });
  ranked.sort((left, right) => right.priority - left.priority || left.index - right.index);
  return {
    all: bounded,
    total: totalElementCount,
    relevantCount: ranked.filter((item) => item.priority > 0).length,
    selected: ranked.filter((item) => item.priority > 0).slice(0, MAX_PROJECTED_ELEMENTS).map((item) => item.element),
  };
}

function boundedHistoryState() {
  let nodes = 0;
  let remainingChars = 32768;
  let complete = true;
  const seen = new WeakSet();
  function visit(value, depth) {
    nodes += 1;
    if (nodes > 512 || depth > 12) { complete = false; return "[bounded]"; }
    if (value === null || typeof value === "boolean" || typeof value === "number") return value;
    if (typeof value === "string") {
      if (value.length > remainingChars) { complete = false; const clipped = value.slice(0, Math.max(0, remainingChars)); remainingChars = 0; return clipped; }
      remainingChars -= value.length;
      return value;
    }
    if (!value || typeof value !== "object") { complete = false; return `[${typeof value}]`; }
    if (seen.has(value)) { complete = false; return "[cycle]"; }
    seen.add(value);
    if (Array.isArray(value)) {
      const result = value.slice(0, 128).map((item) => visit(item, depth + 1));
      if (value.length > 128) complete = false;
      return result;
    }
    const keys = Object.keys(value).sort();
    const result = {};
    for (const key of keys.slice(0, 128)) {
      if (key.length > remainingChars) { complete = false; break; }
      remainingChars -= key.length;
      result[key] = visit(value[key], depth + 1);
    }
    if (keys.length > 128) complete = false;
    return result;
  }
  try { return {value: visit(globalThis.history && globalThis.history.state, 0), complete}; }
  catch (_) { return {value: "[unreadable]", complete: false}; }
}

async function relevantStateFingerprint(selection) {
  const history = boundedHistoryState();
  const historyStateToken = await digestState(JSON.stringify(history.value));
  const viewportToken = `${Number(innerWidth) || 0}x${Number(innerHeight) || 0}@${Number(devicePixelRatio) || 1}`;
  const targets = selection.all.filter((element) => {
    const tag = String(element.tagName || "").toLowerCase();
    const role = String(element.getAttribute && element.getAttribute("role") || "").toLowerCase();
    return IMPORTANT_ELEMENT.test(tag) || tag === "a" && Boolean(element.getAttribute("href"))
      || ["alert", "status", "dialog", "textbox", "button", "combobox", "checkbox", "radio", "link", "tab"].includes(role)
      || Boolean(element.getAttribute && (element.getAttribute("aria-label") || element.getAttribute("aria-invalid") === "true"));
  });
  const active = document.activeElement;
  if (active && !targets.includes(active) && visible(active)) targets.push(active);
  const complete = selection.total <= MAX_CAPTURE_ELEMENTS && targets.length <= MAX_PROJECTED_ELEMENTS && history.complete;
  const elements = targets.slice(0, MAX_PROJECTED_ELEMENTS).map((element) => {
    const attrs = {};
    for (const name of ["id", "role", "aria-label", "aria-labelledby", "aria-describedby", "aria-invalid", "type", "name", "value", "checked", "selected", "disabled", "href", "for"]) {
      const value = element.getAttribute && element.getAttribute(name);
      if (value !== null && value !== undefined) attrs[name] = String(value).slice(0, 512);
    }
    if ("value" in element) attrs.value = String(element.value || "").slice(0, 512);
    if ("checked" in element) attrs.checked = Boolean(element.checked);
    if ("selected" in element) attrs.selected = Boolean(element.selected);
    if ("disabled" in element) attrs.disabled = Boolean(element.disabled);
    const rect = typeof element.getBoundingClientRect === "function" ? element.getBoundingClientRect() : null;
    return {
      element_id: stableElementId(element),
      tag: String(element.tagName || "").toLowerCase(),
      attributes: attrs,
      text: String(element.textContent || "").trim().slice(0, 1024),
      visible: visible(element),
      bounds: rect ? [rect.left, rect.top, rect.width, rect.height].map((value) => Math.round(Number(value) || 0)) : null,
    };
  });
  return {
    relevant_state_token: `sha256:${await digestState(JSON.stringify({elements, historyStateToken, viewportToken}))}`,
    relevant_state_complete: complete,
    history_state_token: historyStateToken,
    viewport_token: viewportToken,
  };
}

function collectAccessibleProjection(elements, privacyMode = "full_local_capture", manifest = {}) {
  return elements.filter(visible).map((element) => {
    const name = element.getAttribute("aria-label") || (element.textContent || "").trim().slice(0, 256);
    const redacted = privacyMode === "privacy_redacted" ? redactSensitiveText(name) : {text: name, manifest: {}};
    addRedactions(manifest, redacted.manifest);
    return {
      element_id: stableElementId(element),
      role: element.getAttribute("role") || element.tagName.toLowerCase(),
      name: redacted.text,
    };
  });
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
      safeUrl = sanitizePrivacyUrl(parsed.href).url;
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

const MAX_DOM_SERIALIZED_CHARS = 2000000;
const MAX_DOM_NODES = 8192;
const MAX_DOM_DEPTH = 128;
const SENSITIVE_ATTRIBUTE = /(^|[-_:])(token|secret|password|passwd|authorization|cookie|csrf|session|api[-_]?key|access[-_]?token|refresh[-_]?token|nonce|signature|state)([-_:]|$)/i;
const URL_ATTRIBUTE = /^(href|src|action|formaction|poster)$/i;
const SENSITIVE_TEXT_RULES = [
  {category: "credential", pattern: /(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|csrf[_-]?token|session(?:[_-]?id)?|secret|password|passwd|authorization|signature|sig)\b\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s&;,<>]+)/gi, replacement: "$1[REDACTED]"},
  {category: "credential", pattern: /\bBearer\s+[A-Za-z0-9._~+\/-]{12,}=*/gi, replacement: "Bearer [REDACTED]"},
  {category: "credential", pattern: /\b(?:eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b/g, replacement: "[REDACTED]"},
  {category: "personal", pattern: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, replacement: "[REDACTED]"},
];

function redactSensitiveText(value) {
  let text = String(value || "");
  const manifest = {};
  for (const rule of SENSITIVE_TEXT_RULES) {
    let count = 0;
    text = text.replace(rule.pattern, (...args) => {
      count += 1;
      return typeof rule.replacement === "function" ? rule.replacement(...args) : args[0].replace(rule.pattern, rule.replacement);
    });
    if (count) manifest[rule.category] = (manifest[rule.category] || 0) + count;
  }
  return {text, manifest};
}

function sanitizePrivacyUrl(value) {
  let parsed;
  try { parsed = new URL(String(value || "")); } catch (_) {
    return {url: "", manifest: {path_segments: 0, query: Boolean(String(value || "").includes("?")), fragment: Boolean(String(value || "").includes("#"))}};
  }
  let redactedSegments = 0;
  const segments = parsed.pathname.split("/").map((segment) => {
    let decoded = segment;
    try { decoded = decodeURIComponent(segment); } catch (_) {}
    const sensitive = decoded.length >= 24
      || /(?:token|secret|signature|(?:^|[-_])auth(?:[-_]|$)|api[-_]?key)\s*[:=_-]/i.test(decoded)
      || /^(?:eyJ[A-Za-z0-9_-]{8,}\.|gh[pousr]_|sk-|AKIA[A-Z0-9]{16})/.test(decoded);
    if (sensitive) { redactedSegments += 1; return "~redacted~"; }
    return segment;
  });
  const hadQuery = Boolean(parsed.search);
  const hadFragment = Boolean(parsed.hash);
  parsed.pathname = segments.join("/");
  parsed.search = "";
  parsed.hash = "";
  return {
    url: `${parsed.origin}${parsed.pathname}`.slice(0, 4096),
    manifest: {path_segments: redactedSegments, query: hadQuery, fragment: hadFragment},
  };
}

function collectRedactionRegions(manifest) {
  const regions = [];
  let complete = true;
  const nodes = document.querySelectorAll("*");
  const limit = Math.min(nodes.length, MAX_CAPTURE_ELEMENTS);
  if (nodes.length > limit) complete = false;
  for (let index = 0; index < limit; index += 1) {
    const element = nodes[index];
    const tag = String(element.tagName || "").toLowerCase();
    const type = String(element.getAttribute && element.getAttribute("type") || "").toLowerCase();
    const editable = element.getAttribute && element.getAttribute("contenteditable") !== null && element.getAttribute("contenteditable") !== "false";
    const formField = tag === "textarea" || editable || (tag === "input" && !["button", "submit", "reset", "checkbox", "radio", "hidden"].includes(type));
    const textNodes = element.childNodes && typeof element.childNodes.length === "number"
      ? Array.from(element.childNodes).filter((node) => node.nodeType === 3).map((node) => String(node.nodeValue || ""))
      : element.children && element.children.length ? [] : [String(element.textContent || "")];
    const text = textNodes.join(" ");
    const detected = redactSensitiveText(text);
    if (formField) addRedactions(manifest, {form_field: 1});
    if (Object.keys(detected.manifest).length) addRedactions(manifest, detected.manifest);
    if (!formField && !Object.keys(detected.manifest).length) continue;
    if (!visible(element)) continue;
    if (typeof element.getBoundingClientRect !== "function") { complete = false; continue; }
    const rect = element.getBoundingClientRect();
    if (!rect || ![rect.left, rect.top, rect.right, rect.bottom].every(Number.isFinite)) { complete = false; continue; }
    const left = Math.max(0, rect.left);
    const top = Math.max(0, rect.top);
    const right = Math.min(innerWidth, rect.right);
    const bottom = Math.min(innerHeight, rect.bottom);
    if (right <= left || bottom <= top) continue;
    const candidate = {x: left, y: top, width: right - left, height: bottom - top};
    const duplicate = regions.some((item) => Math.abs(item.x - candidate.x) < 1 && Math.abs(item.y - candidate.y) < 1
      && Math.abs(item.width - candidate.width) < 1 && Math.abs(item.height - candidate.height) < 1);
    if (!duplicate) regions.push(candidate);
    if (regions.length >= 512) { complete = false; break; }
  }
  return {regions, complete};
}

function attributeEntries(node) {
  if (!node || !node.attributes) return [];
  if (typeof node.attributes.length === "number") {
    return Array.from(node.attributes).map((attribute) => [String(attribute.name), String(attribute.value)]);
  }
  return Object.entries(node.attributes).map(([name, value]) => [String(name), String(value)]);
}

function setSafeAttribute(node, name, value) {
  if (typeof node.setAttribute === "function") node.setAttribute(name, value);
  else if (node.attributes) node.attributes[name] = value;
}

function appendSafeChild(node, child) {
  if (typeof node.appendChild === "function") node.appendChild(child);
  else if (typeof node.append === "function") node.append(child);
}

function addRedactions(manifest, additions) {
  for (const [category, count] of Object.entries(additions || {})) {
    if (count > 0) manifest[category] = (manifest[category] || 0) + count;
  }
}

function safeAttributeValue(source, name, value, privacyMode, manifest) {
  const normalizedName = name.toLowerCase();
  const tagName = String(source.tagName || "").toLowerCase();
  const fieldName = String((typeof source.getAttribute === "function" && source.getAttribute("name")) || "");
  if (normalizedName === "style" || normalizedName === "value" || normalizedName === "integrity" || SENSITIVE_ATTRIBUTE.test(name)) {
    if (privacyMode === "privacy_redacted" && SENSITIVE_ATTRIBUTE.test(name)) addRedactions(manifest, {sensitive_attribute: 1});
    return null;
  }
  if (tagName === "input" && (normalizedName === "checked" || normalizedName === "selected")) return null;
  if (tagName === "option" && normalizedName === "selected") return null;
  if (tagName === "meta" && normalizedName === "content" && SENSITIVE_ATTRIBUTE.test(fieldName)) return null;
  if (!URL_ATTRIBUTE.test(normalizedName)) {
    const text = String(value).slice(0, 4096);
    if (privacyMode !== "privacy_redacted") return text;
    const redacted = redactSensitiveText(text);
    addRedactions(manifest, redacted.manifest);
    return redacted.text;
  }
  if (/^(data|javascript|blob):/i.test(String(value).trim())) return null;
  try {
    const parsed = new URL(String(value), location.href);
    const sanitized = sanitizePrivacyUrl(parsed.href);
    addRedactions(manifest, {url_path_segments: sanitized.manifest.path_segments});
    return sanitized.url;
  } catch (_) {
    return sanitizePrivacyUrl(String(value)).url;
  }
}

function sanitizedDomNode(source, state, depth, privacyMode, manifest) {
  if (!source || depth > MAX_DOM_DEPTH || state.nodes >= MAX_DOM_NODES) return null;
  if (source.nodeType === 3) {
    let text = String(source.nodeValue || "");
    if (privacyMode === "privacy_redacted") {
      const redacted = redactSensitiveText(text);
      text = redacted.text;
      addRedactions(manifest, redacted.manifest);
    }
    const allowed = Math.min(text.length, Math.floor(state.remaining / 6));
    if (allowed <= 0) return null;
    state.remaining -= allowed * 6;
    return document.createTextNode(text.slice(0, allowed));
  }
  const tagName = String(source.tagName || "").toLowerCase();
  if (!tagName || tagName === "script" || tagName === "noscript") return null;
  const copy = source.cloneNode(false);
  state.nodes += 1;
  for (const [name] of attributeEntries(copy)) {
    if (typeof copy.removeAttribute === "function") copy.removeAttribute(name);
    else if (copy.attributes) delete copy.attributes[name];
  }
  for (const [name, value] of attributeEntries(source)) {
    const safe = safeAttributeValue(source, name, value, privacyMode, manifest);
    if (safe !== null && state.remaining > (name.length + safe.length + tagName.length + 8) * 6) {
      setSafeAttribute(copy, name, safe);
      state.remaining -= (name.length + safe.length + 8) * 6;
    }
  }
  if (privacyMode === "privacy_redacted" && (tagName === "textarea" || source.getAttribute && source.getAttribute("contenteditable") !== null && source.getAttribute("contenteditable") !== "false")) {
    copy.textContent = "[REDACTED]";
    state.remaining = Math.max(0, state.remaining - 72);
    addRedactions(manifest, {form_field: 1});
    return copy;
  }
  if (!source.childNodes && tagName !== "textarea") {
    let text = String(source.textContent || "");
    if (privacyMode === "privacy_redacted") {
      const redacted = redactSensitiveText(text);
      text = redacted.text;
      addRedactions(manifest, redacted.manifest);
    }
    const allowed = Math.min(text.length, Math.floor(state.remaining / 6));
    copy.textContent = text.slice(0, allowed);
    state.remaining -= allowed * 6;
  } else {
    copy.textContent = "";
  }
  if (tagName !== "textarea") {
    const children = source.childNodes ? Array.from(source.childNodes) : Array.from(source.children || []);
    for (const child of children) {
      const sanitized = sanitizedDomNode(child, state, depth + 1, privacyMode, manifest);
      if (sanitized) appendSafeChild(copy, sanitized);
      if (state.remaining <= 0) break;
    }
  }
  return copy;
}

function safeDomHtml(privacyMode = "full_local_capture", manifest = {}) {
  const state = {nodes: 0, remaining: MAX_DOM_SERIALIZED_CHARS};
  const clone = sanitizedDomNode(document.documentElement, state, 0, privacyMode, manifest);
  return clone ? String(clone.outerHTML || "").slice(0, MAX_DOM_SERIALIZED_CHARS) : "<html></html>";
}

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function normalizeUtf16(value) {
  const text = String(value);
  let normalized = "";
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        normalized += text[index] + text[index + 1];
        index += 1;
      } else {
        normalized += "\ufffd";
      }
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      normalized += "\ufffd";
    } else {
      normalized += text[index];
    }
  }
  return normalized;
}

function utf8Bytes(value) {
  const text = normalizeUtf16(value);
  if (typeof globalThis.TextEncoder === "function") return Array.from(new globalThis.TextEncoder().encode(text));
  const bytes = [];
  for (let index = 0; index < text.length; index += 1) {
    let code = text.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff && index + 1 < text.length) {
      const next = text.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + next - 0xdc00;
        index += 1;
      }
    }
    if (code < 0x80) bytes.push(code);
    else if (code < 0x800) bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    else if (code < 0x10000) bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    else bytes.push(0xf0 | (code >> 18), 0x80 | ((code >> 12) & 0x3f), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
  }
  return bytes;
}

function rotateRight(value, bits) {
  return (value >>> bits) | (value << (32 - bits));
}

function sha256Fallback(value) {
  const bytes = utf8Bytes(value);
  const bitLength = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  const high = Math.floor(bitLength / 0x100000000);
  const low = bitLength >>> 0;
  for (const shift of [24, 16, 8, 0]) bytes.push((high >>> shift) & 0xff);
  for (const shift of [24, 16, 8, 0]) bytes.push((low >>> shift) & 0xff);
  const state = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  for (let offset = 0; offset < bytes.length; offset += 64) {
    const words = new Array(64).fill(0);
    for (let index = 0; index < 16; index += 1) {
      const start = offset + index * 4;
      words[index] = ((bytes[start] << 24) | (bytes[start + 1] << 16) | (bytes[start + 2] << 8) | bytes[start + 3]) >>> 0;
    }
    for (let index = 16; index < 64; index += 1) {
      const value1 = words[index - 15];
      const value2 = words[index - 2];
      const small0 = rotateRight(value1, 7) ^ rotateRight(value1, 18) ^ (value1 >>> 3);
      const small1 = rotateRight(value2, 17) ^ rotateRight(value2, 19) ^ (value2 >>> 10);
      words[index] = (words[index - 16] + small0 + words[index - 7] + small1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let index = 0; index < 64; index += 1) {
      const big1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + big1 + choice + SHA256_K[index] + words[index]) >>> 0;
      const big0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (big0 + majority) >>> 0;
      [h, g, f, e, d, c, b, a] = [g, f, e, (d + temp1) >>> 0, c, b, a, (temp1 + temp2) >>> 0];
    }
    state[0] = (state[0] + a) >>> 0;
    state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0;
    state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0;
    state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0;
    state[7] = (state[7] + h) >>> 0;
  }
  return state.map((value) => value.toString(16).padStart(8, "0")).join("");
}

async function digestState(value) {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && cryptoApi.subtle && typeof cryptoApi.subtle.digest === "function" && typeof globalThis.Uint8Array === "function") {
    try {
      const digest = await cryptoApi.subtle.digest("SHA-256", new globalThis.Uint8Array(utf8Bytes(value)));
      return Array.from(new globalThis.Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    } catch (_) {}
  }
  return sha256Fallback(value);
}

async function currentDocumentStateToken() {
  const revision = documentRevisionState();
  if (revision && revision.observer) return `state:content-${revision.content}:interaction-${revision.interaction}`;
  return "state:content-unobserved";
}

async function currentDocumentIdentity() {
  const navigation = performance.getEntriesByType("navigation")[0] || {};
  const document_token = `document:${String(performance.timeOrigin || "unknown")}:${String(navigation.startTime || 0)}:${String(navigation.type || "navigate")}`.slice(0, 256);
  const revision = documentRevisionState();
  const nodeList = document.querySelectorAll("*");
  const totalElementCount = Math.max(0, Number(nodeList.length) || 0);
  const candidates = [];
  for (let index = 0; index < Math.min(totalElementCount, MAX_CAPTURE_ELEMENTS); index += 1) candidates.push(nodeList[index]);
  const fingerprint = await relevantStateFingerprint(selectRelevantElements(candidates, totalElementCount));
  return {
    url: String(location.href).slice(0, 4096),
    target_origin: String(location.origin).slice(0, 256),
    document_id: document_token,
    document_token,
    content_revision: revision && revision.observer ? String(revision.content) : "",
    interaction_revision: revision ? String(revision.interaction) : "",
    document_state_token: await currentDocumentStateToken(),
    ...fingerprint,
    interaction_observed: Boolean(revision && revision.interactionObserved),
  };
}

async function captureCurrentTab(options = {}) {
  const privacyMode = options && options.privacyMode || "full_local_capture";
  if (!["full_local_capture", "privacy_redacted", "screenshot_only"].includes(privacyMode)) {
    return {success: false, error_code: "unsupported_privacy_mode"};
  }
  const initial_identity = await currentDocumentIdentity();
  const redactionManifest = {};
  const urlPrivacy = sanitizePrivacyUrl(initial_identity.url);
  redactionManifest.url_path_segments = urlPrivacy.manifest.path_segments;
  if (urlPrivacy.manifest.query) redactionManifest.url_query = 1;
  if (urlPrivacy.manifest.fragment) redactionManifest.url_fragment = 1;
  const capturedHtml = privacyMode === "screenshot_only" ? "" : safeDomHtml(privacyMode, redactionManifest);
  const snapshotDigest = `sha256:${await digestState(capturedHtml)}`;
  const nodeList = privacyMode === "screenshot_only" ? [] : document.querySelectorAll("*");
  const selectedCandidates = [];
  const totalElementCount = Math.max(0, Number(nodeList.length) || 0);
  for (let index = 0; index < Math.min(totalElementCount, MAX_CAPTURE_ELEMENTS); index += 1) {
    selectedCandidates.push(nodeList[index]);
  }
  const selection = selectRelevantElements(selectedCandidates, totalElementCount);
  const relevantFingerprint = await relevantStateFingerprint(selection);
  const allElements = selection.all;
  const selectedElements = selection.selected;
  const elements = selectedElements.map((element) => ({
    element_id: stableElementId(element),
    tag: element.tagName.toLowerCase(),
    id: privacyMode === "privacy_redacted" ? redactSensitiveText(element.id || "").text || undefined : element.id || undefined,
    role: element.getAttribute("role") || undefined,
  }));
  const accessibility = privacyMode === "screenshot_only"
    ? {snapshot: []}
    : {snapshot: collectAccessibleProjection(selectedElements, privacyMode, redactionManifest)};
  const runtime = privacyMode === "screenshot_only"
    ? {console_refs: [], network_refs: []}
    : collectRuntimeRefs();
  if (privacyMode === "privacy_redacted") runtime.console_refs = [];
  const redaction = privacyMode === "privacy_redacted"
    ? collectRedactionRegions(redactionManifest)
    : {regions: [], complete: true};
  redactionManifest.screenshot_regions = redaction.regions.length;
  if (privacyMode === "privacy_redacted") {
    const titleRedaction = redactSensitiveText(document.title);
    addRedactions(redactionManifest, titleRedaction.manifest);
  }
  return {
    success: true,
    privacy_mode: privacyMode,
    url: initial_identity.url,
    target_origin: initial_identity.target_origin,
    document_token: initial_identity.document_token,
    document_state_token: initial_identity.document_state_token,
    captured_at: new Date().toISOString(),
    title: privacyMode === "screenshot_only" ? "Screenshot-only capture" : privacyMode === "privacy_redacted" ? redactSensitiveText(document.title).text : document.title,
    capture_identity: {initial: initial_identity},
    ...relevantFingerprint,
    dom: {
      redaction: privacyMode === "privacy_redacted" ? "deterministic" : "none", password_values_sanitized: true, html: capturedHtml, snapshot_digest: snapshotDigest, elements,
      element_count_total: selection.total,
      element_count_selected: selectedElements.length,
      coverage_incomplete: selection.total > selectedElements.length,
      selection_reason: "visible controls, headings, labels, and status/error elements ranked first; IDs are stable only for this DOM revision",
    },
    accessibility,
    computed_styles: privacyMode === "screenshot_only" ? {} : collectVisibleComputedStyles(selectedElements),
    runtime,
    redaction_regions: redaction.regions,
    redaction_complete: redaction.complete,
    redaction_manifest: privacyMode === "privacy_redacted" ? redactionManifest : {
      url_path_segments: urlPrivacy.manifest.path_segments,
      url_query_removed: urlPrivacy.manifest.query,
      url_fragment_removed: urlPrivacy.manifest.fragment,
    },
    viewport: {width: innerWidth, height: innerHeight, device_scale_factor: devicePixelRatio},
  };
}

async function verifyCurrentTab() {
  const identity = await currentDocumentIdentity();
  return {success: true, ...identity};
}

if (!globalThis.__LOCAL_AI_CAPTURE_LISTENER_INSTALLED__) {
  globalThis.__LOCAL_AI_CAPTURE_LISTENER_INSTALLED__ = true;
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !["LOCAL_AI_CAPTURE_CURRENT_TAB", "LOCAL_AI_VERIFY_CURRENT_TAB"].includes(message.type)) return undefined;
    Promise.resolve(message.type === "LOCAL_AI_CAPTURE_CURRENT_TAB" ? captureCurrentTab({privacyMode: message.privacyMode}) : verifyCurrentTab())
      .then(sendResponse)
      .catch(() => sendResponse({success: false, error_code: "unsupported"}));
    return true;
  });
}
globalThis.captureCurrentTab = captureCurrentTab;
globalThis.verifyCurrentTab = verifyCurrentTab;
globalThis.currentDocumentIdentity = currentDocumentIdentity;
globalThis.sha256Fallback = sha256Fallback;
globalThis.digestState = digestState;
globalThis.redactSensitiveText = redactSensitiveText;
globalThis.sanitizePrivacyUrl = sanitizePrivacyUrl;
})();
