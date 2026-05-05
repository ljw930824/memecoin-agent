$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$log = "C:\Users\dell\.qclaw\workspace\data\listener-launch.log"
$script = "C:\Users\dell\.qclaw\workspace\scripts\signal_listener.py"

function Write-Log($msg) {
    $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    "[$ts] $msg" | Out-File -Append -Encoding UTF8 $log
}

# Check if already running
$existing = Get-Process | Where-Object {
    $_.ProcessName -like '*python*' -and $_.CommandLine -like '*signal_listener*'
}
if ($existing) {
    Write-Log "Already running PID $($existing.Id)"
    Write-Host "Listener already running (PID $($existing.Id))"
    exit 0
}

# Find pythonw.exe
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    # Try common locations
    $candidates = @(
        "C:\Python312\pythonw.exe",
        "C:\Users\dell\AppData\Local\Programs\Python\Python312\pythonw.exe",
        "C:\Users\dell\AppData\Local\Microsoft\WindowsApps\pythonw.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $pythonw = $c; break }
    }
}

if (-not $pythonw) {
    Write-Log "ERROR: pythonw.exe not found"
    Write-Host "ERROR: pythonw.exe not found. Install Python or add to PATH."
    exit 1
}

Write-Log "Using pythonw: $pythonw"

try {
    $proc = Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" `
        -PassThru -WindowStyle Hidden -WorkingDirectory "C:\Users\dell\.qclaw\workspace\scripts"
    Write-Log "Started PID $($proc.Id)"
    Write-Host "Signal listener started (PID $($proc.Id))"
    Write-Host "Log: C:\Users\dell\.qclaw\workspace\data\listener.log"
} catch {
    Write-Log "ERROR starting listener: $_"
    Write-Host "ERROR: $_"
    exit 1
}
