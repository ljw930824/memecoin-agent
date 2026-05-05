$action = New-ScheduledTaskAction -Execute "python" -Argument "`"C:\Users\dell\.qclaw\workspace\scripts\diver_monitor.py`"" -WorkingDirectory "C:\Users\dell\.qclaw\workspace"
$trigger = New-ScheduledTaskTrigger -Once -At "2026-04-28T12:00:00" -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::FromHours(1))
$task = Get-ScheduledTask -TaskName "DiverMonitor" -ErrorAction SilentlyContinue
if ($task) {
    Set-ScheduledTask -TaskName "DiverMonitor" -Action $action -Trigger $trigger -Settings $settings
    Write-Host "Updated DiverMonitor task"
} else {
    Register-ScheduledTask -TaskName "DiverMonitor" -Action $action -Trigger $trigger -Settings $settings -Description "Diver Strategy Monitor - 30min interval"
    Write-Host "Registered DiverMonitor task"
}
Get-ScheduledTask -TaskName "DiverMonitor" | Select-Object TaskName, State, @{N="NextRun";E={$_.NextRunTime}}, @{N="LastRun";E={$_.LastRunTime}}
