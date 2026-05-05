@echo off
setlocal
set SCRIPT=C:\Users\dell\.qclaw\workspace\scripts\active\realtime_sm_monitor.py
set LOG=C:\Users\dell\.qclaw\workspace\data\watchdog.log
set PYTHON=C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe

rem Check if monitor is running
tasklist /FI "IMAGENAME eq python.exe" /FO CSV | findstr /I "python.exe" >nul
if errorlevel 1 (
    echo [%date% %time%] ALERT: No python process, restarting monitor >> "%LOG%"
    start /MIN "" "%PYTHON%" "%SCRIPT%"
    timeout /t 3 /nobreak >nul
    echo [%date% %time%] Monitor restarted >> "%LOG%"
    goto :done
)

rem More specific check: is OUR monitor running?
wmic process where "name='python.exe' and commandline like '%%realtime_sm_monitor%%'" get processid 2>nul | findstr /R "[0-9]" >nul
if errorlevel 1 (
    echo [%date% %time%] ALERT: Monitor not found among python procs, restarting >> "%LOG%"
    start /MIN "" "%PYTHON%" "%SCRIPT%"
    timeout /t 3 /nobreak >nul
    echo [%date% %time%] Monitor restarted >> "%LOG%"
) else (
    echo [%date% %time%] OK: Monitor running >> "%LOG%"
)

:done
