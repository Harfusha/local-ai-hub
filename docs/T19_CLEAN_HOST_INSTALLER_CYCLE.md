# T19 clean-host installer cycle

**Status: NOT RUN.** This procedure is future acceptance, not evidence of install, reinstall, uninstall, or release success. Run only after T20 freezes the post-integration source revision, clears the T04 source-test blocker, and explicitly assigns T19 a serial clean-host slot for that exact revision; a prior slot release alone does not authorize a run. The installer requires a clean Git checkout because `--expected-revision` verifies `HEAD` and the complete porcelain status; an unpacked sdist is not a valid installer input. The v7 artifacts in `T19_RELEASE_VALIDATION_RUNBOOK.md` predate T19 edits. This cycle covers install/reinstall/uninstall at one revision; cross-version update needs a T20-selected baseline revision and separate receipt.

## Safety boundary

- Use a disposable snapshot VM and new local account with no synced profile, vault, personal configuration, or durable Hub state. The installer configures agent files in that account; uninstall removes Hub-managed entries and skills there.
- Exactly one selected Python 3.11+ interpreter must be available to the bootstrap script. Stop if it would install Python or if the scratch path already exists.
- Allow outbound traffic only to the configured Python package index. Keep external Hub, Ollama, and model registries unreachable. Skip model pulls, optional tools/runtimes, and service registration. `--skip-service` still runs setup's local `hubctl restart` path; capture it and stop if it reaches external providers.
- Set `setup.install_dir` and `server.state_dir` under a unique scratch root. Preserve that root and the receipts; run no recursive cleanup.

## Windows PowerShell

Set `$SourceRoot` to a transferred disposable Git checkout of the frozen revision, `$Revision` to its verified 40-character SHA, and `$PythonVersion` to the only registered Python version on this disposable VM. Keep the `.git` metadata with the checkout; package artifact hash/install checks belong to `T19_RELEASE_VALIDATION_RUNBOOK.md`.

```powershell
$PythonVersion = '3.13'
$Lab = Join-Path $env:TEMP "t19-installer-cycle-py$($PythonVersion.Replace('.', ''))"
if (Test-Path $Lab) { throw 'Scratch exists; choose a fresh VM or unique path.' }
$Source = (Resolve-Path -LiteralPath $SourceRoot).Path
$ActualRevision = (& git -C $Source rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $ActualRevision -ine $Revision) { throw 'Source checkout does not match the frozen revision.' }
$SourceStatus = & git -C $Source status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0 -or $SourceStatus) { throw 'Source checkout is not clean.' }
$Install = Join-Path $Lab 'install'
$State = Join-Path $Lab 'state'
Copy-Item (Join-Path $Source 'config.toml.example') (Join-Path $Source 'config.toml')
$InstallToml = $Install.Replace('\', '/')
$StateToml = $State.Replace('\', '/')
Add-Content (Join-Path $Source 'config.toml') -Encoding utf8 -Value "`n[setup]`ninstall_dir = `"$InstallToml`"`n`n[server]`nstate_dir = `"$StateToml`"`nport = 11435`n"
Push-Location $Source
try {
  $Flags = @('-ExpectedRevision',$Revision,'-Profile','integrated','-SkipModelPull','-SkipTools','-SkipService','-SkipOllamaInstall','-SkipLocalNlpPreload','-SkipTokenEconomy','-SkipCompanionSkills')
  & (Join-Path $Source 'install.ps1') @Flags
  if ($LASTEXITCODE -ne 0) { throw "install failed: $LASTEXITCODE" }
  $Config = Join-Path $Install 'config.toml'; $Before = (Get-FileHash $Config).Hash
  & (Join-Path $Install '.venv\Scripts\local-ai-hub.exe') --help
  if ($LASTEXITCODE -ne 0) { throw "CLI failed: $LASTEXITCODE" }
  & (Join-Path $Source 'install.ps1') @Flags
  if ($LASTEXITCODE -ne 0) { throw "reinstall failed: $LASTEXITCODE" }
  if ((Get-FileHash $Config).Hash -ne $Before) { throw 'reinstall changed installed config' }
  New-Item -ItemType Directory -Path $State | Out-Null
  Set-Content (Join-Path $State 'preserve.marker') 'keep' -NoNewline
  & py "-$PythonVersion" (Join-Path $Source 'tools\uninstall.py')
  if ($LASTEXITCODE -ne 0) { throw "uninstall failed: $LASTEXITCODE" }
  if (Test-Path $Install) { throw 'install tree remains' }
  if (-not (Test-Path (Join-Path $State 'preserve.marker'))) { throw 'external state was removed' }
} finally { Pop-Location }
```

## Linux shell

Set `T19_SOURCE_ROOT` to a transferred disposable Git checkout of the frozen revision and `T19_REVISION` to its verified 40-character SHA. Keep `.git` metadata with the checkout. The selected Python must be the only Python 3.11+ executable available to `install.sh` on this VM; package artifact hash/install checks belong to `T19_RELEASE_VALIDATION_RUNBOOK.md`.

```sh
PYTHON_BIN=python3.13
PYTHON_TAG=py313
LAB="$(mktemp -d "/tmp/t19-installer-cycle-$PYTHON_TAG.XXXXXX")"
SOURCE=$(cd "$T19_SOURCE_ROOT" && pwd)
REVISION="$T19_REVISION"
ACTUAL_REVISION=$(git -C "$SOURCE" rev-parse --verify HEAD)
test "$ACTUAL_REVISION" = "$REVISION" || { echo 'Source checkout does not match frozen revision.' >&2; exit 2; }
test -z "$(git -C "$SOURCE" status --porcelain=v1 --untracked-files=all)" || { echo 'Source checkout is not clean.' >&2; exit 2; }
INSTALL="$LAB/install"
STATE="$LAB/state"
"$PYTHON_BIN" --version
cp "$SOURCE/config.toml.example" "$SOURCE/config.toml"
cat >> "$SOURCE/config.toml" <<EOF

[setup]
install_dir = "$INSTALL"
[server]
state_dir = "$STATE"
port = 11435
EOF
cd "$SOURCE"
FLAGS="--expected-revision $REVISION --profile integrated --skip-model-pull --skip-tools --skip-service --skip-ollama-install --skip-local-nlp-preload --skip-token-economy --skip-companion-skills"
./install.sh $FLAGS
CONFIG="$INSTALL/config.toml"; BEFORE=$(sha256sum "$CONFIG" | cut -d ' ' -f 1)
"$INSTALL/.venv/bin/local-ai-hub" --help
./install.sh $FLAGS
AFTER=$(sha256sum "$CONFIG" | cut -d ' ' -f 1); test "$BEFORE" = "$AFTER"
mkdir -p "$STATE"; printf 'keep' > "$STATE/preserve.marker"
"$PYTHON_BIN" "$SOURCE/tools/uninstall.py"
test ! -e "$INSTALL"; test -f "$STATE/preserve.marker"
```

## Cross-version upgrade acceptance

The Windows and Linux snippets above cover first install, same-version reinstall, and uninstall only. Cross-version acceptance requires T20-selected baseline and target revisions, separate clean Git checkouts with verified 40-character SHAs, and revision-bound package hashes. Install the baseline into a fresh scratch install/state pair, record version and config/state hashes, then run the target installer with its matching expected revision against that same pair. Require target version, unchanged user config, and surviving durable state marker. Verify target uninstall preserves external state. Persistent service registration/restart needs a separate receipt. Use only the OS/Python combination assigned by T20; package artifact checks remain in T19_RELEASE_VALIDATION_RUNBOOK.md.

Run one OS/Python combination per disposable VM with a fresh scratch path, only within the exact combination authorized by T20's serial slot. Request another assignment before validating another combination. Record artifact hash, exact commands and exit codes, CLI output, pre/post config hashes, install-tree removal, and survival of the external state marker. One passing cycle covers only that combination. T20 must record Windows and Linux receipts on the integrated candidate before this gate closes.
