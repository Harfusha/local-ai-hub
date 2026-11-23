from __future__ import annotations

import codecs
from collections.abc import Mapping, Sequence
import inspect
import io
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from typing import Any

from .cache import stable_hash
from .command_constants import (
    _COMMAND_LOG_QUEUE_MAX_CHUNKS,
    _MAX_PROJECT_COMMAND_ARGS,
    _MAX_PROJECT_COMMAND_ENV_BYTES,
    _MAX_PROJECT_COMMAND_ENV_ENTRIES,
    _PROJECT_COMMAND_ALIAS_RE,
)
from .command_environment import (
    PROJECT_COMMAND_ENV_KEY_RE as _PROJECT_COMMAND_ENV_KEY_RE,
    is_valid_project_command_env_key as _is_valid_project_command_env_key,
)
from .command_invocation_validation import validate_invocation
from .command_models import CommandInvocation, _ResolvedProjectCommand
from .command_build import classify_build_command
from .command_powershell import classify_powershell_command
from .command_python import classify_hubctl_command, classify_python_command
from .command_read import classify_read_only_command
from .command_shell import classify_raw_shell_subshell
from .command_validation import (
    classify_formatter_command,
    classify_php_validation_script,
    classify_validation_tool,
)
from .command_daemon_process import (
    _process_exited_without_reaping,
    _process_group_liveness,
)
from .command_git import classify_git_command
from .command_jobs import (
    assign_process_to_job,
    close_job_object,
    create_job_object_kill_on_close,
    terminate_and_confirm_windows_job_empty as _terminate_and_confirm_windows_job_empty,
)
from .command_policy import (
    _classification_result,
    classify_dangerous_or_whitelisted_tool,
    command_executable_identity,
    normalize_user_whitelisted_tools,
)
from .command_streams import _BoundedStreamBuffer
from .process_utils import (
    _resume_suspended_process,
    hidden_run_kwargs,
    process_identity,
    terminate_tree,
)
from .state_paths import configured_state_dir

class CommandExecuteMixin:
    def _classify_single(self, command: str | Sequence[str]) -> dict[str, Any]:
        structured = not isinstance(command, str)
        tokens = list(command) if structured else self._tokens(command)
        if not tokens:
            return _classification_result(
                "unknown", cacheable=False, allowed=False,
                reason="empty or unparsable command",
            )
        command_text = " ".join(tokens) if structured else command
        exe_base, lower = command_executable_identity(tokens)
        cfg = self.config.get("commands", {})

        extra_allowed = normalize_user_whitelisted_tools(cfg.get("extra_allowed_tools", []))
        # Keep shell interpreters inside command classification; allowlisting a
        # shell must not grant arbitrary script execution before safety checks.
        executable_policy_result = classify_dangerous_or_whitelisted_tool(
            exe_base, extra_allowed
        )
        if executable_policy_result is not None:
            return executable_policy_result

        # PowerShell commands or script blocks
        if self._is_powershell_command(command_text) or exe_base in {"pwsh", "powershell"}:
            return classify_powershell_command(command_text, cfg, extra_allowed)

        # Reject dangerous shell subshells in raw non-powershell commands
        shell_subshell_result = classify_raw_shell_subshell(
            command, structured=structured
        )
        if shell_subshell_result is not None:
            return shell_subshell_result

        if exe_base == "git":
            return classify_git_command(tokens, lower, cfg)

        read_only_result = classify_read_only_command(
            exe_base,
            lower,
            cfg,
            read_only=self.READ_ONLY,
            volatile_reads=self.VOLATILE_READS,
        )
        if read_only_result is not None:
            return read_only_result

        if self._is_python_interpreter_name(exe_base):
            python_result = classify_python_command(tokens, lower, cfg)
            if python_result is not None:
                return python_result

        if exe_base == "hubctl":
            hubctl_result = classify_hubctl_command(lower, lower, cfg)
            if hubctl_result is not None:
                return hubctl_result

        if exe_base == "php" and lower:
            php_validation_result = classify_php_validation_script(lower[0], cfg)
            if php_validation_result is not None:
                return php_validation_result

        formatter_result = classify_formatter_command(exe_base, lower, cfg)
        if formatter_result is not None:
            return formatter_result

        validation_result = classify_validation_tool(
            exe_base, self.PURE_VALIDATORS, cfg, f"{exe_base} validation tool"
        )
        if validation_result is not None:
            return validation_result

        build_result = classify_build_command(
            exe_base,
            tokens,
            lower,
            cfg,
            mutating_words=self.MUTATING_WORDS,
            validators=self.VALIDATORS,
        )
        if build_result is not None:
            return build_result

        return _classification_result(
            "unknown", cacheable=False,
            allowed=bool(cfg.get("allow_unknown", False)),
            reason="command not in safe broker allowlist",
        )
    def _execute(
        self,
        command: str | Sequence[str],
        cwd: str,
        timeout: int,
        cancel_event: threading.Event | None = None,
        log_callback: Any | None = None,
        *,
        argv_override: Sequence[str] | None = None,
        env_overrides: Mapping[str, str] | None = None,
        environment_overrides: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
    ) -> dict[str, Any]:
        if isinstance(command, str):
            tokens = self._tokens(command)
            needs_shell = self._needs_shell(command)
        else:
            tokens = list(command)
            if not tokens or any(not isinstance(token, str) or "\x00" in token for token in tokens):
                return {
                    "success": False, "exit_code": 2, "timed_out": False,
                    "stdout": "", "stderr": "argv must be a non-empty list of null-free strings",
                    "error": "invalid process argv",
                }
            needs_shell = False
        started = time.perf_counter()
        if argv_override is not None:
            argv = list(argv_override)
            if os.name == "nt" and argv:
                raw0 = argv[0].strip('"')
                if not Path(raw0).is_absolute():
                    resolved = shutil.which(raw0) or shutil.which(raw0, path=cwd)
                    if resolved:
                        argv[0] = resolved
        elif needs_shell:
            if os.name == "nt":
                shell_bin = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
                argv = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", command]
            else:
                if self._is_powershell_command(command) and shutil.which("pwsh"):
                    argv = [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", command]
                else:
                    argv = ["/bin/sh", "-c", command]
        elif os.name == "nt":
            raw0 = tokens[0].strip('"') if tokens else ""
            if raw0.lower() in {"ver", "set"}:
                comspec = os.environ.get("COMSPEC", "cmd.exe")
                argv = [comspec, "/d", "/c", command]
            else:
                suffix = Path(raw0).suffix.lower()
                resolved = shutil.which(raw0) or shutil.which(raw0, path=cwd)
                if (resolved and Path(resolved).suffix.lower() in {".bat", ".cmd"}) or suffix in {".bat", ".cmd"}:
                    comspec = os.environ.get("COMSPEC", "cmd.exe")
                    argv = [comspec, "/d", "/c"] + tokens
                elif resolved:
                    argv = [resolved] + tokens[1:]
                else:
                    argv = tokens
        else:
            argv = tokens
        proc_env = os.environ.copy()
        if env_overrides:
            proc_env.update(env_overrides)
        proc_env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc_env["PYTHONIOENCODING"] = "utf-8"
        if environment_overrides:
            proc_env.update(environment_overrides)
        kwargs: dict[str, Any] = {
            "cwd": str(Path(cwd).resolve()),
            "stdin": subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "env": proc_env,
        }
        job_handle = None
        if os.name == "nt":
            kwargs.update(hidden_run_kwargs(new_group=True))
            job_handle = create_job_object_kill_on_close()
            if not job_handle:
                return {
                    "success": False, "exit_code": 127, "timed_out": False,
                    "stdout": "", "stderr": "Unable to create a kill-on-close Windows Job Object",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": "failed to establish Windows process-tree ownership",
                }
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | 0x00000004
        else:
            kwargs["start_new_session"] = True
        process = None
        try:
            process = subprocess.Popen(argv, **kwargs)
            if job_handle:
                if not assign_process_to_job(job_handle, process.pid):
                    raise OSError("Unable to assign suspended process to Windows Job Object")
                if not _resume_suspended_process(process):
                    raise OSError("Unable to resume suspended Windows process")
            if stdin is not None and getattr(process, "stdin", None):
                try:
                    raw_bytes = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
                    process.stdin.write(raw_bytes)
                    process.stdin.flush()
                except Exception:
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass
        except BaseException as exc:
            cleanup_unconfirmed = False
            if job_handle:
                try:
                    cleanup_unconfirmed = not _terminate_and_confirm_windows_job_empty(job_handle)
                except Exception:
                    cleanup_unconfirmed = True
            if process is not None:
                cleanup_confirmed = False
                try:
                    kwargs: dict[str, Any] = {"grace_seconds": 2.0}
                    signature = inspect.signature(terminate_tree)
                    if "process_group" in signature.parameters and os.name != "nt":
                        kwargs["process_group"] = process.pid
                    if "expected_identity" in signature.parameters and os.name != "nt":
                        kwargs["expected_identity"] = process_identity(process.pid)
                    if "process_handle" in signature.parameters:
                        kwargs["process_handle"] = process
                    cleanup_confirmed = bool(terminate_tree(process.pid, **kwargs))
                except Exception:
                    cleanup_unconfirmed = True
                if cleanup_confirmed:
                    try:
                        process.wait(timeout=2.0)
                    except Exception:
                        cleanup_unconfirmed = True
                    try:
                        cleanup_unconfirmed = cleanup_unconfirmed or process.poll() is None
                    except Exception:
                        cleanup_unconfirmed = True
                else:
                    cleanup_unconfirmed = True
                for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
                    try:
                        if stream and not stream.closed:
                            stream.close()
                    except Exception:
                        cleanup_unconfirmed = True
            if job_handle:
                try:
                    job_closed = close_job_object(job_handle)
                except Exception:
                    job_closed = False
                cleanup_unconfirmed = cleanup_unconfirmed or not job_closed
            if not isinstance(exc, OSError):
                raise
            return {
                "success": False, "exit_code": 127, "timed_out": False,
                "cleanup_unconfirmed": cleanup_unconfirmed,
                "stdout": "", "stderr": str(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": f"failed to spawn process: {exc}",
            }

        process_started = time.perf_counter()
        proc_ident = process_identity(process.pid) if (process is not None and os.name != "nt") else None

        def _cleanup_owned_tree() -> bool:
            if job_handle:
                return _terminate_and_confirm_windows_job_empty(job_handle)
            if os.name != "nt" and process is not None and process.pid > 0:
                try:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        # A missing *process group* does not prove that the
                        # parent process exited. Continue to the owned process
                        # cleanup path when the process handle is still live.
                        try:
                            if process.poll() is not None:
                                return True
                        except Exception:
                            return False
                    except PermissionError:
                        return False
                    except Exception:
                        return False
                    kwargs: dict[str, Any] = {"grace_seconds": float(self.terminate_grace_seconds)}
                    sig = inspect.signature(terminate_tree)
                    if "process_group" in sig.parameters:
                        kwargs["process_group"] = process.pid
                    if "expected_identity" in sig.parameters:
                        kwargs["expected_identity"] = proc_ident
                    if "process_handle" in sig.parameters:
                        kwargs["process_handle"] = process
                    res = terminate_tree(process.pid, **kwargs)
                    if res:
                        return True
                    if process.poll() is not None and _process_group_liveness(process.pid) is False:
                        return True
                    # A failed ownership check cannot authorize another signal
                    # to a numeric process group that may already be reused.
                    return False
                except Exception:
                    return False
            return True if not job_handle and os.name != "nt" else False

        out_buf = _BoundedStreamBuffer(self.max_output_chars, self.max_output_bytes)
        err_buf = _BoundedStreamBuffer(self.max_output_chars, self.max_output_bytes)
        callback_queue: queue.Queue[tuple[str, str] | None] | None = None
        callback_thread: threading.Thread | None = None
        callback_dropped_chars = 0
        callback_chunks_dropped = 0
        callback_drop_lock = threading.Lock()
        callback_start_failed = False

        def _queue_log_callback(stream_name: str, text: str) -> None:
            nonlocal callback_dropped_chars, callback_chunks_dropped
            if callback_queue is None:
                return
            if len(text) > 16_384:
                with callback_drop_lock:
                    callback_dropped_chars += len(text) - 16_384
                text = text[-16_384:]
            try:
                callback_queue.put_nowait((stream_name, text))
            except queue.Full:
                with callback_drop_lock:
                    callback_dropped_chars += len(text)
                    callback_chunks_dropped += 1

        if log_callback:
            callback_queue = queue.Queue(maxsize=_COMMAND_LOG_QUEUE_MAX_CHUNKS)

            def _dispatch_log_callbacks() -> None:
                while True:
                    item = callback_queue.get()
                    try:
                        if item is None:
                            return
                        try:
                            log_callback(*item)
                        except Exception:
                            pass
                    finally:
                        callback_queue.task_done()

            callback_thread = threading.Thread(target=_dispatch_log_callbacks, name="command-log-callback", daemon=True)
            try:
                callback_thread.start()
            except RuntimeError:
                callback_queue = None
                callback_thread = None
                callback_start_failed = True

        reader_error_lock = threading.Lock()
        reader_errors: list[tuple[str, str]] = []

        def _record_reader_error(stream_name: str, error: BaseException) -> None:
            with reader_error_lock:
                reader_errors.append((stream_name, type(error).__name__))

        def _reader(stream: Any, buf: _BoundedStreamBuffer, stream_name: str) -> None:
            nonlocal callback_dropped_chars
            last_callback_time = 0.0
            callback_min_interval = 0.005  # Max ~200 callbacks/sec to prevent downstream lock/choking
            pending_batch: list[str] = []
            pending_chars = 0
            decoder = io.IncrementalNewlineDecoder(
                codecs.getincrementaldecoder("utf-8")(errors="replace"),
                translate=True,
            )
            read_chunk = (
                getattr(stream, "read1", None)
                or getattr(stream, "read", None)
                or getattr(stream, "readline")
            )
            try:
                while True:
                    raw_chunk = read_chunk(2048 if log_callback else 65536)
                    if not raw_chunk:
                        break
                    chunk = raw_chunk if isinstance(raw_chunk, str) else decoder.decode(raw_chunk)
                    if not chunk:
                        continue
                    buf.append(chunk)
                    if log_callback:
                        now = time.monotonic()
                        if now - last_callback_time >= callback_min_interval:
                            if pending_batch:
                                text = "".join(pending_batch) + chunk
                                pending_batch.clear()
                                pending_chars = 0
                            else:
                                text = chunk
                            last_callback_time = now
                            _queue_log_callback(stream_name, text)
                        else:
                            pending_batch.append(chunk)
                            pending_chars += len(chunk)
                            if pending_chars > 16_384:
                                text = "".join(pending_batch)
                                dropped = len(text) - 16_384
                                with callback_drop_lock:
                                    callback_dropped_chars += dropped
                                pending_batch = [text[-16_384:]]
                                pending_chars = 16_384
                tail = decoder.decode(b"", final=True)
                if tail:
                    buf.append(tail)
                    pending_batch.append(tail)
                if log_callback and pending_batch:
                    _queue_log_callback(stream_name, "".join(pending_batch))
            except Exception as exc:
                _record_reader_error(stream_name, exc)
            finally:
                try:
                    stream.close()
                except Exception as exc:
                    _record_reader_error(stream_name, exc)

        t_out = threading.Thread(target=_reader, args=(process.stdout, out_buf, "stdout"), daemon=True)
        t_err = threading.Thread(target=_reader, args=(process.stderr, err_buf, "stderr"), daemon=True)
        started_readers: list[threading.Thread] = []
        try:
            t_out.start()
            started_readers.append(t_out)
            t_err.start()
            started_readers.append(t_err)
        except BaseException as exc:
            cleanup_unconfirmed = False
            if job_handle:
                try:
                    cleanup_unconfirmed = not _terminate_and_confirm_windows_job_empty(job_handle)
                except Exception:
                    cleanup_unconfirmed = True
                if cleanup_unconfirmed:
                    try:
                        tree_cleanup_unconfirmed = not _cleanup_owned_tree()
                        cleanup_unconfirmed = cleanup_unconfirmed or tree_cleanup_unconfirmed
                    except Exception:
                        cleanup_unconfirmed = True
            else:
                try:
                    cleanup_unconfirmed = not _cleanup_owned_tree()
                except Exception:
                    cleanup_unconfirmed = True
            if not cleanup_unconfirmed:
                try:
                    process.wait(timeout=max(2.0, self.terminate_grace_seconds))
                except Exception:
                    cleanup_unconfirmed = True
                cleanup_unconfirmed = cleanup_unconfirmed or process.poll() is None
            for reader in started_readers:
                reader.join(timeout=max(0.1, self.terminate_grace_seconds))
                cleanup_unconfirmed = cleanup_unconfirmed or reader.is_alive()
            for stream, reader in ((process.stdout, t_out), (process.stderr, t_err)):
                if reader in started_readers and reader.is_alive():
                    continue
                try:
                    if stream and not stream.closed:
                        stream.close()
                except Exception:
                    pass
            if callback_queue is not None and callback_thread is not None:
                try:
                    while True:
                        try:
                            callback_queue.get_nowait()
                        except queue.Empty:
                            break
                        callback_queue.task_done()
                    callback_queue.put_nowait(None)
                    callback_thread.join(timeout=0.05)
                    cleanup_unconfirmed = cleanup_unconfirmed or callback_thread.is_alive()
                except Exception:
                    cleanup_unconfirmed = True
            if job_handle:
                try:
                    cleanup_unconfirmed = not close_job_object(job_handle) or cleanup_unconfirmed
                except Exception:
                    cleanup_unconfirmed = True
            self.executed += 1
            return {
                "success": False,
                "exit_code": int(process.returncode or 1),
                "timed_out": False,
                "cancelled": False,
                "aborted_interactive": False,
                "cleanup_unconfirmed": cleanup_unconfirmed,
                "stdout": out_buf.getvalue(),
                "stderr": err_buf.getvalue(),
                "duration_ms": round((time.perf_counter() - process_started) * 1000, 1),
                "error": f"failed to start command pipe reader: {exc}",
            }

        timed_out = False
        cancelled = False
        aborted_interactive = False
        cleanup_unconfirmed = False
        deadline = time.monotonic() + max(1, timeout)
        while not _process_exited_without_reaping(process):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            peek_out = out_buf.peek(500)
            peek_err = err_buf.peek(500)
            if self._is_interactive_prompt(peek_out) or self._is_interactive_prompt(peek_err):
                aborted_interactive = True
                break
            time.sleep(0.02)

        if timed_out or cancelled or aborted_interactive:
            if job_handle:
                try:
                    cleanup_unconfirmed = not _terminate_and_confirm_windows_job_empty(job_handle)
                except Exception:
                    cleanup_unconfirmed = True
                if cleanup_unconfirmed:
                    try:
                        tree_cleanup_unconfirmed = not _cleanup_owned_tree()
                        cleanup_unconfirmed = cleanup_unconfirmed or tree_cleanup_unconfirmed
                    except Exception:
                        cleanup_unconfirmed = True
            else:
                try:
                    cleanup_unconfirmed = not _cleanup_owned_tree()
                except Exception:
                    cleanup_unconfirmed = True
            if not cleanup_unconfirmed:
                try:
                    if os.name == "nt":
                        process.kill()
                except Exception:
                    pass
                try:
                    process.wait(timeout=max(2.0, self.terminate_grace_seconds))
                except Exception:
                    cleanup_unconfirmed = True
                if process.poll() is None:
                    try:
                        if os.name == "nt":
                            process.kill()
                        process.wait(timeout=1.0)
                    except Exception:
                        cleanup_unconfirmed = True
                cleanup_unconfirmed = cleanup_unconfirmed or process.poll() is None
        elif os.name != "nt":
            # A successful leader may leave children that closed their inherited
            # pipes. Kill the command session here as well as when readers stick.
            try:
                cleanup_unconfirmed = not _cleanup_owned_tree()
            except Exception:
                cleanup_unconfirmed = True
        elif job_handle:
            # Windows readers may still be waiting on inherited handles held by
            # descendants after the command leader exits. Terminate the job
            # before joining either reader so a successful call cannot wait for
            # the post-kill drain timeout.
            try:
                cleanup_unconfirmed = not _terminate_and_confirm_windows_job_empty(job_handle)
            except Exception:
                cleanup_unconfirmed = True
            if cleanup_unconfirmed:
                try:
                    tree_cleanup_unconfirmed = not _cleanup_owned_tree()
                    cleanup_unconfirmed = cleanup_unconfirmed or tree_cleanup_unconfirmed
                except Exception:
                    cleanup_unconfirmed = True
        else:
            try:
                cleanup_unconfirmed = not _cleanup_owned_tree()
            except Exception:
                cleanup_unconfirmed = True

        # A successful child can exit before the reader/callback threads finish
        # publishing their last SSE/event chunks.  Keep the drain bounded, but
        # give callback delivery a small scheduler-load margin so callers never
        # observe a successful command before its final stream evidence exists.
        drain_seconds = max(5.0, min(float(self.post_kill_drain_seconds), 10.0))
        drain_deadline = time.monotonic() + drain_seconds
        t_out.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        t_err.join(timeout=max(0.0, drain_deadline - time.monotonic()))
        if t_out.is_alive() or t_err.is_alive():
            if job_handle:
                try:
                    cleanup_unconfirmed = not _terminate_and_confirm_windows_job_empty(job_handle) or cleanup_unconfirmed
                except Exception:
                    cleanup_unconfirmed = True
            else:
                if not cleanup_unconfirmed:
                    try:
                        process.wait(timeout=1.0)
                    except Exception:
                        pass
                try:
                    cleanup_unconfirmed = cleanup_unconfirmed or not _cleanup_owned_tree()
                except Exception:
                    cleanup_unconfirmed = True
        if job_handle:
            try:
                job_closed = close_job_object(job_handle)
            except Exception:
                job_closed = False
            if not job_closed:
                try:
                    cleanup_unconfirmed = not _terminate_and_confirm_windows_job_empty(job_handle) or cleanup_unconfirmed
                except Exception:
                    pass
                try:
                    job_closed = close_job_object(job_handle)
                except Exception:
                    job_closed = False
            cleanup_unconfirmed = (not job_closed) or cleanup_unconfirmed
            job_handle = None
        if t_out.is_alive() or t_err.is_alive():
            cleanup_deadline = time.monotonic() + 1.0
            t_out.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            t_err.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))
            cleanup_unconfirmed = cleanup_unconfirmed or t_out.is_alive() or t_err.is_alive()

        for stream, reader in ((process.stdout, t_out), (process.stderr, t_err)):
            if reader.is_alive():
                continue
            try:
                if stream and not stream.closed:
                    stream.close()
            except Exception:
                pass
        if not cleanup_unconfirmed:
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass

        callback_delivery_unconfirmed = callback_start_failed
        if callback_queue is not None and callback_thread is not None:
            callback_deadline = time.monotonic() + min(1.0, max(0.1, float(self.post_kill_drain_seconds)))
            with callback_queue.all_tasks_done:
                while callback_queue.unfinished_tasks and time.monotonic() < callback_deadline:
                    callback_queue.all_tasks_done.wait(timeout=max(0.0, callback_deadline - time.monotonic()))
                callbacks_drained = callback_queue.unfinished_tasks == 0
            while True:
                try:
                    item = callback_queue.get_nowait()
                except queue.Empty:
                    break
                if item is not None:
                    with callback_drop_lock:
                        callback_dropped_chars += len(item[1])
                        callback_chunks_dropped += 1
                callback_queue.task_done()
            callback_queue.put_nowait(None)
            callback_thread.join(timeout=0.05)
            # Once all queued callbacks have completed, a worker still exiting
            # after its sentinel cannot make their delivery uncertain.
            callback_delivery_unconfirmed = not callbacks_drained

        with reader_error_lock:
            reader_error = reader_errors[0] if reader_errors else None
        capture_unconfirmed = bool(reader_error or t_out.is_alive() or t_err.is_alive())
        stdout = out_buf.getvalue()
        stderr = err_buf.getvalue()
        capture_finished = time.perf_counter()
        self.executed += 1
        return {
            "success": (
                (not timed_out)
                and (not cancelled)
                and (not aborted_interactive)
                and (not cleanup_unconfirmed)
                and (not capture_unconfirmed)
                and process.returncode == 0
            ),
            "exit_code": -9 if (timed_out or cancelled or aborted_interactive) else int(process.returncode or 0),
            "timed_out": timed_out, "cancelled": cancelled, "aborted_interactive": aborted_interactive,
            "cleanup_unconfirmed": cleanup_unconfirmed,
            **({"outcome_unknown": True, "fail_closed": True, "retryable": False} if cleanup_unconfirmed else {}),
            "output_capture_unconfirmed": capture_unconfirmed,
            "stdout": stdout, "stderr": stderr,
            "duration_ms": round((capture_finished - started) * 1000, 1),
            "discarded_output_chars": out_buf.discarded_chars + err_buf.discarded_chars,
            "phase_timings_ms": {
                "shell_startup_ms": round((process_started - started) * 1000, 3),
                "stream_capture_ms": round((capture_finished - process_started) * 1000, 3),
            },
            "log_chunks_dropped": callback_chunks_dropped,
            **({"log_callback_dropped_chars": callback_dropped_chars} if callback_dropped_chars else {}),
            **({"log_callback_delivery_unconfirmed": True} if callback_delivery_unconfirmed else {}),
            **(
                {"error": "interactive_prompt_detected: command aborted because it requested interactive input"} if aborted_interactive
                else {"error": "command cancelled"} if cancelled
                else {"error": f"command timed out after {timeout}s"} if timed_out
                else {"error": f"failed to capture {reader_error[0]} command output ({reader_error[1]})"} if reader_error
                else {"error": "command output capture did not complete"} if capture_unconfirmed
                else {}
            ),
        }

    def _resolve_project_command(
        self,
        alias: str,
        cwd: str,
        *,
        args: Sequence[str] = (),
    ) -> _ResolvedProjectCommand:
        """Resolve one explicit project alias without invoking a process."""
        from .project_config import (
            CommandDefinition,
            ProjectConfigError,
        )

        if not isinstance(alias, str) or not _PROJECT_COMMAND_ALIAS_RE.fullmatch(alias):
            raise ProjectConfigError("invalid_command_alias")
        if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
            raise ProjectConfigError("invalid_command_arguments")
        if len(args) > _MAX_PROJECT_COMMAND_ARGS or any(
            not isinstance(item, str) or len(item) > 4096 or "\x00" in item
            for item in args
        ):
            raise ProjectConfigError("invalid_command_arguments")

        context = self._cached_project_command_context(
            cwd, configured_state_dir(self.config)
        )
        command_root = Path(cwd).expanduser().resolve(strict=True)
        try:
            command_root.relative_to(context.root)
        except ValueError:
            raise ProjectConfigError("command_outside_project") from None

        if not isinstance(context.config_digest, str) or not context.config_digest:
            raise ProjectConfigError("invalid_config")
        definition = context.settings.commands.get(alias)
        if definition is None:
            raise ProjectConfigError("command_alias_not_found")

        command_env_references = dict(context.settings.env_references)
        if isinstance(definition, str):
            if args:
                raise ProjectConfigError("string_command_does_not_accept_arguments")
            command: str | CommandInvocation = definition
            configured_command: str | CommandInvocation = definition
        elif isinstance(definition, CommandDefinition):
            command_env_references.update(definition.env_references)
            configured_command = CommandInvocation(
                argv=list(definition.argv),
                cwd=str(command_root),
                shell=False,
            )
            invocation = CommandInvocation(
                argv=[*definition.argv, *args],
                cwd=str(command_root),
                shell=False,
            )
            invocation_result = validate_invocation(invocation)
            if not invocation_result.get("safe"):
                raise ProjectConfigError("invalid_command_definition")
            command = invocation
        else:
            raise ProjectConfigError("invalid_command_definition")

        project_environment = dict(context.settings.env)
        if len(project_environment) + len(command_env_references) > _MAX_PROJECT_COMMAND_ENV_ENTRIES:
            raise ProjectConfigError("invalid_command_environment")
        environment: dict[str, str] = {}
        environment_size = 0
        for target_name, value in project_environment.items():
            if (
                not isinstance(target_name, str)
                or not _is_valid_project_command_env_key(target_name)
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise ProjectConfigError("invalid_command_environment")
            environment_size += len(target_name.encode("utf-8")) + len(value.encode("utf-8"))
            if environment_size > _MAX_PROJECT_COMMAND_ENV_BYTES:
                raise ProjectConfigError("command_environment_too_large")
            environment[target_name] = value

        for target_name, source_name in command_env_references.items():
            if (
                not isinstance(target_name, str)
                or not _is_valid_project_command_env_key(target_name)
                or not isinstance(source_name, str)
                or not _PROJECT_COMMAND_ENV_KEY_RE.fullmatch(source_name)
            ):
                raise ProjectConfigError("invalid_command_environment")
            if source_name not in os.environ:
                raise ProjectConfigError("command_environment_unavailable")
            value = os.environ[source_name]
            if not isinstance(value, str) or "\x00" in value:
                raise ProjectConfigError("invalid_command_environment")
            environment_size += len(target_name.encode("utf-8")) + len(value.encode("utf-8"))
            if environment_size > _MAX_PROJECT_COMMAND_ENV_BYTES:
                raise ProjectConfigError("command_environment_too_large")
            environment[target_name] = value

        cache_context = stable_hash(
            {
                "alias": alias,
                "config_digest": context.config_digest,
                "environment": environment,
            }
        )
        return _ResolvedProjectCommand(
            alias=alias,
            command=command,
            environment=environment,
            config_digest=context.config_digest,
            cache_context=cache_context,
            configured_command=configured_command,
            caller_arguments=tuple(args),
        )
