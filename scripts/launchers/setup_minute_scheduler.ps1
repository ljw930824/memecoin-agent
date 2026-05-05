# setup_minute_scheduler.ps1 - 配置每分钟扫描任务
# 以管理员身份运行 PowerShell 后执行此脚本

$taskName = "SmartMoneyScan_1Min"
$scriptPath = "C:\Users\dell\.qclaw\workspace\scripts\run_minute_scan.ps1"
$logPath = "C:\Users\dell\.qclaw\workspace\data\cron.log"

# 检查是否已存在同名任务
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "任务 '$taskName' 已存在，正在删除..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# 创建任务动作
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`" 2>&1 | Out-File -Append -FilePath `"$logPath`" -Encoding utf8"

# 创建触发器 - 每分钟运行一次
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)

# 创建任务设置
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

# 创建任务对象
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings

# 注册任务 (使用当前用户)
Register-ScheduledTask -TaskName $taskName -InputObject $task -User $env:USERNAME -RunLevel Highest

Write-Host "任务 '$taskName' 创建成功！" -ForegroundColor Green
Write-Host "运行频率: 每分钟" -ForegroundColor Cyan
Write-Host "日志位置: $logPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "管理命令:" -ForegroundColor Yellow
Write-Host "  查看任务: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "  立即运行: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  停止任务: Stop-ScheduledTask -TaskName '$taskName'"
Write-Host "  删除任务: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
