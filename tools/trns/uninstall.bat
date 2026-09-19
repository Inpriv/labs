@echo off
REM uninstall.bat — remove trns from PATH
REM
REM Strips this folder out of the user PATH. Does not delete the project
REM files (so you can keep them and reinstall later).

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo trns: Python is not on PATH, but trying anyway in case config exists.
)

python trns.py --path-remove
if errorlevel 1 (
    echo.
    echo uninstall: PATH update failed. Try running as Administrator.
    exit /b 1
)

echo.
echo trns removed from PATH.
echo Your config in %USERPROFILE%\.trns is left intact.
echo To wipe it too, delete that folder manually.
endlocal
