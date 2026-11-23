from __future__ import annotations

from collections.abc import Sequence
import ntpath
import os
from pathlib import Path
import re
import shutil
from typing import Any

from .command_policy import (
    _classification_result,
    classify_command_sequence,
    classify_pipeline_filter,
    contains_user_whitelisted_tool,
    normalize_user_whitelisted_tools,
)
from .command_python import (
    is_python_interpreter_name,
    is_well_formed_command_input,
)
from .command_shell import (
    is_powershell_command,
    needs_shell,
    split_shell_command,
    strip_null_redirections,
    tokenize_command,
)

class CommandClassificationMixin:
    def _classify(self, command: str | Sequence[str]) -> dict[str, Any]:
        if not isinstance(command, str):
            return self._classify_single(command)
        cfg = self.config.get("commands", {})
        trimmed = self._strip_null_redirections(command.strip())
        if not trimmed:
            return _classification_result(
                "unknown", cacheable=False, allowed=False,
                reason="empty or unparsable command",
            )

        # Direct PowerShell syntax or explicit pwsh/powershell invocation
        if self._is_powershell_command(trimmed) or trimmed.lower().startswith(("pwsh", "powershell")):
            return self._classify_single(trimmed)

        # Compound sequences (; or &&) outside quotes
        seq_parts = self._split_outside_quotes(trimmed, (";", "&&"))
        if len(seq_parts) > 1:
            classifications = []
            for _, subcmd in seq_parts:
                sub_res = self.classify(subcmd)
                classifications.append(sub_res)
            return classify_command_sequence(classifications, cfg)

        # Pipelines (|) outside quotes
        pipe_parts = self._split_outside_quotes(trimmed, ("|",))
        if len(pipe_parts) > 1:
            first_delim, first_cmd = pipe_parts[0]
            first_res = self._classify_single(first_cmd)
            if not first_res.get("allowed"):
                return first_res
            for _, stage in pipe_parts[1:]:
                stok = self._tokens(stage)
                pipeline_filter_result = classify_pipeline_filter(
                    stok, self.READ_FILTERS, self.READ_ONLY
                )
                if pipeline_filter_result is not None:
                    return pipeline_filter_result
            return _classification_result(
                str(first_res.get("class", "read")), cacheable=False,
                allowed=True,
                replay_safe=bool(first_res.get("replay_safe", False)),
                reason="pipeline with safe filters",
            )

        return self._classify_single(trimmed)
    @staticmethod
    def _is_powershell_command(cmd: str) -> bool:
        return is_powershell_command(cmd)
    @staticmethod
    def _is_python_interpreter_name(executable: str) -> bool:
        return is_python_interpreter_name(executable)
    @classmethod
    def _needs_shell(cls, command: str) -> bool:
        return needs_shell(command)
    def _replay_safety(self, command: str | Sequence[str], result: dict[str, Any]) -> bool:
        if not result.get("allowed"):
            return False

        if isinstance(command, str):
            trimmed = self._strip_null_redirections(command.strip())
            sequence = self._split_outside_quotes(trimmed, (";", "&&"))
            if len(sequence) > 1:
                return all(self.classify(part).get("replay_safe", False) for _, part in sequence)
            pipeline = self._split_outside_quotes(trimmed, ("|",))
            if len(pipeline) > 1:
                return all(self.classify(part).get("replay_safe", False) for _, part in pipeline)
            tokens = self._tokens(trimmed)
        else:
            tokens = [str(part) for part in command]

        if not tokens:
            return False

        exe = ntpath.basename(tokens[0].strip('"').replace("/", "\\")).lower()
        exe_base = re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", exe)
        command_class = result.get("class")
        if self._is_python_interpreter_name(exe_base):
            for index, token in enumerate(tokens[1:], 1):
                if token == "-m" and index + 1 < len(tokens):
                    module = tokens[index + 1].lower()
                    if module == "compileall" or module not in self.KNOWN_PYTHON_MODULES:
                        return False
                    break
        if command_class == "read":
            return True
        if command_class != "validation":
            return False
        # Classified validation is replay-safe by default; concrete side effects
        # must be rejected above or classified outside the validation class.
        return True
    @staticmethod
    def _safe_label(command: str) -> str:
        # Local dashboard metadata only; redact common credential-bearing options.
        text = re.sub(r"(?i)(--?(?:password|token|secret|api[-_]?key)\s*[= ]\s*)([^\s]+)", r"\1***", command.strip())
        text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1***", text)
        return text[:240]
    @staticmethod
    def _split_outside_quotes(s: str, delimiters: tuple[str, ...]) -> list[tuple[str, str]]:
        return split_shell_command(s, delimiters)
    @staticmethod
    def _strip_null_redirections(cmd: str) -> str:
        return strip_null_redirections(cmd)
    @staticmethod
    def _tokens(command: str) -> list[str]:
        return tokenize_command(command)
    def _tool_identity(
        self,
        command: str,
        cwd: str,
        *,
        argv_override: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        if argv_override is None and self._needs_shell(command):
            raw = (shutil.which("pwsh") or shutil.which("powershell") or "powershell") if os.name == "nt" else (shutil.which("sh") or "/bin/sh")
            candidate = Path(raw)
            try:
                stat = candidate.stat()
                return {"path": str(candidate.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
            except Exception:
                return {"path": str(candidate)}
        tokens = list(argv_override) if argv_override is not None else self._tokens(command)
        if not tokens:
            return {}
        raw = tokens[0].strip('"')
        candidate = Path(raw)
        if not candidate.is_absolute():
            which_hit = shutil.which(raw) if os.name == "nt" else None
            if which_hit:
                resolved = Path(which_hit)
            else:
                local = (Path(cwd) / candidate).resolve(strict=False)
                resolved = local if local.exists() else Path(shutil.which(raw) or raw)
        else:
            resolved = candidate
        try:
            stat = resolved.stat()
            return {"path": str(resolved.resolve()), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except Exception:
            return {"path": str(resolved)}
    @classmethod
    def _well_formed_command_input(cls, command: Any) -> bool:
        """Check command/argv structure before an unknown command can be opted in."""
        return is_well_formed_command_input(
            command,
            tokenize=cls._tokens,
            strip_null_redirections=cls._strip_null_redirections,
            python_interpreter_name=cls._is_python_interpreter_name,
        )
    def classify(self, command: str | Sequence[str]) -> dict[str, Any]:
        result = dict(self._classify(command))
        text = command if isinstance(command, str) else " ".join(str(part) for part in command)
        extra_allowed = normalize_user_whitelisted_tools(
            self.config.get("commands", {}).get("extra_allowed_tools", [])
        )
        user_whitelisted = contains_user_whitelisted_tool(text, extra_allowed)
        if user_whitelisted:
            result["cacheable"] = False
        result["replay_safe"] = bool(not user_whitelisted and self._replay_safety(command, result))
        return result
