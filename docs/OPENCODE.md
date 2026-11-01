# OpenCode integration (in progress)

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

`python tools/setup.py --inspect-opencode-hardware` inspects detected dedicated
GPU capacity. `--opencode-profile auto|12gb|16gb` selects a capacity tier and
`--opencode-model NAME` adds an explicit candidate. This inspection does not
install or activate a model and never certifies VRAM admission or performance;
it reports unsupported capacity below the 12 GB tier. Context size, backend
compatibility, free memory and model fit require runtime measurements.

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
can select a Hub configuration. It requires a running updated Hub with a configured API token
of at least 32 ASCII characters, the pinned verified OpenCode executable, and an
explicit model. It starts a dedicated provider session and requests shutdown of
that same session on exit. Before starting, it checks the configured loopback
Ollama inventory and refuses a missing model without downloading it. This check
uses the launcher's configuration; it does not prove that a running Hub has
reloaded that same configuration or that the model fits in GPU memory. After
reserving the Hub scheduler, the provider also checks its own Ollama inventory
and refuses to start if a different model is already resident. It repeats the
version and resident-model checks on the same TCP connection used for each
inference request; a closed connection is not replaced. These checks are snapshots:
unrelated Ollama clients are not fenced and can race the check. Its managed OpenCode data lives under the configured
Hub state directory; existing user configuration is not overwritten. It disables
project OpenCode configuration to prevent endpoint or plugin overrides and tells
the agent to read project `AGENTS.md` instructions. Normal setup prepares its
components only when requested; it does not run the launcher. The launcher does
not sandbox shell network access or establish VRAM
admission. An isolated end-to-end test used OpenCode with a fake backend only.
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
and actions for this profile. Synchronous Ollama and llama.cpp generation and
scheduler submissions honor a request-scoped deny before dispatch. Text search, caller lookup, task creation and memory record/find
have focused HTTP tests. RAG search uses the existing lexical index without
embedding or reranking for this profile; it does not perform semantic retrieval.
The allowlist is incomplete and other RAG operations remain rejected.
Stale CodeIndex results do not enqueue preprocessing for `opencode-local`;
their cache entries are separated so unrestricted clients can still notify the
preprocessor. Repository reads in that profile also do not change the priority
of registered preprocessing projects. Existing independent workers are unaffected.

These layers are not a complete local-only security boundary: the agent label
is caller-supplied, request context does not automatically cross arbitrary
threads, and independently scheduled background workers are not covered.
Do not enable this experimental profile as a guarantee of GPU exclusivity or
cloud isolation. Existing running Hub processes must be restarted separately
before they use these server changes.

The Hub scheduler has an experimental external GPU reservation:
it rejects acquisition while internal work is queued or active and fences
dispatch, idle unload and background acquisition until the holder releases it.
It persists a capability hash under the configured state directory across Hub
process restart; unreadable or malformed reservation state fails closed. It is
not connected to OpenCode and cannot establish that external inference has
stopped. Do not manually clear the state while inference could still run. The
reservation alone is not GPU ownership proof.
An experimental session wrapper holds that reservation across requests, binds
one model, and relays OpenAI-compatible SSE only after serial admission. Its
bounded parser requires a complete `[DONE]` event and upstream EOF; incomplete
or disconnected streams retain the fence. Tests use a loopback fake backend.
An experimental loopback-only, bearer-authenticated HTTP bridge exposes the
streaming chat endpoint to a single model and forwards only to a loopback
backend. Fake-server tests cover authentication, model selection, concurrency,
truncation and backend failure. An isolated OpenCode 2.2.5 process successfully
used the bridge with a fake model backend, and the reservation was then released.
The Hub now owns its lifecycle through authenticated experimental start, status
and stop endpoints. Start requires a configured Hub API token of at least 32
ASCII characters; only a nonce is returned, and the provider credential is
derived locally. Stop is asynchronous and retains the fence on uncertainty.
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
An isolated OpenCode 2.2.5 run with a fake model confirmed that
`session.wait` returned after that test session became idle and `session.get`
reported success. This does not prove exclusive ownership or reconcile an
uncertain task mutation, so it is not yet used to clear the recovery fence.
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
