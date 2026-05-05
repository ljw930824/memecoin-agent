# 交易系统脚本清单 (v3.2)

> 最后更新: 2026-05-02 09:05

## 📌 当前执行链路

```
SmartMoneyUnified (Task Scheduler, 每5分钟)
  └→ run_scalper.ps1
       └→ scalper_orchestrator.py
            ├→ execute_bsc.py      (读 signal-queue.json, 执行 BSC 交易)
            └→ execute_solana.py   (读 signal-queue.json, 执行 Solana 交易)

⚠️ 信号队列 (signal-queue.json) 无生产者！
   - signal_listener.py → 禁用
   - scan_signals_minute.py → 禁用
   - scalper_v3.2.py → 未被调用
   → 结论: execute_bsc/execute_solana 每次跑都是空队列，不产生交易
```

## 🟢 生产脚本（在用）

| 脚本 | 大小 | 功能 | 调用者 |
|------|------|------|--------|
| `run_scalper.ps1` | PS wrapper | 启动 orchestrator | SmartMoneyUnified |
| `scalper_orchestrator.py` | 1KB | 编排器，依次执行 BSC + Solana | run_scalper.ps1 |
| `execute_bsc.py` | 36KB | BSC 链交易执行（baw CLI） | orchestrator |
| `execute_solana.py` | 27KB | Solana 链交易执行（onchainos） | orchestrator |

## 🟡 待启用脚本

| 脚本 | 大小 | 功能 | 状态 | 问题 |
|------|------|------|------|------|
| `scalper_v3.2.py` | 68KB | 完整交易系统（扫描+评分+风控+交易） | **未被调用** | 包含所有 v3.2 增强但不在执行链路 |
| `signal_listener.py` | 20KB | 信号监听 → 写入 signal-queue.json | Task禁用 | 信号源缺失 |
| `scan_signals_minute.py` | 4KB | 1分钟高频信号扫描 | Task禁用 | 依赖 paper_trading_v2.py（缺失） |
| `monitor_positions.py` | 13KB | Solana 持仓 60s 高频监控 | Task禁用 | 独立监控脚本 |
| `safety_check.py` | 15KB | 买入前 5 维安全评分 | 模块，被其他脚本导入 | 可独立运行 |

## ⚫ 历史版本（已淘汰）

| 脚本 | 大小 | 说明 |
|------|------|------|
| `scalper_v3.1.py` | 44KB | v3.1，被 v3.2 替代 |
| `scalper_v3.py` | 41KB | v3.0，被 v3.1 替代 |
| `scalper_v2.py` | 26KB | v2.0，已淘汰 |
| `smart_money_monitor.py` | 23KB | 初代监控，已淘汰 |
| `scalper_signals.py` | 12KB | 旧版信号处理 |
| `scalper_positions.py` | 14KB | 旧版持仓管理 |
| `scalper_freq.py` | 5KB | 旧版频率控制 |
| `scan_both_chains.py` | 20KB | 旧版双链扫描 |

## 🔧 工具/调试脚本

| 脚本 | 功能 |
|------|------|
| `paper_trading.py` | 纸面交易模拟 |
| `backtest_report.py` | 回测报告生成 |
| `diver_monitor.py` | 背离监控（已禁用） |
| `debug_bal*.py` | 余额调试 |
| `_debug_api*.py` | API 调试 |
| `fix_queue*.py` | 队列修复工具 |
| `patch_*.py` | 各种补丁脚本 |
| `_*.py` | 临时测试脚本 |

## 📋 Task Scheduler 任务

| 任务名 | 状态 | 频率 | 执行脚本 |
|--------|------|------|---------|
| SmartMoneyUnified | ✅ 启用 | 每5分钟 | run_scalper.ps1 |
| SmartMoneySignals | ❌ 禁用 | 每1分钟 | run_unified.ps1 |
| SmartMoneyMonitor | ❌ 禁用 | 每1分钟 | monitor_positions.py |
| MonitorPositions | ❌ 禁用 | 每1分钟 | run_monitor.ps1 |
| DiverMonitor | ❌ 禁用 | N/A | diver_monitor.py |

## ⚠️ 已知问题

1. **执行链路断裂**: orchestrator 调用 execute_bsc/solana，但信号队列无生产者 → 空跑
2. **scalper_v3.2.py 未使用**: 最完整的脚本（扫描+评分+风控+交易），但独立于 orchestrator
3. **paper_trading_v2.py 缺失**: scan_signals_minute.py 导入会失败
4. **run_unified.ps1 内容为空**: SmartMoneySignals 任务没有实际执行内容
