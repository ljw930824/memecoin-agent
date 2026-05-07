# scripts/active/ — 生产脚本（当前使用中）

**所有修改必须经过回测验证，严禁跳过回测直接实盘。**

| 脚本 | 版本 | 用途 | 被谁调用 |
|------|------|------|----------|
| qclaw_trading_common.py | v1 | 链字段契约、原子 JSON、文件锁、OKX/TG 环境、动态风控辅助 | 被各 active 脚本 import |
| signal_fetch_once.py | v3.4 (list+tracker+CT_*) | 信号采集：onchainos list + tracker BUY 合并 + 规范 chain 字段 | SmartMoneySignals → run_signals.ps1 |
| api_health_check.py | v2 | API + tracker + 队列新鲜度 + 连续失败 Telegram 升级 | SmartMoneyHealth → run_health.ps1 |
| monitor_positions.py | v3.3 | 持仓监控（锁态读写、Solana 链匹配、部分止盈后 invest 同步） | MonitorPositions → run_monitor.ps1 |
| execute_bsc.py | v3.3 | BSC 执行（sold_ratio 修复、动态 SL/TP、队列刷新 soldRatio、锁态 state） | scalper_orchestrator.py |
| execute_solana.py | v3.3 | Solana 执行（链匹配 CT_501/solana、动态风险档位、锁态 state） | scalper_orchestrator.py |
| scalper_orchestrator.py | v1.1 | 编排器：BSC 异常隔离，Solana 仍执行 | SmartMoneyUnified (禁用) |
| safety_check.py | v1.2 | 买入前安全检查（蜜罐降权非硬拒绝、OKX 无硬编码、quote JSON 宽松解析、流动性 NaN 防护） | execute_bsc/solana |
| backtest_analysis.py | v2 | 回测分析（soldRatio+tracker 盈亏） | 手动运行 |
| realtime_sm_monitor.py | v2.1 | 实验跟单（OKX 无硬编码、BSC TP 告警仅失败时） | 手动运行 |
| tests/test_plan_regressions.py | v1 | 契约与动态风控单元测试 | 手动 `python -m unittest` |

## 修改规则
1. **先复制到 active/ 修改**，测试通过后替换
2. **保留旧版本**到 deprecated/，命名 `{name}_v{N}.py`
3. **每次修改记录**到 `data/version-log.md`，包含：日期、改了什么、为什么改、测试结果
4. **回测必须跑通**才能替换生产文件
