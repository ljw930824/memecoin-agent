# Memecoin Agent

Solana + BSC 链智能跟单系统 — 基于链上 Smart Money 信号的自动化交易框架。

## 核心功能

- **Smart Money 跟踪** — 通过 onchainos tracker 实时监控高胜率钱包活动
- **安全评分开仓** — 买入前 5 维评估（蜜罐/税率/冲击/流动性/持币集中度）
- **阶梯止盈** — +30% 卖 77% 回本 / +100% 卖 50% 收利润 / +300% 卖 50% 博大奖
- **多维风控** — 止损 -8%、soldRatio 跟卖、时间加权止损（6h/12h/24h/48h）
- **双链支持** — Solana (onchainos) + BSC (BAW CLI)
- **交易历史** — 完整记录每笔买入到卖出的 PnL、持有时间、出场原因

## 架构

```
onchainos tracker (REST, 10s 轮询)
    ↓
realtime_sm_monitor.py ← 主循环
    ├── 安全检查: safety_check.py (5 维评分, score≥40 开仓)
    ├── 买入: onchainos buy / BAW CLI market-order swap
    ├── 持仓监控: 价格轮询 + soldRatio 过滤
    ├── 卖出: 阶梯止盈 / 跟卖 / SL / 时间加权
    └── 状态: sm_monitor_state.json (持仓 + 交易历史)
```

## 目录结构

```
.
├── scripts/
│   ├── active/                  # 生产脚本（当前使用中）
│   │   ├── realtime_sm_monitor.py   # 主监控脚本 (v3.3)
│   │   ├── safety_check.py          # 5 维安全评分
│   │   ├── execute_solana.py        # Solana 链交易执行
│   │   ├── execute_bsc.py           # BSC 链交易执行
│   │   ├── monitor_positions.py     # 持仓 P&L 监控
│   │   ├── signal_fetch_once.py     # 信号采集
│   │   ├── scalper_orchestrator.py  # 编排器
│   │   └── api_health_check.py      # API 健康检查
│   ├── simulation/              # 模拟盘脚本
│   │   └── sm_monitor_sim.py        # 模拟跟单 (DRY_RUN=True)
│   ├── archive/                 # 临时调试脚本
│   ├── deprecated/              # 已弃用脚本（历史存档）
│   ├── launchers/               # PowerShell 启动器备份
│   └── run_*.ps1                # Task Scheduler 入口
├── data/
│   ├── sm_monitor_state.json       # 实盘状态（持仓+交易历史）
│   ├── sm_monitor_state_dryrun.json # 模拟盘状态
│   ├── signal-queue.json            # 信号队列
│   └── trend-file.json              # 趋势数据
├── job_scraper/                 # 智能求职匹配系统（独立项目）
├── AGENTS.md                    # Agent 行为规则
├── MEMORY.md                    # 长期记忆
├── SOUL.md                      # Agent 人设
├── TOOLS.md                     # 工具笔记
├── COMMIT_GUIDE.md              # Commit 规范
└── .gitignore                   # 排除 data/ memory/ sessions/
```

## 入场策略

### 信号来源
- onchainos REST tracker activities（10s 轮询，每次 50-100 笔）
- 筛选条件：≥2 个高胜率钱包（wr≥50%）买入同一 token
- 市值门槛：mcap ≥ $10K
- 抛压过滤：soldRatio < 30%

### 安全检查（safety_check.py）
开仓前 5 维评分（满分 100），score ≥ 40 才允许开仓，≥ 60 优先：

| 维度 | 权重 | 说明 |
|------|------|------|
| 蜜罐检测 | 30 | 是蜜罐直接拒绝 |
| 税率检查 | 15 | buy+sell tax ≤ 5% 满分 |
| 价格冲击 | 15 | impact ≤ 2% 满分 |
| 流动性深度 | 25 | > $50K 满分，< $1K 拒绝 |
| 持币集中度 | 15 | top10 ≤ 50% 满分 |

## 出场策略

### 阶梯止盈
| 触发条件 | 操作 | 目的 |
|----------|------|------|
| +30% | 卖 77% | 回本，剩 23% 免费持仓 |
| +100% | 再卖 50% | 收利润 |
| +300% | 再卖 50% | 博大奖 |

### soldRatio 跟卖
| soldRatio | 操作 |
|-----------|------|
| ≥ 50% | 全仓卖出 |
| ≥ 30% | 卖 50% |

### 时间加权止损
| 持仓时间 | 最大容忍亏损 |
|----------|-------------|
| 6h | -5% |
| 12h | -3% |
| 24h | 保本 |
| 48h | 强制平仓 |

### 其他触发
- SL：-8% 止损
- SM 跟卖：≥ 3 笔高胜率钱包卖出 → 跟卖

## 风控规则

- **单笔金额**：$5
- **最大持仓**：3 个 token 同时
- **日亏上限**：-15% 暂停当日交易
- **连续止损**：3 次 SL 冻结 2 小时
- **链范围**：Solana + BSC

## 快速开始

### 环境要求
- Python 3.10+
- onchainos CLI（`~/.local/bin/onchainos.exe`）
- BAW CLI（`baw` 命令）
- Windows Task Scheduler

### 运行实盘监控
```powershell
python scripts/active/realtime_sm_monitor.py
```

### 运行模拟盘
```powershell
python scripts/simulation/sm_monitor_sim.py
```

### 带参数运行
```bash
# 单次执行（不循环）
python scripts/active/realtime_sm_monitor.py --once
```

### Task Scheduler 启动
```powershell
# 启动所有监控任务
.\scripts\run_monitor.ps1
.\scripts\run_signals.ps1
.\scripts\run_health.ps1
```

## 配置

主要配置在脚本顶部常量区：
```python
DRY_RUN = False          # True = 模拟盘
WALLET = 'xxx'           # 钱包地址
SINGLE_BUY = 5.0         # 单笔买入金额 (USD)
MAX_POSITIONS = 3        # 最大同时持仓
STOP_LOSS_PCT = -0.08    # 止损 -8%
LADDER_TP = [0.30, 1.00, 3.00]  # 阶梯止盈触发点
LADDER_RATIOS = [0.77, 0.50, 0.50]  # 阶梯卖出比例
```

## 数据文件

| 文件 | 说明 |
|------|------|
| `data/sm_monitor_state.json` | 实盘持仓状态 + 交易历史 |
| `data/sm_monitor_state_dryrun.json` | 模拟盘状态 |
| `data/signal-queue.json` | 信号队列 |
| `data/trend-file.json` | 趋势数据 |

交易历史记录字段：symbol, entry_time, exit_time, entry_price, exit_price, pnl_pct, hold_hours, reason

## Issue & 版本管理

- GitHub: https://github.com/ljw930824/memecoin-agent
- Commit 规范: 见 [COMMIT_GUIDE.md](COMMIT_GUIDE.md)
- Issue 列表: https://github.com/ljw930824/memecoin-agent/issues

## 安全注意

- API Key / Token / Secret **绝不**存储在代码或 commit 中
- 凭证通过环境变量或本地 `~/.qclaw/openclaw.json` 配置
- `.gitignore` 已排除 `data/`、`memory/`、`sessions/` 等敏感目录

## License

Private
