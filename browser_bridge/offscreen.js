(function installLocalAiScreenshotMasker() {
  function scaleRedactionRegions(regions, viewport, imageWidth, imageHeight) {
    if (!Array.isArray(regions) || regions.length > 512) throw new Error("invalid redaction regions");
    if (!viewport || !Number.isFinite(viewport.width) || !Number.isFinite(viewport.height)
      || viewport.width <= 0 || viewport.height <= 0
      || !Number.isInteger(imageWidth) || !Number.isInteger(imageHeight) || imageWidth <= 0 || imageHeight <= 0) {
      throw new Error("invalid redaction viewport");
    }
    const scaleX = imageWidth / viewport.width;
    const scaleY = imageHeight / viewport.height;
    return regions.map((region) => {
      if (!region || ![region.x, region.y, region.width, region.height].every(Number.isFinite)
        || region.x < 0 || region.y < 0 || region.width <= 0 || region.height <= 0) {
        throw new Error("invalid redaction region");
      }
      if (region.x + region.width > viewport.width || region.y + region.height > viewport.height) {
        throw new Error("redaction region outside viewport");
      }
      const x = Math.max(0, Math.floor(region.x * scaleX));
      const y = Math.max(0, Math.floor(region.y * scaleY));
      const right = Math.min(imageWidth, Math.ceil((region.x + region.width) * scaleX));
      const bottom = Math.min(imageHeight, Math.ceil((region.y + region.height) * scaleY));
      return {x, y, width: right - x, height: bottom - y};
    });
  }

  async function maskScreenshot(dataUrl, regions, viewport) {
    if (typeof dataUrl !== "string" || !/^data:image\/png;base64,/i.test(dataUrl) || dataUrl.length > 12_000_000) {
      throw new Error("invalid screenshot data URL");
    }
    const image = new Image();
    image.src = dataUrl;
    await image.decode();
    const rectangles = scaleRedactionRegions(regions, viewport, image.naturalWidth, image.naturalHeight);
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d", {alpha: false});
    if (!context) throw new Error("screenshot canvas unavailable");
    context.drawImage(image, 0, 0);
    context.fillStyle = "#000000";
    for (const rect of rectangles) context.fillRect(rect.x, rect.y, rect.width, rect.height);
    return {dataUrl: canvas.toDataURL("image/png"), maskedRegions: rectangles.length};
  }

  globalThis.scaleRedactionRegions = scaleRedactionRegions;
  globalThis.maskScreenshot = maskScreenshot;
  if (globalThis.chrome && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (!message || message.type !== "LOCAL_AI_MASK_SCREENSHOT") return undefined;
      maskScreenshot(message.dataUrl, message.regions, message.viewport)
        .then((result) => sendResponse({success: true, ...result}))
        .catch(() => sendResponse({success: false, error_code: "screenshot_redaction_failed"}));
      return true;
    });
  }
})();
