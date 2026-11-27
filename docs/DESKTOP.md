# Native Local AI Hub desktop

The Rust/egui desktop is a separate local operator application. The Hub continues to provide the existing Python service, HTTP and MCP APIs. Closing the desktop does not stop the Hub; use explicit Start, Stop or Restart controls. Reads never start the Hub implicitly.

## Build and launch

Install stable Rust and the platform OpenGL development/runtime libraries. On Ubuntu 22.04 CI installs libgl1-mesa-dev, libxkbcommon-dev, libxkbcommon-x11-0, libxkbcommon-x11-dev, libwayland-dev, libx11-dev, libxi-dev, libxcursor-dev and libxrandr-dev. Linux X11 installations also require the XKB X11 runtime (`libxkbcommon-x11-0` on Debian/Ubuntu) and working OpenGL/EGL drivers. Windows and macOS use the native platform renderer.

```sh
cargo build --manifest-path desktop/Cargo.toml --release
python tools/hubctl.py desktop
```

The previous `dashboard` CLI alias opens the same application. No web dashboard is served. A stopped Hub can be started from the desktop. Configure the existing Hub installation and Python executable in the app if automatic discovery is unsuitable.

## Portable build

The Native desktop CI workflow produces platform-specific binary artifacts and a portable ZIP with a SHA-256 manifest. Verify the archive and install the binary with `tools/install_desktop.py` using its documented required arguments (`python tools/install_desktop.py --help`). Installation changes only the desktop executable; the existing service remains separate. These are unsigned portable builds, not OS-native signed installers.

## Operation and privacy

Select a repository for scoped operations. Refresh views explicitly; focus-only health probes and optional bounded event follow avoid resident polling. Mutations use named, validated operations and confirmation. Detailed traces may contain locally stored sensitive material; the default trace presentation redacts credential-shaped fields and explicit raw display can expose the original record. Never share raw diagnostic output inadvertently.

## Changes & commits

Select a repository root and open **Changes & commits** for summary, details, local-model advisory commit messages, PR and release comparisons. Page through groups with the observed revision; after edits refresh the plan. This surface is read-only: it cannot stage or commit. See [Git Change Intelligence](GIT_CHANGE_INTELLIGENCE.md).

## Release status

The current PR is a draft. See [parity and evidence](DESKTOP_PARITY.md) for gaps and verification requirements. Passing builds do not establish complete behavioral parity.

### Reviewed Git transactions

Changes & commits also exposes local staging preview, confirmed staging apply, confirmed exact staged-tree commit and read-only recovery list/inspection. Supply explicit paths, hunk IDs if needed, observed revision and preview tree. Re-observe after staging. Sequence verification and publication remain CLI operations. No browser dashboard or arbitrary command bridge is introduced.
