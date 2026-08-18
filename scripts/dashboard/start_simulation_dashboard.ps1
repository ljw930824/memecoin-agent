param(
    [int]$DashboardPort = 8765
)

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$PythonCommand = Get-Command python -ErrorAction Stop
$Python = $PythonCommand.Source
$Data = Join-Path $Root 'data'
New-Item -ItemType Directory -Force -Path $Data | Out-Null

$dashboardProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*scripts\dashboard\dashboard_server.py*' })
if($dashboardProcesses.Count -eq 0){
    Start-Process -FilePath $Python `
        -ArgumentList @('-u', (Join-Path $Root 'scripts/dashboard/dashboard_server.py'), '--host', '127.0.0.1', '--port', "$DashboardPort") `
        -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Data 'dashboard.out.log') `
        -RedirectStandardError (Join-Path $Data 'dashboard.err.log') | Out-Null
}

$simulationProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*scripts\active\realtime_sm_monitor.py*--dry-run*' })
if($simulationProcesses.Count -eq 0){
    Start-Process -FilePath $Python `
        -ArgumentList @('-u', (Join-Path $Root 'scripts/active/realtime_sm_monitor.py'), '--dry-run') `
        -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Data 'simulation.out.log') `
        -RedirectStandardError (Join-Path $Data 'simulation.err.log') | Out-Null
}

Write-Output "Dashboard: http://127.0.0.1:$DashboardPort/"
Write-Output 'Simulation: DRY-RUN'
