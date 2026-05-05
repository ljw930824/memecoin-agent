# Stop and disable the DiverMonitor task
$task = Get-ScheduledTask -TaskName "DiverMonitor"
if ($task) {
    Write-Host "Found: $($task.TaskName)"
    Stop-ScheduledTask -TaskName "DiverMonitor" -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName "DiverMonitor"
    $t = Get-ScheduledTask -TaskName "DiverMonitor"
    Write-Host "State after stop: $($t.State)"
    Write-Host "Action: STOPPED and DISABLED"
} else {
    Write-Host "DiverMonitor task not found"
}