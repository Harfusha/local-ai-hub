@echo off
set "LAH_ROOT=%~dp0.."
set "PYTHONPATH=%LAH_ROOT%\src;%PYTHONPATH%"
if exist "%LAH_ROOT%\.venv\Scripts\python.exe" (
  "%LAH_ROOT%\.venv\Scripts\python.exe" -m local_ai_hub.token_economy repo_map %*
) else (
  python -m local_ai_hub.token_economy repo_map %*
)
