"""Pinned, state-scoped llama.cpp runtime installer and process manager."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .process_utils import hidden_run_kwargs, pid_alive, process_executable, terminate_tree

LLAMA_VERSION = "b10964"
MODEL_REVISION = "38f6bab61d341b23a6c00226f32c0d6148bf9f43"
MODEL_FILENAME = "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
MODEL_SHA256 = "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046"
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/"
    f"{MODEL_REVISION}/{MODEL_FILENAME}?download=true"
)
MAX_MODEL_BYTES = 2_000_000_000
MAX_RUNTIME_BYTES = 2_000_000_000
MAX_EXTRACTED_BYTES = 8_000_000_000

# Digests are from the official ggml-org/llama.cpp GitHub build attestation
# for b10964 (attestation 47376843).
RUNTIME_ASSETS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("win32", "amd64"): ("llama-b10964-bin-win-cpu-x64.zip", "917f39c076402c421224824607397af20f53625a60defc20e8dd22446bf4c5d7", "zip"),
    ("win32", "arm64"): ("llama-b10964-bin-win-cpu-arm64.zip", "4b6a004b076eea47c318bea35cf1db2ff2bf037738b04645646ae8d7c3159478", "zip"),
    ("darwin", "arm64"): ("llama-b10964-bin-macos-arm64.tar.gz", "033c845c1df9bf945ff37bb193238b40910b2244be3e1e637b2ceb5878f1a6f5", "tar"),
    ("darwin", "x86_64"): ("llama-b10964-bin-macos-x64.tar.gz", "03430a394d0a169a5e6d8f01c09f48cf58eb026af6fc95940a4a528e2e50cf38", "tar"),
    ("linux", "x86_64"): ("llama-b10964-bin-ubuntu-x64.tar.gz", "9abf88aea48a55d0f80edb1ee20220b186848cca0b4e919d71518cfd7ca67443", "tar"),
    ("linux", "aarch64"): ("llama-b10964-bin-ubuntu-arm64.tar.gz", "5f0e9c95d970892e43380f82ebcab960edfd20a1cd0f7abffa13b29fdb924949", "tar"),
}
SYCL_WINDOWS_X64 = (
    "llama-b10964-bin-win-sycl-x64.zip",
    "18820bc29cd38ceb664034acd426a59b3bae3704c580added5fd17dd1ddd632e",
    "zip",
)


def llama_cpp_managed_selected(config: dict[str, Any]) -> bool:
    ollama = config.get("ollama", {})
    llama = config.get("llama_cpp", {})
    ollama = ollama if isinstance(ollama, dict) else {}
    llama = llama if isinstance(llama, dict) else {}
    return not bool(ollama.get("enabled", False)) and str(llama.get("mode", "auto")).strip().lower() == "on"


def llama_cpp_backend_selection(config: dict[str, Any]) -> str:
    """Return the configured backend policy, independent of current health."""
    ollama = config.get("ollama", {})
    llama = config.get("llama_cpp", {})
    ollama = ollama if isinstance(ollama, dict) else {}
    llama = llama if isinstance(llama, dict) else {}
    mode = str(llama.get("mode", "auto")).strip().lower()
    if bool(ollama.get("enabled", False)):
        return "ollama"
    if mode == "on":
        return "llama.cpp (managed)"
    if mode == "auto":
        return "llama.cpp (external, auto-detect)"
    return "disabled"


class LlamaCppManagedRuntime:
    """Install and supervise the loopback llama-server selected by mode=on."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        server = config.get("server", {}) if isinstance(config.get("server", {}), dict) else {}
        llama = config.get("llama_cpp", {}) if isinstance(config.get("llama_cpp", {}), dict) else {}
        self.state_dir = Path(str(server.get("state_dir", "~/.local-ai-hub/state"))).expanduser().resolve()
        self.llama_config = llama
        self.runtime_dir = self.state_dir / "runtime" / f"llama.cpp-{LLAMA_VERSION}"
        self.model_dir = self.state_dir / "models" / "llama.cpp"
        filename = str(llama.get("managed_model_filename", "hub-qwen-15.gguf")).strip()
        if not filename or Path(filename).name != filename or not filename.lower().endswith(".gguf"):
            raise RuntimeError("llama_cpp.managed_model_filename must be a .gguf filename inside the managed model directory")
        self.model_path = self.model_dir / filename
        self.pid_path = self.state_dir / "llama.cpp.managed.pid"
        self.mode_path = self.state_dir / "llama.cpp.managed-mode"
        self.log_path = self.state_dir / "logs" / "llama.cpp-server.log"
        self._lock = threading.Lock()
        self._retry_after = 0.0
        self._last_error = ""

    @staticmethod
    def _host_platform() -> tuple[str, str]:
        system = platform.system().lower()
        os_name = "win32" if system == "windows" else "darwin" if system == "darwin" else "linux" if system == "linux" else system
        machine = platform.machine().lower()
        arch = {"amd64": "amd64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "arm64"}.get(machine, machine)
        return os_name, arch

    @classmethod
    def runtime_asset(cls, os_name: str | None = None, arch: str | None = None) -> tuple[str, str, str]:
        host = cls._host_platform()
        key = (os_name or host[0], arch or host[1])
        if key not in RUNTIME_ASSETS:
            raise RuntimeError(f"Managed llama.cpp is not supported on {key[0]}/{key[1]}; choose Ollama or configure an external llama.cpp endpoint.")
        if os_name is None and key[0] == "linux":
            try:
                distro = str(platform.freedesktop_os_release().get("ID", "")).lower()
            except (AttributeError, OSError):
                distro = ""
            if distro != "ubuntu":
                raise RuntimeError(f"Managed llama.cpp Linux package requires Ubuntu; found {distro or 'unknown distribution'}. Configure an external endpoint instead.")
        return RUNTIME_ASSETS[key]

    @staticmethod
    def _download(url: str, destination: Path, expected_sha256: str, max_bytes: int, timeout: int) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        digest = hashlib.sha256()
        total = 0
        deadline = time.monotonic() + 1800
        try:
            request = Request(url, headers={"User-Agent": "Local-AI-Hub/4"})
            with urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Download exceeded the 1800-second limit: {urlsplit(url).hostname}")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError(f"Download exceeded the {max_bytes}-byte safety limit: {urlsplit(url).hostname}")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not total or digest.hexdigest().lower() != expected_sha256.lower():
                raise RuntimeError(f"SHA-256 verification failed for {destination.name}; the file was not installed.")
            os.replace(partial, destination)
        finally:
            partial.unlink(missing_ok=True)

    @staticmethod
    def _safe_member(root: Path, name: str) -> Path:
        normalized = name.replace("\\", "/")
        member = PurePosixPath(normalized)
        if not member.parts or member.is_absolute() or any(part in {"", ".", ".."} for part in member.parts) or ":" in member.parts[0]:
            raise RuntimeError(f"Unsafe path in llama.cpp archive: {name}")
        target = root.joinpath(*member.parts).resolve()
        if not target.is_relative_to(root.resolve()):
            raise RuntimeError(f"Archive path escapes the runtime directory: {name}")
        return target

    @classmethod
    def _extract(cls, archive: Path, destination: Path, kind: str) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        expanded = 0
        if kind == "zip":
            with zipfile.ZipFile(archive) as bundle:
                for item in bundle.infolist():
                    expanded += item.file_size
                    if expanded > MAX_EXTRACTED_BYTES:
                        raise RuntimeError("llama.cpp archive exceeded the extraction size limit")
                    target = cls._safe_member(destination, item.filename)
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    mode = (item.external_attr >> 16) & 0xFFFF
                    if mode & 0o170000 == 0o120000:
                        raise RuntimeError(f"Symbolic links are not allowed in llama.cpp archives: {item.filename}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    if mode & 0o111:
                        target.chmod(target.stat().st_mode | 0o111)
            return
        with tarfile.open(archive, "r:gz") as bundle:
            for item in bundle.getmembers():
                expanded += max(0, item.size)
                if expanded > MAX_EXTRACTED_BYTES:
                    raise RuntimeError("llama.cpp archive exceeded the extraction size limit")
                target = cls._safe_member(destination, item.name)
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not item.isfile():
                    raise RuntimeError(f"Links and special files are not allowed in llama.cpp archives: {item.name}")
                source = bundle.extractfile(item)
                if source is None:
                    raise RuntimeError(f"Could not read llama.cpp archive member: {item.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                target.chmod(item.mode & 0o777)

    def provision(self) -> Path:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        asset, digest, kind = self.runtime_asset()
        gpus = (self.config.get("_hardware", {}) or {}).get("gpus", [])
        intel_gpu = os.name == "nt" and any(
            "intel" in str(row.get("vendor", "")).lower() or "intel" in str(row.get("name", "")).lower()
            for row in gpus if isinstance(row, dict)
        )
        if intel_gpu and self._host_platform() == ("win32", "amd64"):
            asset, digest, kind = SYCL_WINDOWS_X64
        binary = self._find_server(self.runtime_dir)
        marker = self.runtime_dir / ".runtime-sha256"
        verified = marker.exists() and marker.read_text(encoding="utf-8").strip() == digest
        if binary is None or not verified:
            archive = self.runtime_dir / asset
            if not archive.exists() or self._sha256(archive) != digest:
                archive.unlink(missing_ok=True)
                self._download(f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/{asset}", archive, digest, MAX_RUNTIME_BYTES, timeout=60)
            stage = Path(tempfile.mkdtemp(prefix="extract-", dir=self.runtime_dir))
            try:
                self._extract(archive, stage, kind)
                extracted = self._find_server(stage)
                if extracted is None:
                    raise RuntimeError("Verified llama.cpp archive does not contain llama-server.")
                target_dir = self.runtime_dir / "bin"
                target_dir.mkdir(parents=True, exist_ok=True)
                for item in stage.rglob("*"):
                    target = target_dir / item.relative_to(stage)
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif item.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
                binary = self._find_server(target_dir)
                marker.write_text(digest, encoding="utf-8")
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        if binary is None:
            raise RuntimeError("llama-server was not installed from the verified archive.")
        if not self.model_path.exists() or self._sha256(self.model_path) != MODEL_SHA256:
            self._download(MODEL_URL, self.model_path, MODEL_SHA256, MAX_MODEL_BYTES, timeout=60)
        self._write_preset()
        return binary

    @staticmethod
    def _find_server(root: Path) -> Path | None:
        name = "llama-server.exe" if os.name == "nt" else "llama-server"
        found = next((path for path in root.rglob(name) if path.is_file()), None)
        if found and os.name != "nt":
            found.chmod(found.stat().st_mode | 0o111)
        return found

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _configured_routes(self) -> tuple[int, list[tuple[str, str]]]:
        models = self.llama_config.get("models", {})
        rows: list[tuple[str, str]] = []
        port = 12438
        if isinstance(models, dict):
            for logical, entry in models.items():
                if not isinstance(entry, dict):
                    continue
                url = urlsplit(str(entry.get("url", "")))
                if url.hostname in {"localhost", "127.0.0.1", "::1"}:
                    port = int(url.port or (443 if url.scheme == "https" else 80))
                if "vl" in str(logical).lower():
                    continue
                alias = str(entry.get("served_model", logical)).strip()
                if alias and alias not in {item[0] for item in rows}:
                    rows.append((alias, str(logical)))
        if not rows:
            rows.append(("hub-qwen-15", "qwen2.5-coder:1.5b"))
        return port, rows

    def _write_preset(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        _, aliases = self._configured_routes()
        path_value = str(self.model_path.resolve()).replace("\\", "/")
        sections = ["version = 1", "", "[*]", "n-gpu-layers = 99", "models-max = 1", ""]
        default_alias = aliases[0][0]
        configured = self.llama_config.get("models", {})
        fast_model = str((self.config.get("models", {}) or {}).get("fast_code", "qwen2.5-coder:1.5b"))
        if isinstance(configured, dict) and isinstance(configured.get(fast_model), dict):
            default_alias = str(configured[fast_model].get("served_model", fast_model))
        for alias, _logical in aliases:
            sections.extend([f"[{alias}]", f'model = "{path_value}"', f'alias = "{alias}"', f"load-on-startup = {'true' if alias == default_alias else 'false'}", ""])
        (self.runtime_dir / "hub.models.ini").write_text("\n".join(sections), encoding="utf-8")

    def _port_and_url(self) -> tuple[int, str]:
        port, _ = self._configured_routes()
        return port, f"http://127.0.0.1:{port}"

    def _default_alias(self) -> str:
        _port, aliases = self._configured_routes()
        configured = self.llama_config.get("models", {})
        fast_model = str((self.config.get("models", {}) or {}).get("fast_code", "qwen2.5-coder:1.5b"))
        if isinstance(configured, dict) and isinstance(configured.get(fast_model), dict):
            return str(configured[fast_model].get("served_model", fast_model))
        return aliases[0][0]

    def _device_attempts(self, intel_windows_gpu: bool) -> list[tuple[str, float]]:
        timeout = float(self.llama_config.get("startup_timeout_seconds", self.llama_config.get("model_load_timeout_seconds", 600)))
        return [("SYCL0", 25.0), ("none", timeout)] if intel_windows_gpu else [("none", timeout)]

    def _managed_pid_alive(self) -> bool:
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return False
        name = Path(process_executable(pid) or "").name.lower()
        return bool(pid_alive(pid) and name in {"llama-server", "llama-server.exe"})

    def is_online(self) -> bool:
        _, url = self._port_and_url()
        try:
            with urlopen(f"{url}/health", timeout=0.8) as response:
                if not 200 <= int(getattr(response, "status", 200)) < 300:
                    return False
            with urlopen(f"{url}/models", timeout=0.8) as response:
                import json
                body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
            rows = body.get("data", []) if isinstance(body, dict) else []
            aliases = {str(row.get("id", "")) for row in rows if isinstance(row, dict)} if isinstance(rows, list) else set()
            return self._default_alias() in aliases
        except Exception:
            return False

    def _ready(self, url: str, timeout: float, process: subprocess.Popen[Any]) -> bool:
        deadline = time.monotonic() + max(1.0, timeout)
        default_alias = self._default_alias()
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                with urlopen(f"{url}/models", timeout=1.0) as response:
                    import json
                    body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
                rows = body.get("data", []) if isinstance(body, dict) else []
                for row in rows if isinstance(rows, list) else []:
                    if isinstance(row, dict) and row.get("id") == default_alias:
                        status = row.get("status", {})
                        if isinstance(status, dict) and str(status.get("value", "")).lower() == "loaded":
                            return True
                        if isinstance(status, dict) and status.get("failed"):
                            return False
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def ensure_running(self) -> bool:
        if self.is_online():
            return True
        with self._lock:
            if self.is_online():
                return True
            if time.monotonic() < self._retry_after:
                return False
            try:
                self.provision()
            except Exception as exc:
                self._last_error = str(exc)
                self._retry_after = time.monotonic() + 60.0
                return False
            try:
                stale_pid = int(self.pid_path.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                stale_pid = 0
            if stale_pid and pid_alive(stale_pid):
                executable = Path(process_executable(stale_pid) or "").name.lower()
                if executable in {"llama-server", "llama-server.exe"}:
                    terminate_tree(stale_pid, grace_seconds=2.0)
            self.pid_path.unlink(missing_ok=True)
            port, url = self._port_and_url()
            binary = self._find_server(self.runtime_dir)
            if binary is None:
                return False
            gpus = (self.config.get("_hardware", {}) or {}).get("gpus", [])
            gpu = os.name == "nt" and any(
                "intel" in str(row.get("vendor", "")).lower() or "intel" in str(row.get("name", "")).lower()
                for row in gpus if isinstance(row, dict)
            )
            attempts = self._device_attempts(gpu)
            for device, wait_seconds in attempts:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                args = [str(binary), "--models-preset", str(self.runtime_dir / "hub.models.ini"), "--models-max", "1", "--host", "127.0.0.1", "--port", str(port), "--device", device]
                kwargs = hidden_run_kwargs(new_group=True)
                if os.name != "nt":
                    kwargs["start_new_session"] = True
                proc: subprocess.Popen[Any] | None = None
                with self.log_path.open("ab") as log_file:
                    try:
                        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT, **kwargs)
                        self.pid_path.write_text(str(proc.pid), encoding="utf-8")
                    except Exception:
                        if proc is not None:
                            terminate_tree(proc.pid, grace_seconds=2.0)
                        self._last_error = "Could not start llama-server. See state/logs/llama.cpp-server.log."
                        self._retry_after = time.monotonic() + 60.0
                        return False
                if proc is not None and self._ready(url, wait_seconds, proc):
                    self.mode_path.write_text(device, encoding="utf-8")
                    self._last_error = ""
                    self._retry_after = 0.0
                    return True
                if proc is not None:
                    terminate_tree(proc.pid, grace_seconds=2.0)
                self.pid_path.unlink(missing_ok=True)
            self._last_error = "llama-server did not become healthy in SYCL/CPU mode. See state/logs/llama.cpp-server.log."
            self._retry_after = time.monotonic() + 60.0
            return False

    def stop(self) -> bool:
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return False
        executable = Path(process_executable(pid) or "").name.lower()
        if not pid_alive(pid) or executable not in {"llama-server", "llama-server.exe"}:
            self.pid_path.unlink(missing_ok=True)
            return False
        stopped = terminate_tree(pid, grace_seconds=3.0)
        if stopped:
            self.pid_path.unlink(missing_ok=True)
        return stopped

    def status(self) -> dict[str, Any]:
        selected = llama_cpp_managed_selected(self.config)
        mode = self.mode_path.read_text(encoding="utf-8").strip() if self.mode_path.exists() else ""
        _, url = self._port_and_url()
        return {"selected": selected, "online": self.is_online() if selected else False, "mode": mode, "last_error": self._last_error, "url": url, "runtime_dir": str(self.runtime_dir), "model_path": str(self.model_path)}
