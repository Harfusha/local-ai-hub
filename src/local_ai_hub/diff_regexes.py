from __future__ import annotations

import re

_DIFF_SHELL_I = re.compile(r"\b(exec|system|shell_exec|subprocess|Process\.Start|Runtime\.getRuntime)\b", re.I)
_DIFF_EVAL_I = re.compile(r"\b(eval|exec)\s*\(", re.I)
_DIFF_SECRET_PASSWORD_I = re.compile(r"\b(password|secret|api[_-]?key|private[_-]?key|token)\b", re.I)
