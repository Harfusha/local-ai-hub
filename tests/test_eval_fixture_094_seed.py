from pathlib import Path
import shutil
import subprocess
import sys


def test_batch_fixture_is_copyable_and_has_reproducible_failing_oracle(tmp_path):
    source = Path(__file__).resolve().parents[1] / "docs" / "agent-evaluation" / "fixtures" / "case-094"
    fixture = tmp_path / "case-094"
    shutil.copytree(source, fixture)
    result = subprocess.run(
        [sys.executable, "oracle_094.py"], cwd=fixture,
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0
    assert "FAILED (failures=3)" in result.stderr
    assert "Ran 3 tests" in result.stderr


def test_batch_oracle_accepts_a_repaired_disposable_copy(tmp_path):
    source = Path(__file__).resolve().parents[1] / "docs" / "agent-evaluation" / "fixtures" / "case-094"
    fixture = tmp_path / "case-094"
    shutil.copytree(source, fixture)
    (fixture / "batch_export.py").write_text(
        "class ExportCancelled(Exception):\n    pass\n\n"
        "def process_batch(items, exporter):\n"
        "    results = []\n"
        "    for item in items:\n"
        "        try:\n"
        "            value = exporter(item)\n"
        "            results.append({'id': item['id'], 'status': 'ok', 'value': value})\n"
        "        except ExportCancelled as exc:\n"
        "            results.append({'id': item['id'], 'status': 'cancelled', 'error': str(exc)})\n"
        "        except Exception as exc:\n"
        "            results.append({'id': item['id'], 'status': 'error', 'error': str(exc)})\n"
        "    return {'success': all(item['status'] == 'ok' for item in results), 'items': results}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "oracle_094.py"], cwd=fixture,
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Ran 3 tests" in result.stderr
