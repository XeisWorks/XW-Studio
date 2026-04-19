@echo off
setlocal

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [XW-Studio] Kein venv gefunden unter: "%VENV_PY%"
    echo.
    echo Bitte zuerst im Projektordner ein venv anlegen und Abhaengigkeiten installieren.
    pause
    exit /b 1
)

pushd "%ROOT%"

rem Support src-layout start without requiring editable install.
set "PYTHONPATH=%ROOT%src;%PYTHONPATH%"
"%VENV_PY%" -m xw_studio
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%
