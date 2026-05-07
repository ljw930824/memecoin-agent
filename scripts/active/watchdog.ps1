# watchdog.ps1 — Silent watchdog for smart money monitor
$ErrorActionPreference = 'SilentlyContinue'
$SCRIPT = "C:\Users\dell\.qclaw\workspace\scripts\active\realtime_sm_monitor.py"
$LOG = "C:\Users\dell\.qclaw\workspace\data\watchdog.log"
$PYTHON = "C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe"
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

# Check if OUR monitor is running
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*realtime_sm_monitor*' }

if (-not $running) {
    "[$ts] ALERT: Monitor not found, restarting" | Out-File -Append -FilePath $LOG -Encoding UTF8
    Start-Process -FilePath $PYTHON -ArgumentList $SCRIPT `
        -WorkingDirectory "C:\Users\dell\.qclaw\workspace\scripts\active" `
        -WindowStyle Hidden
    "[$ts] Monitor restarted" | Out-File -Append -FilePath $LOG -Encoding UTF8
} else {
    "[$ts] OK: Monitor running (PID=$($running.ProcessId))" | Out-File -Append -FilePath $LOG -Encoding UTF8
}
