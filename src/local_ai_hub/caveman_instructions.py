"""Stage candidate instruction compression without changing the source."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .process_utils import windows_creationflags


@dataclass(frozen=True)
class StagedInstruction:
    source: Path
    backup: Path
    candidate: Path | None
    original_sha256: str
    backup_sha256: str
    candidate_sha256: str | None
    semantic_review: dict[str, object] | None
    duration_seconds: float


def compact_local_prompt(
    prompt: str,
    system: str,
    *,
    input_enabled: bool,
    output_enabled: bool,
    structured: bool,
) -> tuple[str, str]:
    """Compact safe plain-text input and request concise natural-language output."""
    if structured:
        return prompt, system
    if input_enabled is True and not re.search(r"```|`|\t|(?m:^ {4})|(?m:^\s*[-*#>|+*-])|[{}\[\]]|^\s*\|", prompt):
        prompt = re.sub(r"[ \t]+$", "", prompt, flags=re.MULTILINE)
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
        prompt = re.sub(r" {2,}", " ", prompt)
    if output_enabled is True:
        system = system.rstrip() + "\nAnswer in concise Caveman style. Preserve every relevant fact, requirement, constraint, exception, uncertainty, and requested structure. Never omit technical detail."
    return prompt, system


def _protected(text: str) -> Counter[str]:
    # Deterministic preservation gates precede the independent semantic review.
    pattern = (
        r"(?m:\A---\r?\n[\s\S]*?\r?\n---\s*$)|```[^\n]*\n[\s\S]*?```|`[^`\n]+`|https?://[^\s)]+|"
        r"(?m:^#{1,6}[^\n]*$)|\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%|"
        r"(?<!\w)(?:\.{0,2}/|[A-Za-z]:\\)[^\s`),;]+|"
        r"(?<!\w)[A-Za-z0-9_.-]+\.(?:py|js|ts|toml|yaml|yml|json|md|mdc|ps1|sh)(?!\w)|"
        r"(?<!\w)\d+(?:\.\d+)*(?!\w)"
    )
    return Counter(re.findall(pattern, text))


def _protected_order(text: str) -> list[str]:
    pattern = r"```[^\n]*\n[\s\S]*?```|`[^`\n]+`|https?://[^\s)]+|(?m:^#{1,6}[^\n]*$)"
    ordered = re.findall(pattern, text)
    lists = re.findall(r"(?m)^(\s*)([-*+]|\d+[.)])\s+", text)
    tables = [line.count("|") for line in text.splitlines() if line.strip().startswith("|")]
    return [*ordered, *(f"LIST:{indent}:{marker}" for indent, marker in lists), *(f"TABLE:{pipes}" for pipes in tables)]


_INSTRUCTION_NAMES = {
    "agents.md", "claude.md", "gemini.md", "codex.md", "copilot.md",
    "agent.md", "copilot-instructions.md", "instructions.md", "mcp.md", "mcp-instructions.md",
    "mcp-server.md", "skill.md", "rules.md", "prompt.md", "agent-instructions.md",
    ".instructions.md", ".prompt.md",
}
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "worktrees",
    "site-packages", "dist", "target", "cache", "caches", "backups",
    "vendor", "plugins", "memories", "sessions", "projects", "debug", "logs",
    "history", "telemetry", "attachments", "artifacts", "state", "temp",
}


def discover_instruction_files(roots: list[Path]) -> list[Path]:
    """Find agent instructions under explicit roots; skip managed/vendor trees."""
    found: set[Path] = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser().absolute()
        if _has_reparse_ancestor(root) or not root.is_dir():
            raise ValueError(f"instruction root must be a regular directory: {root}")
        if any(part.casefold() in {"plugins", "cache", "caches"} for part in root.parts):
            raise ValueError(f"managed plugin/cache roots are excluded: {root}")
        root = root.resolve(strict=True)
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            base = Path(current)
            dirnames[:] = sorted(
                name for name in dirnames
                if name.casefold() not in _SKIP_DIRS
                and not _has_reparse_ancestor(base / name)
                and not name.casefold().endswith(".original")
            )
            for name in filenames:
                path = base / name
                lower = name.casefold()
                if lower.endswith(".original.md") or _has_reparse_ancestor(path):
                    continue
                parts = [part.casefold() for part in path.relative_to(root).parts[:-1]]
                in_rules = any(part in {"skills", "rules", "instructions", "prompts", "mcp-prompts"} for part in parts)
                in_agent_specs = "agents" in parts
                if lower in _INSTRUCTION_NAMES or (in_rules and (lower in {"readme.md", "mcp.md", "instructions.md"} or lower.endswith((".mdc", ".md", ".txt")))) or (in_agent_specs and lower.endswith(".md")):
                    found.add(path.resolve(strict=True))
    return sorted(found, key=lambda p: str(p).casefold())


def _has_reparse_ancestor(path: Path) -> bool:
    for item in (path, *path.parents):
        try:
            mode = item.lstat()
        except FileNotFoundError:
            continue
        attrs = getattr(mode, "st_file_attributes", 0)
        if item.is_symlink() or attrs & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            return True
    return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_openai_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("model endpoint must be local HTTP")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _safe_replace(path: Path, data: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.caveman-{os.getpid()}-{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def backup_instruction(source: Path, stage_root: Path) -> StagedInstruction:
    started = time.perf_counter()
    source = Path(source).expanduser().absolute()
    if source.suffix.lower() not in {".md", ".mdc", ".txt"} or re.search(r"secret|credential|password|token|private|\.env", source.name, re.I):
        raise ValueError("source is not an eligible instruction file")
    if _has_reparse_ancestor(source) or not source.is_file():
        raise ValueError("source must be a regular non-symlink file")
    source = source.resolve(strict=True)
    stage_root = Path(stage_root).expanduser().absolute()
    stage_root.mkdir(parents=True, exist_ok=True)
    if _has_reparse_ancestor(stage_root):
        raise ValueError("staging path cannot traverse a symlink or junction")
    stage_root = stage_root.resolve(strict=True)
    if stage_root == source.parent or source.parent in stage_root.parents or stage_root in source.parents:
        raise ValueError("staging must be outside the source tree")
    original = source.read_bytes()
    if len(original) > 1024 * 1024:
        raise ValueError("instruction file exceeds 1 MiB")
    text = original.decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    folder = Path(tempfile.mkdtemp(prefix="instruction-", dir=stage_root))
    backup = folder / f"original{source.suffix.lower()}"
    backup.write_bytes(original)
    original_sha256 = _sha256(original)
    backup_bytes = backup.read_bytes()
    backup_sha256 = _sha256(backup_bytes)
    if backup_sha256 != original_sha256:
        raise OSError("backup verification failed")
    manifest = {"source": str(source), "original_sha256": original_sha256, "backup_sha256": backup_sha256}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return StagedInstruction(
        source=source, backup=backup, candidate=None, original_sha256=original_sha256,
        backup_sha256=backup_sha256, candidate_sha256=None, semantic_review=None,
        duration_seconds=time.perf_counter() - started,
    )


def compress_backed_up_instruction(
    prepared: StagedInstruction,
    compressor: Callable[[str], str],
    reviewer: Callable[[str, str], dict[str, object]],
) -> StagedInstruction:
    started = time.perf_counter()
    if prepared.candidate is not None or prepared.candidate_sha256 is not None:
        raise ValueError("instruction already has a staged candidate")
    source = prepared.source
    original = prepared.backup.read_bytes()
    if _sha256(original) != prepared.original_sha256 or prepared.backup_sha256 != prepared.original_sha256:
        raise ValueError("verified backup changed; refusing compression")
    if _sha256(source.read_bytes()) != prepared.original_sha256:
        raise ValueError("source changed after backup; refusing compression")
    text = original.decode("utf-8")
    output = compressor(text)
    if not isinstance(output, str) or not output.strip():
        raise ValueError("compressor returned empty or invalid text")
    if _protected(text) - _protected(output) or _protected_order(text) != _protected_order(output):
        raise ValueError("compressed text changed protected content")
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    newline = "\r\n" if b"\r\n" in original else "\n"
    candidate_bytes = output.replace("\n", newline).encode("utf-8")
    if len(candidate_bytes) >= len(original):
        raise ValueError("compressed candidate does not reduce source size")
    review = reviewer(text, output)
    if not isinstance(review, dict):
        raise ValueError("semantic review returned invalid result")
    for key in ("missing", "weakened", "changed", "uncertain"):
        if review.get(key) != []:
            raise ValueError(f"semantic review found {key} content")
    if review.get("equivalent") is not True:
        raise ValueError("semantic review did not affirm equivalence")
    if _sha256(source.read_bytes()) != prepared.original_sha256:
        raise ValueError("source changed while compression ran")
    candidate = prepared.backup.parent / f"candidate{source.suffix.lower()}"
    candidate.write_bytes(candidate_bytes)
    candidate_bytes = candidate.read_bytes()
    result = StagedInstruction(
        source=source, backup=prepared.backup, candidate=candidate,
        original_sha256=prepared.original_sha256, backup_sha256=prepared.backup_sha256,
        candidate_sha256=_sha256(candidate_bytes), semantic_review=review,
        duration_seconds=time.perf_counter() - started,
    )
    (candidate.parent / "manifest.json").write_text(json.dumps({
        "source": str(source), "backup": str(result.backup), "candidate": str(candidate),
        "original_sha256": result.original_sha256,
        "backup_sha256": result.backup_sha256, "candidate_sha256": result.candidate_sha256,
        "semantic_review": review,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def stage_instruction(
    source: Path,
    stage_root: Path,
    compressor: Callable[[str], str],
    reviewer: Callable[[str, str], dict[str, object]],
) -> StagedInstruction:
    return compress_backed_up_instruction(backup_instruction(source, stage_root), compressor, reviewer)


def apply_instruction(staged: StagedInstruction) -> None:
    """Apply a reviewed candidate only while source and verified backup still match."""
    source = staged.source
    if staged.candidate is None or staged.candidate_sha256 is None or staged.semantic_review is None:
        raise ValueError("instruction has no reviewed candidate")
    if staged.semantic_review.get("equivalent") is not True or any(
        staged.semantic_review.get(key) != [] for key in ("missing", "weakened", "changed", "uncertain")
    ):
        raise ValueError("candidate lacks a clean semantic review")
    if _has_reparse_ancestor(source) or _sha256(source.read_bytes()) != staged.original_sha256:
        raise ValueError("source changed after staging; refusing apply")
    backup = staged.backup.read_bytes()
    candidate = staged.candidate.read_bytes()
    if _sha256(backup) != staged.backup_sha256 or _sha256(backup) != staged.original_sha256:
        raise ValueError("verified backup changed; refusing apply")
    if _sha256(candidate) != staged.candidate_sha256:
        raise ValueError("candidate changed after review; refusing apply")
    _safe_replace(source, candidate)
    if _sha256(source.read_bytes()) != staged.candidate_sha256:
        raise OSError(f"applied candidate verification failed; verified backup retained at {staged.backup}")


def restore_instruction(staged: StagedInstruction) -> None:
    """Restore the original only if the source still contains this candidate."""
    if _has_reparse_ancestor(staged.source):
        raise ValueError("source path changed to a symlink or junction; refusing restore")
    if staged.candidate is None or staged.candidate_sha256 is None:
        raise ValueError("instruction has no staged candidate")
    if _sha256(staged.candidate.read_bytes()) != staged.candidate_sha256:
        raise ValueError("candidate changed; refusing restore")
    if _sha256(staged.source.read_bytes()) != staged.candidate_sha256:
        raise ValueError("source changed after apply; refusing restore")
    original = staged.backup.read_bytes()
    if _sha256(original) != staged.original_sha256:
        raise ValueError("verified backup changed; refusing restore")
    _safe_replace(staged.source, original)


def restore_instruction_manifest(manifest_path: Path) -> None:
    """Restore a staged instruction from its durable manifest after hash checks."""
    manifest_path = Path(manifest_path).expanduser().absolute()
    if _has_reparse_ancestor(manifest_path) or not manifest_path.is_file():
        raise ValueError("Caveman manifest must be a regular non-symlink file")
    manifest_path = manifest_path.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"source", "backup", "candidate", "original_sha256", "backup_sha256", "candidate_sha256", "semantic_review"}
    if not isinstance(manifest, dict) or not required.issubset(manifest):
        raise ValueError("Caveman manifest is incomplete")
    folder = manifest_path.parent
    source = Path(manifest["source"]).expanduser().absolute()
    backup = Path(manifest["backup"]).expanduser().absolute()
    candidate = Path(manifest["candidate"]).expanduser().absolute()
    if any(_has_reparse_ancestor(path) for path in (source, backup, candidate)):
        raise ValueError("Caveman manifest paths cannot contain symlinks or junctions")
    if backup.parent != folder or candidate.parent != folder or source == folder or folder in source.parents:
        raise ValueError("Caveman manifest paths escape their verified staging folder")
    for key in ("original_sha256", "backup_sha256", "candidate_sha256"):
        value = manifest[key]
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Caveman manifest contains an invalid hash")
    if not isinstance(manifest["semantic_review"], dict):
        raise ValueError("Caveman manifest semantic review is invalid")
    staged = StagedInstruction(
        source=source, backup=backup, candidate=candidate,
        original_sha256=manifest["original_sha256"], backup_sha256=manifest["backup_sha256"],
        candidate_sha256=manifest["candidate_sha256"], semantic_review=manifest["semantic_review"],
        duration_seconds=0.0,
    )
    restore_instruction(staged)


def review_instruction_semantics(original: str, candidate: str, *, model: str, endpoint: str) -> dict[str, object]:
    """Ask a local model for a conservative, structured entailment review."""
    api_base = _local_openai_endpoint(endpoint)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("semantic review model is required")
    if len(original) + len(candidate) > 48_000:
        raise ValueError("instruction exceeds semantic review context cap")
    url = f"{api_base}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 512,
        "stream": False,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Conservative semantic-equivalence auditor. Compare every instruction, prohibition, scope, condition, exception, precedence, fact, procedure, and requested structure. Candidate is equivalent only if it preserves all meaning. If uncertain, fail. Return JSON only: {\"equivalent\":boolean,\"missing\":[],\"weakened\":[],\"changed\":[],\"uncertain\":[]}. Every array contains concise issue descriptions."},
            {"role": "user", "content": f"ORIGINAL:\\n{original}\\n\\nCANDIDATE:\\n{candidate}"},
        ],
    }

    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise HTTPError(req.full_url, code, "redirect refused for local model endpoint", headers, fp)

    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect).open(request, timeout=180) as response:
            result = json.loads(response.read(2_000_001))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("local semantic review failed") from exc
    if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
        raise ValueError("local semantic reviewer returned invalid response")
    content = result["choices"][0].get("message", {}).get("content")
    review = json.loads(content) if isinstance(content, str) else None
    if not isinstance(review, dict) or type(review.get("equivalent")) is not bool:
        raise ValueError("local semantic reviewer returned invalid verdict")
    for key in ("missing", "weakened", "changed", "uncertain"):
        if not isinstance(review.get(key), list):
            raise ValueError("local semantic reviewer omitted issue lists")
    return review


def compress_with_caveman(text: str, *, skill_dir: Path, model: str, endpoint: str) -> str:
    """Run the installed upstream skill against a temporary copy via a local provider."""
    api_base = _local_openai_endpoint(endpoint)
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
                   CAVEMAN_COMPRESS_ENDPOINT=api_base, LOCALAPPDATA=temp, XDG_DATA_HOME=temp,
                   NO_PROXY="*", no_proxy="*")
        env.pop("CAVEMAN_COMPRESS_API_KEY", None)
        (scratch / "sitecustomize.py").write_text(
            "import urllib.error, urllib.request\n"
            "class _NoRedirect(urllib.request.HTTPRedirectHandler):\n"
            " def redirect_request(self, req, fp, code, msg, headers, newurl):\n"
            "  raise urllib.error.HTTPError(req.full_url, code, 'redirect refused for local provider', headers, fp)\n"
            "urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()))\n",
            encoding="utf-8",
        )
        prior_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(scratch) + (os.pathsep + prior_pythonpath if prior_pythonpath else "")
        try:
            result = subprocess.run([sys.executable, "-m", "scripts", str(path)], cwd=skill_dir, env=env,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=300, creationflags=windows_creationflags())
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("caveman compression timed out") from exc
        if result.returncode != 0:
            diagnostics = f"{result.stdout}\n{result.stderr}"
            if "output is identical to input" in diagnostics:
                reason = "upstream found no useful reduction"
            elif "returned an empty response" in diagnostics:
                reason = "local model returned an empty response"
            elif "Skipping (not natural language)" in diagnostics:
                reason = "upstream rejected non-natural-language content"
            elif "Compression aborted:" in diagnostics:
                reason = "upstream validation rejected the candidate"
            else:
                reason = "upstream compressor refused the file"
            raise RuntimeError(f"caveman compression failed: {reason} (exit code {result.returncode})")
        return path.read_text(encoding="utf-8")
