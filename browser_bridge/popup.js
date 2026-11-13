(function installLocalAiCapturePopup() {
  const VALID_MODES = ["full_local_capture", "privacy_redacted", "screenshot_only"];

  function buildCaptureRequest(mode, noticeAccepted, fullCaptureAcknowledged) {
    if (!VALID_MODES.includes(mode) || noticeAccepted !== true) return null;
    if (mode === "full_local_capture" && fullCaptureAcknowledged !== true) return null;
    return mode;
  }

  globalThis.buildCaptureRequest = buildCaptureRequest;
  if (!globalThis.document || !globalThis.chrome || !chrome.storage || !chrome.runtime) return;

  const byId = (id) => document.getElementById(id);
  const mode = byId("captureMode");
  const notice = byId("noticeAccepted");
  const fullAck = byId("fullCaptureAcknowledged");
  const blockSensitive = byId("blockSensitiveOrigins");
  const button = byId("captureButton");
  const purgeButton = byId("purgeCaptureButton");
  const description = byId("modeDescription");
  const status = byId("captureStatus");
  const descriptions = {
    privacy_redacted: "Masks form fields and recognized credential or email patterns in page evidence and screenshot. Detection is deterministic and can miss unknown secrets.",
    screenshot_only: "Stores the screenshot and limited page metadata. DOM, accessibility, styles, and resource references are omitted.",
    full_local_capture: "Stores unredacted page evidence locally. A second confirmation is required for every full capture.",
  };
  let noticeWasAccepted = false;
  let busy = false;
  let lastBundleArtifactId = null;

  function update() {
    const selected = mode.value;
    fullAck.disabled = selected !== "full_local_capture";
    if (selected !== "full_local_capture") fullAck.checked = false;
    description.textContent = descriptions[selected] || "Unsupported capture mode.";
    button.disabled = busy || buildCaptureRequest(selected, notice.checked, fullAck.checked) === null;
    purgeButton.disabled = busy || !lastBundleArtifactId;
    purgeButton.hidden = !lastBundleArtifactId;
  }

  chrome.storage.local.get(["captureNoticeAccepted", "blockSensitiveOrigins"]).then((settings) => {
    noticeWasAccepted = settings.captureNoticeAccepted === true;
    notice.checked = noticeWasAccepted;
    notice.disabled = noticeWasAccepted;
    blockSensitive.checked = settings.blockSensitiveOrigins !== false;
    update();
  }).catch(() => {
    notice.checked = false;
    notice.disabled = false;
    update();
  });

  mode.addEventListener("change", update);
  notice.addEventListener("change", update);
  fullAck.addEventListener("change", update);
  button.addEventListener("click", async () => {
    const selected = buildCaptureRequest(mode.value, notice.checked, fullAck.checked);
    if (!selected) return;
    busy = true;
    update();
    status.textContent = "Capturing locally…";
    try {
      if (!noticeWasAccepted) {
        await chrome.storage.local.set({captureNoticeAccepted: true});
        noticeWasAccepted = true;
        notice.disabled = true;
      }
      await chrome.storage.local.set({blockSensitiveOrigins: blockSensitive.checked});
      const result = await chrome.runtime.sendMessage({
        type: "LOCAL_AI_START_CAPTURE",
        privacy_mode: selected,
        consent_acknowledged: true,
        full_capture_acknowledged: selected !== "full_local_capture" || fullAck.checked,
        block_sensitive_origins: blockSensitive.checked,
      });
      status.textContent = result && result.success
        ? `Saved locally. Bundle: ${result.bundle_artifact_id}`
        : `Capture failed: ${result && result.error_code || "unsupported"}`;
      lastBundleArtifactId = result && result.success && typeof result.bundle_artifact_id === "string"
        ? result.bundle_artifact_id : null;
    } catch (_) {
      status.textContent = "Capture failed: unsupported";
    } finally {
      busy = false;
      update();
    }
  });
  purgeButton.addEventListener("click", async () => {
    if (!lastBundleArtifactId || busy) return;
    busy = true;
    update();
    status.textContent = "Deleting capture locally…";
    try {
      const result = await chrome.runtime.sendMessage({
        type: "LOCAL_AI_PURGE_CAPTURE",
        bundle_artifact_id: lastBundleArtifactId,
      });
      if (result && result.success) {
        lastBundleArtifactId = null;
        status.textContent = "Capture and unshared evidence deleted.";
      } else {
        status.textContent = `Delete failed: ${result && result.error_code || "unsupported"}`;
      }
    } catch (_) {
      status.textContent = "Delete failed: unsupported";
    } finally {
      busy = false;
      update();
    }
  });
  update();
})();
