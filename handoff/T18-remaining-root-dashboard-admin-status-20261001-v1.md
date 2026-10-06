# T18 remaining root dashboard/admin/status selector

Date: 2026-10-01. Root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; candidate HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`. HUB ignored. No root file content changed.

## Excluded completed coverage

Did not rerun errno diagnostics, accounting, earlier 11-case root-pinned UI/SQLite selector, or candidate 65-case selector.

## Bounded root-pinned batch

Root modules were imported before pytest and all four source paths plus SHA-256 values asserted: `http_server.py` `6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3`; `dashboard.py` `9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760`; `app.py` `2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546`; `telemetry.py` `79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE`.

Command selector:

```powershell
$root='C:\Users\Adam\.local-ai-hub'
$src=Join-Path $root 'src'
$tests=Join-Path $root 'tests'
$ids=@('test_http_admin_action_auth_t18.py','test_http_status_diagnostics_t18.py','test_status_snapshot_quality.py','test_dashboard_operational_surfaces.py::test_dashboard_exposes_activity_mode_and_reports_http_failures','test_dashboard_operational_surfaces.py::test_dashboard_requires_server_confirmation_before_reporting_mode_update','test_dashboard_operational_surfaces.py::test_dashboard_reports_incomplete_vram_unload_after_gaming_pause','test_dashboard_operational_surfaces.py::test_operator_surfaces_report_all_transition_failures','test_dashboard_operational_surfaces.py::test_dashboard_api_fetch_has_bounded_request_timeout')
$pytestArgs=@()
foreach($id in $ids){$parts=$id -split '::',2; $file=Join-Path $tests $parts[0]; $pytestArgs+=if($parts.Count -eq 2){"r'$file::$($parts[1])'"}else{"r'$file'"}}
$list=$pytestArgs -join ','
$code="import sys,hashlib; from pathlib import Path; sys.path.insert(0,r'$src'); import local_ai_hub.http_server,local_ai_hub.dashboard,local_ai_hub.app,local_ai_hub.telemetry; modules=[local_ai_hub.http_server,local_ai_hub.dashboard,local_ai_hub.app,local_ai_hub.telemetry]; expected=[('http_server.py','6F0B986255DD231F40761538227A66F0A9B97F7659064952593FB83B48130DB3'),('dashboard.py','9FC006FD0F5A3E3EBE2CFA0DA79F8786DFD4CB7BE1AB2CD6599CF7363C51A760'),('app.py','2B6E826FEF08863EF9BF1528E402F7DE041A6A2B08A3812E8454398BC1750546'),('telemetry.py','79146032D1C904FA57875858A4C4265A8FE6D02BCC62F9CBCEE258D7DAF685EE')]; package=Path(r'$src')/'local_ai_hub'; assert all(Path(m.__file__).resolve()==package/name and hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest().upper()==sha for m,(name,sha) in zip(modules,expected)); import pytest; raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--tb=short',$list]))"
python -B -W error::ResourceWarning -c $code
```

Result: **25 passed in 1.80s**. Covers admin action-token scope/audit, real mode POST, status diagnostics and dependency deadlines/degradation, dashboard transition feedback, and bounded API timeout. Excludes errno/accounting suites.

The first generated invocation mistakenly doubled `tests` in absolute paths. Pytest reported one missing file and ran zero tests. Corrected selector above produced the 25-pass receipt.

## Post-run integrity

Root source and test hashes matched post-run. Root tracked files were already dirty and T18 made no code/test write. Relevant source pins above; test pins: `tests/test_http_admin_action_auth_t18.py` `3C82151BB3C064E37BDA4CB052EE09CBF9E02B7A3144CBDDE065EDABE46BCC20`; `tests/test_http_status_diagnostics_t18.py` `AE835F8F1521BF57AC34616D83117F3E8EC5D7813D0A4464BEE8D4174CAF966C`; `tests/test_status_snapshot_quality.py` `1A08CC0F690FF70D4A3D78F9C2A122965CC4FBCD2063544090627B4A4C4CF0C8`; `tests/test_dashboard_operational_surfaces.py` `46F2816F1CE47665ED7B01F8C87B617C15B222F1AD1923BF736AE577492B31B6`.

Blocker: none for this bounded T18 selector. Full root release gate remains T20-owned; no full-suite, live Hub, GPU, or user-browser validation here.

