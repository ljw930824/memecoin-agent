# 当前项目与关注

## 活跃策略（V3.2）
- `realtime_sm_monitor.py` — 运行中，Solana 实盘
- `safety_check.py` — 五维安全检查
- `watchdog.ps1` — 10s 循环守护
- Task Scheduler: `SMMonitorWatchdog` 1min 兜底

## 近期重要修复
- [2026-05-21] reconcile 幽灵仓位卖出逻辑
- [2026-05-21] Watchdog 升级 2min→10s 循环 + Task Scheduler 精简
- [2026-05-18] swap 参数修复（slippage→max-auto-slippage 25）
- [2026-05-18] calc_buy_size 余额上限约束

## 已知问题
- BUY 成功率仅 20%（SOL rent 不足 / InstructionError）
- 幽灵仓位 sell spam 已修复，待验证
- BSC 链无活跃交易（BAW CLI 需要登录认证）
- OnChainOS v2.5.0，升级 v3.3.3 持续失败（checksum mismatch）

## 待办
- [ ] 提高 BUY 成功率：预检 SOL 余额、失败 cooldown
- [ ] safety_check fallback_l2 从 42 降到 35
- [ ] 策略回测：验证入场/出场参数
- [ ] BSC 复活：解决 BAW 登录问题
- [ ] 升级 OnChainOS CLI
