# scripts/ — 加密货币聪明钱跟单系统

## 目录结构

```
scripts/
├── active/          # 生产脚本（Task Scheduler 调用）
│   └── MANIFEST.md  # 版本清单 + 修改规则
├── deprecated/      # 已弃用脚本（历史存档）
│   └── MANIFEST.md  # 弃用原因清单
├── archive/         # 临时调试脚本（下划线开头）
│   └── MANIFEST.md  # 调试脚本清单
├── launchers/       # PS1 启动器备份
│   └── *.ps1
├── run_signals.ps1  # Task Scheduler 入口 → active/signal_fetch_once.py
├── run_health.ps1   # Task Scheduler 入口 → active/api_health_check.py
├── run_scalper.ps1  # Task Scheduler 入口 → active/scalper_orchestrator.py
└── run_monitor.ps1  # Task Scheduler 入口 → active/monitor_positions.py
```

## 架构概述

```
信号源 (onchainos signal list + tracker)
    ↓
signal_fetch_once.py (每1分钟, SmartMoneySignals)
    ↓
data/signal-queue.json
    ↓
scalper_orchestrator.py (禁用)
    ├── execute_bsc.py (BAW CLI)
    └── execute_solana.py (onchainos)

monitor_positions.py (每1分钟, MonitorPositions)
    ↓
持仓 SL/TP/信号衰减监控

api_health_check.py (每5分钟, SmartMoneyHealth)
    ↓
API 连通性检测
```

## 版本管理
- **修改规则**: 见 active/MANIFEST.md
- **迭代记录**: 见 data/version-log.md
- **回测报告**: 见 data/backtest_report.md
