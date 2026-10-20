"""Capture installed versions, hash-lock resolver output and assess supplied OSV evidence.

Network I/O belongs to the bounded CI curl step. This tool never reports a partial
or paginated OSV batch as clean. The separate CycloneDX SBOM declares its scope.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import re
from urllib.parse import quote
import uuid


def make_sbom(packages):
    if not isinstance(packages, list) or not packages or len(packages) > 500:
        raise ValueError("bounded installed package inventory required")
    components, seen = [], set()
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("package entry must be an object")
        name, version = package.get("name"), package.get("version")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
                or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)):
            raise ValueError("canonical package name and exact version required")
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in seen:
            raise ValueError("duplicate installed distribution")
        seen.add(normalized)
        purl = f"pkg:pypi/{normalized}@{quote(version, safe='')}"
        components.append({"type": "application" if normalized == "local-ai-hub" else "library",
                           "name": name, "version": version, "purl": purl, "bom-ref": purl})
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX", "specVersion": "1.6",
        "serialNumber": "urn:uuid:" + str(uuid.uuid4()), "version": 1,
        "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(), "properties": [{
            "name": "local-ai-hub:inventory-scope",
            "value": "Installed Python distributions only; native libraries, files and dependency edges are not asserted.",
        }]},
        "components": sorted(components, key=lambda item: item["purl"]),
        "compositions": [{"aggregate": "incomplete"}],
    }


def lock_from_report(report):
    items = report.get("install") if isinstance(report, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("complete resolver install report required")
    lines, names = [], set()
    for item in items:
        metadata = item.get("metadata", {})
        name, version = metadata.get("name"), metadata.get("version")
        digest = item.get("download_info", {}).get("archive_info", {}).get("hashes", {}).get("sha256")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
                or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("resolved dependency requires canonical name, exact version and SHA-256")
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in names:
            raise ValueError("duplicate resolved distribution")
        names.add(key)
        lines.append(f"{name}=={version} --hash=sha256:{digest}")
    return "\n".join(sorted(lines, key=str.lower)) + "\n"


def validate_constraints(report, text):
    pinned = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)", line)
        if not match:
            raise ValueError("release constraints require exact name==version pins")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in pinned:
            raise ValueError("duplicate release constraint")
        pinned[name] = match[2]
    items = report.get("install") if isinstance(report, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("resolved install report required")
    for item in items:
        metadata = item.get("metadata", {})
        raw_name, version = metadata.get("name"), metadata.get("version")
        if not isinstance(raw_name, str) or not isinstance(version, str):
            raise ValueError("resolved package identity required")
        name = re.sub(r"[-_.]+", "-", raw_name).lower()
        if name != "local-ai-hub" and pinned.get(name) != version:
            raise ValueError(f"dependency absent from exact release baseline: {name}=={version}")


def assess_response(packages, response):
    unknown = {"success": False, "complete": False, "status": "unknown"}
    if not isinstance(packages, list) or not packages or not isinstance(response, dict):
        return unknown
    results = response.get("results")
    if not isinstance(results, list) or len(results) != len(packages):
        return unknown
    findings = []
    for package, item in zip(packages, results):
        if not isinstance(item, dict) or item.get("next_page_token") or item.get("error"):
            return unknown
        vulns = item.get("vulns", [])
        if not isinstance(vulns, list) or any(
            not isinstance(v, dict) or not isinstance(v.get("id"), str) or not v["id"]
            or not isinstance(v.get("modified"), str) or not v["modified"] for v in vulns
        ):
            return unknown
        if vulns:
            findings.append({"package": package, "advisories": vulns})
    return {
        "success": not findings, "complete": True,
        "status": "advisories_found" if findings else "no_known_advisories",
        "packages_checked": len(packages), "findings": findings,
        "source": "https://api.osv.dev/v1/querybatch",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resolver-report", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--sbom", type=Path)
    parser.add_argument("--constraints", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--response", type=Path)
    parser.add_argument("--assessment-output", type=Path)
    args = parser.parse_args()
    if args.inventory:
        if not args.response or not args.assessment_output:
            parser.error("assessment requires --response and --assessment-output")
        payload = args.inventory.read_bytes()
        inventory = json.loads(payload)
        response_bytes = args.response.read_bytes()
        result = assess_response(inventory["packages"], json.loads(response_bytes))
        result["inventory_sha256"] = hashlib.sha256(payload).hexdigest()
        result["response_sha256"] = hashlib.sha256(response_bytes).hexdigest()
        args.assessment_output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("success", "complete", "status")}))
        return 0 if result["success"] else 1
    if not all((args.output, args.resolver_report, args.lock, args.queries)):
        parser.error("capture requires --output, --resolver-report, --lock and --queries")
    packages = sorted(
        [{"name": item.metadata["Name"], "version": item.version} for item in distributions()],
        key=lambda item: item["name"].lower(),
    )
    if not 1 <= len(packages) <= 500:
        raise ValueError("installed inventory exceeds bounded OSV batch scope")
    report_bytes = args.resolver_report.read_bytes()
    report = json.loads(report_bytes)
    if args.constraints:
        validate_constraints(report, args.constraints.read_text(encoding="utf-8"))
    lock = lock_from_report(report)
    args.lock.write_text(lock, encoding="utf-8")
    inventory = {
        "schema_version": 1, "format": "installed_distribution_inventory",
        "python": platform.python_version(), "platform": platform.platform(),
        "resolver_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "packages": packages,
    }
    args.output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    if args.sbom:
        args.sbom.write_text(json.dumps(make_sbom(packages), indent=2) + "\n", encoding="utf-8")
    queries = {"queries": [{"package": {"ecosystem": "PyPI", "name": item["name"]},
                            "version": item["version"]} for item in packages]}
    args.queries.write_text(json.dumps(queries) + "\n", encoding="utf-8")
    print(json.dumps({"success": True, "packages": len(packages)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
