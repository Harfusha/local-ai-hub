# Installer, update, reinstall, and recovery

## Install or update

Run `install.ps1` on Windows or `./install.sh` on macOS/Linux. In a terminal, setup offers an interactive wizard. Without a terminal, setup uses explicit command-line flags, saved choices, and configuration defaults without waiting for input.

The wizard remembers the last profile and optional-component choices in the per-user installer preferences file. Explicit command-line flags override remembered choices. Re-run the installer to update the managed code; it preserves the installed configuration, Hub state, model cache, and unrelated agent settings.

For each selected agent, choose MCP, skills, and global instructions independently. These choices persist with the other installer preferences.

`setup-report.json` records each agent's selected MCP, skills, and instructions separately from the installation result. Component results are `not_selected`, `configured`, `configured_with_manual_steps`, or `failed_or_partial`; consult `manual_actions` and this guide for unresolved steps.

The wizard chooses the hardware profile, supported model downloads, local NLP, OpenVINO, Laya runtime, Tree-sitter AST support, performance packages, profiling tools, Serena, Token Economy, agent configuration, service registration, and companion skills. OpenVINO detection follows configured backends and Intel NPU/iGPU hardware; AMD or unidentified NPUs do not trigger OpenVINO installation. OpenVINO remains optional and CPU fallback remains available. Laya dependencies are only needed for a selected Laya route; the configured checkpoint is a local, hash-pinned directory and is not downloaded by setup. Developer test dependencies stay out of the service environment.

## Managed automatic updates

`tools/auto_update.py` checks the latest verified stable GitHub release. Without `--apply`, it only reports whether an update is available. Apply only from the managed installation, as the same OS account that owns its service, with the system Python outside `.venv`:

```powershell
py -3 "$HOME\.local-ai-hub\tools\auto_update.py" --apply
```

Replace the example install path when `setup.install_dir` points elsewhere. The updater downloads and verifies the stable release, exact tagged commit, wheel, and CI smoke receipt before preparing dependencies. It then takes the installation lock, stops the managed service, migrates a verified working copy of state, swaps the payload, and checks service readiness. A development Git checkout is never an update target.

On Linux and macOS, restarting the service during an update can wait up to 65 seconds for closed TCP connections to release the loopback port. The wait can also apply when restoring the previous version after a failed update.

After a migration failure, verified backups appear in `backups` in the update report and in `migration.backups` in `setup-report.json`. An empty list means the operation did not report a verified backup.

The updater waits up to 45 minutes for the installer result. If the result remains unconfirmed, review the retained sibling `.<install-name>.auto-update-attempt` directory. It holds the installer log, the staged release and any result the installer writes later. Keep the directory until the installer has finished and the installed version and service state have been verified. Automatic updates stop while the directory is present.

Only one update attempt can prepare an installation and publish its result at a time. If the final report fails to write after the installer ran, review `result.json` and `installer.log` in the retained attempt directory. The dashboard can still show the earlier installing status.

For a maintenance window, schedule that same command under the installation owner's account. In Windows Task Scheduler, create a daily or weekly task at the chosen time; set **Program** to the absolute system Python path from `py -3 -c "import sys; print(sys.executable)"`, **Arguments** to `"C:\Users\USER\.local-ai-hub\tools\auto_update.py" --apply` with the resolved install path, and **Start in** to the installation directory. On Linux, use a systemd **user** service and timer with `ExecStart=/usr/bin/python3 /home/USER/.local-ai-hub/tools/auto_update.py --apply` and the chosen `OnCalendar`; enable lingering if the user manager must run while logged out. On macOS, use a per-user LaunchAgent with `ProgramArguments` containing the absolute system Python path, updater path, and `--apply`, plus `StartCalendarInterval` for the chosen window. Keep each scheduler under the same account as the Hub service. Scheduling is opt-in; the installer does not create these tasks.

If update reports success, verify the active version and service with `.venv/Scripts/python.exe tools/doctor.py` on Windows or `.venv/bin/python tools/doctor.py` on macOS/Linux from the installation directory. If it reports failure, preserve the named recovery directory, verified state backup, and `failed_candidate_state` when present; do not remove or retry over a retained recovery directory until the recorded recovery steps are reviewed. A failed activation attempts to restore the prior code, state, and service. If the result says rollback or service restoration could not be confirmed, leave the Hub stopped and recover using the exact paths in the error and the state backup below.

## Optional Ponytail plugin

When an agent's Skills component is selected, setup deploys the six Ponytail skills alongside Caveman to that agent's supported homes, including detected MultiGravity profile homes. The bundle is based on the MIT-licensed [official Ponytail repository](https://github.com/DietrichGebert/ponytail), version 5.3.3. Set `setup.install_companion_skills = false` or pass `--skip-companion-skills` for one run to omit companion skills; that flag also skips pinned Superpowers for Gemini/Antigravity. This does not install the separate Ponytail plugin or enable lifecycle hooks.

For the full Codex plugin, use only the [official Ponytail repository](https://github.com/DietrichGebert/ponytail):

```powershell
codex plugin marketplace add DietrichGebert/ponytail
codex plugin add ponytail@ponytail
```

Restart Codex, review the plugin's hooks in `/hooks`, and trust them only after review. For Antigravity plugin-manager registration, run `agy plugin install https://github.com/DietrichGebert/ponytail` with each profile active. The Hub skill deployment does not require `agy`.

Ollama remains opt-in. When selected, setup pulls configured role, vision, subagent, and embedding models. Managed llama.cpp downloads its pinned default GGUF when that runtime is selected. A custom GGUF must already exist with a configured SHA-256; external model endpoints own their downloads. Sentence Transformers and OpenVINO preloads follow the configured Hugging Face download policy. `setup-report.json` lists each Ollama model as requested, ready, skipped, or unavailable, plus failed preloads. Setup does not silently change providers or install CUDA, ROCm, DirectML, or vendor drivers.

If newly installed Token Economy commands are not visible, open a new terminal to reload the updated `PATH`.

The wizard also remembers whether setup may download missing Hugging Face embedding and reranker models. That choice applies to installer preloads only; runtime downloads remain governed by `models.allow_hf_downloads` in the installed configuration. Leave it off for cache-only setup.

Supported MCP clients receive deterministic MCP, skills, and generated-instruction setup. Cursor gets an always-on rule in `~/.cursor/rules/local-ai-hub.mdc`; Windsurf gets a concise global rule in `~/.codeium/windsurf/memories/global_rules.md`; VS Code/Copilot gets global instructions in `~/.copilot/copilot-instructions.md` and skills in `~/.copilot/skills`. Cursor and Windsurf use their native skill directory when the shared `~/.agents/skills` location is disabled. Close and reopen the agent after installation. If the Cursor rule path belongs to unrelated content, an agent file cannot be parsed or written, or the Windsurf 6,000-character rule limit is exceeded, inspect `setup-report.json` and finish its manual step below.

## Full reinstall and data deletion

Choose **Provést úplnou reinstalaci a smazat data Hubu** in the wizard, or pass `--full-reinstall`. Setup prints every deletion path and requires typing exactly `DELETE <resolved state directory>` before it stops the service or deletes data.

For non-interactive use, pass both `--non-interactive --full-reinstall` and `--confirm-full-reinstall "DELETE <resolved state directory>"`. The confirmation must match the configured state path exactly. A path through a symlink or junction, the source checkout, the user home, or an unsafe parent path is refused.

Full reinstall removes the managed `.venv`, Hub state directory, Hub-owned model cache, and `tool-envs` used by Serena and other isolated tools. It keeps `config.toml`, agent configuration, and the saved installer choices so setup can recreate the same integration. Provider-owned model stores and third-party agent applications are outside the Hub data directory; remove those through their own supported tools if desired.

## State migrations

Hub state has an explicit integer version. Ordinary startup never edits or deletes data to make a version match. Setup checks the complete migration chain before replacing installed code. Each conversion is one consecutive step (`N` to `N+1`); after the service stops, setup makes and verifies one backup, then runs all steps oldest-first on one staged copy. It advances the marker and verifies after every step, then replaces the original state only after the full chain succeeds. An unregistered step fails preflight without changing state or installed code. A failed conversion leaves the original state and installed payload untouched and reports its verified backup path.

This release has no registered data converters for older state layouts. An older, unknown, corrupt, or newer state version therefore stops safely; do not edit `state_version.json` by hand. Keep the state directory and use a compatible release or ask an AI to inspect the exact error and write a conversion plan. No migration is claimed until a format-specific converter and preservation check exist.

Migration and verification callbacks must close their SQLite connections and other state handles before returning. Windows requires this before setup can rename the staged directory.

On a migration failure, inspect `setup-report.json` for `status: requires_manual_migration`, the failed stage, exact error, and recovery-guide path. Keep the original state unchanged. For retired tenant-state conversion only, `python tools/convert_single_owner_state.py <source-file-or-database>` prints a dry plan; it does not modify the source. That tool supports only its documented formats and requires a separate output plus explicit collision/archive manifests to apply. It is not a general release-version migrator. Do not run `--apply` without reviewing the plan and preserving the original.

## Automatic updates

Install a release that ships `tools/auto_update.py` using the regular installer before enabling scheduled updates. The target must have a valid install ownership marker, regular `config.toml`, managed `.venv`, and versioned state. Keep the installation in a separate directory from your Git checkout. Use Git and system Python 3.11 or newer under the installation owner's account.

The local dashboard's **Updates** button shows verified release availability. Choose **Review update**, confirm that Hub can restart, and choose **Install and restart**. The updater rechecks the displayed version and commit before applying it. It runs as a separate user task through Task Scheduler, user systemd, or launchd. The dashboard reads `auto-update-dashboard.json` after reconnecting.

Run `python -I -B <install-dir>/tools/auto_update.py` to check for a newer stable GitHub release. Add `--apply` to install it. The updater verifies the official release's wheel, smoke receipt and source commit, stages core dependencies, then stops the Hub for the payload swap and offline migrations. It keeps the installed configuration and restores the prior environment and state if activation fails and the candidate can be stopped. A service that was disabled stays disabled. The update can temporarily need disk space for another copy of the runtime and state.

To enable automatic updates, schedule the `--apply` command for your maintenance window. Use absolute paths to **system Python** and the installed script. Run under the same user who installed the Hub.

| Platform | Schedule |
| --- | --- |
| Windows | In Task Scheduler, create a task for your account. Set the trigger to your maintenance window. Set **Program/script** to the absolute `python.exe` path and **Arguments** to `-I -B "C:\path\to\install\tools\auto_update.py" --apply`. Set **If the task is already running** to **Do not start a new instance**. |
| Linux | In a user `systemd` service with `Type=oneshot`, set `ExecStart=/absolute/path/to/python3 -I -B /absolute/install/tools/auto_update.py --apply`. Create a timer of the same name with `OnCalendar` set to the maintenance window and enable it with `systemctl --user enable --now <name>.timer`. |
| macOS | In a user LaunchAgent, set `ProgramArguments` to the absolute `python3` path, `-I`, `-B`, the installed script path, and `--apply`. Set `StartCalendarInterval` to the maintenance window and load the agent with `launchctl bootstrap gui/$(id -u) <absolute-plist-path>`. |

Scheduled runs write `auto-update-report.json` in the install directory. On failure, inspect its message, state backup paths, and `recovery_directory`, if present. A retained `.<install-name>.auto-update-recovery` directory blocks another update. Its `update.json` records the install, state, and prior version. If rollback stops partway, preserve that directory, `.<install-name>.update-stage-*` beside the installation, and `*.backup-v*` beside the state. Restore matching code, environment and state while the service is confirmed stopped before clearing the recovery directory. A `.*.failed-update-*` directory contains candidate state preserved during rollback.

## Publish a stable release

On GitHub, run **Prepare stable release** on `master` and select `patch`, `minor`, or `major`. The workflow calculates the SemVer, updates the version metadata, README and changelog in a release commit, pushes its tag, and dispatches CI on that tag. The existing package build and smoke checks gate publication. If CI or publication needs retrying, run CI again for the same tag. The release commit is reachable from its tag. `master` remains the development branch.

## Manual setup guide

- If bootstrap cannot install or find Python 3.11+ with `venv`, install a supported Python from the operating system's package source, confirm the chosen interpreter is at least Python 3.11 and that `<python> -m venv --help` works, then rerun `install.ps1` or `./install.sh`. On Debian/Ubuntu, setup prefers an available versioned `python3.14` through `python3.11` package with its matching `venv` package before falling back to the distribution's default `python3`.
- Intel llama.cpp SYCL generation: [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md).
- If the managed llama.cpp runtime or its configured model is unavailable, keep the current provider selected, inspect `[llama_cpp]` and model settings in `config.toml`, then run `python tools/doctor.py` and follow [INSTALLATION.md](INSTALLATION.md) or [LLAMA_CPP_SYCL.md](LLAMA_CPP_SYCL.md) for the selected route. Do not substitute another provider to make setup appear successful.
- Laya inference requires the optional `laya-runtime` packages and an existing absolute checkpoint directory whose name matches the configured revision. Its `expected_sha256` map must cover the checkpoint files. Setup checks for the directory and installs the packages when selected, but does not download or trust an unpinned checkpoint. Use the checkpoint's approved source to obtain it, then verify the configured hashes before enabling inference.
- The `native` extra supplies Cython only. Setup does not compile or install the experimental SimHash extension into the Hub runtime. For the isolated experiment, use `tools/cython_experiment.py --help`, select a work directory outside the source checkout, and provide the requested build-output path; a platform compiler must already be installed.
- Optional runtime requirements and provider limits: [INSTALLATION.md](INSTALLATION.md).
- Configuration and model routes: [CONFIGURATION.md](CONFIGURATION.md) and [MODEL_CAPABILITIES.md](MODEL_CAPABILITIES.md).
- Cursor rule and skill formats: [Rules](https://prod.cursor.com/docs/rules) and [Agent Skills](https://prod.cursor.com/docs/skills).
- Windsurf global rules and skill formats: [Memories & Rules](https://docs.windsurf.com/de/windsurf/cascade/memories) and [Skills](https://docs.windsurf.com/de/windsurf/cascade/skills).
- VS Code/Copilot user instruction and skill locations: [Copilot customization source specification](https://github.com/microsoft/vscode/blob/main/src/vs/sessions/copilot-customizations-spec.md).
- Host-specific MCP setup: inspect the client’s supported MCP configuration format; do not replace unrelated entries.

If setup reports a manual step, copy this prompt to an AI assistant:

```text
Finish the Local AI Hub installer step that setup could not automate.
Read docs/INSTALLER_RECOVERY.md and follow its safety rules. Inspect the exact
installer report and error first. Do not change the configured model provider,
delete Hub state, replace unrelated agent settings, or install drivers without
my explicit approval. Give me a deterministic command or exact UI steps, run
only reversible checks, and report what remains unverified.
```
