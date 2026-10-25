from types import SimpleNamespace

import pytest

from local_ai_hub import gpu_monitor


def nvidia_sample(monkeypatch, output):
    commands = []
    monkeypatch.setattr(gpu_monitor.shutil, "which", lambda _name: "nvidia-smi")

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == 2.0
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(gpu_monitor.subprocess, "run", run)
    return gpu_monitor._nvidia_live(), commands


def test_nvidia_reports_measured_free_memory_not_total_minus_used(monkeypatch):
    sample, commands = nvidia_sample(monkeypatch, "RTX Test, 12, 2000, 8192, 40, 55, 6000\n")
    assert sample["vram_available_mb"] == 6000.0
    assert sample["vram_used_mb"] == 2000.0
    assert sample["vram_total_mb"] == 8192.0
    assert "memory.free" in commands[0][1]


@pytest.mark.parametrize("free", ["N/A", "-1", "nan", "inf", "9000"])
def test_nvidia_unavailable_or_invalid_free_memory_stays_unknown(monkeypatch, free):
    sample, _ = nvidia_sample(monkeypatch, f"RTX Test, 12, 2000, 8192, 40, 55, {free}\n")
    assert sample["vram_available_mb"] is None


def test_nvidia_incomplete_csv_cannot_prove_free_memory(monkeypatch):
    sample, _ = nvidia_sample(monkeypatch, "RTX Test, 12, 2000, 8192, 40, 55\n")
    assert sample is None
