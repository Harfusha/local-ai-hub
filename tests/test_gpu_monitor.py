from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub import gpu_monitor


class GpuMonitorTests(unittest.TestCase):
    def test_windows_engine_usage_sums_processes_per_engine_and_separates_npu(self):
        counters = [
            {"Name": "pid_7_luid_0x00000000_0x00014AA2_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 25},
            {"Name": "pid_8_luid_0x00000000_0x00014AA2_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 20},
            {"Name": "pid_7_luid_0x00000000_0x00014AA2_phys_0_eng_1_engtype_Copy", "UtilizationPercentage": 62},
            {"Name": "pid_7_luid_0x00000000_0x00014F1D_phys_0_eng_0_engtype_Neural", "UtilizationPercentage": 30},
            {"Name": "pid_8_luid_0x00000000_0x00014F1D_phys_0_eng_0_engtype_Neural", "UtilizationPercentage": 35},
        ]

        self.assertEqual(gpu_monitor._windows_engine_usage(counters), {
            "gpu_utilization_pct": 62.0,
            "npu_utilization_pct": 65.0,
        })

    def test_missing_counter_is_unavailable_and_zero_is_a_real_reading(self):
        self.assertEqual(gpu_monitor._windows_engine_usage([]), {
            "gpu_utilization_pct": None,
            "npu_utilization_pct": None,
        })
        self.assertIsNone(gpu_monitor._bounded_percent(None))
        self.assertEqual(gpu_monitor._bounded_percent(0), 0.0)
        self.assertIsNone(gpu_monitor._bounded_percent(float("nan")))

    @unittest.skipUnless(os.name == "nt", "Windows hardware sampler")
    def test_inflight_windows_sample_does_not_spawn_duplicate_queries(self):
        prior = (
            gpu_monitor._WINDOWS_CACHE,
            gpu_monitor._WINDOWS_CACHE_TIME,
            gpu_monitor._WINDOWS_REFRESHING,
        )
        try:
            gpu_monitor._WINDOWS_CACHE = {}
            gpu_monitor._WINDOWS_CACHE_TIME = 0.0
            gpu_monitor._WINDOWS_REFRESHING = True
            with patch.object(gpu_monitor.shutil, "which", return_value="powershell.exe"), \
                    patch.object(gpu_monitor.threading, "Thread") as thread:
                self.assertEqual(gpu_monitor._windows_sample(), {})
                thread.assert_not_called()
        finally:
            (
                gpu_monitor._WINDOWS_CACHE,
                gpu_monitor._WINDOWS_CACHE_TIME,
                gpu_monitor._WINDOWS_REFRESHING,
            ) = prior

    def test_unexpected_refresh_error_propagates_and_clears_refresh_state(self):
        prior = (
            gpu_monitor._WINDOWS_CACHE,
            gpu_monitor._WINDOWS_CACHE_TIME,
            gpu_monitor._WINDOWS_REFRESHING,
        )
        try:
            gpu_monitor._WINDOWS_CACHE = {"stale": True}
            gpu_monitor._WINDOWS_CACHE_TIME = 0.0
            gpu_monitor._WINDOWS_REFRESHING = True
            with patch.object(gpu_monitor.subprocess, "run", side_effect=RuntimeError("unexpected")):
                with self.assertRaisesRegex(RuntimeError, "unexpected"):
                    gpu_monitor._refresh_windows_sample()
            self.assertEqual(gpu_monitor._WINDOWS_CACHE, {})
            self.assertFalse(gpu_monitor._WINDOWS_REFRESHING)
        finally:
            (
                gpu_monitor._WINDOWS_CACHE,
                gpu_monitor._WINDOWS_CACHE_TIME,
                gpu_monitor._WINDOWS_REFRESHING,
            ) = prior

    def test_unexpected_thread_start_error_propagates_and_clears_refresh_state(self):
        prior = (
            gpu_monitor._WINDOWS_CACHE,
            gpu_monitor._WINDOWS_CACHE_TIME,
            gpu_monitor._WINDOWS_REFRESHING,
        )
        try:
            gpu_monitor._WINDOWS_CACHE = {}
            gpu_monitor._WINDOWS_CACHE_TIME = 0.0
            gpu_monitor._WINDOWS_REFRESHING = False
            with patch.object(gpu_monitor.os, "name", "nt"), \
                    patch.object(gpu_monitor.shutil, "which", return_value="powershell.exe"), \
                    patch.object(gpu_monitor.threading, "Thread") as thread:
                thread.return_value.start.side_effect = ValueError("unexpected")
                with self.assertRaisesRegex(ValueError, "unexpected"):
                    gpu_monitor._windows_sample()
            self.assertFalse(gpu_monitor._WINDOWS_REFRESHING)
        finally:
            (
                gpu_monitor._WINDOWS_CACHE,
                gpu_monitor._WINDOWS_CACHE_TIME,
                gpu_monitor._WINDOWS_REFRESHING,
            ) = prior

    def test_hardware_fallback_preserves_measured_free_vram(self):
        hardware = {
            "gpus": [{
                "vendor": "nvidia",
                "backend": "cuda",
                "name": "NVIDIA GPU",
                "vram_mb": 16303,
                "vram_free_mb": 3000,
            }]
        }
        with patch.object(gpu_monitor, "_GPU_CACHE", {}), \
                patch.object(gpu_monitor, "_GPU_CACHE_TIME", 0.0), \
                patch.object(gpu_monitor, "_nvidia_live", return_value=None), \
                patch.object(gpu_monitor, "_rocm_live", return_value=None), \
                patch.object(gpu_monitor, "_windows_live", return_value=None), \
                patch.object(gpu_monitor, "detect_hardware", return_value=hardware) as detect_hardware:
            result = gpu_monitor.get_gpu_telemetry()

        self.assertEqual(result["vram_total_mb"], 16303)
        self.assertEqual(result["vram_available_mb"], 3000)
        self.assertFalse(result["live_metrics"])
        detect_hardware.assert_called_once_with(include_openvino=False)

    def test_dynamic_budget_uses_explicit_available_vram_measurement(self):
        telemetry = {
            "vram_total_mb": 16303,
            "vram_used_mb": 0,
            "vram_available_mb": 3000,
        }
        with patch.object(gpu_monitor, "get_gpu_telemetry", return_value=telemetry):
            budget = gpu_monitor.get_dynamic_token_budget(
                base_tokens=65536,
                min_tokens=8192,
                max_tokens=65536,
            )

        self.assertEqual(budget, 16384)


if __name__ == "__main__":
    unittest.main()
