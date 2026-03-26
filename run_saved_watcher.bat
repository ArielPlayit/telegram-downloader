@echo off
setlocal

set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if exist "%PY%" (
    "%PY%" "%ROOT%watch_saved_downloads.py"
) else (
    py "%ROOT%watch_saved_downloads.py"
)

endlocal
