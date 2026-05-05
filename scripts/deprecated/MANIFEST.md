# scripts/deprecated/ — 已弃用脚本（历史存档）

**禁止从这里复制脚本回 active/。如需恢复，先回测验证。**

| 脚本 | 弃用原因 | 弃用日期 |
|------|----------|----------|
| scalper_v2.py | 被 v3.2 替代 | 2026-04-28 |
| scalper_v3.py | 被 v3.2 替代 | 2026-04-28 |
| scalper_v3.1.py | 被 v3.2 替代 | 2026-05-01 |
| scalper_v3.2.py | 自包含方案被放弃，改用 orchestrator 方案 | 2026-05-02 |
| scalper_freq.py | 功能合入 scalper_orchestrator | 2026-05-01 |
| scalper_positions.py | 功能合入 monitor_positions | 2026-05-01 |
| scalper_signals.py | 功能合入 signal_fetch_once | 2026-05-01 |
| signal_listener.py | v2 评分过旧，signal list 数据源延迟严重（100% sold>90%） | 2026-05-02 |
| paper_trading.py | 被 backtest_analysis.py 替代 | 2026-05-01 |
| paper_backtest.py | 临时测试，已完成使命 | 2026-05-02 |
| scan_both_chains.py | 功能合入 signal_fetch_once | 2026-05-01 |
| scan_signals_minute.py | 功能合入 signal_fetch_once | 2026-05-02 |
| smart_money_monitor.py | 被 realtime_sm_monitor.py 替代 | 2026-05-02 |
| diver_monitor.py | Diver 项目暂停 | 2026-05-02 |
| backtest_report.py | 被 backtest_analysis.py 替代 | 2026-05-02 |
| patch_*.py / rewrite_positions.py | 一次性修改，已完成 | 2026-05-02 |
| close_babyasteroid.py | 一次性平仓 | 2026-04-28 |
| fix_queue*.py / check_queue.py | 一次性修复 | 2026-05-02 |
| debug_balance*.py | 调试完成 | 2026-05-01 |
| square_heat.py | 临时脚本 | 2026-05-02 |
| SCRIPTS.md | 被 MANIFEST 体系替代 | 2026-05-02 |
