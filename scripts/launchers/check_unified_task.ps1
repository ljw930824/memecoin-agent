$task = Get-ScheduledTask | Where-Object {$_.TaskName -match 'SmartMoneyUnified'}
$task.Actions | ForEach-Object {
  Write-Output "Execute: $($_.Execute)"
  Write-Output "Arguments: $($_.Arguments)"
}
$task.Triggers | ForEach-Object {
  Write-Output "Trigger: $($_.CimClass.CimClassName) | Interval: $($_.Repetition.Interval) | Enabled: $($_.Enabled)"
}
