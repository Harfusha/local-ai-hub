# Local AI Hub current-tab bridge

The extension captures only after the user clicks its browser action. Chrome
passes that clicked tab to the service worker; the bridge never activates,
navigates, submits, logs in, or searches for another tab. The content script
only reads the active document, computed styles, accessibility attributes, and
resource timing metadata. It never reads cookies, form values, authorization
headers, or request/response bodies.

Configure the generated extension origin in `browser_bridge.allowed_origins`
when the Hub has an explicit origin allow-list. The capability is one-use,
short-lived, tenant-bound, origin-bound, and tab-bound.
