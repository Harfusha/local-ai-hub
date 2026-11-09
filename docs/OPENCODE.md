# OpenCode integration (in progress)

An offline Windows test runs the existing MCP adapter inside AppContainer and
passes a repository search through the authenticated named-pipe bridge to a
fake Hub using a test-only restricted credential. The exact brief status URL is
also permitted by the restricted profile and tested through the fake Hub. This
is not live Hub, installed-runtime, or GPU acceptance.
In a separate offline test, OpenCode 2.2.5 loaded the MCP configuration but
did not expose the server to the model; `mcp list` reported no configured
servers. A test-only plugin using `ctx.mcp.transform` also failed to expose the
server. The experimental sandbox config now uses a bounded stdio adapter plugin
instead. A real OpenCode process, fake model, staged Python MCP server and fake
Hub completed a repository search through the authenticated pipe. This uses a
test-only process-stop shim and does not establish production isolation.
The control protocol can explicitly accept whole-session cancellation after
authenticating a non-root job member and receiving a client acknowledgement.
It terminates the entire owned Job, not just that member's subtree. The client
returns code 3 for accepted cancellation; this is not a completion receipt.
Tests covered owned descendants and a foreign process. This mode is not wired
to OpenCode's `taskkill` calls or the production launcher.
In one fake-model test OpenCode called `taskkill /pid ... /T /F` on its own
server after the final model response; the observed ancestry was OpenCode
server, OpenCode CLI, then the Node bootstrap. Whole-job cancellation cannot
be substituted for that normal server cleanup without aborting the CLI.
An additional fake-model smoke now routes that observed server stop through
the authenticated LAC1 client and confirms the exact OpenCode process exited.
Its test-only shim does not implement `/T`: this proves neither descendant
termination nor a safe production replacement for OpenCode's `taskkill`.
An attempted real-model smoke against the running Hub was denied before
provider startup by an obsolete requirement for a configured 32-character Hub
API token. Provider and restricted-profile credentials now derive from the
session nonce; the launcher no longer needs a configured Hub API token. That
attempt started no provider and establishes no real-model or GPU result.
An isolated follow-up used a separate CPU-only Ollama instance with the
already installed `qwen2.5-coder:0.5b`, a disposable project and the test-only
single-process stop shim. Real OpenCode returned `OK` through the pipe;
its job cleanup and the Ollama job termination were confirmed. This bypassed
the live Hub provider and did not exercise MCP, coding, goals, or GPU use.
The smoke exited with a temporary-directory cleanup error because its Ollama
log was still open; the exact leftover is
`%LOCALAPPDATA%\Temp\opencode-cpu-smoke-yvw0qxem`. Recursive cleanup was
blocked by the host command policy; the temporary process job was already empty.
The sandbox launcher and full filesystem confinement remain incomplete.
Wheel data includes both plugin directories and the pipe/bootstrap helpers.
Future-profile staging checks those assets before provisioning; this checks
presence only and does not prove the installed launcher can use them.
`opencode_runtime_stage.stage_runtime` copies the existing interpreter, installed
MCP dependencies (including the configured JWT crypto extra), and Hub package
into a caller-owned fresh directory with size limits and per-file hash checks.
It is not yet connected to the production launcher. The AppContainer test has
completed with this runtime, but one combined test run timed out during an
OpenCode session; a later isolated run passed. Reliability remains unverified.
One earlier launch also failed at local transport startup. A controlled test
confirmed that a Windows-excluded TCP port yields `EACCES`; its relationship to
that earlier failure is not proven. Session port selection now asks the OS for
an available ephemeral port instead of sampling the range. The probe closes
before the isolated bind, so a later port collision remains possible and fails
the launch rather than implying that a session started.
`stage_session_bundle` additionally checks the pinned OpenCode executable,
verifies the installed Node.js and staged Python publisher signatures, and
copies the session plugins and bridge helpers. An isolated fake-model test
uses this bundle and the session-generated Python import paths without a test
override; interactive launch and filesystem confinement remain open.
`PrivateStage` creates a fresh staging directory, grants its AppContainer SID
access, and refuses automatic removal when cleanup is unconfirmed or a reparse
point appears. An isolated test denied writing a sibling file and preserved
its ACL. This is a staging check, not a race-free project confinement proof;
it does not change permissions on a user's project.
In a disposable external project, a test-only Windows DACL grant let the
isolated OpenCode process create a file and call MCP through the fake Hub;
the pre-existing project DACLs matched their originals after the test removed
the session SID. A separate test also created and reopened nested files. These
experiments do not provide a production project-ACL lease or prove safety for
concurrent ACL changes, reparse-point races, or arbitrary Git worktrees.
Windows tests found that `SetSecurityInfo` and `SetKernelObjectSecurity` can
change pre-existing inheritance metadata in this scenario. `SetFileSecurity`
preserved the tested fixture's DACL, but a hardlink could still be created
while the file was opened without write/delete sharing. Consequently, a
path-pinned ACL update alone is not sufficient to confine changes to one tree.

The Windows x64 CLI can be provisioned independently with:

```powershell
python tools/setup.py --install-opencode-cli-only
```

This installs the pinned OpenCode 2.2.5 executable into the current user's
`LOCALAPPDATA/Programs/OpenCode-LocalAIHub/2.2.5` directory. The release archive
and executable must match their pinned SHA-256 values. Existing files are never
replaced; an already installed matching binary is reused. `--opencode-dir` can
specify a different directory. A mismatched existing executable or download
failure stops the command with an error.

`python tools/setup.py --install-opencode-sandbox-only` provisions the pinned
Microsoft MXC 1.0.1 Windows x64 executor, verifying the npm package SHA-512 and
executor SHA-256. Existing matching files are reused; other files are not
overwritten. `--opencode-sandbox-dir` selects another destination. Provisioning
does not enable isolation or complete the OpenCode integration.

`python tools/setup.py --inspect-opencode-hardware` inspects detected dedicated
GPU capacity. `--opencode-profile auto|12gb|16gb` selects a capacity tier and
`--opencode-model NAME` adds an explicit candidate. This inspection does not
install or activate a model and never certifies VRAM admission or performance;
it reports unsupported capacity below the 12 GB tier. Context size, backend
compatibility, free memory and model fit require runtime measurements.

To stage components for a GPU that is not installed yet, run
`python tools/setup.py --stage-opencode-profile 16gb`. Add `--skip-model-pull`
to require the candidate model to already exist. This checks the pinned CLI,
the goal plugin and the local Ollama inventory, and downloads the candidate
only when permitted. It does not change the active hardware profile or select
a model. GPU admission, isolation and end-to-end acceptance remain unverified.

The normal Hub generator also writes `generated/opencode-mcp.json` using the
OpenCode V2 `mcp.servers` format. It is a generated manifest only: it is not
merged into OpenCode's configuration or a local-only security boundary. In an
isolated configuration check, OpenCode 2.2.5 accepted its server definition and
reported the local-ai MCP server connected and listed the Hub tools. A probe
invoked `local_ai_repo` `code_index` through OpenCode and obtained the requested
repository symbol. This was a direct probe, not a model-driven coding task.
The manifest defines `local-builder`, `local-planner`, `local-reviewer` and
`local-debugger` using V2 agent fields. The three subagents inherit the session
model and deny the OpenCode `edit` and `shell` permissions. OpenCode 2.2.5
loaded these definitions in an isolated server probe. These permissions are
not proof that every separately configured MCP tool is read-only, or that local
subagent inference is serialized; the manifest is not installed automatically.
The launcher passes a small allowlist of operating-system environment variables
to OpenCode, then adds its scoped Hub credentials and isolated configuration.
Other inherited variables, including arbitrary cloud credentials and custom
development variables, are omitted. The MCP client reads a temporary profile
containing the Hub port and boolean feature settings instead of the owner's
configuration, and cannot auto-start a replacement Hub. This does not restrict files readable by
the same user or network access by launched tools.
The launcher sets `OPENCODE_DISABLE_MODELS_FETCH=1` and
`OPENCODE_DISABLE_AUTOUPDATE=1`. A local endpoint probe with OpenCode 2.2.5
observed two model-catalog requests without the first setting and none with it.
This observation does not establish a general network isolation boundary.
An isolated feasibility probe on Windows build 26300.9818 used the signed
Microsoft MXC 1.0.1 `wxc-exec.exe` (SHA-256
`090f5d1f7bb93104ab08dcd4e8034ef954aeefcdaf6658dde5f7dff4cfc12f3a`).
With direct egress rules plus host-loopback enabled, both a requested localhost
port and an unrelated localhost port were reachable; that policy is unsuitable.
With MXC's loopback-proxy policy, an isolated Python descendant reached only the
configured local proxy port; an unrelated localhost port and `1.1.1.1:443`
were blocked. The package was verified against its npm SHA-512 and the executor's
Microsoft Authenticode signature. This is a connectivity probe, not an OpenCode
sandbox integration or proof against every route. Integration still needs the
restricted local broker wired into the launcher, constrained filesystem grants, process lifecycle and
end-to-end adversarial tests. See [MXC ProcessContainer networking](https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/networking.md).
An experimental fixed-target loopback router now forwards only the restricted
Hub routes and provider chat endpoint. It is not yet used by the launcher. In
another isolated MXC probe, a Python client reached two fake local services via
the router, while direct access to another local port and `1.1.1.1:443` failed;
an absolute-form external proxy request was rejected. This does not establish
OpenCode sandbox, endpoint identity, or production local-only acceptance.
The router permits completion checks but rejects verification receipt mutations
and `project_command`: the current Hub broker executes that command on the host,
outside the sandbox. A sandboxed verification producer and authentic receipts
are still required before `goal_verify` can work through this isolation path.
The experimental MXC policy builder now emits a bounded ProcessContainer policy,
requires the pinned executor, limits access to an explicit loopback proxy and
chosen directories, and deletes its temporary policy file after a normal exit
or handled error. On Windows, the policy uses a delete-on-close file held open
through execution; a subprocess termination test confirmed its removal. A real
MXC socket probe passed using that builder. It is not wired to the launcher;
path grants, secrets, receipt production and whole-tree cleanup require further
work before production use.
An isolated OpenCode 2.2.5 `run --standalone` probe with a fake backend and the
strict proxy policy failed with `Transport: EACCES`: its local client could not
connect to its private server. A separate sandboxed `opencode serve` probe
announced a listener, but the host could not connect to it under that policy.
This prevents claiming a working isolated OpenCode session. MXC's documented
[intra-container loopback issue](https://github.com/microsoft/mxc/issues/1261)
is consistent with the observed failure; its relationship to this exact
OpenCode failure has not been independently proven. Do not loosen host loopback
to all local services to bypass this gate.
In a separate temporary ProcessContainer experiment, a Node process exchanged
five test bytes with a host named pipe while host localhost and internet TCP
were blocked. The pipe granted access to all AppContainers and was only a
feasibility probe with UI access enabled: production IPC would need per-container identity, bounded
framing, authentication and lifecycle controls. A loopback listener and client
in that same container still failed with `EACCES`, including with an explicit
127.0.0.1 egress rule and host loopback denied. Thus this IPC probe does not
resolve OpenCode's internal client/server transport.
On Windows build 26300.9818, a separate raw AppContainer probe with no network
capabilities allowed a Node client to connect to its own local listener while
blocking a host listener and `1.1.1.1:443`. A host named pipe restricted to the
test container's SID received five test bytes; another container SID received
`EPERM`. These probes granted read/execute ACLs only on temporary test files
and removed their temporary AppContainer profiles. They do not establish safe
filesystem access to a real checkout or authenticate ordinary same-user pipe
clients. A further `Experimental_CreateProcessInSandbox` probe with explicit
temporary-directory grants blocked the internal connection, so that API is
not yet a drop-in replacement for the raw AppContainer proof.
An experimental pipe-identity helper checks the token impersonated from an
already-read pipe message and compares its AppContainer SID before dispatch.
In isolated probes it matched the intended AppContainer and rejected an
ordinary process under the same Windows account; the latter could open the
pipe because its owner had access. The experimental relay checks identity on
each message; same-user token theft and complete IPC lifecycle security remain
outside the evidence gathered here.
An experimental relay core checks identity on every nonempty read, requires a
32-byte per-session handshake before connecting, and bounds data and runtime.
Focused tests connected it to the fixed-target HTTP router and checked that
unauthorized input is not forwarded. An experimental single-instance Windows
pipe listener now uses a per-container SID ACL and authenticates each read.
Responses are length-framed and require an authenticated final acknowledgement
before disconnect. A raw AppContainer client reached a fake local HTTP service
through this path, received its full response, and could not connect directly
to a host listener or internet endpoint. A bounded client queue and host relay
service handle sequentially forwarded requests while keeping the pipe name
exclusively owned. Three concurrent requests from a raw AppContainer reached a
fake service, and the relay shut down. These components are not wired into the
launcher; production lifecycle and security acceptance remain open.
In a separate raw AppContainer, OpenCode 2.2.5 reached a fake model hosted by a
same-container Node process, printed the response, and emitted a `step_finish`
event with reason `stop`. The enclosing process did not exit within 20 seconds
and was terminated by the probe. Restricting `HOME`, `APPDATA` and related
paths to the test directory removed watcher permission errors but did not fix
termination. This is a single fake-model turn, not completed session lifecycle,
Hub/MCP integration, a GPU run, or production sandbox acceptance.
A matching unsandboxed control exited successfully; redirecting the sandbox's
home paths and stdin to the test directory and `NUL` did not resolve its hang.
Another fake-model turn requested the real OpenCode `shell` tool. In the raw
AppContainer, PowerShell executed `echo SANDBOX_TOOL_OK`, and the tool returned
exit code zero before the model emitted a final step. The outer session still
did not exit within 20 seconds. Separately, a Node parent blocked inside
`spawn()` when starting OpenCode with piped stdio in this AppContainer; an
unsandboxed control started and stopped the same server normally. This does
not prove that Node's stall causes OpenCode's termination problem.
Another raw AppContainer probe routed OpenCode's fake-model requests through
the authenticated pipe and fixed-target router. OpenCode produced the expected
text and `step_finish`, but did not exit: its child tree contained `taskkill`
commands waiting during cleanup. A test-only temporary `taskkill.cmd` used
PowerShell to stop the requested server process; the same probe then exited
with code 0, and the host terminated its kill-on-close job afterward. This is
evidence for a cleanup bottleneck, not a production-safe replacement,
tree-termination proof, real-model run, filesystem confinement proof, or
Hub/MCP integration.
The experimental `SandboxSession` composes a temporary AppContainer profile,
fixed-target router, separately authenticated relay and process-control pipes,
and an owned Windows job. A randomized container-local port and per-session
secrets are passed through the child environment; the bridge secret is removed
before OpenCode and its shell tool start. The integration test runs the pinned
OpenCode executable with a fake model, invokes its shell tool and checks the
tool result, using a test-only `taskkill` workaround. Separate Windows tests
exercise host file and loopback denial, excluded handle inheritance, service
failure and interruption cleanup. The process-control pipe stops only one
identified job member; it does not implement `taskkill /T`. The composed session
does not grant access to an existing project, provide a complete interactive
launcher, prove local-model or GPU behavior, or establish production isolation.
The Windows test also creates a junction from the sandbox directory to an
independent temporary directory. Reads fail when that target denies the
container SID, but succeed after the same SID receives read permission on the
target. AppContainer ACL checks therefore do not alone confine access to a
particular project path. A one-time scan for existing junctions would not cover
junctions created during a session; the eventual workspace mechanism must
address accessible external targets and concurrent path changes explicitly.
An additional temporary probe used a zero-capability less-privileged
AppContainer with the Windows all-application-packages opt-out. On this
machine, Node failed during `WSAStartup` with error 10107 before opening its
container-local bridge; the profile and relay were then closed. This rules out
claiming that configuration as a working replacement on this machine, not LPAC
on every Windows installation. No broader network capability or system ACL
change was applied to force the probe to work.
The generator can also build a per-launch V2 configuration with the Hub
provider, `local-builder`, MCP and the `/goal` plugin. Its provider policy
denies other model providers and it references credentials through environment
variables. An isolated OpenCode 2.2.5 run used this config with a fake backend;
`/goal` appeared after asynchronous plugin initialization. Setup does not yet
install or launch this configuration. Provider policy alone does not prohibit
network access through arbitrary tools or prove complete local-only isolation.
The local profile rejects model names ending in `:cloud` or `-cloud` before
download or GPU reservation. The provider accepts Ollama 0.34.0 only and adds
`:local` to every upstream model request; that release's source rejects remote
aliases under this suffix. A fake backend verifies forwarding. An isolated real
Ollama 0.34.0 rejected a renamed remote alias with `:local` on the same checked
connection, while an unsuffixed control reached a loopback-only fake remote. No GPU inference or external cloud
was used. On Windows the inference connection must match the PID and creation
identity in the Hub-supervised Ollama owner record; an absent, invalid, or
unmanaged owner fails closed before HTTP traffic. This is ownership consistency,
not cryptographic authentication: same-user modification of the owner record
and cloud access through other tools remain outside this check.

`python tools/opencode_local.py --model MODEL --project PATH` is an experimental
Windows launcher. The same launcher is available through
`python tools/hubctl.py opencode --opencode-model MODEL --root PATH`; `--config`
can select a Hub configuration. It requires a running updated Hub, the pinned
verified OpenCode executable, and an explicit model. It starts a dedicated provider session and requests shutdown of
that same session on exit. Before starting, it checks the configured loopback
Ollama inventory and refuses a missing model without downloading it. This check
uses the launcher's configuration; it does not prove that a running Hub has
reloaded that same configuration or that the model fits in GPU memory. At
inference admission, the provider checks its own Ollama inventory and refuses
the request if a different model is already resident. It repeats the
version and resident-model checks on the same TCP connection used for each
inference request; a closed connection is not replaced. These checks are snapshots:
unrelated Ollama clients are not fenced and can race the check. Its managed OpenCode data lives under the configured
Hub state directory; existing user configuration is not overwritten. It disables
project OpenCode configuration to prevent endpoint or plugin overrides and tells
the agent to read project `AGENTS.md` instructions. Normal setup prepares its
components only when requested; it does not run the launcher. The launcher does
not sandbox shell network access or establish VRAM
admission. An isolated end-to-end test used OpenCode with a fake backend only.
Focused Windows verification on 2026-11-08 ran
`python -m pytest -q tests/test_opencode_inference_session.py tests/test_opencode_launcher_integration.py tests/test_opencode_container_integration.py tests/test_opencode_mcp_container_integration.py tests/test_opencode_project_verification.py`;
20 tests passed. This covers the pinned CLI, provider cleanup, and authenticated
sandbox MCP bridge with a fake backend. It does not verify model-driven edits or
complete local-only isolation.
`python tools/setup.py --prepare-opencode-model MODEL` checks the running
loopback Ollama inventory, downloads that one model only when absent, and checks
the inventory again. `--skip-model-pull` makes this a presence check;
`--opencode-ollama-url` selects another explicit loopback HTTP origin. A timeout
means the download outcome is unknown and requires inspection before retrying.
Installation does not establish model fit, inference, or GPU admission.
Normal Windows setup also accepts `--with-opencode`, or `-WithOpenCode` through
`install.ps1`, with optional `--opencode-profile`, `--opencode-model`, and
`--opencode-dir` (PowerShell: `-OpenCodeProfile`, `-OpenCodeModel`, and
`-OpenCodeDir`). It checks 12 GB capacity before normal installation, installs
the pinned executable, and prepares one provisional model candidate without
pulling unrelated Hub models. `--skip-model-pull` / `-SkipModelPull` requires
the candidate to be present. The command returns an incomplete status until
runtime, local-only, goal and GPU acceptance are established; it does not
select a benchmark-verified default model. Normal installation may restart the
managed Hub and Ollama, so do not run it while they are in use.
`hubctl doctor` reports component hints for the default executable location,
detected GPU profile, goal plugin and known candidate inventory. This is not a
GPU or local-only acceptance test; a custom executable location is not checked.
The `opencode-local` MCP process hides `local_ai_task` and `local_ai_work` and
rejects direct calls to those names; isolated stdio tests verify that other
client profiles retain them. The HTTP handler also rejects unclassified routes
and actions for this profile. Synchronous Ollama and llama.cpp generation,
scheduler submissions, enqueue, prewarm and background session startup honor a
request-scoped deny. The background worker also checks before submitting work
to its threads. Text search, caller lookup, task creation and memory record/find
have focused HTTP tests. RAG search uses the existing lexical index without
embedding or reranking for this profile; it does not perform semantic retrieval.
The allowlist is incomplete and other RAG operations remain rejected.
Stale CodeIndex results do not enqueue preprocessing for `opencode-local`;
their cache entries are separated so unrestricted clients can still notify the
preprocessor. Repository reads in that profile also do not change the priority
of registered preprocessing projects. Existing independent workers are unaffected.

The experimental launcher gives its child a domain-separated restricted Hub
credential instead of forwarding the configured master token. The server forces
that credential into `opencode-local` regardless of the agent header and denies
provider lifecycle calls. The credential is bound to one running provider nonce
and is rejected after stop or replacement. Tests cover HTTP denial, expiration
and isolated launch. Manual
clients using the master token may still supply their own agent label. This is
not a complete local-only security boundary: processes running as the same user
may read the Hub configuration, request context does not automatically cross
arbitrary threads, and independently scheduled background workers are not covered.
Do not enable this experimental profile as a guarantee of GPU exclusivity or
cloud isolation. Existing running Hub processes must be restarted separately
before they use these server changes.

The experimental OpenCode bridge uses a persistent GPU reservation shared by
cooperating schedulers with the same configured state directory. Their model
preparation, dispatch, idle unload, background GPU sessions and direct Ollama
embedding requests use the same admission file when a state directory is
configured. CUDA SentenceTransformers embedding loads and synchronous encoding
also hold it; a CUDA model may remain resident after the file is released. An
incomplete embedding response retains the fence. Focused tests
cover competing scheduler instances, a separate
process, simulated process exit, failed background termination and unknown job
outcomes. Unknown outcomes retain the fence; verified recovery after a crash is
not yet implemented. Do not manually clear the state while inference could
still run. This does not fence independent Ollama clients or arbitrary backend
calls, prove physical VRAM reclamation, or establish GPU exclusivity.
An experimental session wrapper holds that reservation across requests, binds
one model, and relays OpenAI-compatible SSE only after serial admission. Its
bounded parser requires a complete `[DONE]` event and upstream EOF; incomplete
or disconnected streams retain the fence. Tests use a loopback fake backend.
An experimental loopback-only, bearer-authenticated HTTP bridge exposes the
streaming chat endpoint to a single model and forwards only to a loopback
backend. Fake-server tests cover authentication, model selection, concurrency,
truncation and backend failure. An isolated OpenCode 2.2.5 process successfully
used the bridge with a fake model backend, and the reservation was then released.
The Hub owns its lifecycle through experimental start, status and stop
endpoints. Configured API-token protection remains active; loopback operation
does not require a configured Hub API token. Only a nonce is returned, and
provider/profile credentials derive from that session nonce. GPU admission is
lazy and occurs when inference begins. Stop is asynchronous and retains the
fence on uncertainty.
Setup does not start or configure it; no actual Ollama or GPU test has run.
Gaming mode blocks new starts. A request to enter gaming or maintenance starts
provider shutdown and rejects the mode change until shutdown is confirmed.
Recovery and GPU exclusivity remain unverified.

The current HTTP handler skips adaptive context warmup after creating a task
with the `opencode-local` agent identity; other identities retain that warmup.
This closes one possible implicit model path, not all internal inference paths
or independent background workers. Existing running Hub processes must be
restarted separately before they use source changes.

This command installs only the executable. It does not modify PATH or configure
Ollama, OpenCode providers, MCP, local-only enforcement, GPU scheduling, goals,
or cloud delegation. The full integration is not yet implemented or verified;
do not treat this command as a completed local coding environment.

The Agent OS HTTP task-completion request may include `expected_criteria`: a
nonempty ordered list of distinct, canonical criterion strings. When supplied,
it must exactly match the persisted task contract before the existing receipt,
ownership, revision and mutation checks can complete the task. Criteria-bound
completion cannot adopt a task; its existing owner must perform it. This provides a
building block for a goal controller.
An optional `expected_binding` object containing exactly `goal` and `session_id`
requires `expected_criteria` and binds completion to those stored fields. The
completion content snapshot fences task changes through the final transition;
this does not replace persisted receipts or project-root and owner checks.

An experimental OpenCode V2 server plugin is in `tools/opencode_goal`. Its
controller and HTTP transport have focused tests. Setup copies the plugin with
the managed tools payload, but does not activate the OpenCode integration. A
private OpenCode 2.2.5 server loaded its source and
registered `/goal`. A separate isolated probe created a real session and persisted
and recovered a paused controller state using OpenCode's plugin storage; its
prompt was stubbed, so a complete real-agent workflow remains unverified.
Another isolated run invoked the goal command through OpenCode's session command
API, created a real Agent OS task and sent its continuation to a fake model.
The fake model claimed completion while an actual pytest test in that project
failed; no verification receipt was recorded and the task remained incomplete.
The persisted plugin state also was not `DONE`; in the observed run the private
server exited with zero settled goal turns, so this does not prove that the
goal controller processed the failure. A separate isolated server kept alive
until a goal turn settled queried Agent OS verification, stored `FAILED` after
the configured two-turn limit, and left its Agent OS task incomplete. Both goal
turns were observed. OpenCode also made an additional request to name the
session through the same fake provider. Both runs used a fake model and no
failed receipt.
The broker records verification
receipts only for successful commands, so no failed receipt is claimed here.
In a positive isolated test, the broker ran a passing pytest command for the
goal's exact task and owner, persisted its authentic receipt, and OpenCode
stored `DONE` after Agent OS completed the task. The model was simulated.
An isolated fake-model test also paused a goal, stopped and restarted the
OpenCode server, and resumed the same persisted task to its turn limit. This
does not establish recovery from an unknown request outcome or concurrent
process safety.
`opencode run '/goal ...'` sends ordinary prompt text in the
tested version; use the registered command in the TUI or the session command
API instead. This does not establish actual local-model or GPU behavior.
An existing task must match the goal, ordered criteria, owner, project root and
session before prompting; its binding is checked again before completion.
An unverified binding blocks continuation and can be rechecked on resume.
With explicit acceptance criteria, the controller can create a task or bind an
existing task ID. A real HTTP test confirmed creation with the expected owner,
session and criteria. After unconfirmed task creation, `/goal resume` checks
the existing task's exact binding before continuing; it does not repeat the
creation. Missing or mismatched task evidence leaves the goal blocked. An
isolated real Hub HTTP test simulated losing the creation response after a
confirmed commit and recovered from a separate controller process. The
controller also blocks known active goals when its event stream closes and
refuses new or resumed goals in that plugin instance. The interrupted outcome
is unknown and needs operator inspection; automatic recovery is not implemented.
Before submitting a continuation, the controller records an unknown prompt
admission, explicit message ID and delivery mode in its durable storage, and
clears them only after the returned ID, session, type and text all match. On
`/goal resume`, a blocked admission can be reconciled to `PAUSED` only when the
task binding matches, the current context contains the exact prompt followed by
exactly one successful idle with no intervening user prompt, and the session reports a
successful idle. A second `/goal resume` is needed to continue. Missing,
compacted or ambiguous history stays blocked; recovery does not send a prompt
or establish goal completion. Focused tests cover pause races and a real
OpenCode 2.2.5 history with a fake model; task binding in that history test was
stubbed. Cross-process controller exclusion and an actual model remain unverified.
An isolated OpenCode server with a fake provider also accepted a repeated
prompt ID without a second main model request. A separate file-backed process
exit test remains blocked when matching recovery history is unavailable.
The controller also persists an unknown task-completion intent before sending
the Agent OS mutation. It clears the intent only after a matching completed
task is confirmed. On resume, a recorded completion event can be reconciled
without another mutation when the exact completed task binding and fresh
verification both match. Stale, unavailable or mismatched evidence remains
blocked. A simulated process-exit test uses file-backed test storage; a separate
isolated integration test reconciled a completed task against a real Hub and
authentic test receipt. Cross-process goal ownership remains unimplemented.
The experimental HTTP verification action `project_command` accepts a project
root, task ID, session ID and configured command alias. It requires an active
restricted provider credential and a 32-hex `X-LocalAI-Request-ID`; the durable
journal rejects or replays duplicates rather than running them twice. The task
binding and project rules must require the alias, and the broker must classify
its exact configured command as allowed replay-safe validation. The broker runs
it without cache and owns any receipt. A real Hub and isolated pytest project
test covered successful and failing commands, replay, conflicting IDs, missing
journal and wrong session. The plugin exposes `goal_verify` as a direct model
tool with a single configured alias; it checks shell permission and the current
goal binding and persists the request ID before dispatch. Unknown or cancelled
operations remain pending and are not retried automatically. An isolated real
OpenCode 2.2.5 run with a fake model invoked this tool, ran a real project test,
and completed the task using the Hub's persisted receipt. This does not prove
cross-process exclusion or local-model behavior.
An isolated OpenCode 2.2.5 run with a fake model confirmed that
`session.wait` returned after that test session became idle and `session.get`
reported success. This alone does not prove exclusive ownership or reconcile an
uncertain task mutation; prompt recovery additionally requires the evidence
described above.
This safety behavior has focused tests, not a real-agent recovery test. The
plugin does not infer stagnation from `session.context()`, which need not contain
the current transcript. It can flag three unchanged ordered OpenCode step
snapshots paired with an unchanged Agent OS checkpoint as possible stagnation.
Missing or unordered evidence breaks the streak; snapshots do not capture every
kind of progress. The continuation limit also applies. An isolated OpenCode
2.2.5 run with a fake model produced ordered snapshot events that were replayed
through the controller. A real-model workflow has not yet verified this
detection. Controllers sharing one loaded plugin module serialize goal operations
for the same session. Separate module instances or processes are not fenced.
The controller is not a completed integration: cross-process concurrency,
model-driven goal execution, local-only enforcement and GPU coordination
remain unverified or unfinished.
