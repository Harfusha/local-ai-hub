"""Owned process boundary for non-preemptible CUDA NLP calls."""
from __future__ import annotations

from contextlib import redirect_stdout
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import weakref

from .process_utils import popen_managed, terminate_tree

_INPUT_LIMIT = 1024 * 1024
_OUTPUT_LIMIT = 32 * 1024 * 1024


def _windows_avx512_available():
    try:
        import ctypes
        # Windows feature 41 includes operating-system support for AVX-512F.
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(41))
    except (AttributeError, OSError):
        return True


def _cuda_worker_environment(kwargs):
    device = str(kwargs.get("device", "")).lower()
    if (sys.platform != "win32" or not (device == "cuda" or device.startswith("cuda:"))
            or "CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK" in os.environ
            or _windows_avx512_available()):
        return None
    # cuBLASLt may otherwise dispatch AVX-512 despite disabled Windows XState.
    env = os.environ.copy()
    env["CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK"] = "1"
    return env


class _ModelProcess:
    def __init__(self, argv, *, env=None):
        self.process = popen_managed(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self._responses = queue.Queue(maxsize=2)
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._sequence = 0
        self._closed = False
        self._writers = []
        self._stderr_tail = bytearray()
        self._stderr_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True, name="model-response")
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True, name="model-stderr")
        self._reader.start()
        self._stderr_reader.start()

    def _read_stderr(self):
        try:
            reader = getattr(self.process.stderr, "read1", self.process.stderr.read)
            while True:
                chunk = reader(4096)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_tail.extend(chunk)
                    if len(self._stderr_tail) > 8192:
                        del self._stderr_tail[:-8192]
        except (OSError, ValueError):
            return

    def _worker_failure_context(self):
        details = []
        exit_code = self.process.poll()
        if exit_code is None:
            try:
                exit_code = self.process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        if exit_code is not None:
            details.append(f"worker exit code: {exit_code}")
        if not self._stderr_tail:
            time.sleep(0.05)
        with self._stderr_lock:
            stderr = bytes(self._stderr_tail).decode("utf-8", "replace").strip()
        if stderr:
            details.append(f"worker stderr: {stderr[-2000:]}")
        return f" ({'; '.join(details)})" if details else ""

    def _read(self):
        try:
            while True:
                raw = self.process.stdout.readline(_OUTPUT_LIMIT + 1)
                if not raw:
                    self._stderr_reader.join(timeout=0.2)
                    item = None
                elif len(raw) > _OUTPUT_LIMIT or not raw.endswith(b"\n"):
                    item = ValueError("model response exceeds byte limit")
                else:
                    item = json.loads(raw)
                self._responses.put_nowait(item)
                if item is None or isinstance(item, Exception):
                    return
        except (ValueError, OSError, queue.Full) as exc:
            try:
                self._responses.put_nowait(exc)
            except queue.Full:
                pass

    def request(self, payload, *, timeout):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("model timeout must be finite and within (0,300]")
        raw = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > _INPUT_LIMIT:
            raise ValueError("model request exceeds byte limit")
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            raise TimeoutError("model request lock timed out")
        try:
            if self._closed:
                raise RuntimeError("model process is closed")
            self._sequence += 1
            raw = json.dumps({**payload, "request_id": self._sequence}, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
            if len(raw) > _INPUT_LIMIT:
                raise ValueError("model request exceeds byte limit")
            written, failures = threading.Event(), []

            def write():
                try:
                    self.process.stdin.write(raw)
                    self.process.stdin.flush()
                except (OSError, ValueError) as exc:
                    failures.append(exc)
                finally:
                    written.set()

            writer = threading.Thread(target=write, daemon=True, name="model-request")
            self._writers = [thread for thread in self._writers if thread.is_alive()]
            self._writers.append(writer)
            writer.start()
            if not written.wait(max(0.0, deadline - time.monotonic())):
                raise TimeoutError("model request write timed out" + self._worker_failure_context())
            if failures:
                raise RuntimeError("model request pipe failed") from failures[0]
            try:
                response = self._responses.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError("model operation timed out" + self._worker_failure_context()) from None
            if isinstance(response, Exception):
                raise response
            if not isinstance(response, dict) or response.get("request_id") != self._sequence:
                raise RuntimeError(
                    "model response identity mismatch or unexpected EOF"
                    + self._worker_failure_context()
                )
            if response.get("success") is not True:
                raise RuntimeError(str(response.get("error", "model operation failed"))[:2000])
            return response
        except BaseException:
            self.close()
            raise
        finally:
            self._lock.release()

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            terminate_tree(self.process.pid, process_handle=self.process, grace_seconds=0.2)
            try:
                self.process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                raise RuntimeError("model process cleanup unconfirmed") from None
            for thread in [self._reader, self._stderr_reader, *self._writers]:
                if thread is not threading.current_thread():
                    thread.join(timeout=0.5)
            if any(thread.is_alive() for thread in [self._reader, self._stderr_reader, *self._writers]):
                raise RuntimeError("model pipe cleanup unconfirmed")
            self.process.stdin.close()
            self.process.stdout.close()
            self.process.stderr.close()
            finalizer = getattr(self.process, "_local_ai_job_finalizer", None)
            if finalizer is not None:
                finalizer()
            self._closed = True


class OwnedNLPModel:
    owned_process = True

    def __init__(self, kind, model_name, kwargs, *, max_length, allow_downloads=False):
        if kind not in ("embedding", "reranker"):
            raise ValueError("unsupported owned model kind")
        source = str(Path(__file__).resolve().parent.parent)
        code = f"import sys;sys.path.insert(0,{source!r});from local_ai_hub.owned_model import worker_main;worker_main()"
        self._transport = _ModelProcess([sys.executable, "-u", "-c", code], env=_cuda_worker_environment(kwargs))
        self._finalizer = weakref.finalize(self, self._transport.close)
        metadata = self._transport.request({"operation": "load", "kind": kind, "model_name": model_name,
            "kwargs": kwargs, "max_length": max_length, "allow_downloads": allow_downloads is True}, timeout=120)
        self.model_name = metadata["model_name"]
        self.prompts = metadata.get("prompts", {})
        self.config = SimpleNamespace(_commit_hash=metadata.get("revision"))
        self.max_seq_length = metadata.get("max_seq_length", max_length)

    def encode(self, items, **kwargs):
        return self._transport.request({"operation": "encode", "items": items, "kwargs": kwargs}, timeout=60)["value"]

    def predict(self, items, **kwargs):
        return self._transport.request({"operation": "predict", "items": items, "kwargs": kwargs}, timeout=60)["value"]

    def close(self):
        self._transport.close()
        self._finalizer.detach()


def _load(spec):
    from sentence_transformers import CrossEncoder, SentenceTransformer
    kind = spec["kind"]
    if kind not in ("embedding", "reranker"):
        raise ValueError("unsupported model kind")
    constructor = SentenceTransformer if kind == "embedding" else CrossEncoder
    kwargs, name = dict(spec["kwargs"]), spec["model_name"]

    def construct(model_name, options):
        try:
            return constructor(model_name, local_files_only=True, **options)
        except Exception:
            from pathlib import Path
            import os
            clean_name = str(model_name).replace("/", "--")
            bases = []
            if os.environ.get("HF_HOME"):
                bases.append(Path(os.environ["HF_HOME"]) / "hub")
            bases.extend([
                Path.home() / ".cache" / "huggingface" / "hub",
                Path(os.path.expanduser("~")) / ".cache" / "huggingface" / "hub",
            ])
            user_prof = os.environ.get("USERPROFILE")
            if user_prof:
                bases.append(Path(user_prof) / ".cache" / "huggingface" / "hub")
            if os.name == "nt":
                sys_drive = os.environ.get("SystemDrive", "C:")
                if not sys_drive.endswith(("\\", "/")):
                    sys_drive += "\\"
                usr_name = os.environ.get("USERNAME")
                if usr_name:
                    bases.append(Path(sys_drive) / "Users" / usr_name / ".cache" / "huggingface" / "hub")
            seen = set()
            for base in bases:
                b_str = str(base.resolve(strict=False))
                if b_str in seen:
                    continue
                seen.add(b_str)
                hub_dir = base / f"models--{clean_name}" / "snapshots"
                if hub_dir.is_dir():
                    requested_revision = options.get("revision")
                    for snapshot in hub_dir.iterdir():
                        if requested_revision is not None:
                            # A local directory ignores the loader's revision
                            # argument. Only a full immutable snapshot ID can
                            # prove that this fallback honors the request.
                            if (not isinstance(requested_revision, str)
                                    or len(requested_revision) not in {40, 64}
                                    or any(c not in "0123456789abcdefABCDEF" for c in requested_revision)
                                    or snapshot.name.casefold() != requested_revision.casefold()):
                                continue
                        if snapshot.is_dir() and (snapshot / "config.json").exists() and ((snapshot / "model.safetensors").exists() or (snapshot / "pytorch_model.bin").exists()):
                            return constructor(str(snapshot), **options)
            if spec.get("allow_downloads") is not True:
                raise
            return constructor(model_name, **options)

    try:
        model = construct(name, kwargs)
    except Exception:
        if kind != "embedding" or name == "BAAI/bge-small-en-v1.5" or kwargs.get("revision") is not None:
            raise
        name = "BAAI/bge-small-en-v1.5"
        kwargs["trust_remote_code"] = False
        kwargs.pop("revision", None)
        model = construct(name, kwargs)
    if kind == "embedding" and hasattr(model, "max_seq_length"):
        maximum = model.max_seq_length or 512
        try:
            maximum = getattr(model[0].auto_model.config, "max_position_embeddings", maximum) or maximum
        except (AttributeError, IndexError, TypeError):
            pass
        model.max_seq_length = min(int(spec["max_length"]), int(maximum))
    candidates = [model]
    try:
        candidates.extend([model[0], model[0].auto_model])
    except (AttributeError, IndexError, KeyError, TypeError):
        pass
    revision = next((getattr(getattr(item, "config", None), "_commit_hash", None) for item in candidates
                     if getattr(getattr(item, "config", None), "_commit_hash", None)), None)
    return model, {"model_name": name, "max_seq_length": getattr(model, "max_seq_length", spec["max_length"]),
                   "revision": revision, "prompts": {str(key): "" for key in (getattr(model, "prompts", {}) or {})}}


def worker_main():
    model, kind = None, None
    source, output = sys.stdin.buffer, sys.stdout
    while True:
        raw = source.readline(_INPUT_LIMIT + 1)
        if not raw or len(raw) > _INPUT_LIMIT:
            return
        request_id = None
        try:
            request = json.loads(raw)
            request_id = request["request_id"]
            operation = request["operation"]
            with redirect_stdout(sys.stderr):
                if operation == "load" and model is None:
                    model, value = _load(request)
                    kind = request["kind"]
                elif (operation, kind) in (("encode", "embedding"), ("predict", "reranker")):
                    value = getattr(model, operation)(request["items"], **request["kwargs"])
                    value = {"value": value.tolist() if hasattr(value, "tolist") else value}
                else:
                    raise ValueError("unsupported model operation")
            response = {**value, "success": True, "request_id": request_id}
        except Exception as exc:
            response = {"success": False, "request_id": request_id, "error": f"{type(exc).__name__}: {exc}"[:2000]}
        try:
            encoded = json.dumps(response, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError) as exc:
            # Model output can contain non-finite scores or unsupported scalar
            # objects. Report a request-bound protocol failure instead of
            # letting the worker exit and making the parent see an unexplained EOF.
            response = {
                "success": False,
                "request_id": request_id,
                "error": f"model response is not valid JSON: {type(exc).__name__}: {str(exc)[:1000]}",
            }
            encoded = json.dumps(response, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _OUTPUT_LIMIT - 1:
            encoded = json.dumps({"success": False, "request_id": request_id, "error": "model response exceeds byte limit"}, separators=(",", ":"))
        output.write(encoded + "\n")
        output.flush()
