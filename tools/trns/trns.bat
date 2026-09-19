@echo off
REM trns.bat — Windows launcher for trns.py
REM
REM When this folder is on PATH (see `python trns.py --path-add`), typing
REM
REM     trns hello world
REM
REM resolves here and forwards to the Python entry point.
REM
REM We deliberately avoid `chcp 65001` (UTF-8) so console output stays in the
REM user's default code page; the Python layer uses Unicode escapes anyway.

setlocal
set "TRNS_SCRIPT=%~dp0trns.py"

where python >nul 2>nul
if errorlevel 1 (
    echo trns: Python is not on PATH. Install Python 3.9+ from python.org and try again.
    exit /b 1
)

python "%TRNS_SCRIPT%" %*
exit /b %ERRORLEVEL%
