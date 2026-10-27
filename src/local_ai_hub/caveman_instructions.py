"""Stage candidate instruction compression without changing the source."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.parse import urlsplit

from .process_utils import windows_creationflags


@dataclass(frozen=True)
class StagedInstruction:
    source: Path
    backup: Path
    candidate: Path


def compact_local_prompt(prompt: str, system: str, *, enabled: bool, structured: bool) -> tuple[str, str]:
    """Optionally compact plain prose spacing and request concise natural-language output."""
    if enabled is not True or structured:
        return prompt, system
    if not re.search(r"```|`|\t|(?m:^ {4})|(?m:^\s*[-*#>])|[{}\[\]]", prompt):
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
    system = system.rstrip() + "\nBe concise. Preserve all relevant facts, constraints, uncertainty, and requested structure."
    return prompt, system


def _protected(text: str) -> Counter[str]:
    # These checks are necessary, not proof of semantic equivalence.
    pattern = r"```[^\n]*\n[\s\S]*?```|`[^`\n]+`|https?://[^\s)]+|(?m:^#{1,6}[^\n]*$)"
    return Counter(re.findall(pattern, text))


def stage_instruction(source: Path, stage_root: Path, compressor: Callable[[str], str]) -> StagedInstruction:
    source = Path(source)
    if source.suffix.lower() not in {".md", ".txt"} or re.search(r"secret|credential|password|token|private|\.env", source.name, re.I):
        raise ValueError("source is not an eligible instruction file")
    if source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular non-symlink file")
    source = source.resolve(strict=True)
    stage_root = Path(stage_root).resolve()
    if stage_root == source.parent or source.parent in stage_root.parents:
        raise ValueError("staging must be outside the source directory")
    original = source.read_bytes()
    if len(original) > 1024 * 1024:
        raise ValueError("instruction file exceeds 1 MiB")
    text = original.decode("utf-8")
    stage_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="instruction-", dir=stage_root))
    backup = folder / "original"
    backup.write_bytes(original)
    if backup.read_bytes() != original:
        raise OSError("backup verification failed")
    output = compressor(text)
    if not isinstance(output, str) or not output.strip():
        raise ValueError("compressor returned empty or invalid text")
    if _protected(text) - _protected(output):
        raise ValueError("compressed text changed protected content")
    if source.read_bytes() != original:
        raise ValueError("source changed while compression ran")
    candidate = folder / "candidate.md"
    candidate.write_text(output, encoding="utf-8", newline="")
    return StagedInstruction(source=source, backup=backup, candidate=candidate)


def compress_with_caveman(text: str, *, skill_dir: Path, model: str, endpoint: str) -> str:
    """Run the installed upstream skill against a temporary copy via a local provider."""
    endpoint_parts = urlsplit(endpoint)
    if (endpoint_parts.scheme != "http" or endpoint_parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or endpoint_parts.username or endpoint_parts.password or endpoint_parts.query or endpoint_parts.fragment):
        raise ValueError("caveman endpoint must be a local HTTP endpoint")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("caveman model is required")
    skill_dir = Path(skill_dir).resolve(strict=True)
    if not (skill_dir / "scripts" / "__main__.py").is_file():
        raise ValueError("caveman-compress skill scripts not found")
    with tempfile.TemporaryDirectory(prefix="lah-caveman-") as temp:
        scratch = Path(temp)
        path = scratch / "instruction.md"
        path.write_text(text, encoding="utf-8", newline="")
        env = dict(os.environ)
        env.update(CAVEMAN_COMPRESS_PROVIDER="openai-compat", CAVEMAN_COMPRESS_MODEL=model,
                   CAVEMAN_COMPRESS_ENDPOINT=endpoint, LOCALAPPDATA=temp, XDG_DATA_HOME=temp,
                   NO_PROXY="*", no_proxy="*")
        env.pop("CAVEMAN_COMPRESS_API_KEY", None)
        try:
            result = subprocess.run([sys.executable, "-m", "scripts", str(path)], cwd=skill_dir, env=env,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=300, creationflags=windows_creationflags())
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("caveman compression timed out") from exc
        if result.returncode != 0:
            raise RuntimeError(f"caveman compression failed with exit code {result.returncode}")
        return path.read_text(encoding="utf-8")
