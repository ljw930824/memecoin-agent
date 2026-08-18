# scripts/active/ — 主链脚本

**所有修改必须经过回测验证，严禁跳过回测直接实盘。**

| 脚本 | 版本 | 用途 | 被谁调用 |
|------|------|------|----------|
| qclaw_trading_common.py | v1 | 链字段契约、原子 JSON、文件锁、OKX/TG 环境、动态风控辅助 | 被各 active 脚本 import |
| signal_fetch_once.py | v3.4 (list+tracker+CT_*) | 信号采集：onchainos list + tracker BUY 合并 + 规范 chain 字段 | SmartMoneySignals → run_signals.ps1 |
| api_health_check.py | v2 | API + tracker + 队列新鲜度 + 连续失败 Telegram 升级 | SmartMoneyHealth → run_health.ps1 |
| monitor_positions.py | v3.3 | 持仓监控（锁态读写、Solana 链匹配、部分止盈后 invest 同步） | MonitorPositions → run_monitor.ps1 |
| execute_bsc.py | v3.3 | BSC 执行（sold_ratio 修复、动态 SL/TP、队列刷新 soldRatio、锁态 state） | scalper_orchestrator.py |
| execute_solana.py | v3.3 | Solana 执行（链匹配 CT_501/solana、动态风险档位、锁态 state） | scalper_orchestrator.py |
| scalper_orchestrator.py | v1.1 | 旧队列执行编排器 | 兼容保留（不与主链并行） |
| safety_check.py | v1.2 | 买入前安全检查（蜜罐降权非硬拒绝、OKX 无硬编码、quote JSON 宽松解析、流动性 NaN 防护） | execute_bsc/solana |
| realtime_sm_monitor.py | v3.5-fast | WS 信号 + 持仓价格事件驱动跟单；默认 +10% 全仓退出 | 主入口 |
| ../tests/test_active_pipeline.py | v2 | WS 字段、价格订阅、时间、快速退出和路径离线测试 | `python -m unittest discover -s tests -v` |

## 修改规则
1. **先复制到 active/ 修改**，离线测试通过后替换
2. **保留旧版本**到 deprecated/，命名 `{name}_v{N}.py`
3. **每次修改记录**到 `data/version-log.md`，包含：日期、改了什么、为什么改、测试结果
4. 当前仓库没有可执行的历史回测模块；上线前仍必须补做历史回测、模拟盘和小额实盘验证，不能把本次离线测试当作交易有效性证明
