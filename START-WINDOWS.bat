@echo off
setlocal
cd /d "%~dp0"
set "HELPDESK_SQLSERVER="
echo PM06 Help Desk: http://localhost:8096
echo operator, engineer, engineer2, admin / Practice2026!
echo Keep this window open. Press Ctrl+C to stop.
if exist "%~dp0runtime-windows\python.exe" (
    "%~dp0runtime-windows\python.exe" -X utf8 "%~dp0app.py" --http --port 8096 --seed
    goto finish
)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -X utf8 "%~dp0app.py" --http --port 8096 --seed
    goto finish
)
where python >nul 2>&1
if not errorlevel 1 (
    python -X utf8 "%~dp0app.py" --http --port 8096 --seed
    goto finish
)
echo Install Python 3.9 or later from python.org, or use the full Windows ZIP.
:finish
pause
