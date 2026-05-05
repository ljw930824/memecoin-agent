$existing = Get-ScheduledTask -TaskName "DiverMonitor" -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName "DiverMonitor" -Confirm:$false
    Write-Host "Deleted old task"
}

$action = New-ScheduledTaskAction -Execute "python" -Argument "`"C:\Users\dell\.qclaw\workspace\scripts\diver_monitor.py`"" -WorkingDirectory "C:\Users\dell\.qclaw\workspace"
$trigger = New-ScheduledTaskTrigger -Once -At "2026-04-28T12:30:00" -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 1)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$t = Register-ScheduledTask -TaskName "DiverMonitor" -Action $action -Trigger $trigger -Settings $settings -Description "Diver Strategy - 30min interval" -Force

Write-Host "Task registered, State:" $t.State
Get-ScheduledTaskInfo -TaskName "DiverMonitor" | Select-Object TaskName, State, NextRunTime, LastRunTime
