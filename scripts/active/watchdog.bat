@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%..\.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "SCRIPT=%SCRIPT_DIR%realtime_sm_monitor.py"
set "LOG=%ROOT%\data\watchdog.log"
for /f "delims=" %%I in ('where python 2^>nul') do if not defined PYTHON set "PYTHON=%%I"
if not defined PYTHON set "PYTHON=python"

rem Check if monitor is running
tasklist /FI "IMAGENAME eq python.exe" /FO CSV | findstr /I "python.exe" >nul
if errorlevel 1 (
    echo [%date% %time%] ALERT: No python process, restarting monitor >> "%LOG%"
    start /MIN "" "%PYTHON%" -u "%SCRIPT%" --dry-run
    timeout /t 3 /nobreak >nul
    echo [%date% %time%] Monitor restarted >> "%LOG%"
    goto :done
)

rem More specific check: is OUR monitor running?
wmic process where "name='python.exe' and commandline like '%%realtime_sm_monitor%%'" get processid 2>nul | findstr /R "[0-9]" >nul
if errorlevel 1 (
    echo [%date% %time%] ALERT: Monitor not found among python procs, restarting >> "%LOG%"
    start /MIN "" "%PYTHON%" -u "%SCRIPT%" --dry-run
    timeout /t 3 /nobreak >nul
    echo [%date% %time%] Monitor restarted >> "%LOG%"
) else (
    echo [%date% %time%] OK: Monitor running >> "%LOG%"
)

:done
