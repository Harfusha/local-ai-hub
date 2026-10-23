"""Offline wheel/sdist capability proof, not approval of a production release.

Run directly with a Python having local setuptools>=75 and wheel, or via pytest.
T19_PACKAGE_SOURCE_ROOT selects live source bytes (defaults to this worktree).
No Git export, daemon, network, global installation, or user configuration.
Temporary artifacts are retained; the printed receipt locates hashes and logs.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist",
            "data", "generated", "state", "tool-envs"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inputs(root: Path) -> list[Path]:
    """Select packaging inputs from existing MANIFEST rules, never Git HEAD."""
    try:
        from setuptools._distutils.filelist import FileList
        from setuptools._distutils.text_file import TextFile
    except ImportError:
        raise unittest.SkipTest("local setuptools MANIFEST parser unavailable; no installation") from None
    paths = {root / "pyproject.toml", root / "MANIFEST.in"}
    paths.update((root / "src").rglob("*"))
    selected = FileList()
    selected.files = [str(path.relative_to(root)) for path in sorted(paths) if path.is_file()]
    universe = set(selected.files)
    template = TextFile(str(root / "MANIFEST.in"), strip_comments=True, skip_blanks=True,
                        join_lines=True, collapse_join=True)
    try:
        lines = template.readlines()
    finally:
        template.close()
    for line in lines:
        parts = line.split()
        action, *args = parts
        additions = set()
        if action in {"include", "global-include"} and args:
            for pattern in args:
                additions.update(root.glob(pattern) if action == "include" else root.rglob(pattern))
        elif action == "recursive-include" and len(args) >= 2:
            directory, *patterns = args
            for parent in root.glob(directory):
                if parent.is_dir():
                    for pattern in patterns:
                        additions.update(parent.rglob(pattern))
        elif action == "graft" and len(args) == 1:
            for parent in root.glob(args[0]):
                if parent.is_dir():
                    additions.update(parent.rglob("*"))
        elif ((action in {"exclude", "global-exclude"} and args)
              or (action == "recursive-exclude" and len(args) >= 2)
              or (action == "prune" and len(args) == 1)):
            pass
        else:
            raise AssertionError(f"unsupported MANIFEST rule: {line}")
        universe.update(str(path.relative_to(root)) for path in additions if path.is_file())
        selected.set_allfiles(sorted(universe))
        # Let the actual backend enforce anchored/case-sensitive globs and
        # ordered subtraction/re-inclusion; prune is not a permanent blacklist.
        selected.process_template_line(line)
    paths = {root / relative for relative in selected.files}
    result = []
    for path in sorted(paths):
        relative = path.relative_to(root)
        if (EXCLUDED.intersection(relative.parts)
                or path.suffix in {".pyc", ".pyo"}
                or any(part.endswith(".egg-info") for part in relative.parts)):
            continue
        # Reject link/junction escapes instead of copying host/runtime material.
        for parent in (path, *path.parents):
            if parent == root:
                break
            assert not parent.is_symlink() and not getattr(parent, "is_junction", lambda: False)(), str(parent)
        assert path.resolve().is_relative_to(root), str(path)
        if path.is_file():
            result.append(path)
    assert 0 < len(result) <= 4096, "packaging input count exceeds smoke bound"
    return result


def _snapshot(root: Path, target: Path) -> dict[str, str]:
    identities = {}
    total = 0
    for path in _inputs(root):
        size = path.stat().st_size
        assert size <= 8 * 1024 * 1024, f"oversized packaging input: {path}"
        total += size
        assert total <= 128 * 1024 * 1024, "packaging snapshot exceeds smoke bound"
        content = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        identities[relative] = _sha(content)
        assert _sha(destination.read_bytes()) == identities[relative]
    assert identities == _identities(root), "selected source changed while snapshotting"
    return identities


def _identities(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _sha(path.read_bytes()) for path in _inputs(root)}


def _environment(scratch: Path) -> dict[str, str]:
    # Construct a child environment, never modify the user's PATH/configuration.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT",
                              "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}}
    home = scratch / "home"
    home.mkdir(exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home / "AppData/Roaming"),
               LOCALAPPDATA=str(home / "AppData/Local"), TEMP=str(scratch), TMP=str(scratch),
               XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
               PIP_NO_CACHE_DIR="1", PIP_REQUIRE_VIRTUALENV="1")
    return env


def _run(command: list[str], cwd: Path, env: dict[str, str], scratch: Path,
         label: str, receipt: dict, timeout: int = 60) -> str:
    """Retain full logs; drain pipes and kill the process tree on timeout."""
    log = scratch / f"{label}.log"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    start = time.monotonic()
    child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", creationflags=flags,
                             start_new_session=os.name != "nt")
    try:
        output, _ = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                               creationflags=flags, check=False)
            else:
                os.killpg(child.pid, signal.SIGKILL)
        finally:
            if child.poll() is None:
                child.kill()
        output, _ = child.communicate(timeout=10)
        log.write_text(output, encoding="utf-8")
        raise AssertionError(f"{label} timed out; log: {log}") from None
    log.write_text(output, encoding="utf-8")
    receipt["commands"].append({"argv": command, "cwd": str(cwd), "exit_code": child.returncode,
                                "seconds": round(time.monotonic() - start, 3), "log": str(log),
                                "log_sha256": _sha(log.read_bytes())})
    assert child.returncode == 0, f"{label} exit={child.returncode}; log: {log}\n{output[-2400:]}"
    return output


OFFLINE_GUARD = r'''
import sys
forbidden = []
def deny_external(event, args):
    if event in {"socket.__new__", "socket.connect", "socket.bind", "socket.getaddrinfo",
                 "socket.sendto", "socket.sendmsg", "subprocess.Popen", "os.system"}:
        forbidden.append(event)
        raise AssertionError("packaging smoke forbids " + event)
sys.addaudithook(deny_external)
'''


SCHEMA_WIRE_GUARD = r'''
def schema_wire_payload(schemas):
    encoded = json.dumps(schemas, sort_keys=True, allow_nan=False)
    wire = json.loads(encoded)
    assert json.dumps(wire, sort_keys=True, allow_nan=False) == encoded
    return wire
'''


PROBE = OFFLINE_GUARD + SCHEMA_WIRE_GUARD + r'''
import hashlib, importlib.metadata, importlib.resources, json, pathlib, sys
from unittest.mock import patch

scratch = pathlib.Path(sys.argv[1]).resolve()
venv = pathlib.Path(sys.prefix).resolve()
assert venv == scratch / "venv" and sys.prefix != sys.base_prefix
assert "include-system-site-packages = false" in (venv / "pyvenv.cfg").read_text().lower()
for dependency in ("mcp", "watchdog"):
    try:
        importlib.metadata.version(dependency)
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError("fresh --no-deps venv contains " + dependency)
for path in sys.path:
    assert "site-packages" not in path or pathlib.Path(path).resolve().is_relative_to(venv)

import local_ai_hub
from local_ai_hub import client, config, generator, hardware
origins = {}
for name, module in sorted(sys.modules.copy().items()):
    if name == "local_ai_hub" or name.startswith("local_ai_hub."):
        origin = pathlib.Path(module.__file__).resolve()
        assert origin.is_relative_to(venv) and "site-packages" in origin.parts, str(origin)
        origins[name] = str(origin)
package = pathlib.Path(local_ai_hub.__file__).resolve().parent
installed = {"src/local_ai_hub/" + p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
resource = importlib.resources.files("local_ai_hub").joinpath("defaults.toml").read_bytes()
configuration = scratch / "smoke.toml"
configuration.write_text(
    '[hardware]\nprofile="cpu"\nauto_tune=false\n'
    '[server]\nport=59992\nauto_start_ollama=false\nstate_dir=' + json.dumps(str(scratch / "state")) + '\n'
    '[llama_cpp]\nmode="off"\n[features]\nlocal_models=false\n', encoding="utf-8")
# Only hardware discovery is substituted: load_config otherwise probes GPUs even
# with auto_tune=false. SDK, resource loading, config merging and schemas are real.
with patch.object(hardware, "detect_hardware", return_value={"profile": "cpu", "gpus": [], "npus": []}):
    sdk = client.HubClient(config_path=str(configuration), auto_start=False)
assert sdk.auto_start is False and sdk.base_url == "http://127.0.0.1:59992"
assert pathlib.Path(sdk.config["_config_path"]) == configuration
assert pathlib.Path(sdk.config["_defaults_path"]) == package / "defaults.toml"
assert pathlib.Path(sdk.config["server"]["state_dir"]) == scratch / "state"
schemas = schema_wire_payload(generator.generate_mcp_tool_schemas(sdk.config))
expected = {"local_ai_status", "local_ai_repo", "local_ai_coord", "local_ai_artifact", "local_ai_rag"}
assert set(schemas) == expected, sorted(schemas)
for name, schema in schemas.items():
    assert schema["name"] == name and schema["parameters"]["type"] == "object"
    properties = schema["parameters"]["properties"]
    assert {"max_response_tokens", "response_profile", "reuse_key"} <= properties.keys()
    assert set(schema["parameters"].get("required", [])) <= properties.keys()
repo = schemas["local_ai_repo"]["parameters"]
assert "action" in repo["required"]
assert {"preprocess", "context", "solve"} <= set(repo["properties"]["action"]["enum"])
# All assertions above inspect the actual JSON wire payload. Python-only tuple
# metadata is valid JSON array data, not a container-identity contract.
sdk.close()
assert not forbidden, forbidden
assert not (scratch / "state").exists(), "SDK constructor started runtime state"
assert not (scratch / "home/.local-ai-hub").exists(), "SDK touched user install layout"
print(json.dumps({"version": local_ai_hub.__version__, "distribution_version": importlib.metadata.version("local-ai-hub"),
                  "origins": origins, "installed_files": installed, "defaults_sha256": hashlib.sha256(resource).hexdigest(),
                  "schema_names": sorted(schemas), "schema_sha256": hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest(),
                  "hardware_discovery": "substituted_cpu_only", "forbidden_events": forbidden}))
'''


def _isolated_toolchain() -> dict[str, str | None]:
    probe = """
import importlib.metadata
import json

versions = {}
for name in ("setuptools", "wheel", "pip"):
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = None
print(json.dumps(versions))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        return {name: None for name in ("setuptools", "wheel", "pip")}
    versions = json.loads(result.stdout)
    return {name: versions.get(name) for name in ("setuptools", "wheel", "pip")}


def _verify_package(source: Path, scratch: Path) -> dict:
    receipt = {"status": "running", "source_root": str(source), "scratch": str(scratch),
               "proof_scope": "current_source_snapshot_capability", "production_release_approved": False,
               "runner": {"executable": sys.executable, "python_version": sys.version},
               "commands": [], "toolchain": {}}
    receipt_path = scratch / "receipt.json"
    try:
        # Probe the same isolated interpreter used by the offline build workers.
        receipt["toolchain"] = _isolated_toolchain()
        for name in ("setuptools", "wheel", "pip"):
            if receipt["toolchain"][name] is None:
                receipt["status"] = "skipped"
                raise unittest.SkipTest(
                    f"isolated local {name} unavailable; no network/global install; {receipt_path}"
                )
        setuptools_major = int(receipt["toolchain"]["setuptools"].split(".")[0])
        if setuptools_major < 75:
            receipt["status"] = "skipped"
            raise unittest.SkipTest(f"setuptools>=75 required; {receipt_path}")
        snapshot = scratch / "source"
        identities = _snapshot(source, snapshot)
        receipt["source_files"] = identities
        receipt["source_snapshot_sha256"] = _sha(json.dumps(identities, sort_keys=True).encode())
        project = tomllib.loads((snapshot / "pyproject.toml").read_text(encoding="utf-8"))
        assert project["build-system"]["build-backend"] == "setuptools.build_meta"
        version = project["project"]["version"]
        version_nodes = ast.parse((snapshot / "src/local_ai_hub/__init__.py").read_text(encoding="utf-8")).body
        declared = next(ast.literal_eval(n.value) for n in version_nodes if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
        assert version == declared, "source metadata/module versions disagree"
        receipt["version"] = version
        dist = scratch / "dist"
        dist.mkdir()
        env = _environment(scratch)
        # -I prevents inherited PYTHONPATH/editable source from becoming build input.
        sdist_code = OFFLINE_GUARD + "import setuptools.build_meta as b; print(b.build_sdist(sys.argv[1])); assert not forbidden, forbidden"
        _run([sys.executable, "-I", "-B", "-c", sdist_code, str(dist)], snapshot, env, scratch, "sdist", receipt)
        sdists = list(dist.glob("*.tar.gz"))
        assert len(sdists) == 1
        sdist = sdists[0]
        receipt["sdist"] = {"path": str(sdist), "sha256": _sha(sdist.read_bytes())}
        extracted = scratch / "sdist-source"
        extracted.mkdir()
        with tarfile.open(sdist) as archive:
            # Hash archived bytes, including dirty/untracked selected inputs.
            files = {member.name.partition("/")[2]: member for member in archive.getmembers() if member.isfile()}
            for relative, expected_hash in identities.items():
                assert relative in files, f"sdist missing selected input: {relative}"
                stream = archive.extractfile(files[relative])
                assert stream is not None
                with stream:
                    assert _sha(stream.read()) == expected_hash, f"sdist source mismatch: {relative}"
            assert not any("docs/superpowers/" in name for name in files)
            archive.extractall(extracted, filter="data")
        roots = list(extracted.iterdir())
        assert len(roots) == 1 and roots[0].is_dir()
        wheel_code = OFFLINE_GUARD + "import setuptools.build_meta as b; print(b.build_wheel(sys.argv[1])); assert not forbidden, forbidden"
        _run([sys.executable, "-I", "-B", "-c", wheel_code, str(dist)], roots[0], env, scratch, "wheel", receipt)
        wheels = list(dist.glob("*.whl"))
        assert len(wheels) == 1
        wheel = wheels[0]
        receipt["wheel"] = {"path": str(wheel), "sha256": _sha(wheel.read_bytes()), "built_from": receipt["sdist"]["sha256"]}
        package_files = {name: value for name, value in identities.items() if name.startswith("src/local_ai_hub/")}
        with zipfile.ZipFile(wheel) as archive:
            for relative, expected_hash in package_files.items():
                name = relative.removeprefix("src/")
                assert name in archive.namelist(), f"wheel missing selected package resource: {name}"
                assert _sha(archive.read(name)) == expected_hash, f"wheel source mismatch: {name}"
        venv = scratch / "venv"
        _run([sys.executable, "-I", "-B", "-m", "venv", str(venv)], scratch, env, scratch, "venv", receipt)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run([str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
              "--no-cache-dir", "--disable-pip-version-check", str(wheel)], scratch, env, scratch, "install", receipt)
        output = _run([str(python), "-I", "-B", "-c", PROBE, str(scratch)], scratch, env, scratch, "installed-smoke", receipt)
        installed = json.loads(output.strip())
        assert installed["version"] == installed["distribution_version"] == version
        assert installed["defaults_sha256"] == identities["src/local_ai_hub/defaults.toml"]
        assert installed["installed_files"] == package_files, "installed package differs from exact selected snapshot"
        assert _sha(wheel.read_bytes()) == receipt["wheel"]["sha256"], "wheel changed during installation"
        assert _identities(source) == identities, "selected source drifted during smoke"
        receipt["installed"] = installed
        receipt["status"] = "passed"
        return receipt
    except unittest.SkipTest:
        raise
    except Exception as exc:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
        print(f"T19_PACKAGE_RECEIPT={receipt_path}", flush=True)


class PackagedSDKSmoke(unittest.TestCase):
    def test_builder_toolchain_probe_uses_isolated_interpreter(self) -> None:
        commands: list[list[str]] = []

        def completed(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"setuptools": None, "wheel": None, "pip": "25.2"}),
            )

        with mock.patch.object(subprocess, "run", side_effect=completed):
            toolchain = _isolated_toolchain()

        self.assertEqual(toolchain, {"setuptools": None, "wheel": None, "pip": "25.2"})
        self.assertEqual(commands, [[sys.executable, "-I", "-B", "-c", mock.ANY]])

    def test_missing_isolated_build_dependency_skips_without_installing(self) -> None:
        command = [sys.executable, "-I", "-B", "-c", "probe"]
        result = subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"setuptools": None, "wheel": None, "pip": "25.2"}),
        )
        with tempfile.TemporaryDirectory(prefix="t19-toolchain-preflight-") as directory:
            scratch = Path(directory)
            with mock.patch.object(subprocess, "run", return_value=result):
                with self.assertRaisesRegex(unittest.SkipTest, "isolated local setuptools unavailable"):
                    _verify_package(ROOT, scratch)
            receipt = json.loads((scratch / "receipt.json").read_text(encoding="utf-8"))

        self.assertEqual(receipt["status"], "skipped")
        self.assertIsNone(receipt["toolchain"]["setuptools"])

    def test_schema_wire_retains_metadata_and_rejects_invalid_values(self) -> None:
        namespace = {"json": json}
        exec(SCHEMA_WIRE_GUARD, namespace)
        convert = namespace["schema_wire_payload"]
        metadata = {"x-operation-contract": {"required": ("task",), "requires": ()}}
        self.assertEqual(
            convert(metadata),
            {"x-operation-contract": {"required": ["task"], "requires": []}},
        )
        self.assertIsInstance(metadata["x-operation-contract"]["required"], tuple)
        for invalid in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(invalid=repr(invalid)), self.assertRaises(ValueError):
                convert({"minimum": invalid})
        with self.assertRaises(TypeError):
            convert({"unsupported": object()})

    def test_wheel_from_sdist_runs_sdk_in_fresh_venv(self) -> None:
        source = Path(os.environ.get("T19_PACKAGE_SOURCE_ROOT", str(ROOT))).resolve(strict=True)
        scratch = Path(tempfile.mkdtemp(prefix="t19-packaged-sdk-"))
        receipt = _verify_package(source, scratch)
        self.assertEqual(receipt["status"], "passed")
        self.assertFalse(receipt["production_release_approved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
