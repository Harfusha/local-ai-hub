# Local AI Hub current-tab bridge

The extension captures only after the user clicks its browser action. Chrome
passes that clicked tab to the service worker; the bridge never activates,
navigates, submits, logs in, or searches for another tab. The content script
only reads the active document, computed styles, accessibility attributes, and
resource timing metadata. It never reads cookies, form values, authorization
headers, or request/response bodies.

Configure the exact generated extension origin in `browser_bridge.allowed_origins`
or authenticate the bridge request with the Hub API token. The default allow-list
is empty and never grants a wildcard extension origin. The capability is one-use,
short-lived, tenant-bound, origin-bound, and bound to the explicit tab/window.
Capture aborts if the active tab changes before or after the screenshot, and
returns explicit timeout, permission, closed-tab, or mismatch errors. Password
input values/defaults are cleared only on a cloned DOM snapshot; the page itself
is not mutated. Bundles include bounded capture-time and target-origin provenance.
