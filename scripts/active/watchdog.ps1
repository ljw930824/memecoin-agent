# watchdog.ps1 - 10s heartbeat monitor for realtime_sm_monitor.py
# Runs in continuous loop; Task Scheduler fires every ~1min as backup (restarts this if it dies)
$ErrorActionPreference = 'SilentlyContinue'
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$WORKDIR = Split-Path -Parent (Split-Path -Parent $SCRIPT_DIR)
$SCRIPT = Join-Path $SCRIPT_DIR "realtime_sm_monitor.py"
$LOG = Join-Path $WORKDIR "data\watchdog.log"
$PYTHON = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PYTHON) { $PYTHON = "python" }
$CHECK_INTERVAL = 10  # seconds
$LOG_INTERVAL = 60     # log "OK" at most every 60s
$STATE_STALE_SEC = 120  # restart if state file not updated for 2 min (process stuck)

$last_ok_log = [datetime]::MinValue
$was_dead = $false

function ts { Get-Date -Format 'yyyy-MM-dd HH:mm:ss' }

while ($true) {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*realtime_sm_monitor*' }

    # Detect stuck process: state file stale = process not writing
    $STATE_FILE = Join-Path $WORKDIR "data\sm_monitor_state_dryrun.json"
    $stale = $false
    if (Test-Path $STATE_FILE) {
        $mtime = (Get-Item $STATE_FILE).LastWriteTime
        if ((New-TimeSpan -Start $mtime -End (Get-Date)).TotalSeconds -gt $STATE_STALE_SEC) {
            $stale = $true
        }
    }

    if (-not $running -or $stale) {
        $now = Get-Date
        if ($stale) {
            $mtimeStr = (Get-Item $STATE_FILE).LastWriteTime.ToString('HH:mm:ss')
            "[$(ts)] ALERT: Monitor stuck (state stale since $mtimeStr), restarting" | Out-File -Append -FilePath $LOG -Encoding UTF8
        } else {
            "[$(ts)] ALERT: Monitor not found, restarting" | Out-File -Append -FilePath $LOG -Encoding UTF8
        }
        # Kill ALL python processes running this script
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*realtime_sm_monitor*' } | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        Start-Process -FilePath $PYTHON -ArgumentList @('-u', $SCRIPT, '--dry-run') `
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
