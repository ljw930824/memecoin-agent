# 启动说明：模拟盘监控进程

> 适用版本：v3.4 + ws_price + ws_instant_sl + pnl_fix + is_alive 修复
> 生成时间：2026-08-17

---

## 一、首次启动流程

### 1. 环境检查

```powershell
# 检查 Python 版本（需 3.8+）
python --version

# 检查工作目录
cd C:\Users\dell\Documents\handoff_20260817
Get-Location

# 检查依赖（理论上无第三方依赖）
python -c "import requests, websockets, json; print('OK')"
```

### 2. 验证关键文件存在

```powershell
# 核心脚本
Test-Path scripts\active\realtime_sm_monitor.py
Test-Path scripts\active\okx_dex_ws.py
Test-Path scripts\active\safety_check.py

# 数据文件
Test-Path data\sm_wallets.json
Test-Path data\sm_monitor_state_dryrun.json
```

### 3. 清理旧状态（如果需要全新启动）

```powershell
# 先确保没有进程在跑
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
  $_.CommandLine -like "*realtime_sm_monitor*"
} | Stop-Process -Force

# 删除旧状态文件
Remove-Item data\sm_monitor_state_dryrun.json -ErrorAction SilentlyContinue

# 备份旧日志（可选）
Rename-Item data\sm_trade-log_dryrun.txt data\sm_trade-log_dryrun_$(Get-Date -Format 'yyyyMMdd').txt -ErrorAction SilentlyContinue
```

---

## 二、启动监控进程

### 方式 A：手动启动（推荐用于调试）

```powershell
cd C:\Users\dell\Documents\handoff_20260817
$env:PYTHONUNBUFFERED='1'
python -u scripts\active\realtime_sm_monitor.py --dry-run 2>&1
```

**参数说明**：
- `--dry-run`：明确启用模拟盘
- WebSocket 有事件时立即唤醒；无事件时最多等待 10 秒走 REST 兜底
- `--live`：明确启用实盘，必须先完成模拟验证
- `-u`：无缓冲输出（重要，日志能实时显示）

### 方式 B：后台启动（生产用）

```powershell
$proc = Start-Process -FilePath 'python' `
  -ArgumentList '-u', 'scripts\active\realtime_sm_monitor.py', '--dry-run' `
  -WindowStyle Hidden `
  -WorkingDirectory 'C:\Users\dell\Documents\handoff_20260817' `
  -PassThru

$proc.Id | Out-File -FilePath 'temp\monitor_pid.txt' -Encoding utf8
Write-Host "Started PID $($proc.Id)"
```

### 方式 C：启用 Watchdog 保活

```powershell
# 启动监控
Start-Process -FilePath 'python' -ArgumentList ... -WindowStyle Hidden -PassThru

# 启动 watchdog（每 60s 检查，2 分钟未更新则重启）
Start-Process -FilePath 'powershell' `
  -ArgumentList '-WindowStyle', 'Hidden', '-File', 'scripts\active\watchdog.ps1' `
  -PassThru
```

---

## 三、状态监控

### 实时日志查看

```powershell
# 最近 50 行
Get-Content data\sm_trade-log_dryrun.txt -Tail 50

# 实时跟踪
Get-Content data\sm_trade-log_dryrun.txt -Wait -Tail 20
```

### 状态快照

```powershell
python -c "import json; s = json.load(open('data\sm_monitor_state_dryrun.json','r',encoding='utf-8')); print('positions:', len(s.get('positions',{})), 'trade_history:', len(s.get('trade_history',[])), 'daily_pnl:', s.get('daily_pnl',0))"
```

### 进程状态

```powershell
Get-Process -Name python | Where-Object {
  $_.CommandLine -like "*realtime_sm_monitor*"
} | Select-Object Id, StartTime, CPU, WS
```

---

## 四、关键日志模式识别

### 正常信号流程
```
[时间] New trades: N across M tokens
[时间] SKIP Token: mcap=$X < $30,000      ← 市值过滤
[时间] SKIP Token: stale signal (Ns old)   ← 旧信号过滤
[时间] SKIP Token: all buy wallets low winrate  ← 钱包过滤
[时间] SKIP Token: max positions (3)       ← 满仓拦截
[时间] RISK BLOCK: daily PnL -X% <= -5% limit  ← 风控拦截
[时间] Risk status: OK                     ← 风控正常
[时间] No positions (wallets tracked: N)   ← 空仓扫描
[时间] BUY Token: $X.X at $Y.Y             ← 实际买入（模拟）
[时间] SELL Token: +X% via reason          ← 实际卖出（模拟）
```

### 异常信号
```
'OkxDexWs' object has no attribute 'is_alive'  ← WS 健康检查异常（已修复）
Connection refused / Timeout                   ← 网络问题
trade_history size 不增长                     ← 持久化 bug
buy_signals 堆积 > 50                          ← 队列未清理
```

---

## 五、重启标准流程（重要！）

### 何时需要重启
- 进程僵死（state 文件 2 分钟未更新）
- 风控计算错误（daily_pnl 显示异常）
- 代码更新后
- trade_history 脏数据需要清理

### 重启顺序（必须遵守）
1. **先停进程**
   ```powershell
   Get-Process -Name python | Where-Object {$_.CommandLine -like "*realtime_sm_monitor*"} | Stop-Process -Force
   ```

2. **清状态文件**（可选，新启动时建议清理）
   ```powershell
   Remove-Item data\sm_monitor_state_dryrun.json -Force
   ```

3. **再启动新进程**
   ```powershell
   Start-Process -FilePath 'python' -ArgumentList '-u', 'scripts\active\realtime_sm_monitor.py', '--dry-run' -WindowStyle Hidden -WorkingDirectory 'C:\Users\dell\Documents\handoff_20260817' -PassThru
   ```

4. **等待 12 秒后验证**
   ```powershell
   Start-Sleep -Seconds 12
   Get-Content data\sm_trade-log_dryrun.txt -Tail 20
   ```

**⚠️ 不按顺序的后果**：旧进程会把内存 state 写回文件，导致清理失效。

---

## 六、参数调优参考

### 当前参数（2026-06-15 后）
```python
MIN_MCAP = 30000               # 从 15000 提升
MIN_SAFETY_SCORE = 70          # 从 50 提升
MIN_CONSENSUS_WALLETS = 1      # 从 2 降低
MIN_WALLET_WINRATE = 0.50      # 50%
MIN_SOLD_RATIO = 0.30          # < 30%
STOP_LOSS = -0.08              # -8%
```

### 调优位置
- `scripts/active/realtime_sm_monitor.py` L95-148（参数定义区）
- `scripts/active/safety_check.py` L62（MIN_SAFETY_SCORE）

### 调优后必须验证
```powershell
# 语法检查
python -c "import py_compile; py_compile.compile('scripts/active/realtime_sm_monitor.py', doraise=True)"

# 启动测试（短轮次）
python -u scripts/active/realtime_sm_monitor.py --dry-run --once 2>&1
```

---

## 七、常见问题排查

### Q1：日志显示 "RISK BLOCK"
**原因**：今日 PnL ≤ -5% 触发风控
**排查**：
```python
python -c "import json, time; from datetime import datetime, timezone, timedelta; s=json.load(open('data/sm_monitor_state_dryrun.json','r',encoding='utf-8')); today_start=datetime.now(timezone(timedelta(hours=8))).replace(hour=0,minute=0,second=0,microsecond=0).timestamp(); th=[t for t in s.get('trade_history',[]) if t.get('exit_ts',0)>=today_start]; print('今日平仓:', len(th), 'PnL:', sum(t.get('pnl',0) for t in th))"
```

### Q2：trade_history 不增长
**原因**：持久化 bug 或卖出路径未调 `_save_trade_history()`
**修复**：检查 `realtime_sm_monitor.py` 卖出路径是否调用 `_save_trade_history()` 末尾的 `save_state(state)`

### Q3：进程僵死
**现象**：state 文件 2 分钟未更新
**排查**：看 watchdog 日志 `watchdog.log`，确认是否自动重启

### Q4：BSC 余额查询失败 `NOT_LOGGED_IN`
**原因**：BAW CLI 未登录
**修复**：执行 `baw auth signin --image` 重新扫码

---

## 八、实盘切换（暂不建议）

**前置条件**：
- 账户余额 ≥ $30（避免 $3 仓位占比过高）
- OKX API 凭证已配置
- BAW CLI 已登录
- 至少 7 天模拟盘稳定运行

**切换命令**：
```powershell
python -u scripts\active\realtime_sm_monitor.py --live
```

**⚠️ 警告**：
- 实盘前必须小资金测试
- 监控进程崩溃 = 失去风控保护
- 建议保留模拟盘 30 天，验证策略稳定性

---

*启动说明版本: v1.0 | 生成于 2026-08-17*
