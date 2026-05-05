# scripts/active/ — 生产脚本（当前使用中）

**所有修改必须经过回测验证，严禁跳过回测直接实盘。**

| 脚本 | 版本 | 用途 | 被谁调用 |
|------|------|------|----------|
| signal_fetch_once.py | v3.3 (onchainos+soldRatio) | 信号采集（onchainos 主源 + Binance 辅助） | SmartMoneySignals → run_signals.ps1 |
| api_health_check.py | v1 | API 连通性健康检查 | SmartMoneyHealth → run_health.ps1 |
| monitor_positions.py | v3.2 | 持仓 P&L 监控 + SL/TP 执行 | MonitorPositions → run_monitor.ps1 |
| execute_bsc.py | v3.2 (风控+trailing) | BSC 链交易执行（BAW CLI） | scalper_orchestrator.py |
| execute_solana.py | v3.2 (风控+trailing) | Solana 链交易执行（onchainos） | scalper_orchestrator.py |
| scalper_orchestrator.py | v1 | 编排器：调度 BSC + Solana 执行 | SmartMoneyUnified (禁用) |
| safety_check.py | v1 (空值bug未修) | 买入前 5 维安全评分 | execute_bsc/solana |
| backtest_analysis.py | v2 | 回测分析（soldRatio+tracker 盈亏） | 手动运行 |
| realtime_sm_monitor.py | v2 (tracker 差分) | 聪明钱实时跟单（实验性） | 手动运行 |

## 修改规则
1. **先复制到 active/ 修改**，测试通过后替换
2. **保留旧版本**到 deprecated/，命名 `{name}_v{N}.py`
3. **每次修改记录**到 `data/version-log.md`，包含：日期、改了什么、为什么改、测试结果
4. **回测必须跑通**才能替换生产文件
