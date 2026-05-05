# run_minute_scan.ps1 - 每分钟扫描 Smart Money 信号
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "scan_signals_minute.py"

# Set UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

try {
    & python $pythonScript 2>&1
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
    exit 1
}
