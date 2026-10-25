# Browser and desktop automation

The Hub reuses the official Playwright MCP extension for your existing Chrome,
Playwright MCP isolated headless Chrome sessions, and Microsoft winapp for Windows
UI Automation. It does not introduce another public MCP tool or replace the
existing current-tab capture extension.

## Enable explicitly

Automation ships disabled, with no allowed targets, files or applications. Update
the Hub's operator configuration; never grant an agent permission to enlarge it.
Explicit port zero is invalid. Downloads retain the original browser request;
the broker checks declared lengths and reads the intercepted response in bounded
chunks before Chrome writes the file. Oversized responses stop with
`download_size_limit`, including responses without Content-Length. Non-HTTP(S)
downloads reject; agents cannot use a download to enlarge target permissions.
Install the optional backend in a directory you control, with a pinned version:

```powershell
# Use node plus npm-cli.js directly; .cmd/.bat wrappers are not supported.
& 'C:/Program Files/nodejs/node.exe' 'C:/Program Files/nodejs/node_modules/npm/bin/npm-cli.js' install --prefix 'C:/Tools/hub-browser' --ignore-scripts --no-audit --no-fund '@playwright/mcp@0.0.83'
```

The executable and CLI paths below must exist. Isolated mode uses installed
Chrome; the Hub does not pull packages or browser binaries. Version 0.0.83's
`browser_run_code_unsafe` is used internally for a fixed, broker-authored adapter;
agents cannot provide JavaScript, CDP commands, shell commands or backend tools.

```toml
[automation]
enabled = true
allowed_targets = ["http://127.0.0.1:8765/", "http://192.168.1.20:8080/app"]
playwright_command = ["C:/Program Files/nodejs/node.exe", "C:/Tools/hub-browser/node_modules/@playwright/mcp/cli.js"]
profile_directory = "Default"
max_sessions = 8
session_ttl_seconds = 900
timeout_seconds = 20
allowed_file_roots = []
winapp_executable = ""
allowed_applications = {}
allow_physical_input = false
sandbox_enabled = false
allowed_sandbox_applications = {}
```

Targets bind scheme, hostname/IP, effective port and optional path boundary.
`/app` permits `/app` and `/app/...`, not `/application`. Empty lists deny all;
wildcards, credentials and ambiguous paths reject. A hostname grants that hostname,
not a pinned IP identity; use literal IP rules when that is the intended identity.
Configured extension-origin permissions for the old capture bridge are separate.

Install Microsoft's [Playwright extension](https://playwright.dev/mcp/configuration/browser-extension)
for personal Chrome. The extension owns its browser connection/selection prompt.
The selected page must exactly match the requested initial URL. The Hub does not
copy your profile/cookies, launch a second process on that profile or open a public
debugging port. One extension session leases that profile; isolated sessions are
independent and may run concurrently within `max_sessions`.

## Agent contract

Create an Agent OS task for an explicit authorized repository root first. Use the
existing tool `local_ai_task(action="automation", root=..., task_id=...,
automation={...})`. HTTP uses POST `/api/task/automation` with the same three
fields and ordinary Hub API authorization. Read-only credentials cannot operate
the UI. The server checks the actual task's repository and active status.

Open:

```json
{"op":"open","mode":"isolated","url":"http://127.0.0.1:8765/"}
```

For personal Chrome use `mode="extension"`. Keep the returned `session_id` and
`session_key` private to this task. Act:

```json
{"op":"act","session_id":"<returned>","session_key":"<returned>","request_id":"click-001","command":"click","selector":"#submit"}
```

Commands: `snapshot`, `navigate` (`url`), `click`, `fill` (`text`), `press` (`key`),
`select` (`option`), `check` (`checked`), `hover`, `drag` (`destination` selector),
`scroll` (`x`,`y`), `screenshot`, `dialog` (`accept`, optional `text`), `upload`
(`files`), `download` (clicks `selector`), `tabs`, `new_tab` (`url`), `switch_tab`
(`destination` is returned tab_id), `close_tab`. Element commands use a CSS
`selector` scoped to the owned page; arbitrary frame traversal is not exposed.
`dialog` configures the next dialog; otherwise dialogs dismiss by default.
`close_tab` closes owned auxiliary tabs; close the session to release its main tab.

Snapshot output is a bounded accessibility tree. Screenshots mask every iframe.
Navigation guards apply before and after operations and intercept document
requests through CDP, including HTTP redirects. An unexpected target or uncertain
execution fences the session. Cached request IDs never execute the mutation again;
reusing an ID with different arguments rejects. The journal is bounded to 256
operations per session, without eviction that could accidentally permit replay.

Use `op="status"` or `op="close"` with the session identity/key. Closing during an
operation requests cancellation, reports uncertainty and releases resources after
cleanup; it does not undo an already submitted action. Expiry also releases idle
sessions without requiring another agent request. Shutdown reports pending work
until cleanup has completed. Backend failures never trigger a broader fallback.

Uploads require explicit configured file roots, canonical existing files and size
limits. Downloads and screenshots land in owned state directories, become bounded
artifacts, then leave temporary storage. Binary content is retrieved through the
existing artifact API, not inlined into model responses. An unrequested download
is outside the supported workflow; use the explicit download command.

## Desktop and Windows Sandbox

Install Microsoft [winapp](https://github.com/microsoft/winappCli/blob/main/docs/ui-automation.md)
separately. Configure its absolute `.exe` path and exact application executable
paths, for example `allowed_applications = { editor = "C:/Windows/System32/notepad.exe" }`.
Open with `{"op":"open","mode":"desktop","application":"editor","window_id":12345}`.
Get the actual HWND through the operator's winapp window inventory; the Hub never
guesses a window or launches an arbitrary executable supplied by an agent.

Desktop commands: `inspect`, `invoke`, `set_value` (`text`), `get_value`, `screenshot`.
`click`, `hover`, `focus`, `press` additionally require `allow_physical_input=true`.
Press supports ordinary navigation/edit keys, not system shortcuts. Selectors
come from winapp inspection. Window executable, PID and process lifetime are
checked before and after each operation. Known browsers and shells reject as
desktop targets; use browser sessions for Chrome. User-owned applications are
never killed when a session closes. The broker serializes desktop operations.

For an operator-prepared Windows Sandbox, set `sandbox_enabled=true`, configure
`allowed_sandbox_applications` with absolute **guest** executable paths, and open
`mode="desktop_sandbox"` with a guest HWND. Every UI command includes
`--on sandbox`. A fixed read-only helper executed through `winapp target exec
sandbox` resolves the guest window's executable/PID/start time; host identity is
never substituted. If guest identity or transport is unavailable, the operation
fails closed. The Hub does not enable Windows features, change firewall rules,
provision or reset a VM, install guest agents, or silently switch to the host.

Windows Sandbox is one shared guest, not a separate VM per agent. Separate VMs
are required for mutually untrusted desktop workflows. A browser context likewise
isolates browser state, not the OS or network. Web subresources retain normal
network access: `network_egress_isolated=false`. Strong egress isolation requires
external VM/network policy; it is never inferred from an origin filter.

## Validation

Focused tests:
`python -m pytest -q tests/test_automation_broker.py tests/test_automation_adapters.py tests/test_automation_integration.py`.
The opt-in actual headless Chrome test uses `LOCAL_AI_AUTOMATION_MCP_CLI` (absolute
installed CLI path) and optional `LOCAL_AI_AUTOMATION_NODE`. Run
`python -m pytest -q tests/test_automation_runtime.py`. It creates only owned
headless sessions and local fixture servers, never personal-profile connections.
Extension, native Windows UI and prepared Sandbox acceptance require actual
operator-owned sessions; fake adapters do not establish those results.
