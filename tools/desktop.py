"""Native, source-checkout desktop control surface (incremental parity migration)."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.client import HubClient
from local_ai_hub.process_utils import hidden_run_kwargs

LIFECYCLE = frozenset({"start", "stop", "restart"})
MODES = ("active", "gaming", "maintenance", "preprocessing")
VIEWS = {
    "Overview": "/api/live/status?light=1&scope=process",
    "Projects": "/api/preprocess/status",
    "Tasks": "/api/agent-state/tasks?limit=100",
    "Memory": "/api/agent-state/memory",
    "Incidents": "/api/agent-state/incidents",
    "Activity": "/api/live?limit=50",
    "Service health": "/api/logs/tail?lines=250",
    "Diagnostics": "/api/doctor",
}
SCOPED = frozenset({"Tasks", "Memory", "Incidents"})


class HubControl:
    """Explicit, bounded operations only. Reads must never start the service."""

    def __init__(self, config: str | None = None) -> None:
        self.config = config

    def _client(self) -> HubClient:
        return HubClient(config_path=self.config, auto_start=False)

    def online(self) -> bool:
        client = self._client()
        try:
            return client._online(timeout=2.0)
        finally:
            client.close()

    def _cli(self, args: tuple[str, ...], timeout: float) -> str:
        env = os.environ.copy()
        if self.config is not None:
            env["LOCAL_AI_CONFIG"] = self.config
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "hubctl.py"), *args],
            cwd=ROOT, env=env, timeout=timeout, check=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            **hidden_run_kwargs(),
        )
        if completed.returncode:
            raise RuntimeError(
                f"Hub command failed (exit {completed.returncode}): "
                + (completed.stderr.strip() or completed.stdout.strip())[-4000:]
            )
        return completed.stdout.strip()

    def lifecycle(self, action: str) -> str:
        if action not in LIFECYCLE:
            raise ValueError("Unsupported lifecycle action")
        if action == "start" and self.online():
            return "Hub is already online."
        if action == "stop" and not self.online():
            # Still call the CLI: a managed supervisor may be warming up.
            pass
        return self._cli((action,), timeout=760)

    def mode(self, value: str) -> str:
        if value not in MODES:
            raise ValueError("Unsupported activity mode")
        return self._cli(("mode", value), timeout=30)

    def read(self, view: str, root: str = "") -> dict[str, Any]:
        path = VIEWS[view]
        if view in SCOPED:
            if not root.strip():
                raise ValueError("Select an explicit repository root first.")
            root_path = Path(root).expanduser().resolve(strict=True)
            if not root_path.is_dir():
                raise ValueError("Repository root must be a directory.")
            path += ("&" if "?" in path else "?") + urlencode({"root": str(root_path)})
        client = self._client()
        try:
            if not client._online(timeout=2.0):
                raise RuntimeError("Hub is not reachable. Use Start Hub if it is stopped.")
            data = client.get(path, timeout=15.0, requires_heavy_work=False)
            if data.get("success") is False:
                raise RuntimeError(str(data.get("error") or "Hub request failed"))
            return data
        finally:
            client.close()


class Desktop:
    """Tk event loop owns all widgets; one background operation at a time."""

    def __init__(self, window: tk.Tk, control: HubControl) -> None:
        self.window, self.control = window, control
        self.results: queue.Queue[tuple[str, Any, Exception | None]] = queue.Queue()
        self.busy = False
        self.closing = False
        self.online: bool | None = None
        self.view = "Overview"
        window.title("Local AI Hub — Desktop")
        window.geometry("1050x690")
        window.minsize(760, 480)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.columnconfigure(1, weight=1)
        window.rowconfigure(2, weight=1)
        self.state = tk.StringVar(value="Hub: checking…")
        self.notice = tk.StringVar(value="Desktop running.")
        toolbar = ttk.Frame(window, padding=12)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(toolbar, textvariable=self.state).pack(side="left", padx=(0, 16))
        self.buttons: list[ttk.Button] = []
        for action in ("start", "stop", "restart"):
            button = ttk.Button(toolbar, text=action.title() + " Hub",
                                command=lambda a=action: self.lifecycle(a))
            button.pack(side="left", padx=3)
            self.buttons.append(button)
        ttk.Label(toolbar, text="Activity mode").pack(side="left", padx=(18, 4))
        self.mode = tk.StringVar(value=MODES[0])
        ttk.Combobox(toolbar, textvariable=self.mode, values=MODES,
                     state="readonly", width=15).pack(side="left")
        button = ttk.Button(toolbar, text="Apply mode", command=self.apply_mode)
        button.pack(side="left", padx=4)
        self.buttons.append(button)

        filters = ttk.Frame(window, padding=(12, 0, 12, 8))
        filters.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Label(filters, text="Repository root (for scoped views)").pack(side="left")
        self.root = tk.StringVar()
        ttk.Entry(filters, textvariable=self.root).pack(side="left", fill="x", expand=True, padx=8)
        button = ttk.Button(filters, text="Refresh view", command=self.refresh)
        button.pack(side="right")
        self.buttons.append(button)

        nav = ttk.Frame(window, padding=(12, 0, 8, 12))
        nav.grid(row=2, column=0, sticky="ns")
        self.nav = tk.Listbox(nav, exportselection=False, width=22, height=12)
        for view in VIEWS:
            self.nav.insert("end", view)
        self.nav.selection_set(0)
        self.nav.pack(fill="both", expand=True)
        self.nav.bind("<<ListboxSelect>>", self.select)
        panel = ttk.Frame(window, padding=(0, 0, 12, 12))
        panel.grid(row=2, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        self.title = ttk.Label(panel, text=self.view, font=("TkDefaultFont", 16))
        self.title.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.output = tk.Text(panel, wrap="none", state="disabled", undo=False)
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.output.yview)
        horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.output.xview)
        self.output.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.output.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        ttk.Label(window, textvariable=self.notice, padding=8).grid(
            row=3, column=0, columnspan=2, sticky="ew")
        self.write("Select a view and refresh. Start Hub if the service is not reachable.")
        window.after(50, self.drain)
        window.after(100, self.probe)

    def write(self, value: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", value)
        self.output.configure(state="disabled")

    def select(self, _event: object = None) -> None:
        selection = self.nav.curselection()
        if not selection:
            return
        self.view = tuple(VIEWS)[selection[0]]
        self.title.configure(text=self.view)
        self.write("Refresh to load this view.")
        if not self.busy:
            self.refresh()

    def submit(self, kind: str, work: Callable[[], Any]) -> None:
        if self.busy or self.closing:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")
        if kind != "probe":
            self.notice.set(f"{kind}: running…")

        def run() -> None:
            try:
                self.results.put((kind, work(), None))
            except Exception as exc:
                self.results.put((kind, None, exc))

        # Closing the window does not stop the service or cancel a lifecycle command.
        threading.Thread(target=run, daemon=True).start()

    def probe(self) -> None:
        if not self.busy:
            self.submit("probe", self.control.online)
        if not self.closing:
            self.window.after(5000, self.probe)

    def refresh(self) -> None:
        view, root = self.view, self.root.get()
        self.submit("view:" + view, lambda: self.control.read(view, root))

    def lifecycle(self, action: str) -> None:
        if action != "start" and not messagebox.askyesno(
            "Confirm service operation", f"{action.title()} Hub? Active requests may be interrupted.",
            parent=self.window,
        ):
            return
        self.submit(action, lambda: self.control.lifecycle(action))

    def apply_mode(self) -> None:
        value = self.mode.get()
        if messagebox.askyesno("Confirm mode", f"Switch Hub activity mode to {value}?",
                               parent=self.window):
            self.submit("mode", lambda: self.control.mode(value))

    def drain(self) -> None:
        try:
            kind, value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons:
                button.configure(state="normal")
            if kind == "probe":
                self.online = None if error else bool(value)
                label = "unknown (check configuration)" if error else (
                    "online" if value else "unreachable / stopped")
                self.state.set("Hub: " + label)
            elif error:
                self.notice.set(f"{kind}: failed — {error}")
                if kind == "view:" + self.view:
                    self.write(f"Unable to load view: {error}")
            elif kind.startswith("view:"):
                if kind == "view:" + self.view:
                    if self.view == "Service health" and isinstance(value.get("lines"), list):
                        output = "\n".join(map(str, value["lines"]))
                    else:
                        output = json.dumps(value, indent=2, ensure_ascii=False)
                    self.write(output[:250_000] + ("\n[Display truncated; use CLI for full data.]" if len(output) > 250_000 else ""))
                self.notice.set(f"{kind}: loaded")
            else:
                self.notice.set(f"{kind}: {value or 'completed'}")
            if kind in LIFECYCLE:
                self.online = None
                self.state.set("Hub: checking after operation…")
                self.submit("probe", self.control.online)
        if not self.closing:
            self.window.after(100, self.drain)

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo("Operation running",
                                "Finish the current operation before closing.", parent=self.window)
            return
        self.closing = True
        self.window.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("LOCAL_AI_CONFIG"))
    args = parser.parse_args()
    config = str(Path(args.config).expanduser().resolve()) if args.config else None
    window = tk.Tk()
    Desktop(window, HubControl(config))
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
