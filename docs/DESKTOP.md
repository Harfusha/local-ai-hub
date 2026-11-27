# Native Local AI Hub desktop

The Rust/egui desktop is a separate local operator application. The Hub continues to provide the existing Python service, HTTP and MCP APIs. Closing the desktop does not stop the Hub; use explicit Start, Stop or Restart controls. Reads never start the Hub implicitly.

## Build and launch

Install stable Rust and the platform OpenGL development/runtime libraries. On Ubuntu 22.04 CI installs libgl1-mesa-dev, libxkbcommon-dev, libxkbcommon-x11-0, libxkbcommon-x11-dev, libwayland-dev, libx11-dev, libxi-dev, libxcursor-dev and libxrandr-dev. Linux X11 installations also require the XKB X11 runtime (`libxkbcommon-x11-0` on Debian/Ubuntu) and working OpenGL/EGL drivers. Windows and macOS use the native platform renderer.

```sh
cargo build --manifest-path desktop/Cargo.toml --release --locked
python tools/hubctl.py desktop
```

The previous `dashboard` CLI alias opens the same application. No web dashboard is served. A stopped Hub can be started from the desktop. Configure the existing Hub installation and Python executable in the app if automatic discovery is unsuitable.

## Portable build

The Native desktop CI workflow builds locked Rust dependencies and produces portable ZIPs for Linux x64, Windows x64, macOS Intel and macOS Apple Silicon. Stable tagged release publication is gated on native builds/tests and exact version/revision, platform and SHA-256 receipts. Verify the archive and install the binary with `tools/install_desktop.py` using its documented required arguments (`python tools/install_desktop.py --help`). Installation changes only the desktop executable; the existing service remains separate. These are unsigned portable builds, not OS-native signed installers. Verified release installation and update use version-specific binary paths. For headless installs use `tools/setup.py --skip-desktop`; the `.desktop-disabled` marker prevents subsequent automatic downloads. To opt back in, remove this marker from the trusted installation and install the verified release asset manually. The previous desktop process is not overwritten while running. A failed desktop download does not invalidate a successful independent service update; consult the desktop result in the update report.

## Operation and privacy

Select a repository for scoped operations. Settings → Operator tools exposes a typed CLI operation catalog for knowledge, handoffs, client setup, generation, inventory and maintenance. Reads are bounded and do not implicitly start the Hub. Compression can be staged but in-place application remains CLI-only until it can apply the exact reviewed artifact. Trace detail supports event cursors, metrics, content pages and server-redacted export. Refresh views explicitly; focus-only health probes and optional bounded event follow avoid resident polling. Mutations use named, validated operations and confirmation. Detailed traces may contain locally stored sensitive material; the default trace presentation redacts credential-shaped fields and explicit raw display can expose the original record. Never share raw diagnostic output inadvertently.

## Release status

The current PR is a draft. See [parity and evidence](DESKTOP_PARITY.md) for gaps and verification requirements. Passing builds do not establish complete behavioral parity.
