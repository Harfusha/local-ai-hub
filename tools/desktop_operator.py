"""Fixed local operator CLI catalog shared by the Rust desktop and its bridge.

Only named operations and typed fields become argv; no shell, caller-provided
flags, commands or executable paths. Existing hubctl validation remains final.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

CLIENTS = ("antigravity", "codex", "claude", "opencode", "cursor", "windsurf",
           "devin", "vscode", "gemini_cli")


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"
    required: bool = False
    choices: tuple[str, ...] = ()
    allow_empty: bool = False


@dataclass(frozen=True)
class Operation:
    argv: tuple[str, ...]
    fields: tuple[Field, ...] = ()
    mutation: bool = False
    root: bool = False
    timeout: int = 60
    json_output: bool = True


CLIENT = Field("client", "Agent client (empty = auto-detect)", "choice", choices=CLIENTS)
LIMIT = Field("limit", "Maximum records (1–1000)", "integer")
TASK = Field("task-id", "Task ID", required=True)
REVISION = Field("expected-revision", "Expected revision (empty for create)", required=True, allow_empty=True)
RECORD = Field("record-file", "Local JSON record or batch file", "file", True)
OP_ID = Field("operation-id", "Stable operation ID")
REQUIRED_OP = Field("operation-id", "Stable operation ID", required=True)
DIGEST = Field("preview-digest", "Reviewed preview digest", required=True)
HANDOFF = Field("handoff-id", "Handoff ID", required=True)
FINDING = Field("finding-id", "Finding ID", required=True)
SUBJECT = Field("subject-digest", "Subject digest", required=True)
REASON = Field("reason", "Reason", required=True)
QUERY = Field("query", "Query")
PROJECT = Field("project-id", "Explicit project UUID")
MODE = Field("knowledge-mode", "Knowledge mode", "choice", choices=("shared", "review_only", "read_only"))

OPERATIONS: dict[str, Operation] = {
    "Supervisor status": Operation(("service-status",)),
    "Agent storage inventory": Operation(("agent-state", "storage-inventory"), timeout=90),
    "Client status": Operation(("client", "status"), (CLIENT,), root=True),
    "Detect client": Operation(("client", "detect"), root=True),
    "Preview client instructions": Operation(("client", "inject", "--dry-run"), (CLIENT,), root=True),
    "Inject client instructions": Operation(("client", "inject"), (CLIENT,), mutation=True, root=True),
    "Preview instruction removal": Operation(("client", "remove", "--dry-run"), (CLIENT,), root=True),
    "Remove client instructions": Operation(("client", "remove"), (CLIENT,), mutation=True, root=True),
    "Preview client config": Operation(("client", "config"), (CLIENT,), root=True),
    "Apply VS Code config": Operation(("client", "config", "--client=vscode", "--apply"), mutation=True, root=True),
    "Generate agent artifacts": Operation(("generate",), (Field("install", "Deploy to configured agents", "bool"),), mutation=True, timeout=180),
    "Clean build/cache files": Operation(("clean",), mutation=True, timeout=120),
    "Cleanup agent state and inspect ports": Operation(("cleanup", "--ports"), mutation=True, timeout=120),
    "Optimize offline databases": Operation(("cleanup", "--vacuum"), mutation=True, timeout=600),
    "Stage compressed instructions": Operation(("compress-instructions",), (Field("model", "Optional model"),), mutation=True, root=True, timeout=720, json_output=False),
    # Applying compressed instructions via CLI generates another candidate rather
    # than applying the exact reviewed bytes. Keep this out of desktop until
    # the underlying CLI offers a revision/digest-bound apply contract.
    "Knowledge catalog": Operation(("knowledge", "catalog"), root=True),
    "Knowledge query": Operation(("knowledge", "query"), (QUERY, LIMIT), root=True),
    "Knowledge validate": Operation(("knowledge", "validate"), root=True),
    "Knowledge audit": Operation(("knowledge", "audit"), root=True),
    "Knowledge sync status": Operation(("knowledge", "sync-status"), root=True),
    "Knowledge diff": Operation(("knowledge", "diff"), (Field("base", "Base Git revision", required=True), Field("head", "Head Git revision")), root=True),
    "Knowledge impact": Operation(("knowledge", "impact"), (Field("changed-path", "Changed repository-relative paths (one per line)", "lines", True),), root=True),
    "Knowledge remediation preview": Operation(("knowledge", "remediate"), (FINDING, SUBJECT), root=True),
    "Knowledge remediation apply": Operation(("knowledge", "remediate", "--apply"), (FINDING, SUBJECT, TASK), mutation=True, root=True),
    "Initialize knowledge": Operation(("knowledge", "init", "--apply"), (PROJECT, MODE, OP_ID), mutation=True, root=True),
    "Save knowledge record": Operation(("knowledge", "save", "--apply"), (RECORD, REVISION, OP_ID), mutation=True, root=True),
    "Review knowledge finding": Operation(("knowledge", "review", "--apply"), (FINDING, SUBJECT, Field("decision", "Decision", "choice", True, ("acceptable", "expected", "confirmed_issue", "false_positive", "deferred")), REASON, REVISION, OP_ID), mutation=True, root=True),
    "Knowledge batch preview": Operation(("knowledge", "batch-preview"), (RECORD,), root=True),
    "Knowledge batch apply": Operation(("knowledge", "batch-apply", "--apply"), (RECORD, DIGEST, REQUIRED_OP), mutation=True, root=True),
    "Knowledge batch recovery": Operation(("knowledge", "batch-recover", "--apply"), (RECORD, DIGEST, REQUIRED_OP), mutation=True, root=True),
    "Rebuild knowledge projection": Operation(("knowledge", "projection-rebuild"), mutation=True, root=True, timeout=120),
    "List task handoffs": Operation(("knowledge", "handoff-list"), (LIMIT,), root=True),
    "Handoff preflight": Operation(("knowledge", "handoff-preflight"), (Field("limit", "Maximum tasks (1–64)", "integer", True),), root=True),
    "Handoff export preview": Operation(("knowledge", "handoff-export"), (TASK, Field("include-historical-verification", "Include historical verification summaries", "bool")), root=True),
    "Handoff export apply": Operation(("knowledge", "handoff-export", "--apply"), (TASK, REVISION, DIGEST, OP_ID, Field("include-historical-verification", "Include historical verification summaries", "bool")), mutation=True, root=True),
    "Handoff resume preview": Operation(("knowledge", "handoff-resume"), (HANDOFF,), root=True),
    "Handoff resume apply": Operation(("knowledge", "handoff-resume", "--apply"), (HANDOFF, TASK, REVISION, DIGEST, OP_ID), mutation=True, root=True),
}


def catalog() -> dict[str, Any]:
    return {"operations": [
        {"name": name, "requires_confirmation": op.mutation, "requires_root": op.root,
         "fields": [{"name": f.name, "label": f.label, "kind": f.kind, "required": f.required,
                     "choices": list(f.choices), "allow_empty": f.allow_empty} for f in op.fields]}
        for name, op in OPERATIONS.items()
    ]}


def build_argv(args: dict[str, Any]) -> tuple[tuple[str, ...], Operation]:
    name = args.get("name")
    if not isinstance(name, str) or name not in OPERATIONS:
        raise ValueError("Unsupported operator command")
    op = OPERATIONS[name]
    if op.mutation and args.get("confirmed") is not True:
        raise ValueError("Explicit confirmation required")
    supplied = args.get("fields", {})
    if not isinstance(supplied, dict) or set(supplied) - {f.name for f in op.fields}:
        raise ValueError("Unknown operator field")
    argv = [*op.argv, "--no-auto-start"]
    if op.json_output:
        argv.append("--json")
    if op.root:
        root_value = args.get("root")
        if not isinstance(root_value, str) or not root_value.strip():
            raise ValueError("Select an explicit repository root")
        root = Path(root_value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Repository root must be a directory")
        argv.append("--root=" + str(root))
    for field in op.fields:
        value = supplied.get(field.name)
        if field.kind == "bool":
            if value is not None and type(value) is not bool:
                raise ValueError(f"{field.label} must be boolean")
            if value is True:
                argv.append("--" + field.name)
            continue
        if value is None or value == "":
            if field.allow_empty and field.name in supplied:
                argv.append("--" + field.name + "=")
                continue
            if field.required:
                raise ValueError(f"{field.label} is required")
            continue
        if not isinstance(value, str) or len(value) > 12000 or "\x00" in value:
            raise ValueError(f"Invalid {field.label}")
        if field.kind == "integer":
            number = int(value)
            maximum = 16 if name.startswith("Legacy ") else 64 if name == "Handoff preflight" else 1000
            if not 1 <= number <= maximum:
                raise ValueError(f"{field.label} outside allowed range")
            value = str(number)
        if field.kind == "choice" and value not in field.choices:
            raise ValueError(f"Invalid {field.label}")
        if field.kind == "file":
            path = Path(value).expanduser().resolve(strict=True)
            if not path.is_file() or path.stat().st_size > 200_000:
                raise ValueError("Choose a JSON file of at most 200 KB")
            # Validate structure before the operator command reads the same file.
            with path.open("rb") as stream:
                raw = stream.read(200_001)
            if len(raw) > 200_000 or not isinstance(json.loads(raw), dict):
                raise ValueError("Expected bounded JSON object")
            value = str(path)
        if field.kind == "lines":
            values = [line.strip() for line in value.splitlines() if line.strip()]
            if not values or len(values) > 100:
                raise ValueError("Provide 1–100 changed paths")
            argv.extend("--" + field.name + "=" + line for line in values)
        else:
            # --flag=value prevents a value beginning with '-' being parsed
            # as a new flag, even for a string provided by an untrusted caller.
            argv.append("--" + field.name + "=" + value)
    return tuple(argv), op
