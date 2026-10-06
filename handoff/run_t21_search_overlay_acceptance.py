from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT_PACKAGE = Path(r"C:\Users\Adam\.local-ai-hub\src\local_ai_hub")
T21_TEST = Path(
    r"C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub"
    r"\tests\test_t21_search_policy_consumers.py"
)
PATCH = Path(__file__).with_name("t21-root-current-search-policy-v20261001-r3.patch")
PREIMAGE_SHA256 = {
    "repo_tools.py": "d6eae9a69059353b1d182a3d1a2d3af8cf61aa623ac8817b97a121ab9385d07d",
    "services.py": "1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1",
    "project_config.py": "4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713",
}
POSTIMAGE_SHA256 = {
    "repo_tools.py": "8da38ecbe3daa4c975ec8f14fedbc74d91d04ceeaf4cbb2c7155a3e554b6da65",
    "services.py": "a06ae015085e4b4dc61bf09a99570332044d65d623b7521218e569c329554235",
}
TEST_SHA256 = "2d95eceb2b4f3c283af5006633ead8378669bf033bd0781312a50bf3e5de7c1b"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_closed_policy() -> None:
    import json
    import local_ai_hub.repo_tools as repo_tools_module

    from local_ai_hub.project_config import PathHint, resolve_project_context
    from local_ai_hub.repo_tools import RepositoryTools
    from local_ai_hub.services import LocalAIServices

    with tempfile.TemporaryDirectory(prefix="t21-search-policy-guards-") as temp:
        root = Path(temp) / "repo"
        root.mkdir()
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, timeout=10)
        (root / ".local-ai.toml").write_text(
            'exclude_paths = ["src/secret.py"]\n'
            'force_include_paths = ["node_modules/@my-org/**", "node_modules/**/direct.shader"]\n'
            '[file_limits]\nmax_file_size_bytes = 24\n'
            '[custom_extensions]\ntext = [".shader", ".dep"]\nbinary = [".php"]\n',
            encoding="utf-8",
        )
        (root / "src").mkdir()
        for name, content in {
            "visible.py": "needle\n",
            "secret.py": "needle secret\n",
            "large.py": "needle " + "x" * 40,
            "opaque.php": "needle binary\n",
            "button.shader": "needle shader\n",
        }.items():
            (root / "src" / name).write_text(content, encoding="utf-8")
        for index in range(193):
            content = "needle batch\n" if index == 192 else "plain batch\n"
            (root / "src" / f"zz_batch_{index:03}.py").write_text(content, encoding="utf-8")
        (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        forced = root / "node_modules" / "@my-org" / "button.dep"
        forced.parent.mkdir(parents=True)
        forced.write_text("needle forced\n", encoding="utf-8")
        direct_forced = root / "node_modules" / "direct.shader"
        direct_forced.write_text("needle direct\n", encoding="utf-8")
        config = {
            "server": {"state_dir": str(Path(temp) / "state")},
            "search": {"max_files": 400},
            "rag": {"extensions": [".py", ".php"]},
        }
        service = LocalAIServices.__new__(LocalAIServices)
        service.config = config
        service.repo_tools = RepositoryTools(config)
        if not service.repo_tools._rg:
            raise SystemExit("installed ripgrep is required for this regression")
        service.learner = service.code_index = service.preprocessor = None
        service.deterministic = service.evidence_store = None
        service._repo_cache_state = lambda _root: {"fingerprint": "current", "stale": False}
        service._repo_cached = lambda _operation, _root, _params, compute: compute()
        outside_hint = PathHint(
            path="../outside.py", purpose="repository_search", scope="repo_search",
        )
        real_run = repo_tools_module.subprocess.run
        rg_calls = []

        def record_ripgrep(command, *args, **kwargs):
            if command and os.path.normcase(str(command[0])) == os.path.normcase(service.repo_tools._rg):
                rg_calls.append(tuple(command))
            return real_run(command, *args, **kwargs)

        repo_tools_module.subprocess.run = record_ripgrep
        try:
            broad = service.repo_search(str(root), "needle", path_hints=[outside_hint])
        finally:
            repo_tools_module.subprocess.run = real_run
        broad_paths = sorted(item["path"] for item in broad["results"])
        expected_broad = [
            "node_modules/@my-org/button.dep", "node_modules/direct.shader",
            "src/button.shader", "src/visible.py", "src/zz_batch_192.py",
        ]
        if not broad.get("success") or broad_paths != expected_broad or broad.get("engine") != "ripgrep":
            raise SystemExit(f"bounded ripgrep policy mismatch: engine={broad.get('engine')}, paths={broad_paths}")
        if len(rg_calls) < 2:
            raise SystemExit(f"expected multiple bounded argv batches, got {len(rg_calls)}")

        settings = resolve_project_context(root, Path(temp) / "state").settings
        service.repo_tools.search = lambda *_args, **_kwargs: {"success": True, "results": []}
        hints = [
            PathHint(path=path, purpose="repository_search", scope="repo_search")
            for path in (
                "src/button.shader", "node_modules/@my-org/button.dep",
                "node_modules/direct.shader", "src/secret.py", "src/large.py", "src/opaque.php",
            )
        ]
        targeted = service.repo_search(str(root), "needle", path_hints=hints)
        targeted_paths = sorted(item["path"] for item in targeted["results"])
        if not targeted.get("success") or targeted_paths != expected_broad[:3]:
            raise SystemExit(f"targeted project policy mismatch: {targeted_paths}")
        unsafe = service.repo_tools.search_paths(
            str(root), "needle", ["../outside.py"], project_settings=settings,
        )
        if unsafe.get("success") is not False:
            raise SystemExit(f"out-of-root path was not rejected: {unsafe}")
        print(json.dumps({
            "broad_paths": broad_paths,
            "broad_engine": broad.get("engine"),
            "ripgrep_batches": len(rg_calls),
            "targeted_paths": targeted_paths,
            "denied": ["exclude", "binary", "oversize", "outside_root"],
        }, sort_keys=True))


def main() -> int:
    for name, expected in PREIMAGE_SHA256.items():
        actual = sha256(ROOT_PACKAGE / name)
        if actual != expected:
            raise SystemExit(f"root preimage drift: {name} {actual}")
    if sha256(T21_TEST) != TEST_SHA256:
        raise SystemExit(f"T21 test drift: {sha256(T21_TEST)}")

    with tempfile.TemporaryDirectory(prefix="t21-root-search-overlay-") as temp:
        temp_root = Path(temp)
        package = temp_root / "src" / "local_ai_hub"
        package.mkdir(parents=True)
        for name in PREIMAGE_SHA256:
            shutil.copyfile(ROOT_PACKAGE / name, package / name)
        (package / "__init__.py").write_text(
            '__version__ = "4.0.0"\n'
            f"__path__.append({str(ROOT_PACKAGE)!r})\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(temp_root), "apply", str(PATCH)],
            check=True, timeout=10,
        )
        for name, expected in POSTIMAGE_SHA256.items():
            actual = sha256(package / name)
            if actual != expected:
                raise SystemExit(f"patch postimage mismatch: {name} {actual}")

        source_root = package.parent
        os.environ["T21_EXPECT_SOURCE_ROOT"] = str(package)
        sys.path.insert(0, str(source_root))
        import local_ai_hub

        if Path(local_ai_hub.__file__).resolve() != (package / "__init__.py").resolve():
            raise SystemExit("overlay package import path mismatch")
        import local_ai_hub.project_config as project_config
        import local_ai_hub.repo_tools as repo_tools
        import local_ai_hub.services as services

        for module in (project_config, repo_tools, services):
            if not Path(module.__file__).resolve().is_relative_to(package.resolve()):
                raise SystemExit(f"overlay module import path mismatch: {module.__file__}")
        import pytest

        result = int(pytest.main([
            str(T21_TEST), "-q", "-s", "-p", "no:cacheprovider", "--tb=short",
        ]))
        if result == 0:
            verify_closed_policy()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
