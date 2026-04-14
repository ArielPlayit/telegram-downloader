@echo off
setlocal

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else (
    set "PY=py"
)

echo [build] Installing dependencies...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :error
%PY% -m pip install -r "%ROOT%requirements.txt" pyinstaller
if errorlevel 1 goto :error

echo [build] Building TelegramDownloader.exe...
%PY% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name TelegramDownloader ^
    --add-data "%ROOT%locales;locales" ^
    --add-data "%ROOT%config.py;." ^
    --add-data "%ROOT%downloads;downloads" ^
    "%ROOT%gui_app.py"
if errorlevel 1 goto :error

echo.
echo [build] Done.
echo [build] EXE: "%ROOT%dist\TelegramDownloader\TelegramDownloader.exe"
goto :eof

:error
echo.
echo [build] Error while building EXE.
exit /b 1
