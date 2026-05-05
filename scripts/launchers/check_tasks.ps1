Get-ScheduledTask | Where-Object {$_.TaskName -match 'scalper|signal|position|unified'} | ForEach-Object {
  $info = $_ | Get-ScheduledTaskInfo
  Write-Output "$($_.TaskName) | State: $($_.State) | LastRun: $($info.LastRunTime) | Result: $($info.LastTaskResult) | NextRun: $($info.NextRunTime)"
}
