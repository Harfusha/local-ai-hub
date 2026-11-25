from unittest.mock import Mock

from local_ai_hub.vram_balancer import VRAMBalancer


def test_sampler_uses_hardware_inventory_for_openvino_integrated_gpu(monkeypatch):
    hardware = {
        "gpus": [],
        "openvino_gpu_devices": [
            {"vendor": "intel", "name": "Intel Arc (iGPU)", "kind": "gpu"}
        ],
        "openvino_devices": [],
    }
    inventory_probe = Mock(return_value={"available": False})
    generic_probe = Mock(side_effect=AssertionError("generic probe selected"))
    monkeypatch.setattr(
        "local_ai_hub.vram_balancer.get_gpu_telemetry_for_hardware", inventory_probe
    )
    monkeypatch.setattr("local_ai_hub.vram_balancer.get_gpu_telemetry", generic_probe)

    balancer = VRAMBalancer({"_hardware": hardware})
    balancer._status_from_telemetry = Mock()
    balancer._sample_gpu_telemetry(1)

    inventory_probe.assert_called_once_with(hardware)
    generic_probe.assert_not_called()
