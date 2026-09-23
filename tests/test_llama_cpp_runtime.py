from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.llama_cpp_runtime import LlamaCppManagedRuntime, llama_cpp_backend_selection, llama_cpp_managed_selected


class LlamaCppRuntimeTests(unittest.TestCase):
    def test_backend_selection_is_explicit_and_ollama_has_precedence(self):
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}}), "ollama")
        self.assertFalse(llama_cpp_managed_selected({"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}}))
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}}), "llama.cpp (managed)")
        self.assertTrue(llama_cpp_managed_selected({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}}))
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": False}, "llama_cpp": {"mode": "auto"}}), "llama.cpp (external, auto-detect)")
        self.assertEqual(llama_cpp_backend_selection({"ollama": {"enabled": False}, "llama_cpp": {"mode": "off"}}), "disabled")

    def test_runtime_assets_are_pinned_and_unsupported_platforms_fail(self):
        self.assertEqual(LlamaCppManagedRuntime.runtime_asset("win32", "amd64")[0], "llama-b10964-bin-win-cpu-x64.zip")
        self.assertEqual(LlamaCppManagedRuntime.runtime_asset("darwin", "arm64")[0], "llama-b10964-bin-macos-arm64.tar.gz")
        with self.assertRaisesRegex(RuntimeError, "not supported"):
            LlamaCppManagedRuntime.runtime_asset("freebsd", "x86_64")

    def test_download_requires_expected_sha256_and_removes_partial_files(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "artifact.bin"
            payload = b"verified runtime bytes"
            with patch("local_ai_hub.llama_cpp_runtime.urlopen", return_value=io.BytesIO(payload)):
                LlamaCppManagedRuntime._download("https://example.invalid/artifact", destination, hashlib.sha256(payload).hexdigest(), 100, 1)
            self.assertEqual(destination.read_bytes(), payload)
            destination.unlink()
            with patch("local_ai_hub.llama_cpp_runtime.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    LlamaCppManagedRuntime._download("https://example.invalid/artifact", destination, "0" * 64, 100, 1)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())

    def test_archive_extraction_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.txt", "bad")
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                LlamaCppManagedRuntime._extract(archive, Path(temp) / "extract", "zip")
            self.assertFalse((Path(temp) / "outside.txt").exists())

    def test_preset_maps_configured_text_aliases_to_verified_default_model(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "models": {"fast_code": "qwen2.5-coder:1.5b"},
                "llama_cpp": {"models": {
                    "qwen2.5-coder:1.5b": {"served_model": "hub-qwen-15", "url": "http://127.0.0.1:12438"},
                    "qwen2.5-coder:3b": {"served_model": "hub-qwen-3", "url": "http://127.0.0.1:12438"},
                    "qwen3-vl:4b": {"served_model": "hub-qwen-vl", "url": "http://127.0.0.1:12438"},
                }},
            })
            runtime._write_preset()
            preset = (runtime.runtime_dir / "hub.models.ini").read_text(encoding="utf-8")
            self.assertIn("[hub-qwen-15]", preset)
            self.assertIn("[hub-qwen-3]", preset)
            self.assertNotIn("[hub-qwen-vl]", preset)
            self.assertIn("load-on-startup = true", preset)
            self.assertIn("load-on-startup = false", preset)

    def test_intel_start_retries_on_cpu_after_sycl_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LlamaCppManagedRuntime({
                "server": {"state_dir": temp},
                "_hardware": {"gpus": [{"vendor": "Intel", "name": "Intel Arc"}]},
                "models": {"fast_code": "qwen2.5-coder:1.5b"},
                "llama_cpp": {"mode": "on", "startup_timeout_seconds": 3, "models": {
                    "qwen2.5-coder:1.5b": {"served_model": "hub-qwen-15", "url": "http://127.0.0.1:12438"},
                }},
            })
            fake_proc = SimpleNamespace(pid=42, poll=lambda: None)
            with (
                patch.object(runtime, "is_online", return_value=False),
                patch.object(runtime, "provision", return_value=runtime.runtime_dir / "bin" / "llama-server.exe"),
                patch.object(runtime, "_find_server", return_value=runtime.runtime_dir / "bin" / "llama-server.exe"),
                patch.object(runtime, "_device_attempts", return_value=[("SYCL0", 0.1), ("none", 0.1)]),
                patch.object(runtime, "_ready", side_effect=[False, True]),
                patch("local_ai_hub.llama_cpp_runtime.subprocess.Popen", return_value=fake_proc) as popen,
                patch("local_ai_hub.llama_cpp_runtime.terminate_tree", return_value=True),
            ):
                self.assertTrue(runtime.ensure_running())
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(popen.call_args_list[0].args[0][-1], "SYCL0")
            self.assertEqual(popen.call_args_list[1].args[0][-1], "none")
            self.assertEqual(runtime.mode_path.read_text(encoding="utf-8"), "none")

    def test_install_and_update_guidance_share_provider_selection_policy(self):
        for relative in ("docs/INSTALLATION.md", "docs/OPERATIONS.md", "docs/INSTALL_PROMPT.md", "docs/UPDATE_PROMPT.md", "docs/LLAMA_CPP_SYCL.md"):
            guidance = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertIn('llama_cpp.mode = "on"', guidance, relative)
            self.assertIn('"auto"', guidance, relative)
            self.assertNotIn("never installs or starts llama.cpp automatically", guidance, relative)


if __name__ == "__main__":
    unittest.main()
