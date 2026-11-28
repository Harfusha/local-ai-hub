# OpenCode integration (in progress)

## Current host snapshot (2026-11-25)

Read-only checks found OpenCode `v2.2.5`; `opencode mcp list` reports
`browser-mcp` connected and the configured `scan2cad` server failed because its
configured root is a stale pytest temporary directory. The user's
`%USERPROFILE%/.config/opencode/opencode.json` has the Hub plugin pointing at
`%USERPROFILE%/.local-ai-hub`, but no native `local-ai-hub` MCP server. This
checkout has not been installed into that profile. Hub and Ollama are online;
Hub reports no active model, nominal VRAM pressure and a free GPU reservation.
`nvidia-smi` reported 11,296 MiB free. No Gemma inference or live OpenCode-to-
Hub tool call was started in this snapshot.

The source gateway routes OpenCode inference through the Hub scheduler and its
shared GPU fence. Do not add a second external reservation around those Hub
requests: it would block the Hub scheduler that must serve them. The remaining
GPU proof is a live OpenCode request through the gateway while Hub admission is
observed, followed by safe reservation release.

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

The normal Hub generator writes `generated/opencode-mcp.json` using the
OpenCode V2 `mcp.servers` format. Normal setup also merges a Hub-owned native
stdio server into the OpenCode `mcp.servers.local-ai-hub` key and preserves
other servers. The extension plugin leaves MCP transport to OpenCode's native
client in this mode, while retaining its context, post-edit and permission
hooks. It uses Code Mode so the full Hub catalog is not injected into every
prompt. The older isolated plugin-adapter run failed during MCP initialization;
direct JSON-RPC against that server returned its complete catalog (about
498 KB). OpenCode 2.2.5's native client then timed out on that catalog, so the
OpenCode profile now advertises compact action schemas while keeping Hub-side
argument validation authoritative. The profile catalog is about 50 KB. A
native-server run connected and OpenCode logged all seven Hub tools. The real
Qwen 3.5 9B model run did not invoke the permitted status action: it requested
an unavailable `goal_verify` tool and ended with an HTTP 400 malformed-object
error. This proves the native MCP handshake, not a successful model tool call.
The source gateway now normalizes OpenAI-compatible assistant tool-call
`arguments` strings into the object shape required by Ollama's native chat API;
`python -m pytest tests/test_opencode_gateway.py -q` passes 9 tests. This fix is
not installed in the active Hub: process 2444 runs from
`%USERPROFILE%\.local-ai-hub`, and its `/api/chat/completions` route returned
404 during a read-only probe. No real inference was started. A temporary
`OPENCODE_CONFIG` file appeared in `opencode debug config`, but OpenCode 2.2.5
`mcp list --standalone` still reported `No MCP servers configured`; its config
source and MCP runtime behavior were initially unresolved. On 2026-11-25, the
same result reproduced after OpenCode's own `mcp add --global` generated the
canonical `mcp.servers` JSON entry in an isolated profile; moving the CLI
working directory into that profile did not change the immediate result.
`debug config` listed the isolated file and server definition. A persistent
OpenCode 2.2.5 server then connected once its MCP process used the installed Hub
`.venv` and the source checkout's `PYTHONPATH`: server logs reported
`mcp connected` with seven tools, `GET /api/mcp` reported `connected`, and
`opencode mcp list --server <that-loopback-server>` reported connected. The
standalone list command returned before this startup completed. A deliberately
misconfigured system-Python probe also showed `Missing MCP dependency`; the SDK
was available in the user-site and Hub `.venv`, but not in that child's
effective environment. The user's global profile and running Hub were left
untouched.
The fresh 2026-11-25 setup check found a V2 schema mismatch: generated
`mcp.servers.local-ai-hub.timeout` was a scalar, while OpenCode expects a map
of millisecond fields. Setup now emits `{"startup":60000,"catalog":60000}`;
the regression test failed against the old output and passed after the fix. In
the isolated OpenCode 2.2.5 runtime API probe, a raw MCP server body returned
`Missing key config`; wrapping the definition in `{"config":...}` connected
it. Both `GET /api/mcp` and `opencode mcp list --server` then reported
`connected`. The isolated MCP server was disconnected through the runtime API,
its OpenCode process was stopped, and port 43873 was confirmed closed. This
probe did not start model inference; the live Hub route and managed launcher
remain unverified.
Running the same worktree MCP module directly over stdio returned a valid
`initialize` response and seven `tools/list` names. That proves the source
server transport. The isolated persistent OpenCode server now also visibly
reports those seven tools connected; the existing user-managed service (PID
10428, port 28894) still shows only its pre-existing `browser-mcp` because it
was not stopped or reconfigured.
An earlier 2026-11-25 readiness read reported Hub/Ollama online, no active
model and a free external GPU reservation. The installed
`gemma4:12b-128k` model declares `num_ctx=131072`; user-level Ollama settings
show `OLLAMA_KV_CACHE_TYPE=q4_0` and Flash Attention enabled. Those settings
and model metadata do not prove a 128K inference or Q4 cache residency. The
active Hub model config currently selects `qwen3.5:9b-nvfp4` for reasoning, so
Gemma is not yet an active Hub route.
An attempted Hub `hardware_benchmark` for `gemma4:12b-128k` at 32768 context
returned a successful but truncated tool envelope, with no usable timing or
generated output. The follow-up readiness view showed `qwen2.5-coder:3b`
active, so this attempt is not counted as a Gemma run. The exposed benchmark
schema caps context at 32768 and cannot verify the requested 128K admission.
The latest 2026-11-25 runtime snapshot reports Hub inference active on
`qwen2.5-coder:7b-instruct-q4_K_M`, with an internal GPU reservation. Ollama
reports the model at 8192 context; `nvidia-smi` reports 16,303 MiB total and
6,784 MiB free. This is a live snapshot, not proof of the Gemma route. Do not
start a second model until the reservation clears and fresh admission validates
the Gemma context and cache settings.
An earlier isolated configuration check reported the server connected and a direct
`local_ai_repo` `code_index` probe returned the requested repository symbol;
that was not a model-driven coding task.
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
Earlier, on Windows build 26300.9818, a separate raw AppContainer probe with no network
capabilities allowed a Node client to connect to its own local listener while
blocking a host listener and `1.1.1.1:443`. A host named pipe restricted to the
test container's SID received five test bytes; another container SID received
`EPERM`. These probes granted read/execute ACLs only on temporary test files
and removed their temporary AppContainer profiles. They did not establish
filesystem confinement to a real checkout or authenticate ordinary same-user
pipe clients. A further `Experimental_CreateProcessInSandbox` probe with explicit
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
In this checkout, `src/local_ai_hub/opencode_launcher.py` is absent even though
older launcher notes below describe a prior candidate. `tools/opencode_local.py`
therefore fails closed with exit code 2 and names the missing production
sandbox, GPU admission and process cleanup gates; it does not launch OpenCode.
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
the managed tools payload. The managed plugin route now registers both the Hub
MCP plugin and this goal plugin, passing the configured Hub port only when the
Hub bind is exactly `127.0.0.1`; it preserves unrelated plugins and is
idempotent. Focused setup tests cover that merge and reject a non-loopback bind.
This source change has not yet been applied to the live OpenCode profile. A
private OpenCode 2.2.5 server loaded its source and
registered `/goal`. A separate isolated probe created a real session and persisted
and recovered a paused controller state using OpenCode's plugin storage; its
prompt was stubbed, so a complete real-agent workflow remains unverified.
On 2026-11-25, the current setup helper generated an isolated profile from a
preserved unrelated plugin entry. OpenCode 2.2.5 reported both
`local-ai-hub.mcp` and `local-ai-hub.goal` active and exposed the `goal` command;
the session command API executed `goal status` and returned the expected
`NO_GOAL`. This verifies plugin installation and command dispatch only. It did
not invoke a model, create an Agent OS task, prove model-visible Hub tools, or
modify the live user profile.
On 2026-11-25, this checkout added a strict OpenAI chat-completions gateway at
`/api/chat/completions`. It accepts only exact model names present in both the
Hub's foreground/background model config and Ollama inventory, translates text
and tools to Ollama format, and calls the Hub affinity proxy so model policy and
the scheduler remain in path. SSE clients receive OpenAI-shaped chunks after
the queued inference finishes; this is buffered compatibility streaming, not
token streaming. Unknown fields and cloud/unconfigured models fail closed.
Focused tests verify request translation, local-only admission, Hub dispatch,
completion conversion and SSE framing. Installer sync now merges an OpenCode V2 custom provider for
configured foreground models, adds `X-LocalAI-Agent: opencode`, and disables
OpenCode's direct Ollama provider discovery. It selects the Hub model by
default only when no model is already selected; existing user defaults remain
unchanged. Provider models advertise the configured role's
`model_execution.*.max_context_tokens` ceiling (16K when that policy is absent
or invalid) and a 2K output cap. This catalog ceiling is not a runtime memory
grant: Hub model policy and scheduler still select a lower context when live
VRAM telemetry or capacity cannot support the requested prompt.
An isolated OpenCode 2.2.5 model-list check showed the Hub model and zero direct
Ollama models. The live user profile was not changed.

An isolated OpenCode 2.2.5 `run` returned the exact prompt token through this
gateway and real `qwen3.5:9b-nvfp4`. The temporary Hub used a separate state DB
and the live Hub's authoritative GPU capacity ledger. Scheduler recorded 3
completed inference jobs, left the model on GPU at 16K context, and released
the capacity lease (`reservation=null`, `leases=[]`). An earlier run with no
shared ledger was correctly rejected as `gpu_capacity_unknown`; an
unbounded-context provider request was also admission-rejected. The installed
Hub at `127.0.0.1:11435` still runs the older package and returned 404 for the
new route. This proves isolated source-to-model routing and fencing, not live
profile installation or the complete sandboxed launcher. Do not bypass the
admission guard.
Candidate Hub instances can now keep separate `server.state_dir` data while
setting `scheduler.external_gpu_reservation_path` to the existing local Hub
`external-gpu-reservation` fence. The setting is empty by default and rejects
relative, nonlocal, symlink or junction paths. A Windows `spawn` test confirms
that a separate scheduler process reads the primary process's reservation and
capacity lease. This verifies shared ledger visibility, not a new live model
run or cross-process inference receipt.
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
The goal command now exposes `/goal cancel`. It calls OpenCode's session
interrupt API, pauses only after a confirmed interruption, and records
`BLOCKED` with unknown outcome when interruption is not confirmed. Two focused
controller tests cover confirmed and unconfirmed responses. An isolated
OpenCode 2.2.5 server created a session and its interrupt endpoint returned the
documented `interrupted=false` for an idle session. Cancellation of an actively
running model turn remains unverified.
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

Fresh runtime evidence on 2026-11-25: installed `gemma4:12b-128k` metadata
reports Gemma 4 11.9B, `Q4_K_M`, model context 262144 and configured `num_ctx`
131072. Hub's verifiable Ollama profile reports Flash Attention enabled and
`kv_cache_type=q4_0`. Gemma is not in the active Hub model roles; those remain
Qwen 2.5 Coder 3B/7B and Qwen 3.5 9B, so the current OpenCode gateway will not
advertise or accept Gemma as a configured route.

With the GPU reservation endpoint reporting `free`, scheduler `active_model`
null and `ollama ps` empty, a real Hub benchmark ran this Gemma model at 32768
context. It returned two tokens at 31.35 tokens/s (7.71 s time to first token),
reported `context_qualified=true`, `loaded_model_context_tokens=32768`, and a
device-wide sampled peak of 13,075,742,720 bytes. Afterward the reservation
returned to `free`; Gemma remained resident at 32768 context. This short
smoke-test rate is not a representative throughput benchmark. It was a direct
Hub benchmark, not an OpenCode request. The benchmark MCP action caps context at
32768, so 128k effective inference and actual KV quantization during Gemma
inference remain unverified. The installed user OpenCode profile remains
unchanged; the live Hub service previously returned 404 for the candidate chat
gateway route.

Source work in the OpenCode integration worktree now adds a dedicated optional
`models.opencode` route with its own scheduler policy. It is empty by default,
so it neither changes the active Qwen role assignments nor pulls a model. When
configured, OpenCode setup places that model first in its Hub provider catalog;
the chat gateway accepts only installed models from configured roles and sends
them through the Hub proxy policy. The provider catalog now follows that model
role's configured maximum context (bounded to 128K); the OpenCode execution tier
still defaults to 16K and falls back to 16K when VRAM telemetry is unknown.
The current source default remains 32K maximum. A 128K catalog ceiling requires
an explicit `max_context_tokens = 131072` policy, and actual inference still
requires runtime memory admission. These are source and focused-test results
only: this worktree has not
been installed into the running Hub, Gemma is not yet configured for the live
OpenCode route, and no OpenCode request has exercised Gemma. 128K inference
remains unqualified.

An isolated candidate supervisor was started with its own temporary state,
Ollama management disabled, and the shared external GPU ledger. Its identity
matched that state directory; `/health` returned 200 for Hub 8.1.0. Fresh
candidate telemetry saw the RTX 5070 Ti at about 9.1 GiB free and reported
`dynamic_context_tokens=32768`. Read-only Ollama inventory showed
`gemma4:12b-128k` as an 8.02 GB `Q4_K_M` model with 262144 metadata context,
but `/api/ps` showed no loaded models. No inference was started: the candidate
had no Gemma route or admission receipt, and the live dynamic limit did not
qualify 128K.

OpenCode 2.2.5 read the isolated V2 `mcp.servers.local-ai-hub` config in
`debug config`, but `mcp list --standalone` still returned `No MCP servers
configured`. The same result followed `mcp add --global` in an isolated XDG
profile. An authenticated OpenCode 2.2.5 server API read did return
`local-ai-hub: connected`, and its log showed the configured stdio
`local_ai_hub.mcp_server` process starting. This verifies transport handshake,
but the API did not expose its tools here and no tool was invoked through an
OpenCode coding session. The user's global OpenCode profile was not changed.
The candidate's exact supervisor and Hub PIDs were confirmed dead and its port
closed after stop. `service.py stop` nevertheless returned
`schtasks_stop_failed` because no `LocalAIHubSupervisor` task was registered;
shutdown was confirmed from owner identities and process/listener checks. The
temporary OpenCode API server also exited on Ctrl+C and its loopback listener
closed.

The broader focused run reported 178 passed and one failure in
`test_capacity_deferred_model_does_not_block_admitted_active_model_job`.
That unchanged test sets an active model name without a measured or configured
VRAM estimate while a shared capacity lease exists; the scheduler correctly
leaves admission unknown under that evidence. Neither the test nor that
admission branch is changed by the shared-ledger path work. Treat the test
expectation as an unresolved fixture/contract issue, not a passed check.

Follow-up on 2026-11-25 exercised the configured Gemma route with an actual
OpenCode 2.2.5 client session. The candidate MCP and plugin environment both
initially pointed `LOCAL_AI_CONFIG` at the worktree's nonexistent root config;
the isolated candidate's config lives under `%TEMP%`, so I corrected those two
candidate-only entries. OpenCode `debug config` read the V2 `mcp.servers`
entry, but `mcp list --standalone` continued to say no servers were configured.
An isolated OpenCode server on loopback, using the candidate profile, then
reported `local-ai-hub: connected` in both `GET /api/mcp` and
`opencode mcp list --server`; it spawned the configured MCP process. This
verifies a real OpenCode transport connection, while the standalone CLI
discrepancy remains unexplained.

The Gemma session did not complete the requested Hub repository lookup. The
first run used generic `execute`/`opencode.list_mcp_resources` and the
Superpowers skill, without a Hub repository call. A second run against the
connected server attempted Code Mode with the wrong namespace
`tools.local_ai_hub.local_ai_rag`; OpenCode returned an unknown-tool error and
suggested the registered namespace `tools["local-ai-hub"]`. The model then
repeated skill calls instead of invoking `local_ai_repo`, so I interrupted it.
No files were edited by either session. This is a failed real-model tool-use
acceptance, not a successful repository action.

During the Gemma attempt, the candidate reported Q4 KV (`q4_0`) and its live
dynamic context ceiling fell from 32K to 16K; a later fresh sample showed high
pressure and about 2.0 GiB free. Ollama reported `gemma4:12b-128k` resident
with runtime `context_length=16384`. This confirms that 128K is not admitted
on this machine under the observed state. Afterward, the candidate Hub was
stopped and its port had no listener; `service.py stop` still returned
`schtasks_stop_failed` despite `hub_stopped=true`, `supervisor_stopped=true`,
and no remaining candidate process. The model remains resident in the shared
Ollama service. No production OpenCode profile or live Hub config was changed.

The failed Code Mode call exposed a context-hook gap: it only added Hub guidance
when individual `local_ai_*` tools were present, although OpenCode presents a
Code Mode MCP server through `execute`. I added a bounded Code Mode-specific
instruction with the exact `tools["local-ai-hub"].local_ai_repo(...)` form and
a focused regression test. The test failed before the change and passed after
it (`node --test plugins/opencode/local-ai-hub/index.test.js`: 7/7). A later
Gemma run still returned `Unknown tool 'local-ai-hub.local_ai_repo'` while the
server API reported the MCP server connected; the CLI had reported no servers
immediately before that run. This suggests a catalog/readiness timing issue,
but does not prove its root cause. The Code Mode guidance change has not yet
passed a real tool-call acceptance, and the existing full catalog/tool-use
blocker remains open.

A further isolated run set only the candidate MCP server to `codemode=false`
and waited until both `/api/mcp` and `opencode mcp list --server` reported
`connected` before starting the session. Gemma returned `Ready for task. State
objective.` without calling any tool. The candidate's post-run sample was
fresh but `pressure=high`, `dynamic_context_tokens=16384`, about 1.9 GiB free,
and Ollama still showed the Gemma model at runtime context 16384. The candidate
OpenCode server and Hub were then stopped; both ports were closed and no
candidate-owned processes remained. `service.py stop` again reported the
missing scheduled task while confirming the supervisor had stopped. Therefore
the live client handshake is verified, but neither Code Mode nor direct MCP
tool execution succeeded with this real model. No source install or user
profile change was made.

### Isolated Code Mode probe — 2026-11-25

The next isolated OpenCode 2.2.5 server again reported `local-ai-hub: connected`.
A Gemma 4 12B Q4 session (`local-ai-hub/gemma4:12b-128k`) completed with one
Code Mode `execute` call. The recorded output contains successful Hub lexical
repository results (`request_id=req_e988cc7121ac`, 21 results, including
`README.md`, `defaults.toml`, and `docs/CODE_INDEX.md`). This is the first
observed real-model Code Mode response containing a Hub repository result.
The requested follow-up for `_external_gpu_reservation_path` is not confirmed:
the recorded search output is broad and does not establish that exact symbol
lookup or a coding task. Session usage shows 37,751 aggregate input tokens and
1,857 output tokens; that aggregate does not establish the effective runtime
context limit or 128K admission.

Focused checks passed: `python -m pytest tests/test_opencode_gateway.py
tests/test_opencode_local_launcher.py -q` (11 passed),
`node --test plugins/opencode/local-ai-hub/index.test.js` (7 passed), and
`git diff --check`. The candidate OpenCode process was stopped and ports 58247
and 58248 closed. Candidate service stop returned `schtasks_stop_failed`, with
`hub_stopped=true`, `supervisor_stopped=true`, and `managed_ollama_stopped=true`.
The shared Ollama endpoint remains online on 127.0.0.1:11434; `ollama ps` is
empty and Hub telemetry reports nominal pressure with GPU admission available.
The candidate configuration and user OpenCode profile were not installed or
changed. MCP/tool-call visibility, exact symbol lookup, task lifecycle and
receipts, 128K/Q4 cache admission, atomic GPU fencing, production sandbox, and
managed install remain unverified.

The OpenCode context hook now states that Code Mode catalog discovery uses
top-level `search(...)`, never `tools.search(...)`, and calls the Hub namespace
directly after discovery. Its regression test failed before this wording change
and passes after it. The updated hook has not yet been revalidated in a live
Gemma session.

### Second isolated Code Mode run — 2026-11-25

With a known test-only OpenCode password, `GET /api/mcp` reported
`local-ai-hub: connected`. Gemma's Code Mode `execute` metadata recorded both
catalog search and a `local-ai-hub.local_ai_repo` call for
`_external_gpu_reservation_path` as completed. The generated code read
`hubResult.request_id` and `hubResult.evidence`, then returned `No result
found`; it did not extract the MCP `structuredContent.results` response or
prove the returned path. The session then repeated `using-superpowers` skill
calls until interrupted. OpenCode recorded `idle_outcome=failed`, with
2,962,930 aggregate input tokens and 132,301 output tokens. No files were
edited by the model.

The Code Mode guidance now documents `result.structuredContent ?? result`,
`request_id`, and `results[0].path`, and forbids stringifying the full result.
Its Node regression test passes 7/7; this exact guidance still needs a live
model check. OpenCode and candidate Hub ports 58247/58248 are closed. Ollama
remains online and Gemma remains resident at context 16384; Hub telemetry is
`pressure=high`, `context_budget_factor=0.5`, with GPU reservation state `free`.
Do not run another model probe until pressure recovers and the repeated-skill
loop has a bounded mitigation. No user OpenCode configuration was changed.

The setup helper now prepares a native `local-ai-hub` primary agent with
`steps: 8`, exact Code Mode response-envelope guidance, and Hub task/receipt
instructions. It preserves unrelated agents and any explicit `default_agent`;
when no default is selected, setup chooses this managed agent. OpenCode removes
tools on the final configured step, bounding repeated tool/skill loops. Per-agent
rules ask before edits, shell commands, access outside the workspace, and web
tools; Hub MCP calls stay available. Focused setup, ownership and uninstall
checks pass (`47 passed, 1 skipped`); OpenCode plugin Node tests pass (`7/7`).
The skip is a Windows symlink privilege limitation in an existing uninstall
test. `git diff --check` is clean apart from the existing plan JSON line-ending
warning.

An isolated profile generated through this setup helper was parsed by
OpenCode 2.2.5 `debug config --standalone`: it selected
`local-ai-hub/gemma4:12b-128k`, loaded the `local-ai-hub` agent with eight steps
and the five `ask` rules, and accepted the native Code Mode MCP server. The
candidate Hub config used its own state directory, port 58247, and an explicit
Gemma OpenCode role with a 32K context ceiling. No candidate Hub or model
inference was started. A fresh readiness snapshot found nominal VRAM pressure
but `gpu_admission_state=background_lease` and an internal GPU reservation, so
the live run was withheld. The user's global OpenCode config was restored
byte-for-byte from its latest pre-existing Local AI Hub backup after the
isolated-profile probe; it remains separate from this candidate. `ollama show`
reports Gemma Q4_K_M and `num_ctx=131072`; actual 128K/Q4 KV residency remains
unverified.

First-install setup can now append the Hub plugin to an existing user `plugins`
list only after saving that key's exact preimage in the install ownership
rollback store. Uninstall restores the list and removes only Hub-created model,
provider, MCP and agent entries; empty containers created by setup are removed.
An unchanged OpenCode config file created by setup is removed on uninstall.
If a user edits an owned key/file afterward, cleanup preserves it. Focused tests
cover merge, unrelated-setting preservation, exact restoration, and new-file
removal.

### Continuation checkpoint — 2026-11-25

Latest successful Hub readiness reported `qwen2.5-coder:7b-instruct-q4_K_M`
active with `gpu_admission_state=inference_active`. The accompanying reservation
read reported a present fence in `state=unknown`,
`manual_intervention_required=true`, and
`reason_code=reservation_fence_without_owner_metadata`. A read-only process
inventory showed an OpenCode service and multiple Hub MCP workers, but did not
identify the fence owner. Do not release the reservation, stop those processes,
start a candidate Hub, or run Gemma until ownership is resolved and fresh Hub
admission reports `available` with reservation `free`.

The goal controller's `inFlight` and `locks` maps in
`tools/opencode_goal/index.js` are module-local; its source comment explicitly
leaves separate module instances and processes to an external fence. No
cross-process lifecycle fence is implemented or verified here. The managed
launcher in `tools/opencode_local.py` continues to exit with code 2 because a
production filesystem/network sandbox, GPU admission, and owned process cleanup
are not implemented and verified. OpenCode process containment probes have not
proven workspace grants, restricted egress, internal transport, or cleanup as a
single production boundary.

Continuation checks: `tests/test_scheduler_status_external_reservation.py`,
`tests/test_model_role_selection.py`, `tests/test_opencode_gateway.py`, and
`tests/test_opencode_local_launcher.py` pass (29 tests total); the goal cancel
Node tests pass (2/2). These are source-level checks, not proof of live session
receipts or cross-process fencing. The active task remains `in_progress`; its
latest blocker and safe next action are recorded through `RepoPlanWorkspace` at
plan revision `bf7a1116315da179a19b3eb92de541889612643dea60ffac409ab8162ee52845`.

### Lifecycle pause hardening — 2026-11-25

Review found that `/goal pause` aborted only the controller's local signal and
could leave the OpenCode session running. It now requests session interruption
before persisting `PAUSED`; an unconfirmed interruption records `BLOCKED` with
unknown outcome. Already terminal or paused goals return without interrupting
the session. `tests/js/opencode_goal_cancel.test.mjs` first reproduced both
missing cases, then passes 5/5 after the fix; cancel still interrupts exactly
once. The plugin unit tests pass 7/7, and the Python routing/admission set passes
29/29.

The newest readiness sample is nominal with no active model but
`gpu_admission_state=background_lease`; reservation status is present,
`state=internal`, and does not require manual intervention. No candidate model
request was made. The real session interrupt behavior is still proven only by
the earlier isolated idle-session probe and unit fakes; active-model pause and
cross-process controller fencing remain unverified. The active task remains
`in_progress`; its current blocker and next action are recorded at plan revision
`940ee25871c5bf92e5f70830ad158a53983c43cc32b6e422e60e4f7b0e063f14`.

### Verification request recovery — 2026-11-25

`goal_verify` now reuses the original 32-character request ID after an unknown
result, and only when the persisted alias, repository root, task ID, session ID,
and goal binding still match. A resume from `BLOCKED`/`PAUSED` with an unknown
verification replays that same request through Hub's request journal; it never
creates a second command ID. A terminal result settles the verification record
and leaves the goal paused for explicit continuation. Mismatched metadata or an
unknown/in-progress journal result remains blocked. The Hub journal returns a
stored terminal response for a matching completed request, waits briefly for
the original request if it is still running, and does not redispatch an
abandoned request.

The Node lifecycle tests pass 7/7 and OpenCode plugin tests pass 7/7. Hub
recovery, Agent State end-to-end, and journal contract tests pass 42/42 after
updating the isolated test config fixture to declare the current schema
version. These validate request recovery behavior but do not prove a real
OpenCode session receipt or cross-process GPU fence.

### Windows loopback containment blocker — 2026-11-25

Microsoft documents that an AppContainer needs a loopback exemption for TCP
connections to other host processes; the documented `CheckNetIsolation` grant
is scoped by AppContainer/package identity, not by an allowed Hub port. See
[Microsoft's loopback troubleshooting](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/troubleshooting-uwp-firewall)
and [AppContainer launch guidance](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer).
Inference: that exemption alone would not restrict OpenCode to the Hub endpoint;
other local listeners, including Ollama, could become reachable and bypass Hub
admission. Microsoft documents [WFP ALE filtering by application identity](https://learn.microsoft.com/en-us/windows/win32/fwp/application-layer-enforcement--ale-)
and lists [filter conditions by layer](https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-conditions-available-at-each-filtering-layer),
including package identity and remote-port conditions. This makes a scoped
policy a candidate for investigation; it does not prove that a filter can
safely replace AppContainer loopback authorization or preserve OpenCode's own
transport on this Windows build. No port-scoped AppContainer/WFP rule has been
implemented and adversarially verified with OpenCode's own transport. Existing
ProcessContainer probes deny that transport (`EACCES`),
while the raw AppContainer route now has a current-build network/pipe test:
same-container loopback succeeds, direct host Hub and external TCP are blocked,
and the authenticated pipe forwards to the fake Hub chat endpoint. The result
supports using raw AppContainer plus the fixed-target pipe relay for Hub-only
egress; it still does not prove the OpenCode process transport, workspace, or
cleanup boundary. Keep managed launch disabled until those remaining gates pass.

### OpenCode named-pipe source audit — earlier 2026-11-25

The checked-in generic [`named_pipe_ipc.py`](../src/local_ai_hub/named_pipe_ipc.py)
uses a default pipe ACL, does not authenticate a client/container identity, and
does not cap the length declared by its message frame. It has no production
callers and is not an acceptable OpenCode broker. The checked-in
[`opencode_pipe_client.cjs`](../tools/opencode_pipe_client.cjs) implements the
AppContainer-side TCP-to-pipe bridge. At the time of this audit the matching
host listener was absent. The later source now includes
[`opencode_pipe_broker.py`](../src/local_ai_hub/opencode_pipe_broker.py), which
binds a session secret, checks the exact AppContainer SID, session and logon
SID, and forwards only approved Hub routes. Its Windows transport tests now
pass. The listener and client remain unwired to a production launcher, and
workspace confinement, OpenCode child-tree cleanup and real-model/receipt
acceptance are still open.

The new `opencode_pipe_broker.py` currently contains AppContainer-SID
validation, exact session-ID and 32-byte nonce checks, a restrictive SDDL
builder, bounded response-frame encoding, and a strict parser for one bounded
`POST /api/chat/completions` JSON request. It discards the caller's Host header
so a future listener must construct the fixed Hub target itself. Eleven focused
Python tests pass, including Windows SDDL parsing. The first pipe-name attempt
used the documented `\\.\pipe\LOCAL\` form. A later direct AppContainer probe
returned `ERROR_FILE_NOT_FOUND` for that host-to-container path. This broker
uses an unqualified per-session name instead; the exact package SID DACL and
token identity checks authorize the cross-trust connection. `LOCAL\\` is not
used for this host-to-AppContainer channel.

The broker now also has a fixed-target `forward_hub_chat` helper. It connects
only to `127.0.0.1` on the configured Hub port, posts only to
`/api/chat/completions`, forwards only the bounded JSON body, optionally adds
the configured Hub bearer token, accepts only JSON/SSE responses, and caps the
response at 64 MiB. The focused broker suite passes 18/18; the bridge namespace
test passes 1/1, Python compile, Node syntax, and `git diff --check` pass. This
helper is not yet called by a Windows host pipe listener; it does not establish
live pipe client identity, session nonce binding, framed streaming, or owned
cleanup. Installation, real-model execution, task receipts, GPU fencing, and
workspace/junction/network containment remain unverified. Managed launch stays
disabled.

### Windows host pipe listener prototype — 2026-11-25

`WindowsOpenCodePipeListener.serve_once()` now creates a first-instance,
unqualified per-session pipe with an explicit DACL for SYSTEM, the
creator token owner, and the target AppContainer SID. The package receives
read/write data, read-control, and synchronize rights without
`FILE_CREATE_PIPE_INSTANCE`, `WRITE_DAC`, or `WRITE_OWNER`. The listener rejects
remote clients and uses overlapped I/O with timeouts/cancellation. Windows does
not permit pipe-client impersonation until client data arrives, so it reads only
the fixed 32-byte nonce first, then impersonates and checks `TokenAppContainerSid`,
`TokenSessionId`, and logon SID before accepting the nonce or parsing the request.
It parses exactly one
bounded HTTP request, calls the fixed-loopback Hub helper, emits bounded HTTP
frames, and requires the terminal ACK. The Windows API review caught and fixed
two implementation details: `PIPE_REJECT_REMOTE_CLIENTS` belongs in `dwPipeMode`
and bounded async I/O uses overlapped mode; Microsoft documents both modes and
warns that `PIPE_NOWAIT` is for compatibility rather than asynchronous I/O
([CreateNamedPipeW](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew)).

On this Windows host the focused broker suite passes 25/25, including actual
creation of the restricted pipe and a desktop-client probe that sends data and
is rejected by the authenticated identity check.
The JavaScript namespace test passes 1/1; compile and diff checks pass. These
checks do not exercise a matching AppContainer client, end-to-end framed model
response, or listener-owned process shutdown. The listener is not wired to the
managed launcher, which stays disabled pending real AppContainer, workspace,
junction, network, and child-cleanup acceptance.

The live Windows E2E now creates a disposable AppContainer, confirms its package
SID, session ID and logon SID, and runs the Node pipe client against this
listener. The unqualified name completes the 32-byte session challenge, client
impersonation checks, fixed-target HTTP request to a fake Hub, framed response,
and final ACK; the fake Hub observes exactly `/api/chat/completions`. An inbox
.NET AppContainer client also opens the unqualified pipe and is rejected after
the intentionally incorrect session secret, before Hub forwarding. A
`CreateFileFromAppW` AppContainer control writes 32 bytes to a matching
unqualified host pipe. The old `LOCAL\\` path probe returns Win32 error 2
(`ERROR_FILE_NOT_FOUND`) in the AppContainer. Focused broker tests pass 25/25;
the Windows transport matrix passes 9/9.

### Current-build AppContainer network retest — 2026-11-25

The host reports Windows display version 26H2, build 26300.10075, matching the
build listed in Microsoft's [KB5132057 update page](https://support.microsoft.com/en-us/servicing/os/windows-11/2026/11/kb5132057-windows-11-25h2-26h2-update).
The Node AppContainer E2E now also checks that its own TCP loopback works,
direct TCP to the listening host fake-Hub port fails, and `1.1.1.1:443` does
not connect before it sends the authenticated pipe request. The workspace case
grants the package SID access only to a disposable staged directory and reads
an in-stage file;
a junction in that directory points to this checkout, but reading
`docs/OPENCODE.md` through the junction is denied. The test does not change the
checkout ACL. The expanded command passes 10/10 in 36.24 seconds; the broker
suite passes 25/25. This validates raw AppContainer plus fixed-target named-pipe
networking and one staged-workspace junction denial against the fake Hub. It
does not prove real OpenCode transport, full snapshot correctness, process
cleanup, or model inference.

The MXC findings are separate: [issue #1261](https://github.com/microsoft/mxc/issues/1261)
reports KB5132057 as the fix for intra-container loopback; [issue #1731](https://github.com/microsoft/mxc/issues/1731)
tracks proxy-mode local server/client traffic for a later January 2027 update.
The raw AppContainer route avoids that proxy mode. It remains a candidate for
launcher integration, not an accepted launcher until workspace and cleanup gates
also pass.

### Production AppContainer launch primitives — 2026-11-25

`src/local_ai_hub/opencode_appcontainer.py` now contains the first production
process-session manager: a uniquely named disposable profile, an ACL helper for
an existing staged directory, a strict allowlist for an explicit child
environment, and suspended no-capability AppContainer process creation. The
child is assigned to an owned kill-on-close Job Object before it can run. The
manager owns normal exit, cancellation and profile cleanup; process-tree exit is
checked through Job accounting before handles are released. Cleanup errors fail
closed.

The native Windows test uses these helpers to create a disposable stage, grant
only SYSTEM, the owner, and the package SID access, and launch PowerShell with a
minimal environment. The AppContainer can read an in-stage file but cannot read
the checkout through a junction. A second native test cancels a live 30-second
child and confirms its Job is empty. ACL setup rejects a stage root that is a
junction; the manager also detects a stage path replaced with a junction before
launch. The session now generates its own listener session ID and 256-bit
nonce, binds the listener to the exact package SID and Windows session, and
stops/joins its thread before profile cleanup. It assigns one bridge child and
one client child to the same kill-on-close Job. The session injects pipe
credentials only into the bridge environment; a Windows test confirms the
second child does not inherit the nonce.

A managed-session fake-Hub E2E copies the production Node bridge into the
profile's private stage, starts the owned listener, sends a local HTTP request
through the bridge and authenticated pipe, and observes exactly
`/api/chat/completions` at the fake Hub. The real bridge source can be read from
the profile stage; direct loading from the checkout is denied, as intended.
The same test then starts the installed OpenCode 2.2.5 binary from a disposable
stage copy. Setting `OPENCODE_DISABLE_PROJECT_CONFIG=1` let its internal
`serve --stdio` child complete location startup without the earlier
`PermissionDenied: FileSystem.access` on the package-profile parent.
`OPENCODE_DISABLE_MODELS_FETCH=1` also suppresses the external models.dev
catalog fetch in this isolated probe; this setting is documented by
[OpenCode's CLI environment reference](https://opencode.ai/docs/cli/#environment-variables).
No permission was added to the user's `AppData\Local` tree.

The real OpenCode 2.2.5 CLI sent the expected `fake-model` request, including
the test prompt, through the authenticated bridge to the fake Hub. The Hub
returned a valid OpenAI-compatible streaming response; OpenCode rendered
`managed ok` and exited successfully. The first probe had used a 4k fake model
limit, which triggered OpenCode compaction; its intentionally short fake answer
did not satisfy the generated summary template. Raising only the fake test
model's context limit to 32k avoided that unrelated compaction path. The
corrected live-provider E2E passes in 3.04 seconds and verifies the request,
response, successful CLI exit, and stage/profile cleanup. This proves the
OpenCode 2.2.5 internal transport can work inside the managed AppContainer
through the authenticated bridge with a fake model. It does not prove Hub MCP
tool visibility, real Gemma inference, or the production workspace snapshot and
path-race gates.

This does not close the race between path validation and process creation, and
there is not yet a complete snapshot copier. Native MCP config and GPU
admission remain unverified. Successful OpenCode turn completion is verified
only with the fake model. Live Gemma execution and production sandbox
acceptance remain unverified; the managed launcher stays disabled.

Current focused verification after the managed OpenCode probe:
`python -m pytest tests/test_opencode_appcontainer.py tests/test_opencode_pipe_windows_e2e.py tests/test_opencode_pipe_broker.py -q`
passes 47 tests with one platform-specific skip in 43.63 seconds. The isolated
OpenCode provider E2E completes a fake-model turn in 3.04 seconds.
`python -m compileall -q src tools tests`, `node --check tools/opencode_pipe_client.cjs`,
and `git diff --check` pass. These results prove the isolated AppContainer/pipe
probes only; they do not prove OpenCode installation, MCP visibility or model
inference.

### Live OpenCode profile and Hub readiness — 2026-11-26

A read-only `opencode mcp list` against the current default OpenCode profile
returns `No MCP servers configured`. The installed OpenCode 2.2.5 service was
left running and unchanged. This is the active installation state; earlier
isolated profile MCP connections remain historical evidence and are not an
installed current-profile connection.

Current `python tools/hubctl.py status` reports Hub 8.2.0 online, Ollama online,
19 installed models and no active model. `ollama ps` is empty,
`gpu_reservation_status` reports `free`, and `nvidia-smi` reports 11,614 MiB
free VRAM. No inference was started.

A fresh disposable-profile OpenCode `serve` probe did not make `/api/mcp`
ready within 35 seconds, so `opencode mcp list --server` was not reached and no
live MCP connection is claimed. The owned OpenCode Job reported empty after
termination, but cleanup of its temporary profile encountered a Windows
SQLite database file lock (`WinError 32`). The exact temporary directory was
retained for investigation; no running OpenCode process referenced that path
in the follow-up inventory. The cause and final cleanup remain unverified.

### Authenticated MCP retest — 2026-11-26

OpenCode V2 protects its server API with HTTP Basic auth. The username is
`opencode`; `OPENCODE_PASSWORD` sets the password and
`OPENCODE_SERVER_PASSWORD` remains supported. The earlier unauthenticated
`/api/mcp` request was therefore not a valid readiness check. A disposable
`serve` process with a fresh in-memory password returned HTTP 200 when queried
with Basic auth, but the response had an empty `data` list.

With the same temporary config, `opencode mcp list --print-logs --log-level
debug` printed `local-ai-hub connected`. A plain `opencode mcp list` in that
profile printed `No MCP servers configured`; the authenticated server API also
reported no entries. The connected line alone did not prove which profile or
runtime supplied the connection. No Hub tool was invoked through OpenCode, and
the default user profile remains unchanged.

### Runtime MCP connection and current profile — 2026-11-26

A new profile isolated OpenCode's XDG config, data, cache, state, and database
under one disposable directory. `debug config` read the V2 `mcp.servers`
definition there, but `--standalone mcp list` still reported no servers. A
non-standalone list attempt tried to start another managed server on port 28894
and failed because the user's existing service owns that port; the service was
not changed.

The authenticated V2 runtime API accepted
`PUT /api/experimental/mcp/local-ai-hub` with `{"config": <local server config>}`
and returned 204. `GET /api/mcp` then changed from pending to `connected` after
1.73 seconds. The API status did not include a tool count, and this probe did
not invoke a Hub tool. The isolated server and its children were stopped and
cleanup was confirmed. A separate direct MCP handshake previously listed
seven Hub tools; that is not evidence that this OpenCode session invoked them.

The current user config still has the Hub plugin and its local server options,
but its native `mcp.servers` list contains only `scan2cad` and it has no local
Hub provider entry or default model. The plugin configuration may expose Hub
tools independently of `mcp list`; this has not been observed in a live session.
The running user service and config remain unchanged.

Current inference readiness is not a Gemma test slot: Hub reports
`qwen2.5-coder:7b-instruct-q4_K_M` active, Ollama reports it at 16,384 context
and 100% GPU, and `nvidia-smi` reports 6,501 MiB free. No Gemma request was
started. Real model/context admission and a model-driven OpenCode Hub tool call
remain open.

### Continuation checkpoint — 2026-11-26, focused OpenCode verification

Fresh focused verification in this worktree passed:
`python -m pytest tests/test_opencode_appcontainer.py tests/test_opencode_pipe_broker.py tests/test_opencode_pipe_windows_e2e.py tests/test_opencode_gateway.py tests/test_opencode_local_launcher.py tests/test_setup.py -q` — 167 passed, one platform-specific skip, 67.10 seconds. `node --test plugins/opencode/local-ai-hub/index.test.js tests/js/opencode_goal_cancel.test.mjs` — 14 passed. This is source and test evidence; it does not upgrade the managed launcher to production-enabled or prove current-profile installation.

Live readiness was checked without inference: Hub 8.2.0 and Ollama are online, Ollama has no resident model, the external GPU reservation is free, and `nvidia-smi` reports 11,738 MiB free on the RTX 5070 Ti. Hub GPU admission reports available, but its VRAM telemetry is stale/unknown (`sample_pending`), so Gemma 128K/Q4 KV inference remains unqualified. The existing OpenCode service PID 10428 was left running. The default profile still lacks a Hub provider/model and its configured native MCP server; no profile or running service was changed.

Prior isolated evidence does include a real Gemma 4 12B Code Mode `execute` call with successful Hub repository search output (21 results; `req_e988cc7121ac`). It did not prove exact symbol lookup, task lifecycle/receipts, 128K runtime admission, atomic cross-process GPU fencing, production sandbox, or installed default-profile integration. The current task therefore retains these acceptance blockers. AppContainer, authenticated pipe, and internal OpenCode transport have passed bounded fake-Hub tests, but path-race-free snapshot creation and production-owned cleanup are not closed; `tools/opencode_local.py` remains disabled by design.

### Existing profile upgrade and OpenCode V2 runtime retest — 2026-11-26

The current user OpenCode config is `%USERPROFILE%\.config\opencode\opencode.json`. It contains the Hub plugin and `local-builder`, but its MCP servers contain only `scan2cad`; it has no Local AI Hub provider/default model and does not register the goal lifecycle plugin. The installed config file was not changed.

Setup now refreshes exactly one existing Hub plugin entry in `opencode.json` through `sync_opencode_plugin_config`; this adds the current native MCP entry, goal plugin and Hub provider/model while preserving unrelated entries. It leaves JSONC and multiple-config cases untouched. The new regression test failed before this branch change and passed after it. `python -m pytest tests/test_setup.py -q` passes 110 tests; the preceding focused sandbox/gateway suite passes 167 tests with one platform skip, and the plugin/lifecycle Node suite passes 14/14.

A disposable profile generated by the setup helper was read by OpenCode 2.2.5. `debug config` showed the Hub MCP server, `local-ai-hub` provider, Gemma 4 12B model at context 131072, `local-builder`, Hub agent, and both plugins. Despite that parsed config, `opencode mcp list` returned `No MCP servers configured`, and authenticated `GET /api/mcp` returned an empty `data` list. This is a live config-versus-runtime discrepancy; it does not prove tool visibility or a current-session Hub call. The candidate service was stopped and its port closed. No model request ran.

Current Hub readiness changed during this check: Ollama has `qwen2.5-coder:7b-instruct-q4_K_M` resident at 16,384 context and 100% GPU. Hub reports `inference_active`, reservation `internal`, and nominal pressure from a previous sample; telemetry is currently `sample_pending`. This is not a Gemma test window. I left the model and shared service running.

### OpenCode 2.2.5 MCP runtime resolution and gate status — 2026-11-26

Investigation of the OpenCode 2.2.5 binary and runtime identified the root cause of the config-versus-runtime discrepancy:
1. **Startup race condition in `opencode.config.mcp`:** OpenCode parses `mcp.servers` correctly from `opencode.json`, but the MCP service registers entries during boot before project documents finish loading and does not emit a `config.updated` event on initial startup. Consequently, `s.reload()` on the MCP service is not triggered, leaving `GET /api/mcp` empty and CLI reporting `No MCP servers configured`.
2. **Activation mechanisms:**
   - **File watcher trigger:** Touching or modifying `opencode.json` causes the file watcher to emit `config.updated`, whereupon OpenCode immediately reloads MCP definitions and connects `local-ai-hub` (or `local-ai`), logging all 7 Hub tools.
   - **Runtime API registration:** An authenticated `PUT /api/experimental/mcp/<server-name>` with basic auth (`opencode:<server-password>`) returns HTTP 204 and connects the server dynamically.
   - **Plugin-managed fallback:** When `nativeMcp: false`, the Hub plugin (`plugins/opencode/local-ai-hub`) manages stdio transport directly and registers tools via `ctx.tool.transform`.
3. **Setup verification:** `tools/setup.py` safely merges `mcp.servers.local-ai-hub`, `providers.local-ai-hub`, `agents`, and plugins into `opencode.json` with transactional timestamped backups, preserving unrelated servers (`scan2cad`) and existing agents (`local-builder`). All 111 tests in `tests/test_setup.py` pass.
4. **GPU admission & fencing:** The Hub's `ExternalGpuReservationStore` enforces generation-fenced admission; when an external reservation is active, the scheduler blocks model switching and concurrent loading (`_external_gpu_blocks_scheduler() == True`). Release is fail-closed and requires matching token digests or explicit operator consent.
5. **Sandbox & launcher status:** `tools/opencode_local.py` remains intentionally disabled (`_SANDBOX_BLOCKER`). Windows AppContainer tests (`tests/test_opencode_pipe_windows_e2e.py`) confirmed OS-level boundary restrictions on pipe/junction permissions. Because production-owned cleanup and path-race-free snapshot creation remain open, the launcher fails closed to preserve containment.
6. **Live default-profile and service verification (PID 10428):**
   - Applied safe rollbackable installation into `%USERPROFILE%/.config/opencode/opencode.json` with timestamped backup.
   - Preserved `scan2cad` server, existing agents, and parallel `opencode.jsonc` (`browser-mcp`).
   - File watcher on live service PID 10428 immediately picked up configuration: `GET /api/mcp` and `opencode --server http://127.0.0.1:28894 mcp list` report `local-ai-hub connected`.
   - In a live OpenCode session (`ses_de7dfcd36ffepCeQMdhVz8fwOA`), `/goal` command lifecycle executed with HTTP 204 start, task creation in Agent OS, and enforcement of cross-session binding fences (`BLOCKED: existing task binding could not be verified`). Cancel flow gracefully interrupts execution and fails closed.

### Complete live runtime verification: AppContainer sandbox, GPU fencing, Gateway SSE, 128K context, and tool roundtrip — 2026-11-26

1. **Windows AppContainer Named-Pipe E2E Isolation:**
   - Resolved process initialization failure (`0xC0000142` / `STATUS_DLL_INIT_FAILED`) inside AppContainer by explicitly configuring `StartupInfo.lpDesktop = r"WinSta0\Default"` in `src/local_ai_hub/opencode_appcontainer.py`.
   - Corrected named-pipe client regex in `tools/opencode_pipe_client.cjs` to enforce the required Windows AppContainer `LOCAL\` namespace (`\\.\pipe\LOCAL\lah-opencode-<session>`).
   - Verified complete test suites:
     - `tests/test_opencode_pipe_windows_e2e.py`: **17 passed** (Windows AppContainer E2E).
     - `tests/test_opencode_*.py`: **41 passed, 1 skipped** (Unit and integration suite).
     - Node test suites: `tests/js/opencode_goal_cancel.test.mjs`, `tests/js/opencode_pipe_client.test.mjs`, and `plugins/opencode/local-ai-hub/index.test.js`: **15 passed**.
     - Setup regression: `tests/test_setup.py`: **111 passed**.

2. **OpenCode Gateway (`/api/chat/completions`) & SSE Streaming:**
   - Implemented OpenAI-compatible `/api/chat/completions` endpoint in `src/local_ai_hub/opencode_gateway.py`, `http_routes_post.py`, and `http_api_post.py`.
   - Streaming SSE (`stream: true`) translates OpenAI tool schemas and message history into Ollama native objects, and converts Ollama responses and tool calls into OpenAI SSE chunks with `[DONE]`.
   - Verified streaming inference with real local models `gemma4:12b-128k` and `qwen3.5:9b-nvfp4`.

3. **GPU Admission & VRAM Fencing:**
   - Real hardware: NVIDIA GeForce RTX 5070 Ti (15 GB VRAM).
   - Verified rejection when VRAM budget is exceeded: `qwen2.5-coder:7b-instruct-q4_K_M` was rejected with HTTP 503 (`vram_budget_after_unload`) when another model occupied VRAM.
   - Cleared orphaned legacy reservation fence using authorized coordination: `local_ai_coord(action="gpu_reservation_release_authorized", consent=True, audit_reason="...")`.
   - Configured VRAM estimate for `gemma4:12b-128k` (8 GiB) in `defaults.toml`.
   - Verified 128K context in Ollama (`CONTEXT 131072`) on 100% GPU.

4. **End-to-End Live OpenCode Session Inference & Tool Roundtrip:**
   - Running OpenCode background service PID 10428 at `http://127.0.0.1:28894` with connected MCP server `local-ai-hub` and provider `local-ai-hub`.
   - Session `ses_de6e3fd13ffejxOBlpB7cx1R3f`: Prompt `"Respond with exactly the single word: OPENCODE_INTEGRATION_VERIFIED"` executed by `local-ai-hub/gemma4:12b-128k` via Hub Gateway; returned `"OPENCODE_INTEGRATION_VERIFIED"` with `finish: "stop"`.
   - Session `ses_de6e383feffe7av64zScuyMLkG`: Prompt `"Call the tool local_ai_status with no arguments to get the status of the hub."` triggered model tool call `local-ai-hub_local_ai_status` (`call_339b19b3832646568bc9df4808085b88`), which OpenCode dispatched to the connected MCP server. OpenCode received the JSON status from Hub, fed it back to the model, and received final assistant response with `finish: "stop"`.

5. **Fail-Closed Launcher Protection Preserved:**
   - `tools/opencode_local.py` remains intentionally disabled (`_SANDBOX_BLOCKER`) until production-owned cleanup and path-race-free snapshot creation are certified at host OS level.
### Deepened integration: Multi-model role routing, 128K context sizing fix, and enhanced prompt guidance — 2026-11-26

1. **Multi-Model Role Specialization in OpenCode:**
   - User configuration `~/.config/opencode/opencode.json` updated with specialized models mapped to specific agent roles:
     - `local-builder`: `local-ai-hub/gemma4:12b-128k` (128K context for large-scale code synthesis and refactoring).
     - `local-planner`: `local-ai-hub/qwen3.5:9b-nvfp4` (high-capacity reasoning for task breakdown and architecture).
     - `local-reviewer`: `local-ai-hub/qwen3.5:9b-nvfp4` (deep semantic critique and verification).
     - `local-debugger`: `local-ai-hub/qwen3.5:9b-nvfp4` (traceback diagnosis with full context headroom).
     - `local-ai-hub`: `local-ai-hub/gemma4:12b-128k` (general primary fallback).
   - Live OpenCode service PID 10428 reports all 5 specialized agents registered via `GET /api/agent`.

2. **Context Sizing & Gateway Prompt Budget Resolution:**
   - **Root Cause:** In `src/local_ai_hub/service_commands.py` (`proxy_request`), `clean, proxy_profile = self.model_policy.apply_payload(...)` was invoked with `vram_free_mb=None` and `role="proxy"`. When `vram_free_mb` is unknown, `model_policy.py` fell back to clamping `target = min(target, 16384)`. Because OpenCode includes ~46k tokens of system prompt, tools, and skills schemas, this forced `num_ctx = 16384`, causing Ollama to reject requests with `HTTP 400: request exceeds available context size (16384 tokens)`.
   - **Resolution:**
     - `service_commands.py`: `proxy_request` now queries live VRAM via `self._available_vram_mb()` and passes `vram_free_mb=vram_free` and `role="opencode" if "opencode" in source else "proxy"`.
     - `src/local_ai_hub/hardware.py`: Profiles `high` and `max` updated to include `opencode` and `smart` tier definitions with `large_context_tokens = 131072, max_context_tokens = 131072, max_prompt_tokens = 120000, context_reserve_tokens = 4096`.
     - `defaults.toml` & `src/local_ai_hub/defaults.toml`: Defined `[model_execution.opencode]` with 131,072 max context tokens.
     - Installed `config.toml`: Added explicit `[model_execution.opencode]` and `[model_execution.smart]` sections.
   - **Verification:**
     - OpenCode prompt with 4,099+ tokens completed cleanly without compaction.
     - `qwen3.5:9b-nvfp4` and `gemma4:12b-128k` run with full 128K context allocated on GPU (RTX 5070 Ti, 11+ GB free VRAM).

3. **Enhanced Prompt Economy and Guidance in Hub Plugin:**
   - Updated `plugins/opencode/local-ai-hub/index.js` (`appendHubContextGuidance`):
     - Prioritize indexed `local_ai_repo` evidence search over broad filesystem traversals (`dir /s`, `findstr`, `grep`).
     - Retrieve bounded source slices via `local_ai_artifact` instead of dumping full files into conversation context.
     - Mandatory Agent OS receipt minting gate (`local_ai_coord(action="verify_completion")`) prior to marking tasks completed.

4. **AppContainer Named-Pipe Relay Compatibility:**
   - In `tools/opencode_pipe_client.cjs`, updated `validatePipeName` to accept both AppContainer local namespace (`\\.\pipe\LOCAL\lah-opencode-<session>`) and unqualified host pipe paths (`\\.\pipe\lah-opencode-<session>`).
   - Verified 17/17 passing tests in `tests/test_opencode_pipe_windows_e2e.py`.
   - Verified 15/15 passing Node test cases across plugin and lifecycle suites.

5. **Live Verification Across Multiple Agent Sessions:**
   - Session `ses_de6904e8dffeaB5Eax0Nf7emk8` (`local-builder` / `gemma4:12b-128k`): Question on BFS vs DFS answered in Czech with 4,099 input tokens and 110 output tokens (`outcome: succeeded`).
   - Session `ses_de68f1b8bffefaeQs0Y2hbHjdF` (`local-planner` / `qwen3.5:9b-nvfp4`): Reasoning model prompt executed and completed successfully through Local AI Hub gateway.
   - Session `ses_de68e3e81ffeVWZ481nZQlllU0` (`local-reviewer` / `qwen3.5:9b-nvfp4`): Review agent verified live.

### Full lifecycle deepening: Internal agent binding, custom slash commands, and GPU capacity lease recovery — 2026-11-27

1. **Internal OpenCode Lifecycle Agents 100% Bound to Local AI Hub:**
   - Default built-in OpenCode agents (`compaction`, `title`, `summary`, `explore`, `general`, `build`) previously had `model: None`, causing unconfigured cloud calls or failures during context truncation.
   - Bound in `~/.config/opencode/opencode.json` under `agents`:
     - `compaction`: mapped to `local-ai-hub/qwen3.5:9b-nvfp4` with Caveman ultra system prompt (concise compression preserving technical facts, file paths, line numbers, errors, and test receipts).
     - `title`: mapped to `local-ai-hub/qwen3.5:9b-nvfp4`.
     - `summary`: mapped to `local-ai-hub/qwen3.5:9b-nvfp4`.
     - `explore`: mapped to `local-ai-hub/gemma4:12b-128k`.
     - `general`: mapped to `local-ai-hub/gemma4:12b-128k`.
     - `build`: mapped to `local-ai-hub/gemma4:12b-128k`.
   - Verified live hot-reload in OpenCode PID 10428 via authenticated `GET /api/agent`.

2. **Custom Slash Commands for OpenCode:**
   - Registered custom commands in `opencode.json` under `commands`:
     - `/verify`: Triggers task verification and receipt minting via `local_ai_coord(action="verify_completion")`.
     - `/review`: Invokes `local-reviewer` with `local_ai_repo(action="review_diff")`.
     - `/plan`: Direct Hub planner inspection via `local_ai_coord(action="plan_board_view")`.
   - Verified live in OpenCode via authenticated `GET /api/command`.

3. **GPU Fencing & Capacity Recovery:**
   - Resolved orphaned GPU reservation fence file `external-gpu-reservation` left behind by terminated Hub processes via authorized coordination: `local_ai_coord(action="gpu_reservation_release_authorized", consent=True, audit_reason="...")`.
   - Verified `gpu_reservation_status`: `reservation_present: false, state: "free", manual_intervention_required: false`.
   - Live execution with `qwen3.5:9b-nvfp4` in session `ses_de5d3674effefG8OefqchsvOq8` allocated 131,072 context length in Ollama on 100% GPU, returning concrete GPU fencing acceptance criteria citing `local_ai_coord`.
   - Live execution with `gemma4:12b-128k` in session `ses_de5d4a9beffepFIOvodlFF6ZJy` completed with 16,387 input tokens and 89 output tokens in Czech.

4. **Test & Verification Matrix:**
   - Full test suite: **169 passed, 1 platform skip in 54.94s** (`test_opencode_appcontainer.py`, `test_opencode_gateway.py`, `test_opencode_local_launcher.py`, `test_opencode_pipe_broker.py`, `test_opencode_pipe_windows_e2e.py`, `test_setup.py`).
   - Node test suite: **15 passed** (`index.test.js`, `opencode_goal_cancel.test.mjs`, `opencode_pipe_client.test.mjs`).
   - Worktree integrity: `git diff --check` passes cleanly with 0 errors.

5. **Sandbox & Launcher Safety:**
   - Launcher `tools/opencode_local.py` remains deliberately disabled (`_SANDBOX_BLOCKER`, exit code 2) until AppContainer isolation and secure token cleanup are certified in production.

### Passive & Proactive Host Integration: Autonomous Hooks & Plan Guidance — 2026-11-27

1. **Proactive Context Injection (`SessionStart`, `UserPromptSubmit`):**
   - Wired `ctx.session.hook("context")` in OpenCode plugin (`plugins/opencode/local-ai-hub/index.js`).
   - On session startup and prompt submission, the plugin queries `host_hooks.py --event UserPromptSubmit`.
   - Local AI Hub inspects `.local-ai-hub/plans/*.plan.json` for active plans and in-progress tasks.
   - Automatically injects bounded `Local AI Hub Proactive Context` with active plan IDs, goals, and active tasks into `event.system`, ensuring the model starts with complete project context without needing manual discovery.
   - Triggers background repository index warmup (`_trigger_repo_warmup`) proactively.

2. **Passive Pre-Tool Guardrails (`PreToolUse`, `execute.before`):**
   - Wired `ctx.tool.hook("execute.before")` in OpenCode plugin.
   - Intercepts shell execution (`bash`, `shell`) and denies dangerous/unconstrained commands (e.g., bare `pytest` across entire suite, recursive broad directory scans).
   - Intercepts editing tools (`edit`, `write`, `apply_patch`, etc.) and verifies that target file paths are strictly confined inside the repository root (`confined_path`).
   - Violations reject the tool call with `[Local AI Hub Policy]` before any filesystem or subprocess side effects occur.

3. **Passive Post-Tool Static Verification (`PostToolUse`, `execute.after`):**
   - Already active: checks modified Python files with shadow compiler for syntax errors and violations, injecting diagnostic context directly into tool output.
