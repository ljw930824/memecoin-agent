# Setup Task Scheduler for new architecture
# Disables old tasks, creates MonitorPositions (1min) + SmartMoneyUnified (5min backup)

$ErrorActionPreference = 'SilentlyContinue'

# 1. Disable old tasks
Disable-ScheduledTask -TaskName 'SmartMoneySignals' | Out-Null
Disable-ScheduledTask -TaskName 'SmartMoneyManager' | Out-Null
Write-Host "Old tasks disabled: SmartMoneySignals, SmartMoneyManager"

# 2. Create MonitorPositions (every 1 minute)
$action1 = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument '-ExecutionPolicy Bypass -File "C:\Users\dell\.qclaw\workspace\scripts\run_monitor.ps1"'
$trigger1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1).ToString('HH:mm') `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 9999)
Register-ScheduledTask -TaskName 'MonitorPositions' -Action $action1 -Trigger $trigger1 -Force | Out-Null
Write-Host "Created: MonitorPositions (every 1 min)"

# 3. Create SmartMoneyUnified (every 5 minutes, backup scan)
$action2 = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument '-ExecutionPolicy Bypass -File "C:\Users\dell\.qclaw\workspace\scripts\run_unified.ps1"'
$trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2).ToString('HH:mm') `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 9999)
Register-ScheduledTask -TaskName 'SmartMoneyUnified' -Action $action2 -Trigger $trigger2 -Force | Out-Null
Write-Host "Created: SmartMoneyUnified (every 5 min, backup)"

Write-Host ""
Write-Host "Done! Current tasks:"
Get-ScheduledTask | Where-Object {$_.TaskName -in @('MonitorPositions','SmartMoneyUnified','SmartMoneySignals','SmartMoneyManager')} |
    Select-Object TaskName, State | Format-Table -AutoSize
