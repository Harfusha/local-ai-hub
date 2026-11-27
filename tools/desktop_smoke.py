"""Linux/X11 smoke and idle measurement for the actual native desktop binary.

Run under xvfb-run. A temporary empty installation directory prevents service
control or model execution. This measures the desktop process only, not Hub.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time


def main() -> int:
    import psutil

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--idle-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.idle_seconds <= 0:
        parser.error("--idle-seconds must be positive")
    binary = args.binary.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="lah-desktop-smoke-") as temp:
        env = os.environ.copy()
        env.pop("LOCAL_AI_CONFIG", None)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("LOCAL_AI_DESKTOP_PYTHON", None)
        env["LOCAL_AI_HUB_ROOT"] = temp
        started = time.monotonic()
        process = subprocess.Popen([str(binary)], env=env, cwd=temp,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            observed = False
            while time.monotonic() - started < 20:
                if process.poll() is not None:
                    raise RuntimeError(f"Desktop exited before first window: {process.returncode}; "
                                       + process.stderr.read(4000).decode(errors="replace"))
                windows = subprocess.run(["xwininfo", "-root", "-tree"], check=True,
                                         capture_output=True, text=True, timeout=3)
                if '"Local AI Hub"' in windows.stdout:
                    observed = True
                    break
                time.sleep(0.1)
            if not observed:
                raise RuntimeError("No Local AI Hub window observed within smoke deadline; X11 tree: " + windows.stdout[-3000:])
            startup = time.monotonic() - started
            monitored = psutil.Process(process.pid)
            time.sleep(2)
            t0 = time.monotonic()
            cpu0 = monitored.cpu_times()
            rss = []
            while time.monotonic() - t0 < args.idle_seconds:
                if process.poll() is not None:
                    raise RuntimeError("Desktop exited during idle measurement")
                rss.append(monitored.memory_info().rss)
                time.sleep(min(1.0, max(0.01, args.idle_seconds - (time.monotonic() - t0))))
            elapsed = time.monotonic() - t0
            cpu1 = monitored.cpu_times()
            print(json.dumps({
                "method": "Xvfb X11, software OpenGL, Hub absent, desktop process only",
                "platform": platform.platform(), "machine": platform.machine(),
                "glibc": platform.libc_ver(), "first_window_seconds": startup,
                "idle_sample_seconds": elapsed, "idle_rss_mean_bytes": sum(rss) / len(rss),
                "idle_rss_peak_bytes": max(rss),
                "idle_cpu_percent_one_core": 100 * ((cpu1.user + cpu1.system) - (cpu0.user + cpu0.system)) / elapsed,
            }, indent=2))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stderr is not None:
                process.stderr.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
