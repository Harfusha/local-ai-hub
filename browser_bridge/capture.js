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

const MAX_DOM_SERIALIZED_CHARS = 2000000;
const MAX_DOM_NODES = 8192;
const MAX_DOM_DEPTH = 128;
const SENSITIVE_ATTRIBUTE = /(^|[-_:])(token|secret|password|passwd|authorization|cookie|csrf|session|api[-_]?key|access[-_]?token|refresh[-_]?token|nonce|signature|state)([-_:]|$)/i;
const URL_ATTRIBUTE = /^(href|src|action|formaction|poster)$/i;

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

function safeAttributeValue(source, name, value) {
  const normalizedName = name.toLowerCase();
  const tagName = String(source.tagName || "").toLowerCase();
  const fieldName = String((typeof source.getAttribute === "function" && source.getAttribute("name")) || "");
  if (normalizedName === "style" || normalizedName === "value" || normalizedName === "integrity" || SENSITIVE_ATTRIBUTE.test(name)) return null;
  if (tagName === "input" && (normalizedName === "checked" || normalizedName === "selected")) return null;
  if (tagName === "option" && normalizedName === "selected") return null;
  if (tagName === "meta" && normalizedName === "content" && SENSITIVE_ATTRIBUTE.test(fieldName)) return null;
  if (!URL_ATTRIBUTE.test(normalizedName)) return String(value).slice(0, 4096);
  if (/^(data|javascript|blob):/i.test(String(value).trim())) return null;
  try {
    const parsed = new URL(String(value), location.href);
    return `${parsed.origin}${parsed.pathname}`.slice(0, 4096);
  } catch (_) {
    return String(value).split(/[?#]/, 1)[0].slice(0, 4096);
  }
}

function sanitizedDomNode(source, state, depth) {
  if (!source || depth > MAX_DOM_DEPTH || state.nodes >= MAX_DOM_NODES) return null;
  if (source.nodeType === 3) {
    const text = String(source.nodeValue || "");
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
    const safe = safeAttributeValue(source, name, value);
    if (safe !== null && state.remaining > (name.length + safe.length + tagName.length + 8) * 6) {
      setSafeAttribute(copy, name, safe);
      state.remaining -= (name.length + safe.length + 8) * 6;
    }
  }
  if (!source.childNodes && tagName !== "textarea") {
    const text = String(source.textContent || "");
    const allowed = Math.min(text.length, Math.floor(state.remaining / 6));
    copy.textContent = text.slice(0, allowed);
    state.remaining -= allowed * 6;
  } else {
    copy.textContent = "";
  }
  if (tagName !== "textarea") {
    const children = source.childNodes ? Array.from(source.childNodes) : Array.from(source.children || []);
    for (const child of children) {
      const sanitized = sanitizedDomNode(child, state, depth + 1);
      if (sanitized) appendSafeChild(copy, sanitized);
      if (state.remaining <= 0) break;
    }
  }
  return copy;
}

function safeDomHtml() {
  const state = {nodes: 0, remaining: MAX_DOM_SERIALIZED_CHARS};
  const clone = sanitizedDomNode(document.documentElement, state, 0);
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
  let historyState = "";
  try {
    historyState = JSON.stringify(globalThis.history && globalThis.history.state) || "";
  } catch (_) {}
  return `state:sha256:${await digestState(`${safeDomHtml()}\n${historyState}`)}`.slice(0, 256);
}

async function currentDocumentIdentity() {
  const navigation = performance.getEntriesByType("navigation")[0] || {};
  const document_token = `document:${String(performance.timeOrigin || "unknown")}:${String(navigation.startTime || 0)}:${String(navigation.type || "navigate")}`.slice(0, 256);
  return {
    url: String(location.href).slice(0, 4096),
    target_origin: String(location.origin).slice(0, 256),
    document_token,
    document_state_token: await currentDocumentStateToken(),
  };
}

async function captureCurrentTab() {
  const initial_identity = await currentDocumentIdentity();
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
    document_state_token: initial_identity.document_state_token,
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

async function verifyCurrentTab() {
  const identity = await currentDocumentIdentity();
  return {success: true, ...identity};
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !["LOCAL_AI_CAPTURE_CURRENT_TAB", "LOCAL_AI_VERIFY_CURRENT_TAB"].includes(message.type)) return undefined;
  Promise.resolve(message.type === "LOCAL_AI_CAPTURE_CURRENT_TAB" ? captureCurrentTab() : verifyCurrentTab())
    .then(sendResponse)
    .catch(() => sendResponse({success: false, error_code: "unsupported"}));
  return true;
});
