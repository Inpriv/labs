@echo off
REM install.bat — set up trns on Windows
REM
REM Adds this folder to the user PATH and prints a friendly summary.
REM Re-running it is safe; it silently no-ops if the folder is already there.

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo trns: Python is not on PATH. Install Python 3.9+ from python.org and try again.
    exit /b 1
)

python trns.py --path-add
if errorlevel 1 (
    echo.
    echo install: PATH update failed. Try running as Administrator, or check the log above.
    exit /b 1
)

echo.
echo trns is installed.
echo.
echo   - Type  trns         in any new terminal window to start.
echo   - Type  trns hello   to translate a single phrase.
echo   - Type  trns --help  for all command-line options.
echo.
echo If a terminal you already have open does not see the new command,
echo close it and open a fresh one.
endlocal
