# watchdog.ps1 - 10s heartbeat monitor for realtime_sm_monitor.py
# Runs in continuous loop; Task Scheduler fires every ~1min as backup (restarts this if it dies)
$ErrorActionPreference = 'SilentlyContinue'
$SCRIPT = "C:\Users\dell\.qclaw\workspace\scripts\active\realtime_sm_monitor.py"
$LOG = "C:\Users\dell\.qclaw\workspace\data\watchdog.log"
$PYTHON = "C:\Users\dell\AppData\Local\Programs\Python\Python310\python.exe"
$WORKDIR = "C:\Users\dell\.qclaw\workspace\scripts\active"
$CHECK_INTERVAL = 10  # seconds
$LOG_INTERVAL = 60     # log "OK" at most every 60s

$last_ok_log = [datetime]::MinValue
$was_dead = $false

function ts { Get-Date -Format 'yyyy-MM-dd HH:mm:ss' }

while ($true) {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*realtime_sm_monitor*' }

    if (-not $running) {
        $now = Get-Date
        "[$(ts)] ALERT: Monitor not found, restarting" | Out-File -Append -FilePath $LOG -Encoding UTF8
        Start-Process -FilePath $PYTHON -ArgumentList $SCRIPT `
            -WorkingDirectory $WORKDIR `
            -WindowStyle Hidden
        "[$(ts)] Monitor restarted" | Out-File -Append -FilePath $LOG -Encoding UTF8
        $was_dead = $true
        $last_ok_log = $now
    } else {
        $was_dead = $false
        if (([datetime]::Now - $last_ok_log).TotalSeconds -ge $LOG_INTERVAL) {
            "[$(ts)] OK: Monitor running (PID=$($running.ProcessId))" | Out-File -Append -FilePath $LOG -Encoding UTF8
            $last_ok_log = Get-Date
        }
    }

    Start-Sleep -Seconds $CHECK_INTERVAL
}
