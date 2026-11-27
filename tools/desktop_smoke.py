"""Linux/X11 native desktop smoke and resource measurements.

Offline mode uses an empty installation. Online mode runs a real isolated Hub
with inference, preprocessing and observability disabled; no production state.
The measured process is the Rust desktop, including its normal health probes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen


@contextmanager
def isolated_hub(temp: Path):
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    observed_ready = threading.Event()

    class SmokeHandler(http_server.Handler):
        def do_GET(self):
            super().do_GET()
            if self.path == "/ready":
                observed_ready.set()

    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), SmokeHandler)
    app = None
    thread = None
    original_app = http_server.APP
    config = temp / "isolated.toml"
    port = server.server_address[1]
    ready_url = f"http://127.0.0.1:{port}/ready"
    try:
        config.write_text(
            "[local_ai_hub]\nconfig_schema_version = 1\n[server]\n"
            + "port = " + str(port) + "\n"
            + "state_dir = " + json.dumps(str(temp / "state"))
            + "\nauto_start_ollama = false\n[ollama]\nenabled = false\n[smart_ollama]\nenabled = false"
            + "\n[observability]\nenabled = false\n[background_gpu]\nenabled = false"
            + "\n[preprocessing]\nenabled = false\n",
            encoding="utf-8",
        )
        app = LocalAIApp(str(config))
        http_server.APP = app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with urlopen(ready_url, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("Isolated Hub is not ready")
            response.read()
        # Wait for the handler to finish the initial request before clearing it;
        # the next observed request must come from the actual desktop adapter.
        if not observed_ready.wait(timeout=5):
            raise RuntimeError("Initial readiness request was not observed")
        observed_ready.clear()
        yield config, observed_ready, ready_url
    finally:
        if thread is not None:
            server.shutdown()
            thread.join(timeout=5)
        server.server_close()
        if app is not None:
            app.close()
        http_server.APP = original_app


def measure(binary: Path, temp: Path, env: dict[str, str], idle_seconds: float,
            *, online=None) -> dict:
    import psutil

    started = time.monotonic()
    with (temp / "desktop-stderr.log").open("w+b") as errors:
        process = subprocess.Popen([str(binary)], env=env, cwd=temp,
                                   stdout=subprocess.DEVNULL, stderr=errors)
        try:
            window_id = None
            tree = ""
            while time.monotonic() - started < 20:
                if process.poll() is not None:
                    errors.seek(0)
                    raise RuntimeError(f"Desktop exited before first window: {process.returncode}; "
                                       + errors.read(4000).decode(errors="replace"))
                windows = subprocess.run(["xwininfo", "-root", "-tree"], check=True,
                                         capture_output=True, text=True, timeout=3)
                tree = windows.stdout
                match = re.search(r'(0x[0-9a-fA-F]+)\s+"Local AI Hub"', tree)
                if match:
                    window_id = match.group(1)
                    break
                time.sleep(0.1)
            if window_id is None:
                raise RuntimeError("No Local AI Hub window observed within smoke deadline; X11 tree: " + tree[-3000:])
            startup = time.monotonic() - started
            # Explicitly focus the window so its normal 30-second health probe
            # is exercised under Xvfb, which has no window manager.
            subprocess.run(["xdotool", "windowfocus", "--sync", window_id], check=True, timeout=5)
            first_ready = None
            if online is not None:
                _, observed_ready, _ = online
                if not observed_ready.wait(timeout=15):
                    raise RuntimeError("Real desktop adapter did not reach isolated Hub readiness")
                first_ready = time.monotonic() - started
            monitored = psutil.Process(process.pid)
            time.sleep(2)
            t0 = time.monotonic()
            cpu0 = monitored.cpu_times()
            rss = []
            adapter_cpu = 0.0
            adapter_rss_peak = 0
            child_cpu: dict[tuple[int, float], float] = {}
            while time.monotonic() - t0 < idle_seconds:
                if process.poll() is not None:
                    raise RuntimeError("Desktop exited during idle measurement")
                rss.append(monitored.memory_info().rss)
                live_child_rss = 0
                # Sample transient bridge children separately. This is a lower
                # bound on their CPU because short-lived processes can exit
                # between samples; do not add it to exact desktop CPU.
                for child in monitored.children(recursive=True):
                    try:
                        identity = (child.pid, child.create_time())
                        cpu = child.cpu_times()
                        now_cpu = cpu.user + cpu.system
                        adapter_cpu += max(0.0, now_cpu - child_cpu.get(identity, 0.0))
                        child_cpu[identity] = now_cpu
                        live_child_rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                adapter_rss_peak = max(adapter_rss_peak, live_child_rss)
                time.sleep(min(0.1, max(0.01, idle_seconds - (time.monotonic() - t0))))
            elapsed = time.monotonic() - t0
            cpu1 = monitored.cpu_times()
            report = {
                "method": "Xvfb X11, software OpenGL, " + ("isolated real Hub online" if online else "Hub absent"),
                "platform": platform.platform(), "machine": platform.machine(),
                "glibc": platform.libc_ver(), "first_window_seconds": startup,
                "first_adapter_ready_request_seconds": first_ready,
                "idle_sample_seconds": elapsed, "idle_rss_mean_bytes": sum(rss) / len(rss),
                "idle_rss_peak_bytes": max(rss),
                "idle_cpu_percent_one_core": 100 * ((cpu1.user + cpu1.system) - (cpu0.user + cpu0.system)) / elapsed,
                "sampled_bridge_children_cpu_seconds_lower_bound": adapter_cpu,
                "sampled_bridge_children_rss_peak_bytes_lower_bound": adapter_rss_peak,
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if online is not None:
            with urlopen(online[2], timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError("Hub stopped when desktop process exited")
                response.read()
            report["hub_ready_after_desktop_exit"] = True
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--idle-seconds", type=float, default=60.0)
    parser.add_argument("--online-hub-root", type=Path)
    args = parser.parse_args()
    if args.idle_seconds <= 0:
        parser.error("--idle-seconds must be positive")
    binary = args.binary.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="lah-desktop-smoke-") as directory:
        temp = Path(directory)
        env = os.environ.copy()
        env.pop("LOCAL_AI_CONFIG", None)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("LOCAL_AI_DESKTOP_PYTHON", None)
        env["LOCAL_AI_HUB_ROOT"] = directory
        if args.online_hub_root is not None:
            root = args.online_hub_root.resolve(strict=True)
            if not (root / "tools" / "desktop.py").is_file():
                parser.error("--online-hub-root must be a trusted Hub checkout")
            with isolated_hub(temp) as online:
                env["LOCAL_AI_HUB_ROOT"] = str(root)
                env["LOCAL_AI_DESKTOP_PYTHON"] = sys.executable
                env["LOCAL_AI_CONFIG"] = str(online[0])
                report = measure(binary, temp, env, args.idle_seconds, online=online)
        else:
            report = measure(binary, temp, env, args.idle_seconds)
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
