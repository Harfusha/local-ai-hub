from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_ai_hub.gpu_monitor import _bounded_percent, _windows_engine_usage


class GpuMonitorTests(unittest.TestCase):
    def test_windows_engine_usage_uses_busy_engine_and_separates_neural_engines(self):
        counters = [
            {"Name": "pid_7_luid_0x00000000_0x00014AA2_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 25},
            {"Name": "pid_8_luid_0x00000000_0x00014AA2_phys_0_eng_0_engtype_3D", "UtilizationPercentage": 20},
            {"Name": "pid_7_luid_0x00000000_0x00014AA2_phys_0_eng_1_engtype_Copy", "UtilizationPercentage": 62},
            {"Name": "pid_7_luid_0x00000000_0x00014F1D_phys_0_eng_0_engtype_Neural", "UtilizationPercentage": 30},
            {"Name": "pid_8_luid_0x00000000_0x00014F1D_phys_0_eng_0_engtype_Neural", "UtilizationPercentage": 35},
        ]

        self.assertEqual(_windows_engine_usage(counters), {
            "gpu_utilization_pct": 62.0,
            "npu_utilization_pct": 65.0,
        })

    def test_missing_counter_is_unavailable_and_zero_is_a_real_reading(self):
        self.assertEqual(_windows_engine_usage([]), {
            "gpu_utilization_pct": None,
            "npu_utilization_pct": None,
        })
        self.assertIsNone(_bounded_percent(None))
        self.assertEqual(_bounded_percent(0), 0.0)
