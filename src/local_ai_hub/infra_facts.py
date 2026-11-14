from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_INFRA_RESOURCE = re.compile('^\\s*resource\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_MODULE = re.compile('^\\s*module\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_PROVIDER = re.compile('^\\s*provider\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_VARIABLE = re.compile('^\\s*variable\\s+[\\"\\\']([^\\"\\\']+)[\\"\\\']')
_INFRA_STAGE_I = re.compile('^-?\\s*stage\\s*:\\s*([^#]+)', re.I)
_INFRA_JOB_I = re.compile('^-?\\s*job\\s*:\\s*([^#]+)', re.I)
_INFRA_TASK_I = re.compile('^-?\\s*task\\s*:\\s*([^#]+)', re.I)
_INFRA_SCRIPT_I = re.compile('^(?:script|bash|pwsh|powershell)\\s*:\\s*(.+)', re.I)
_INFRA_SERVICE = re.compile('^\\s*service\\s+([A-Za-z_]\\w*)')
_INFRA_RPC = re.compile('^\\s*rpc\\s+([A-Za-z_]\\w*)\\s*\\(')
_INFRA_MESSAGE = re.compile('^\\s*message\\s+([A-Za-z_]\\w*)')


def _extract_container_facts(name: str, lines: list[str], fact: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if name in {"dockerfile", "containerfile"} or name.startswith("dockerfile."):
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            m = re.match(r"(?i)^FROM\s+([^\s]+)(?:\s+AS\s+([^\s]+))?", stripped)
            if m:
                facts.append(fact("container_base", m.group(1), m.group(1), line_no, stage=m.group(2) or ""))
            m = re.match(r"(?i)^EXPOSE\s+(.+)$", stripped)
            if m:
                for port in m.group(1).split():
                    facts.append(fact("port", port, port, line_no, source="docker"))
            m = re.match(r"(?i)^(?:ENV|ARG)\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
            if m:
                facts.append(fact("env", m.group(1), m.group(1), line_no, source="docker"))
            if re.match(r"(?i)^(?:ENTRYPOINT|CMD)\b", stripped):
                facts.append(fact("entrypoint", "container", stripped[:300], line_no, source="docker"))
            if re.match(r"(?i)^HEALTHCHECK\b", stripped):
                facts.append(fact("healthcheck", "container", stripped[:300], line_no, source="docker"))

    if name in {"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"}:
        in_services = False; service = ""; service_indent = -1
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
            if re.match(r"^services\s*:\s*$", stripped):
                in_services = True; service = ""; service_indent = indent; continue
            if in_services and stripped and not line.startswith(" ") and not stripped.startswith("#"):
                in_services = False; service = ""
            if in_services:
                m = re.match(r"^\s+([A-Za-z0-9_.-]+)\s*:\s*$", line)
                if m and indent == service_indent + 2:
                    service = m.group(1)
                    facts.append(fact("service", service, service, line_no, source="compose"))
                    continue
                m = re.match(r"^\s*image\s*:\s*[\"']?([^\"'#\s]+)", stripped, re.I)
                if m and service:
                    facts.append(fact("container_image", service, m.group(1), line_no, service=service))
                m = re.search(r"[\"']?(\d{2,5})(?::(\d{2,5}))?(?:/(?:tcp|udp))?[\"']?", stripped)
                if m and service and ("port" in stripped.lower() or stripped.startswith("-")):
                    facts.append(fact("port", service, m.group(0).strip("\"'"), line_no, service=service))
                if stripped.lower().startswith("healthcheck:") and service:
                    facts.append(fact("healthcheck", service, service, line_no, source="compose"))
    return facts

def _extract_ci_facts(low: str, name: str, lines: list[str], fact: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if "/.github/workflows/" in f"/{low}" or low.startswith(".github/workflows/"):
        in_jobs = False; jobs_indent = -1
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
            if re.match(r"^jobs\s*:\s*$", stripped):
                in_jobs = True; jobs_indent = indent; continue
            if in_jobs:
                m = re.match(r"^\s+([A-Za-z0-9_.-]+)\s*:\s*$", line)
                if m and indent == jobs_indent + 2:
                    facts.append(fact("ci_job", m.group(1), m.group(1), line_no, source="github-actions"))
            m = re.match(r"^uses\s*:\s*([^\s#]+)", stripped)
            if m:
                facts.append(fact("ci_action", m.group(1), m.group(1), line_no, source="github-actions"))
            m = re.match(r"^run\s*:\s*(.+)$", stripped)
            if m:
                facts.append(fact("ci_command", "run", m.group(1)[:300], line_no, source="github-actions"))

    if name in {".gitlab-ci.yml", ".gitlab-ci.yaml"}:
        reserved = {"stages", "variables", "default", "include", "workflow", "image", "services", "before_script", "after_script", "cache"}
        current_job = ""
        in_script = False
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
            top = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*$", stripped) if indent == 0 else None
            if top:
                key = top.group(1); in_script = False
                current_job = "" if key in reserved or key.startswith(".") else key
                if current_job:
                    facts.append(fact("ci_job", current_job, current_job, line_no, source="gitlab-ci"))
                continue
            if current_job and re.match(r"^script\s*:\s*$", stripped):
                in_script = True; continue
            if current_job and in_script:
                cmd = re.match(r"^-\s+(.+)$", stripped)
                if cmd:
                    facts.append(fact("ci_command", current_job, cmd.group(1)[:300], line_no, source="gitlab-ci"))
                elif stripped and not stripped.startswith("#") and indent <= 2:
                    in_script = False

    if name in {"azure-pipelines.yml", "azure-pipelines.yaml"}:
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            for kind, pattern in (
                ("ci_stage", _INFRA_STAGE_I),
                ("ci_job", _INFRA_JOB_I),
                ("ci_action", _INFRA_TASK_I),
                ("ci_command", _INFRA_SCRIPT_I),
            ):
                m = pattern.search(stripped)
                if m:
                    value = m.group(1).strip().strip("\"'")[:300]
                    facts.append(fact(kind, value, value, line_no, source="azure-pipelines"))
    return facts

def _extract_config_facts(rel: str, name: str, lines: list[str], fact: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if name.startswith(".env"):
        for line_no, line in enumerate(lines, 1):
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if m:
                facts.append(fact("env", m.group(1), m.group(1), line_no, source="env-file"))

    if Path(rel).suffix.lower() in {".ini", ".cfg", ".properties"}:
        section = ""
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            sm = re.match(r"^\[([^]]+)\]$", stripped)
            if sm:
                section = sm.group(1); continue
            km = re.match(r"^([A-Za-z0-9_.-]+)\s*[=:]", stripped)
            if km:
                key = f"{section}.{km.group(1)}" if section else km.group(1)
                facts.append(fact("config_key", key, key, line_no, source="ini-properties"))

    if Path(rel).suffix.lower() in {".tf", ".tfvars"}:
        patterns = {
            "terraform_resource": _INFRA_RESOURCE,
            "terraform_module": _INFRA_MODULE,
            "terraform_provider": _INFRA_PROVIDER,
            "config_key": _INFRA_VARIABLE,
        }
        for line_no, line in enumerate(lines, 1):
            for kind, pattern in patterns.items():
                m = pattern.search(line)
                if m:
                    value = ".".join(x for x in m.groups() if x)
                    facts.append(fact(kind, value, value, line_no, source="terraform"))

    if Path(rel).suffix.lower() == ".proto":
        for line_no, line in enumerate(lines, 1):
            for kind, pattern in (
                ("proto_service", _INFRA_SERVICE),
                ("proto_rpc", _INFRA_RPC),
                ("proto_message", _INFRA_MESSAGE),
            ):
                m = pattern.search(line)
                if m:
                    facts.append(fact(kind, m.group(1), m.group(1), line_no, source="protobuf"))
    return facts

def _extract_yaml_facts(rel: str, name: str, text: str, lines: list[str], fact: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    # Kubernetes YAML is declarative and can be represented losslessly enough for
    # discovery without embedding the whole manifest. Keep extraction conservative.
    if Path(rel).suffix.lower() in {".yaml", ".yml"} and re.search(r"(?m)^\s*apiVersion\s*:", text) and re.search(r"(?m)^\s*kind\s*:", text):
        kind = ""; resource_name = ""
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            m = re.match(r"^kind\s*:\s*([^#]+)", stripped, re.I)
            if m:
                kind = m.group(1).strip().strip("\"'")
                facts.append(fact("k8s_kind", kind, kind, line_no, source="kubernetes"))
                continue
            # metadata.name is intentionally accepted only on a simple scalar line;
            # the exact evidence coordinate remains available if disambiguation is needed.
            m = re.match(r"^name\s*:\s*([A-Za-z0-9_.-]+)\s*$", stripped)
            if m and not resource_name:
                resource_name = m.group(1)
                facts.append(fact("k8s_resource", resource_name, kind or "resource", line_no, source="kubernetes", resource_kind=kind))
            m = re.match(r"^image\s*:\s*([^#\s]+)", stripped, re.I)
            if m:
                facts.append(fact("container_image", resource_name or kind or "k8s", m.group(1).strip("\"'"), line_no, source="kubernetes"))
            m = re.match(r"^(?:containerPort|port|targetPort)\s*:\s*([0-9]{1,5})", stripped, re.I)
            if m:
                facts.append(fact("port", resource_name or kind or "k8s", m.group(1), line_no, source="kubernetes"))

    # OpenAPI/Swagger paths are exact declared routes. YAML gets precise line
    # coordinates; JSON is supplemented below from parsed data when available.
    if Path(rel).suffix.lower() in {".yaml", ".yml"} and ("openapi:" in text[:5000].lower() or "swagger:" in text[:5000].lower() or "openapi" in name or "swagger" in name):
        current_path = ""
        path_indent = -1
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip(); indent = len(line) - len(line.lstrip(" "))
            pm = re.match(r"^(/[^:]+)\s*:\s*$", stripped)
            if pm:
                current_path = pm.group(1).strip(); path_indent = indent; continue
            mm = re.match(r"^(get|post|put|patch|delete|options|head|trace)\s*:\s*$", stripped, re.I)
            if current_path and mm and indent > path_indent:
                method = mm.group(1).upper()
                facts.append(fact("route", current_path, method, line_no, method=method, source="openapi"))
            elif current_path and stripped and indent <= path_indent and not stripped.startswith("#"):
                current_path = ""
    return facts

def _extract_package_facts(name: str, text: str, fact: Any, json_dumps: Any, logger: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if name == "package.json":
        try:
            pkg_data = json.loads(text)
            if isinstance(pkg_data, dict):
                if "name" in pkg_data:
                    facts.append(fact("package_name", str(pkg_data["name"]), "npm", 1, source="package.json"))
                for script_name, cmd in (pkg_data.get("scripts") or {}).items():
                    facts.append(fact("npm_script", str(script_name), str(cmd)[:300], 1, script=str(script_name), command=str(cmd)))
                for dep_key, kind in (("dependencies", "prod"), ("devDependencies", "dev"), ("peerDependencies", "peer")):
                    for dep, ver in (pkg_data.get(dep_key) or {}).items():
                        facts.append(fact("dependency", str(dep), str(ver), 1, manager="npm", dep_kind=kind))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as parse_exc:
            logger.debug("Npm package metadata skipped (%s)", type(parse_exc).__name__)

    if name == "composer.json":
        try:
            comp_data = json.loads(text)
            if isinstance(comp_data, dict):
                if "name" in comp_data:
                    facts.append(fact("package_name", str(comp_data["name"]), "composer", 1, source="composer.json"))
                for dep_key, kind in (("require", "prod"), ("require-dev", "dev")):
                    for dep, ver in (comp_data.get(dep_key) or {}).items():
                        facts.append(fact("dependency", str(dep), str(ver), 1, manager="composer", dep_kind=kind))
                autoload = comp_data.get("autoload") or {}
                if isinstance(autoload, dict):
                    for ns, target_dir in (autoload.get("psr-4") or {}).items():
                        facts.append(fact("psr4_autoload", str(ns).rstrip("\\"), str(target_dir), 1, namespace=str(ns), path=str(target_dir)))
                autoload_dev = comp_data.get("autoload-dev") or {}
                if isinstance(autoload_dev, dict):
                    for ns, target_dir in (autoload_dev.get("psr-4") or {}).items():
                        facts.append(fact("psr4_autoload", str(ns).rstrip("\\"), str(target_dir), 1, namespace=str(ns), path=str(target_dir), dev=True))
                for script_name, cmd in (comp_data.get("scripts") or {}).items():
                    cmd_val = cmd if isinstance(cmd, str) else json_dumps(cmd)
                    facts.append(fact("composer_script", str(script_name), str(cmd_val)[:300], 1, script=str(script_name)))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as parse_exc:
            logger.debug("Composer package metadata skipped (%s)", type(parse_exc).__name__)
    return facts

def extract_infra_facts(path: str, text: str, *, fact: Any, json_dumps: Any, logger: Any) -> list[dict[str, Any]]:
    """Extract common infrastructure/build facts with zero model calls.

    Parsers are intentionally conservative: they expose coordinates/declared
    values, not behavioral interpretations. This makes the output suitable for
    direct evidence and safe cache reuse.
    """
    facts: list[dict[str, Any]] = []
    rel = path.replace("\\", "/")
    low = rel.lower(); name = Path(rel).name.lower()
    lines = text.splitlines()

    facts.extend(_extract_container_facts(name, lines, fact))
    facts.extend(_extract_ci_facts(low, name, lines, fact))
    facts.extend(_extract_config_facts(rel, name, lines, fact))
    facts.extend(_extract_yaml_facts(rel, name, text, lines, fact))
    facts.extend(_extract_package_facts(name, text, fact, json_dumps, logger))

    return facts

