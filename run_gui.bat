@echo off
setlocal

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" "%~dp0gui_app.py"
) else (
    py "%~dp0gui_app.py"
)
