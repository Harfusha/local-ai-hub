# T19 Release Validation Runbook

Status: **procedure only; no clean-host result recorded**. The v7 artifact pair below is historical: it predates T19 prompt/generator source edits and cannot validate them. Preserve its recorded hashes for provenance. Current release validation must use a new artifact pair built from T20's frozen integrated revision.

## Frozen-source command pack — prepared, not run

Run only after T20 names one frozen integration revision and explicitly assigns T19 a serial validation slot. T20 owns the central queue; a prior slot release alone does not authorize the next run. Set environment variable `T19_FROZEN_SOURCE` to a clean checkout of that revision with no pre-existing `build/` or `dist/`; keep existing user worktrees and artifacts untouched. The commands derive a revision-specific artifact directory outside `$SourceRoot`. These commands validate T19 source gates; they do not complete T20 release acceptance.

```powershell
$SourceRoot = (Resolve-Path $env:T19_FROZEN_SOURCE).Path
$Revision = (git -C $SourceRoot rev-parse --short HEAD).Trim()
$ArtifactDir = Join-Path $env:TEMP "local-ai-hub-4.0.0-$Revision"
if (git -C $SourceRoot status --porcelain --untracked-files=all) { throw 'T19_FROZEN_SOURCE must be a clean checkout' }
foreach ($name in @('build', 'dist')) {
    if (Test-Path (Join-Path $SourceRoot $name)) { throw "T19_FROZEN_SOURCE contains $name/; preserve it and select a clean checkout" }
}
if (Test-Path $ArtifactDir) { throw 'Artifact directory already exists; choose a fresh frozen revision or external output path' }
New-Item -ItemType Directory -Force $ArtifactDir | Out-Null
Set-Location $SourceRoot

$tests = Get-ChildItem -Path tests -Filter 'test_t19_*.py' -File |
    Sort-Object Name | ForEach-Object { $_.FullName }
python -B -m pytest -q -p no:cacheprovider --tb=short $tests
if ($LASTEXITCODE -ne 0) { throw 'T19 scoped tests failed' }

# Run after T01 releases the inventory source contract; check mode does not rewrite docs.
python tools/surface_inventory.py --check --task-id T19
if ($LASTEXITCODE -ne 0) { throw 'T19 surface inventory check failed' }

# Run before building; require clean frozen source without build/ or dist/.
python tools/release_check.py --root $SourceRoot --expected-version 4.0.0 --post-test --json
if ($LASTEXITCODE -ne 0) { throw 'Release source check failed' }

# Write release artifacts externally; allow disposable build intermediates only in this clean checkout.
$BuildEnv = Join-Path $env:TEMP "local-ai-hub-build-$Revision"
if (Test-Path $BuildEnv) { throw 'Build environment already exists; choose a fresh temporary path' }
py -3.13 -m venv $BuildEnv
$Builder = Join-Path $BuildEnv 'Scripts\python.exe'
& $Builder -m pip install build
if ($LASTEXITCODE -ne 0) { throw 'Build frontend install failed' }
& $Builder -m pip --version
& $Builder -m build --version
& $Builder -m build --sdist --wheel --outdir $ArtifactDir $SourceRoot
if ($LASTEXITCODE -ne 0) { throw 'Package build failed' }
Get-FileHash -Algorithm SHA256 (Join-Path $ArtifactDir 'local_ai_hub-4.0.0.tar.gz')
Get-FileHash -Algorithm SHA256 (Join-Path $ArtifactDir 'local_ai_hub-4.0.0-py3-none-any.whl')
```

Record the frozen revision, exact commands, exit codes, output paths and both artifact hashes before beginning clean-host validation. Do not overwrite the v7 artifacts or reuse their receipts for a newer package.

## Historical v7 artifact identity

Preserve these recorded v7 hashes as historical provenance only. Do not install this pair as evidence for the current integrated revision:

| Artifact | SHA-256 |
| --- | --- |
| `local_ai_hub-4.0.0.tar.gz` | `9ae54e1f86e5c8e810ba32be7f9df19277485d834a38f664aac68336a1e18efb` |
| `local_ai_hub-4.0.0-py3-none-any.whl` | `e2bc477680cebc36b9300651250d217214ca80ef9bfebb943c89397eff4c7f76` |

## Current frozen candidate identity

Use only the sdist and wheel emitted into `$ArtifactDir` by the frozen-source command pack above. Transfer that immutable pair and its revision/hash receipt to each clean host without rebuilding. Set `$Root`/`$ROOT` to the transferred artifact directory and `$Revision`/`$T19_REVISION` to the exact frozen commit identifier. Verify both artifact hashes against the frozen-source receipt before installation. Use disposable, clean Windows 10/11 and Linux hosts with Python 3.11–3.14. Record OS release, architecture, Python and pip versions, date, revision, and artifact hashes. Start with no installed Hub, no `PYTHONPATH`, and no system-site-packages in the virtual environments. Keep the host offline from any Hub service; these checks cover package installation and local doctor output only.

| Python | Windows launcher | Linux executable | Environment tag |
| --- | --- | --- | --- |
| 3.11 | `py -3.11` | `python3.11` | `py311` |
| 3.12 | `py -3.12` | `python3.12` | `py312` |
| 3.13 | `py -3.13` | `python3.13` | `py313` |
| 3.14 | `py -3.14` | `python3.14` | `py314` |

## Windows

Run in PowerShell. Set `$Root` to the transferred frozen `$ArtifactDir` and `$Revision` to the commit identifier in its receipt, then execute:

```powershell
$Sdist = Join-Path $Root 'local_ai_hub-4.0.0.tar.gz'
$Wheel = Join-Path $Root 'local_ai_hub-4.0.0-py3-none-any.whl'
$PythonVersion = '3.13' # Repeat with 3.11, 3.12, and 3.14.
$PythonTag = $PythonVersion.Replace('.', '')
$Launcher = "-$PythonVersion"
$SdistEnv = Join-Path $env:TEMP "t19-$Revision-sdist-py$PythonTag"
$WheelEnv = Join-Path $env:TEMP "t19-$Revision-wheel-py$PythonTag"
$SourceExtract = Join-Path $env:TEMP "t19-$Revision-sdist-source-py$PythonTag"
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber
[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
& py $Launcher --version
Get-FileHash -Algorithm SHA256 $Sdist
Get-FileHash -Algorithm SHA256 $Wheel

& py $Launcher -m venv $SdistEnv
& (Join-Path $SdistEnv 'Scripts\Activate.ps1')
python --version
python -m pip --version
python -m pip install --no-cache-dir "${Sdist}[dev,intel-accelerators,local-nlp,performance,profiling,token-economy]"
python -m pip check
local-ai-hub --help
New-Item -ItemType Directory -Force $SourceExtract | Out-Null
tar -xzf $Sdist -C $SourceExtract
python (Join-Path $SourceExtract 'local_ai_hub-4.0.0\tools\doctor.py') --json
deactivate

& py $Launcher -m venv $WheelEnv
& (Join-Path $WheelEnv 'Scripts\Activate.ps1')
python --version
python -m pip --version
python -m pip install --no-cache-dir $Wheel
python -m pip check
local-ai-hub --help
deactivate
```

Run the Windows block once for each `$PythonVersion` value: `'3.11'`, `'3.12'`, `'3.13'`, and `'3.14'`. It derives separate sdist/wheel environments per version. Treat package builds and install smoke as serial validation: run only under T20's explicit T19 slot assignment. That assignment must also cover any pytest command; never infer authorization from a prior slot release.

## Linux

Run in a clean shell. Set `ROOT` to the transferred frozen `$ArtifactDir` and `T19_REVISION` to the commit identifier in its receipt:

```sh
SDIST="$ROOT/local_ai_hub-4.0.0.tar.gz"
WHEEL="$ROOT/local_ai_hub-4.0.0-py3-none-any.whl"
PYTHON_BIN=python3.13 # Repeat with python3.11, python3.12, and python3.14.
PYTHON_TAG=py313
SDIST_ENV="/tmp/t19-${T19_REVISION}-sdist-$PYTHON_TAG"
WHEEL_ENV="/tmp/t19-${T19_REVISION}-wheel-$PYTHON_TAG"
SOURCE_EXTRACT="/tmp/t19-${T19_REVISION}-sdist-source-$PYTHON_TAG"
cat /etc/os-release
uname -m
"$PYTHON_BIN" --version
sha256sum "$SDIST" "$WHEEL"

"$PYTHON_BIN" -m venv "$SDIST_ENV"
. "$SDIST_ENV/bin/activate"
python --version
python -m pip --version
python -m pip install --no-cache-dir "${SDIST}[dev,intel-accelerators,local-nlp,performance,profiling,token-economy]"
python -m pip check
local-ai-hub --help
mkdir -p "$SOURCE_EXTRACT"
tar -xzf "$SDIST" -C "$SOURCE_EXTRACT"
python "$SOURCE_EXTRACT/local_ai_hub-4.0.0/tools/doctor.py" --json
deactivate

"$PYTHON_BIN" -m venv "$WHEEL_ENV"
. "$WHEEL_ENV/bin/activate"
python --version
python -m pip --version
python -m pip install --no-cache-dir "$WHEEL"
python -m pip check
local-ai-hub --help
deactivate
```

Run the Linux block four times, setting these values before each run: `PYTHON_BIN=python3.11` and `PYTHON_TAG=py311`; `PYTHON_BIN=python3.12` and `PYTHON_TAG=py312`; `PYTHON_BIN=python3.13` and `PYTHON_TAG=py313`; `PYTHON_BIN=python3.14` and `PYTHON_TAG=py314`. It derives separate sdist/wheel environments per version. Treat package builds and install smoke as serial validation: run only under T20's explicit T19 slot assignment. That assignment must also cover any pytest command; never infer authorization from a prior slot release.

## Installer reinstall/uninstall cycle

Clean-host installer lifecycle remains unverified. Use the bounded disposable-VM procedure in [T19 clean-host installer cycle](T19_CLEAN_HOST_INSTALLER_CYCLE.md); do not infer install/reinstall/uninstall or release acceptance from source checks or patch applicability.

## Receipt fields

Create a new receipt per host and artifact under the current frozen candidate's external artifact directory; a v7 template may be consulted for field shape only. Include the exact revision and command, exit code, stdout/stderr artifact paths, OS release, architecture, Python and pip versions, artifact hash, venv path, `pip check` result, CLI help result, and doctor JSON. Record optional components as reported, including unavailable Hub or device services. Do not treat an unavailable live service as an install failure, and do not convert a package install result into model, HTTP, MCP, or release acceptance.

**Historical gate status (2026-10-01):** The v7 receipt template remained `pending_run`. Candidate records showed successful package installs, `pip check`, and CLI help for that v7 pair in fresh Windows virtual environments, plus an sdist install with all six extras. Those results do not establish clean-host acceptance for the current frozen revision. Obtain fresh Windows and Linux receipts for the new artifact pair before closing this gate.

For current replay evidence, require T07/T20 owner receipts bound to the same frozen revision and artifact pair. The v7 `sdk-replay-owner-receipts.json` is historical only; its owner results have different source scopes and do not establish replay acceptance for the current candidate.

## Rollback and recovery

Follow [OPERATIONS.md](OPERATIONS.md#rollback-and-durable-state-recovery) on a disposable host. Stop the service and create a matched `code`/`config`/`state` snapshot with `--covers code config state --service-stopped`. Keep the entire state directory together, including SQLite `-wal` and `-shm` files. Keep the snapshot outside the selected source roots. Do not start the upgraded service unless snapshot creation and digest verification succeed.

For the T08 incompatible-database case, use an isolated copy of a documented prior-version state fixture. Record state-file hashes before the upgrade attempt. Confirm the new release fails closed on the unsupported schema, preserve its post-attempt DB/WAL/SHM files, then restore the matching old code/config/state snapshot with the same root labels. Verify doctor output and durable task/evidence lookups after restore. Never run older code against state written by newer code. Do not perform this scenario against a user's active state directory.

The T08 owner may consult the v7 `rollback-recovery-receipt-template.json` for field shape only. Save a new receipt with the current frozen candidate artifacts. It must bind fixture provenance, old/new source or artifact hashes, snapshot manifest hash, exact commands and exit codes, schema failure evidence, pre/post DB/WAL/SHM hashes, restore result, doctor output, and task/evidence lookup results. Current T19 source tests do not replace this owner-run recovery receipt.

**Historical gate status (2026-10-01; refresh before release):** T08 had not issued a root rollback-recovery receipt. Its recorded prerequisites named owner-approved `append_in_transaction` and ordered event-publication APIs, a receipt-projection helper, cursor-backed event-page and retention behavior, T05-owned migration/backup guards, and T05-owned `agent_memory` writer call sites. Do not treat this historical list as the current T08 blocker; use T08's latest root-bound receipt and T20's frozen acceptance matrix. Require a current root receipt for crash recovery, atomic receipt-write recovery/rollback, ordered publication, event-page snapshot/retention cursor, idempotency/CAS, and scope/cache behavior before closing this gate. Preserve command and log hashes, root HEAD, and changed-file list. Candidate-only T08 passes do not satisfy it.

## MCP adapter and daemon identity mismatch

**Reported 2026-10-03; not independently re-run in this T19 worktree.** A fresh installed-runtime report showed `hubctl status` exit 0 with Hub v4.0.0 online (PID 121388), and `doctor.py` exit 0 with Hub v4.0.0/Python 3.13.2 and compact MCP listing 8 tools. Serena reported healthy while `tools/call` timed out; `local_ai_coord` lease calls returned terminal HTTP 500 with a legacy `_singleflight(request_id)` `TypeError`. OpenVINO was absent, an optional accelerator dependency.

The version string is not a build identity: current T19 `pyproject.toml` and `local_ai_hub.__version__` both report `4.0.0`, with no commit fingerprint in health/status. Current T19 `HubClient._singleflight` accepts `request_id`; that source signature does not explain the reported legacy TypeError. Treat this as an unresolved MCP/daemon loaded-code mismatch. Do not attribute it to a specific process until process paths and artifact fingerprints are captured.

After T04's source-test blocker clears, T20 freezes the revision, and T20 assigns T19 its serial slot, use one bounded update verification: record the exact clean source SHA and wheel/sdist hashes; capture daemon and MCP adapter PID, parent PID, executable, command line, Python executable, loaded `local_ai_hub` module path, and `client.py`/`mcp_server.py` SHA-256 separately; run the installer once with that same `--expected-revision`; then verify `hubctl.py status`, `doctor.py`, MCP `tools/list`, and one `local_ai_coord` claim followed by its release. `tools/setup.py` either installs/reconciles the selected user service or runs one `hubctl.py restart` when `--skip-service` is used; do not issue a second unconditional `service.py restart`. Reload the MCP host separately to replace its stdio adapter. Accept only if both processes resolve to the pinned artifact and the tool call completes without timeout, HTTP 500, or `TypeError`. Stop at the first failure; never auto-replay `outcome_unknown` mutations. Preserve command output and process/artifact fingerprints in the T20-bound receipt.

## Open owners and release gates

- **T03 transport/schema:** provide a revision-bound contract receipt and integrate it with the candidate.
- **T07 replay/idempotency:** resolve failing replay contracts and provide an exact-candidate receipt. The separate-worktree pass does not transfer to v7.
- **T08 recovery:** complete the listed root prerequisites, then provide restart and incompatible-database recovery evidence. The T19 rollback-recovery template remains `pending_run` until T08 issues its receipt.
- **T20 release acceptance:** combine owner receipts on one integrated revision; include clean-host Windows/Linux results and final review.
- **T19 installed MCP/daemon identity:** close the reported v4.0.0 process-skew symptom with separate process fingerprints and one successful bounded tool-call receipt on T20's frozen revision.

Keep v7 candidate-only until those owners close their gates on one frozen revision.
